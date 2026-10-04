"""What a customer agrees to while booking (ADR-073 §9, phase 4c).

The company's booking terms and privacy policy are documents of
`shared.customers`. A customer who books for themselves is shown the ones in
force in their language and names the text rows they accepted; the booking
appends a line of the consent journal for each, in its own transaction, so a
booking and what was agreed to exist together or not at all. A marketing
consent is a line of its own, never part of accepting a document.

The language is the booking's: the visitor's when the company has it, else
the company's first (ADR-071 pkt 21). The reader never substitutes another
language. Booking terms in force without a text in the booking's language
close online booking in that language (the owner's decision of 2026-10-04):
the form says so and names the languages that have them, a write is 409
`booking_language_unavailable`, and the panel warns where the company sets
its languages and documents. Only the terms do that — a privacy policy
without a text in the language is not shown and not required.

The marketing consent is one optional box with one wording
(`customers.api.marketing_wording`), which the company may switch off
(`booking.online.marketing_consent`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.api import setting
from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.locales import (
    clamp_content_locale,
    organization_content_locales,
)
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.customers.api import (
    ConsentKind,
    Customer,
    DocumentInForce,
    DocumentKind,
    current_document,
    document_locales,
    marketing_wording,
    record_consent,
)

from .company_settings import MARKETING_CONSENT
from .security import PUBLIC_BOOKING_ROLE

#: The journal's `source` of what was agreed to while booking; the reference
#: is the booking's id, for a visit and a stay alike.
SOURCE = "booking.appointment"

#: The documents a booking form shows, in the order shown, and what the
#: customer states about each. Two separate statements — a working wording
#: until the lawyer answers (the plan's legal list, 03.10), and the one place
#: to change it. A language without its own wording reads the English one.
DOCUMENT_STATEMENTS: dict[str, dict[str, str]] = {
    DocumentKind.BOOKING_TERMS: {
        "pl": "Akceptuję regulamin",
        "en": "I accept the terms",
        "de": "Ich akzeptiere die Buchungsbedingungen",
        "es": "Acepto las condiciones",
        "ru": "Я принимаю условия",
    },
    DocumentKind.PRIVACY_POLICY: {
        "pl": "Zapoznałem się z polityką prywatności",
        "en": "I have read the privacy policy",
        "de": "Ich habe die Datenschutzerklärung gelesen",
        "es": "He leído la política de privacidad",
        "ru": "Я ознакомился с политикой конфиденциальности",
    },
}


@dataclass(frozen=True, slots=True)
class BookingConsents:
    """What the customer was shown and agreed to while booking.

    `documents` — the `text_id` of every document they accepted, as the form
    got them from `shown`; `marketing` — they ticked the marketing consent
    the form showed (`shown`'s `marketing`).
    """

    documents: tuple[UUID, ...] = ()
    marketing: bool = False


class DocumentsChanged(APIException):
    """The documents in force are not the ones the customer accepted: the
    answer carries what to show, and the booking is asked for again (the
    pattern of `quote_changed`)."""

    status_code = 409
    default_code = "documents_changed"
    default_detail = (
        "Dokumenty firmy nie zostały zaakceptowane albo zmieniły się. "
        "Przeczytaj obowiązujące i potwierdź ponownie."
    )
    #: The detail below is data, not messages: the handler reads the code here.
    problem_code = "documents_changed"

    def __init__(self, shown: dict[str, Any]) -> None:
        super().__init__()
        # Set after: DRF turns every leaf of a detail into text.
        body: Any = {"message": self.default_detail, **shown}
        self.detail = body


class BookingLanguageUnavailable(APIException):
    """The company's booking terms have no text in the booking's language, so
    nobody books online in it: the answer names the languages that have one."""

    status_code = 409
    default_code = "booking_language_unavailable"
    default_detail = (
        "W tym języku nie można zarezerwować online: regulamin rezerwacji nie ma w nim wersji."
    )
    #: The detail below is data, not messages: the handler reads the code here.
    problem_code = "booking_language_unavailable"

    def __init__(self, locale: str, locales: tuple[str, ...]) -> None:
        super().__init__()
        body: Any = {"message": self.default_detail, "locale": locale, "locales": list(locales)}
        self.detail = body


def _organization() -> Organization:
    return Organization.objects.get(pk=require_tenant_context().organization_id)


def _locale(asked: str | None, organization: Organization) -> str:
    return clamp_content_locale((asked or "").strip().lower() or None, organization=organization)


def booking_locale(asked: str | None) -> str:
    """The language a booking is made in: the visitor's when the company has
    it, otherwise the company's first — what `match_or_create` gives a new
    customer."""
    return _locale(asked, _organization())


@dataclass(frozen=True, slots=True)
class _Languages:
    """Where a customer can book online: `bookable` — in the booking's own
    language; `offered` — the company's languages they can, in its order."""

    bookable: bool
    offered: tuple[str, ...]


def _languages(locale: str, organization: Organization) -> _Languages:
    """Every language until booking terms are in force, then those the terms
    have a text in. The booking's language is asked about by itself: it is the
    company's first where the deployment serves none of the company's own."""
    locales = organization_content_locales(organization)
    written = document_locales(DocumentKind.BOOKING_TERMS)
    if written is None:
        return _Languages(True, locales)
    return _Languages(locale in written, tuple(code for code in locales if code in written))


def _marketing(locale: str, organization: Organization) -> str:
    """The marketing consent the form shows in this language; empty when the
    company switched it off or the language has no wording."""
    if not setting(MARKETING_CONSENT):
        return ""
    return marketing_wording(locale, organization.name)


def _in_force(locale: str) -> list[DocumentInForce]:
    found = (current_document(kind, locale) for kind in DOCUMENT_STATEMENTS)
    return [document for document in found if document is not None]


def _payload(documents: list[DocumentInForce], locale: str) -> dict[str, Any]:
    return {
        "locale": locale,
        "documents": [
            {
                "kind": document.kind,
                "statement": DOCUMENT_STATEMENTS[document.kind].get(
                    locale, DOCUMENT_STATEMENTS[document.kind]["en"]
                ),
                "text_id": str(document.text_id),
                "version": document.version,
                "effective_from": document.effective_from.isoformat(),
                "url": document.url,
            }
            for document in documents
        ],
    }


def shown(asked: str | None) -> dict[str, Any]:
    """What a booking form shows before the customer books: each document in
    force in the booking's language with the statement to tick, and where to
    read it — none when the company has published none in that language;
    whether the language can be booked in at all, with the languages that can;
    and the marketing consent to offer, if any."""
    organization = _organization()
    locale = _locale(asked, organization)
    languages = _languages(locale, organization)
    statement = _marketing(locale, organization)
    return {
        **_payload(_in_force(locale), locale),
        "bookable": languages.bookable,
        "bookable_locales": list(languages.offered),
        "marketing": {"statement": statement} if statement else None,
    }


def record(
    consents: BookingConsents | None,
    *,
    customer: Customer,
    reference: UUID,
    asked: str | None,
) -> None:
    """Appends what the customer agreed to, inside the booking's transaction.

    A customer who books for themselves (the public form's context) books
    only in a language the booking terms have a text in (409
    `booking_language_unavailable` with the languages that have one) and must
    have accepted every document in force in the booking's language: one
    missing or another text than the one in force is 409 `documents_changed`
    with the documents to show. Either way the booking is rolled back.
    Whoever books for a customer — the team in the panel, a product — passes
    `consents` only when it showed the documents itself; without it nothing
    is asked and nothing is written.

    A ticked marketing consent is a line of its own, in the wording the form
    showed — for a customer who left an e-mail, where the company asks for it.
    """
    public = require_tenant_context().role_key == PUBLIC_BOOKING_ROLE
    if consents is None:
        if not public:
            return
        consents = BookingConsents()
    organization = _organization()
    locale = _locale(asked, organization)
    languages = _languages(locale, organization)
    if not languages.bookable:
        raise BookingLanguageUnavailable(locale, languages.offered)
    documents = _in_force(locale)
    if any(document.text_id not in consents.documents for document in documents):
        raise DocumentsChanged(_payload(documents, locale))
    for document in documents:
        record_consent(
            customer=customer,
            text_id=document.text_id,
            source=SOURCE,
            source_reference=str(reference),
        )
    statement = _marketing(locale, organization) if consents.marketing else ""
    if statement and customer.email:
        record_consent(
            customer=customer,
            kind=ConsentKind.MARKETING,
            wording=statement,
            locale=locale,
            source=SOURCE,
            source_reference=str(reference),
        )
