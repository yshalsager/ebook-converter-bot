import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from ebook_converter_bot.utils.converter_options import (
    cleanup_expired_requests,
    cleanup_request_files,
)


@pytest.fixture
def converter_module(tmp_path: Path, monkeypatch):
    bot_module = ModuleType("ebook_converter_bot.bot")
    bot_module.BOT = SimpleNamespace(
        on=lambda _: lambda function: function,
        loop=SimpleNamespace(create_task=lambda coroutine: coroutine.close()),
    )
    monkeypatch.setitem(sys.modules, "ebook_converter_bot.bot", bot_module)
    path = Path(__file__).resolve().parents[1] / "ebook_converter_bot" / "modules" / "converter.py"
    spec = importlib.util.spec_from_file_location(
        "ebook_converter_bot.modules._isolation_test", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DOWNLOAD_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(module, "get_lang", lambda _: "en")
    monkeypatch.setattr(module, "get_user_option_defaults", lambda _: None)
    monkeypatch.setattr(module, "record_conversion_event", lambda _: None)
    monkeypatch.setattr(module, "increment_usage", lambda _: None)
    monkeypatch.setattr(module, "update_format_analytics", lambda *args, **kwargs: None)
    yield module
    for state in module.queue.values():
        cleanup_request_files(state)


class UploadEvent:
    def __init__(self, filename: str, content: bytes = b"book", failure: str = ""):
        self.chat_id = self.sender_id = self.chat = 42
        self.pattern_match = None
        self.filename = filename
        self.content = content
        self.failure = failure
        self.directory = None
        self.edits = []
        self.sent = []
        self.answers = []
        self.message = SimpleNamespace(
            file=SimpleNamespace(name=filename, size=len(content)),
            download_media=self.download_media,
        )
        self.client = SimpleNamespace(send_file=self.send_file)

    async def reply(self, *args, **kwargs):
        return self

    async def edit(self, text, **kwargs):
        if self.failure == "reply":
            raise RuntimeError("Message edit failed")
        self.edits.append(text)
        return self

    async def answer(self, text, **kwargs):
        self.answers.append(text)

    async def send_file(self, chat, path, **kwargs):
        self.sent.append(Path(path).read_bytes())

    async def download_media(self, directory):
        self.directory = Path(directory)
        output = self.directory / self.filename
        output.write_bytes(self.content)
        if self.failure == "exception":
            raise RuntimeError("Download failed")
        if self.failure == "cancel":
            raise asyncio.CancelledError
        if self.failure == "none":
            return None
        return str(output)


def test_uploads_with_matching_names_keep_separate_directories(converter_module) -> None:
    module = converter_module

    async def run():
        await module.file_converter.__wrapped__(UploadEvent("book.md", b"User A"))
        await module.file_converter.__wrapped__(UploadEvent("book.epub", b"User B"))

    asyncio.run(run())
    first, second = module.queue.values()
    first_path, second_path = Path(first.input_file_path), Path(second.input_file_path)
    assert first_path.parent != second_path.parent
    assert first_path.read_bytes() == b"User A"
    assert second_path.read_bytes() == b"User B"
    assert first_path.parent.stat().st_mode & 0o077 == 0
    cleanup_request_files(first)
    assert not first_path.parent.exists()
    assert second_path.read_bytes() == b"User B"


@pytest.mark.parametrize("failure", ["none", "exception", "cancel", "reply"])
def test_incomplete_download_removes_private_directory(converter_module, failure: str) -> None:
    event = UploadEvent("book.epub", failure=failure)
    call = converter_module.file_converter.__wrapped__(event)
    if failure == "none":
        asyncio.run(call)
    else:
        expected = asyncio.CancelledError if failure == "cancel" else RuntimeError
        with pytest.raises(expected):
            asyncio.run(call)
    assert not event.directory.exists()
    assert converter_module.queue == {}


def test_late_upload_failure_preserves_reused_request_id(converter_module, monkeypatch) -> None:
    module = converter_module
    request_id = "12345678"
    monkeypatch.setattr(module, "sample", lambda *args: list(request_id))
    first, second = UploadEvent("first.epub"), UploadEvent("second.epub")
    active_states = []

    async def fail_after_handoff(*args, **kwargs):
        active_states.append(module.queue.pop(request_id))
        await module.file_converter.__wrapped__(second)
        raise RuntimeError("Reply failed after delivery")

    monkeypatch.setattr(first, "edit", fail_after_handoff)
    try:
        with pytest.raises(RuntimeError, match="Reply failed after delivery"):
            asyncio.run(module.file_converter.__wrapped__(first))
        assert list(module.queue) == [request_id]
        assert (second.directory / second.filename).read_bytes() == second.content
        assert first.directory.exists()
    finally:
        for state in active_states:
            cleanup_request_files(state)


@pytest.mark.parametrize("backend", ["calibre", "boko", "kfxgen"])
@pytest.mark.parametrize("fails", [False, True])
def test_conversion_cleanup_does_not_touch_another_upload(
    converter_module, monkeypatch, backend: str, fails: bool
) -> None:
    module = converter_module
    first = UploadEvent("book.md", b"User A")
    second = UploadEvent("book.epub", b"User B")

    async def run():
        await module.file_converter.__wrapped__(first)
        await module.file_converter.__wrapped__(second)

    asyncio.run(run())
    request_id, other_id = module.queue
    state = module.queue[request_id]
    if backend == "boko":
        source = Path(state.input_file_path)
        renamed = source.with_suffix(".mobi")
        source.rename(renamed)
        state.input_file_path = str(renamed)
        state.input_ext = "mobi"
    state.conversion_backend = backend
    first.data = f"run|kfx|{request_id}".encode()
    other_source = Path(module.queue[other_id].input_file_path)

    async def fake_run(command, timeout=600):
        if fails:
            return 1, "Conversion failed"
        if command[0] == "ebook-convert":
            Path(command[2]).write_bytes(b"generated")
        elif "boko" in command or command[:2] == ["calibre-debug", "-r"]:
            Path(command[-1]).write_bytes(b"generated")
        return 0, ""

    monkeypatch.setattr(module.converter, "_run_command", fake_run)
    asyncio.run(module.converter_callback.__wrapped__(first))
    assert request_id not in module.queue
    assert not first.directory.exists()
    assert other_source.read_bytes() == b"User B"
    assert first.sent == ([] if fails else [b"generated"])


def test_conversion_status_failure_still_cleans_request(converter_module) -> None:
    event = UploadEvent("book.epub")
    module = converter_module
    asyncio.run(module.file_converter.__wrapped__(event))
    request_id = next(iter(module.queue))
    event.failure = "reply"
    event.data = f"run|epub|{request_id}".encode()
    with pytest.raises(RuntimeError, match="Message edit failed"):
        asyncio.run(module.converter_callback.__wrapped__(event))
    assert not event.directory.exists()
    assert module.queue == {}


@pytest.mark.parametrize("action", ["cancel", "expire", "missing"])
def test_queued_request_cleanup_removes_only_its_directory(converter_module, action: str) -> None:
    module = converter_module
    first, second = UploadEvent("book.md"), UploadEvent("book.epub")

    async def run():
        await module.file_converter.__wrapped__(first)
        await module.file_converter.__wrapped__(second)

    asyncio.run(run())
    request_id, other_id = module.queue
    state = module.queue[request_id]
    other_source = Path(module.queue[other_id].input_file_path)
    (first.directory / "leftover.txt").write_text("temporary output")
    if action == "cancel":
        first.data = f"cancel|{request_id}".encode()
        asyncio.run(module.cancel_conversion_callback.__wrapped__(first))
    elif action == "expire":
        state.queued_at = 0
        cleanup_expired_requests(module.queue, ttl_seconds=60)
    else:
        Path(state.input_file_path).unlink()
        assert asyncio.run(module.get_request_state(first, request_id)) is None
    assert request_id not in module.queue
    assert not first.directory.exists()
    assert other_source.exists()
