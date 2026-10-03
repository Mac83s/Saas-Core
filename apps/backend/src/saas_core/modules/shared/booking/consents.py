"""What a customer agrees to while booking (ADR-073 §9, phase 4c).

The company's booking terms and privacy policy are documents of
`shared.customers`. A customer who books for themselves is shown the ones in
force in their language and names the text rows they accepted; the booking
appends a line of the consent journal for each, in its own transaction, so a
booking and what was agreed to exist together or not at all. A marketing
consent is a line of its own, never part of accepting a document.

The language is the booking's: the visitor's when the company has it, else
the company's first (ADR-071 pkt 21). A document without a text in that
language is not shown and not required — the reader never substitutes another
language, and the company was told so when it approved the version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from rest_framework.exceptions import APIException

from saas_core.modules.core.organizations.context import require_tenant_context
from saas_core.modules.core.organizations.locales import clamp_content_locale
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.customers.api import (
    ConsentKind,
    Customer,
    DocumentInForce,
    DocumentKind,
    current_document,
    record_consent,
)

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
    got them from `shown`; `marketing` — the wording of a marketing consent
    they gave, empty when none was asked for or given.
    """

    documents: tuple[UUID, ...] = ()
    marketing: str = ""


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


def booking_locale(asked: str | None) -> str:
    """The language a booking is made in: the visitor's when the company has
    it, otherwise the company's first — what `match_or_create` gives a new
    customer."""
    organization = Organization.objects.get(pk=require_tenant_context().organization_id)
    return clamp_content_locale((asked or "").strip().lower() or None, organization=organization)


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
    read it. Empty when the company has published none in that language."""
    locale = booking_locale(asked)
    return _payload(_in_force(locale), locale)


def record(
    consents: BookingConsents | None,
    *,
    customer: Customer,
    reference: UUID,
    asked: str | None,
) -> None:
    """Appends what the customer agreed to, inside the booking's transaction.

    A customer who books for themselves (the public form's context) must have
    accepted every document in force in the booking's language: one missing
    or another text than the one in force is 409 `documents_changed` with the
    documents to show, and the booking is rolled back. Whoever books for a
    customer — the team in the panel, a product — passes `consents` only when
    it showed the documents itself; without it nothing is asked and nothing
    is written.
    """
    public = require_tenant_context().role_key == PUBLIC_BOOKING_ROLE
    if consents is None:
        if not public:
            return
        consents = BookingConsents()
    locale = booking_locale(asked)
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
    if consents.marketing:
        record_consent(
            customer=customer,
            kind=ConsentKind.MARKETING,
            wording=consents.marketing,
            locale=locale,
            source=SOURCE,
            source_reference=str(reference),
        )
