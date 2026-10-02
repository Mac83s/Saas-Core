"""Content languages: one check for every module (ADR-071 pkt 3).

A content language is what a company's customers read — pages, entries, the
profile, bookings, e-mails to customers. It is a two-letter code from the
locale registry (`settings.LOCALE_REGISTRY`), stored as a plain string with a
format check rather than a choice list, because which languages a company may
use depends on the company: its `public_locales`, within the profile's
`supportedLocales`. The panel's own pl/en (`LocaleEnum`) is a different axis.

Three field codes, the same everywhere: `locale_not_in_registry` (no such
language on this platform), `locale_not_enabled` (the company does not offer it)
and — in sites — `locale_not_seeded` (no template seeds to start a site in it).
"""

from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from django.core.validators import RegexValidator
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail, ValidationError

from .models import Organization

LOCALE_NOT_IN_REGISTRY = "locale_not_in_registry"
LOCALE_NOT_ENABLED = "locale_not_enabled"
LOCALE_NOT_SEEDED = "locale_not_seeded"
CONTENT_LOCALE_PATTERN = r"^[a-z]{2}$"


def organization_content_locales(organization: Organization) -> tuple[str, ...]:
    """The company's languages this deployment serves, in the company's order."""
    supported = set(settings.SITES_SUPPORTED_LOCALES)
    return tuple(code for code in organization.public_locales if code in supported)


def content_locale_problem(code: str, *, organization: Organization) -> str | None:
    """The field code that refuses `code` for this company, or None."""
    if code not in settings.LOCALE_REGISTRY:
        return LOCALE_NOT_IN_REGISTRY
    if code not in organization_content_locales(organization):
        return LOCALE_NOT_ENABLED
    return None


def assert_content_locale(code: str, *, organization: Organization, field: str = "locale") -> str:
    """`code` when the company offers it; otherwise a 400 naming the field and why."""
    problem = content_locale_problem(code, organization=organization)
    if problem == LOCALE_NOT_IN_REGISTRY:
        raise ValidationError({
            field: [ErrorDetail("Tego języka nie ma na platformie.", code=problem)]
        })
    if problem == LOCALE_NOT_ENABLED:
        raise ValidationError({
            field: [ErrorDetail("Firma nie ma włączonego tego języka.", code=problem)]
        })
    return code


def assert_organization_content_locale(
    code: str, *, organization_id: Any, field: str = "locale"
) -> str:
    """`assert_content_locale` for the organization of the current request."""
    organization = Organization.objects.only("id", "public_locales").get(pk=organization_id)
    return assert_content_locale(code, organization=organization, field=field)


def include_site_source_locale(*, organization_id: Any, code: str, first: bool) -> None:
    """A site's source language is always one of the company's (ADR-071 pkt 6).

    Starting a site in a language of the profile that the company has not
    listed yet adds it — at the front when it is the company's first site, so
    the language the company chose to speak becomes its customers' language,
    at the end otherwise. Plan TL10 moves this into the one service that
    changes the company's languages, with history and the plan's limit.
    """
    organization = Organization.objects.select_for_update().get(pk=organization_id)
    if code in organization.public_locales:
        return
    if code not in settings.SITES_SUPPORTED_LOCALES:
        assert_content_locale(code, organization=organization, field="default_locale")
    locales = list(organization.public_locales)
    organization.public_locales = [code, *locales] if first else [*locales, code]
    organization.save(update_fields=["public_locales", "updated_at"])


def clamp_content_locale(code: str | None, *, organization: Organization) -> str:
    """The language to use for a visitor's choice: theirs when the company has
    it, otherwise the company's first — a booking is never refused over a
    language (ADR-071 pkt 21)."""
    offered = organization_content_locales(organization)
    if code in offered:
        return str(code)
    return offered[0] if offered else str(settings.SITES_DEFAULT_LOCALE)


class ContentLocaleField(serializers.CharField):
    """A content language: two lowercase letters known to the locale registry.

    Whether the company offers it is the service's question — it needs the
    organization, which a serializer field does not have.
    """

    default_error_messages = {
        "invalid": "Kod języka to dwie małe litery ISO 639-1, np. de.",
        LOCALE_NOT_IN_REGISTRY: "Tego języka nie ma na platformie.",
    }

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("max_length", 2)
        kwargs.setdefault("min_length", 2)
        kwargs.setdefault(
            "help_text",
            "Język treści: dwuliterowy kod z rejestru języków platformy, włączony dla firmy.",
        )
        super().__init__(**kwargs)
        self.validators.append(RegexValidator(CONTENT_LOCALE_PATTERN, code="invalid"))

    def to_internal_value(self, data: Any) -> str:
        value = super().to_internal_value(data)
        if re.fullmatch(CONTENT_LOCALE_PATTERN, value) is None:
            self.fail("invalid")
        if value not in settings.LOCALE_REGISTRY:
            self.fail(LOCALE_NOT_IN_REGISTRY)
        return value
