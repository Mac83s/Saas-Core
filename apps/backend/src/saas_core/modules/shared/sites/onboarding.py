from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db import transaction
from rest_framework.exceptions import APIException, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .domain_services import (
    DomainHostnameConflict,
    DomainQuarantined,
    SubdomainAvailability,
    normalize_platform_label,
    subdomain_availability,
)
from .models import (
    Site,
    SiteOnboardingDraft,
    SiteOnboardingMutation,
    SiteOnboardingStep,
    canonical_json_hash,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED
from .services import MutationResult, SitesIdempotencyConflict, create_site

ONBOARDING_SAVED = "sites.onboarding.saved"


class SiteOnboardingVersionConflict(APIException):
    status_code = 409
    default_detail = "Postęp konfiguracji został zmieniony w innej sesji."
    default_code = "site_onboarding_version_conflict"


class SiteOnboardingIncomplete(APIException):
    status_code = 409
    default_detail = "Uzupełnij adres i podstawowe dane przed utworzeniem witryny."
    default_code = "site_onboarding_incomplete"


class SiteOnboardingCompleted(APIException):
    status_code = 409
    default_detail = "Konfiguracja pierwszej witryny jest już zakończona."
    default_code = "site_onboarding_completed"


@dataclass(frozen=True, slots=True)
class SiteOnboardingState:
    id: UUID | None
    version: int
    step: str
    name: str
    subdomain_label: str
    default_locale: str
    platform_domain: str
    hostname: str
    site_id: UUID | None
    updated_at: datetime | None


def get_site_onboarding() -> SiteOnboardingState:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    draft = SiteOnboardingDraft.all_objects.filter(
        organization_id=context.organization_id
    ).first()
    return _state(draft)


@transaction.atomic
def save_site_onboarding(
    *,
    version: int,
    step: str,
    name: str,
    subdomain_label: str,
    default_locale: str,
    idempotency_key: str,
) -> SiteOnboardingState:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    normalized_name = name.strip()
    normalized_label = (
        normalize_platform_label(subdomain_label) if subdomain_label.strip() else ""
    )
    if default_locale not in settings.SITES_SUPPORTED_LOCALES:
        raise ValidationError({"default_locale": ["Nieobsługiwany język witryny."]})
    _validate_step(
        step=step,
        name=normalized_name,
        subdomain_label=normalized_label,
    )
    availability: SubdomainAvailability | None = None
    if normalized_label:
        availability = subdomain_availability(normalized_label)
        if not availability.available:
            if availability.reason == "quarantined":
                raise DomainQuarantined
            if availability.reason == "taken":
                raise DomainHostnameConflict
            raise ValidationError({"subdomain_label": ["Ta nazwa nie może zostać użyta."]})
    request_hash = canonical_json_hash({
        "version": version,
        "step": step,
        "name": normalized_name,
        "subdomain_label": normalized_label,
        "default_locale": default_locale,
    })
    organization = Organization.objects.select_for_update().get(
        pk=context.organization_id
    )
    existing_mutation = SiteOnboardingMutation.all_objects.filter(
        organization=organization,
        actor_id=context.actor_id,
        idempotency_key=normalized_key,
    ).select_related("draft").first()
    if existing_mutation is not None:
        if existing_mutation.request_hash != request_hash:
            raise SitesIdempotencyConflict
        return _state(existing_mutation.draft)
    actor = User.objects.get(pk=context.actor_id)
    draft, _ = SiteOnboardingDraft.all_objects.select_for_update().get_or_create(
        organization=organization,
        defaults={
            "created_by": actor,
            "updated_by": actor,
            "default_locale": settings.SITES_DEFAULT_LOCALE,
        },
    )
    if draft.step == SiteOnboardingStep.COMPLETED:
        raise SiteOnboardingCompleted
    if draft.version != version:
        raise SiteOnboardingVersionConflict
    draft.step = step
    draft.name = normalized_name
    draft.subdomain_label = normalized_label
    draft.default_locale = default_locale
    draft.version += 1
    draft.updated_by = actor
    draft.save(
        update_fields=[
            "step",
            "name",
            "subdomain_label",
            "default_locale",
            "version",
            "updated_by",
            "updated_at",
        ]
    )
    SiteOnboardingMutation.all_objects.create(
        organization=organization,
        draft=draft,
        actor=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
        resulting_version=draft.version,
    )
    record_audit(
        organization=organization,
        action=ONBOARDING_SAVED,
        actor=actor,
        target_type="site_onboarding",
        target_id=draft.id,
        metadata={"step": step, "version": draft.version},
    )
    return _state(draft)


@transaction.atomic
def complete_site_onboarding(*, idempotency_key: str) -> MutationResult[Site]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    try:
        draft = SiteOnboardingDraft.all_objects.select_for_update().get(
            organization_id=context.organization_id
        )
    except SiteOnboardingDraft.DoesNotExist as error:
        raise SiteOnboardingIncomplete from error
    if draft.site_id is not None:
        site = draft.site
        assert site is not None
        return MutationResult(site, False)
    if (
        draft.step != SiteOnboardingStep.REVIEW
        or not draft.name
        or not draft.subdomain_label
    ):
        raise SiteOnboardingIncomplete
    result = create_site(
        name=draft.name,
        slug=draft.subdomain_label,
        default_locale=draft.default_locale,
        subdomain_label=draft.subdomain_label,
        idempotency_key=f"onboarding:{normalized_key}",
    )
    draft.site = result.value
    draft.step = SiteOnboardingStep.COMPLETED
    draft.version += 1
    draft.save(update_fields=["site", "step", "version", "updated_at"])
    return result


def _state(draft: SiteOnboardingDraft | None) -> SiteOnboardingState:
    label = draft.subdomain_label if draft is not None else ""
    return SiteOnboardingState(
        id=draft.id if draft is not None else None,
        version=draft.version if draft is not None else 0,
        step=draft.step if draft is not None else SiteOnboardingStep.ADDRESS,
        name=draft.name if draft is not None else "",
        subdomain_label=label,
        default_locale=(
            draft.default_locale if draft is not None else settings.SITES_DEFAULT_LOCALE
        ),
        platform_domain=settings.SITES_PLATFORM_DOMAIN,
        hostname=(f"{label}.{settings.SITES_PLATFORM_DOMAIN}" if label else ""),
        site_id=draft.site_id if draft is not None else None,
        updated_at=draft.updated_at if draft is not None else None,
    )


def _validate_step(*, step: str, name: str, subdomain_label: str) -> None:
    if step not in {
        SiteOnboardingStep.ADDRESS,
        SiteOnboardingStep.DETAILS,
        SiteOnboardingStep.REVIEW,
    }:
        raise ValidationError({"step": ["Nieobsługiwany krok konfiguracji."]})
    if not subdomain_label:
        raise ValidationError({"subdomain_label": ["Wybierz adres witryny."]})
    if step == SiteOnboardingStep.REVIEW and len(name) < 2:
        raise ValidationError({"name": ["Wpisz nazwę widoczną dla klientów."]})


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 100:
        raise ValidationError({"Idempotency-Key": ["Wymagany klucz do 100 znaków."]})
    return normalized
