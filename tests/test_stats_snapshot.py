from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from ebook_converter_bot.db import curd
from ebook_converter_bot.db.base import Base
from ebook_converter_bot.db.models.analytics import Analytics
from ebook_converter_bot.db.models.chat import Chat
from ebook_converter_bot.db.models.conversion_event import ConversionEvent
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ATTEMPTS = 3
SUCCESSES = 2
SUCCESS_PERCENT = 66.7
AVG_DURATION_MS = 2000


def _configure_test_session(monkeypatch: Any) -> sessionmaker[Session]:
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


def test_record_conversion_event_and_stats_snapshot(monkeypatch: Any) -> None:
    testing_session_local = _configure_test_session(monkeypatch)

    with testing_session_local() as session:
        session.add_all(
            [
                Chat(user_id=1, user_name="one", type=0, usage_times=2),
                Chat(user_id=2, user_name="two", type=0, usage_times=0),
                Chat(user_id=3, user_name="three", type=0, usage_times=10),
                Analytics(format="epub", input_times=3, output_times=0),
                Analytics(format="pdf", input_times=0, output_times=2),
                Analytics(format="kfx", input_times=0, output_times=1),
            ]
        )
        session.commit()

    curd.record_conversion_event(
        ConversionEvent(
            user_id=1,
            input_format="epub",
            output_format="pdf",
            success=True,
            duration_ms=1000,
            input_size_bytes=100,
            output_size_bytes=200,
            backend="calibre",
        )
    )
    curd.record_conversion_event(
        ConversionEvent(
            user_id=1,
            input_format="epub",
            output_format="pdf",
            success=False,
            error_message="boom",
            duration_ms=3000,
            backend="calibre",
        )
    )
    curd.record_conversion_event(
        ConversionEvent(
            user_id=3,
            input_format="epub",
            output_format="kfx",
            success=True,
            duration_ms=2000,
            backend="calibre",
        )
    )

    snapshot = curd.get_stats_snapshot(recent_days=30)

    assert snapshot["users"] == {
        "all": 3,
        "converted": 2,
        "inactive": 1,
        "repeat": 2,
        "power": 1,
        "converted_percent": 66.7,
        "repeat_percent": 100.0,
        "active_7d": 2,
        "active_recent": 2,
    }
    assert snapshot["legacy"] == {"successes": ATTEMPTS, "input_total": ATTEMPTS}
    assert snapshot["recent"]["attempts"] == ATTEMPTS
    assert snapshot["recent"]["successes"] == SUCCESSES
    assert snapshot["recent"]["failures"] == 1
    assert snapshot["recent"]["success_percent"] == SUCCESS_PERCENT
    assert snapshot["recent"]["avg_duration_ms"] == AVG_DURATION_MS
    assert snapshot["recent"]["top_pairs"] == [
        {"input": "epub", "output": "pdf", "count": 2},
        {"input": "epub", "output": "kfx", "count": 1},
    ]
    assert snapshot["recent"]["failed_pairs"] == [{"input": "epub", "output": "pdf", "count": 1}]
    assert snapshot["formats"]["input"] == [{"format": "epub", "count": 3}]
    assert snapshot["formats"]["output"] == [
        {"format": "pdf", "count": 2},
        {"format": "kfx", "count": 1},
    ]


def test_stats_snapshot_empty_database(monkeypatch: Any) -> None:
    _configure_test_session(monkeypatch)

    snapshot = curd.get_stats_snapshot(recent_days=30)

    assert snapshot["users"]["all"] == 0
    assert snapshot["users"]["converted_percent"] == 0.0
    assert snapshot["recent"]["attempts"] == 0
    assert snapshot["recent"]["avg_duration_ms"] is None
    assert snapshot["recent"]["top_pairs"] == []
