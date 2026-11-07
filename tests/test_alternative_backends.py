import asyncio
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import ebook_converter_bot.utils.convert as convert_utils
import pytest
from ebook_converter_bot.utils.backend_routes import backend_choices, resolve_backend
from ebook_converter_bot.utils.bok_to_epub import EpubBook, write_epub
from ebook_converter_bot.utils.convert import (
    MAX_BOKO_WORKERS,
    TASK_TIMEOUT,
    ConversionOptions,
    Converter,
)
from ebook_converter_bot.utils.converter_options import (
    ConversionRequestState,
    apply_persisted_options,
    build_options_keyboard,
    build_route_options_keyboard,
    route_option_values,
    set_request_option,
    state_to_persisted_options,
)
from ebook_converter_bot.utils.epub import xml_parser
from lxml import etree

from tests.test_converter_options import LABELS, _flatten_data


@pytest.mark.parametrize(
    ("input_type", "output_type", "expected"),
    [
        ("epub", "kfx", ["calibre", "boko", "kfxgen"]),
        ("epub", "azw3", ["calibre", "boko"]),
        ("epub", "md", ["pandoc", "boko"]),
        ("docx", "epub", ["calibre", "pandoc"]),
        ("docx", "kfx", ["calibre", "kfxgen"]),
        ("mobi", "epub", ["calibre", "boko"]),
        ("mobi", "md", ["boko"]),
        ("kfx", "epub", ["calibre", "boko"]),
        ("kpf", "kfx", ["calibre"]),
        ("bok", "kfx", ["calibre", "boko", "kfxgen"]),
        ("pdf", "kfx", ["calibre", "boko", "kfxgen"]),
        ("rst", "epub", ["pandoc"]),
        ("epub", "epub", ["calibre"]),
    ],
)
def test_route_backend_choices(input_type: str, output_type: str, expected: list[str]) -> None:
    assert backend_choices(input_type, output_type) == expected
    assert resolve_backend(input_type, output_type, "unavailable") == expected[0]


@pytest.mark.parametrize(
    ("output_type", "backend", "expected"),
    [
        ("kfx", "boko", ["calibre", "boko", "kfxgen"]),
        ("kfx", "kfxgen", ["calibre", "boko", "kfxgen"]),
        ("azw3", "boko", ["calibre", "boko"]),
        ("md", "boko", ["pandoc", "boko"]),
        ("docx", "kfxgen", ["calibre", "pandoc"]),
    ],
)
def test_route_chooser_shows_only_available_backends(
    output_type: str, backend: str, expected: list[str]
) -> None:
    state = ConversionRequestState("/tmp/book.epub", 0, "epub", conversion_backend=backend)  # noqa: S108
    labels = LABELS | {"conversion_backend_label": "محرك التحويل"}
    rows = build_route_options_keyboard("12345678", state, output_type, labels)
    buttons = [
        button
        for row in rows
        for button in row
        if _flatten_data([[button]])[0].startswith(b"opt|conversion_backend|")
    ]
    data = _flatten_data([buttons])
    assert data == [f"opt|conversion_backend|{name}|12345678".encode() for name in expected]
    effective = resolve_backend("epub", output_type, backend)
    assert [button.text for button in buttons] == [
        f"{labels[f'{name}_label']}{' ✅' if name == effective else ''}" for name in expected
    ]


@pytest.mark.parametrize("backend", ["boko", "kfxgen"])
def test_native_kfx_controls_do_not_mutate_saved_preferences(backend: str) -> None:
    state = ConversionRequestState(
        "book.epub",
        0,
        "epub",
        conversion_backend=backend,
        force_rtl=True,
        kfx_doc_type="book",
        kfx_pages=None,
        smarten_punctuation=True,
        epub_version="2",
    )
    saved = state_to_persisted_options(state)
    rows = build_route_options_keyboard("12345678", state, "kfx", LABELS)
    data = _flatten_data(rows)
    values = route_option_values(state, "kfx")
    assert values["conversion_backend"] == backend
    assert values["force_rtl"] is True
    assert values["smarten_punctuation"] is False
    assert values["epub_version"] == "default"
    assert not any(item.startswith(b"opt|kfx_doc_type|") for item in data)
    if backend == "boko":
        assert values["kfx_doc_type"] == "book"
        assert values["kfx_pages"] == 0
        assert not any(item.startswith(b"opt|kfx_pages|") for item in data)
    else:
        assert values["kfx_doc_type"] == "doc"
        assert values["kfx_pages"] is None
        assert b"opt|kfx_pages|auto|12345678" in data
    assert state_to_persisted_options(state) == saved
    restored = ConversionRequestState("/tmp/new.epub", 0, "epub")  # noqa: S108
    apply_persisted_options(restored, saved)
    assert restored.conversion_backend == backend
    assert set_request_option(restored, "conversion_backend", backend)


@pytest.fixture
def arabic_epub(tmp_path: Path) -> Path:
    source = tmp_path / "كتاب.epub"
    write_epub(
        source,
        EpubBook(
            title="كتاب اختبار",
            author="كاتب",
            about="",
            pages=[
                {
                    "page_number": 1,
                    "page": 1,
                    "part": 1,
                    "text_html": "<h1>المقدمة</h1><p>مرحبا بالعالم</p>",
                }
            ],
            toc_tree=[{"text": "المقدمة", "page": 1, "anchor": ""}],
        ),
        include_toc_page=False,
    )
    return source


@pytest.mark.skipif(shutil.which("boko") is None, reason="Boko CLI is not installed")
@pytest.mark.parametrize("output_type", ["azw3", "kfx", "md"])
def test_boko_cli_converts_arabic_epub(arabic_epub: Path, output_type: str) -> None:
    arabic_epub = arabic_epub.rename(arabic_epub.with_name(f"Conversion error: {arabic_epub.name}"))
    state = ConversionRequestState(
        str(arabic_epub), 0, "epub", conversion_backend="boko", force_rtl=True
    )
    options = ConversionOptions(**route_option_values(state, output_type))
    result = asyncio.run(Converter().convert_ebook_many(arabic_epub, output_type, options))
    assert result.backend == "boko"
    assert not result.conversion_error
    assert result.output_files == [arabic_epub.with_suffix(f".{output_type}")]
    output = result.output_files[0]
    if output_type == "md":
        assert "مرحبا بالعالم" in output.read_text()
    else:
        readback = arabic_epub.parent / "readback.epub"
        executable = shutil.which("boko")
        assert executable is not None
        subprocess.run(  # noqa: S603 -- local CLI and generated test fixtures
            [executable, "convert", str(output), str(readback)],
            check=True,
            capture_output=True,
        )
        with ZipFile(readback) as book:
            opf = next(name for name in book.namelist() if name.endswith(".opf"))
            spine = etree.fromstring(book.read(opf), xml_parser).find(
                "{http://www.idpf.org/2007/opf}spine"
            )
            assert spine is not None
            assert spine.get("page-progression-direction") == "rtl"
            text = "\n".join(
                "".join(etree.fromstring(book.read(name), xml_parser).itertext())
                for name in book.namelist()
                if name.endswith((".xhtml", ".html"))
            )
            assert "مرحبا بالعالم" in text
    assert not list(arabic_epub.parent.glob(".boko-*"))


@pytest.mark.parametrize("input_type", ["mobi", "kfx"])
def test_boko_direct_import_does_not_use_kfx_input(
    tmp_path: Path, monkeypatch, input_type: str
) -> None:
    converter = Converter()
    source = tmp_path / f"book.{input_type}"
    source.write_bytes(b"source")
    commands = []

    async def fake_run(command, timeout=TASK_TIMEOUT):
        commands.append(command)
        Path(command[-1]).write_text("converted")
        return 0, ""

    monkeypatch.setattr(converter, "_run_command", fake_run)
    result = asyncio.run(
        converter.convert_ebook_many(source, "md", ConversionOptions(conversion_backend="boko"))
    )
    assert result.backend == "boko"
    assert result.output_files[0].read_text() == "converted"
    assert len(commands) == 1
    index = commands[0].index("boko")
    assert commands[0][index : index + 4] == ["boko", "convert", "--quiet", str(source)]


@pytest.mark.parametrize(("pages", "expected_flag"), [(None, True), (0, False)])
def test_kfxgen_uses_same_profile_and_respects_pages(
    tmp_path: Path, monkeypatch, pages, expected_flag: bool
) -> None:
    converter = Converter()
    source = tmp_path / "book.epub"
    source.write_bytes(b"source")
    commands = []
    timeouts = []

    async def fake_run(command, timeout=TASK_TIMEOUT):
        commands.append(command)
        timeouts.append(timeout)
        if command[0] == "ebook-convert":
            Path(command[2]).write_bytes(b"KFX")
        return 0, ""

    monkeypatch.setattr(converter, "_run_command", fake_run)
    result = asyncio.run(
        converter.convert_ebook_many(
            source,
            "kfx",
            ConversionOptions(conversion_backend="kfxgen", kfx_pages=pages),
            timeout=17,
        )
    )
    assert result.backend == "kfxgen"
    assert not result.conversion_error
    assert commands[0][:2] == ["calibre-debug", "-c"]
    assert commands[1][:2] == ["ebook-convert", str(source)]
    assert Path(commands[1][2]).name == source.with_suffix(".kfx").name
    assert Path(commands[1][2]).parent.parent == tmp_path
    assert not Path(commands[1][2]).exists()
    assert ("--kfxgen-disable-approximate-pages" in commands[1]) == expected_flag
    assert timeouts == [17, 17]


@pytest.mark.parametrize("backend", ["boko", "kfxgen"])
def test_native_failure_does_not_send_stale_output(
    tmp_path: Path, monkeypatch, backend: str
) -> None:
    converter = Converter()
    source = tmp_path / "book.epub"
    source.write_bytes(b"source")
    output = source.with_suffix(".kfx")
    output.write_bytes(b"stale")
    calls = []

    async def fake_run(command, timeout=TASK_TIMEOUT):
        calls.append(command)
        if "boko" in command:
            Path(command[-1]).write_bytes(b"partial")
        return -9, "Worker failed"

    monkeypatch.setattr(converter, "_run_command", fake_run)
    state = ConversionRequestState(str(source), 0, "epub", conversion_backend=backend)
    result = asyncio.run(
        converter.convert_ebook_many(
            source, "kfx", ConversionOptions(**route_option_values(state, "kfx"))
        )
    )
    assert result.backend == backend
    assert result.output_files == []
    assert result.conversion_error == "Worker failed"
    assert source.read_bytes() == b"source"
    assert output.read_bytes() == b"stale"
    assert not list(tmp_path.glob(".boko-*"))
    assert len(calls) == 1


@pytest.mark.parametrize("backend", ["calibre", "boko", "kfxgen"])
def test_bok_kfx_stage_respects_backend(arabic_epub: Path, monkeypatch, backend: str) -> None:
    data = arabic_epub.read_bytes()
    arabic_epub.unlink()
    source = arabic_epub.with_suffix(".bok")
    source.write_bytes(b"bok")
    converter = Converter()
    commands = []
    monkeypatch.setattr(convert_utils, "bok_to_epub", lambda _, output: output.write_bytes(data))

    async def fake_run(command, timeout=TASK_TIMEOUT):
        commands.append(command)
        if "boko" in command:
            Path(command[-1]).write_bytes(b"KFX")
        elif command[0] == "ebook-convert":
            Path(command[2]).write_bytes(b"KFX")
        elif command[:3] == ["calibre-debug", "-r", "KFX Output"]:
            Path(command[-1]).with_suffix(".kfx").write_bytes(b"KFX")
        return 0, ""

    monkeypatch.setattr(converter, "_run_command", fake_run)
    state = ConversionRequestState(str(source), 0, "bok", conversion_backend=backend)
    result = asyncio.run(
        converter.convert_ebook_many(
            source, "kfx", ConversionOptions(**route_option_values(state, "kfx"))
        )
    )
    assert result.backend == backend
    assert not result.conversion_error
    assert result.output_files == [source.with_suffix(".kfx")]
    assert not arabic_epub.exists()
    if backend == "boko":
        assert "boko" in commands[-1]
    else:
        assert commands[-1][0] == {"calibre": "calibre-debug", "kfxgen": "ebook-convert"}[backend]


@pytest.mark.parametrize("timeout", [None, TASK_TIMEOUT * 2])
def test_boko_worker_limits(tmp_path: Path, monkeypatch, timeout: int | None) -> None:
    converter = Converter()
    active = 0
    peak = 0

    async def fake_run(command, timeout=TASK_TIMEOUT):
        nonlocal active, peak
        assert timeout == TASK_TIMEOUT
        assert command[:-2] == ["env", "RAYON_NUM_THREADS=2", "boko", "convert", "--quiet"]
        assert Path(command[-2]) == tmp_path / Path(command[-1]).with_suffix(".mobi").name
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        Path(command[-1]).write_bytes(b"markdown")
        active -= 1
        return 0, ""

    monkeypatch.setattr(converter, "_run_command", fake_run)

    async def run():
        tasks = []
        for index in range(4):
            source = tmp_path / f"book-{index}.mobi"
            source.write_bytes(b"source")
            tasks.append(
                converter.convert_ebook_many(
                    source, "md", ConversionOptions(conversion_backend="boko"), timeout=timeout
                )
            )
        return await asyncio.gather(*tasks)

    assert all(not result.conversion_error for result in asyncio.run(run()))
    assert peak == MAX_BOKO_WORKERS


def test_chooser_and_dispatch_agree_for_all_advertised_routes() -> None:
    converter = Converter()
    for input_type in converter.supported_input_types:
        for output_type in converter.get_supported_output_types_for_input(input_type):
            for backend in backend_choices(input_type, output_type):
                state = ConversionRequestState("unused", 0, input_type, conversion_backend=backend)
                options = ConversionOptions(**route_option_values(state, output_type))
                assert (
                    converter._select_backend(input_type, output_type, options).name == backend
                ), (
                    input_type,
                    output_type,
                    backend,
                )


@pytest.mark.parametrize("backend", ["calibre", "boko", "kfxgen"])
def test_pdf_kfx_stage_respects_backend(arabic_epub: Path, monkeypatch, backend: str) -> None:
    data = arabic_epub.read_bytes()
    arabic_epub.unlink()
    source = arabic_epub.with_suffix(".pdf")
    source.write_bytes(b"PDF")
    converter = Converter()
    commands = []

    def fake_pdf_to_htmlz(_, output):
        output.write_bytes(b"HTMLZ")
        return ""

    async def fake_run(command, timeout=TASK_TIMEOUT):
        commands.append(command)
        if command[0] == "ebook-convert":
            output = Path(command[2])
            output.write_bytes(data if output.suffix == ".epub" else b"KFX")
        elif "boko" in command:
            Path(command[-1]).write_bytes(b"KFX")
        elif command[:3] == ["calibre-debug", "-r", "KFX Output"]:
            Path(command[-1]).with_suffix(".kfx").write_bytes(b"KFX")
        return 0, ""

    monkeypatch.setattr(convert_utils, "pdf_to_htmlz", fake_pdf_to_htmlz)
    monkeypatch.setattr(converter, "_run_command", fake_run)
    state = ConversionRequestState(
        str(source), 0, "pdf", conversion_backend=backend, force_rtl=True
    )
    result = asyncio.run(
        converter.convert_ebook_many(
            source, "kfx", ConversionOptions(**route_option_values(state, "kfx"))
        )
    )
    assert result.backend == backend
    assert not result.conversion_error
    assert result.output_files == [source.with_suffix(".kfx")]
    assert commands[0][:3] == ["ebook-convert", str(source.with_suffix(".htmlz")), str(arabic_epub)]
    assert not arabic_epub.exists()
    assert not source.with_suffix(".htmlz").exists()
    if backend != "calibre":
        assert result.converted_to_rtl


@pytest.mark.parametrize("backend", ["boko", "kfxgen"])
def test_native_epub_input_keeps_shared_preprocessing(
    tmp_path: Path, monkeypatch, backend: str
) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"EPUB")
    converter = Converter()
    operations = []
    monkeypatch.setattr(
        convert_utils, "set_epub_to_rtl", lambda path: operations.append(("rtl", path)) or True
    )
    monkeypatch.setattr(
        convert_utils, "fix_content_opf_problems", lambda path: operations.append(("fix", path))
    )
    monkeypatch.setattr(convert_utils, "flatten_toc", lambda path: operations.append(("toc", path)))
    monkeypatch.setattr(
        convert_utils,
        "remove_epub_footnotes",
        lambda path, keep_markers: operations.append(("notes", path, keep_markers)),
    )

    async def fake_run(command, timeout=TASK_TIMEOUT):
        if "boko" in command:
            Path(command[-1]).write_bytes(b"KFX")
        elif command[0] == "ebook-convert":
            Path(command[2]).write_bytes(b"KFX")
        return 0, ""

    monkeypatch.setattr(converter, "_run_command", fake_run)
    state = ConversionRequestState(
        str(source),
        0,
        "epub",
        conversion_backend=backend,
        force_rtl=True,
        fix_epub=True,
        flat_toc=True,
        footnote_mode="markers",
    )
    result = asyncio.run(
        converter.convert_ebook_many(
            source, "kfx", ConversionOptions(**route_option_values(state, "kfx"))
        )
    )
    assert not result.conversion_error
    assert result.converted_to_rtl
    assert operations == [
        ("rtl", source),
        ("fix", source),
        ("toc", source),
        ("notes", source, True),
    ]


def test_calibre_kfx_still_uses_named_cli(tmp_path: Path, monkeypatch) -> None:
    converter = Converter()
    source = tmp_path / "book.epub"
    source.write_bytes(b"EPUB")
    commands = []

    async def fake_run(command, timeout=TASK_TIMEOUT):
        commands.append(command)
        return 0, ""

    monkeypatch.setattr(converter, "_run_command", fake_run)
    result = asyncio.run(
        converter.convert_ebook_many(
            source, "kfx", ConversionOptions(kfx_doc_type="book", kfx_pages=0)
        )
    )
    assert result.backend == "calibre"
    assert commands == [
        [
            "calibre-debug",
            "-r",
            "KFX Output",
            "--",
            "--book",
            "--pages",
            "0",
            str(source),
            str(source.with_suffix(".kfx")),
        ]
    ]


@pytest.mark.parametrize("backend", ["calibre", "boko", "kfxgen"])
def test_backend_honors_explicit_kfx_output_path(tmp_path: Path, monkeypatch, backend: str) -> None:
    converter = Converter()
    source = tmp_path / "source.epub"
    source.write_bytes(b"EPUB")
    output = tmp_path / "different.kfx"

    async def fake_run(command, timeout=TASK_TIMEOUT):
        if command[0] == "ebook-convert":
            Path(command[2]).write_bytes(b"KFX")
        elif "boko" in command or command[:2] == ["calibre-debug", "-r"]:
            Path(command[-1]).write_bytes(b"KFX")
        return 0, ""

    monkeypatch.setattr(converter, "_run_command", fake_run)
    state = ConversionRequestState(str(source), 0, "epub", conversion_backend=backend)
    options = ConversionOptions(**route_option_values(state, "kfx"))
    error = asyncio.run(converter.backends[backend].convert(source, output, "kfx", options))
    assert not error
    assert output.read_bytes() == b"KFX"
    assert not source.with_suffix(".kfx").exists()


@pytest.mark.parametrize("backend", ["boko", "kfxgen"])
def test_general_kfx_options_hide_unsupported_native_controls(backend: str) -> None:
    state = ConversionRequestState(
        "book.epub", 0, "epub", options_context="kfx", conversion_backend=backend
    )
    data = _flatten_data(build_options_keyboard("12345678", state, LABELS))
    assert not any(item.startswith(b"opt|kfx_doc_type|") for item in data)
    assert any(item.startswith(b"opt|kfx_pages|") for item in data) == (backend == "kfxgen")


@pytest.mark.parametrize("input_type", ["bok", "kfx", "azw8", "kfx-zip"])
@pytest.mark.parametrize("mode", ["markers", "remove"])
def test_prepared_epub_routes_accept_and_persist_footnote_controls(
    input_type: str, mode: str
) -> None:
    state = ConversionRequestState("book", 0, input_type, conversion_backend="pandoc")
    data = _flatten_data(build_route_options_keyboard("12345678", state, "md", LABELS))
    assert f"opt|footnote_mode|{mode}|12345678".encode() in data
    assert set_request_option(state, "footnote_mode", mode)
    assert route_option_values(state, "md")["footnote_mode"] == mode
    restored = ConversionRequestState("new-book", 0, input_type)
    apply_persisted_options(restored, state_to_persisted_options(state))
    assert restored.footnote_mode == mode


def test_failed_boko_epub_conversion_keeps_worker_error_and_skips_rtl(
    tmp_path: Path, monkeypatch
) -> None:
    converter = Converter()
    source = tmp_path / "book.mobi"
    source.write_bytes(b"source")
    source.with_suffix(".epub").write_bytes(b"stale output")
    processed = []
    monkeypatch.setattr(
        convert_utils, "set_epub_to_rtl", lambda path: processed.append(path) or True
    )

    async def fake_run(command, timeout=TASK_TIMEOUT):
        Path(command[-1]).write_bytes(b"partial")
        return -9, "Worker timed out"

    monkeypatch.setattr(converter, "_run_command", fake_run)
    result = asyncio.run(
        converter.convert_ebook_many(
            source,
            "epub",
            ConversionOptions(conversion_backend="boko", force_rtl=True),
        )
    )
    assert result.backend == "boko"
    assert result.conversion_error == "Worker timed out"
    assert result.output_files == []
    assert processed == []
    assert source.with_suffix(".epub").read_bytes() == b"stale output"
    assert not list(tmp_path.glob(".boko-*"))


@pytest.mark.parametrize("fails", [False, True])
def test_markdown_kfx_bridge_preserves_neighboring_epub(
    tmp_path: Path, monkeypatch, fails: bool
) -> None:
    converter = Converter()
    source = tmp_path / "book.md"
    source.write_text("# User A")
    neighbor = tmp_path / "book.epub"
    neighbor.write_bytes(b"User B source")

    async def fake_run(command, timeout=TASK_TIMEOUT):
        if command[0] == "ebook-convert":
            assert Path(command[2]) != neighbor
            Path(command[2]).write_bytes(b"intermediate")
        else:
            Path(command[-1]).write_bytes(b"KFX")
        return (1, "Failed") if fails else (0, "")

    monkeypatch.setattr(converter, "_run_command", fake_run)
    result = asyncio.run(converter.convert_ebook_many(source, "kfx"))
    assert bool(result.conversion_error) == fails
    assert neighbor.read_bytes() == b"User B source"
    assert not list(tmp_path.glob(".kfx-*"))


def test_kfxgen_partial_failure_preserves_existing_destination(tmp_path: Path, monkeypatch) -> None:
    converter = Converter()
    source = tmp_path / "book.epub"
    source.write_bytes(b"source")
    output = source.with_suffix(".kfx")
    output.write_bytes(b"old destination")

    async def fake_run(command, timeout=TASK_TIMEOUT):
        if command[0] == "ebook-convert":
            Path(command[2]).write_bytes(b"partial output")
            return 1, "Failed"
        return 0, ""

    monkeypatch.setattr(converter, "_run_command", fake_run)
    result = asyncio.run(
        converter.convert_ebook_many(source, "kfx", ConversionOptions(conversion_backend="kfxgen"))
    )
    assert result.conversion_error == "Failed"
    assert result.output_files == []
    assert output.read_bytes() == b"old destination"
    assert not list(tmp_path.glob(".kfxgen-*"))


def test_run_command_reports_silent_nonzero_exit(monkeypatch) -> None:
    class FailedProcess:
        pid = 123
        returncode = -6

        async def communicate(self):
            return b"", b""

    async def fake_spawn(*args, **kwargs):
        return FailedProcess()

    monkeypatch.setattr(convert_utils.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(convert_utils, "killpg", lambda *args: None)
    code, error = asyncio.run(Converter._run_command(["worker"]))
    assert code == FailedProcess.returncode
    assert "status -6" in error


def test_native_backend_rejects_incompatible_options_without_fallback(tmp_path: Path) -> None:
    source = tmp_path / "book.epub"
    source.write_bytes(b"source")
    result = asyncio.run(
        Converter().convert_ebook_many(
            source,
            "azw3",
            ConversionOptions(conversion_backend="boko", epub_version="2"),
        )
    )
    assert result.backend == "boko"
    assert result.output_files == []
    assert "formatting options" in result.conversion_error
