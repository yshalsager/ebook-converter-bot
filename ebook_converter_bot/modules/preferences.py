from telethon import Button, events

from ebook_converter_bot import LOCALES
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_lang, update_language
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.telegram import tg_exceptions_handler


@BOT.on(events.NewMessage(pattern="/settings|/preferences"))
@BOT.on(events.CallbackQuery(pattern="update_preferences"))
@tg_exceptions_handler
async def preferences_handler(event: events.NewMessage.Event) -> None:
    """Set chat preferences."""
    lang = get_lang(event.chat_id)
    buttons = [Button.inline(_("Language", lang), data="update_language")]
    message = _("**Available bot preferences:**", lang)
    (
        await event.respond(message, buttons=buttons)
        if not hasattr(event, "data")
        else await event.edit(message, buttons=buttons)
    )


@BOT.on(events.CallbackQuery(pattern="update_language"))
@tg_exceptions_handler
async def update_language_callback(event: events.CallbackQuery.Event) -> None:
    """Update language handler."""
    lang = get_lang(event.chat_id)
    buttons = [
        Button.inline(
            f"{i['name']} ({i['nativeName']})", data=f"setlanguage_{i['code']}"
        )
        for i in LOCALES
    ] + [Button.inline(_("Back", lang), data="update_preferences")]
    await event.edit(
        _("**Select Bot language**", lang), buttons=[buttons[i::5] for i in range(5)]
    )


@BOT.on(events.CallbackQuery(pattern=r"setlanguage_\w+"))
@tg_exceptions_handler
async def set_language_callback(event: events.CallbackQuery.Event) -> None:
    """Set language handler."""
    language_code = event.data.decode().split("_")[-1]
    update_language(event.chat_id, language_code)
    language = next(iter(filter(lambda x: x["code"] == language_code, LOCALES)))
    language_name = language["name"]
    language_native_name = language["nativeName"]
    await event.edit(
        _("**Language has been set to**: {} ({})", get_lang(event.chat_id)).format(
            language_name, language_native_name
        ),
        buttons=[
            Button.inline(_("Back", get_lang(event.chat_id)), data="update_language")
        ],
    )
