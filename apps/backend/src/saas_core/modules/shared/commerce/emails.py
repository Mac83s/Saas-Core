"""What commerce writes to a buyer (ADR-073 §5): the transfer's details with
the order's number, the amount and the date it is awaited until.

A mail says the buyer's own order and nothing of anybody else's: the number,
what the first line is called in the buyer's language, the amount, the
company's account. It goes through the notification templates, in the buyer's
language where the template has it (pl, en, de), else English, then Polish.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import translation
from django.utils.formats import date_format

from saas_core.modules.shared.notifications.api import (
    AUDIENCE_CUSTOMER,
    EmailTemplate,
    queue_email,
    register_email_template,
)

from .models import Order, OrderLine, Payment
from .transfer_account import TransferAccount

TRANSFER_DETAILS = "commerce.transfer_details"

_TEMPLATES = (
    EmailTemplate(
        key=TRANSFER_DETAILS,
        version=1,
        category="required",
        audience=AUDIENCE_CUSTOMER,
        subjects={
            "pl": "Zamówienie {number} — dane do przelewu",
            "en": "Order {number} — transfer details",
            "de": "Bestellung {number} — Überweisungsdaten",
        },
        bodies={
            "pl": (
                "<p>Dziękujemy za zamówienie {number} w {organization_name}: {subject}.</p>"
                "<p>Czeka ono na wpłatę przelewem. Prosimy o wpłatę {amount} do {due_at}.</p>"
                "<p>Odbiorca: {account_holder}<br>Numer rachunku: {account_number}<br>"
                "Tytuł przelewu: {number}</p>"
                "<p>Jeśli wpłata nie dotrze w terminie, zamówienie wygaśnie.</p>"
            ),
            "en": (
                "<p>Thank you for your order {number} at {organization_name}: {subject}.</p>"
                "<p>It is waiting for a bank transfer. Please pay {amount} by {due_at}.</p>"
                "<p>Recipient: {account_holder}<br>Account number: {account_number}<br>"
                "Transfer title: {number}</p>"
                "<p>If the payment does not arrive in time, the order will expire.</p>"
            ),
            "de": (
                "<p>Vielen Dank für Ihre Bestellung {number} bei {organization_name}: "
                "{subject}.</p>"
                "<p>Sie wartet auf eine Überweisung. Bitte überweisen Sie {amount} bis "
                "{due_at}.</p>"
                "<p>Empfänger: {account_holder}<br>Kontonummer: {account_number}<br>"
                "Verwendungszweck: {number}</p>"
                "<p>Geht die Zahlung nicht rechtzeitig ein, verfällt die Bestellung.</p>"
            ),
        },
        allowed_context=frozenset({
            "number",
            "organization_name",
            "subject",
            "amount",
            "due_at",
            "account_holder",
            "account_number",
        }),
    ),
    # v2 carries the buyer's own link to what they bought, when the source has
    # one: without it a buyer who closed the page has no way back to give the
    # booking up. v1 stays for a source without a link.
    EmailTemplate(
        key=TRANSFER_DETAILS,
        version=2,
        category="required",
        audience=AUDIENCE_CUSTOMER,
        subjects={
            "pl": "Zamówienie {number} — dane do przelewu",
            "en": "Order {number} — transfer details",
            "de": "Bestellung {number} — Überweisungsdaten",
        },
        bodies={
            "pl": (
                "<p>Dziękujemy za zamówienie {number} w {organization_name}: {subject}.</p>"
                "<p>Czeka ono na wpłatę przelewem. Prosimy o wpłatę {amount} do {due_at}.</p>"
                "<p>Odbiorca: {account_holder}<br>Numer rachunku: {account_number}<br>"
                "Tytuł przelewu: {number}</p>"
                "<p>Jeśli wpłata nie dotrze w terminie, zamówienie wygaśnie.</p>"
                '<p><a href="{manage_url}">Zobacz szczegóły albo zrezygnuj</a></p>'
            ),
            "en": (
                "<p>Thank you for your order {number} at {organization_name}: {subject}.</p>"
                "<p>It is waiting for a bank transfer. Please pay {amount} by {due_at}.</p>"
                "<p>Recipient: {account_holder}<br>Account number: {account_number}<br>"
                "Transfer title: {number}</p>"
                "<p>If the payment does not arrive in time, the order will expire.</p>"
                '<p><a href="{manage_url}">See the details or cancel</a></p>'
            ),
            "de": (
                "<p>Vielen Dank für Ihre Bestellung {number} bei {organization_name}: "
                "{subject}.</p>"
                "<p>Sie wartet auf eine Überweisung. Bitte überweisen Sie {amount} bis "
                "{due_at}.</p>"
                "<p>Empfänger: {account_holder}<br>Kontonummer: {account_number}<br>"
                "Verwendungszweck: {number}</p>"
                "<p>Geht die Zahlung nicht rechtzeitig ein, verfällt die Bestellung.</p>"
                '<p><a href="{manage_url}">Details ansehen oder stornieren</a></p>'
            ),
        },
        allowed_context=frozenset({
            "number",
            "organization_name",
            "subject",
            "amount",
            "due_at",
            "account_holder",
            "account_number",
            "manage_url",
        }),
    ),
)


def register_templates() -> None:
    """From `CommerceConfig.ready`."""
    for template in _TEMPLATES:
        register_email_template(template)


def transfer_details(
    order: Order, payment: Payment, account: TransferAccount, *, link: str = ""
) -> None:
    """Tells the buyer where to pay, how much and until when — and, with the
    source's `link`, where they see what they bought and can give it up. A
    buyer without an e-mail gets nothing: the company that took the order
    tells them."""
    if not order.buyer_email or payment.due_at is None:
        return
    locale = order.customer.locale
    first = (
        OrderLine.all_objects.filter(
            organization_id=order.organization_id, order=order, revision=order.revision
        )
        .order_by("position")
        .first()
    )
    queue_email(
        recipient_email=order.buyer_email,
        template_key=TRANSFER_DETAILS,
        template_version=2 if link else 1,
        locale=locale,
        template_context={
            "number": order.number,
            "organization_name": order.organization.name,
            "subject": first.customer_name if first else order.number,
            "amount": money(payment.amount_minor, payment.currency, locale),
            "due_at": local_time(payment.due_at, order.organization.timezone, locale),
            "account_holder": account.holder,
            "account_number": account.number,
            **({"manage_url": link} if link else {}),
        },
        # One per awaited payment: a retry of the order's request sends no second.
        idempotency_key=f"commerce-transfer:{payment.id}",
        causation_id=f"commerce-order:{order.id}",
    )


def money(amount_minor: int, currency: str, locale: str) -> str:
    """An amount as its reader's language writes it: `1 250,00 PLN` in Polish
    and German, `1,250.00 PLN` in English."""
    whole, part = divmod(amount_minor, 100)
    english = locale == "en"
    grouped = f"{whole:,}".replace(",", "," if english else chr(0xA0))
    return f"{grouped}{'.' if english else ','}{part:02d} {currency}"


def local_time(value: datetime, zone: str, locale: str) -> str:
    """The wall clock of the company's place, written as the reader's
    language writes a date — a template is `str.format_map` over strings."""
    with translation.override(locale):
        return date_format(value.astimezone(ZoneInfo(zone)), "DATETIME_FORMAT")
