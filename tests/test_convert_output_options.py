import asyncio
import shutil
import subprocess
from pathlib import Path
from zipfile import ZipFile

import ebook_converter_bot.utils.convert as convert_utils
import pytest
from ebook_converter_bot.utils.convert import (
    DOCX_ARABIC_REFERENCE_DOC,
    MAX_SPLIT_OUTPUT_FILES,
    PDF_FONT_PROFILES,
    PDF_FONTS_DIR,
    TASK_TIMEOUT,
    ConversionOptions,
    Converter,
)

EXPECTED_SPLIT_OUTPUTS = 2
EXPECTED_RTL_PDF_COMMANDS = 2
EXPECTED_PANDOC_BASE_FILTERS = 2
EXPECTED_PANDOC_MD_FILTERS = 3
EXPECTED_PANDOC_RTL_EPUB_FILTERS = 3
EXPECTED_PANDOC_RTL_MD_FILTERS = 4
EXPECTED_PANDOC_DOCX_RTL_FILTERS = 4
EXPECTED_PANDOC_DOCX_RTL_MD_FILTERS = 5
EXPECTED_PANDOC_DOCX_RTL_HTML_FILTERS = 4
OPTION_CASES = [
    {
        "output_type": "docx",
        "options": ConversionOptions(
            smarten_punctuation=True,
            change_justification="left",
            line_height=150,
            remove_paragraph_spacing=True,
            docx_page_size="a4",
            docx_no_toc=True,
        ),
        "expected_flags": ["--smarten-punctuation", "--remove-paragraph-spacing", "--docx-no-toc"],
        "expected_pairs": [
            ("--change-justification", "left"),
            ("--minimum-line-height", "150"),
            ("--docx-page-size", "a4"),
        ],
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
            pdf_no_cover=True,
            pdf_no_chapter_pagebreak=True,
        ),
        "expected_flags": ["--pdf-page-numbers", "--pdf-no-cover"],
        "expected_pairs": [("--paper-size", "a4"), ("--chapter-mark", "none")],
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


def _lua_filter_args(output_file: Path, suffixes: list[str]) -> list[str]:
    return [f"--lua-filter={output_file.with_suffix(suffix)}" for suffix in suffixes]


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
                    force_rtl=True,
                    pdf_paper_size="a4",
                    pdf_page_numbers=True,
                    pdf_no_cover=True,
                    pdf_no_chapter_pagebreak=True,
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
        assert "--pdf-no-cover" not in commands[0]
        assert "--chapter-mark" not in commands[0]
        assert _contains_flag_pair(commands[1], "--paper-size", "a4")
        assert "--pdf-page-numbers" in commands[1]
        assert "--pdf-no-cover" in commands[1]
        assert _contains_flag_pair(commands[1], "--chapter-mark", "none")
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


def test_pdf_font_profiles_have_required_assets() -> None:
    assert {"scheherazade_new", "vazirmatn", "kfgqpc_uthman_taha", "adwaa_lotfi"} <= set(
        PDF_FONT_PROFILES
    )
    for profile in PDF_FONT_PROFILES.values():
        assert (PDF_FONTS_DIR / profile.css_file).exists()
        for required_file in profile.required_files:
            assert (PDF_FONTS_DIR / required_file).exists()


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
                pdf_no_cover=True,
                pdf_no_chapter_pagebreak=True,
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
        assert "--pdf-no-cover" not in command
        assert "--chapter-mark" not in command

    asyncio.run(run())


def test_calibre_backend_handles_shared_document_routes_by_default(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello")
        output_file = input_file.with_suffix(".epub")

        result = await converter.convert_ebook_many(input_file, "epub")

        assert result.output_files == [output_file]
        assert commands[0][:3] == ["ebook-convert", str(input_file), str(output_file)]

    asyncio.run(run())


def test_pandoc_backend_is_used_when_selected_for_shared_document_routes(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello")
        output_file = input_file.with_suffix(".epub")

        result = await converter.convert_ebook_many(
            input_file,
            "epub",
            options=ConversionOptions(conversion_backend="pandoc"),
        )

        assert result.output_files == [output_file]
        assert commands == [
            [
                "pandoc",
                str(input_file),
                "-f",
                "gfm",
                "-t",
                "epub",
                *_lua_filter_args(output_file, [".empty-blocks.lua", ".arabic-punctuation.lua"]),
                "-o",
                str(output_file),
            ]
        ]

    asyncio.run(run())


def test_pandoc_toc_and_number_sections_options_add_flags_for_supported_output(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello")
        output_file = input_file.with_suffix(".epub")

        result = await converter.convert_ebook_many(
            input_file,
            "epub",
            options=ConversionOptions(
                conversion_backend="pandoc",
                pandoc_toc=True,
                pandoc_number_sections=True,
            ),
        )

        assert result.output_files == [output_file]
        assert commands == [
            [
                "pandoc",
                str(input_file),
                "-f",
                "gfm",
                "-t",
                "epub",
                *_lua_filter_args(output_file, [".empty-blocks.lua", ".arabic-punctuation.lua"]),
                "--standalone",
                "--toc",
                "--number-sections",
                "-o",
                str(output_file),
            ]
        ]

    asyncio.run(run())


def test_pandoc_docx_rtl_and_heading_pagebreaks_add_lua_filters(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands: list[list[str]] = []
        input_file = tmp_path / "book.md"
        input_file.write_text("# عنوان\n\nنص\n\n## فرع")
        output_file = input_file.with_suffix(".docx")

        async def fake_run(
            command: list[str], timeout: int | None = TASK_TIMEOUT
        ) -> tuple[int | None, str]:
            commands.append(command)
            filter_paths = [
                Path(item.removeprefix("--lua-filter="))
                for item in command
                if item.startswith("--lua-filter=")
            ]
            assert len(filter_paths) == EXPECTED_PANDOC_DOCX_RTL_FILTERS
            assert "function Para" in filter_paths[0].read_text()
            assert "starts_arabic_punctuation" in filter_paths[1].read_text()
            assert 'w:br w:type="page"' in filter_paths[2].read_text()
            assert "dir = 'rtl'" in filter_paths[3].read_text()
            output_file.write_text("docx")
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]

        result = await converter.convert_ebook_many(
            input_file,
            "docx",
            options=ConversionOptions(
                conversion_backend="pandoc",
                force_rtl=True,
                docx_header_pagebreaks=True,
            ),
        )

        assert result.output_files == [output_file]
        assert result.converted_to_rtl is True
        assert commands[0] == [
            "pandoc",
            str(input_file),
            "-f",
            "gfm",
            "-t",
            "docx",
            *_lua_filter_args(
                output_file,
                [
                    ".empty-blocks.lua",
                    ".arabic-punctuation.lua",
                    ".docx-header-pagebreaks.lua",
                    ".rtl-wrap.lua",
                ],
            ),
            "-o",
            str(output_file),
        ]
        assert output_file.with_suffix(".empty-blocks.lua").exists() is False
        assert output_file.with_suffix(".arabic-punctuation.lua").exists() is False
        assert output_file.with_suffix(".docx-header-pagebreaks.lua").exists() is False
        assert output_file.with_suffix(".rtl-wrap.lua").exists() is False

    asyncio.run(run())


def test_pandoc_heading_shift_and_docx_reference_add_flags(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello")
        output_file = input_file.with_suffix(".docx")

        result = await converter.convert_ebook_many(
            input_file,
            "docx",
            options=ConversionOptions(
                conversion_backend="pandoc",
                pandoc_heading_shift=-1,
                docx_arabic_reference=True,
            ),
        )

        assert result.output_files == [output_file]
        assert _contains_flag_pair(commands[0], "--shift-heading-level-by", "-1")
        assert _contains_flag_pair(commands[0], "--reference-doc", str(DOCX_ARABIC_REFERENCE_DOC))

    asyncio.run(run())


def test_docx_heading_pagebreak_filter_accounts_for_heading_shift() -> None:
    content = Converter().pandoc_backend._docx_header_pagebreaks_filter_content(-1)

    assert "local heading_shift = -1" in content
    assert "block.level + heading_shift" in content


def test_pandoc_backend_rejects_same_format_alias_routes() -> None:
    converter = Converter()

    assert converter.pandoc_backend.supports("asciidoc", "adoc", ConversionOptions()) is False
    assert converter.pandoc_backend.supports("typst", "typ", ConversionOptions()) is False
    assert converter.pandoc_backend.supports("typ", "typst", ConversionOptions()) is False


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_docx_cleanup_filter_handles_pandoc_attribute_lists(tmp_path: Path) -> None:
    pandoc = shutil.which("pandoc")
    assert pandoc is not None
    lua_filter = tmp_path / "docx-cleanup.lua"
    lua_filter.write_text(Converter().pandoc_backend._docx_cleanup_filter_content())
    native_input = tmp_path / "input.native"
    native_input.write_text(
        '[ Header 1 ( "" , [] , [] ) [ Space , Str "Title" , Space ]'
        ' , Para [ Span ( "" , [] , [] ) [ Str "wrapped" ] ]'
        ' , Div ( "" , [] , [] ) [ Para [ Str "inside" ] ] ]'
    )

    result = subprocess.run(  # noqa: S603
        [
            pandoc,
            str(native_input),
            "-f",
            "native",
            "-t",
            "gfm+raw_html",
            f"--lua-filter={lua_filter}",
            "--wrap=none",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "# Title\n\nwrapped\n\ninside\n"


def test_docx_to_md_uses_pandoc_only_route(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.docx"
        input_file.write_text("hello")
        output_file = input_file.with_suffix(".md")

        result = await converter.convert_ebook_many(input_file, "md")

        assert result.output_files == [output_file]
        assert commands == [
            [
                "pandoc",
                str(input_file),
                "-f",
                "docx",
                "-t",
                "gfm+raw_html",
                "--wrap=none",
                "--markdown-headings=atx",
                f"--extract-media={tmp_path / 'book_media'}",
                *_lua_filter_args(
                    output_file,
                    [
                        ".docx-cleanup.lua",
                        ".empty-blocks.lua",
                        ".arabic-punctuation.lua",
                        ".bidi-cleanup.lua",
                    ],
                ),
                "-o",
                str(output_file),
            ]
        ]
        assert output_file.with_suffix(".docx-cleanup.lua").exists() is False
        assert output_file.with_suffix(".empty-blocks.lua").exists() is False
        assert output_file.with_suffix(".arabic-punctuation.lua").exists() is False
        assert output_file.with_suffix(".bidi-cleanup.lua").exists() is False

    asyncio.run(run())


def test_doc_to_epub_extracts_with_antiword_then_uses_calibre_by_default(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        antiword_commands: list[list[str]] = []
        commands: list[list[str]] = []
        input_file = tmp_path / "book.doc"
        input_file.write_bytes(b"legacy doc")
        output_file = input_file.with_suffix(".epub")

        async def fake_run(
            command: list[str],
            timeout: int | None = TASK_TIMEOUT,
            stdout_file: Path | None = None,
        ) -> tuple[int | None, str]:
            if stdout_file:
                antiword_commands.append(command)
                stdout_file.write_text("مرحبا\n")
                return 0, ""
            commands.append(command)
            Path(command[2]).write_text("converted")
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]

        result = await converter.convert_ebook_many(input_file, "epub")

        assert result.output_files == [output_file]
        assert result.conversion_error == ""
        assert output_file.read_text() == "converted"
        assert antiword_commands == [["antiword", "-m", "UTF-8.txt", "-w", "0", str(input_file)]]
        assert commands[0][0] == "ebook-convert"
        assert Path(commands[0][1]).suffix == ".txt"
        assert Path(commands[0][1]).exists() is False
        assert Path(commands[0][2]).suffix == ".epub"
        assert Path(commands[0][2]).exists() is False

    asyncio.run(run())


def test_doc_to_md_extracts_with_antiword_then_uses_pandoc_plain_input(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        converter = Converter()
        antiword_commands: list[list[str]] = []
        commands: list[list[str]] = []
        input_file = tmp_path / "book.doc"
        input_file.write_bytes(b"legacy doc")
        output_file = input_file.with_suffix(".md")

        async def fake_run(
            command: list[str],
            timeout: int | None = TASK_TIMEOUT,
            stdout_file: Path | None = None,
        ) -> tuple[int | None, str]:
            if stdout_file:
                antiword_commands.append(command)
                stdout_file.write_text("    indented text\n")
                return 0, ""
            commands.append(command)
            assert Path(command[1]).read_text() == "indented text\n"
            Path(command[-1]).write_text("converted")
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]

        result = await converter.convert_ebook_many(input_file, "md")

        assert result.output_files == [output_file]
        assert result.conversion_error == ""
        assert output_file.read_text() == "converted"
        assert antiword_commands == [["antiword", "-m", "UTF-8.txt", "-w", "0", str(input_file)]]
        assert commands[0][0] == "pandoc"
        assert Path(commands[0][1]).suffix == ".txt"
        assert commands[0][2:5] == ["-f", "markdown", "-t"]
        assert Path(commands[0][1]).exists() is False
        assert Path(commands[0][-1]).suffix == ".md"
        assert Path(commands[0][-1]).exists() is False

    asyncio.run(run())


def test_html_to_md_uses_pandoc_markdown_route(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.html"
        input_file.write_text("<h1>Hello</h1>")
        output_file = input_file.with_suffix(".md")

        result = await converter.convert_ebook_many(input_file, "md")

        assert result.output_files == [output_file]
        assert commands == [
            [
                "pandoc",
                str(input_file),
                "-f",
                "html",
                "-t",
                "gfm+raw_html",
                "--wrap=none",
                "--markdown-headings=atx",
                f"--extract-media={tmp_path / 'book_media'}",
                *_lua_filter_args(
                    output_file,
                    [".empty-blocks.lua", ".arabic-punctuation.lua", ".bidi-cleanup.lua"],
                ),
                "-o",
                str(output_file),
            ]
        ]
        assert output_file.with_suffix(".empty-blocks.lua").exists() is False
        assert output_file.with_suffix(".arabic-punctuation.lua").exists() is False
        assert output_file.with_suffix(".bidi-cleanup.lua").exists() is False

    asyncio.run(run())


def test_md_output_is_not_converted_for_non_pandoc_inputs(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.mobi"
        input_file.write_text("hello")
        output_file = input_file.with_suffix(".md")

        result = await converter.convert_ebook_many(input_file, "md")

        assert result.output_files == [output_file]
        assert commands == []

    asyncio.run(run())


def test_epub_to_md_uses_temporary_preprocessed_copy_and_keeps_source(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands: list[list[str]] = []
        preprocess_calls: list[Path] = []
        input_file = tmp_path / "book.epub"
        input_file.write_text("original")
        output_file = input_file.with_suffix(".md")

        def fake_preprocess(path: Path, options: ConversionOptions) -> None:
            preprocess_calls.append(path)
            assert options.fix_epub is True
            assert options.flat_toc is True
            assert options.epub_standardize_footnotes is True
            path.write_text("prepared")

        async def fake_run(
            command: list[str], timeout: int | None = TASK_TIMEOUT
        ) -> tuple[int | None, str]:
            commands.append(command)
            assert Path(command[1]).read_text() == "prepared"
            filter_paths = [
                Path(item.removeprefix("--lua-filter="))
                for item in command
                if item.startswith("--lua-filter=")
            ]
            assert len(filter_paths) == EXPECTED_PANDOC_RTL_MD_FILTERS
            assert "function Para" in filter_paths[0].read_text()
            assert "starts_arabic_punctuation" in filter_paths[1].read_text()
            assert "function Span" in filter_paths[2].read_text()
            assert "function Pandoc" in filter_paths[3].read_text()
            output_file.write_text("مرحبا")
            return 0, ""

        converter._preprocess_pandoc_epub = fake_preprocess  # type: ignore[method-assign]
        converter._run_command = fake_run  # type: ignore[method-assign]

        result = await converter.convert_ebook_many(
            input_file,
            "md",
            options=ConversionOptions(
                force_rtl=True,
                fix_epub=True,
                flat_toc=True,
                epub_standardize_footnotes=True,
            ),
        )

        prepared_file = Path(commands[0][1])
        assert result.output_files == [output_file]
        assert result.converted_to_rtl is True
        assert preprocess_calls == [prepared_file]
        assert prepared_file != input_file
        assert prepared_file.exists() is False
        assert input_file.read_text() == "original"
        assert output_file.read_text() == "مرحبا"
        assert commands[0][2:5] == ["-f", "epub", "-t"]
        assert "--lua-filter=" in " ".join(commands[0])
        assert output_file.with_suffix(".empty-blocks.lua").exists() is False
        assert output_file.with_suffix(".arabic-punctuation.lua").exists() is False
        assert output_file.with_suffix(".bidi-cleanup.lua").exists() is False
        assert output_file.with_suffix(".rtl-wrap.lua").exists() is False

    asyncio.run(run())


def test_docx_to_md_force_rtl_adds_lua_filters(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands: list[list[str]] = []
        input_file = tmp_path / "book.docx"
        input_file.write_text("hello")
        output_file = input_file.with_suffix(".md")

        async def fake_run(
            command: list[str], timeout: int | None = TASK_TIMEOUT
        ) -> tuple[int | None, str]:
            commands.append(command)
            filter_paths = [
                Path(item.removeprefix("--lua-filter="))
                for item in command
                if item.startswith("--lua-filter=")
            ]
            assert len(filter_paths) == EXPECTED_PANDOC_DOCX_RTL_MD_FILTERS
            assert "function Header" in filter_paths[0].read_text()
            assert "function Para" in filter_paths[1].read_text()
            assert "starts_arabic_punctuation" in filter_paths[2].read_text()
            assert "function Span" in filter_paths[3].read_text()
            assert "function Pandoc" in filter_paths[4].read_text()
            assert "dir = 'rtl'" in filter_paths[4].read_text()
            output_file.write_text("مرحبا\nhello")
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]

        result = await converter.convert_ebook_many(
            input_file,
            "md",
            options=ConversionOptions(force_rtl=True),
        )

        assert result.output_files == [output_file]
        assert result.converted_to_rtl is True
        assert "--lua-filter=" in " ".join(commands[0])
        assert output_file.with_suffix(".docx-cleanup.lua").exists() is False
        assert output_file.with_suffix(".empty-blocks.lua").exists() is False
        assert output_file.with_suffix(".arabic-punctuation.lua").exists() is False
        assert output_file.with_suffix(".bidi-cleanup.lua").exists() is False
        assert output_file.with_suffix(".rtl-wrap.lua").exists() is False
        assert output_file.read_text() == "مرحبا\nhello"

    asyncio.run(run())


def test_pandoc_epub_force_rtl_uses_lua_wrapper_without_epub_postprocess(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        converter = Converter()
        commands: list[list[str]] = []
        rtl_paths: list[Path] = []
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello")
        output_file = input_file.with_suffix(".epub")

        original_rtl = convert_utils.set_epub_to_rtl

        async def fake_run(
            command: list[str], timeout: int | None = TASK_TIMEOUT
        ) -> tuple[int | None, str]:
            commands.append(command)
            filter_paths = [
                Path(item.removeprefix("--lua-filter="))
                for item in command
                if item.startswith("--lua-filter=")
            ]
            assert len(filter_paths) == EXPECTED_PANDOC_RTL_EPUB_FILTERS
            assert "function Para" in filter_paths[0].read_text()
            assert "starts_arabic_punctuation" in filter_paths[1].read_text()
            assert "function Pandoc" in filter_paths[2].read_text()
            output_file.write_text("converted")
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]
        convert_utils.set_epub_to_rtl = lambda path: rtl_paths.append(path) or True
        try:
            result = await converter.convert_ebook_many(
                input_file,
                "epub",
                options=ConversionOptions(conversion_backend="pandoc", force_rtl=True),
            )
        finally:
            convert_utils.set_epub_to_rtl = original_rtl

        assert result.output_files == [output_file]
        assert result.converted_to_rtl is True
        assert rtl_paths == []
        assert commands[0] == [
            "pandoc",
            str(input_file),
            "-f",
            "gfm",
            "-t",
            "epub",
            *_lua_filter_args(
                output_file,
                [".empty-blocks.lua", ".arabic-punctuation.lua", ".rtl-wrap.lua"],
            ),
            "-o",
            str(output_file),
        ]
        assert output_file.with_suffix(".empty-blocks.lua").exists() is False
        assert output_file.with_suffix(".arabic-punctuation.lua").exists() is False
        assert output_file.with_suffix(".rtl-wrap.lua").exists() is False

    asyncio.run(run())


def test_pandoc_html_force_rtl_uses_lua_wrapper(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands: list[list[str]] = []
        input_file = tmp_path / "book.docx"
        input_file.write_text("hello")
        output_file = input_file.with_suffix(".html")

        async def fake_run(
            command: list[str], timeout: int | None = TASK_TIMEOUT
        ) -> tuple[int | None, str]:
            commands.append(command)
            filter_paths = [
                Path(item.removeprefix("--lua-filter="))
                for item in command
                if item.startswith("--lua-filter=")
            ]
            assert len(filter_paths) == EXPECTED_PANDOC_DOCX_RTL_HTML_FILTERS
            assert "function Header" in filter_paths[0].read_text()
            assert "function Para" in filter_paths[1].read_text()
            assert "starts_arabic_punctuation" in filter_paths[2].read_text()
            assert "function Pandoc" in filter_paths[3].read_text()
            output_file.write_text('<div dir="rtl">hello</div>')
            return 0, ""

        converter._run_command = fake_run  # type: ignore[method-assign]

        result = await converter.convert_ebook_many(
            input_file,
            "html",
            options=ConversionOptions(force_rtl=True),
        )

        assert result.output_files == [output_file]
        assert result.converted_to_rtl is True
        assert commands[0] == [
            "pandoc",
            str(input_file),
            "-f",
            "docx",
            "-t",
            "html5",
            *_lua_filter_args(
                output_file,
                [
                    ".docx-cleanup.lua",
                    ".empty-blocks.lua",
                    ".arabic-punctuation.lua",
                    ".rtl-wrap.lua",
                ],
            ),
            "-o",
            str(output_file),
        ]
        assert output_file.with_suffix(".docx-cleanup.lua").exists() is False
        assert output_file.with_suffix(".empty-blocks.lua").exists() is False
        assert output_file.with_suffix(".arabic-punctuation.lua").exists() is False
        assert output_file.with_suffix(".rtl-wrap.lua").exists() is False

    asyncio.run(run())


def test_pandoc_backend_is_used_for_pandoc_only_input_routes(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.rst"
        input_file.write_text("Hello\n=====\n")
        output_file = input_file.with_suffix(".epub")

        result = await converter.convert_ebook_many(input_file, "epub")

        assert result.output_files == [output_file]
        assert commands == [
            [
                "pandoc",
                str(input_file),
                "-f",
                "rst",
                "-t",
                "epub",
                *_lua_filter_args(output_file, [".empty-blocks.lua", ".arabic-punctuation.lua"]),
                "-o",
                str(output_file),
            ]
        ]

    asyncio.run(run())


def test_pandoc_extended_input_and_output_route_uses_format_mapping(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.adoc"
        input_file.write_text("= Hello\n\nBody")
        output_file = input_file.with_suffix(".rst")

        result = await converter.convert_ebook_many(input_file, "rst")

        assert result.output_files == [output_file]
        assert commands == [
            [
                "pandoc",
                str(input_file),
                "-f",
                "asciidoc",
                "-t",
                "rst",
                *_lua_filter_args(output_file, [".empty-blocks.lua", ".arabic-punctuation.lua"]),
                "-o",
                str(output_file),
            ]
        ]

    asyncio.run(run())


def test_pandoc_backend_selected_for_existing_txt_output_when_requested(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello")
        output_file = input_file.with_suffix(".txt")

        result = await converter.convert_ebook_many(
            input_file,
            "txt",
            options=ConversionOptions(conversion_backend="pandoc"),
        )

        assert result.output_files == [output_file]
        assert commands == [
            [
                "pandoc",
                str(input_file),
                "-f",
                "gfm",
                "-t",
                "plain",
                *_lua_filter_args(output_file, [".empty-blocks.lua", ".arabic-punctuation.lua"]),
                "-o",
                str(output_file),
            ]
        ]

    asyncio.run(run())


def test_calibre_backend_is_used_when_pandoc_is_selected_with_calibre_specific_options(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        converter = Converter()
        commands = _capture_commands(converter)
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello")
        output_file = input_file.with_suffix(".epub")

        result = await converter.convert_ebook_many(
            input_file,
            "epub",
            options=ConversionOptions(conversion_backend="pandoc", epub_version="3"),
        )

        assert result.output_files == [output_file]
        assert commands[0][:3] == ["ebook-convert", str(input_file), str(output_file)]
        assert _contains_flag_pair(commands[0], "--epub-version", "3")

    asyncio.run(run())


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("output_type", ["epub", "docx"])
def test_pandoc_smoke_outputs_supported_formats(tmp_path: Path, output_type: str) -> None:
    async def run() -> None:
        converter = Converter()
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello\n\nBody text.\n\n[^1]: Footnote text.\n")
        output_file = input_file.with_suffix(f".{output_type}")

        result = await converter.convert_ebook_many(
            input_file,
            output_type,
            options=ConversionOptions(conversion_backend="pandoc"),
        )

        assert result.conversion_error == ""
        assert result.output_files == [output_file]
        assert output_file.exists()
        assert output_file.stat().st_size > 0
        with ZipFile(output_file) as archive:
            assert archive.namelist()

    asyncio.run(run())


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.parametrize("output_type", ["adoc", "html", "org", "rst", "tex", "txt", "typ"])
def test_pandoc_smoke_outputs_extended_markup_formats(
    tmp_path: Path,
    output_type: str,
) -> None:
    async def run() -> None:
        converter = Converter()
        input_file = tmp_path / "book.md"
        input_file.write_text("# Hello\n\nBody text.\n")
        output_file = input_file.with_suffix(f".{output_type}")

        result = await converter.convert_ebook_many(
            input_file,
            output_type,
            options=ConversionOptions(conversion_backend="pandoc"),
        )

        assert result.conversion_error == ""
        assert result.output_files == [output_file]
        assert output_file.exists()
        assert output_file.stat().st_size > 0

    asyncio.run(run())


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
def test_pandoc_smoke_outputs_markdown_from_docx(tmp_path: Path) -> None:
    async def run() -> None:
        converter = Converter()
        source_md = tmp_path / "source.md"
        arabic_body = "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645"
        source_md.write_text(f"# \u0639\u0646\u0648\u0627\u0646\n\n{arabic_body}.")
        input_file = tmp_path / "book.docx"
        await converter._run_command(["pandoc", str(source_md), "-o", str(input_file)])
        output_file = input_file.with_suffix(".md")

        result = await converter.convert_ebook_many(
            input_file,
            "md",
            options=ConversionOptions(force_rtl=True),
        )

        assert result.conversion_error == ""
        assert result.output_files == [output_file]
        assert result.converted_to_rtl is True
        assert output_file.exists()
        content = output_file.read_text()
        assert 'dir="rtl"' in content
        assert 'lang="ar"' in content
        assert "<span dir=" not in content
        assert arabic_body in content

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
