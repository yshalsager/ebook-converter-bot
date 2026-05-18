import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any

from sqlalchemy import func, select
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
    existing = set(session.scalars(select(Analytics.format)).all())
    missing = [f for f in formats if f not in existing]
    if not missing:
        return
    session.add_all([Analytics(format=i) for i in missing])
    session.commit()


@with_session
def update_format_analytics(file_format: str, output: bool = False, *, session: Session) -> None:
    file_format_analytics = session.scalar(select(Analytics).where(Analytics.format == file_format))
    if not file_format_analytics:
        return
    if output:
        file_format_analytics.output_times += 1
    else:
        file_format_analytics.input_times += 1
    session.commit()


@with_session
def add_chat_to_db(user_id: int, user_name: str, chat_type: int, *, session: Session) -> None:
    if not session.scalar(select(Chat).where(Chat.user_id == user_id)):
        session.add(Chat(user_id=user_id, user_name=user_name, type=chat_type))
        session.commit()


@with_session
def remove_chat(user_id: int, *, session: Session) -> bool:
    chat = session.scalar(select(Chat).where(Chat.user_id == user_id))
    if not chat:
        return False
    session.delete(chat)
    session.commit()
    return True


@with_session
def increment_usage(user_id: int, *, session: Session) -> None:
    chat = session.scalar(select(Chat).where(Chat.user_id == user_id))
    if not chat:
        return
    chat.usage_times += 1
    session.commit()


@with_session
def update_language(user_id: int, language: str, *, session: Session) -> None:
    chat = session.scalar(select(Preference).where(Preference.user_id == user_id))
    if not chat:
        chat = Preference(user_id=user_id, language=language)
        session.add(chat)
    else:
        chat.language = language
    session.commit()


@with_session
def get_lang(user_id: int, *, session: Session) -> str:
    language = session.scalar(select(Preference.language).where(Preference.user_id == user_id))
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
    rows: Sequence[Any],
    first_key: str,
    second_key: str | None = None,
) -> list[dict[str, int | str]]:
    if second_key:
        return [
            {first_key: first, second_key: second, "count": count} for first, second, count in rows
        ]
    return [{first_key: key, "count": count} for key, count in rows]


def _conversion_pair_rows(
    session: Session,
    cutoff: datetime,
    top_limit: int,
    *,
    success: bool | None = None,
) -> list[dict[str, int | str]]:
    count = func.count(ConversionEvent.id).label("count")
    stmt = select(
        ConversionEvent.input_format,
        ConversionEvent.output_format,
        count,
    ).where(ConversionEvent.created_at >= cutoff)
    if success is not None:
        stmt = stmt.where(ConversionEvent.success.is_(success))
    return _format_rows(
        session.execute(
            stmt.group_by(ConversionEvent.input_format, ConversionEvent.output_format)
            .order_by(count.desc())
            .limit(top_limit)
        ).all(),
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
    all_users = session.scalar(select(func.count()).select_from(Chat)) or 0
    converted_users = session.scalar(select(func.count()).where(Chat.usage_times > 0)) or 0
    repeat_users = (
        session.scalar(select(func.count()).where(Chat.usage_times >= REPEAT_USER_MIN_USAGE)) or 0
    )
    power_users = (
        session.scalar(select(func.count()).where(Chat.usage_times >= POWER_USER_MIN_USAGE)) or 0
    )
    legacy_successes = session.scalar(select(sql_sum(Analytics.output_times))) or 0
    legacy_input_total = session.scalar(select(sql_sum(Analytics.input_times))) or 0

    recent_attempts = (
        session.scalar(select(func.count()).where(ConversionEvent.created_at >= recent_cutoff)) or 0
    )
    recent_successes = (
        session.scalar(
            select(func.count()).where(
                ConversionEvent.created_at >= recent_cutoff,
                ConversionEvent.success.is_(True),
            )
        )
        or 0
    )
    recent_failures = recent_attempts - recent_successes

    active_7d = (
        session.scalar(
            select(func.count(func.distinct(ConversionEvent.user_id))).where(
                ConversionEvent.created_at >= week_cutoff
            )
        )
        or 0
    )
    active_recent = (
        session.scalar(
            select(func.count(func.distinct(ConversionEvent.user_id))).where(
                ConversionEvent.created_at >= recent_cutoff
            )
        )
        or 0
    )
    avg_duration_ms = session.scalar(
        select(func.avg(ConversionEvent.duration_ms)).where(
            ConversionEvent.created_at >= recent_cutoff,
            ConversionEvent.duration_ms.is_not(None),
        )
    )
    top_pairs = _conversion_pair_rows(session, recent_cutoff, top_limit)
    failed_pairs = _conversion_pair_rows(session, recent_cutoff, top_limit, success=False)

    output_formats = _format_rows(
        session.execute(
            select(Analytics.format, Analytics.output_times)
            .where(Analytics.output_times > 0)
            .order_by(Analytics.output_times.desc())
            .limit(top_limit)
        ).all(),
        "format",
    )
    input_formats = _format_rows(
        session.execute(
            select(Analytics.format, Analytics.input_times)
            .where(Analytics.input_times > 0)
            .order_by(Analytics.input_times.desc())
            .limit(top_limit)
        ).all(),
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
    return list(session.scalars(select(Chat)).all())


@with_session
def get_broadcast_chats(filters: dict[str, Any] | None = None, *, session: Session) -> list[Chat]:
    stmt = select(Chat).order_by(Chat.user_id)
    if filters:
        if filters.get("username_only"):
            stmt = stmt.where(Chat.user_name != "")
        active_after = filters.get("active_after")
        if active_after:
            active_users = select(ConversionEvent.user_id).where(
                ConversionEvent.created_at >= active_after
            )
            stmt = stmt.where(Chat.user_id.in_(active_users))
    return list(session.scalars(stmt).all())


@with_session
def get_user_option_defaults(user_id: int, *, session: Session) -> dict[str, Any] | None:
    options_json = session.scalar(
        select(UserOptionDefault.options_json).where(UserOptionDefault.user_id == user_id)
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
    defaults = session.scalar(select(UserOptionDefault).where(UserOptionDefault.user_id == user_id))
    options_json = json.dumps(options, ensure_ascii=False, separators=(",", ":"))
    if defaults is None:
        defaults = UserOptionDefault(user_id=user_id, options_json=options_json)
        session.add(defaults)
    else:
        defaults.options_json = options_json
        defaults.updated_at = datetime.now(UTC)
    session.commit()
