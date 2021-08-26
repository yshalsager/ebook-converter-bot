"""Converter"""
import asyncio
from pathlib import Path

from telethon import events, Button

from ebook_converter_bot.bot import BOT
from ebook_converter_bot.utils.convert import Converter
from ebook_converter_bot.utils.i18n import translate as _

converter = Converter()


@BOT.on(events.NewMessage(func=lambda x: x.message.file))
async def file_converter(event: events.NewMessage.Event):
    """Convert ebook to another format"""
    if not await converter.is_supported_input_type(event.message.file.name):
        # Unsupported file
        await event.reply(_("The file you sent is not a supported type!"))
        return
    if event.message.file.size > 104857600:  # 100 MB
        await event.reply(_("Files larger than 100 MB are not supported!"))
        return
    reply = await event.reply(_("Downloading the file..."))
    downloaded = await event.message.download_media(f"/tmp/{event.message.file.name}")
    buttons = [
        [Button.inline("azw3", data=f"azw3|{downloaded}"),
         Button.inline("docx", data=f"docx|{downloaded}"),
         Button.inline("epub", data=f"epub|{downloaded}"),
         Button.inline("fb2", data=f"fb2|{downloaded}")],
        [Button.inline("htmlz", data=f"htmlz|{downloaded}"),
         Button.inline("kfx", data=f"kfx|{downloaded}"),
         Button.inline("lit", data=f"lit|{downloaded}"),
         Button.inline("lrf", data=f"lrf|{downloaded}")],
        [Button.inline("mobi", data=f"mobi|{downloaded}"),
         Button.inline("oeb", data=f"oeb|{downloaded}"),
         Button.inline("pdb", data=f"pdb|{downloaded}"),
         Button.inline("pdf", data=f"pdf|{downloaded}")],
        [Button.inline("pmlz", data=f"pmlz|{downloaded}"),
         Button.inline("rb", data=f"rb|{downloaded}"),
         Button.inline("rtf", data=f"rtf|{downloaded}"),
         Button.inline("snb", data=f"snb|{downloaded}")],
        [Button.inline("tcr", data=f"tcr|{downloaded}"),
         Button.inline("txt", data=f"txt|{downloaded}"),
         Button.inline("txtz", data=f"txtz|{downloaded}"),
         Button.inline("zip", data=f"zip|{downloaded}")]
    ]
    reply = await reply.edit(_("Select the format you want to convert to."), buttons=buttons)
    await asyncio.sleep(30)
    await reply.delete()
    if Path(downloaded).exists():
        Path(downloaded).unlink()


@BOT.on(events.CallbackQuery())
async def converter_callback(event: events.CallbackQuery.Event):
    """Converter callback handler"""
    output_type, input_file = event.data.decode().split('|')
    if not Path(input_file).exists():
        return
    reply = await event.reply(_(f"Converting the file to {output_type}..."))
    output_file = await converter.convert_ebook(input_file, output_type)
    await reply.edit(_("Done! Uploading the converted file..."))
    await event.client.send_file(event.chat, output_file, force_document=True)
    Path(input_file).unlink()
    Path(output_file).unlink()
