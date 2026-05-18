"""Database initialization."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ebook_converter_bot import PARENT_DIR

module_path = Path(__file__).parent

db_connection_string = f"sqlite:///{PARENT_DIR}/ebook_converter_bot.db"
engine = create_engine(db_connection_string, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_alembic_config() -> Config:
    config = Config(str(PARENT_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(module_path / "migrations"))
    config.set_main_option("sqlalchemy.url", db_connection_string)
    return config


def initialize_database() -> None:
    command.upgrade(get_alembic_config(), "head")


def get_session() -> Session:
    return SessionLocal()
