from typing import List, Dict

from sqlalchemy.sql.functions import sum

from ebook_converter_bot.db.models.analytics import Analytics
from ebook_converter_bot.db.models.chat import Chat
from ebook_converter_bot.db.models.preference import Preference
from ebook_converter_bot.db.session import session


def generate_analytics_columns(formats: List[str]):
    if not session.query(Analytics).first():
        formats_columns = [Analytics(format=i) for i in formats]
        session.add_all(formats_columns)
        session.commit()


def update_format_analytics(file_format: str, output: bool = False):
    file_format: Analytics = session.query(Analytics).filter(Analytics.format == file_format).first()
    if not file_format:
        return
    if output:
        file_format.output_times += 1
    else:
        file_format.input_times += 1
    session.commit()


def add_chat_to_db(user_id: int, user_name: str, chat_type: int):
    if not session.query(Chat).filter(Chat.user_id == user_id).first():
        session.add(Chat(user_id=user_id, user_name=user_name, type=chat_type))
        session.commit()


def increment_usage(user_id: int):
    chat = session.query(Chat).filter(Chat.user_id == user_id).first()
    if not chat:
        return
    chat.usage_times += 1
    session.commit()


def update_language(user_id: int, language: str):
    chat: Preference = session.query(Preference).filter(Preference.user_id == user_id).first()
    if not chat:
        chat = Preference(user_id=user_id, language=language)
        session.add(chat)
    else:
        chat.language = language
    session.commit()


def get_lang(user_id: int) -> str:
    chat = session.query(Preference.language).filter(Preference.user_id == user_id).first()
    return chat.language if chat else 'en'


def get_chats_count() -> (int, int):
    all_chats = session.query(Chat).count()
    active_chats = session.query(Chat).filter(Chat.usage_times > 0).count()
    return all_chats, active_chats


def get_usage_count() -> (int, int):
    usage_times = session.query(sum(Chat.usage_times).label('usage_times')).first().usage_times
    output_times = session.query(sum(Analytics.output_times).label('output_times')).first().output_times
    return usage_times, output_times


def get_top_formats() -> (Dict[str, int], Dict[str, int]):
    out_formats: List[Analytics] = session.query(Analytics).order_by(Analytics.output_times.desc()).limit(5).all()
    in_formats: List[Analytics] = session.query(Analytics).order_by(Analytics.input_times.desc()).limit(5).all()
    return {i.format: i.output_times for i in out_formats}, {i.format: i.input_times for i in in_formats}
