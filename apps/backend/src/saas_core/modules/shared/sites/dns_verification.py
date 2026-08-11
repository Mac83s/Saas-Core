from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from typing import Protocol
from uuid import UUID

import dns.exception
import dns.resolver
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from prometheus_client import Counter

from .models import Domain, DomainKind, DomainStatus, DomainTlsStatus

DNS_VERIFICATION_RESULTS = Counter(
    "saas_core_domain_dns_verification_total",
    "Wyniki kontroli domen klientów.",
    ("result",),
)


@dataclass(frozen=True, slots=True)
class DnsCheckResult:
    verified: bool
    transient: bool
    code: str


class DomainDnsResolver(Protocol):
    def resolve_values(self, name: str, record_type: str) -> set[str]: ...


class DnspythonResolver:
    def __init__(self) -> None:
        self._resolver = dns.resolver.Resolver(configure=True)
        self._resolver.cache = dns.resolver.LRUCache(max_size=1024)
        self._resolver.lifetime = settings.DOMAIN_DNS_TIMEOUT_SECONDS
        self._resolver.retry_servfail = True

    def resolve_values(self, name: str, record_type: str) -> set[str]:
        answer = self._resolver.resolve(
            name,
            record_type,
            lifetime=settings.DOMAIN_DNS_TIMEOUT_SECONDS,
            search=False,
        )
        if record_type == "TXT":
            return {
                b"".join(record.strings).decode("utf-8")
                for record in answer
            }
        if record_type == "CNAME":
            return {str(record.target).rstrip(".").casefold() for record in answer}
        return {str(record).rstrip(".").casefold() for record in answer}


@cache
def default_dns_resolver() -> DnspythonResolver:
    return DnspythonResolver()


def check_domain_dns(
    *,
    hostname: str,
    verification_name: str,
    verification_token: str,
    resolver: DomainDnsResolver | None = None,
) -> DnsCheckResult:
    selected_resolver = resolver or default_dns_resolver()
    try:
        txt_values = selected_resolver.resolve_values(verification_name, "TXT")
    except dns.resolver.NXDOMAIN:
        return DnsCheckResult(False, False, "nxdomain")
    except dns.resolver.NoAnswer:
        return DnsCheckResult(False, False, "txt_missing")
    except (dns.exception.Timeout, dns.resolver.LifetimeTimeout, dns.resolver.NoNameservers):
        return DnsCheckResult(False, True, "resolver_unavailable")
    if verification_token not in txt_values:
        return DnsCheckResult(False, False, "txt_mismatch")

    record_values: dict[str, set[str]] = {"CNAME": set(), "A": set(), "AAAA": set()}
    for record_type in record_values:
        try:
            record_values[record_type] = selected_resolver.resolve_values(
                hostname,
                record_type,
            )
        except dns.resolver.NoAnswer:
            continue
        except dns.resolver.NXDOMAIN:
            return DnsCheckResult(False, False, "nxdomain")
        except (dns.exception.Timeout, dns.resolver.LifetimeTimeout, dns.resolver.NoNameservers):
            return DnsCheckResult(False, True, "resolver_unavailable")

    expected_cname = settings.DOMAIN_DNS_CNAME_TARGET
    cname_matches = bool(
        expected_cname and expected_cname in record_values["CNAME"]
    )
    ipv4_matches = bool(
        set(settings.DOMAIN_DNS_EXPECTED_IPV4) & record_values["A"]
    )
    ipv6_matches = bool(
        set(settings.DOMAIN_DNS_EXPECTED_IPV6) & record_values["AAAA"]
    )
    if not (cname_matches or ipv4_matches or ipv6_matches):
        return DnsCheckResult(False, False, "routing_mismatch")
    return DnsCheckResult(True, False, "verified")


def verify_domain_dns(
    *,
    domain_id: UUID,
    resolver: DomainDnsResolver | None = None,
    checked_at: datetime | None = None,
) -> DnsCheckResult | None:
    now = checked_at or timezone.now()
    domain = Domain.all_objects.filter(pk=domain_id).only(
        "id",
        "kind",
        "status",
        "hostname",
        "verification_name",
        "verification_token",
    ).first()
    if domain is None or domain.kind != DomainKind.CUSTOM:
        return None
    if domain.status in {DomainStatus.DISABLED, DomainStatus.RELEASED}:
        return None
    result = check_domain_dns(
        hostname=domain.hostname,
        verification_name=domain.verification_name,
        verification_token=domain.verification_token,
        resolver=resolver,
    )
    with transaction.atomic():
        current = Domain.all_objects.select_for_update().get(pk=domain_id)
        if current.status in {DomainStatus.DISABLED, DomainStatus.RELEASED}:
            return None
        if (
            current.verification_name != domain.verification_name
            or current.verification_token != domain.verification_token
        ):
            return None
        _apply_dns_result(domain=current, result=result, checked_at=now)
    DNS_VERIFICATION_RESULTS.labels(result=result.code).inc()
    from .tls import invalidate_tls_decision

    invalidate_tls_decision(domain_id=domain_id)
    return result


def schedule_due_domain_verifications(*, limit: int = 100) -> int:
    now = timezone.now()
    domain_ids = list(
        Domain.all_objects.filter(
            kind=DomainKind.CUSTOM,
            status__in=[DomainStatus.PENDING, DomainStatus.VERIFIED, DomainStatus.FAILED],
            next_check_at__lte=now,
        )
        .order_by("next_check_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    from .tasks import verify_site_domain

    for domain_id in domain_ids:
        verify_site_domain.delay(str(domain_id))
    return len(domain_ids)


def _apply_dns_result(
    *,
    domain: Domain,
    result: DnsCheckResult,
    checked_at: datetime,
) -> None:
    was_canonical = domain.is_canonical
    domain.last_checked_at = checked_at
    domain.dns_error_code = "" if result.verified else result.code
    if result.verified:
        domain.status = DomainStatus.VERIFIED
        domain.tls_status = DomainTlsStatus.ELIGIBLE
        domain.last_verified_at = checked_at
        domain.consecutive_transient_errors = 0
        domain.next_check_at = checked_at + timedelta(seconds=settings.DOMAIN_REVERIFY_SECONDS)
    elif result.transient:
        domain.consecutive_transient_errors += 1
        grace_expired = (
            domain.last_verified_at is None
            or checked_at - domain.last_verified_at
            > timedelta(seconds=settings.DOMAIN_TRANSIENT_GRACE_SECONDS)
        )
        if grace_expired:
            domain.status = DomainStatus.FAILED
            domain.tls_status = DomainTlsStatus.FAILED
            domain.is_canonical = False
        exponent = min(domain.consecutive_transient_errors - 1, 5)
        delay_seconds = min(60 * (2**exponent), 1800)
        domain.next_check_at = checked_at + timedelta(seconds=delay_seconds)
    else:
        domain.status = DomainStatus.FAILED
        domain.tls_status = DomainTlsStatus.FAILED
        domain.is_canonical = False
        domain.consecutive_transient_errors = 0
        domain.next_check_at = checked_at + timedelta(seconds=settings.DOMAIN_REVERIFY_SECONDS)
    domain.save(
        update_fields=[
            "status",
            "tls_status",
            "is_canonical",
            "last_checked_at",
            "last_verified_at",
            "next_check_at",
            "dns_error_code",
            "consecutive_transient_errors",
            "updated_at",
        ]
    )
    if was_canonical and not domain.is_canonical:
        _choose_canonical_fallback(domain)


def _choose_canonical_fallback(domain: Domain) -> None:
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
