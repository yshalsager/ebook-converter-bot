import asyncio
from pathlib import Path

import ebook_converter_bot.utils.convert as convert_utils
import pytest
from ebook_converter_bot.utils.convert import (
    MAX_SPLIT_OUTPUT_FILES,
    PDF_FONTS_DIR,
    TASK_TIMEOUT,
    ConversionOptions,
    Converter,
)

EXPECTED_SPLIT_OUTPUTS = 2
EXPECTED_RTL_PDF_COMMANDS = 2
OPTION_CASES = [
    {
        "output_type": "docx",
        "options": ConversionOptions(
            smarten_punctuation=True,
            change_justification="left",
            remove_paragraph_spacing=True,
            docx_page_size="a4",
            docx_no_toc=True,
        ),
        "expected_flags": ["--smarten-punctuation", "--remove-paragraph-spacing", "--docx-no-toc"],
        "expected_pairs": [("--change-justification", "left"), ("--docx-page-size", "a4")],
    },
    {
        "output_type": "epub",
        "options": ConversionOptions(
            epub_version="3",
            epub_inline_toc=True,
            epub_remove_background=True,
        ),
        "expected_flags": ["--epub-inline-toc"],
        "expected_pairs": [
            ("--epub-version", "3"),
            ("--filter-css", "background,background-color,background-image"),
        ],
    },
    {
        "output_type": "pdf",
        "options": ConversionOptions(
            pdf_paper_size="a4",
            pdf_page_numbers=True,
        ),
        "expected_flags": ["--pdf-page-numbers"],
        "expected_pairs": [("--paper-size", "a4")],
    },
]


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


@pytest.fixture
def converter_with_commands() -> tuple[Converter, list[list[str]]]:
    converter = Converter()
    return converter, _capture_commands(converter)


@pytest.mark.parametrize(
    "case",
    OPTION_CASES,
    ids=["docx", "epub", "pdf"],
)
def test_output_options_are_applied_only_when_changed(
    tmp_path: Path,
    converter_with_commands: tuple[Converter, list[list[str]]],
    case: dict[str, ConversionOptions | list[str] | list[tuple[str, str]] | str],
) -> None:
    async def run() -> None:
        converter, commands = converter_with_commands
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")

        await converter.convert_ebook_many(
            input_file,
            str(case["output_type"]),
            options=case["options"],
        )

        command = commands[0]
        for flag in case["expected_flags"]:
            assert flag in command
        for flag, value in case["expected_pairs"]:
            assert _contains_flag_pair(command, flag, value)

    asyncio.run(run())


def test_force_rtl_pdf_uses_epub_intermediate_for_non_epub_input(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands: list[list[str]] = []
        rtl_paths: list[Path] = []
        input_file = tmp_path / "book.docx"
        input_file.write_text("hello")
        output_file = input_file.with_suffix(".pdf")
        intermediate_epub = input_file.with_suffix(".epub")

        original_rtl = convert_utils.set_epub_to_rtl

        async def fake_run(
            command: list[str], timeout: int | None = TASK_TIMEOUT
        ) -> tuple[int | None, str]:
            commands.append(command)
            Path(command[2]).write_text("converted")
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]
        convert_utils.set_epub_to_rtl = lambda path: rtl_paths.append(path) or True
        try:
            result = await converter.convert_ebook_many(
                input_file,
                "pdf",
                options=ConversionOptions(
                    force_rtl=True, pdf_paper_size="a4", pdf_page_numbers=True
                ),
            )
        finally:
            convert_utils.set_epub_to_rtl = original_rtl

        assert result.output_files == [output_file]
        assert result.converted_to_rtl is True
        assert result.conversion_error == ""
        assert len(commands) == EXPECTED_RTL_PDF_COMMANDS
        assert commands[0][:3] == ["ebook-convert", str(input_file), str(intermediate_epub)]
        assert commands[1][:3] == ["ebook-convert", str(intermediate_epub), str(output_file)]
        assert "--paper-size" not in commands[0]
        assert "--pdf-page-numbers" not in commands[0]
        assert _contains_flag_pair(commands[1], "--paper-size", "a4")
        assert "--pdf-page-numbers" in commands[1]
        assert rtl_paths == [intermediate_epub]
        assert intermediate_epub.exists() is False

    asyncio.run(run())


def test_force_rtl_pdf_with_epub_input_uses_existing_preprocess(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands: list[list[str]] = []
        rtl_paths: list[Path] = []
        input_file = tmp_path / "book.epub"
        input_file.write_text("hello")
        output_file = input_file.with_suffix(".pdf")

        original_rtl = convert_utils.set_epub_to_rtl

        async def fake_run(
            command: list[str], timeout: int | None = TASK_TIMEOUT
        ) -> tuple[int | None, str]:
            commands.append(command)
            Path(command[2]).write_text("converted")
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]
        convert_utils.set_epub_to_rtl = lambda path: rtl_paths.append(path) or True
        try:
            result = await converter.convert_ebook_many(
                input_file,
                "pdf",
                options=ConversionOptions(force_rtl=True, pdf_paper_size="letter"),
            )
        finally:
            convert_utils.set_epub_to_rtl = original_rtl

        assert result.output_files == [output_file]
        assert result.converted_to_rtl is True
        assert result.conversion_error == ""
        assert len(commands) == 1
        assert commands[0][:3] == ["ebook-convert", str(input_file), str(output_file)]
        assert _contains_flag_pair(commands[0], "--paper-size", "letter")
        assert rtl_paths == [input_file]

    asyncio.run(run())


def test_pdf_font_profile_adds_embed_and_css_flags(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")

        await converter.convert_ebook_many(
            input_file,
            "pdf",
            options=ConversionOptions(pdf_font_profile="amiri"),
        )

        command = commands[0]
        assert _contains_flag_pair(command, "--pdf-serif-family", "Amiri")
        assert _contains_flag_pair(command, "--pdf-sans-family", "Amiri")
        assert _contains_flag_pair(command, "--embed-font-family", "Amiri")
        assert "--embed-all-fonts" in command
        assert _contains_flag_pair(command, "--extra-css", str(PDF_FONTS_DIR / "amiri.css"))

    asyncio.run(run())


def test_format_specific_flags_do_not_leak_to_other_outputs(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.txt"
        input_file.write_text("hello")

        await converter.convert_ebook_many(
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

        await converter.convert_ebook_many(
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

        await converter.convert_ebook_many(
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

        await converter.convert_ebook_many(input_file, "epub")
        await converter.convert_ebook_many(input_file, "epub", timeout=None)

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

        await converter.convert_ebook_many(input_file, "epub")
        await converter.convert_ebook_many(input_file, "epub", timeout=None)

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


def test_convert_ebook_many_split_capped_cleans_outputs(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        input_file = tmp_path / "book.epub"
        input_file.write_text("input")
        created_files: list[Path] = []

        def fake_split(_input_file: Path, _out_dir: Path) -> list[Path]:
            for index in range(MAX_SPLIT_OUTPUT_FILES + 1):
                output_file = tmp_path / f"part-{index}.epub"
                output_file.write_text("split")
                created_files.append(output_file)
            return created_files

        original_split = convert_utils.split_epub_by_volumes
        convert_utils.split_epub_by_volumes = fake_split
        try:
            result = await converter.convert_ebook_many(
                input_file,
                "epub",
                options=ConversionOptions(epub_split_volumes=True),
            )
        finally:
            convert_utils.split_epub_by_volumes = original_split

        assert result.split_capped is True
        assert result.split_count == MAX_SPLIT_OUTPUT_FILES + 1
        assert result.output_files == []
        assert all(not path.exists() for path in created_files)

    asyncio.run(run())


def test_convert_ebook_many_split_applies_volume_output_flags(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        input_file = tmp_path / "book.epub"
        input_file.write_text("input")

        split_outputs = [tmp_path / "part-1.epub", tmp_path / "part-2.epub"]
        for path in split_outputs:
            path.write_text("split")

        converted_options: list[ConversionOptions] = []
        compressed: list[Path] = []
        rtl_applied: list[Path] = []
        preprocess_calls: list[Path] = []

        original_split = convert_utils.split_epub_by_volumes
        original_rtl = convert_utils.set_epub_to_rtl

        async def fake_convert_non_bok(
            input_volume: Path,
            output_type: str,
            options: ConversionOptions,
            timeout: int | None = TASK_TIMEOUT,
        ) -> tuple[Path, bool | None, str]:
            converted_options.append(options)
            rebuilt = input_volume.with_name(f"{input_volume.stem}_.epub")
            rebuilt.write_text("rebuilt")
            return rebuilt, None, ""

        async def fake_compress(
            output_file: Path,
            output_type: str,
            timeout: int | None = TASK_TIMEOUT,
        ) -> str:
            compressed.append(output_file)
            return ""

        convert_utils.split_epub_by_volumes = lambda _input_file, _out_dir: split_outputs.copy()
        convert_utils.set_epub_to_rtl = lambda path: rtl_applied.append(path) or True
        converter._convert_non_bok = fake_convert_non_bok  # type: ignore[method-assign]
        converter._compress_cover = fake_compress  # type: ignore[method-assign]
        converter._preprocess_input_epub = (  # type: ignore[method-assign]
            lambda path, _options: preprocess_calls.append(path) or True
        )
        try:
            result = await converter.convert_ebook_many(
                input_file,
                "epub",
                options=ConversionOptions(
                    epub_split_volumes=True,
                    epub_version="3",
                    compress_cover=True,
                    force_rtl=True,
                    fix_epub=True,
                    flat_toc=True,
                    epub_standardize_footnotes=True,
                ),
            )
        finally:
            convert_utils.split_epub_by_volumes = original_split
            convert_utils.set_epub_to_rtl = original_rtl

        assert preprocess_calls == [input_file]
        assert result.split_capped is False
        assert len(result.output_files) == EXPECTED_SPLIT_OUTPUTS
        assert all(path.exists() for path in result.output_files)
        assert compressed == result.output_files
        assert rtl_applied == result.output_files
        assert len(converted_options) == EXPECTED_SPLIT_OUTPUTS
        assert all(option.epub_split_volumes is False for option in converted_options)
        assert all(option.fix_epub is False for option in converted_options)
        assert all(option.flat_toc is False for option in converted_options)
        assert all(option.epub_standardize_footnotes is False for option in converted_options)
        assert all(option.epub_version == "3" for option in converted_options)

        for path in result.output_files:
            path.unlink(missing_ok=True)

    asyncio.run(run())


def test_convert_ebook_many_split_returns_empty_when_unsplittable(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        converter = Converter()
        input_file = tmp_path / "book.epub"
        input_file.write_text("input")
        called: list[tuple[Path, str]] = []
        preprocess_calls: list[Path] = []

        original_split = convert_utils.split_epub_by_volumes

        async def fake_convert_non_bok(
            source_file: Path,
            output_type: str,
            options: ConversionOptions,
            timeout: int | None = TASK_TIMEOUT,
        ) -> tuple[Path, bool | None, str]:
            called.append((source_file, output_type))
            output_file = source_file.with_name("book_.epub")
            output_file.write_text("out")
            return output_file, None, ""

        convert_utils.split_epub_by_volumes = lambda _input_file, _out_dir: []
        converter._convert_non_bok = fake_convert_non_bok  # type: ignore[method-assign]
        converter._preprocess_input_epub = (  # type: ignore[method-assign]
            lambda path, _options: preprocess_calls.append(path) or True
        )
        try:
            result = await converter.convert_ebook_many(
                input_file,
                "epub",
                options=ConversionOptions(epub_split_volumes=True),
            )
        finally:
            convert_utils.split_epub_by_volumes = original_split

        assert called == []
        assert preprocess_calls == [input_file]
        assert result.output_files == []
        assert result.conversion_error == ""
        assert result.converted_to_rtl is True

    asyncio.run(run())


def test_convert_ebook_many_split_preprocess_ignores_flat_toc(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        input_file = tmp_path / "book.epub"
        input_file.write_text("input")
        preprocess_options: list[ConversionOptions] = []

        original_split = convert_utils.split_epub_by_volumes

        convert_utils.split_epub_by_volumes = lambda _input_file, _out_dir: []
        converter._preprocess_input_epub = (  # type: ignore[method-assign]
            lambda _path, options: preprocess_options.append(options) or None
        )
        requested_options = ConversionOptions(
            epub_split_volumes=True,
            flat_toc=True,
            fix_epub=True,
        )
        try:
            result = await converter.convert_ebook_many(
                input_file,
                "epub",
                options=requested_options,
            )
        finally:
            convert_utils.split_epub_by_volumes = original_split

        assert result.output_files == []
        assert len(preprocess_options) == 1
        assert preprocess_options[0].flat_toc is False
        assert preprocess_options[0].fix_epub is True
        assert requested_options.flat_toc is True

    asyncio.run(run())


def test_convert_ebook_many_split_missing_rebuild_output_fails_and_cleans(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        input_file = tmp_path / "book.epub"
        input_file.write_text("input")

        split_output = tmp_path / "part-1.epub"
        split_output.write_text("split")

        original_split = convert_utils.split_epub_by_volumes

        async def fake_convert_non_bok(
            source_file: Path,
            output_type: str,
            options: ConversionOptions,
            timeout: int | None = TASK_TIMEOUT,
        ) -> tuple[Path, bool | None, str]:
            assert source_file == split_output
            assert output_type == "epub"
            return source_file.with_name("missing_.epub"), None, ""

        convert_utils.split_epub_by_volumes = lambda _input_file, _out_dir: [split_output]
        converter._convert_non_bok = fake_convert_non_bok  # type: ignore[method-assign]
        try:
            result = await converter.convert_ebook_many(
                input_file,
                "epub",
                options=ConversionOptions(epub_split_volumes=True),
            )
        finally:
            convert_utils.split_epub_by_volumes = original_split

        assert result.output_files == []
        assert "Failed to rebuild split volume: part-1.epub" in result.conversion_error
        assert split_output.exists() is False

    asyncio.run(run())
