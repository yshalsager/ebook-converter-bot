import asyncio
import logging
import re
from asyncio.subprocess import PIPE, STDOUT, Process
from os import getpgid, killpg, setsid
from pathlib import Path
from signal import SIGKILL
from string import Template
from typing import ClassVar

from ebook_converter_bot.utils.epub import (
    fix_content_opf_problems,
    flatten_toc,
    set_epub_to_rtl,
)

logger = logging.getLogger(__name__)


class Converter:
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
    ]
    supported_output_types: ClassVar[list[str]] = [
        "azw3",
        "docx",
        "epub",
        "fb2",
        "htmlz",
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

    def __init__(self) -> None:
        self._convert_command = Template('ebook-convert "$input_file" "$output_file"')
        # TODO: Add the ability to use converter options
        # https://manual.calibre-ebook.com/generated/en/ebook-convert.html
        self._kfx_input_convert_command = Template(
            'calibre-debug -r "KFX Input" -- "$input_file"'
        )  # KFX to EPUB
        self._kfx_output_convert_command = Template(
            'calibre-debug -r "KFX Output" -- "$input_file"'
        )

    @classmethod
    def get_supported_types(cls) -> list[str]:
        return sorted(set(cls.supported_input_types + cls.supported_output_types))

    def is_supported_input_type(self, input_file: str) -> bool:
        return input_file.lower().split(".")[-1] in self.supported_input_types

    @staticmethod
    async def _run_command(command: str) -> tuple[int | None, str]:
        conversion_error = ""
        process: Process = await asyncio.create_subprocess_shell(  # noqa: S604
            command,
            stdin=PIPE,
            stdout=PIPE,
            stderr=STDOUT,
            shell=True,
            preexec_fn=setsid,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=600
            )  # wait for 10 minutes
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

    async def _convert_to_kfx(self, input_file: Path) -> tuple[int | None, str]:
        """Convert an ebook to KFX
        :param input_file: Pathname of the .epub, .opf, .mobi, .doc, .docx, .kpf, or .kfx-zip file to be converted
        :return:
        """
        return await self._run_command(
            self._kfx_output_convert_command.safe_substitute(input_file=input_file)
        )

    async def _convert_from_kfx_to_epub(
        self, input_file: Path
    ) -> tuple[int | None, str]:
        """Convert a KFX ebook to EPUB
        :param input_file: Pathname of the .azw8, .kfx, .kfx-zip, or .kpf file to be processed
        :return:
        """
        return await self._run_command(
            self._kfx_input_convert_command.safe_substitute(input_file=input_file)
        )

    async def convert_ebook(  # noqa: C901
        self,
        input_file: Path,
        output_type: str,
        force_rtl: bool = False,
        fix_epub: bool = False,
        flat_toc: bool = False,
    ) -> tuple[Path, bool | None, str]:
        conversion_error = ""
        set_to_rtl: bool | None = None
        input_type: str = input_file.suffix.lower()[1:]
        output_file: Path = input_file.with_suffix(f".{output_type}")
        # EPUB pre-processing
        if input_type == "epub":
            if force_rtl:
                set_to_rtl = set_epub_to_rtl(input_file)
            if fix_epub:
                fix_content_opf_problems(input_file)
            if flat_toc:
                flatten_toc(input_file)
        # Conversion
        if input_type in self.kfx_input_allowed_types:
            _, conversion_error = await self._convert_from_kfx_to_epub(input_file)
            if output_type == "epub" and force_rtl:
                set_to_rtl = set_epub_to_rtl(output_file)
            else:
                # 2nd step conversion
                epub_file: Path = input_file.with_suffix(".epub")
                if force_rtl:
                    set_to_rtl = set_epub_to_rtl(epub_file)
                await self._run_command(
                    self._convert_command.safe_substitute(
                        input_file=epub_file, output_file=output_file
                    )
                )
                epub_file.unlink(missing_ok=True)
        if output_type == "kfx" and input_type in self.kfx_output_allowed_types:
            _, conversion_error = await self._convert_to_kfx(input_file)
        if output_type in self.supported_output_types:
            if input_type != output_type:
                _, conversion_error = await self._run_command(
                    self._convert_command.safe_substitute(
                        input_file=input_file, output_file=output_file
                    )
                )
            if output_type == "epub" and force_rtl:
                set_to_rtl = set_epub_to_rtl(output_file)
        return output_file, set_to_rtl, conversion_error
