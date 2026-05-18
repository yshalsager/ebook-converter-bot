"""Bot restart module."""

import json
from os import execl, getenv
from pathlib import Path
from sys import executable

from telethon import events

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_lang
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.update import (
    DEFAULT_UPDATE_REPO_BRANCH,
    DEFAULT_UPDATE_REPO_URL,
    BadZipFile,
    run_command,
    update_from_archive,
)

MAX_UPDATE_OUTPUT_LENGTH = 3500


def _trim_output(output: str) -> str:
    if len(output) <= MAX_UPDATE_OUTPUT_LENGTH:
        return output
    return f"...\n{output[-MAX_UPDATE_OUTPUT_LENGTH:]}"


async def _edit_with_output(message, text: str, output: object) -> None:
    safe_output = _trim_output(str(output)).replace("```", "'''")
    await message.edit(f"{text}:\n```\n{safe_output}\n```")


@BOT.on(events.NewMessage(from_users=TG_BOT_ADMINS, pattern=r"/restart"))
async def restart(event: events.NewMessage.Event) -> None:
    """Restart the bot."""
    restart_message = await event.reply(_("Restarting, please wait...", get_lang(event.chat_id)))
    Path("restart.json").write_text(
        json.dumps({"chat": restart_message.chat_id, "message": restart_message.id})
    )
    execl(executable, executable, "-m", "ebook_converter_bot")  # noqa: S606


@BOT.on(events.NewMessage(from_users=TG_BOT_ADMINS, pattern=r"/update"))
async def update(event: events.NewMessage.Event) -> None:
    """Update the bot from a GitHub source archive."""
    lang = get_lang(event.chat_id)
    message = await event.reply(_("Updating, please wait...", lang))
    repo_url = getenv("UPDATE_REPO_URL") or DEFAULT_UPDATE_REPO_URL
    branch = getenv("UPDATE_REPO_BRANCH") or DEFAULT_UPDATE_REPO_BRANCH
    await message.edit(_("Fetching update source from {} ({})...", lang).format(repo_url, branch))
    try:
        partial_copy_failures = await update_from_archive(repo_url, branch)
    except (ValueError, RuntimeError, BadZipFile, OSError) as error:
        await _edit_with_output(message, _("Failed to fetch update source", lang), error)
        return

    update_message = _("Source update successful. Updating dependencies...", lang)
    if partial_copy_failures:
        update_message = "{}\n{}".format(
            _("Updated source, but could not replace: {}", lang).format(
                ", ".join(partial_copy_failures)
            ),
            update_message,
        )
    await message.edit(update_message)

    output, code = await run_command(["uv", "sync", "--frozen", "--no-cache"])
    if code != 0:
        await _edit_with_output(message, _("Failed to update dependencies", lang), output)
        return

    await message.edit(_("Updated successfully!", lang))
    await restart(event)
