"""Converter."""

import asyncio
from pathlib import Path
from random import sample
from string import digits
from time import monotonic
from typing import cast

from telethon import Button, events

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_lang
from ebook_converter_bot.utils.analytics import analysis
from ebook_converter_bot.utils.convert import (
    MAX_SPLIT_OUTPUT_FILES,
    TASK_TIMEOUT,
    ConversionOptions,
    Converter,
)
from ebook_converter_bot.utils.converter_options import (
    CONTEXT_TYPES,
    ConversionRequestState,
    build_options_keyboard,
    cleanup_expired_requests,
    format_button_rows,
    set_request_option,
)
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.telegram import tg_exceptions_handler

MAX_ALLOWED_FILE_SIZE = 26214400  # 25 MB
QUEUE_TTL_SECONDS = 1800  # 30 minutes
CB_VIEW = "view"
CB_OPT = "opt"
CB_CTX = "ctx"
CB_FMT = "fmt"
CB_CANCEL = "cancel"

converter = Converter()
BOT_ADMIN_IDS = set(TG_BOT_ADMINS)
if "converter_queue" not in BOT.__dict__:
    BOT.__dict__["converter_queue"] = {}
queue: dict[str, ConversionRequestState] = cast(
    dict[str, ConversionRequestState], BOT.__dict__["converter_queue"]
)


async def cleanup_queue_loop() -> None:
    while True:
        cleanup_expired_requests(queue, ttl_seconds=QUEUE_TTL_SECONDS)
        sleep_task = asyncio.create_task(asyncio.sleep(60))
        done, _ = await asyncio.wait(
            {sleep_task, BOT.disconnected}, return_when=asyncio.FIRST_COMPLETED
        )
        if BOT.disconnected in done:
            sleep_task.cancel()
            break


queue_cleanup_task = BOT.loop.create_task(cleanup_queue_loop())


def options_labels(lang: str) -> dict[str, str]:
    return {
        "force_rtl_label": _("Force RTL", lang),
        "compress_cover_label": _("Compress cover", lang),
        "fix_epub_label": _("Fix EPUB before converting", lang),
        "flat_toc_label": _("Flatten EPUB TOC", lang),
        "smarten_punctuation_label": _("Smarten punctuation", lang),
        "change_justification_label": _("Text justification", lang),
        "remove_paragraph_spacing_label": _("Remove paragraph spacing", lang),
        "original_label": _("Original", lang),
        "left_label": _("Left", lang),
        "justify_label": _("Justify", lang),
        "docx_page_size_label": _("DOCX page size", lang),
        "docx_no_toc_label": _("DOCX: disable generated TOC", lang),
        "epub_version_label": _("EPUB version", lang),
        "epub_inline_toc_label": _("EPUB: inline TOC", lang),
        "epub_remove_background_label": _("Remove EPUB background", lang),
        "epub_split_volumes_label": _("Split EPUB volumes", lang),
        "epub_standardize_footnotes_label": _("Standardize EPUB footnotes", lang),
        "pdf_paper_size_label": _("PDF paper size", lang),
        "pdf_page_numbers_label": _("PDF: page numbers", lang),
        "kfx_doc_type_label": _("KFX doc type", lang),
        "kfx_pages_label": _("KFX pages", lang),
        "default_label": _("Default", lang),
        "letter_label": _("Letter", lang),
        "a4_label": _("A4", lang),
        "none_label": _("None", lang),
        "auto_label": _("Auto", lang),
        "pdoc_label": "PDOC",
        "ebok_label": "EBOK",
        "reset_options_label": _("Reset options", lang),
        "back_to_formats_label": _("Back to formats", lang),
        "cancel_label": _("Cancel", lang),
    }


def render_options_summary(state: ConversionRequestState, lang: str) -> str:
    summary_parts = [
        text
        for enabled, text in (
            (state.force_rtl, _("Force RTL", lang)),
            (state.compress_cover, _("Compress cover", lang)),
            (state.smarten_punctuation, _("Smarten punctuation", lang)),
            (state.remove_paragraph_spacing, _("Remove paragraph spacing", lang)),
            (
                state.change_justification != "original",
                _("Text justification: {}", lang).format(state.change_justification),
            ),
            (
                state.input_ext == "epub" and state.fix_epub,
                _("Fix EPUB before converting", lang),
            ),
            (
                state.input_ext == "epub" and state.flat_toc,
                _("Flatten EPUB TOC", lang),
            ),
            (
                state.docx_page_size != "default",
                _("DOCX page size: {}", lang).format(state.docx_page_size.upper()),
            ),
            (state.docx_no_toc, _("DOCX: disable generated TOC", lang)),
            (
                state.epub_version != "default",
                _("EPUB version: {}", lang).format(state.epub_version),
            ),
            (state.epub_inline_toc, _("EPUB: inline TOC", lang)),
            (
                getattr(state, "epub_remove_background", False),
                _("Remove EPUB background", lang),
            ),
            (
                state.input_ext == "epub" and getattr(state, "epub_split_volumes", False),
                _("Split EPUB volumes", lang),
            ),
            (
                state.input_ext == "epub" and getattr(state, "epub_standardize_footnotes", False),
                _("Standardize EPUB footnotes", lang),
            ),
            (
                state.pdf_paper_size != "default",
                _("PDF paper size: {}", lang).format(state.pdf_paper_size.upper()),
            ),
            (state.pdf_page_numbers, _("PDF: page numbers", lang)),
            (state.kfx_doc_type == "book", _("KFX doc type: EBOK", lang)),
            (state.kfx_pages == 0, _("KFX pages: Auto", lang)),
        )
        if enabled
    ]
    return "\n".join(summary_parts)


def build_conversion_options(state: ConversionRequestState) -> ConversionOptions:
    options = ConversionOptions()
    is_epub_input = state.input_ext == "epub"
    option_values = {
        "force_rtl": state.force_rtl,
        "compress_cover": state.compress_cover,
        "fix_epub": state.fix_epub if is_epub_input else False,
        "flat_toc": state.flat_toc if is_epub_input else False,
        "smarten_punctuation": state.smarten_punctuation,
        "change_justification": state.change_justification,
        "remove_paragraph_spacing": state.remove_paragraph_spacing,
        "kfx_doc_type": state.kfx_doc_type,
        "kfx_pages": state.kfx_pages,
        "docx_page_size": state.docx_page_size,
        "docx_no_toc": state.docx_no_toc,
        "epub_version": state.epub_version,
        "epub_inline_toc": state.epub_inline_toc,
        "epub_remove_background": getattr(state, "epub_remove_background", False),
        "epub_split_volumes": getattr(state, "epub_split_volumes", False)
        if is_epub_input
        else False,
        "epub_standardize_footnotes": (
            getattr(state, "epub_standardize_footnotes", False) if is_epub_input else False
        ),
        "pdf_paper_size": state.pdf_paper_size,
        "pdf_page_numbers": state.pdf_page_numbers,
    }
    for key, value in option_values.items():
        if hasattr(options, key):
            setattr(options, key, value)
    return options


def render_screen(
    request_id: str,
    state: ConversionRequestState,
    lang: str,
    *,
    show_options: bool = False,
) -> tuple[str, list[list]]:
    summary = render_options_summary(state, lang)
    labels = options_labels(lang)
    if show_options:
        message_text = (
            f"{_('Conversion options:', lang)}\n\n{summary}"
            if summary
            else _("Conversion options:", lang)
        )
        buttons = build_options_keyboard(request_id, state, labels)
        return message_text, buttons
    message_text = (
        f"{_('Select the format you want to convert to:', lang)}\n\n{summary}"
        if summary
        else _("Select the format you want to convert to:", lang)
    )
    buttons = format_button_rows(request_id, converter.supported_output_types, per_row=3)
    buttons.append(
        [
            Button.inline(_("Options ⚙️", lang), data=f"{CB_VIEW}|opts|{request_id}"),
            Button.inline(_("Cancel", lang), data=f"{CB_CANCEL}|{request_id}"),
        ]
    )
    return message_text, buttons


async def get_request_state(
    event: events.CallbackQuery.Event,
    request_id: str,
    *,
    pop: bool = False,
) -> ConversionRequestState | None:
    cleanup_expired_requests(queue, ttl_seconds=QUEUE_TTL_SECONDS)
    lang = get_lang(event.chat_id)
    state = queue.get(request_id)
    if not state:
        await event.answer(
            _("This conversion request expired. Please send the file again.", lang),
            alert=True,
        )
        return None
    input_file = Path(state.input_file_path)
    if not input_file.exists():
        queue.pop(request_id, None)
        await event.answer(
            _("The source file is no longer available. Please send it again.", lang),
            alert=True,
        )
        return None
    if pop:
        queue.pop(request_id, None)
    else:
        state.queued_at = monotonic()
    return state


@BOT.on(events.NewMessage(func=lambda x: x.message.file and x.is_private))
@BOT.on(events.NewMessage(pattern="/convert", func=lambda x: x.message.is_reply))
@tg_exceptions_handler
async def file_converter(event: events.NewMessage.Event) -> None:
    """Convert ebook to another format."""
    lang = get_lang(event.chat_id)
    if event.pattern_match:
        message = await event.get_reply_message()
        if not message or not message.file:
            await event.reply(_("Reply to a supported file to convert it.", lang))
            return
        file = message.file
    else:
        message = event.message
        file = event.message.file
    if not file:
        return
    file_name = file.name or ""
    if not converter.is_supported_input_type(file_name):
        # Unsupported file
        await event.reply(_("The file you sent is not a supported type!", lang))
        return
    if event.sender_id not in BOT_ADMIN_IDS and file.size > MAX_ALLOWED_FILE_SIZE:
        await event.reply(_("Files larger than 25 MB are not supported!", lang))
        return
    reply = await event.reply(_("Downloading the file...", lang))
    download_dir = Path("/tmp/ebook_converter_bot")  # noqa: S108
    download_dir.mkdir(parents=True, exist_ok=True)
    downloaded = await message.download_media(download_dir)
    if not downloaded:
        await reply.edit(_("Failed to download the file. Please send it again.", lang))
        return
    cleanup_expired_requests(queue, ttl_seconds=QUEUE_TTL_SECONDS)
    random_id = "".join(sample(digits, 8))
    while random_id in queue:
        random_id = "".join(sample(digits, 8))
    queue[random_id] = ConversionRequestState(
        input_file_path=downloaded,
        queued_at=monotonic(),
        input_ext=file_name.lower().split(".")[-1],
    )
    message_text, buttons = render_screen(random_id, queue[random_id], lang)
    await reply.edit(message_text, buttons=buttons)


@BOT.on(events.CallbackQuery(pattern=rf"{CB_VIEW}\|(opts|formats)\|\d+"))
@tg_exceptions_handler
async def view_switch_callback(event: events.CallbackQuery.Event) -> None:
    _view, view_name, request_id = event.data.decode().split("|")
    lang = get_lang(event.chat_id)
    state = await get_request_state(event, request_id)
    if not state:
        return
    if view_name == "opts":
        message_text, buttons = render_screen(request_id, state, lang, show_options=True)
        await event.edit(message_text, buttons=buttons)
        return
    message_text, buttons = render_screen(request_id, state, lang)
    await event.edit(message_text, buttons=buttons)


@BOT.on(events.CallbackQuery(pattern=rf"{CB_CTX}\|(docx|epub|pdf|kfx)\|\d+"))
@tg_exceptions_handler
async def options_context_callback(event: events.CallbackQuery.Event) -> None:
    _ctx, context_name, request_id = event.data.decode().split("|")
    state = await get_request_state(event, request_id)
    if not state:
        return
    if context_name not in CONTEXT_TYPES:
        return
    state.options_context = context_name
    lang = get_lang(event.chat_id)
    message_text, buttons = render_screen(request_id, state, lang, show_options=True)
    await event.edit(message_text, buttons=buttons)


@BOT.on(events.CallbackQuery(pattern=rf"{CB_OPT}\|[^|]+\|[^|]+\|\d+"))
@tg_exceptions_handler
async def options_toggle_callback(event: events.CallbackQuery.Event) -> None:
    _opt, option_key, option_value, request_id = event.data.decode().split("|")
    lang = get_lang(event.chat_id)
    state = await get_request_state(event, request_id)
    if not state:
        return
    if not set_request_option(state, option_key, option_value):
        await event.answer(_("This option is not available in this context.", lang), alert=True)
        return
    message_text, buttons = render_screen(request_id, state, lang, show_options=True)
    await event.edit(message_text, buttons=buttons)


@BOT.on(events.CallbackQuery(pattern=rf"{CB_CANCEL}\|\d+"))
@tg_exceptions_handler
async def cancel_conversion_callback(event: events.CallbackQuery.Event) -> None:
    _cancel, request_id = event.data.decode().split("|")
    state = await get_request_state(event, request_id, pop=True)
    if not state:
        return
    lang = get_lang(event.chat_id)
    Path(state.input_file_path).unlink(missing_ok=True)
    await event.edit(_("Conversion request canceled.", lang))


@BOT.on(events.CallbackQuery(pattern=rf"{CB_FMT}\|[\w-]+\|\d+"))
@tg_exceptions_handler
@analysis
async def converter_callback(
    event: events.CallbackQuery.Event,
) -> tuple[str, str] | None:
    """Converter callback handler."""
    lang = get_lang(event.chat_id)
    converted = False
    _fmt, output_type, request_id = event.data.decode().split("|")
    state = await get_request_state(event, request_id, pop=True)
    if not state:
        return None
    reply = await event.edit(_("Converting the file to {}...", lang).format(output_type))
    input_file = Path(state.input_file_path)
    options = build_conversion_options(state)
    batch_result = await converter.convert_ebook_many(
        input_file,
        output_type,
        options=options,
        timeout=None if event.sender_id in BOT_ADMIN_IDS else TASK_TIMEOUT,
    )
    output_files = [file_path for file_path in batch_result.output_files if file_path.exists()]
    if batch_result.split_capped:
        message_text = _("Split produced {} files, maximum allowed is {}.", lang).format(
            batch_result.split_count, MAX_SPLIT_OUTPUT_FILES
        )
        await reply.edit(message_text)
    elif output_files:
        message_text = ""
        if state.force_rtl and batch_result.converted_to_rtl:
            message_text += _("Converted to RTL successfully!\n", lang)
        message_text += (
            _("Done! Uploading the converted files...", lang)
            if len(output_files) > 1
            else _("Done! Uploading the converted file...", lang)
        )
        await reply.edit(message_text)
        for output_file in output_files:
            await event.client.send_file(
                event.chat, output_file, reply_to=reply, force_document=True
            )
        converted = True
    else:
        input_file_name = input_file.name
        error_message = _("Failed to convert the file (`{}`) to {} :(", lang).format(
            input_file_name, output_type
        )
        if batch_result.conversion_error:
            error_message += f"\n\n`{batch_result.conversion_error}`"
        await reply.edit(error_message)
    input_file.unlink(missing_ok=True)
    for output_file in batch_result.output_files:
        output_file.unlink(missing_ok=True)
    if converted:
        return state.input_ext, output_type
    return None
