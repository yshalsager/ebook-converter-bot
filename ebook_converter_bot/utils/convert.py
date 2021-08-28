import logging
from asyncio import create_subprocess_shell
from asyncio.subprocess import PIPE, Process, STDOUT
from string import Template

logger = logging.getLogger(__name__)


class Converter:
    supported_input_types = ['azw', 'azw3', 'azw4', 'azw8', 'cb7', 'cbc', 'cbr', 'cbz', 'chm', 'djvu', 'docx',
                             'doc', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'kfx', 'kfx-zip', 'kpf', 'lit',
                             'lrf', 'mobi', 'odt', 'opf', 'pdb', 'pml', 'prc', 'rb', 'rtf', 'snb', 'tcr',
                             'txt', 'txtz']
    supported_output_types = ['azw3', 'docx', 'epub', 'fb2', 'htmlz', 'kfx', 'lit', 'lrf', 'mobi', 'oeb',
                              'pdb', 'pmlz', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz', 'zip']

    def __init__(self):
        self._convert_command = Template("ebook-convert $input_file $output_file")
        # TODO: Add the ability to use converter options
        # https://manual.calibre-ebook.com/generated/en/ebook-convert.html
        self._kfx_input_convert_command = Template(
            'WINEDEBUG=-all calibre-debug -r "KFX Input" -- "$input_file"')  # KFX to EPUB
        self._kfx_output_convert_command = Template('WINEDEBUG=-all calibre-debug -r "KFX Output" -- "$input_file"')
        self.kfx_output_allowed_types = ['epub', 'opf', 'mobi', 'doc', 'docx', 'kpf', 'kfx-zip']
        self.kfx_input_allowed_types = ['azw8', 'kfx', 'kfx-zip']

    @classmethod
    def get_supported_types(cls):
        return sorted(list(set(cls.supported_input_types + cls.supported_output_types)))

    async def is_supported_input_type(self, input_file):
        return input_file.lower().split('.')[-1] in self.supported_input_types

    @staticmethod
    async def _run_command(command):
        process: Process = await create_subprocess_shell(command, stdin=PIPE, stdout=PIPE, stderr=STDOUT, shell=True)
        await process.wait()
        output = await process.stdout.read()
        output = output.decode().strip()
        logger.info(output)
        return process.returncode

    async def _convert_to_kfx(self, input_file):
        """
        Convert an ebook to KFX
        :param input_file: Pathname of the .epub, .opf, .mobi, .doc, .docx, .kpf, or .kfx-zip file to be converted
        :return:
        """
        await self._run_command(self._kfx_output_convert_command.safe_substitute(input_file=input_file))

    async def _convert_from_kfx_to_epub(self, input_file):
        """
        Convert a KFX ebook to EPUB
        :param input_file: Pathname of the .azw8, .kfx, .kfx-zip, or .kpf file to be processed
        :return:
        """
        await self._run_command(self._kfx_input_convert_command.safe_substitute(input_file=input_file))

    async def convert_ebook(self, input_file, output_type):
        input_type = input_file.lower().split('.')[-1]
        output_file = input_file.replace(input_type, output_type)
        if input_type in self.kfx_input_allowed_types:
            await self._convert_from_kfx_to_epub(input_file)
            if output_type == "epub":
                return output_file
            # 2nd step conversion
            await self._run_command(self._convert_command.safe_substitute(
                input_file=input_file.replace(input_type, "epub"), output_file=output_file))
            return output_file
        elif output_type == "kfx" and input_type in self.kfx_output_allowed_types:
            await self._convert_to_kfx(input_file)
            return output_file
        elif output_type in self.supported_output_types:
            await self._run_command(
                self._convert_command.safe_substitute(
                    input_file=input_file,
                    output_file=output_file
                ))
            return output_file
