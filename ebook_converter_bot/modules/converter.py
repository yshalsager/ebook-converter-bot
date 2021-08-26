"""Converter"""
import asyncio
from pathlib import Path
from random import sample
from string import digits

from telethon import events, Button

from ebook_converter_bot.bot import BOT
from ebook_converter_bot.utils.convert import Converter
from ebook_converter_bot.utils.i18n import translate as _

converter = Converter()
queue = {}


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
    random_id = ''.join(sample(digits, 5))
    queue.update({random_id: downloaded})
    buttons = [
        [Button.inline("azw3", data=f"azw3|{random_id}"),
         Button.inline("docx", data=f"docx|{random_id}"),
         Button.inline("epub", data=f"epub|{random_id}"),
         Button.inline("fb2", data=f"fb2|{random_id}")],
        [Button.inline("htmlz", data=f"htmlz|{random_id}"),
         Button.inline("kfx", data=f"kfx|{random_id}"),
         Button.inline("lit", data=f"lit|{random_id}"),
         Button.inline("lrf", data=f"lrf|{random_id}")],
        [Button.inline("mobi", data=f"mobi|{random_id}"),
         Button.inline("oeb", data=f"oeb|{random_id}"),
         Button.inline("pdb", data=f"pdb|{random_id}"),
         Button.inline("pdf", data=f"pdf|{random_id}")],
        [Button.inline("pmlz", data=f"pmlz|{random_id}"),
         Button.inline("rb", data=f"rb|{random_id}"),
         Button.inline("rtf", data=f"rtf|{random_id}"),
         Button.inline("snb", data=f"snb|{random_id}")],
        [Button.inline("tcr", data=f"tcr|{random_id}"),
         Button.inline("txt", data=f"txt|{random_id}"),
         Button.inline("txtz", data=f"txtz|{random_id}"),
         Button.inline("zip", data=f"zip|{random_id}")]
    ]
    reply = await reply.edit(_("Select the format you want to convert to."), buttons=buttons)
    await asyncio.sleep(30)
    await reply.delete()
    if Path(downloaded).exists():
        Path(downloaded).unlink()


@BOT.on(events.CallbackQuery())
async def converter_callback(event: events.CallbackQuery.Event):
    """Converter callback handler"""
    output_type, random_id = event.data.decode().split('|')
    input_file = queue.get(random_id)
    if not input_file or not Path(input_file).exists():
        return
    del queue[random_id]
    reply = await event.reply(_(f"Converting the file to {output_type}..."))
    output_file = await converter.convert_ebook(input_file, output_type)
    await reply.edit(_("Done! Uploading the converted file..."))
    await event.client.send_file(event.chat, output_file, force_document=True)
    Path(input_file).unlink()
    Path(output_file).unlink()
