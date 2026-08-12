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
