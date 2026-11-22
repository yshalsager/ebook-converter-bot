import asyncio

import ebook_converter_bot.utils.telegram as telegram_mod
from ebook_converter_bot.utils.telegram import tg_exceptions_handler
from telethon.errors import FloodWaitError, QueryIdInvalidError, SlowModeWaitError

expected_calls = 2


def test_tg_exceptions_handler_retries_on_slow_mode(monkeypatch) -> None:
    slept: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        slept.append(seconds)

    monkeypatch.setattr(telegram_mod, "sleep", fake_sleep)

    calls = {"n": 0}

    @tg_exceptions_handler
    async def f() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise SlowModeWaitError(None, 3)
        return "ok"

    assert asyncio.run(f()) == "ok"
    assert slept == [3]
    assert calls["n"] == expected_calls


def test_tg_exceptions_handler_retries_on_flood_wait(monkeypatch) -> None:
    slept: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        slept.append(seconds)

    monkeypatch.setattr(telegram_mod, "sleep", fake_sleep)

    calls = {"n": 0}

    @tg_exceptions_handler
    async def f() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise FloodWaitError(None, 5)
        return "ok"

    assert asyncio.run(f()) == "ok"
    assert slept == [5]
    assert calls["n"] == expected_calls


def test_tg_exceptions_handler_ignores_late_callback_answer() -> None:
    @tg_exceptions_handler
    async def f() -> str:
        raise QueryIdInvalidError(None)

    assert asyncio.run(f()) is None
