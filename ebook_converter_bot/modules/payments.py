"""Telegram Stars purchases; balances are derived from successful conversions."""

import asyncio
import logging
from collections import Counter
from datetime import timedelta
from typing import NamedTuple

from telethon import Button, events, functions, types, utils

from ebook_converter_bot import PAYMENTS_ENABLED, SUB_PERIOD, TG_BOT_ADMINS
from ebook_converter_bot.bot import BOT
from ebook_converter_bot.db.curd import (
    active_subs,
    add_payment,
    credits_left,
    find_payment,
    find_recent_payment,
    first_subscription_charge,
    free_used,
    get_lang,
    is_subscription_renewal,
    mark_refunded,
    payment_usage,
    sub_left,
)
from ebook_converter_bot.db.models.payment import Payment
from ebook_converter_bot.utils.i18n import translate as _
from ebook_converter_bot.utils.telegram import tg_exceptions_handler

LOGGER = logging.getLogger(__name__)
FREE_QUOTA = 30
BOT_ADMIN_IDS = set(TG_BOT_ADMINS)


class Product(NamedTuple):
    kind: str
    stars: int
    credits: int


PRODUCTS = {
    "pack_s": Product("pack", 100, 50),
    "pack_l": Product("pack", 450, 300),
    "plus": Product("sub", 250, 300),
    "pro": Product("sub", 750, 1500),
    "donate_50": Product("donation", 50, 0),
    "donate_250": Product("donation", 250, 0),
    "donate_1000": Product("donation", 1000, 0),
}
# shortcut: rebuilt after restart; persist only if invoice creation becomes a bottleneck.
invoice_links: dict[tuple[int, str, str], str] = {}
# shortcut: resets on restart; persist only if rollout needs historical decision counts.
shadow_decisions: Counter[str] = Counter()


def decide_charge(chat_id: int, sender_id: int, is_private: bool) -> str:
    if sender_id in BOT_ADMIN_IDS:
        return "free"
    if free_used(chat_id) < FREE_QUOTA:
        charge = "free"
    elif sub_left(sender_id) > 0:
        charge = "sub"
    elif credits_left(sender_id) > 0:
        charge = "credit"
    else:
        charge = "paywall" if is_private else "group_limit"
    if not PAYMENTS_ENABLED:
        shadow_decisions[charge] += 1
        if charge != "free":
            LOGGER.info("Shadow payment: chat=%s sender=%s decision=%s", chat_id, sender_id, charge)
        return "free"
    return charge


def validate_payment(payload: bytes, user_id: int, currency: str, amount: int) -> str:
    try:
        product, payer = payload.decode().split(":")
        valid = product in PRODUCTS and int(payer) == user_id and user_id > 0
    except ValueError:
        valid = False
    if not valid or currency != "XTR" or amount != PRODUCTS[product].stars:
        raise ValueError("Price changed or invalid payment, send /buy or /donate again.")
    return product


def status_text(chat_id: int, user_id: int, lang: str) -> str:
    text = _("Free: {} left this month. Plan: {} left. Pack credits: {}.", lang).format(
        max(0, FREE_QUOTA - free_used(chat_id)),
        max(0, sub_left(user_id)),
        max(0, credits_left(user_id)),
    )
    for row in active_subs(user_id):
        text += "\n" + _("{} active until {}.", lang).format(
            row.product.title(), row.subscription_until.date()
        )
    return text


async def invoice_link(user_id: int, product: str, title: str) -> str:
    key = (user_id, product, title)
    if key not in invoice_links:
        item = PRODUCTS[product]
        result = await BOT(
            functions.payments.ExportInvoiceRequest(
                types.InputMediaInvoice(
                    title=title,
                    description=title,
                    payload=f"{product}:{user_id}".encode(),
                    provider="",
                    provider_data=types.DataJSON("{}"),
                    invoice=types.Invoice(
                        currency="XTR",
                        prices=[types.LabeledPrice(title, item.stars)],
                        subscription_period=SUB_PERIOD if item.kind == "sub" else None,
                    ),
                )
            )
        )
        invoice_links[key] = result.url
    return invoice_links[key]


async def show_buy(event) -> None:
    lang = get_lang(event.chat_id)
    if not PAYMENTS_ENABLED:
        await event.reply(_("Plans are not available. You can still /donate.", lang))
        return
    labels = [
        ("pack_s", _("{} conversions — {} ⭐", lang)),
        ("pack_l", _("{} conversions — {} ⭐", lang)),
        ("plus", _("Plus: {}/month — {} ⭐", lang)),
        ("pro", _("Pro: {}/month — {} ⭐", lang)),
    ]
    buttons = []
    for key, template in labels:
        label = template.format(PRODUCTS[key].credits, PRODUCTS[key].stars)
        buttons.append([Button.url(label, await invoice_link(event.sender_id, key, label))])
    await event.reply(
        status_text(event.chat_id, event.sender_id, lang)
        + "\n"
        + _("By paying you accept /terms.", lang),
        buttons=buttons,
    )


@BOT.on(events.NewMessage(pattern=r"^/buy(?:@\w+)?$"))
@tg_exceptions_handler
async def buy(event) -> None:
    await show_buy(event)


@BOT.on(events.NewMessage(pattern=r"^/donate(?:@\w+)?$"))
@tg_exceptions_handler
async def donate(event) -> None:
    lang = get_lang(event.chat_id)
    buttons = []
    for key, item in PRODUCTS.items():
        if item.kind == "donation":
            title = _("Donate {} ⭐", lang).format(item.stars)
            buttons.append([Button.url(title, await invoice_link(event.sender_id, key, title))])
    buttons.append(
        [
            Button.url("PayPal", "https://www.paypal.me/yshalsager"),
            Button.url("Patreon", "https://www.patreon.com/XiaomiFirmwareUpdater"),
            Button.url("Liberapay", "https://liberapay.com/yshalsager"),
        ]
    )
    await event.reply(_("Support the bot. By paying you accept /terms.", lang), buttons=buttons)


@BOT.on(events.NewMessage(pattern=r"^/(?:terms|support|paysupport)(?:@\w+)?$"))
@tg_exceptions_handler
async def terms(event) -> None:
    await event.reply(
        _(
            "Failed conversions are never charged. Pack credits never expire; ask for a refund of an unused pack.\n"
            "Subscriptions renew every 30 days until cancelled in Telegram: Settings → My Stars → Subscriptions. "
            "Unused allowance does not roll over. No partial refunds for a started period.\n"
            "Donations are only refundable by mistake, case by case. Telegram support cannot help with purchases in this bot. "
            "For help or refunds, contact the developer: @yshalsager.",
            get_lang(event.chat_id),
        )
    )


@BOT.on(events.Raw(types.UpdateBotPrecheckoutQuery))
async def precheckout(update) -> None:
    error = None
    try:
        validate_payment(update.payload, update.user_id, update.currency, update.total_amount)
    except ValueError as exc:
        error = _(str(exc), get_lang(update.user_id))
    await BOT(
        functions.messages.SetBotPrecheckoutResultsRequest(
            update.query_id, success=error is None, error=error
        )
    )


@BOT.on(events.Raw(types.UpdateNewMessage))
async def payment_received(update) -> None:
    message = update.message
    if not isinstance(message, types.MessageService) or not isinstance(
        message.action, types.MessageActionPaymentSentMe
    ):
        return
    try:
        action = message.action
        user_id = message.peer_id.user_id
        product = validate_payment(action.payload, user_id, action.currency, action.total_amount)
        item = PRODUCTS[product]
        if add_payment(
            Payment(
                user_id=user_id,
                product=product,
                kind=item.kind,
                stars=action.total_amount,
                credits=item.credits,
                charge_id=action.charge.id,
                provider_charge_id=action.charge.provider_charge_id,
                subscription_until=action.subscription_until_date,
                recurring=bool(action.recurring_used),
                created_at=message.date,
            )
        ):
            lang = get_lang(user_id)
            await BOT.send_message(
                user_id,
                _("Thank you for the support!", lang)
                if item.kind == "donation"
                else _("Thanks!", lang) + "\n" + status_text(user_id, user_id, lang),
            )
    except Exception:
        LOGGER.exception("Could not process Stars payment")


def reconcile_transaction(transaction) -> None:
    if find_payment(transaction.id):
        if transaction.refund:
            mark_refunded(transaction.id)
        return
    if (
        not transaction.bot_payload
        or not transaction.date
        or transaction.pending
        or transaction.failed
    ):
        return
    if not isinstance(transaction.peer, types.StarsTransactionPeer) or not isinstance(
        transaction.peer.peer, types.PeerUser
    ):
        return
    user_id = transaction.peer.peer.user_id
    product = validate_payment(
        transaction.bot_payload, user_id, "XTR", abs(transaction.amount.amount)
    )
    if transaction.amount.nanos:
        raise ValueError("Fractional Stars payment")
    item = PRODUCTS[product]
    if find_recent_payment(user_id, product, transaction.date):
        # shortcut: remove this time-based fallback once logs show charge IDs always match
        LOGGER.warning("Stars transaction %s matched by time, not charge ID", transaction.id)
    else:
        add_payment(
            Payment(
                user_id=user_id,
                product=product,
                kind=item.kind,
                stars=item.stars,
                credits=item.credits,
                charge_id=transaction.id,
                provider_charge_id=transaction.id,
                created_at=transaction.date,
                recurring=item.kind == "sub"
                and is_subscription_renewal(user_id, product, transaction.date),
                subscription_until=transaction.date + timedelta(seconds=SUB_PERIOD)
                if item.kind == "sub"
                else None,
            )
        )
    if transaction.refund:
        mark_refunded(transaction.id)


async def reconciliation_loop() -> None:
    while True:
        try:
            offset = ""
            while True:
                result = await BOT(
                    functions.payments.GetStarsTransactionsRequest(
                        peer=types.InputPeerSelf(),
                        ascending=True,
                        offset=offset,
                        limit=100,
                    )
                )
                for transaction in result.history or []:  # omitted when there are none
                    try:
                        reconcile_transaction(transaction)
                    except Exception:
                        LOGGER.exception("Could not reconcile Stars transaction %s", transaction.id)
                if not result.next_offset or result.next_offset == offset:
                    break
                offset = result.next_offset
            LOGGER.info("Stars reconciliation finished")
        except Exception:
            LOGGER.exception("Stars reconciliation failed")
        await asyncio.sleep(86400)


@BOT.on(events.NewMessage(from_users=TG_BOT_ADMINS, pattern=r"^/refund(?:@\w+)?(?:\s+(\S+))?$"))
@tg_exceptions_handler
async def refund(event) -> None:
    lang = get_lang(event.chat_id)
    row = find_payment(event.pattern_match.group(1) or "")
    if not row:
        await event.reply(_("Payment not found. Use /refund <provider_charge_id>.", lang))
        return
    cancel_id = first_subscription_charge(row) if row.kind == "sub" else row.provider_charge_id
    user = utils.get_input_user(await BOT.get_input_entity(row.user_id))
    await BOT(functions.payments.RefundStarsChargeRequest(user, row.provider_charge_id))
    mark_refunded(row.provider_charge_id)
    text = _("Refunded.", lang)
    used = payment_usage(row)
    if used:
        warning = (
            _("Warning: {} of {} credits from this pack were used.", lang)
            if row.kind == "pack"
            else _("Warning: {} of {} used in this period.", lang)
        )
        text += " " + warning.format(used, row.credits)
    if row.kind == "sub":
        try:
            await BOT(functions.payments.BotCancelStarsSubscriptionRequest(user, cancel_id))
        except Exception:
            LOGGER.exception("Subscription cancellation failed")
            text += "\n" + _("Subscription cancellation failed; cancel it in Telegram.", lang)
    await event.reply(text)


reconciliation_task = BOT.loop.create_task(reconciliation_loop())
