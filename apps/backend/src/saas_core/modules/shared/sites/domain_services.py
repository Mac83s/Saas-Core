from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.shared.billing.api import FeatureOperation, authorize_entitled

from .domains import InvalidHostname, normalize_hostname, verification_record_name
from .models import (
    Domain,
    DomainKind,
    DomainMutation,
    DomainStatus,
    DomainTlsStatus,
    Site,
    canonical_json_hash,
)
from .permissions import CUSTOM_DOMAIN_ENABLED, SITE_PUBLISH, SITES_ENABLED

DOMAIN_CREATED = "sites.domain.created"
DOMAIN_DISABLED = "sites.domain.disabled"
DOMAIN_ENABLED = "sites.domain.enabled"
DOMAIN_RELEASED = "sites.domain.released"
DOMAIN_CANONICAL_CHANGED = "sites.domain.canonical_changed"
DOMAIN_VERIFICATION_REQUESTED = "sites.domain.verification_requested"


class SitesIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji wskazuje inne żądanie."
    default_code = "sites_idempotency_conflict"


class SiteNotFound(NotFound):
    default_detail = "Strona nie istnieje."
    default_code = "site_not_found"


@dataclass(frozen=True, slots=True)
class MutationResult[T]:
    value: T
    created: bool


class DomainHostnameConflict(APIException):
    status_code = 409
    default_detail = "Hostname jest już przypisany albo zarezerwowany."
    default_code = "domain_hostname_conflict"


class DomainQuarantined(APIException):
    status_code = 409
    default_detail = "Domena pozostaje w okresie kwarantanny po zwolnieniu."
    default_code = "domain_quarantined"


class DomainNotFound(NotFound):
    default_detail = "Domena nie istnieje."
    default_code = "domain_not_found"


class DomainLifecycleConflict(APIException):
    status_code = 409
    default_detail = "Operacja nie jest dozwolona w bieżącym stanie domeny."
    default_code = "domain_lifecycle_conflict"


def platform_hostname(site: Site) -> str:
    readable_slug = site.slug[:50].rstrip("-")
    label = f"{readable_slug}-{site.id.hex[:12]}"
    return normalize_hostname(f"{label}.{settings.SITES_PLATFORM_DOMAIN}")


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise ValidationError({"Idempotency-Key": ["Wymagany klucz do 120 znaków."]})
    return normalized


def create_platform_domain(
    *,
    site: Site,
    actor: User,
    idempotency_key: str,
) -> Domain:
    hostname = platform_hostname(site)
    now = timezone.now()
    domain_id = uuid.uuid7()
    try:
        return Domain.all_objects.create(
            id=domain_id,
            organization_id=site.organization_id,
            site=site,
            hostname=hostname,
            kind=DomainKind.PLATFORM,
            status=DomainStatus.VERIFIED,
            verification_name="",
            verification_token="",
            tls_status=DomainTlsStatus.ELIGIBLE,
            is_canonical=True,
            last_checked_at=now,
            last_verified_at=now,
            next_check_at=None,
            created_by=actor,
            idempotency_key=f"platform:{_idempotency_key(idempotency_key)}",
            request_hash=canonical_json_hash({"site_id": str(site.id), "hostname": hostname}),
        )
    except IntegrityError as error:
        raise DomainHostnameConflict from error


def list_domains(*, site_id: UUID) -> list[Domain]:
    context = authorize_entitled(
        SITE_PUBLISH,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    if not Site.all_objects.filter(
        pk=site_id,
        organization_id=context.organization_id,
    ).exists():
        raise SiteNotFound
    return list(
        Domain.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site_id,
        ).order_by("created_at", "id")
    )


@transaction.atomic
def create_custom_domain(
    *,
    site_id: UUID,
    hostname: str,
    idempotency_key: str,
) -> MutationResult[Domain]:
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    authorize_entitled(SITE_PUBLISH, CUSTOM_DOMAIN_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    normalized_hostname = _validated_custom_hostname(hostname)
    request_hash = canonical_json_hash({
        "site_id": str(site_id),
        "hostname": normalized_hostname,
    })
    existing = Domain.all_objects.filter(
        organization_id=context.organization_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SitesIdempotencyConflict
        return MutationResult(existing, False)
    try:
        site = Site.all_objects.select_for_update().get(
            pk=site_id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    _assert_hostname_available(normalized_hostname)

    actor = User.objects.get(pk=context.actor_id)
    domain_id = uuid.uuid7()
    challenge = (
        f"saas-core-domain-verification={domain_id}.{secrets.token_urlsafe(32)}"
    )
    try:
        domain = Domain.all_objects.create(
            id=domain_id,
            organization_id=context.organization_id,
            site=site,
            hostname=normalized_hostname,
            kind=DomainKind.CUSTOM,
            status=DomainStatus.PENDING,
            verification_name=verification_record_name(normalized_hostname),
            verification_token=challenge,
            tls_status=DomainTlsStatus.PENDING,
            is_canonical=False,
            next_check_at=timezone.now(),
            created_by=actor,
            idempotency_key=normalized_key,
            request_hash=request_hash,
        )
    except IntegrityError as error:
        raise DomainHostnameConflict from error
    record_audit(
        organization=site.organization,
        action=DOMAIN_CREATED,
        actor=actor,
        target_type="site_domain",
        target_id=domain.id,
        metadata={"site_id": str(site.id), "hostname": domain.hostname},
    )
    return MutationResult(domain, True)


@transaction.atomic
def mutate_domain(
    *,
    domain_id: UUID,
    action: Literal["disable", "enable", "release", "set_canonical", "verify"],
    idempotency_key: str,
) -> MutationResult[Domain]:
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    request_hash = canonical_json_hash({"domain_id": str(domain_id), "action": action})
    try:
        domain = (
            Domain.all_objects.select_for_update()
            .select_related("site", "organization")
            .get(pk=domain_id, organization_id=context.organization_id)
        )
    except Domain.DoesNotExist as error:
        raise DomainNotFound from error
    if domain.kind == DomainKind.CUSTOM:
        authorize_entitled(SITE_PUBLISH, CUSTOM_DOMAIN_ENABLED)
    existing = DomainMutation.all_objects.filter(
        organization_id=context.organization_id,
        domain=domain,
        created_by_id=context.actor_id,
        action=action,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        if existing.request_hash != request_hash:
            raise SitesIdempotencyConflict
        return MutationResult(domain, False)

    actor = User.objects.get(pk=context.actor_id)
    audit_action = _apply_action(domain=domain, action=action)
    DomainMutation.all_objects.create(
        organization_id=context.organization_id,
        domain=domain,
        action=action,
        created_by=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=domain.organization,
        action=audit_action,
        actor=actor,
        target_type="site_domain",
        target_id=domain.id,
        metadata={"site_id": str(domain.site_id), "hostname": domain.hostname},
    )
    transaction.on_commit(lambda: _after_domain_mutation(domain.id, action))
    return MutationResult(domain, True)


def _validated_custom_hostname(value: str) -> str:
    try:
        hostname = normalize_hostname(value)
    except InvalidHostname as error:
        raise ValidationError({"hostname": [str(error)]}) from error
    platform_domain = normalize_hostname(settings.SITES_PLATFORM_DOMAIN)
    if hostname == platform_domain or hostname.endswith(f".{platform_domain}"):
        raise ValidationError({"hostname": ["Domena platformy nie może być domeną własną."]})
    return hostname


def _assert_hostname_available(hostname: str) -> None:
    if Domain.all_objects.filter(hostname=hostname).exclude(
        status=DomainStatus.RELEASED
    ).exists():
        raise DomainHostnameConflict
    released = (
        Domain.all_objects.filter(hostname=hostname, status=DomainStatus.RELEASED)
        .order_by("-released_at")
        .first()
    )
    if (
        released is not None
        and released.quarantine_until is not None
        and released.quarantine_until > timezone.now()
    ):
        raise DomainQuarantined


def _apply_action(
    *,
    domain: Domain,
    action: Literal["disable", "enable", "release", "set_canonical", "verify"],
) -> str:
    now = timezone.now()
    if action == "disable":
        if domain.status in {DomainStatus.DISABLED, DomainStatus.RELEASED}:
            raise DomainLifecycleConflict
        was_canonical = domain.is_canonical
        domain.status = DomainStatus.DISABLED
        domain.tls_status = DomainTlsStatus.DISABLED
        domain.is_canonical = False
        domain.save(update_fields=["status", "tls_status", "is_canonical", "updated_at"])
        if was_canonical:
            _ensure_canonical_fallback(domain)
        return DOMAIN_DISABLED
    if action == "enable":
        if domain.status != DomainStatus.DISABLED:
            raise DomainLifecycleConflict
        if domain.kind == DomainKind.PLATFORM:
            domain.status = DomainStatus.VERIFIED
            domain.tls_status = DomainTlsStatus.ELIGIBLE
            domain.next_check_at = None
        else:
            domain.status = DomainStatus.PENDING
            domain.tls_status = DomainTlsStatus.PENDING
            domain.next_check_at = now
        if not Domain.all_objects.filter(site_id=domain.site_id, is_canonical=True).exists():
            domain.is_canonical = True
        domain.dns_error_code = ""
        domain.save(
            update_fields=[
                "status",
                "tls_status",
                "next_check_at",
                "dns_error_code",
                "is_canonical",
                "updated_at",
            ]
        )
        return DOMAIN_ENABLED
    if action == "release":
        if domain.kind != DomainKind.CUSTOM or domain.status == DomainStatus.RELEASED:
            raise DomainLifecycleConflict
        was_canonical = domain.is_canonical
        domain.status = DomainStatus.RELEASED
        domain.tls_status = DomainTlsStatus.DISABLED
        domain.is_canonical = False
        domain.released_at = now
        domain.quarantine_until = now + timedelta(days=settings.DOMAIN_RELEASE_QUARANTINE_DAYS)
        domain.next_check_at = None
        domain.save(
            update_fields=[
                "status",
                "tls_status",
                "is_canonical",
                "released_at",
                "quarantine_until",
                "next_check_at",
                "updated_at",
            ]
        )
        if was_canonical:
            _ensure_canonical_fallback(domain)
        return DOMAIN_RELEASED
    if action == "set_canonical":
        if domain.status != DomainStatus.VERIFIED or domain.is_canonical:
            raise DomainLifecycleConflict
        Domain.all_objects.filter(site_id=domain.site_id, is_canonical=True).update(
            is_canonical=False,
            updated_at=now,
        )
        domain.is_canonical = True
        domain.save(update_fields=["is_canonical", "updated_at"])
        return DOMAIN_CANONICAL_CHANGED
    if action == "verify":
        if domain.kind != DomainKind.CUSTOM or domain.status in {
            DomainStatus.DISABLED,
            DomainStatus.RELEASED,
        }:
            raise DomainLifecycleConflict
        domain.next_check_at = now
        domain.save(update_fields=["next_check_at", "updated_at"])
        return DOMAIN_VERIFICATION_REQUESTED
    raise AssertionError(f"Nieobsługiwana akcja domeny: {action}")


def _ensure_canonical_fallback(domain: Domain) -> None:
    fallback = (
        Domain.all_objects.filter(site_id=domain.site_id, status=DomainStatus.VERIFIED)
        .exclude(pk=domain.pk)
        .order_by("kind", "created_at")
        .first()
    )
    if fallback is not None:
        Domain.all_objects.filter(pk=fallback.pk).update(
            is_canonical=True,
            updated_at=timezone.now(),
        )


def _after_domain_mutation(domain_id: UUID, action: str) -> None:
    from .tasks import verify_site_domain
    from .tls import invalidate_tls_decision

    invalidate_tls_decision(domain_id=domain_id)
    if action in {"enable", "verify"}:
        verify_site_domain.delay(str(domain_id))
