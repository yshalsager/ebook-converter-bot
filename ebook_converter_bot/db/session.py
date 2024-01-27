"""Database initialization."""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ebook_converter_bot import PARENT_DIR
from ebook_converter_bot.db.base import Base

module_path = Path(__file__).parent

db_connection_string = f"sqlite:///{PARENT_DIR}/ebook_converter_bot.db"
engine = create_engine(db_connection_string, connect_args={"check_same_thread": False})

Base.metadata.create_all(bind=engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
session = SessionLocal()
