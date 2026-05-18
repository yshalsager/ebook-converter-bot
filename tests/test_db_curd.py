from collections.abc import Iterator
from contextlib import contextmanager

from ebook_converter_bot.db import curd
from ebook_converter_bot.db.base import Base
from ebook_converter_bot.db.models.analytics import Analytics
from ebook_converter_bot.db.models.chat import Chat
from ebook_converter_bot.db.models.conversion_event import ConversionEvent
from ebook_converter_bot.db.models.preference import Preference
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

LONG_ERROR_LENGTH = 2500
TRUNCATED_ERROR_LENGTH = 2000


def _configure_test_session(monkeypatch) -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    @contextmanager
    def test_get_session() -> Iterator[Session]:
        session = testing_session_local()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(curd, "get_session", test_get_session)
    return testing_session_local


def test_generate_analytics_columns_adds_missing_formats_only(monkeypatch) -> None:
    testing_session_local = _configure_test_session(monkeypatch)

    curd.generate_analytics_columns(["epub", "pdf"])
    curd.generate_analytics_columns(["epub", "kfx"])

    with testing_session_local() as session:
        rows = session.scalars(select(Analytics).order_by(Analytics.format)).all()

    assert [(row.format, row.input_times, row.output_times) for row in rows] == [
        ("epub", 0, 0),
        ("kfx", 0, 0),
        ("pdf", 0, 0),
    ]


def test_update_format_analytics_increments_input_and_output(monkeypatch) -> None:
    testing_session_local = _configure_test_session(monkeypatch)
    curd.generate_analytics_columns(["epub"])

    curd.update_format_analytics("epub")
    curd.update_format_analytics("epub", output=True)
    curd.update_format_analytics("missing")

    with testing_session_local() as session:
        analytics = session.scalar(select(Analytics).where(Analytics.format == "epub"))

    assert analytics is not None
    assert analytics.input_times == 1
    assert analytics.output_times == 1


def test_chat_lifecycle_helpers(monkeypatch) -> None:
    testing_session_local = _configure_test_session(monkeypatch)

    curd.add_chat_to_db(1, "first", 0)
    curd.add_chat_to_db(1, "ignored", 1)
    curd.add_chat_to_db(2, "second", 1)
    curd.increment_usage(1)
    curd.increment_usage(404)

    chats = sorted(curd.get_all_chats(), key=lambda chat: chat.user_id)
    assert [(chat.user_id, chat.user_name, chat.type, chat.usage_times) for chat in chats] == [
        (1, "first", 0, 1),
        (2, "second", 1, 0),
    ]
    assert curd.remove_chat(2) is True
    assert curd.remove_chat(2) is False

    with testing_session_local() as session:
        remaining_user_ids = session.scalars(select(Chat.user_id)).all()

    assert remaining_user_ids == [1]


def test_language_helpers_default_create_and_update(monkeypatch) -> None:
    testing_session_local = _configure_test_session(monkeypatch)

    assert curd.get_lang(1) == "en"
    curd.update_language(1, "ar")
    curd.update_language(1, "en")

    with testing_session_local() as session:
        preferences = session.scalars(select(Preference)).all()

    assert [(preference.user_id, preference.language) for preference in preferences] == [(1, "en")]
    assert curd.get_lang(1) == "en"


def test_record_conversion_event_truncates_error_and_applies_defaults(monkeypatch) -> None:
    testing_session_local = _configure_test_session(monkeypatch)

    curd.record_conversion_event(
        ConversionEvent(
            user_id=1,
            input_format="epub",
            output_format="pdf",
            success=False,
            error_message="x" * LONG_ERROR_LENGTH,
        )
    )

    with testing_session_local() as session:
        event = session.scalar(select(ConversionEvent))

    assert event is not None
    assert len(event.error_message or "") == TRUNCATED_ERROR_LENGTH
    assert event.created_at is not None
    assert event.duration_ms is None
