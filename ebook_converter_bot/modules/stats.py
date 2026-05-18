"""Bot stats module."""

from telethon import events

from ebook_converter_bot import TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import get_stats_snapshot


def _format_format_rows(rows: list[dict[str, int | str]]) -> str:
    if not rows:
        return "    No data\n"
    return "".join(f"    __{row['format']}__: {row['count']} times.\n" for row in rows)


def _format_pair_rows(rows: list[dict[str, int | str]]) -> str:
    if not rows:
        return "    No data\n"
    return "".join(
        f"    __{row['input']} -> {row['output']}__: {row['count']} times.\n" for row in rows
    )


def _format_duration(duration_ms: int | None) -> str:
    return "No data" if duration_ms is None else f"{duration_ms / 1000:.1f}s"


@BOT.on(events.NewMessage(from_users=TG_BOT_ADMINS, pattern=r"/stats"))
async def stats(event: events.NewMessage.Event) -> None:
    stats_message = await event.reply("Getting stats, please wait...")
    snapshot = get_stats_snapshot()
    users = snapshot["users"]
    legacy = snapshot["legacy"]
    recent = snapshot["recent"]
    formats = snapshot["formats"]
    recent_days = snapshot["recent_days"]

    message = (
        "**Users**\n"
        f"All: {users['all']}\n"
        f"Converted ever: {users['converted']} ({users['converted_percent']}%)\n"
        f"Inactive: {users['inactive']}\n"
        f"Repeat: {users['repeat']} ({users['repeat_percent']}% of converted)\n"
        f"Power (10+): {users['power']}\n"
        f"Active 7d: {users['active_7d']}\n"
        f"Active {recent_days}d: {users['active_recent']}\n\n"
        "**Lifetime legacy**\n"
        f"Successful conversions: {legacy['successes']}\n"
        f"Input format records: {legacy['input_total']}\n\n"
        f"**Tracked last {recent_days}d**\n"
        f"Attempts: {recent['attempts']}\n"
        f"Successes: {recent['successes']}\n"
        f"Failures: {recent['failures']}\n"
        f"Success rate: {recent['success_percent']}%\n"
        f"Avg duration: {_format_duration(recent['avg_duration_ms'])}\n\n"
        f"**Top pairs last {recent_days}d**\n"
        f"{_format_pair_rows(recent['top_pairs'])}\n"
        f"**Failed pairs last {recent_days}d**\n"
        f"{_format_pair_rows(recent['failed_pairs'])}\n"
        "**Top output formats (legacy)**\n"
        f"{_format_format_rows(formats['output'])}\n"
        "**Top input formats (legacy)**\n"
        f"{_format_format_rows(formats['input'])}"
    )

    await stats_message.edit(message)
