# ruff: noqa: PLR2004
import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from alembic import command
from ebook_converter_bot.db import curd
from ebook_converter_bot.db import session as db_session
from ebook_converter_bot.db.models.chat import Chat
from ebook_converter_bot.db.models.conversion_event import ConversionEvent
from ebook_converter_bot.db.models.payment import Payment
from sqlalchemy import func, inspect, select, text
from telethon import events, types

from tests.test_db_curd import _configure_test_session
from tests.test_db_migrations import _patch_database
from tests.test_request_isolation import UploadEvent

pytest_plugins = ["tests.test_request_isolation"]


@pytest.fixture
def payments(monkeypatch):
    bot = ModuleType("ebook_converter_bot.bot")
    bot.BOT = SimpleNamespace(
        on=lambda _: lambda function: function,
        loop=SimpleNamespace(create_task=lambda coroutine: coroutine.close()),
    )
    monkeypatch.setitem(sys.modules, "ebook_converter_bot.bot", bot)
    path = Path(__file__).resolve().parents[1] / "ebook_converter_bot/modules/payments.py"
    spec = importlib.util.spec_from_file_location("_test_payments", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PAYMENTS_ENABLED", True)
    monkeypatch.setattr(module, "BOT_ADMIN_IDS", {999})
    return module


@pytest.fixture
def sessions(monkeypatch):
    return _configure_test_session(monkeypatch)


def conversion(*, user_id=1, charge="free", success=True, created_at=None):
    return ConversionEvent(
        user_id=user_id,
        payer_id=None if charge == "free" else user_id,
        input_format="epub",
        output_format="pdf",
        success=success,
        charge=charge,
        created_at=created_at or datetime.now(UTC),
    )


def payment(  # noqa: PLR0913 - mirrors the payment fields under test
    *,
    product="pack_s",
    credits=50,  # noqa: A002
    until=None,
    status="paid",
    charge_id="charge",
    provider="provider",
):
    return Payment(
        user_id=1,
        product=product,
        kind="sub" if until else "pack",
        stars=100,
        credits=credits,
        charge_id=charge_id,
        provider_charge_id=provider,
        subscription_until=until,
        status=status,
    )


def test_gate_tiers_and_failed_jobs(payments, sessions):
    with sessions() as session:
        session.add_all([conversion() for _ in range(29)])
        session.add(conversion(success=False))
        session.commit()
    assert payments.decide_charge(1, 1, True) == "free"
    curd.record_conversion_event(conversion())
    assert payments.decide_charge(1, 1, True) == "paywall"
    assert payments.decide_charge(1, 1, False) == "group_limit"
    curd.add_payment(payment())
    assert payments.decide_charge(1, 1, True) == "credit"
    assert payments.decide_charge(1, 1, False) == "credit"
    curd.add_payment(
        payment(
            product="plus",
            credits=300,
            until=datetime.now(UTC) + timedelta(days=1),
            charge_id="sub",
            provider="sub-provider",
        )
    )
    assert payments.decide_charge(1, 1, True) == "sub"
    assert payments.decide_charge(1, 999, True) == "free"
    payments.PAYMENTS_ENABLED = False
    assert payments.decide_charge(1, 1, False) == "free"


@pytest.mark.parametrize(
    "case",
    [
        (29, 0, 0, True, "free"),
        (30, 1, 5, True, "sub"),
        (30, 0, 1, True, "credit"),
        (30, 0, 0, True, "paywall"),
        (30, 0, 0, False, "group_limit"),
    ],
)
def test_disabled_gate_records_shadow_but_returns_free(payments, monkeypatch, caplog, case):
    free_count, sub_count, credit_count, private, decision = case
    payments.PAYMENTS_ENABLED = False
    monkeypatch.setattr(payments, "free_used", lambda _: free_count)
    monkeypatch.setattr(payments, "sub_left", lambda _: sub_count)
    monkeypatch.setattr(payments, "credits_left", lambda _: credit_count)
    caplog.set_level("INFO")
    assert payments.decide_charge(10, 1, private) == "free"
    assert payments.shadow_decisions == {decision: 1}
    assert (f"chat=10 sender=1 decision={decision}" in caplog.text) is (decision != "free")
    assert payments.decide_charge(10, 999, private) == "free"
    assert payments.shadow_decisions == {decision: 1}


def test_group_free_allowance_belongs_to_chat_paid_allowance_to_sender(payments, sessions):
    with sessions() as session:
        session.add_all([conversion(user_id=-20) for _ in range(30)])
        session.commit()
    curd.add_payment(payment())
    assert payments.decide_charge(-20, 1, False) == "credit"
    assert payments.decide_charge(-20, 2, False) == "group_limit"
    assert payments.decide_charge(1, 1, True) == "free"


def test_rolling_boundary(monkeypatch, sessions):
    now = datetime(2026, 11, 18, tzinfo=UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(curd, "datetime", Clock)
    with sessions() as session:
        session.add_all(
            [
                conversion(created_at=now - timedelta(days=30, seconds=1)),
                conversion(created_at=now - timedelta(days=30)),
                conversion(created_at=now, success=False),
                conversion(created_at=now, charge="credit"),
            ]
        )
        session.commit()
    assert curd.free_used(1) == 1


def test_subscriptions_active_lapsed_overlapping_and_failures(sessions):
    now = datetime.now(UTC)
    curd.add_payment(payment(until=now - timedelta(seconds=1)))
    assert curd.sub_left(1) == 0
    curd.add_payment(
        payment(
            product="plus",
            credits=300,
            until=now + timedelta(days=10),
            charge_id="plus",
            provider="plus",
        )
    )
    assert curd.sub_left(1) == 300
    curd.add_payment(
        payment(
            product="pro",
            credits=1500,
            until=now + timedelta(days=25),
            charge_id="pro",
            provider="pro",
        )
    )
    with sessions() as session:
        session.add_all(
            [
                conversion(charge="sub", created_at=now - timedelta(days=21)),
                conversion(charge="sub", created_at=now - timedelta(days=19)),
                conversion(charge="sub", success=False),
            ]
        )
        session.commit()
    assert curd.sub_left(1) == 1799


def test_credits_partly_used_and_refunded_excluded(sessions):
    curd.add_payment(payment())
    curd.add_payment(
        payment(credits=300, charge_id="refunded", provider="refunded", status="refunded")
    )
    curd.record_conversion_event(conversion(charge="credit"))
    curd.record_conversion_event(conversion(charge="credit", success=False))
    assert curd.credits_left(1) == 49
    assert curd.payment_usage(curd.find_payment("provider")) == 1
    curd.mark_refunded("provider")
    assert curd.credits_left(1) == -1
    row = curd.find_payment("provider")
    assert row.status == "refunded"
    assert row.refunded_at is not None


@pytest.mark.parametrize("used", [0, 12, 62, 200])
def test_pack_usage_is_fifo_and_excludes_refunded_packs(sessions, used):
    now = datetime.now(UTC)
    for key, status in (
        ("refunded", "refunded"),
        ("first", "paid"),
        ("second", "paid"),
        ("third", "paid"),
    ):
        row = payment(charge_id=key, provider=key, status=status)
        row.created_at = now
        curd.add_payment(row)
    with sessions() as session:
        session.add_all([conversion(charge="credit") for _ in range(used)])
        session.add(conversion(charge="credit", success=False))
        session.add(conversion(charge="credit", user_id=2))
        session.commit()
    for index, key in enumerate(("first", "second", "third")):
        assert curd.payment_usage(curd.find_payment(key)) == max(0, min(50, used - index * 50))


@pytest.mark.parametrize("days", [-10, 10])
def test_subscription_usage_is_limited_to_its_period(sessions, days):
    until = datetime.now(UTC) + timedelta(days=days)
    start = until - timedelta(days=30)
    curd.add_payment(payment(product="plus", credits=300, until=until))
    with sessions() as session:
        session.add_all(
            [
                conversion(charge="sub", created_at=start - timedelta(seconds=1)),
                conversion(charge="sub", created_at=start),
                conversion(charge="sub", created_at=until - timedelta(seconds=1)),
                conversion(charge="sub", created_at=until),
                conversion(charge="sub", created_at=start, success=False),
                conversion(charge="credit", created_at=start),
                conversion(charge="sub", created_at=start, user_id=2),
            ]
        )
        session.commit()
    assert curd.payment_usage(curd.find_payment("provider")) == 2


@pytest.mark.parametrize(
    ("payload", "user", "currency", "amount"),
    [
        (b"pack_s:1", 2, "XTR", 100),
        (b"pack_s:1", 1, "USD", 100),
        (b"pack_s:1", 1, "XTR", 99),
        (b"unknown:1", 1, "XTR", 100),
        (b"pack_s:garbage", 1, "XTR", 100),
        (b"pack_s:1:2", 1, "XTR", 100),
        (b"\xff", 1, "XTR", 100),
        (b"", 1, "XTR", 100),
        (b"pack_s:0", 0, "XTR", 100),
    ],
)
def test_payload_rejected(payments, payload, user, currency, amount):
    with pytest.raises(ValueError, match="send /buy"):
        payments.validate_payment(payload, user, currency, amount)


@pytest.mark.parametrize(
    "key", ["pack_s", "pack_l", "plus", "pro", "donate_50", "donate_250", "donate_1000"]
)
def test_valid_products(payments, key):
    item = payments.PRODUCTS[key]
    assert payments.validate_payment(f"{key}:1".encode(), 1, "XTR", item.stars) == key


def transaction(**changes):
    values = {
        "id": "transaction",
        "amount": types.StarsAmount(100, 0),
        "date": datetime.now(UTC),
        "peer": types.StarsTransactionPeer(types.PeerUser(1)),
        "bot_payload": b"pack_s:1",
    }
    values.update(changes)
    return types.StarsTransaction(**values)


def test_duplicate_and_reconciliation_match_either_charge_id(payments, sessions):
    assert curd.add_payment(payment(charge_id="transaction"))
    assert not curd.add_payment(payment(charge_id="transaction"))
    payments.reconcile_transaction(transaction())
    payments.reconcile_transaction(transaction(id="provider"))
    missing = transaction(id="missing", date=datetime.now(UTC) + timedelta(minutes=2))
    payments.reconcile_transaction(missing)
    payments.reconcile_transaction(missing)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 2
    assert curd.credits_left(1) == 100
    payments.reconcile_transaction(
        transaction(id="provider", amount=types.StarsAmount(-100, 0), refund=True)
    )
    assert curd.credits_left(1) == 50
    assert curd.find_payment("provider").status == "refunded"
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 2


@pytest.mark.parametrize("seconds", [-61, -60, 0, 60, 61])
def test_reconciliation_matches_recent_payment_with_unknown_id(payments, sessions, seconds):
    now = datetime.now(UTC)
    row = payment()
    row.created_at = now
    curd.add_payment(row)
    payments.reconcile_transaction(transaction(date=now + timedelta(seconds=seconds)))
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == (
            2 if abs(seconds) > 60 else 1
        )


def test_reconciled_subscription_and_late_service_update(payments, sessions):
    tx = transaction(
        bot_payload=b"plus:1",
        amount=types.StarsAmount(250, 0),
        subscription_period=payments.SUB_PERIOD,
    )
    payments.reconcile_transaction(tx)
    row = curd.find_payment(tx.id)
    assert not row.recurring
    assert row.subscription_until.replace(tzinfo=UTC) == tx.date + timedelta(
        seconds=payments.SUB_PERIOD
    )
    assert curd.sub_left(1) == 300
    # An actual service update replaces provisional transaction IDs, not the balance.
    incoming = payment(
        product="plus",
        credits=300,
        until=tx.date + timedelta(seconds=payments.SUB_PERIOD),
        charge_id="real-charge",
        provider=tx.id,
    )
    incoming.recurring = True
    assert not curd.add_payment(incoming)
    assert curd.find_payment(tx.id).charge_id == "real-charge"
    assert curd.find_payment(tx.id).recurring
    assert curd.sub_left(1) == 300


@pytest.mark.parametrize("seconds", [-86401, -86400, 0, 86400, 86401])
def test_reconciled_subscription_detects_renewal_near_prior_expiry(payments, sessions, seconds):
    date = datetime.now(UTC)
    previous = payment(product="plus", credits=300, until=date + timedelta(seconds=seconds))
    previous.created_at = date - timedelta(days=30)
    curd.add_payment(previous)
    payments.reconcile_transaction(
        transaction(
            date=date,
            bot_payload=b"plus:1",
            amount=types.StarsAmount(250, 0),
            subscription_period=payments.SUB_PERIOD,
        )
    )
    assert curd.find_payment("transaction").recurring is (abs(seconds) <= 86400)


def test_reconciliation_recovers_two_renewals_oldest_first(payments, sessions):
    now = datetime.now(UTC)
    initial = payment(product="plus", credits=300, until=now - timedelta(days=30))
    initial.created_at = now - timedelta(days=60)
    curd.add_payment(initial)
    for key, date in (("r1", now - timedelta(days=30)), ("r2", now)):
        payments.reconcile_transaction(
            transaction(
                id=key,
                date=date,
                bot_payload=b"plus:1",
                amount=types.StarsAmount(250, 0),
                subscription_period=payments.SUB_PERIOD,
            )
        )
        assert curd.find_payment(key).recurring
    assert curd.first_subscription_charge(curd.find_payment("r2")) == "provider"


@pytest.mark.parametrize("payload", [b"pack_s:1", None])
def test_reconciliation_refunds_old_price_but_rejects_new_wrong_price(payments, sessions, payload):
    curd.add_payment(payment())
    payments.PRODUCTS["pack_s"] = payments.Product("pack", 120, 50)
    payments.reconcile_transaction(
        transaction(
            id="provider", amount=types.StarsAmount(-100, 0), refund=True, bot_payload=payload
        )
    )
    assert curd.find_payment("provider").status == "refunded"
    with pytest.raises(ValueError, match="Price changed"):
        payments.reconcile_transaction(transaction())
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Payment)) == 1


@pytest.mark.parametrize("changes", [{"pending": True}, {"failed": True}, {"bot_payload": None}])
def test_reconciliation_skips_unpaid_transactions(payments, sessions, changes):
    payments.reconcile_transaction(transaction(**changes))
    assert curd.find_payment("transaction") is None


def test_reconciliation_rejects_untrusted_payload(payments, sessions):
    for tx in (
        transaction(bot_payload=b"pack_s:2"),
        transaction(amount=types.StarsAmount(99, 0)),
        transaction(amount=types.StarsAmount(100, 1)),
    ):
        with pytest.raises(ValueError, match=r"invalid payment|Fractional Stars"):
            payments.reconcile_transaction(tx)
    assert curd.find_payment("transaction") is None


def test_paywall_timestamp_is_first_only(sessions):
    curd.add_chat_to_db(1, "reader", 0)
    curd.mark_paywall(1)
    with sessions() as session:
        first = session.scalar(select(Chat.paywall_seen_at))
    curd.mark_paywall(1)
    curd.mark_paywall(999)
    with sessions() as session:
        assert session.scalar(select(Chat.paywall_seen_at)) == first


def test_invoice_links_and_localized_precheckout(payments, monkeypatch, sessions):
    calls = []

    async def telegram(request):
        calls.append(request)
        return SimpleNamespace(url="https://t.me/invoice")

    monkeypatch.setattr(payments, "BOT", telegram)
    # compiled .mo files are generated, so check the payer's language is used, not the catalog
    monkeypatch.setattr(payments, "_", lambda text, lang: f"{lang}:{text}")
    curd.update_language(2, "ar")

    async def run():
        await payments.invoice_link(1, "plus", "Plus")
        await payments.invoice_link(1, "plus", "Plus")
        assert len(calls) == 1
        media = calls[0].invoice_media
        assert media.provider == ""
        assert media.payload == b"plus:1"
        assert media.invoice.currency == "XTR"
        assert media.invoice.subscription_period == payments.SUB_PERIOD
        await payments.invoice_link(1, "plus", "بلس")
        assert len(calls) == 2
        assert calls[-1].invoice_media.title == "بلس"
        await payments.invoice_link(1, "pack_s", "Pack S")
        assert calls[-1].invoice_media.invoice.subscription_period is None
        await payments.precheckout(types.UpdateBotPrecheckoutQuery(10, 1, b"plus:1", "XTR", 250))
        assert calls[-1].success
        await payments.precheckout(types.UpdateBotPrecheckoutQuery(11, 2, b"plus:1", "XTR", 250))
        assert not calls[-1].success
        assert calls[-1].error == "ar:Price changed or invalid payment, send /buy or /donate again."

    asyncio.run(run())


def test_group_buy_status_uses_chat_free_quota_and_payer_plan(payments, sessions, monkeypatch):
    with sessions() as session:
        session.add_all([conversion(user_id=-20) for _ in range(30)])
        session.commit()
    curd.add_payment(payment())
    replies = []

    async def invoice_link(*args):
        return "https://t.me/invoice"

    async def reply(text, **kwargs):
        replies.append(text)

    monkeypatch.setattr(payments, "invoice_link", invoice_link)
    asyncio.run(payments.show_buy(SimpleNamespace(chat_id=-20, sender_id=1, reply=reply)))
    assert replies[0].startswith("Free: 0 left this month. Plan: 0 left. Pack credits: 50.")


def test_payment_statistics(sessions):
    curd.add_chat_to_db(1, "reader", 0)
    curd.mark_paywall(1)
    curd.add_payment(payment())
    curd.add_payment(payment(charge_id="refunded", provider="refunded", status="refunded"))
    curd.add_payment(
        payment(
            product="plus",
            until=datetime.now(UTC) + timedelta(days=1),
            charge_id="plus",
            provider="plus",
        )
    )
    with sessions() as session:
        session.add_all([conversion() for _ in range(31)])
        session.add(conversion(charge="credit"))
        session.commit()
    result = curd.payment_stats()
    assert (
        result["over"],
        result["seen"],
        result["payers"],
        result["subs"],
        result["sold"],
        result["used"],
    ) == (1, 1, 1, 1, 50, 1)
    assert ("pack", "refunded", 100) in result["stars"]


def test_service_payment_delivery_is_idempotent(payments, sessions, monkeypatch):
    sent = []

    async def send_message(user_id, text):
        sent.append((user_id, text))

    monkeypatch.setattr(payments.BOT, "send_message", send_message, raising=False)
    action = types.MessageActionPaymentSentMe(
        "XTR", 100, b"pack_s:1", types.PaymentCharge("service-charge", "service-provider")
    )
    message = types.MessageService(
        id=1,
        peer_id=types.PeerUser(1),
        date=datetime.now(UTC),
        action=action,
    )
    update = types.UpdateNewMessage(message, 1, 1)
    assert events.NewMessage.build(update) is None

    async def run():
        await payments.payment_received(update)
        await payments.payment_received(update)
        action.total_amount = 99
        await payments.payment_received(update)

    asyncio.run(run())
    assert len(sent) == 1
    assert curd.credits_left(1) == 50
    assert curd.find_payment("service-charge").provider_charge_id == "service-provider"


@pytest.mark.parametrize("charge", ["paywall", "group_limit"])
def test_converter_gate_keeps_the_request(converter_module, monkeypatch, charge):
    module = converter_module
    event = UploadEvent("book.md")
    shown = []
    monkeypatch.setattr(module, "decide_charge", lambda *args: charge)
    monkeypatch.setattr(module, "mark_paywall", shown.append)

    async def show_buy(event):
        assert event.answers == []  # the message goes out before the late-prone answer
        shown.append("buy")

    monkeypatch.setattr(module, "show_buy", show_buy)

    async def run():
        await module.file_converter.__wrapped__(event)
        request_id = next(iter(module.queue))
        event.data = f"run|epub|{request_id}".encode()
        await module.converter_callback.__wrapped__(event)
        assert request_id in module.queue
        assert not module.active_users

    asyncio.run(run())
    assert shown == ([event.chat_id, "buy"] if charge == "paywall" else [])
    assert event.answers == [""]


@pytest.mark.parametrize("charge", ["free", "sub", "credit"])
@pytest.mark.parametrize("success", [True, False])
def test_converter_records_charge_and_remaining(converter_module, monkeypatch, charge, success):
    module = converter_module
    event = UploadEvent("book.md")
    recorded = []
    monkeypatch.setattr(module, "decide_charge", lambda *args: charge)
    monkeypatch.setattr(module, "record_conversion_event", recorded.append)
    monkeypatch.setattr(module, "PAYMENTS_ENABLED", True)
    monkeypatch.setattr(module, "free_used", lambda _: 29)
    monkeypatch.setattr(module, "sub_left", lambda _: 10)
    monkeypatch.setattr(module, "credits_left", lambda _: 20)

    async def convert(input_file, *args, **kwargs):
        output = input_file.with_suffix(".epub")
        output.write_bytes(b"converted")
        return SimpleNamespace(
            backend="calibre",
            output_files=[output] if success else [],
            split_capped=False,
            conversion_error=None if success else "Failed",
            converted_to_rtl=False,
        )

    monkeypatch.setattr(module.converter, "convert_ebook_many", convert)

    async def run():
        await module.file_converter.__wrapped__(event)
        request_id = next(iter(module.queue))
        event.data = f"run|epub|{request_id}".encode()
        await module.converter_callback.__wrapped__(event)

    asyncio.run(run())
    row = recorded[0]
    assert (row.charge, row.payer_id, row.success) == (
        charge,
        None if charge == "free" else event.sender_id,
        success,
    )
    if success:
        assert event.edits[-1].endswith(
            "1 free conversions left this month. /buy"
            if charge == "free"
            else f"{10 if charge == 'sub' else 20} conversions left in your plan."
        )
    else:
        assert "conversions left" not in event.edits[-1]


@pytest.mark.parametrize(
    "item",
    [
        ("pack_s", "pack", False),
        ("plus", "sub", False),
        ("plus", "sub", True),
        ("donate_50", "donation", False),
    ],
)
def test_refund_marks_payment_and_cancels_subscriptions(payments, sessions, monkeypatch, item):
    product, kind, resubscribed = item
    calls, replies = [], []
    until = datetime.now(UTC) + timedelta(days=10) if kind == "sub" else None
    row = payment(product=product, credits=payments.PRODUCTS[product].credits, until=until)
    row.kind, row.recurring = kind, kind == "sub"
    if kind == "sub":
        if resubscribed:
            old = payment(
                product=product,
                until=datetime.now(UTC) - timedelta(days=60),
                charge_id="old",
                provider="old-provider",
            )
            old.created_at = datetime.now(UTC) - timedelta(days=90)
            curd.add_payment(old)
        initial = payment(
            product=product, until=until, charge_id="initial", provider="initial-provider"
        )
        initial.created_at = datetime.now(UTC) - timedelta(days=30)
        curd.add_payment(initial)
    curd.add_payment(row)
    curd.record_conversion_event(conversion(charge="sub" if kind == "sub" else "credit"))

    async def telegram(request):
        calls.append(request)

    async def input_entity(user_id):
        assert user_id == 1
        return types.InputUser(1, 123)

    async def reply(text):
        replies.append(text)

    telegram.get_input_entity = input_entity
    monkeypatch.setattr(payments, "BOT", telegram)
    event = SimpleNamespace(
        chat_id=1, pattern_match=SimpleNamespace(group=lambda _: "provider"), reply=reply
    )
    asyncio.run(payments.refund.__wrapped__(event))
    assert curd.find_payment("provider").status == "refunded"
    assert calls[0].charge_id == "provider"
    assert calls[0].user_id.user_id == 1
    assert len(calls) == (2 if kind == "sub" else 1)
    assert ("Warning:" in replies[0]) is (kind != "donation")
    if kind != "donation":
        assert f"1 of {payments.PRODUCTS[product].credits}" in replies[0]
    if kind == "sub":
        assert type(calls[1]).__name__ == "BotCancelStarsSubscriptionRequest"
        assert calls[1].charge_id == "initial-provider"


def test_subscription_cancellation_ignores_a_later_chain_and_falls_back(sessions):
    now = datetime.now(UTC)
    for key, days, recurring in (("old", 90, False), ("renewal", 60, True), ("new", 30, False)):
        row = payment(
            product="plus", until=now - timedelta(days=days - 30), charge_id=key, provider=key
        )
        row.created_at, row.recurring = now - timedelta(days=days), recurring
        curd.add_payment(row)
    assert curd.first_subscription_charge(curd.find_payment("renewal")) == "old"
    curd.mark_refunded("old")
    assert curd.first_subscription_charge(curd.find_payment("renewal")) == "renewal"


def test_disabled_converter_records_free_despite_shadow_paywall(
    converter_module, payments, monkeypatch
):
    module = converter_module
    payments.PAYMENTS_ENABLED = False
    monkeypatch.setattr(payments, "free_used", lambda _: 30)
    monkeypatch.setattr(payments, "sub_left", lambda _: 0)
    monkeypatch.setattr(payments, "credits_left", lambda _: 0)
    monkeypatch.setattr(module, "decide_charge", payments.decide_charge)
    monkeypatch.setattr(module, "PAYMENTS_ENABLED", False)
    recorded = []
    monkeypatch.setattr(module, "record_conversion_event", recorded.append)

    async def convert(input_file, *args, **kwargs):
        output = input_file.with_suffix(".epub")
        output.write_bytes(b"converted")
        return SimpleNamespace(
            backend="calibre",
            output_files=[output],
            split_capped=False,
            conversion_error=None,
            converted_to_rtl=False,
        )

    monkeypatch.setattr(module.converter, "convert_ebook_many", convert)
    event = UploadEvent("book.md")

    async def run():
        await module.file_converter.__wrapped__(event)
        event.data = f"run|epub|{next(iter(module.queue))}".encode()
        await module.converter_callback.__wrapped__(event)

    asyncio.run(run())
    assert payments.shadow_decisions == {"paywall": 1}
    assert (recorded[0].charge, recorded[0].payer_id, recorded[0].success) == ("free", None, True)


def test_stats_show_shadow_counts_only_when_disabled(payments, sessions, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "ebook_converter_bot/modules/stats.py"
    spec = importlib.util.spec_from_file_location("_test_payment_stats", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PAYMENTS_ENABLED", False)
    monkeypatch.setattr(module, "shadow_decisions", payments.shadow_decisions)
    payments.shadow_decisions["paywall"] = 2
    messages = []

    async def edit(text):
        messages.append(text)

    async def reply(text):
        return SimpleNamespace(edit=edit)

    event = SimpleNamespace(chat_id=1, reply=reply)
    asyncio.run(module.stats(event))
    assert messages[-1].endswith("Shadow decisions: {'paywall': 2}")
    module.PAYMENTS_ENABLED = True
    asyncio.run(module.stats(event))
    assert "Shadow decisions:" not in messages[-1]


def test_reconciliation_loop_survives_bad_transactions(payments, sessions, monkeypatch):
    async def telegram(request):
        assert (request.inbound, request.ascending, request.offset, request.limit) == (
            None,
            True,
            "",
            100,
        )
        return SimpleNamespace(
            history=[transaction(bot_payload=b"bad"), transaction()], next_offset=None
        )

    async def sleep(delay):
        assert delay == 86400
        raise asyncio.CancelledError

    monkeypatch.setattr(payments, "BOT", telegram)
    monkeypatch.setattr(payments.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(payments.reconciliation_loop())
    assert curd.credits_left(1) == 50


def test_reconciliation_loop_handles_empty_history(payments, monkeypatch):
    async def telegram(request):
        return SimpleNamespace(history=None, next_offset=None)

    async def sleep(delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(payments, "BOT", telegram)
    monkeypatch.setattr(payments.asyncio, "sleep", sleep)
    errors = []
    monkeypatch.setattr(payments.LOGGER, "exception", lambda *args: errors.append(args))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(payments.reconciliation_loop())
    assert errors == []


def test_migration_backfills_existing_events(monkeypatch, tmp_path):
    _patch_database(monkeypatch, tmp_path / "payments.db")
    command.upgrade(db_session.get_alembic_config(), "20260518_0002")
    with db_session.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO conversion_events (user_id, input_format, output_format, success, created_at) VALUES (1, 'epub', 'pdf', 1, CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(db_session.get_alembic_config(), "head")
    with db_session.engine.connect() as connection:
        assert connection.execute(text("SELECT charge, payer_id FROM conversion_events")).one() == (
            "free",
            None,
        )
    inspector = inspect(db_session.engine)
    assert "payments" in inspector.get_table_names()
    assert any(
        index["column_names"] == ["payer_id", "charge"]
        for index in inspector.get_indexes("conversion_events")
    )
    assert any(
        constraint["column_names"] == ["provider_charge_id"]
        for constraint in inspector.get_unique_constraints("payments")
    )
