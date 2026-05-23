import asyncio
import logging
import re
from asyncio.subprocess import PIPE, STDOUT, Process
from dataclasses import dataclass, replace
from os import getpgid, killpg, setsid
from pathlib import Path
from shutil import copy2
from signal import SIGKILL
from tempfile import NamedTemporaryFile
from typing import ClassVar

from ebook_converter_bot.utils.bok_to_epub import bok_to_epub
from ebook_converter_bot.utils.epub import (
    fix_content_opf_problems,
    flatten_toc,
    set_epub_to_rtl,
    standardize_epub_footnotes,
)
from ebook_converter_bot.utils.epub_split import split_epub_by_volumes
from ebook_converter_bot.utils.pdf import pdf_to_htmlz

logger = logging.getLogger(__name__)

TASK_TIMEOUT = 600  # 10 min
MAX_SPLIT_OUTPUT_FILES = 35
PDF_FONTS_DIR = Path(__file__).resolve().parents[1] / "data" / "fonts" / "pdf"


@dataclass(frozen=True)
class PdfFontProfile:
    serif_family: str
    sans_family: str
    embed_family: str
    css_file: str
    required_files: tuple[str, ...]


PDF_FONT_PROFILES: dict[str, PdfFontProfile] = {
    "noto_naskh_arabic": PdfFontProfile(
        serif_family="Noto Naskh Arabic",
        sans_family="Noto Naskh Arabic",
        embed_family="Noto Naskh Arabic",
        css_file="noto_naskh_arabic.css",
        required_files=(
            "noto_naskh_arabic/NotoNaskhArabic-Regular.ttf",
            "noto_naskh_arabic/NotoNaskhArabic-Bold.ttf",
        ),
    ),
    "amiri": PdfFontProfile(
        serif_family="Amiri",
        sans_family="Amiri",
        embed_family="Amiri",
        css_file="amiri.css",
        required_files=("amiri/Amiri-Regular.ttf", "amiri/Amiri-Bold.ttf"),
    ),
    "ibm_plex_sans_arabic": PdfFontProfile(
        serif_family="IBM Plex Sans Arabic",
        sans_family="IBM Plex Sans Arabic",
        embed_family="IBM Plex Sans Arabic",
        css_file="ibm_plex_sans_arabic.css",
        required_files=(
            "ibm_plex_sans_arabic/IBMPlexSansArabic-Regular.ttf",
            "ibm_plex_sans_arabic/IBMPlexSansArabic-Bold.ttf",
        ),
    ),
}


@dataclass
class ConversionOptions:
    force_rtl: bool = False
    compress_cover: bool = False
    fix_epub: bool = False
    flat_toc: bool = False
    smarten_punctuation: bool = False
    change_justification: str = "original"
    line_height: int | None = None
    remove_paragraph_spacing: bool = False
    kfx_doc_type: str = "doc"
    kfx_pages: int | None = None
    docx_page_size: str = "default"
    docx_no_toc: bool = False
    docx_header_pagebreaks: bool = False
    epub_version: str = "default"
    epub_inline_toc: bool = False
    epub_remove_background: bool = False
    epub_split_volumes: bool = False
    epub_standardize_footnotes: bool = False
    pdf_paper_size: str = "default"
    pdf_font_profile: str = "default"
    pdf_page_numbers: bool = False
    pdf_no_cover: bool = True
    pdf_no_chapter_pagebreak: bool = False
    conversion_backend: str = "calibre"
    pandoc_toc: bool = False
    pandoc_number_sections: bool = False


@dataclass
class ConversionBatchResult:
    output_files: list[Path]
    converted_to_rtl: bool | None
    conversion_error: str = ""
    split_capped: bool = False
    split_count: int = 0


class ConversionBackend:
    name: ClassVar[str]

    def supports(
        self,
        input_type: str,
        output_type: str,
        options: ConversionOptions,
    ) -> bool:
        raise NotImplementedError

    async def convert(
        self,
        input_file: Path,
        output_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> str:
        raise NotImplementedError


class CalibreBackend(ConversionBackend):
    name: ClassVar[str] = "calibre"

    def __init__(self, converter: Converter) -> None:
        self.converter = converter

    def supports(
        self,
        input_type: str,
        output_type: str,
        options: ConversionOptions,
    ) -> bool:
        return (
            input_type not in self.converter.pandoc_only_input_types
            and output_type in self.converter.calibre_output_types
        )

    async def convert(
        self,
        input_file: Path,
        output_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> str:
        command = ["ebook-convert", str(input_file), str(output_file)]
        self.converter._append_ebook_convert_options(command, output_type, options)
        _, conversion_error = await self.converter._run_command(command, timeout=timeout)
        return conversion_error


class PandocBackend(ConversionBackend):
    name: ClassVar[str] = "pandoc"
    input_format_by_type: ClassVar[dict[str, str]] = {
        "adoc": "asciidoc",
        "asciidoc": "asciidoc",
        "docx": "docx",
        "epub": "epub",
        "html": "html",
        "md": "gfm",
        "mediawiki": "mediawiki",
        "odt": "odt",
        "org": "org",
        "rst": "rst",
        "rtf": "rtf",
        "t2t": "t2t",
        "tex": "latex",
        "textile": "textile",
        "tsv": "tsv",
        "txt": "markdown",
        "typ": "typst",
        "typst": "typst",
    }
    output_format_by_type: ClassVar[dict[str, str]] = {
        "adoc": "asciidoc",
        "docx": "docx",
        "epub": "epub",
        "html": "html5",
        "md": "gfm+raw_html",
        "org": "org",
        "rst": "rst",
        "tex": "latex",
        "txt": "plain",
        "typ": "typst",
        "typst": "typst",
    }
    markdown_output_types: ClassVar[set[str]] = {"md"}
    rtl_output_types: ClassVar[set[str]] = {"docx", "epub", "html", "md"}
    toc_output_types: ClassVar[set[str]] = {
        "docx",
        "epub",
        "html",
        "md",
        "rst",
        "tex",
        "typ",
        "typst",
    }
    number_sections_output_types: ClassVar[set[str]] = {
        "docx",
        "epub",
        "html",
        "tex",
    }
    supported_input_types: ClassVar[set[str]] = set(input_format_by_type)
    supported_output_types: ClassVar[set[str]] = set(output_format_by_type)

    def __init__(self, converter: Converter) -> None:
        self.converter = converter

    @staticmethod
    def _uses_unsupported_options(
        input_type: str,
        output_type: str,
        options: ConversionOptions,
    ) -> bool:
        rtl_supported = output_type in PandocBackend.rtl_output_types
        epub_preprocess_supported = input_type == "epub"
        return any(
            (
                options.force_rtl and not rtl_supported,
                options.compress_cover,
                options.fix_epub and not epub_preprocess_supported,
                options.flat_toc and not epub_preprocess_supported,
                options.smarten_punctuation,
                options.change_justification != "original",
                options.line_height is not None,
                options.remove_paragraph_spacing,
                options.kfx_doc_type != "doc",
                options.kfx_pages is not None,
                options.docx_page_size != "default",
                options.docx_no_toc,
                options.docx_header_pagebreaks and output_type != "docx",
                options.epub_version != "default",
                options.epub_inline_toc,
                options.epub_remove_background,
                options.epub_split_volumes,
                options.epub_standardize_footnotes and not epub_preprocess_supported,
                options.pdf_paper_size != "default",
                options.pdf_font_profile != "default",
                options.pdf_page_numbers,
                options.pdf_no_cover and output_type == "pdf",
                options.pdf_no_chapter_pagebreak,
                options.pandoc_toc and output_type not in PandocBackend.toc_output_types,
                options.pandoc_number_sections
                and output_type not in PandocBackend.number_sections_output_types,
            )
        )

    @classmethod
    def is_same_format_route(cls, input_type: str, output_type: str) -> bool:
        return input_type == output_type or cls.input_format_by_type.get(
            input_type
        ) == cls.output_format_by_type.get(output_type)

    def supports(
        self,
        input_type: str,
        output_type: str,
        options: ConversionOptions,
    ) -> bool:
        return (
            input_type in self.supported_input_types
            and output_type in self.supported_output_types
            and not self.is_same_format_route(input_type, output_type)
            and not self._uses_unsupported_options(input_type, output_type, options)
        )

    @staticmethod
    def _rtl_wrap_filter_content() -> str:
        return """function Pandoc(doc)
  return pandoc.Pandoc({
    pandoc.Div(doc.blocks, pandoc.Attr('', {}, { dir = 'rtl', lang = 'ar' }))
  }, doc.meta)
end
"""

    @staticmethod
    def _bidi_span_cleanup_filter_content() -> str:
        return """function Span(span)
  if span.identifier ~= '' or #span.classes > 0 then
    return span
  end

  local attr_count = 0
  for key, _ in pairs(span.attributes) do
    attr_count = attr_count + 1
    if key ~= 'dir' then
      return span
    end
  end

  if attr_count == 1 and (span.attributes.dir == 'rtl' or span.attributes.dir == 'ltr') then
    return span.content
  end

  return span
end
"""

    @staticmethod
    def _remove_empty_blocks_filter_content() -> str:
        return """local function has_visible_inline(inline)
  if inline.t == 'Str' then
    return inline.text:match('%S') ~= nil
  end
  if inline.t == 'Space' or inline.t == 'SoftBreak' or inline.t == 'LineBreak' then
    return false
  end
  return true
end

local function has_visible_inlines(inlines)
  for _, inline in ipairs(inlines) do
    if has_visible_inline(inline) then
      return true
    end
  end
  return false
end

function Para(para)
  if not has_visible_inlines(para.content) then
    return {}
  end
  return para
end

function Plain(plain)
  if not has_visible_inlines(plain.content) then
    return {}
  end
  return plain
end
"""

    @staticmethod
    def _arabic_punctuation_filter_content() -> str:
        return """local function starts_arabic_punctuation(inline)
  if inline.t ~= 'Str' then
    return false
  end

  local first = inline.text:sub(1, 2)
  return first == '،' or first == '؛' or first == '؟'
end

function Inlines(inlines)
  local result = {}
  for index, inline in ipairs(inlines) do
    if inline.t == 'Space' and starts_arabic_punctuation(inlines[index + 1]) then
      goto continue
    end
    table.insert(result, inline)
    ::continue::
  end
  return result
end

function Str(str)
  str.text = str.text
    :gsub('%s+،', '،')
    :gsub('%s+؛', '؛')
    :gsub('%s+؟', '؟')
    :gsub('،%s%s+', '، ')
    :gsub('؛%s%s+', '؛ ')
    :gsub('؟%s%s+', '؟ ')
  return str
end
"""

    @staticmethod
    def _docx_cleanup_filter_content() -> str:
        return """local function has_empty_attributes(attributes)
  for _, _ in pairs(attributes) do
    return false
  end
  return true
end

local function has_empty_attr(element)
  return element.identifier == '' and #element.classes == 0 and has_empty_attributes(element.attributes)
end

local function trim_inlines(inlines)
  while #inlines > 0 do
    local first = inlines[1]
    if first.t == 'Space' or first.t == 'SoftBreak' or first.t == 'LineBreak' then
      table.remove(inlines, 1)
    elseif first.t == 'Str' and first.text:match('^%s*$') then
      table.remove(inlines, 1)
    else
      break
    end
  end

  while #inlines > 0 do
    local last = inlines[#inlines]
    if last.t == 'Space' or last.t == 'SoftBreak' or last.t == 'LineBreak' then
      table.remove(inlines)
    elseif last.t == 'Str' and last.text:match('^%s*$') then
      table.remove(inlines)
    else
      break
    end
  end

  return inlines
end

function Span(span)
  if has_empty_attr(span) then
    return span.content
  end
  return span
end

function Div(div)
  if has_empty_attr(div) then
    return div.content
  end
  return div
end

function Header(header)
  header.content = trim_inlines(header.content)
  if #header.content == 0 then
    return {}
  end
  return header
end
"""

    @staticmethod
    def _docx_header_pagebreaks_filter_content() -> str:
        return """local page_break = pandoc.RawBlock('openxml', '<w:p><w:r><w:br w:type="page" /></w:r></w:p>')

function Pandoc(doc)
  local blocks = {}
  local seen_heading = false
  for _, block in ipairs(doc.blocks) do
    if block.t == 'Header' and block.level <= 2 then
      if seen_heading then
        table.insert(blocks, page_break)
      end
      seen_heading = true
    end
    table.insert(blocks, block)
  end
  return pandoc.Pandoc(blocks, doc.meta)
end
"""

    @staticmethod
    def _write_lua_filter(output_file: Path, suffix: str, content: str) -> Path:
        lua_filter = output_file.with_suffix(suffix)
        lua_filter.write_text(content)
        return lua_filter

    def _write_lua_filters(
        self,
        output_file: Path,
        input_type: str,
        output_type: str,
        options: ConversionOptions,
    ) -> list[Path]:
        filters: list[Path] = []
        if input_type == "docx":
            filters.append(
                self._write_lua_filter(
                    output_file,
                    ".docx-cleanup.lua",
                    self._docx_cleanup_filter_content(),
                )
            )
        filters.append(
            self._write_lua_filter(
                output_file,
                ".empty-blocks.lua",
                self._remove_empty_blocks_filter_content(),
            )
        )
        filters.append(
            self._write_lua_filter(
                output_file,
                ".arabic-punctuation.lua",
                self._arabic_punctuation_filter_content(),
            )
        )
        if output_type in self.markdown_output_types:
            filters.append(
                self._write_lua_filter(
                    output_file,
                    ".bidi-cleanup.lua",
                    self._bidi_span_cleanup_filter_content(),
                )
            )
        if options.docx_header_pagebreaks and output_type == "docx":
            filters.append(
                self._write_lua_filter(
                    output_file,
                    ".docx-header-pagebreaks.lua",
                    self._docx_header_pagebreaks_filter_content(),
                )
            )
        if options.force_rtl and output_type in self.rtl_output_types:
            filters.append(
                self._write_lua_filter(
                    output_file, ".rtl-wrap.lua", self._rtl_wrap_filter_content()
                )
            )
        return filters

    @staticmethod
    def _append_lua_filters(command: list[str], lua_filters: list[Path]) -> None:
        command.extend(f"--lua-filter={lua_filter}" for lua_filter in lua_filters)

    def _append_pandoc_options(
        self,
        command: list[str],
        output_type: str,
        options: ConversionOptions,
    ) -> None:
        add_toc = options.pandoc_toc and output_type in self.toc_output_types
        add_number_sections = (
            options.pandoc_number_sections and output_type in self.number_sections_output_types
        )
        if add_toc or add_number_sections:
            command.append("--standalone")
        if add_toc:
            command.append("--toc")
        if add_number_sections:
            command.append("--number-sections")

    def _prepare_input_file(self, input_file: Path, options: ConversionOptions) -> Path:
        if input_file.suffix.lower() != ".epub":
            return input_file
        with NamedTemporaryFile(
            dir=input_file.parent,
            prefix=f"{input_file.stem}.pandoc-",
            suffix=".epub",
            delete=False,
        ) as temp_file:
            prepared_file = Path(temp_file.name)
        copy2(input_file, prepared_file)
        self.converter._preprocess_pandoc_epub(prepared_file, options)
        return prepared_file

    async def _convert_to_markdown(
        self,
        input_file: Path,
        output_file: Path,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> str:
        media_dir = output_file.with_name(f"{output_file.stem}_media")
        input_type = input_file.suffix.lower()[1:]
        command = [
            "pandoc",
            str(input_file),
            "-f",
            self.input_format_by_type[input_type],
            "-t",
            self.output_format_by_type["md"],
            "--wrap=none",
            "--markdown-headings=atx",
            f"--extract-media={media_dir}",
        ]
        lua_filters = self._write_lua_filters(output_file, input_type, "md", options)
        self._append_lua_filters(command, lua_filters)
        self._append_pandoc_options(command, "md", options)
        command.extend(["-o", str(output_file)])
        try:
            _, conversion_error = await self.converter._run_command(command, timeout=timeout)
            return conversion_error
        finally:
            for lua_filter in lua_filters:
                lua_filter.unlink(missing_ok=True)

    async def convert(
        self,
        input_file: Path,
        output_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> str:
        prepared_input = self._prepare_input_file(input_file, options)
        lua_filters: list[Path] = []
        try:
            if output_type in self.markdown_output_types:
                return await self._convert_to_markdown(
                    prepared_input,
                    output_file,
                    options,
                    timeout=timeout,
                )
            input_type = prepared_input.suffix.lower()[1:]
            command = [
                "pandoc",
                str(prepared_input),
                "-f",
                self.input_format_by_type[input_type],
                "-t",
                self.output_format_by_type[output_type],
            ]
            lua_filters = self._write_lua_filters(output_file, input_type, output_type, options)
            self._append_lua_filters(command, lua_filters)
            self._append_pandoc_options(command, output_type, options)
            command.extend(["-o", str(output_file)])
            _, conversion_error = await self.converter._run_command(
                command,
                timeout=timeout,
            )
            return conversion_error
        finally:
            for lua_filter in lua_filters:
                lua_filter.unlink(missing_ok=True)
            if prepared_input != input_file:
                prepared_input.unlink(missing_ok=True)


class Converter:
    polish_supported_types: ClassVar[set[str]] = {"azw3", "epub", "kepub"}
    pandoc_only_input_types: ClassVar[set[str]] = {
        "adoc",
        "asciidoc",
        "mediawiki",
        "org",
        "rst",
        "t2t",
        "tex",
        "textile",
        "tsv",
        "typ",
        "typst",
    }
    pandoc_only_output_types: ClassVar[list[str]] = [
        "adoc",
        "html",
        "md",
        "org",
        "rst",
        "tex",
        "typ",
        "typst",
    ]
    pandoc_output_types: ClassVar[list[str]] = [
        "docx",
        "epub",
        *pandoc_only_output_types,
        "txt",
    ]
    pandoc_input_types: ClassVar[set[str]] = set(PandocBackend.supported_input_types)
    shared_backend_input_types: ClassVar[set[str]] = {
        "docx",
        "epub",
        "html",
        "md",
        "odt",
        "rtf",
        "txt",
    }
    supported_input_types: ClassVar[list[str]] = [
        "azw",
        "azw3",
        "azw4",
        "azw8",
        "adoc",
        "asciidoc",
        "cb7",
        "cbc",
        "cbr",
        "cbz",
        "chm",
        "djvu",
        "docx",
        "doc",
        "kepub",
        "epub",
        "fb2",
        "fbz",
        "html",
        "htmlz",
        "kfx",
        "kfx-zip",
        "kpf",
        "lit",
        "lrf",
        "md",
        "mobi",
        "mediawiki",
        "odt",
        "opf",
        "org",
        "pdb",
        "pml",
        "prc",
        "rb",
        "rst",
        "rtf",
        "snb",
        "tcr",
        "tex",
        "textile",
        "tsv",
        "txt",
        "txtz",
        "t2t",
        "typ",
        "typst",
        "bok",
        "pdf",
    ]
    calibre_output_types: ClassVar[list[str]] = [
        "azw3",
        "docx",
        "epub",
        "fb2",
        "htmlz",
        "kepub",
        "kfx",
        "lit",
        "lrf",
        "mobi",
        "oeb",
        "pdb",
        "pdf",
        "pmlz",
        "rb",
        "rtf",
        "snb",
        "tcr",
        "txt",
        "txtz",
        "zip",
    ]
    supported_output_types: ClassVar[list[str]] = [
        *calibre_output_types,
        *pandoc_only_output_types,
    ]
    kfx_output_allowed_types: ClassVar[list[str]] = [
        "epub",
        "opf",
        "mobi",
        "doc",
        "docx",
        "kpf",
        "kfx-zip",
    ]
    kfx_input_allowed_types: ClassVar[list[str]] = ["azw8", "kfx", "kfx-zip"]

    def __init__(self) -> None:
        self.calibre_backend = CalibreBackend(self)
        self.pandoc_backend = PandocBackend(self)

    @classmethod
    def get_supported_types(cls) -> list[str]:
        return sorted(set(cls.supported_input_types + cls.supported_output_types))

    @classmethod
    def get_supported_output_types_for_input(cls, input_type: str) -> list[str]:
        if input_type == "doc":
            return [*cls.calibre_output_types, *cls.pandoc_only_output_types]
        if input_type not in cls.pandoc_input_types:
            return cls.calibre_output_types
        if input_type in cls.pandoc_only_input_types:
            return [
                output_type
                for output_type in cls.pandoc_output_types
                if not PandocBackend.is_same_format_route(input_type, output_type)
            ]
        return [
            output_type
            for output_type in [*cls.calibre_output_types, *cls.pandoc_only_output_types]
            if (input_type == "epub" and output_type == "epub")
            or not PandocBackend.is_same_format_route(input_type, output_type)
        ]

    def is_supported_input_type(self, input_file: str | None) -> bool:
        if not input_file:
            return False
        return input_file.lower().split(".")[-1] in self.supported_input_types

    @staticmethod
    async def _run_command(
        command: list[str],
        timeout: int | None = TASK_TIMEOUT,
        stdout_file: Path | None = None,
    ) -> tuple[int | None, str]:
        conversion_error = ""
        stdout_handle = stdout_file.open("wb") if stdout_file else None
        try:
            process: Process = await asyncio.create_subprocess_exec(
                *command,
                stdin=PIPE,
                stdout=stdout_handle or PIPE,
                stderr=PIPE if stdout_file else STDOUT,
                preexec_fn=setsid,
            )
        except FileNotFoundError:
            if stdout_handle:
                stdout_handle.close()
            return None, f"{command[0]} is required but was not found."

        try:
            timeout_error = ""
            if timeout is None:
                stdout, stderr = await process.communicate()
            else:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            output_bytes = stderr if stdout_file else stdout
            output = "\n".join(
                [
                    i
                    for i in (output_bytes or b"").decode(errors="replace").splitlines()
                    if all(word not in i for word in [":fixme:", "DEBUG -", "INFO -"])
                ]
            )
            logger.info(output)
            if errors_list := re.findall(
                r"(Conversion Failure Reason\s+\*{5,}\s+[E\d]+:.*)|(Conversion error: .*)",
                output,
            ):
                conversion_error = "\n".join(
                    [error[0].strip() or error[1].strip() for error in errors_list]
                ).replace("*", "")
            elif process.returncode not in (0, None) and output:
                conversion_error = output
        except asyncio.exceptions.TimeoutError:
            logger.info(f"Timeout while running command: {command}")
            timeout_error = f"Timeout while running command: {command[0]}"
        try:
            # If it timed out terminate the process and its child processes.
            killpg(getpgid(process.pid), SIGKILL)
            process.kill()
        except OSError:
            pass  # Ignore 'no such process' error
        if stdout_handle:
            stdout_handle.close()
        return process.returncode, conversion_error or timeout_error

    @staticmethod
    def _append_common_options(command: list[str], options: ConversionOptions) -> None:
        if options.smarten_punctuation:
            command.append("--smarten-punctuation")
        if options.remove_paragraph_spacing:
            command.append("--remove-paragraph-spacing")
        if options.change_justification != "original":
            command.extend(["--change-justification", options.change_justification])
        if options.line_height is not None:
            command.extend(["--minimum-line-height", str(options.line_height)])

    @staticmethod
    def _append_docx_options(command: list[str], options: ConversionOptions) -> None:
        command.extend(["--filter-css", "float"])
        if options.docx_page_size != "default":
            command.extend(["--docx-page-size", options.docx_page_size])
        if options.docx_no_toc:
            command.append("--docx-no-toc")

    @staticmethod
    def _append_epub_options(command: list[str], options: ConversionOptions) -> None:
        if options.epub_version != "default":
            command.extend(["--epub-version", options.epub_version])
        if options.epub_inline_toc:
            command.append("--epub-inline-toc")
        if options.epub_remove_background:
            command.extend(["--filter-css", "background,background-color,background-image"])

    @staticmethod
    def _append_pdf_options(command: list[str], options: ConversionOptions) -> None:
        if options.pdf_paper_size != "default":
            command.extend(["--paper-size", options.pdf_paper_size])
        if options.pdf_page_numbers:
            command.append("--pdf-page-numbers")
        if options.pdf_no_cover:
            command.append("--pdf-no-cover")
        if options.pdf_no_chapter_pagebreak:
            command.extend(["--chapter-mark", "none"])
        Converter._append_pdf_font_profile_options(command, options)

    @staticmethod
    def _append_pdf_font_profile_options(command: list[str], options: ConversionOptions) -> None:
        if options.pdf_font_profile == "default":
            return

        profile = PDF_FONT_PROFILES.get(options.pdf_font_profile)
        if not profile:
            logger.warning("Unknown PDF font profile: %s", options.pdf_font_profile)
            return

        css_path = PDF_FONTS_DIR / profile.css_file
        required_paths = [PDF_FONTS_DIR / file_path for file_path in profile.required_files]
        missing_paths = [path for path in [css_path, *required_paths] if not path.exists()]
        if missing_paths:
            logger.warning(
                "PDF font profile '%s' has missing assets: %s",
                options.pdf_font_profile,
                ", ".join(str(path) for path in missing_paths),
            )
            return

        command.extend(["--pdf-serif-family", profile.serif_family])
        command.extend(["--pdf-sans-family", profile.sans_family])
        command.extend(["--embed-font-family", profile.embed_family])
        command.append("--embed-all-fonts")
        command.extend(["--extra-css", str(css_path)])

    def _append_ebook_convert_options(
        self,
        command: list[str],
        output_type: str,
        options: ConversionOptions,
    ) -> None:
        self._append_common_options(command, options)
        if output_type == "docx":
            self._append_docx_options(command, options)
        elif output_type == "epub":
            self._append_epub_options(command, options)
        elif output_type == "pdf":
            self._append_pdf_options(command, options)

    def _select_backend(
        self,
        input_type: str,
        output_type: str,
        options: ConversionOptions,
    ) -> ConversionBackend:
        calibre_supported = self.calibre_backend.supports(input_type, output_type, options)
        pandoc_supported = self.pandoc_backend.supports(input_type, output_type, options)
        if options.conversion_backend == "pandoc" and pandoc_supported:
            return self.pandoc_backend
        if calibre_supported:
            return self.calibre_backend
        if pandoc_supported:
            return self.pandoc_backend
        return self.calibre_backend

    async def _convert_to_kfx(
        self,
        input_file: Path,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> tuple[int | None, str]:
        command = ["calibre-debug", "-r", "KFX Output", "--"]
        if options.kfx_doc_type == "book":
            command.append("--book")
        if options.kfx_pages is not None:
            command.extend(["--pages", str(options.kfx_pages)])
        command.append(str(input_file))
        return await self._run_command(command, timeout=timeout)

    async def _convert_from_kfx_to_epub(
        self, input_file: Path, timeout: int | None = TASK_TIMEOUT
    ) -> tuple[int | None, str]:
        return await self._run_command(
            ["calibre-debug", "-r", "KFX Input", "--", str(input_file)],
            timeout=timeout,
        )

    async def _compress_cover(
        self, output_file: Path, output_type: str, timeout: int | None = TASK_TIMEOUT
    ) -> str:
        if output_type not in self.polish_supported_types or not output_file.exists():
            return ""
        _, compression_error = await self._run_command(
            ["ebook-polish", "--compress-images", str(output_file)],
            timeout=timeout,
        )
        return compression_error

    async def _convert_from_bok(
        self,
        input_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> tuple[Path, bool | None, str]:
        epub_file = input_file.with_suffix(".epub")
        output_file = input_file.with_suffix(f".{output_type}")
        conversion_error = ""
        set_to_rtl: bool | None = None

        try:
            if timeout is None:
                await asyncio.to_thread(bok_to_epub, input_file, epub_file)
            else:
                await asyncio.wait_for(
                    asyncio.to_thread(bok_to_epub, input_file, epub_file), timeout=timeout
                )
        except Exception as e:  # noqa: BLE001
            return output_file, set_to_rtl, str(e)

        if options.force_rtl:
            set_to_rtl = set_epub_to_rtl(epub_file)

        if output_type == "epub":
            return epub_file, set_to_rtl, conversion_error

        if output_type == "kfx":
            _, conversion_error = await self._convert_to_kfx(epub_file, options, timeout=timeout)
            epub_file.unlink(missing_ok=True)
            return input_file.with_suffix(".kfx"), set_to_rtl, conversion_error

        if output_type == "kepub":
            output_file = input_file.with_suffix(".kepub")

        conversion_error = await self.calibre_backend.convert(
            epub_file, output_file, output_type, options, timeout=timeout
        )
        epub_file.unlink(missing_ok=True)
        return output_file, set_to_rtl, conversion_error

    async def _prepare_doc_input(
        self,
        input_file: Path,
        timeout: int | None = TASK_TIMEOUT,
    ) -> tuple[Path, str]:
        with NamedTemporaryFile(
            dir=input_file.parent,
            prefix=f"{input_file.stem}.antiword-",
            suffix=".txt",
            delete=False,
        ) as temp_file:
            prepared_file = Path(temp_file.name)

        return_code, conversion_error = await self._run_command(
            ["antiword", "-m", "UTF-8.txt", "-w", "0", str(input_file)],
            timeout=timeout,
            stdout_file=prepared_file,
        )
        if return_code != 0:
            prepared_file.unlink(missing_ok=True)
            return (
                prepared_file,
                conversion_error or "antiword failed to extract text from the .doc file.",
            )
        if not prepared_file.read_bytes().strip():
            prepared_file.unlink(missing_ok=True)
            return prepared_file, "antiword did not extract any text from the .doc file."

        text = prepared_file.read_text(errors="replace")
        prepared_file.write_text("\n".join(line.lstrip() for line in text.splitlines()) + "\n")
        return prepared_file, ""

    async def _convert_from_doc(
        self,
        input_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> tuple[Path, bool | None, str]:
        output_file = input_file.with_suffix(
            ".kepub" if output_type == "kepub" else f".{output_type}"
        )
        prepared_file, conversion_error = await self._prepare_doc_input(
            input_file,
            timeout=timeout,
        )
        if conversion_error:
            return output_file, None, conversion_error

        try:
            if output_type == "txt":
                copy2(prepared_file, output_file)
                return output_file, None, ""

            temp_output_file, converted_to_rtl, conversion_error = await self._convert_non_bok(
                prepared_file,
                output_type,
                options,
                timeout=timeout,
            )
            if not temp_output_file.exists():
                return (
                    output_file,
                    converted_to_rtl,
                    conversion_error
                    or f"Failed to convert the extracted DOC text to {output_type}.",
                )
            if temp_output_file != output_file:
                temp_output_file.replace(output_file)
            return output_file, converted_to_rtl, conversion_error
        finally:
            prepared_file.unlink(missing_ok=True)

    @staticmethod
    def _preprocess_input_epub(input_file: Path, options: ConversionOptions) -> bool | None:
        set_to_rtl: bool | None = None
        if options.force_rtl:
            set_to_rtl = set_epub_to_rtl(input_file)
        if options.fix_epub:
            fix_content_opf_problems(input_file)
        if options.flat_toc:
            flatten_toc(input_file)
        if options.epub_standardize_footnotes:
            standardize_epub_footnotes(input_file)
        return set_to_rtl

    @staticmethod
    def _preprocess_pandoc_epub(input_file: Path, options: ConversionOptions) -> None:
        if options.fix_epub:
            fix_content_opf_problems(input_file)
        if options.flat_toc:
            flatten_toc(input_file)
        if options.epub_standardize_footnotes:
            standardize_epub_footnotes(input_file)

    async def _convert_from_kfx_input(
        self,
        input_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> tuple[Path, bool | None, str]:
        output_file = input_file.with_suffix(
            ".kepub" if output_type == "kepub" else f".{output_type}"
        )
        _, conversion_error = await self._convert_from_kfx_to_epub(input_file, timeout=timeout)
        if output_type == "epub":
            set_to_rtl = set_epub_to_rtl(output_file) if options.force_rtl else None
            return output_file, set_to_rtl, conversion_error

        epub_file = input_file.with_suffix(".epub")
        set_to_rtl = set_epub_to_rtl(epub_file) if options.force_rtl else None
        output_conversion_error = await self.calibre_backend.convert(
            epub_file, output_file, output_type, options, timeout=timeout
        )
        epub_file.unlink(missing_ok=True)
        conversion_error = self._merge_errors(conversion_error, output_conversion_error)
        return output_file, set_to_rtl, conversion_error

    async def _convert_to_pdf_with_rtl_intermediate(
        self,
        input_file: Path,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> tuple[Path, bool | None, str]:
        output_file = input_file.with_suffix(".pdf")
        epub_options = replace(
            options,
            force_rtl=False,
            compress_cover=False,
            smarten_punctuation=False,
            change_justification="original",
            remove_paragraph_spacing=False,
            docx_page_size="default",
            docx_no_toc=False,
            docx_header_pagebreaks=False,
            epub_version="default",
            epub_inline_toc=False,
            epub_remove_background=False,
            epub_split_volumes=False,
            epub_standardize_footnotes=False,
            pdf_paper_size="default",
            pdf_font_profile="default",
            pdf_page_numbers=False,
            pdf_no_cover=False,
            pdf_no_chapter_pagebreak=False,
            conversion_backend="calibre",
        )
        epub_file, _ignored_rtl, conversion_error = await self._convert_non_bok(
            input_file, "epub", epub_options, timeout=timeout, prefer_calibre=True
        )
        if conversion_error:
            epub_file.unlink(missing_ok=True)
            return output_file, None, conversion_error
        if not epub_file.exists():
            return output_file, None, "Failed to build intermediate EPUB for RTL PDF conversion."

        set_to_rtl = set_epub_to_rtl(epub_file)
        try:
            pdf_options = replace(
                options,
                force_rtl=False,
                fix_epub=False,
                flat_toc=False,
                epub_standardize_footnotes=False,
                epub_split_volumes=False,
                epub_version="default",
                epub_inline_toc=False,
                epub_remove_background=False,
            )
            conversion_error = await self.calibre_backend.convert(
                epub_file, output_file, "pdf", pdf_options, timeout=timeout
            )
            return output_file, set_to_rtl, conversion_error
        finally:
            epub_file.unlink(missing_ok=True)

    async def _convert_non_bok(  # noqa: C901,PLR0911
        self,
        input_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
        prefer_calibre: bool = False,
    ) -> tuple[Path, bool | None, str]:
        conversion_error = ""
        input_type = input_file.suffix.lower()[1:]
        output_file = input_file.with_suffix(f".{output_type}")

        if output_type == "pdf" and options.force_rtl and input_type != "epub":
            return await self._convert_to_pdf_with_rtl_intermediate(
                input_file, options, timeout=timeout
            )

        backend = (
            self.calibre_backend
            if prefer_calibre
            else self._select_backend(input_type, output_type, options)
        )
        set_to_rtl = (
            self._preprocess_input_epub(input_file, options)
            if input_type == "epub" and backend is self.calibre_backend
            else None
        )
        rebuild_epub = (
            input_type == "epub"
            and output_type == "epub"
            and (
                options.smarten_punctuation
                or options.remove_paragraph_spacing
                or options.change_justification != "original"
                or options.epub_version != "default"
                or options.epub_inline_toc
                or options.epub_remove_background
            )
        )

        if input_type in self.kfx_input_allowed_types:
            return await self._convert_from_kfx_input(
                input_file, output_type, options, timeout=timeout
            )

        if output_type == "kfx":
            if input_type not in self.kfx_output_allowed_types:
                return output_file, set_to_rtl, conversion_error
            _, conversion_error = await self._convert_to_kfx(input_file, options, timeout=timeout)
            return output_file, set_to_rtl, conversion_error

        if output_type not in self.supported_output_types or (
            input_type == output_type and not rebuild_epub
        ):
            return output_file, set_to_rtl, conversion_error

        if output_type == "kepub":
            output_file = input_file.with_suffix(".kepub")
        elif rebuild_epub:
            output_file = input_file.with_name(f"{input_file.stem}_.epub")
            output_file.unlink(missing_ok=True)

        if not backend.supports(input_type, output_type, options):
            return output_file, set_to_rtl, conversion_error
        conversion_error = await backend.convert(
            input_file, output_file, output_type, options, timeout=timeout
        )

        if (
            options.force_rtl
            and backend is self.pandoc_backend
            and output_type in PandocBackend.rtl_output_types
        ):
            set_to_rtl = True
        elif output_type == "epub" and options.force_rtl:
            set_to_rtl = set_epub_to_rtl(output_file)

        return output_file, set_to_rtl, conversion_error

    async def _convert_from_pdf(
        self,
        input_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> tuple[Path, bool | None, str]:
        if output_type == "pdf":
            return input_file, None, ""

        htmlz_file = input_file.with_suffix(".htmlz")
        err = pdf_to_htmlz(input_file, htmlz_file)
        if err:
            htmlz_file.unlink(missing_ok=True)
            return input_file.with_suffix(f".{output_type}"), None, err

        try:
            if output_type == "kfx":
                epub_options = replace(
                    options,
                    compress_cover=False,
                    smarten_punctuation=False,
                    change_justification="original",
                    remove_paragraph_spacing=False,
                    docx_page_size="default",
                    docx_no_toc=False,
                    docx_header_pagebreaks=False,
                    epub_version="default",
                    epub_inline_toc=False,
                    epub_remove_background=False,
                    epub_split_volumes=False,
                    pdf_paper_size="default",
                    pdf_font_profile="default",
                    pdf_page_numbers=False,
                    pdf_no_cover=False,
                    pdf_no_chapter_pagebreak=False,
                    conversion_backend="calibre",
                )
                epub_file, set_to_rtl, conversion_error = await self._convert_non_bok(
                    htmlz_file, "epub", epub_options, timeout=timeout
                )
                if conversion_error:
                    epub_file.unlink(missing_ok=True)
                    return input_file.with_suffix(".kfx"), set_to_rtl, conversion_error

                _, conversion_error = await self._convert_to_kfx(
                    epub_file, options, timeout=timeout
                )
                epub_file.unlink(missing_ok=True)
                return input_file.with_suffix(".kfx"), set_to_rtl, conversion_error

            return await self._convert_non_bok(htmlz_file, output_type, options, timeout=timeout)
        finally:
            htmlz_file.unlink(missing_ok=True)

    @staticmethod
    def _cleanup_files(paths: list[Path]) -> None:
        for path in paths:
            path.unlink(missing_ok=True)

    @staticmethod
    def _merge_errors(*errors: str) -> str:
        return "\n".join([error for error in errors if error]).strip()

    async def _convert_epub_split_volumes(
        self,
        input_file: Path,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> ConversionBatchResult:
        preprocess_options = replace(options, flat_toc=False)
        set_to_rtl = self._preprocess_input_epub(input_file, preprocess_options)
        split_files = split_epub_by_volumes(input_file, input_file.parent)
        if not split_files:
            return ConversionBatchResult([], set_to_rtl)

        if len(split_files) > MAX_SPLIT_OUTPUT_FILES:
            self._cleanup_files(split_files)
            return ConversionBatchResult(
                [],
                set_to_rtl,
                split_capped=True,
                split_count=len(split_files),
            )

        volume_options = replace(
            options,
            force_rtl=False,
            fix_epub=False,
            flat_toc=False,
            epub_standardize_footnotes=False,
            epub_split_volumes=False,
            compress_cover=False,
        )
        output_files: list[Path] = []
        generated_files: set[Path] = set(split_files)
        conversion_errors: list[str] = []
        for split_file in split_files:
            output_file, _converted_to_rtl, volume_error = await self._convert_non_bok(
                split_file, "epub", volume_options, timeout=timeout
            )
            if output_file != split_file:
                generated_files.add(output_file)
                if not output_file.exists():
                    conversion_errors.append(
                        self._merge_errors(
                            volume_error,
                            f"Failed to rebuild split volume: {split_file.name}",
                        )
                    )
                    output_files.append(split_file)
                    continue
                split_file.unlink(missing_ok=True)
                output_file.replace(split_file)
                generated_files.discard(output_file)

            if options.force_rtl and split_file.exists():
                set_epub_to_rtl(split_file)
            postprocess_error = (
                await self._compress_cover(split_file, "epub", timeout=timeout)
                if options.compress_cover
                else ""
            )
            if merged_error := self._merge_errors(volume_error, postprocess_error):
                conversion_errors.append(merged_error)

            output_files.append(split_file)

        if conversion_errors:
            self._cleanup_files(list(generated_files.union(output_files)))
            return ConversionBatchResult([], set_to_rtl, "\n".join(conversion_errors))

        return ConversionBatchResult(output_files, set_to_rtl)

    async def convert_ebook_many(
        self,
        input_file: Path,
        output_type: str,
        options: ConversionOptions | None = None,
        timeout: int | None = TASK_TIMEOUT,
    ) -> ConversionBatchResult:
        options = options or ConversionOptions()
        input_type = input_file.suffix.lower()[1:]
        converted_to_rtl: bool | None = None

        if input_type == "epub" and output_type == "epub" and options.epub_split_volumes:
            return await self._convert_epub_split_volumes(input_file, options, timeout=timeout)
        if input_type in {"bok", "doc", "pdf"}:
            convert_fn = {
                "bok": self._convert_from_bok,
                "doc": self._convert_from_doc,
                "pdf": self._convert_from_pdf,
            }[input_type]
            output_file, converted_to_rtl, conversion_error = await convert_fn(
                input_file, output_type, options, timeout=timeout
            )
        else:
            output_file, converted_to_rtl, conversion_error = await self._convert_non_bok(
                input_file,
                output_type,
                options,
                timeout=timeout,
            )

        output_files = [output_file]
        if options.compress_cover:
            compression_error = await self._compress_cover(
                output_file, output_type, timeout=timeout
            )
            conversion_error = self._merge_errors(conversion_error, compression_error)
        return ConversionBatchResult(output_files, converted_to_rtl, conversion_error)
