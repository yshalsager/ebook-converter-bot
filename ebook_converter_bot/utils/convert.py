import asyncio
import logging
import re
from asyncio.subprocess import PIPE, STDOUT, Process
from dataclasses import dataclass, replace
from os import getpgid, killpg, setsid
from pathlib import Path
from signal import SIGKILL
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


@dataclass
class ConversionOptions:
    force_rtl: bool = False
    compress_cover: bool = False
    fix_epub: bool = False
    flat_toc: bool = False
    smarten_punctuation: bool = False
    change_justification: str = "original"
    remove_paragraph_spacing: bool = False
    kfx_doc_type: str = "doc"
    kfx_pages: int | None = None
    docx_page_size: str = "default"
    docx_no_toc: bool = False
    epub_version: str = "default"
    epub_inline_toc: bool = False
    epub_remove_background: bool = False
    epub_split_volumes: bool = False
    epub_standardize_footnotes: bool = False
    pdf_paper_size: str = "default"
    pdf_page_numbers: bool = False


@dataclass
class ConversionBatchResult:
    output_files: list[Path]
    converted_to_rtl: bool | None
    conversion_error: str = ""
    split_capped: bool = False
    split_count: int = 0


class Converter:
    polish_supported_types: ClassVar[set[str]] = {"azw3", "epub", "kepub"}
    supported_input_types: ClassVar[list[str]] = [
        "azw",
        "azw3",
        "azw4",
        "azw8",
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
        "odt",
        "opf",
        "pdb",
        "pml",
        "prc",
        "rb",
        "rtf",
        "snb",
        "tcr",
        "txt",
        "txtz",
        "bok",
        "pdf",
    ]
    supported_output_types: ClassVar[list[str]] = [
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

    @classmethod
    def get_supported_types(cls) -> list[str]:
        return sorted(set(cls.supported_input_types + cls.supported_output_types))

    def is_supported_input_type(self, input_file: str | None) -> bool:
        if not input_file:
            return False
        return input_file.lower().split(".")[-1] in self.supported_input_types

    @staticmethod
    async def _run_command(
        command: list[str], timeout: int | None = TASK_TIMEOUT
    ) -> tuple[int | None, str]:
        conversion_error = ""
        process: Process = await asyncio.create_subprocess_exec(
            *command,
            stdin=PIPE,
            stdout=PIPE,
            stderr=STDOUT,
            preexec_fn=setsid,
        )
        try:
            if timeout is None:
                stdout, _ = await process.communicate()
            else:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
            output = "\n".join(
                [
                    i
                    for i in stdout.decode().splitlines()
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
        except asyncio.exceptions.TimeoutError:
            logger.info(f"Timeout while running command: {command}")
        try:
            # If it timed out terminate the process and its child processes.
            killpg(getpgid(process.pid), SIGKILL)
            process.kill()
        except OSError:
            pass  # Ignore 'no such process' error
        return process.returncode, conversion_error

    @staticmethod
    def _append_common_options(command: list[str], options: ConversionOptions) -> None:
        if options.smarten_punctuation:
            command.append("--smarten-punctuation")
        if options.remove_paragraph_spacing:
            command.append("--remove-paragraph-spacing")
        if options.change_justification != "original":
            command.extend(["--change-justification", options.change_justification])

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

        command = ["ebook-convert", str(epub_file), str(output_file)]
        self._append_ebook_convert_options(command, output_type, options)
        _, conversion_error = await self._run_command(command, timeout=timeout)
        epub_file.unlink(missing_ok=True)
        return output_file, set_to_rtl, conversion_error

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
        command = ["ebook-convert", str(epub_file), str(output_file)]
        self._append_ebook_convert_options(command, output_type, options)
        await self._run_command(command, timeout=timeout)
        epub_file.unlink(missing_ok=True)
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
            epub_version="default",
            epub_inline_toc=False,
            epub_remove_background=False,
            epub_split_volumes=False,
            epub_standardize_footnotes=False,
            pdf_paper_size="default",
            pdf_page_numbers=False,
        )
        epub_file, _ignored_rtl, conversion_error = await self._convert_non_bok(
            input_file, "epub", epub_options, timeout=timeout
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
            command = ["ebook-convert", str(epub_file), str(output_file)]
            self._append_ebook_convert_options(command, "pdf", pdf_options)
            _, conversion_error = await self._run_command(command, timeout=timeout)
            return output_file, set_to_rtl, conversion_error
        finally:
            epub_file.unlink(missing_ok=True)

    async def _convert_non_bok(
        self,
        input_file: Path,
        output_type: str,
        options: ConversionOptions,
        timeout: int | None = TASK_TIMEOUT,
    ) -> tuple[Path, bool | None, str]:
        conversion_error = ""
        input_type = input_file.suffix.lower()[1:]
        output_file = input_file.with_suffix(f".{output_type}")

        if output_type == "pdf" and options.force_rtl and input_type != "epub":
            return await self._convert_to_pdf_with_rtl_intermediate(
                input_file, options, timeout=timeout
            )

        set_to_rtl = (
            self._preprocess_input_epub(input_file, options) if input_type == "epub" else None
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

        command = ["ebook-convert", str(input_file), str(output_file)]
        self._append_ebook_convert_options(command, output_type, options)
        _, conversion_error = await self._run_command(command, timeout=timeout)

        if output_type == "epub" and options.force_rtl:
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
                    epub_version="default",
                    epub_inline_toc=False,
                    epub_remove_background=False,
                    epub_split_volumes=False,
                    pdf_paper_size="default",
                    pdf_page_numbers=False,
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
        if input_type in {"bok", "pdf"}:
            convert_fn = self._convert_from_bok if input_type == "bok" else self._convert_from_pdf
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
