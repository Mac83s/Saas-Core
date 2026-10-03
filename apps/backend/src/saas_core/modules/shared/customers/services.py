"""Finding a company's customer by their contact, and taking the person out
of the record (ADR-073 §2). Who may do either is the caller's question: a
booking, an order and the retention run each answer it for themselves."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping

from django.utils import timezone
from rest_framework.exceptions import ValidationError

from saas_core.modules.core.organizations.locales import clamp_content_locale
from saas_core.modules.core.organizations.models import Organization

from .models import Customer

type CustomerAnonymizer = Callable[[Customer], None]

_anonymizers: dict[str, CustomerAnonymizer] = {}


def register_customer_anonymizer(name: str, anonymizer: CustomerAnonymizer) -> None:
    """From a module's `AppConfig.ready`: what it stores about a customer
    beside the customer's own row — a visit's notes, an order's buyer snapshot,
    a delivery address. `strip_customer` calls it in its own transaction, with
    the customer's row locked and the company's tenant set."""
    _anonymizers[name] = anonymizer


def match_or_create(
    organization: Organization, customer_data: Mapping[str, str]
) -> tuple[Customer, str]:
    """The end customer by their contact, made on their first booking or
    order; and the e-mail a confirmation goes to."""
    email = customer_data.get("email", "").strip().lower()
    phone = customer_data.get("phone", "").strip()
    if not email and not phone:
        raise ValidationError("Wymagany jest e-mail albo telefon.")
    contact_hash = hashlib.sha256(f"{email}|{phone}".encode()).hexdigest()
    # Locked, and asked for again under the lock: a retention run (or a hand
    # anonymisation) that takes this customer in another transaction makes the
    # caller wait, and the row then no longer matches — the booking gets a
    # new customer instead of attaching a visit to a stripped one. NO KEY, so
    # rows that only point at the customer do not queue behind it.
    customer = (
        Customer.all_objects.select_for_update(no_key=True)
        .filter(organization=organization, contact_hash=contact_hash, anonymized_at__isnull=True)
        .first()
    )
    if customer is None:
        customer = Customer.all_objects.create(
            organization=organization,
            display_name=customer_data["display_name"].strip(),
            email=email,
            phone=phone,
            contact_hash=contact_hash,
            locale=clamp_content_locale(
                str(customer_data.get("locale") or "").strip().lower() or None,
                organization=organization,
            ),
        )
    return customer, email


def strip_customer(customer: Customer) -> None:
    """Takes the person out of a customer's record, in every copy the system
    stores (docs/architecture/privacy-retention.md) — by hand from the panel
    or by the company's retention setting. The caller holds the row's lock and
    the company's tenant. What the customer did stays, without the person."""
    now = timezone.now()
    customer.display_name = "Zanonimizowany klient"
    customer.email = ""
    customer.phone = ""
    customer.contact_hash = hashlib.sha256(f"anon:{customer.id}".encode()).hexdigest()
    customer.anonymized_at = now
    customer.updated_at = now
    # The company is named in the statement itself, not left to RLS alone.
    Customer.all_objects.filter(organization_id=customer.organization_id, pk=customer.pk).update(
        display_name=customer.display_name,
        email=customer.email,
        phone=customer.phone,
        contact_hash=customer.contact_hash,
        anonymized_at=now,
        updated_at=now,
    )
    for name in sorted(_anonymizers):
        _anonymizers[name](customer)
