from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from ebook_converter_bot.db import curd
from ebook_converter_bot.db.base import Base
from ebook_converter_bot.db.models.user_option_default import UserOptionDefault
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def _configure_test_session(monkeypatch: Any) -> sessionmaker[Session]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    @contextmanager
    def test_get_session() -> Session:
        session = testing_session_local()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(curd, "get_session", test_get_session)
    return testing_session_local


def test_get_user_option_defaults_returns_none_when_missing(monkeypatch: Any) -> None:
    _configure_test_session(monkeypatch)

    assert curd.get_user_option_defaults(12345) is None


def test_user_option_defaults_upsert_and_roundtrip(monkeypatch: Any) -> None:
    _configure_test_session(monkeypatch)

    original = {
        "force_rtl": True,
        "docx_page_size": "a4",
        "kfx_pages": 0,
        "options_context": "epub",
    }
    curd.upsert_user_option_defaults(7, original)
    loaded = curd.get_user_option_defaults(7)

    assert loaded == original

    updated = {
        "force_rtl": False,
        "docx_page_size": "letter",
        "kfx_pages": None,
        "options_context": "pdf",
    }
    curd.upsert_user_option_defaults(7, updated)
    loaded_updated = curd.get_user_option_defaults(7)

    assert loaded_updated == updated


def test_get_user_option_defaults_ignores_malformed_json(monkeypatch: Any) -> None:
    testing_session_local = _configure_test_session(monkeypatch)

    with testing_session_local() as session:
        session.add(
            UserOptionDefault(
                user_id=88,
                options_json='{"force_rtl": true',
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()

    assert curd.get_user_option_defaults(88) is None


def test_get_user_option_defaults_ignores_non_object_json(monkeypatch: Any) -> None:
    testing_session_local = _configure_test_session(monkeypatch)

    with testing_session_local() as session:
        session.add(
            UserOptionDefault(
                user_id=99,
                options_json='["force_rtl"]',
                updated_at=datetime.now(UTC),
            )
        )
        session.commit()

    assert curd.get_user_option_defaults(99) is None
