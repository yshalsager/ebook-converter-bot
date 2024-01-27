"""Converter."""

from pathlib import Path
from random import sample
from string import digits

from telethon import Button, events
from telethon.tl.custom import Message, MessageButton

from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_lang
from ebook_converter_bot.utils.analytics import analysis
from ebook_converter_bot.utils.convert import Converter
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.telegram import tg_exceptions_handler

MAX_ALLOWED_FILE_SIZE = 26214400  # 25 MB

converter = Converter()
queue = {}


@BOT.on(events.NewMessage(func=lambda x: x.message.file and x.is_private))
@BOT.on(events.NewMessage(pattern="/convert", func=lambda x: x.message.is_reply))
@tg_exceptions_handler
async def file_converter(event: events.NewMessage.Event) -> None:
    """Convert ebook to another format."""
    lang = get_lang(event.chat_id)
    if event.pattern_match:
        message = await event.get_reply_message()
        file = message.file
    else:
        message = event.message
        file = event.message.file
    if not file:
        return
    if not converter.is_supported_input_type(file.name):
        # Unsupported file
        await event.reply(_("The file you sent is not a supported type!", lang))
        return
    if file.size > MAX_ALLOWED_FILE_SIZE:
        await event.reply(_("Files larger than 25 MB are not supported!", lang))
        return
    reply = await event.reply(_("Downloading the file...", lang))
    downloaded = await message.download_media(f"/tmp/{file.name}")  # noqa: S108
    if " " in downloaded:
        Path(downloaded).rename(downloaded.replace(" ", "_"))
        downloaded = downloaded.replace(" ", "_")
    random_id = "".join(sample(digits, 8))
    queue.update({random_id: downloaded})
    buttons = [
        Button.inline("🔸 azw3", data=f"azw3|{random_id}"),
        Button.inline("🔸 docx", data=f"docx|{random_id}"),
        Button.inline("🔸 epub", data=f"epub|{random_id}"),
        Button.inline("fb2", data=f"fb2|{random_id}"),
        Button.inline("htmlz", data=f"htmlz|{random_id}"),
        Button.inline("🔸 kfx", data=f"kfx|{random_id}"),
        Button.inline("lit", data=f"lit|{random_id}"),
        Button.inline("lrf", data=f"lrf|{random_id}"),
        Button.inline("🔸 mobi", data=f"mobi|{random_id}"),
        Button.inline("oeb", data=f"oeb|{random_id}"),
        Button.inline("pdb", data=f"pdb|{random_id}"),
        Button.inline("🔸 pdf", data=f"pdf|{random_id}"),
        Button.inline("pmlz", data=f"pmlz|{random_id}"),
        Button.inline("rb", data=f"rb|{random_id}"),
        Button.inline("rtf", data=f"rtf|{random_id}"),
        Button.inline("snb", data=f"snb|{random_id}"),
        Button.inline("tcr", data=f"tcr|{random_id}"),
        Button.inline("txt", data=f"txt|{random_id}"),
        Button.inline("txtz", data=f"txtz|{random_id}"),
        Button.inline("zip", data=f"zip|{random_id}"),
    ]
    buttons = [buttons[i::5] for i in range(5)]
    buttons.append([Button.inline(_("Force RTL", lang) + " ❓", data="rtl_disabled")])
    if file.name.lower().endswith(".epub"):
        buttons.extend(
            [
                [
                    Button.inline(
                        _("Fix EPUB before converting", lang) + " ❓", data="epub_keep"
                    )
                ],
                [
                    Button.inline(
                        _("Flatten EPUB TOC", lang) + " ❓", data="epub_keep_toc"
                    )
                ],
            ]
        )
    await reply.edit(
        _("Select the format you want to convert to:", lang), buttons=buttons
    )


@BOT.on(events.CallbackQuery(pattern="rtl_enabled|rtl_disabled"))
@tg_exceptions_handler
async def rtl_enable_callback(event: events.CallbackQuery.Event) -> None:
    """RTL callback handler."""
    message: Message = await event.get_message()
    lang = get_lang(event.chat_id)
    epub_button_row = None
    if message.buttons[-1][0].data.startswith(b"epub"):
        epub_button_row = message.buttons.pop(-1)
    rtl_button_row: list[MessageButton] = message.buttons[5]
    if event.data == b"rtl_disabled":
        rtl_button_row[0] = Button.inline(
            _("Force RTL", lang) + " ✅", data="rtl_enabled"
        )
    elif event.data == b"rtl_enabled":
        rtl_button_row[0] = Button.inline(
            _("Force RTL", lang) + " ❌", data="rtl_disabled"
        )
    message.buttons[5] = rtl_button_row
    if epub_button_row:
        message.buttons.append(epub_button_row)
    await message.edit(message.text, buttons=message.buttons)


@BOT.on(events.CallbackQuery(pattern="epub_fix|epub_keep"))
@tg_exceptions_handler
async def epub_fix_enable_callback(event: events.CallbackQuery.Event) -> None:
    """Epub Fix callback handler."""
    message: Message = await event.get_message()
    lang = get_lang(event.chat_id)
    epub_button_row: list[MessageButton] = message.buttons[-2]
    if event.data == b"epub_keep":
        epub_button_row[0] = Button.inline(
            _("Fix EPUB before converting", lang) + " ✅", data="epub_fix"
        )
    elif event.data == b"epub_fix":
        epub_button_row[0] = Button.inline(
            _("Fix EPUB before converting", lang) + " ❌", data="epub_keep"
        )
    message.buttons[-2] = epub_button_row
    await message.edit(message.text, buttons=message.buttons)


@BOT.on(events.CallbackQuery(pattern="epub_flat_toc|epub_keep_toc"))
@tg_exceptions_handler
async def epub_toc_edit_enable_callback(event: events.CallbackQuery.Event) -> None:
    """Epub TOC edit callback handler."""
    message: Message = await event.get_message()
    lang = get_lang(event.chat_id)
    epub_button_row: list[MessageButton] = message.buttons[-1]
    if event.data == b"epub_keep_toc":
        epub_button_row[0] = Button.inline(
            _("Flatten EPUB TOC", lang) + " ✅", data="epub_flat_toc"
        )
    elif event.data == b"epub_flat_toc":
        epub_button_row[0] = Button.inline(
            _("Flatten EPUB TOC", lang) + " ❌", data="epub_flat_toc"
        )
    message.buttons[-1] = epub_button_row
    await message.edit(message.text, buttons=message.buttons)


@BOT.on(events.CallbackQuery(pattern=r"\w+\|\d+"))
@tg_exceptions_handler
@analysis
async def converter_callback(
    event: events.CallbackQuery.Event,
) -> tuple[str, str] | None:
    """Converter callback handler."""
    message: Message = await event.get_message()
    fix_epub = False
    flat_toc = False
    if message.buttons[-1][0].data.startswith(b"epub"):
        convert_to_rtl = message.buttons[-3][0].data == b"rtl_enabled"
        fix_epub = message.buttons[-2][0].data == b"epub_fix"
        flat_toc = message.buttons[-1][0].data == b"epub_flat_toc"
    else:
        convert_to_rtl = message.buttons[-1][0].data == b"rtl_enabled"
    lang = get_lang(event.chat_id)
    converted = False
    output_type: str
    random_id: str
    output_type, random_id = event.data.decode().split("|")
    if not queue.get(random_id):
        return None
    input_file = Path(queue[random_id])
    if not input_file.exists():
        return None
    del queue[random_id]
    reply = await event.edit(
        _("Converting the file to {}...", lang).format(output_type)
    )
    output_file, converted_to_rtl, conversion_error = await converter.convert_ebook(
        input_file,
        output_type,
        force_rtl=convert_to_rtl,
        fix_epub=fix_epub,
        flat_toc=flat_toc,
    )
    if output_file.exists():
        message_text = ""
        if convert_to_rtl and converted_to_rtl:
            message_text += _("Converted to RTL successfully!\n", lang)
        message_text += _("Done! Uploading the converted file...", lang)
        await reply.edit(message_text)
        await event.client.send_file(
            event.chat, output_file, reply_to=reply, force_document=True
        )
        converted = True
    else:
        input_file_name = input_file.name
        error_message = _("Failed to convert the file (`{}`) to {} :(", lang).format(
            input_file_name, output_type
        )
        if conversion_error:
            error_message += f"\n\n`{conversion_error}`"
        await reply.edit(error_message)
    input_file.unlink(missing_ok=True)
    output_file.unlink(missing_ok=True)
    if converted:
        return input_file.suffix, output_type
    return None
