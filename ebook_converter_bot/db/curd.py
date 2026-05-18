import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any

from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from sqlalchemy.sql.functions import sum as sql_sum

from ebook_converter_bot.db.models.analytics import Analytics
from ebook_converter_bot.db.models.chat import Chat
from ebook_converter_bot.db.models.conversion_event import ConversionEvent
from ebook_converter_bot.db.models.preference import Preference
from ebook_converter_bot.db.models.user_option_default import UserOptionDefault
from ebook_converter_bot.db.session import get_session

LOGGER = logging.getLogger(__name__)
REPEAT_USER_MIN_USAGE = 2
POWER_USER_MIN_USAGE = 10


def with_session(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with get_session() as session:
            return func(*args, session=session, **kwargs)

    return wrapper


@with_session
def generate_analytics_columns(formats: list[str], *, session: Session) -> None:
    existing = {row[0] for row in session.query(Analytics.format).all()}
    missing = [f for f in formats if f not in existing]
    if not missing:
        return
    session.add_all([Analytics(format=i) for i in missing])
    session.commit()


@with_session
def update_format_analytics(file_format: str, output: bool = False, *, session: Session) -> None:
    file_format_analytics: Analytics | None = (
        session.query(Analytics).filter(Analytics.format == file_format).first()
    )
    if not file_format_analytics:
        return
    if output:
        file_format_analytics.output_times += 1
    else:
        file_format_analytics.input_times += 1
    session.commit()


@with_session
def add_chat_to_db(user_id: int, user_name: str, chat_type: int, *, session: Session) -> None:
    if not session.query(Chat).filter(Chat.user_id == user_id).first():
        session.add(Chat(user_id=user_id, user_name=user_name, type=chat_type))
        session.commit()


@with_session
def remove_chat(user_id: int, *, session: Session) -> bool:
    chat = session.query(Chat).filter(Chat.user_id == user_id).first()
    if not chat:
        return False
    session.delete(chat)
    session.commit()
    return True


@with_session
def increment_usage(user_id: int, *, session: Session) -> None:
    chat = session.query(Chat).filter(Chat.user_id == user_id).first()
    if not chat:
        return
    chat.usage_times += 1
    session.commit()


@with_session
def update_language(user_id: int, language: str, *, session: Session) -> None:
    chat: Preference | None = (
        session.query(Preference).filter(Preference.user_id == user_id).first()
    )
    if not chat:
        chat = Preference(user_id=user_id, language=language)
        session.add(chat)
    else:
        chat.language = language
    session.commit()


@with_session
def get_lang(user_id: int, *, session: Session) -> str:
    language: str = (
        session.query(Preference.language).filter(Preference.user_id == user_id).scalar()
    )
    return language or "en"


@with_session
def record_conversion_event(event: ConversionEvent, *, session: Session) -> None:
    if event.error_message:
        event.error_message = event.error_message[:2000]
    session.add(event)
    session.commit()


def _percent(part: int, total: int) -> float:
    return round((part / total) * 100, 1) if total else 0.0


def _format_rows(
    query: Any,
    first_key: str,
    second_key: str | None = None,
) -> list[dict[str, int | str]]:
    if second_key:
        return [
            {first_key: first, second_key: second, "count": count}
            for first, second, count in query.all()
        ]
    return [{first_key: key, "count": count} for key, count in query.all()]


def _conversion_pair_rows(
    session: Session,
    cutoff: datetime,
    top_limit: int,
    *,
    success: bool | None = None,
) -> list[dict[str, int | str]]:
    query = session.query(
        ConversionEvent.input_format,
        ConversionEvent.output_format,
        func.count(ConversionEvent.id).label("count"),
    ).filter(ConversionEvent.created_at >= cutoff)
    if success is not None:
        query = query.filter(ConversionEvent.success.is_(success))
    return _format_rows(
        query.group_by(ConversionEvent.input_format, ConversionEvent.output_format)
        .order_by(desc("count"))
        .limit(top_limit),
        "input",
        "output",
    )


@with_session
def get_stats_snapshot(
    *,
    recent_days: int = 30,
    top_limit: int = 5,
    session: Session,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    recent_cutoff = now - timedelta(days=recent_days)
    week_cutoff = now - timedelta(days=7)
    all_users = session.query(Chat).count()
    converted_users = session.query(Chat).filter(Chat.usage_times > 0).count()
    repeat_users = session.query(Chat).filter(Chat.usage_times >= REPEAT_USER_MIN_USAGE).count()
    power_users = session.query(Chat).filter(Chat.usage_times >= POWER_USER_MIN_USAGE).count()
    legacy_successes = session.query(sql_sum(Analytics.output_times)).scalar() or 0
    legacy_input_total = session.query(sql_sum(Analytics.input_times)).scalar() or 0

    recent_query = session.query(ConversionEvent).filter(
        ConversionEvent.created_at >= recent_cutoff
    )
    recent_attempts = recent_query.count()
    recent_successes = recent_query.filter(ConversionEvent.success.is_(True)).count()
    recent_failures = recent_attempts - recent_successes
    active_query = session.query(func.count(func.distinct(ConversionEvent.user_id)))

    active_7d = active_query.filter(ConversionEvent.created_at >= week_cutoff).scalar() or 0
    active_recent = active_query.filter(ConversionEvent.created_at >= recent_cutoff).scalar() or 0
    avg_duration_ms = (
        session.query(func.avg(ConversionEvent.duration_ms))
        .filter(
            ConversionEvent.created_at >= recent_cutoff,
            ConversionEvent.duration_ms.is_not(None),
        )
        .scalar()
    )
    top_pairs = _conversion_pair_rows(session, recent_cutoff, top_limit)
    failed_pairs = _conversion_pair_rows(session, recent_cutoff, top_limit, success=False)

    output_formats = _format_rows(
        session.query(Analytics.format, Analytics.output_times)
        .filter(Analytics.output_times > 0)
        .order_by(Analytics.output_times.desc())
        .limit(top_limit),
        "format",
    )
    input_formats = _format_rows(
        session.query(Analytics.format, Analytics.input_times)
        .filter(Analytics.input_times > 0)
        .order_by(Analytics.input_times.desc())
        .limit(top_limit),
        "format",
    )

    return {
        "recent_days": recent_days,
        "users": {
            "all": all_users,
            "converted": converted_users,
            "inactive": all_users - converted_users,
            "repeat": repeat_users,
            "power": power_users,
            "converted_percent": _percent(converted_users, all_users),
            "repeat_percent": _percent(repeat_users, converted_users),
            "active_7d": active_7d,
            "active_recent": active_recent,
        },
        "legacy": {
            "successes": legacy_successes,
            "input_total": legacy_input_total,
        },
        "recent": {
            "attempts": recent_attempts,
            "successes": recent_successes,
            "failures": recent_failures,
            "success_percent": _percent(recent_successes, recent_attempts),
            "avg_duration_ms": int(avg_duration_ms) if avg_duration_ms is not None else None,
            "top_pairs": top_pairs,
            "failed_pairs": failed_pairs,
        },
        "formats": {
            "input": input_formats,
            "output": output_formats,
        },
    }


@with_session
def get_all_chats(*, session: Session) -> list[Chat]:
    return session.query(Chat).all()


@with_session
def get_user_option_defaults(user_id: int, *, session: Session) -> dict[str, Any] | None:
    options_json = (
        session.query(UserOptionDefault.options_json)
        .filter(UserOptionDefault.user_id == user_id)
        .scalar()
    )
    if not options_json:
        return None
    try:
        parsed = json.loads(options_json)
    except json.JSONDecodeError:
        LOGGER.warning("Invalid user options JSON for user_id=%s", user_id)
        return None
    if not isinstance(parsed, dict):
        LOGGER.warning("User options JSON must be an object for user_id=%s", user_id)
        return None
    return parsed


@with_session
def upsert_user_option_defaults(user_id: int, options: dict[str, Any], *, session: Session) -> None:
    defaults = session.query(UserOptionDefault).filter(UserOptionDefault.user_id == user_id).first()
    options_json = json.dumps(options, ensure_ascii=False, separators=(",", ":"))
    if defaults is None:
        defaults = UserOptionDefault(user_id=user_id, options_json=options_json)
        session.add(defaults)
    else:
        defaults.options_json = options_json
        defaults.updated_at = datetime.now(UTC)
    session.commit()
