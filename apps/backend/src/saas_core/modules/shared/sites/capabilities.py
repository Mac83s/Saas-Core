"""What this tenant's content surface can do (W9.6.2).

SeoContentRank has no database, no ORM and no shell — it only has this API. It
therefore cannot discover what is possible by looking: which languages a site
publishes in, which blocks it may use and at which schema version, how much
storage is left, which page types are meaningful, which addresses are live, and
which version of the contract it is talking to. Answering that in one read is
what lets the connector refuse a plan it cannot execute *before* it writes
anything.

Nothing here is a draft. The reply describes shape and limits, never unpublished
content: a read scope must not become a way to survey what a customer has not
published yet.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings

from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
    decide_feature,
    decide_quota,
)

from .block_contracts import site_block_contracts
from .models import (
    AutomationGrantMode,
    ContentAutomationGrant,
    ContentCollectionKind,
    Domain,
    DomainStatus,
    PageType,
    Site,
    SitePurpose,
)
from .permissions import SITE_CONTENT_EDIT, SITES_ENABLED, SITES_MAX

#: The connector contract this deployment speaks. Bumped when a command or a
#: payload changes shape in a way an older connector could not handle; a
#: connector that does not recognise it must stop rather than guess.
CONTENT_CONTRACT_VERSION = 1

#: The oldest contract this deployment still accepts. Raising it turns away
#: connectors that were working yesterday, so it moves only after every
#: connected connector reports the newer version — the calendar alone is not
#: enough when the connector on the other side is our own product.
MINIMUM_CONTENT_CONTRACT_VERSION = 1

#: Quotas worth reporting: the ones a content operation can actually exhaust.
REPORTED_QUOTAS = ("storage.bytes", SITES_MAX)


def read_content_capabilities() -> dict[str, Any]:
    """Shape and limits for the calling tenant, never its unpublished content."""
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    contracts = site_block_contracts()
    # Scoped explicitly rather than through `all_objects`: `shared.sites` tables
    # do not enforce row-level security, so the unscoped manager here would have
    # handed every tenant the slugs and hostnames of every other one.
    sites = list(
        Site.all_objects.filter(organization_id=context.organization_id).order_by(
            "created_at"
        )
    )
    return {
        "contract_version": CONTENT_CONTRACT_VERSION,
        "minimum_contract_version": MINIMUM_CONTENT_CONTRACT_VERSION,
        # Every version still accepted, spelled out. A connector holding one
        # number has to decide whether its own is acceptable, and deriving the
        # range from two integers is a rule it would have to reimplement.
        "contract_versions": [
            str(version)
            for version in range(
                MINIMUM_CONTENT_CONTRACT_VERSION, CONTENT_CONTRACT_VERSION + 1
            )
        ],
        # Read out of the schema rather than kept as a second list: a
        # capabilities response that disagrees with the contract is worse than
        # none, because a client believes it.
        "commands": supported_commands(),
        # What this particular caller may do. A session gets `null` — the
        # question only means something for a credential.
        "grant": _grant_summary(context),
        "locales": {
            "default": settings.SITES_DEFAULT_LOCALE,
            "supported": list(settings.SITES_SUPPORTED_LOCALES),
        },
        "block_schemas": [
            {
                "block_type": block_type,
                "versions": sorted(versions),
                "latest_version": max(versions),
            }
            for block_type, versions in sorted(contracts.validators.items())
        ],
        "content_types": {
            "site_purposes": [value for value, _label in SitePurpose.choices],
            "page_types": [value for value, _label in PageType.choices],
            "collection_kinds": [
                value for value, _label in ContentCollectionKind.choices
            ],
        },
        "quotas": [_quota(key) for key in REPORTED_QUOTAS],
        "sites": [_site(site, organization_id=context.organization_id) for site in sites],
    }


def supported_commands() -> list[str]:
    """The command names the frozen contract defines, taken from the contract.

    SeoContentRank derives its own list from the same file, so the two cannot
    disagree about what may be sent.
    """
    from .change_sets import change_set_validator

    # The validator types its schema as bool-or-mapping, since JSON Schema
    # allows `true`/`false` as whole schemas. Ours is an object.
    schema: dict[str, Any] = dict(change_set_validator().schema)  # type: ignore[arg-type]
    defs = schema["$defs"]
    names = []
    for branch in defs["command"]["oneOf"]:
        definition = defs[branch["$ref"].rsplit("/", 1)[-1]]
        names.append(str(definition["properties"]["command"]["const"]))
    return sorted(names)


def _grant_summary(context: Any) -> dict[str, Any] | None:
    """What this credential was hired to do, as the connector must mirror it.

    `mode` is the narrowest of the active grants, not the widest. A connector
    that understands only one mode per connection then cannot escalate by
    reading this field — and one that reads `scopes` gets the exact answer per
    resource.
    """
    from .services import _is_automation

    if not _is_automation(context) or context.credential_id is None:
        return None
    grants = [
        grant
        for grant in ContentAutomationGrant.all_objects.filter(
            organization_id=context.organization_id,
            credential_id=context.credential_id,
            revoked_at__isnull=True,
        ).select_related("site", "collection")
        if grant.active
    ]
    if not grants:
        # Authenticated and hired for nothing. Saying so plainly is kinder than
        # letting the connector discover it one refusal at a time.
        return {"mode": None, "scopes": []}
    order = list(AutomationGrantMode.values)
    return {
        "mode": min(grants, key=lambda grant: order.index(grant.mode)).mode,
        "scopes": [
            {
                "kind": "site" if grant.site_id else "collection",
                "id": str(grant.site_id or grant.collection_id),
                "mode": grant.mode,
                "expires_at": (
                    grant.expires_at.isoformat() if grant.expires_at else None
                ),
            }
            for grant in grants
        ],
    }


def _quota(quota_key: str) -> dict[str, Any]:
    decision = decide_quota(quota_key)
    return {
        "key": quota_key,
        "limit": decision.value,
        "available": decision.available,
    }


def _site(site: Site, *, organization_id: Any) -> dict[str, Any]:
    # Only verified hostnames: an address still waiting on DNS is not somewhere
    # a connector should be publishing links to.
    hostnames = list(
        Domain.all_objects.filter(
            organization_id=organization_id,
            site_id=site.id,
            status=DomainStatus.VERIFIED,
        )
        .order_by("-is_canonical", "hostname")
        .values_list("hostname", flat=True)
    )
    return {
        "site_id": str(site.id),
        "slug": site.slug,
        "purpose": site.purpose,
        "default_locale": site.default_locale,
        "hostnames": hostnames,
        # Whether the site has ever been published, not what is in its drafts.
        "published": site.current_publication_id is not None,
    }


def content_write_allowed() -> bool:
    """Whether writes are possible at all, separately from any single call.

    A connector that asks first can report "your plan does not allow this"
    instead of collecting a 402 halfway through a batch.
    """
    return decide_feature(SITES_ENABLED, operation=FeatureOperation.WRITE).allowed
