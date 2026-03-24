import asyncio
from pathlib import Path

import ebook_converter_bot.utils.convert as convert_utils
from ebook_converter_bot.utils.convert import TASK_TIMEOUT, ConversionOptions, Converter


def _capture_commands(converter: Converter) -> list[list[str]]:
    commands: list[list[str]] = []

    async def fake_run(
        command: list[str], timeout: int | None = TASK_TIMEOUT
    ) -> tuple[int | None, str]:
        commands.append(command)
        return 0, ""

    converter._run_command = fake_run  # type: ignore[method-assign]
    return commands


def _contains_flag_pair(command: list[str], flag: str, value: str) -> bool:
    try:
        index = command.index(flag)
    except ValueError:
        return False
    return index + 1 < len(command) and command[index + 1] == value


def test_docx_options_are_applied_only_when_changed(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")

        await converter.convert_ebook(
            input_file,
            "docx",
            options=ConversionOptions(
                smarten_punctuation=True,
                change_justification="left",
                remove_paragraph_spacing=True,
                docx_page_size="a4",
                docx_no_toc=True,
            ),
        )

        command = commands[0]
        assert "--smarten-punctuation" in command
        assert "--remove-paragraph-spacing" in command
        assert _contains_flag_pair(command, "--change-justification", "left")
        assert _contains_flag_pair(command, "--docx-page-size", "a4")
        assert "--docx-no-toc" in command

    asyncio.run(run())


def test_epub_options_are_applied_only_when_changed(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")

        await converter.convert_ebook(
            input_file,
            "epub",
            options=ConversionOptions(
                epub_version="3",
                epub_inline_toc=True,
                epub_remove_background=True,
            ),
        )

        command = commands[0]
        assert _contains_flag_pair(command, "--epub-version", "3")
        assert "--epub-inline-toc" in command
        assert _contains_flag_pair(
            command, "--filter-css", "background,background-color,background-image"
        )

    asyncio.run(run())


def test_pdf_options_are_applied_only_when_changed(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")

        await converter.convert_ebook(
            input_file,
            "pdf",
            options=ConversionOptions(
                pdf_paper_size="a4",
                pdf_page_numbers=True,
            ),
        )

        command = commands[0]
        assert _contains_flag_pair(command, "--paper-size", "a4")
        assert "--pdf-page-numbers" in command

    asyncio.run(run())


def test_format_specific_flags_do_not_leak_to_other_outputs(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")

        await converter.convert_ebook(
            input_file,
            "fb2",
            options=ConversionOptions(
                docx_page_size="a4",
                docx_no_toc=True,
                epub_version="3",
                epub_inline_toc=True,
                epub_remove_background=True,
                pdf_paper_size="letter",
                pdf_page_numbers=True,
            ),
        )

        command = commands[0]
        assert "--docx-page-size" not in command
        assert "--docx-no-toc" not in command
        assert "--epub-version" not in command
        assert "--epub-inline-toc" not in command
        assert "--filter-css" not in command
        assert "--paper-size" not in command
        assert "--pdf-page-numbers" not in command

    asyncio.run(run())


def test_epub_remove_background_applies_for_epub_input_to_epub_output(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.epub"
        input_file.write_text("hello")

        await converter.convert_ebook(
            input_file,
            "epub",
            options=ConversionOptions(epub_remove_background=True),
        )

        command = commands[0]
        assert command[0] == "ebook-convert"
        assert command[1] == str(input_file)
        assert command[2].endswith("_.epub")
        assert _contains_flag_pair(
            command, "--filter-css", "background,background-color,background-image"
        )

    asyncio.run(run())


def test_compress_cover_runs_ebook_polish_for_supported_outputs(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")
        output_file = input_file.with_suffix(".epub")
        output_file.write_text("converted")

        await converter.convert_ebook(
            input_file,
            "epub",
            options=ConversionOptions(compress_cover=True),
        )

        assert commands[0][0] == "ebook-convert"
        assert commands[1] == ["ebook-polish", "--compress-images", str(output_file)]

    asyncio.run(run())


def test_convert_ebook_passes_timeout_to_run_command(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        timeouts: list[int | None] = []

        async def fake_run(
            command: list[str], timeout: int | None = TASK_TIMEOUT
        ) -> tuple[int | None, str]:
            timeouts.append(timeout)
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")

        await converter.convert_ebook(input_file, "epub")
        await converter.convert_ebook(input_file, "epub", timeout=None)

        assert timeouts == [TASK_TIMEOUT, None]

    asyncio.run(run())


def test_convert_ebook_passes_timeout_to_bok_flow(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        captured_timeouts: list[int | None] = []

        async def fake_convert_from_bok(
            input_file: Path,
            output_type: str,
            options: ConversionOptions,
            timeout: int | None = TASK_TIMEOUT,
        ) -> tuple[Path, bool | None, str]:
            captured_timeouts.append(timeout)
            return input_file.with_suffix(f".{output_type}"), None, ""

        converter._convert_from_bok = fake_convert_from_bok  # type: ignore[method-assign]
        input_file = tmp_path / "book.bok"
        input_file.write_text("hello")

        await converter.convert_ebook(input_file, "epub")
        await converter.convert_ebook(input_file, "epub", timeout=None)

        assert captured_timeouts == [TASK_TIMEOUT, None]

    asyncio.run(run())


def test_preprocess_input_epub_runs_footnote_standardization(tmp_path: Path) -> None:
    input_file = tmp_path / "book.epub"
    input_file.write_text("hello")
    called: list[Path] = []

    original = convert_utils.standardize_epub_footnotes
    convert_utils.standardize_epub_footnotes = lambda path: called.append(path) or True
    try:
        Converter._preprocess_input_epub(
            input_file,
            ConversionOptions(epub_standardize_footnotes=True),
        )
    finally:
        convert_utils.standardize_epub_footnotes = original

    assert called == [input_file]
