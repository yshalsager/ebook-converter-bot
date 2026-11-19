import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from ebook_converter_bot.db.models.chat import Chat


@pytest.fixture
def broadcast(monkeypatch):
    bot = ModuleType("ebook_converter_bot.bot")
    sent: list[int] = []

    async def send_message(chat_id, _message):
        sent.append(chat_id)

    bot.BOT = SimpleNamespace(on=lambda _: lambda function: function, send_message=send_message)
    monkeypatch.setitem(sys.modules, "ebook_converter_bot.bot", bot)
    path = Path(__file__).resolve().parents[1] / "ebook_converter_bot/modules/broadcast.py"
    spec = importlib.util.spec_from_file_location("_test_broadcast", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_lang", lambda _chat_id: "en")
    monkeypatch.setattr(module, "get_broadcast_chats", lambda _filters: [Chat(user_id=1, type=0)])
    monkeypatch.setattr(module, "mark_chat_unreachable", lambda _chat_id: None)
    module.sent = sent
    return module


class Event:
    chat_id = 999

    def __init__(self, text: str) -> None:
        self.message = SimpleNamespace(message=text)
        self.replies: list[str] = []

    async def reply(self, text: str):
        self.replies.append(text)
        return SimpleNamespace(edit=self.reply)

    async def get_reply_message(self):
        return "announcement"


def test_broadcast_without_confirm_is_a_dry_run(broadcast) -> None:
    event = Event("/broadcast\nprivate_only")
    asyncio.run(broadcast.broadcast_handler(event))

    assert broadcast.sent == []
    assert event.replies[0].startswith("Dry run: would send to 1 chats")


def test_broadcast_with_confirm_sends(broadcast) -> None:
    event = Event("/broadcast\nprivate_only\nconfirm")
    asyncio.run(broadcast.broadcast_handler(event))

    assert broadcast.sent == [1]
