import asyncio
from types import SimpleNamespace

import pytest
from ebook_converter_bot.utils import convert as convert_utils
from ebook_converter_bot.utils import converter_options

from tests.test_request_isolation import UploadEvent

pytest_plugins = ["tests.test_request_isolation"]


async def prepare_request(module, event):
    await module.file_converter.__wrapped__(event)
    request_id = next(reversed(module.queue))
    event.data = f"run|epub|{request_id}".encode()
    return request_id


def test_active_chat_rejection_preserves_request(converter_module):
    module = converter_module
    event = UploadEvent("book.md")

    async def run():
        request_id = await prepare_request(module, event)
        module.active_users.add(event.chat_id)
        await module.converter_callback.__wrapped__(event)
        assert request_id in module.queue
        assert event.answers == ["Wait for your current conversion to finish."]

    asyncio.run(run())


def test_concurrent_chat_admission_after_request_lookup(converter_module, monkeypatch):
    module = converter_module
    first, second = UploadEvent("first.md"), UploadEvent("second.md")
    get_request_state = module.get_request_state

    async def delayed_lookup(*args, **kwargs):
        await asyncio.sleep(0)
        return await get_request_state(*args, **kwargs)

    async def convert(*args, **kwargs):
        await asyncio.sleep(0)
        return SimpleNamespace(
            backend="calibre", output_files=[], split_capped=False, conversion_error="Failed"
        )

    monkeypatch.setattr(module, "get_request_state", delayed_lookup)
    monkeypatch.setattr(module.converter, "convert_ebook_many", convert)

    async def run():
        await prepare_request(module, first)
        second_id = await prepare_request(module, second)
        await asyncio.gather(
            module.converter_callback.__wrapped__(first),
            module.converter_callback.__wrapped__(second),
        )
        assert second.answers == ["Wait for your current conversion to finish."]
        assert second_id in module.queue
        assert not module.active_users

    asyncio.run(run())


def test_route_cooldown_and_expiry(converter_module, monkeypatch):
    module = converter_module
    now = 10000.0
    monkeypatch.setattr(module, "monotonic", lambda: now)
    monkeypatch.setattr(converter_options, "monotonic", lambda: now)

    async def timeout_conversion(*args, **kwargs):
        return SimpleNamespace(
            backend="calibre",
            output_files=[],
            split_capped=False,
            conversion_error="Timeout while running command: ebook-convert",
        )

    monkeypatch.setattr(module.converter, "convert_ebook_many", timeout_conversion)

    async def run():
        nonlocal now
        for _ in range(2):
            event = UploadEvent("book.md")
            await prepare_request(module, event)
            await module.converter_callback.__wrapped__(event)
            now += 60
        event = UploadEvent("book.md")
        request_id = await prepare_request(module, event)
        await module.converter_callback.__wrapped__(event)
        assert event.answers == ["This route timed out twice. Retry in 58 minutes."]
        assert request_id in module.queue
        assert module.recent_route_timeouts((43, "md", "epub")) == []
        now += 3480
        module.queue[request_id].queued_at = now
        assert len(module.recent_route_timeouts((42, "md", "epub"))) == 1
        await module.converter_callback.__wrapped__(event)
        assert request_id not in module.queue
        assert not module.active_users
        now += 3600
        assert module.recent_route_timeouts((42, "md", "epub")) == []
        assert module.route_timeouts == {}

    asyncio.run(run())


@pytest.mark.parametrize("admin", [False, True])
def test_deadline_records_failure_and_admin_exemption(converter_module, monkeypatch, admin):
    module = converter_module
    event = UploadEvent("book.md")
    recorded = []
    monkeypatch.setattr(module, "JOB_TIMEOUT_SECONDS", 0)
    monkeypatch.setattr(module, "record_conversion_event", recorded.append)
    monkeypatch.setattr(module, "get_lang", lambda _: "ar")
    monkeypatch.setattr(module, "_", lambda text, lang: f"{lang}:{text}")
    if admin:
        module.BOT_ADMIN_IDS.add(event.sender_id)
        module.active_users.add(event.chat_id)
        module.route_timeouts[(42, "md", "epub")] = [module.monotonic()] * 2

    async def convert(input_file, output_type, **kwargs):
        assert kwargs["timeout"] == (None if admin else module.TASK_TIMEOUT)
        await asyncio.sleep(0)
        output = input_file.with_suffix(".epub")
        output.write_bytes(b"converted")
        return SimpleNamespace(
            backend="calibre",
            output_files=[output],
            split_capped=False,
            conversion_error=None,
            converted_to_rtl=False,
        )

    monkeypatch.setattr(module.converter, "convert_ebook_many", convert)

    async def run():
        await prepare_request(module, event)
        await module.converter_callback.__wrapped__(event)

    asyncio.run(run())
    assert recorded[0].success is admin
    if not admin:
        assert recorded[0].error_message == module.JOB_TIMEOUT_ERROR
        assert module.JOB_TIMEOUT_ERROR == "Timeout: whole conversion exceeded 20 minutes"
        assert len(module.route_timeouts[(42, "md", "epub")]) == 1
        assert not module.active_users
    assert module.conversion_slots._value == module.MAX_CONCURRENT_CONVERSIONS


def test_global_slots_release_before_delivery(converter_module, monkeypatch):
    module = converter_module
    module.conversion_slots = asyncio.Semaphore(1)
    converting = asyncio.Event()
    finish = asyncio.Event()
    event, second = UploadEvent("first.md"), UploadEvent("second.md")
    second.chat_id = second.sender_id = second.chat = 43

    async def convert(input_file, *args, **kwargs):
        if input_file.name == "second.md":
            assert second.edits[-1] == "Converting the file to epub..."
        converting.set()
        await finish.wait()
        output = input_file.with_suffix(".epub")
        output.write_bytes(b"converted")
        return SimpleNamespace(
            backend="calibre",
            output_files=[output],
            split_capped=False,
            conversion_error=None,
            converted_to_rtl=False,
        )

    async def send_file(*args, **kwargs):
        assert not module.conversion_slots.locked()

    monkeypatch.setattr(module.converter, "convert_ebook_many", convert)
    monkeypatch.setattr(event.client, "send_file", send_file)

    async def run():
        await prepare_request(module, event)
        await prepare_request(module, second)
        first_task = asyncio.create_task(module.converter_callback.__wrapped__(event))
        await converting.wait()
        second_task = asyncio.create_task(module.converter_callback.__wrapped__(second))
        await asyncio.sleep(0)
        assert "Queued. Waiting for a conversion slot..." in second.edits
        finish.set()
        await asyncio.gather(first_task, second_task)
        assert not module.active_users
        queued_index = second.edits.index("Queued. Waiting for a conversion slot...")
        assert second.edits[queued_index + 1] == "Converting the file to epub..."
        assert event.edits.count("Converting the file to epub...") == 1

    asyncio.run(run())


def test_group_members_have_separate_admission_and_cooldown(converter_module, monkeypatch):
    module = converter_module
    started = []
    both_started = asyncio.Event()
    recorded = []
    monkeypatch.setattr(module, "record_conversion_event", recorded.append)

    async def convert(input_file, *args, **kwargs):
        started.append(input_file)
        if len(started) == 2:  # noqa: PLR2004
            both_started.set()
        await both_started.wait()
        return SimpleNamespace(
            backend="calibre",
            output_files=[],
            split_capped=False,
            conversion_error="Timeout while running command: ebook-convert",
        )

    monkeypatch.setattr(module.converter, "convert_ebook_many", convert)

    async def run():
        first, second = UploadEvent("first.md"), UploadEvent("second.md")
        first.chat_id = second.chat_id = -10042
        second.sender_id = 43
        await prepare_request(module, first)
        await prepare_request(module, second)
        await asyncio.wait_for(
            asyncio.gather(
                module.converter_callback.__wrapped__(first),
                module.converter_callback.__wrapped__(second),
            ),
            timeout=1,
        )
        assert not first.answers
        assert not second.answers
        assert not module.active_users
        assert all(event.user_id == first.chat_id for event in recorded)
        module.route_timeouts[(first.sender_id, "md", "epub")].append(module.monotonic())
        await prepare_request(module, first)
        await prepare_request(module, second)
        await module.converter_callback.__wrapped__(first)
        await module.converter_callback.__wrapped__(second)
        assert first.answers == ["This route timed out twice. Retry in 60 minutes."]
        assert not second.answers
        assert len(started) == 3  # noqa: PLR2004

    asyncio.run(run())


@pytest.mark.parametrize("backend", ["bok", "anydoc"])
def test_extraction_timeout_has_countable_error(tmp_path, monkeypatch, backend):
    async def extract(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(convert_utils.asyncio, "to_thread", extract)
    converter = convert_utils.Converter()
    source = tmp_path / f"book.{backend}"
    if backend == "bok":
        result = asyncio.run(
            converter._convert_from_bok(
                source,
                "epub",
                convert_utils.ConversionOptions(),
                timeout=0,
            )
        )
    else:
        result = asyncio.run(converter._prepare_anydoc_input(source, timeout=0))
    assert (
        result[-1] == f"Timeout while running {'BOK' if backend == 'bok' else 'Anydoc'} extraction"
    )


def test_command_cancellation_kills_process_group(monkeypatch):
    killed = []
    started = asyncio.Event()

    async def communicate():
        started.set()
        await asyncio.Event().wait()

    async def create_process(*args, **kwargs):
        return SimpleNamespace(pid=123, communicate=communicate)

    monkeypatch.setattr(convert_utils.asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(convert_utils, "killpg", lambda pid, signal: killed.append((pid, signal)))

    async def run():
        task = asyncio.create_task(convert_utils.Converter._run_command(["worker"], timeout=None))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert killed == [(123, convert_utils.SIGKILL)]
