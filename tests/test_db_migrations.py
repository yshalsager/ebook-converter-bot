from pathlib import Path

import pytest
from alembic import command
from ebook_converter_bot.db import (  # noqa: F401
    Analytics,
    Chat,
    ConversionEvent,
    Preference,
    UserOptionDefault,
)
from ebook_converter_bot.db import session as db_session
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError

BASELINE_REVISION = "20260518_0001"
HEAD_REVISION = "20260518_0002"


def _patch_database(monkeypatch, db_path: Path) -> None:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(db_session, "db_connection_string", f"sqlite:///{db_path}")
    monkeypatch.setattr(db_session, "engine", engine)


def test_initialize_database_upgrades_fresh_database(monkeypatch, tmp_path: Path) -> None:
    _patch_database(monkeypatch, tmp_path / "fresh.db")

    db_session.initialize_database()

    inspector = inspect(db_session.engine)
    assert {
        "alembic_version",
        "analytics",
        "chats",
        "conversion_events",
        "preferences",
        "user_option_defaults",
    }.issubset(inspector.get_table_names())
    with db_session.engine.connect() as connection:
        assert (
            connection.execute(text("select version_num from alembic_version")).scalar_one()
            == HEAD_REVISION
        )


def test_initialize_database_upgrades_manually_stamped_baseline_database(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_database(monkeypatch, tmp_path / "existing.db")
    command.upgrade(db_session.get_alembic_config(), BASELINE_REVISION)

    db_session.initialize_database()

    inspector = inspect(db_session.engine)
    assert "conversion_events" in inspector.get_table_names()
    with db_session.engine.connect() as connection:
        assert (
            connection.execute(text("select version_num from alembic_version")).scalar_one()
            == HEAD_REVISION
        )


def test_initialize_database_does_not_auto_stamp_unversioned_existing_database(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_database(monkeypatch, tmp_path / "unversioned.db")
    with db_session.engine.begin() as connection:
        connection.execute(text("create table analytics (id integer primary key)"))

    with pytest.raises(OperationalError, match="already exists"):
        db_session.initialize_database()

    with db_session.engine.connect() as connection:
        assert connection.execute(text("select count(*) from alembic_version")).scalar_one() == 0
