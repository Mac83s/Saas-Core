"""How many content types a site may have switched on (ADR-079 pkt 21–23).

A site's first content type — its blog, or whatever the company makes first —
takes nothing but the site itself. Every further one passes two gates, both
asked here and nowhere else:

- the deployment's switch `features.contentTypes`: whether the platform offers
  companies further types at all;
- the plan's number `sites.content_types.additional.max`: how many switched-on
  types beyond the first one site may have. A plan without the number has no
  limit, exactly like the limit on languages (ADR-071 pkt 7).

Asked only when a type is made or switched on again. Nothing here ever takes a
type away: a company over its limit — after a cheaper plan, an expired
subscription, the platform's switch turned off — keeps every type it has,
answering visitors and open to edits. The platform's own workspace is exempt
from both gates: it has no plan, and the switch is about what companies are
offered (pkt 28).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from rest_framework.exceptions import APIException, ErrorDetail, ValidationError

from saas_core.modules.core.organizations.models import Organization, WorkspaceKind
from saas_core.modules.shared.billing.api import DecisionReason, FeatureOperation, decide_quota

from .models import ContentCollection, Site

CONTENT_TYPES_ADDITIONAL_MAX = "sites.content_types.additional.max"

CONTENT_TYPES_NOT_OFFERED = "content_types_not_offered"
QUOTA_EXCEEDED = "quota_exceeded"
PLAN_ACCESS_DENIED = "plan_access_denied"
CONTENT_TYPE_ARCHIVED = "content_type_archived"

_DENIALS = {
    "read_only": "subskrypcja jest tylko do odczytu",
    "access_blocked": "dostęp do konta jest zablokowany",
    "snapshot_expired": "uprawnienia planu wygasły",
    "snapshot_missing": "firma nie ma jeszcze planu",
    "unknown_quota": "plan nie zna limitu typów treści",
}


@dataclass(frozen=True, slots=True)
class ContentTypesLimit:
    """Whether a site may have one more content type switched on now."""

    allowed: bool
    #: Why not: `content_types_not_offered`, `quota_exceeded` or
    #: `plan_access_denied`; "" when allowed.
    code: str = ""
    #: The same in words a company's owner reads.
    message: str = ""
    #: Whether further types are offered here at all (the platform's switch).
    offered: bool = True
    #: Switched-on types beyond the first the plan allows; None — no limit.
    additional_max: int | None = None
    #: Switched-on types beyond the first the site has.
    additional_used: int = 0


class ContentTypeRefused(ValidationError):
    """One more content type the site may not have now. The code is the
    problem's own, so a caller branches on it without reading the words."""

    def __init__(self, limit: ContentTypesLimit) -> None:
        super().__init__([ErrorDetail(limit.message, code=limit.code)])
        self.problem_code = limit.code


class ContentTypeArchived(APIException):
    status_code = 409
    default_detail = (
        "Ten typ treści jest wyłączony. Włącz go, żeby zmieniać i publikować jego wpisy."
    )
    default_code = CONTENT_TYPE_ARCHIVED


def content_types_limit(
    site: Site, *, beside: ContentCollection | None = None
) -> ContentTypesLimit:
    """The gates' word on one more switched-on type for `site`.

    `beside` is a type left out of the count: the one about to be switched on
    again, or — asked before switching one off — the one whose return is being
    weighed. Reads the site's types as they are; the caller holds the site's
    row lock when the answer decides a write.
    """
    active = ContentCollection.all_objects.filter(
        organization_id=site.organization_id, site_id=site.id, archived_at__isnull=True
    )
    if beside is not None:
        active = active.exclude(pk=beside.pk)
    count = active.count()
    used = max(0, count - 1)
    workspace_kind = (
        Organization.objects.filter(pk=site.organization_id)
        .values_list("workspace_kind", flat=True)
        .first()
    )
    if workspace_kind == WorkspaceKind.PLATFORM:
        return ContentTypesLimit(allowed=True, additional_used=used)
    offered = bool(settings.CONTENT_TYPES_OFFERED)
    if count == 0:
        # The first type of a site: the site's own entitlement is all it takes.
        return ContentTypesLimit(allowed=True, offered=offered)
    if not offered:
        return ContentTypesLimit(
            allowed=False,
            code=CONTENT_TYPES_NOT_OFFERED,
            message=(
                "Ta platforma nie oferuje kolejnych typów treści. "
                "Typy, które strona już ma, działają dalej."
            ),
            offered=False,
            additional_used=used,
        )
    decision = decide_quota(CONTENT_TYPES_ADDITIONAL_MAX, operation=FeatureOperation.WRITE)
    if decision.available:
        if count > decision.value:
            return ContentTypesLimit(
                allowed=False,
                code=QUOTA_EXCEEDED,
                message=(
                    "Plan nie obejmuje kolejnego typu treści (limit poza pierwszym: "
                    f"{decision.value}). Więcej daje wyższy plan; typy, które strona już ma, "
                    "działają dalej."
                ),
                additional_max=decision.value,
                additional_used=used,
            )
        return ContentTypesLimit(
            allowed=True, additional_max=decision.value, additional_used=used
        )
    if decision.reason == DecisionReason.QUOTA_MISSING:
        # A plan that names no number has no limit.
        return ContentTypesLimit(allowed=True, additional_used=used)
    why = _DENIALS.get(str(decision.reason), str(decision.reason))
    return ContentTypesLimit(
        allowed=False,
        code=PLAN_ACCESS_DENIED,
        message=f"Plan nie pozwala teraz dodać typu treści: {why}.",
        additional_used=used,
    )


def ensure_content_type_capacity(site: Site, *, beside: ContentCollection | None = None) -> None:
    """Refuses one more switched-on type the gates have no room for."""
    limit = content_types_limit(site, beside=beside)
    if not limit.allowed:
        raise ContentTypeRefused(limit)
