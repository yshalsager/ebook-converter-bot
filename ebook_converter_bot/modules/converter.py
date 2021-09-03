"""Converter"""
from pathlib import Path
from random import sample
from string import digits
from typing import List

from telethon import events, Button
from telethon.tl.custom import Message, MessageButton

from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_lang
from ebook_converter_bot.utils.analytics import analysis
from ebook_converter_bot.utils.convert import Converter
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.telegram import tg_exceptions_handler

converter = Converter()
queue = {}


@BOT.on(events.NewMessage(func=lambda x: x.message.file and x.is_private))
@BOT.on(events.NewMessage(pattern='/convert', func=lambda x: x.message.is_reply))
@tg_exceptions_handler
async def file_converter(event: events.NewMessage.Event):
    """Convert ebook to another format"""
    lang = get_lang(event.chat_id)
    if event.pattern_match:
        message = await event.get_reply_message()
        file = message.file
    else:
        message = event.message
        file = event.message.file
    if not file:
        return
    if not await converter.is_supported_input_type(file.name):
        # Unsupported file
        await event.reply(_("The file you sent is not a supported type!", lang))
        return
    if file.size > 104857600:  # 100 MB
        await event.reply(_("Files larger than 100 MB are not supported!", lang))
        return
    reply = await event.reply(_("Downloading the file...", lang))
    downloaded = await message.download_media(f"/tmp/{file.name}")
    if " " in downloaded:
        Path(downloaded).rename(downloaded.replace(' ', '_'))
        downloaded = downloaded.replace(' ', '_')
    random_id = ''.join(sample(digits, 8))
    queue.update({random_id: downloaded})
    buttons = [Button.inline("azw3", data=f"azw3|{random_id}"),
               Button.inline("docx", data=f"docx|{random_id}"),
               Button.inline("epub", data=f"epub|{random_id}"),
               Button.inline("fb2", data=f"fb2|{random_id}"),
               Button.inline("htmlz", data=f"htmlz|{random_id}"),
               Button.inline("kfx", data=f"kfx|{random_id}"),
               Button.inline("lit", data=f"lit|{random_id}"),
               Button.inline("lrf", data=f"lrf|{random_id}"),
               Button.inline("mobi", data=f"mobi|{random_id}"),
               Button.inline("oeb", data=f"oeb|{random_id}"),
               Button.inline("pdb", data=f"pdb|{random_id}"),
               Button.inline("pmlz", data=f"pmlz|{random_id}"),
               Button.inline("rb", data=f"rb|{random_id}"),
               Button.inline("rtf", data=f"rtf|{random_id}"),
               Button.inline("snb", data=f"snb|{random_id}"),
               Button.inline("tcr", data=f"tcr|{random_id}"),
               Button.inline("txt", data=f"txt|{random_id}"),
               Button.inline("txtz", data=f"txtz|{random_id}"),
               Button.inline("zip", data=f"zip|{random_id}")]
    buttons = [buttons[i::5] for i in range(5)]
    buttons.append([Button.inline(_("Force RTL", lang) + " ❓", data="rtl_disabled")])
    await reply.edit(_("Select the format you want to convert to:", lang),
                     buttons=buttons)


@BOT.on(events.CallbackQuery(pattern='rtl_enabled|rtl_disabled'))
@tg_exceptions_handler
async def rtl_enable_callback(event: events.CallbackQuery.Event):
    """RTL callback handler"""
    message: Message = await event.get_message()
    lang = get_lang(event.chat_id)
    rtl_button_row: List[MessageButton] = message.buttons.pop(-1)
    if event.data == event.data == b"rtl_disabled":
        rtl_button_row[0] = Button.inline(_("Force RTL", lang) + " ✅", data="rtl_enabled")
    elif event.data == b"rtl_enabled":
        rtl_button_row[0] = Button.inline(_("Force RTL", lang) + " ❌", data="rtl_disabled")
    message.buttons.append(rtl_button_row)
    await message.edit(message.text, buttons=message.buttons)


@BOT.on(events.CallbackQuery(pattern=r'\w+\|\d+'))
@tg_exceptions_handler
@analysis
async def converter_callback(event: events.CallbackQuery.Event):
    """Converter callback handler"""
    message: Message = await event.get_message()
    convert_to_rtl = message.buttons[-1][0].data == b"rtl_enabled"
    lang = get_lang(event.chat_id)
    converted = False
    output_type, random_id = event.data.decode().split('|')
    input_file = queue.get(random_id)
    if not input_file or not Path(input_file).exists():
        return
    del queue[random_id]
    reply = await event.edit(_("Converting the file to {}...", lang).format(output_type))
    output_file, converted_to_rtl = await converter.convert_ebook(input_file, output_type, force_rtl=convert_to_rtl)
    if Path(output_file).exists():
        message_text = ""
        if convert_to_rtl and converted_to_rtl:
            message_text += _("Converted to RTL successfully!\n", lang)
        message_text += _("Done! Uploading the converted file...", lang)
        await reply.edit(message_text)
        await event.client.send_file(event.chat, output_file, reply_to=reply, force_document=True)
        converted = True
    else:
        input_file_name = input_file.split('/')[-1]
        await reply.edit(
            _("Failed to convert the file (`{}`) to {} :(", lang).format(input_file_name, output_type))
    Path(input_file).unlink(missing_ok=True)
    Path(output_file).unlink(missing_ok=True)
    if converted:
        return input_file.lower().split('.')[-1], output_type
