from __future__ import annotations

from dataclasses import dataclass
from html import escape
from string import Formatter
from typing import Any


@dataclass(frozen=True, slots=True)
class EmailTemplate:
    key: str
    version: int
    category: str
    subjects: dict[str, str]
    bodies: dict[str, str]
    allowed_context: frozenset[str]


TEMPLATES: dict[tuple[str, int], EmailTemplate] = {
    ("booking.confirmation", 1): EmailTemplate(
        key="booking.confirmation",
        version=1,
        category="required",
        subjects={"pl": "Potwierdzenie rezerwacji", "en": "Booking confirmation"},
        bodies={
            "pl": (
                "<p>Rezerwacja w {organization_name} została potwierdzona.</p>"
                "<p>Termin: {starts_at}</p>"
            ),
            "en": (
                "<p>Your booking at {organization_name} is confirmed.</p><p>Time: {starts_at}</p>"
            ),
        },
        allowed_context=frozenset({"organization_name", "starts_at"}),
    ),
    ("booking.reminder", 1): EmailTemplate(
        key="booking.reminder",
        version=1,
        category="required",
        subjects={"pl": "Przypomnienie o rezerwacji", "en": "Booking reminder"},
        bodies={
            "pl": (
                "<p>Przypominamy o rezerwacji w {organization_name}.</p><p>Termin: {starts_at}</p>"
            ),
            "en": (
                "<p>This is a reminder about your booking at {organization_name}.</p>"
                "<p>Time: {starts_at}</p>"
            ),
        },
        allowed_context=frozenset({"organization_name", "starts_at"}),
    ),
    ("system.activity", 1): EmailTemplate(
        key="system.activity",
        version=1,
        category="required",
        subjects={"pl": "Ważna informacja o koncie", "en": "Important account information"},
        bodies={
            "pl": "<p>Witaj {display_name},</p><p>{message}</p>",
            "en": "<p>Hello {display_name},</p><p>{message}</p>",
        },
        allowed_context=frozenset({"display_name", "message"}),
    ),
    ("billing.trial_ending", 1): EmailTemplate(
        key="billing.trial_ending",
        version=1,
        category="required",
        subjects={
            "pl": "Okres próbny dobiega końca",
            "en": "Your trial is ending",
        },
        bodies={
            "pl": (
                "<p>Okres próbny planu {plan_name} w {organization_name} kończy się "
                "{ends_at}.</p><p>Po tej dacie pobierzemy pierwszą opłatę. Jeśli nie "
                "chcesz kontynuować, zrezygnuj przed tym terminem.</p>"
            ),
            "en": (
                "<p>The trial of the {plan_name} plan at {organization_name} ends "
                "{ends_at}.</p><p>We will take the first payment after that date. "
                "Cancel before then if you do not want to continue.</p>"
            ),
        },
        allowed_context=frozenset({"organization_name", "plan_name", "ends_at"}),
    ),
    ("billing.grace_ending", 1): EmailTemplate(
        key="billing.grace_ending",
        version=1,
        category="required",
        subjects={
            "pl": "Płatność nie przeszła — dostęp wygasa",
            "en": "Payment failed — access is ending",
        },
        bodies={
            "pl": (
                "<p>Nie udało się pobrać opłaty za plan {plan_name} w "
                "{organization_name}.</p><p>Do {ends_at} nic się nie zmienia. Po tej "
                "dacie konto przejdzie w tryb tylko do odczytu — dane zostają, edycja "
                "zostaje wstrzymana.</p>"
            ),
            "en": (
                "<p>We could not charge for the {plan_name} plan at "
                "{organization_name}.</p><p>Nothing changes until {ends_at}. After "
                "that the account becomes read-only — the data stays, editing "
                "stops.</p>"
            ),
        },
        allowed_context=frozenset({"organization_name", "plan_name", "ends_at"}),
    ),
    ("product.update", 1): EmailTemplate(
        key="product.update",
        version=1,
        category="marketing",
        subjects={"pl": "Nowości w usłudze", "en": "Product updates"},
        bodies={
            "pl": "<p>Witaj {display_name},</p><p>{message}</p>",
            "en": "<p>Hello {display_name},</p><p>{message}</p>",
        },
        allowed_context=frozenset({"display_name", "message"}),
    ),
}


def register_email_template(template: EmailTemplate) -> None:
    """A product's own template, registered from its `AppConfig.ready`.

    A published (key, version) never changes: registering a different template
    under the same pair is an error, registering the same one again is not.
    """
    existing = TEMPLATES.get((template.key, template.version))
    if existing is not None and existing != template:
        raise ValueError(f"Szablon {template.key} v{template.version} już istnieje.")
    TEMPLATES[(template.key, template.version)] = template


def render_template(
    *, key: str, version: int, locale: str, context: dict[str, Any]
) -> tuple[str, str]:
    template = TEMPLATES.get((key, version))
    if template is None or locale not in template.subjects:
        raise ValueError("Nieznany szablon, wersja albo locale.")
    fields = {
        field_name
        for _, field_name, _, _ in Formatter().parse(template.bodies[locale])
        if field_name
    }
    if fields != set(context) or not fields <= template.allowed_context:
        raise ValueError("Kontekst nie odpowiada kontraktowi szablonu.")
    safe_context = {key: escape(str(value)) for key, value in context.items()}
    return template.subjects[locale], template.bodies[locale].format_map(safe_context)


def template_catalog() -> list[dict[str, object]]:
    return [
        {
            "key": template.key,
            "version": template.version,
            "category": template.category,
            "locales": sorted(template.subjects),
            "context_fields": sorted(template.allowed_context),
        }
        for template in TEMPLATES.values()
    ]
