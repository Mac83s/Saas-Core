"""What commerce writes to a buyer (ADR-073 §5, §8): the transfer's details
with the order's number, the amount and the date it is awaited until; the
rest of the price when it is due by a transfer, and again when its date has
passed; what comes back of what they paid when the order is canceled; and
that the company has given money back — or that such a note was a mistake.

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
    AUDIENCE_STAFF,
    EmailTemplate,
    queue_email,
    register_email_template,
)

from .models import Order, OrderLine, Payment, PaymentMethod, Refund
from .transfer_account import TransferAccount

TRANSFER_DETAILS = "commerce.transfer_details"
#: The rest of the price, due by a transfer: sent when it is planned and once
#: more as its date comes near.
BALANCE_DETAILS = "commerce.balance_details"
#: Its date has passed. Nothing is canceled by that (owner decision 29a).
BALANCE_OVERDUE = "commerce.balance_overdue"
#: The same, to the company's people who manage payments.
OFFICE_BALANCE_OVERDUE = "commerce.office_balance_overdue"
#: What comes back of what the buyer paid for a canceled order.
REFUND_SETTLED = "commerce.refund_settled"
#: The company marked a refund: the money is on its way, or was handed over.
REFUND_MARKED = "commerce.refund_marked"
#: That refund was marked by mistake and taken back.
REFUND_WITHDRAWN = "commerce.refund_withdrawn"

#: How a refund the company marks by hand was made, as its mail says it.
_REFUND_METHOD = {
    PaymentMethod.TRANSFER.value: {
        "pl": "przelewem",
        "en": "by bank transfer",
        "de": "per Überweisung",
    },
    # At the desk: cash or the company's own card terminal.
    PaymentMethod.CASH.value: {"pl": "na miejscu", "en": "at the desk", "de": "vor Ort"},
}
_REFUND_CONTEXT = frozenset({"number", "organization_name", "subject", "refund", "method"})

_BALANCE_CONTEXT = frozenset({
    "number",
    "organization_name",
    "subject",
    "amount",
    "due_at",
    "account_holder",
    "account_number",
    "manage_url",
})

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
    EmailTemplate(
        key=BALANCE_DETAILS,
        version=1,
        category="required",
        audience=AUDIENCE_CUSTOMER,
        subjects={
            "pl": "Zamówienie {number} — dopłata do {due_at}",
            "en": "Order {number} — the balance is due by {due_at}",
            "de": "Bestellung {number} — Restzahlung bis {due_at}",
        },
        bodies={
            "pl": (
                "<p>Zamówienie {number} w {organization_name}: {subject}.</p>"
                "<p>Do zapłaty pozostało {amount}. Prosimy o przelew do {due_at}.</p>"
                "<p>Odbiorca: {account_holder}<br>Numer rachunku: {account_number}<br>"
                "Tytuł przelewu: {number}</p>"
                '<p><a href="{manage_url}">Zobacz rezerwację</a></p>'
            ),
            "en": (
                "<p>Order {number} at {organization_name}: {subject}.</p>"
                "<p>{amount} is left to pay. Please transfer it by {due_at}.</p>"
                "<p>Recipient: {account_holder}<br>Account number: {account_number}<br>"
                "Transfer title: {number}</p>"
                '<p><a href="{manage_url}">See the booking</a></p>'
            ),
            "de": (
                "<p>Bestellung {number} bei {organization_name}: {subject}.</p>"
                "<p>Es sind noch {amount} zu zahlen. Bitte überweisen Sie den Betrag bis "
                "{due_at}.</p>"
                "<p>Empfänger: {account_holder}<br>Kontonummer: {account_number}<br>"
                "Verwendungszweck: {number}</p>"
                '<p><a href="{manage_url}">Buchung ansehen</a></p>'
            ),
        },
        allowed_context=_BALANCE_CONTEXT,
    ),
    EmailTemplate(
        key=BALANCE_OVERDUE,
        version=1,
        category="required",
        audience=AUDIENCE_CUSTOMER,
        subjects={
            "pl": "Zamówienie {number} — termin dopłaty minął",
            "en": "Order {number} — the balance is overdue",
            "de": "Bestellung {number} — Restzahlung überfällig",
        },
        bodies={
            "pl": (
                "<p>Zamówienie {number} w {organization_name}: {subject}.</p>"
                "<p>Termin dopłaty {amount} minął {due_at}. Prosimy o przelew jak "
                "najszybciej. Rezerwacja pozostaje ważna; o dalszych krokach decyduje "
                "{organization_name}.</p>"
                "<p>Odbiorca: {account_holder}<br>Numer rachunku: {account_number}<br>"
                "Tytuł przelewu: {number}</p>"
                '<p><a href="{manage_url}">Zobacz rezerwację</a></p>'
            ),
            "en": (
                "<p>Order {number} at {organization_name}: {subject}.</p>"
                "<p>The balance of {amount} was due by {due_at}. Please transfer it as "
                "soon as you can. Your booking still stands; what happens next is "
                "{organization_name}'s decision.</p>"
                "<p>Recipient: {account_holder}<br>Account number: {account_number}<br>"
                "Transfer title: {number}</p>"
                '<p><a href="{manage_url}">See the booking</a></p>'
            ),
            "de": (
                "<p>Bestellung {number} bei {organization_name}: {subject}.</p>"
                "<p>Die Restzahlung von {amount} war bis {due_at} fällig. Bitte überweisen "
                "Sie den Betrag so bald wie möglich. Ihre Buchung bleibt bestehen; über das "
                "weitere Vorgehen entscheidet {organization_name}.</p>"
                "<p>Empfänger: {account_holder}<br>Kontonummer: {account_number}<br>"
                "Verwendungszweck: {number}</p>"
                '<p><a href="{manage_url}">Buchung ansehen</a></p>'
            ),
        },
        allowed_context=_BALANCE_CONTEXT,
    ),
    EmailTemplate(
        key=OFFICE_BALANCE_OVERDUE,
        version=1,
        category="required",
        audience=AUDIENCE_STAFF,
        subjects={
            "pl": "Zamówienie {number} — dopłata nie wpłynęła w terminie",
            "en": "Order {number} — the balance did not arrive in time",
        },
        bodies={
            "pl": (
                "<p>{organization_name}: dopłata {amount} do zamówienia {number} miała "
                "wpłynąć do {due_at} i nie została oznaczona.</p>"
                "<p>Rezerwacja pozostaje potwierdzona. Klient dostał przypomnienie. Jeśli "
                "przelew dotarł, oznacz wpłatę w zamówieniu; o odwołaniu rezerwacji "
                "decydujesz samodzielnie.</p>"
                '<p><a href="{panel_url}">Otwórz zamówienie</a></p>'
            ),
            "en": (
                "<p>{organization_name}: the balance of {amount} for order {number} was "
                "due by {due_at} and has not been marked.</p>"
                "<p>The booking stays confirmed. The customer got a reminder. If the "
                "transfer arrived, mark the payment on the order; calling the booking off "
                "is your own decision.</p>"
                '<p><a href="{panel_url}">Open the order</a></p>'
            ),
        },
        allowed_context=frozenset({
            "number",
            "organization_name",
            "amount",
            "due_at",
            "panel_url",
        }),
    ),
    EmailTemplate(
        key=REFUND_SETTLED,
        version=1,
        category="required",
        audience=AUDIENCE_CUSTOMER,
        subjects={
            "pl": "Zamówienie {number} — rozliczenie wpłaty",
            "en": "Order {number} — what you paid",
            "de": "Bestellung {number} — Abrechnung Ihrer Zahlung",
        },
        bodies={
            "pl": (
                "<p>Zamówienie {number} w {organization_name} ({subject}) zostało "
                "anulowane.</p>"
                "<p>Wpłacono: {paid}<br>Do zwrotu: {refund}</p>"
                "<p>Kwota zwrotu wynika z warunków, na których złożono rezerwację. Zwrot "
                "przekazuje {organization_name}.</p>"
            ),
            "en": (
                "<p>Order {number} at {organization_name} ({subject}) has been canceled.</p>"
                "<p>Paid: {paid}<br>To be refunded: {refund}</p>"
                "<p>The refund follows the terms the booking was made under. "
                "{organization_name} returns it to you.</p>"
            ),
            "de": (
                "<p>Die Bestellung {number} bei {organization_name} ({subject}) wurde "
                "storniert.</p>"
                "<p>Gezahlt: {paid}<br>Erstattung: {refund}</p>"
                "<p>Die Erstattung richtet sich nach den Bedingungen, zu denen gebucht "
                "wurde. {organization_name} zahlt sie an Sie zurück.</p>"
            ),
        },
        allowed_context=frozenset({
            "number",
            "organization_name",
            "subject",
            "paid",
            "refund",
        }),
    ),
    # The company's own reason for a refund is never here: it may name
    # somebody, and it stays on the order's page (§8).
    EmailTemplate(
        key=REFUND_MARKED,
        version=1,
        category="required",
        audience=AUDIENCE_CUSTOMER,
        subjects={
            "pl": "Zamówienie {number} — zwrot {refund}",
            "en": "Order {number} — refund of {refund}",
            "de": "Bestellung {number} — Erstattung von {refund}",
        },
        bodies={
            "pl": (
                "<p>{organization_name} przekazuje zwrot za zamówienie {number} "
                "({subject}).</p>"
                "<p>Kwota: {refund}<br>Sposób: {method}</p>"
                "<p>Na pytania o zwrot odpowiada {organization_name}.</p>"
            ),
            "en": (
                "<p>{organization_name} is returning money for order {number} ({subject}).</p>"
                "<p>Amount: {refund}<br>How: {method}</p>"
                "<p>{organization_name} answers any questions about the refund.</p>"
            ),
            "de": (
                "<p>{organization_name} erstattet Geld für die Bestellung {number} "
                "({subject}).</p>"
                "<p>Betrag: {refund}<br>Art: {method}</p>"
                "<p>Fragen zur Erstattung beantwortet {organization_name}.</p>"
            ),
        },
        allowed_context=_REFUND_CONTEXT,
    ),
    EmailTemplate(
        key=REFUND_WITHDRAWN,
        version=1,
        category="required",
        audience=AUDIENCE_CUSTOMER,
        subjects={
            "pl": "Zamówienie {number} — korekta wiadomości o zwrocie",
            "en": "Order {number} — a correction about your refund",
            "de": "Bestellung {number} — Korrektur zur Erstattung",
        },
        bodies={
            "pl": (
                "<p>Wiadomość o zwrocie {refund} ({method}) za zamówienie {number} "
                "({subject}) została wysłana przez pomyłkę: {organization_name} wycofuje "
                "ten wpis.</p>"
                "<p>Ten zwrot nie został przekazany. Na pytania odpowiada "
                "{organization_name}.</p>"
            ),
            "en": (
                "<p>The message about a refund of {refund} ({method}) for order {number} "
                "({subject}) was sent by mistake: {organization_name} has taken that entry "
                "back.</p>"
                "<p>That refund was not made. {organization_name} answers any "
                "questions.</p>"
            ),
            "de": (
                "<p>Die Nachricht über eine Erstattung von {refund} ({method}) für die "
                "Bestellung {number} ({subject}) wurde irrtümlich gesendet: "
                "{organization_name} hat den Eintrag zurückgenommen.</p>"
                "<p>Diese Erstattung wurde nicht geleistet. Fragen beantwortet "
                "{organization_name}.</p>"
            ),
        },
        allowed_context=_REFUND_CONTEXT,
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
    queue_email(
        recipient_email=order.buyer_email,
        template_key=TRANSFER_DETAILS,
        template_version=2 if link else 1,
        locale=locale,
        template_context={
            "number": order.number,
            "organization_name": order.organization.name,
            "subject": _subject(order),
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


def balance(
    order: Order,
    payment: Payment,
    account: TransferAccount,
    *,
    link: str,
    step: str,
) -> None:
    """Tells the buyer about the rest of the price due by a transfer. `step`
    says which mail it is, and each goes once: `planned` when the balance is
    set, `reminder` as its date comes near, `overdue` when it has passed."""
    if not order.buyer_email or payment.due_at is None:
        return
    locale = order.customer.locale
    queue_email(
        recipient_email=order.buyer_email,
        template_key=BALANCE_OVERDUE if step == "overdue" else BALANCE_DETAILS,
        template_version=1,
        locale=locale,
        template_context={
            "number": order.number,
            "organization_name": order.organization.name,
            "subject": _subject(order),
            "amount": money(payment.amount_minor, payment.currency, locale),
            "due_at": local_time(payment.due_at, order.organization.timezone, locale),
            "account_holder": account.holder,
            "account_number": account.number,
            "manage_url": link,
        },
        # A balance moved to another date is planned anew, and says so again.
        idempotency_key=f"commerce-balance:{payment.id}:{step}:{payment.due_at.isoformat()}",
        causation_id=f"commerce-order:{order.id}",
    )


def refund_settled(order: Order, *, paid_minor: int, refund_minor: int) -> None:
    """Tells the buyer of a canceled order what comes back of what they paid."""
    if not order.buyer_email:
        return
    locale = order.customer.locale
    queue_email(
        recipient_email=order.buyer_email,
        template_key=REFUND_SETTLED,
        template_version=1,
        locale=locale,
        template_context={
            "number": order.number,
            "organization_name": order.organization.name,
            "subject": _subject(order),
            "paid": money(paid_minor, order.currency, locale),
            "refund": money(refund_minor, order.currency, locale),
        },
        # An order is canceled once.
        idempotency_key=f"commerce-refund-settled:{order.id}",
        causation_id=f"commerce-order:{order.id}",
    )


def refund_marked(order: Order, refund: Refund) -> None:
    """Tells the buyer that the company has given money back: how much and
    how. Until now only the transfer itself said so. A buyer without an
    e-mail gets nothing."""
    _refund_mail(order, refund, REFUND_MARKED, "marked")


def refund_withdrawn(order: Order, refund: Refund) -> None:
    """Tells the buyer that the refund they were written about was marked by
    mistake and taken back, so nobody waits for money that is not coming."""
    _refund_mail(order, refund, REFUND_WITHDRAWN, "withdrawn")


def _refund_mail(order: Order, refund: Refund, template: str, step: str) -> None:
    if not order.buyer_email:
        return
    locale = order.customer.locale
    words = _REFUND_METHOD[refund.method]
    queue_email(
        recipient_email=order.buyer_email,
        template_key=template,
        template_version=1,
        locale=locale,
        template_context={
            "number": order.number,
            "organization_name": order.organization.name,
            "subject": _subject(order),
            "refund": money(refund.amount_minor, refund.currency, locale),
            "method": words.get(locale) or words["en"],
        },
        # One per refund and step: a refund is marked once and taken back once.
        idempotency_key=f"commerce-refund-{step}:{refund.id}",
        causation_id=f"commerce-order:{order.id}",
    )


def _subject(order: Order) -> str:
    """What the order is for, in the buyer's language: its first line."""
    first = (
        OrderLine.all_objects.filter(
            organization_id=order.organization_id, order=order, revision=order.revision
        )
        .order_by("position")
        .first()
    )
    return first.customer_name if first else order.number


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
