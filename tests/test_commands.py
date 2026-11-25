# ruff: noqa: PLR2004
import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from telethon.tl import types


@pytest.fixture
def commands(monkeypatch):
    calls = []

    async def bot(request):
        calls.append(request)

    async def get_input_entity(user_id):
        return types.InputPeerUser(user_id, 1)

    bot.on = lambda _: lambda function: function
    bot.get_input_entity = get_input_entity
    bot.loop = SimpleNamespace(create_task=lambda coroutine: coroutine.close())
    module = ModuleType("ebook_converter_bot.bot")
    module.BOT = bot
    monkeypatch.setitem(sys.modules, "ebook_converter_bot.bot", module)
    path = Path(__file__).resolve().parents[1] / "ebook_converter_bot/modules/commands.py"
    spec = importlib.util.spec_from_file_location("_test_commands", path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    monkeypatch.setattr(loaded, "TG_BOT_ADMINS", [999])
    monkeypatch.setattr(loaded, "get_lang", lambda _: "en")
    loaded.calls = calls
    return loaded


def names(request):
    return [command.command for command in request.commands]


def test_sync_sets_language_menus_and_admin_chat(commands) -> None:
    asyncio.run(commands.sync_commands())

    by_scope = {(type(call.scope).__name__, call.lang_code): names(call) for call in commands.calls}
    assert by_scope[("BotCommandScopeUsers", "")] == list(commands.USER_COMMANDS)
    assert by_scope[("BotCommandScopeUsers", "ar")] == list(commands.USER_COMMANDS)
    assert by_scope[("BotCommandScopeChats", "tr")] == ["convert", "help"]
    admin = by_scope[("BotCommandScopePeer", "")]
    assert "grant" in admin
    assert "grant" not in by_scope[("BotCommandScopeUsers", "")]
    assert commands.calls[-1].scope.peer.user_id == 999


def test_user_chat_menu_has_no_admin_commands(commands) -> None:
    asyncio.run(commands.set_chat_commands(5, "ar"))

    (call,) = commands.calls
    assert call.scope.peer.user_id == 5
    assert names(call) == list(commands.USER_COMMANDS)
