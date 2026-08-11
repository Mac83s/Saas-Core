from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from prometheus_client import Counter

from saas_core.modules.core.organizations.models import OrganizationStatus

from .domains import InvalidHostname, normalize_hostname
from .models import Domain, DomainStatus, DomainTlsStatus

TLS_AUTHORIZATION_DECISIONS = Counter(
    "saas_core_domain_tls_authorization_total",
    "Decyzje endpointu Caddy On-Demand TLS.",
    ("decision",),
)


@dataclass(frozen=True, slots=True)
class TlsAuthorization:
    allowed: bool
    reason: str


def authorize_tls_hostname(value: str) -> TlsAuthorization:
    try:
        hostname = normalize_hostname(value)
    except InvalidHostname:
        return _decision(False, "invalid_hostname")
    digest = hashlib.sha256(hostname.encode()).hexdigest()
    if not _within_rate_limit(digest):
        return _decision(False, "rate_limited")
    cache_key = f"sites:tls-decision:{digest}"
    cached = cache.get(cache_key)
    if cached in {"allow", "deny"}:
        return _decision(cached == "allow", "cached")

    domain = (
        Domain.all_objects.select_related("site", "organization")
        .filter(hostname=hostname)
        .filter(
            status=DomainStatus.VERIFIED,
            organization__status=OrganizationStatus.ACTIVE,
            site__current_publication__isnull=False,
        )
        .filter(Q(tls_status=DomainTlsStatus.ELIGIBLE) | Q(tls_status=DomainTlsStatus.REQUESTED))
        .first()
    )
    allowed = domain is not None
    cache.set(
        cache_key,
        "allow" if allowed else "deny",
        timeout=settings.DOMAIN_TLS_DECISION_CACHE_SECONDS,
    )
    if domain is not None:
        Domain.all_objects.filter(pk=domain.pk).update(
            tls_status=DomainTlsStatus.REQUESTED,
            tls_last_requested_at=timezone.now(),
            updated_at=timezone.now(),
        )
    return _decision(allowed, "allowed" if allowed else "not_eligible")


def invalidate_tls_decision(*, domain_id: UUID) -> None:
    hostname = Domain.all_objects.filter(pk=domain_id).values_list("hostname", flat=True).first()
    if hostname:
        digest = hashlib.sha256(str(hostname).encode()).hexdigest()
        cache.delete(f"sites:tls-decision:{digest}")


def invalidate_site_tls_decisions(*, site_id: UUID) -> None:
    cache.delete_many([
        f"sites:tls-decision:{hashlib.sha256(hostname.encode()).hexdigest()}"
        for hostname in Domain.all_objects.filter(site_id=site_id).values_list(
            "hostname", flat=True
        )
    ])


def _within_rate_limit(host_digest: str) -> bool:
    bucket = int(timezone.now().timestamp() // 60)
    key = f"sites:tls-rate:{bucket}:{host_digest}"
    if cache.add(key, 1, timeout=70):
        return True
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=70)
        return True
    return count <= settings.DOMAIN_TLS_RATE_LIMIT_PER_MINUTE


def _decision(allowed: bool, reason: str) -> TlsAuthorization:
    TLS_AUTHORIZATION_DECISIONS.labels(decision=reason).inc()
    return TlsAuthorization(allowed, reason)
