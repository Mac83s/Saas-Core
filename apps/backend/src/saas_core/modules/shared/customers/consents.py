"""Marketing consents in the panel (ADR-073 §9; the owner's answers of
04.10): who agreed to receive the company's offers, and a withdrawal.

A consent to receive offers and promotions is a line of the consent journal
with `kind="marketing"`, written by the form that showed the sentence
(`documents.marketing_wording`, over `MARKETING_WORDING`) — never part of
accepting a document. The journal keeps the hash of what the person saw, not
the words, so the list reads a line's words back by rendering that sentence
for the company and comparing hashes. A line whose hash matches none — the
company was renamed since, or the sentence was changed — is still listed as
agreed to, with its date and form, and says that its exact words are no longer
known.

Nothing is ever changed in the journal: a withdrawal is the next line with
`granted=False`, and the customer's latest line says where they stand.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import OuterRef, QuerySet, Subquery
from rest_framework.exceptions import APIException, NotFound

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.models import Organization

from .documents import (
    CUSTOMERS_MANAGE,
    CUSTOMERS_READ,
    MARKETING_WORDING,
    marketing_wording,
    record_consent,
    text_hash,
)
from .models import ConsentKind, ConsentRecord, Customer

#: The journal's `source` of a withdrawal somebody of the company wrote down;
#: its reference is the journal line it withdraws.
PANEL_SOURCE = "customers.panel"

STATES = ("granted", "withdrawn")
MAX_PAGE_SIZE = 100


class ConsentChanged(APIException):
    """The consent the caller saw is not the customer's latest any more: they
    agreed again, or somebody already wrote the withdrawal down."""

    status_code = 409
    default_detail = "Zgoda tego klienta zmieniła się w międzyczasie. Odśwież listę."
    default_code = "consent_changed"


def _wording(line: ConsentRecord, company: str) -> str:
    """The words a journal line's hash stands for, or nothing when no
    sentence known today gives that hash."""
    for locale in dict.fromkeys([line.locale, *MARKETING_WORDING]):
        sentence = marketing_wording(locale, company)
        if sentence and text_hash(sentence) == line.text_hash:
            return sentence
    return ""


def _lines(organization_id: UUID) -> QuerySet[ConsentRecord]:
    return ConsentRecord.all_objects.filter(
        organization_id=organization_id, kind=ConsentKind.MARKETING, customer__isnull=False
    )


def _row(customer: Customer, lines: list[ConsentRecord], company: str) -> dict[str, Any]:
    """Where one customer stands: their latest line decides, and the consent
    shown is the latest one they gave."""
    latest = lines[-1]
    given = next(line for line in reversed(lines) if line.granted)
    return {
        "customer_id": customer.id,
        "name": customer.display_name,
        "email": customer.email,
        "phone": customer.phone,
        "granted": latest.granted,
        "consent_id": given.id,
        "consented_at": given.created_at,
        "source": given.source,
        "source_reference": given.source_reference,
        "locale": given.locale,
        "wording": _wording(given, company),
        "withdrawn_at": None if latest.granted else latest.created_at,
    }


def list_marketing_consents(
    *, state: str = "granted", page: int = 1, page_size: int = 25
) -> dict[str, Any]:
    """Who agreed to receive the company's offers and promotions, newest
    first: `granted` — whose consent stands, `withdrawn` — who took it back.
    Read from the consent journal: when, on which form (`source` and that
    record's id), in which language and to which words. A customer whose data
    was removed is not listed — nobody is left to write to; their journal
    lines stay."""
    context = authorize(CUSTOMERS_READ)
    organization = Organization.objects.get(pk=context.organization_id)
    latest = (
        _lines(organization.id).filter(customer_id=OuterRef("pk")).order_by("-created_at", "-id")
    )
    customers = (
        Customer.all_objects.filter(organization_id=organization.id, anonymized_at__isnull=True)
        .annotate(
            consent_granted=Subquery(latest.values("granted")[:1]),
            consent_at=Subquery(latest.values("created_at")[:1]),
        )
        # A customer with no marketing line has no answer here at all.
        .filter(consent_granted=(state == "granted"))
        .order_by("-consent_at", "id")
    )
    start = (page - 1) * page_size
    found = list(customers[start : start + page_size])
    journal: dict[UUID, list[ConsentRecord]] = {}
    for line in (
        _lines(organization.id)
        .filter(customer_id__in=[c.id for c in found])
        .order_by("created_at", "id")
    ):
        if line.customer_id is not None:
            journal.setdefault(line.customer_id, []).append(line)
    return {
        "total": customers.count(),
        "page": page,
        "page_size": page_size,
        "items": [
            _row(customer, journal[customer.id], organization.name)
            for customer in found
            # A withdrawal with no consent before it names nothing to show.
            if any(line.granted for line in journal[customer.id])
        ],
    }


def withdraw_marketing_consent(customer_id: UUID, *, consent_id: UUID) -> dict[str, Any]:
    """The customer told the company they no longer want its offers: the next
    line of the journal, `granted=False`, written by a person of the company.
    `consent_id` is the consent the caller saw (`consent_id` of the list): when
    it is not the customer's latest line any more — they agreed again, or the
    withdrawal is already written — the answer is 409 `consent_changed` and
    nothing is written, so a repeat never writes two lines. The customer may
    agree again on a form; that is a new line."""
    context = authorize(CUSTOMERS_MANAGE)
    with transaction.atomic():
        # Locked: two people withdrawing at once write one line, not two.
        customer = (
            Customer.all_objects.select_for_update(no_key=True)
            .filter(
                organization_id=context.organization_id, pk=customer_id, anonymized_at__isnull=True
            )
            .first()
        )
        if customer is None:
            raise NotFound("Nie ma takiego klienta.")
        lines = list(
            _lines(context.organization_id)
            .filter(customer_id=customer.id)
            .order_by("created_at", "id")
        )
        if not lines or lines[-1].id != consent_id or not lines[-1].granted:
            raise ConsentChanged
        given = lines[-1]
        organization = Organization.objects.get(pk=context.organization_id)
        lines.append(
            record_consent(
                customer=customer,
                kind=ConsentKind.MARKETING,
                locale=given.locale,
                granted=False,
                source=PANEL_SOURCE,
                source_reference=str(given.id),
            )
        )
        # Who wrote it down is in the history; never the customer's name.
        record_audit(
            organization=organization,
            action="customers.consent.withdrawn",
            actor=User.objects.filter(pk=context.actor_id).first(),
            target_type="customer",
            target_id=customer.id,
            metadata={"kind": ConsentKind.MARKETING.value, "consent_id": str(given.id)},
        )
        return _row(customer, lines, organization.name)
