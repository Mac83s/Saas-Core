"""Publishing a company profile into the public catalogue, and taking it back.

ADR-053. The catalogue row exists if and only if the profile is published, so
publication is a create-or-update and withdrawal is a delete — not a flag. An
absent row is cheaper to prove than a satisfied condition, and this table is
read without a tenant.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.authorization import authorize
from saas_core.modules.core.organizations.models import Organization, OrganizationAuditAction
from saas_core.modules.shared.billing.api import authorize_entitled

from .catalog_contract import categories, cities
from .models import CatalogEntry, ProfileSubjectKind, PublicProfile
from .permissions import PROFILES_ENABLED, PROFILES_MANAGE

#: How many suffixes we try before giving up on a slug. Two companies of the
#: same name in one town is ordinary; forty is somebody scripting.
_SLUG_ATTEMPTS = 40


class ProfileNotPublishable(APIException):
    status_code = 409
    default_detail = "Uzupełnij nazwę, miasto i kategorię przed publikacją w katalogu."
    default_code = "profile_not_publishable"


class CatalogSlugUnavailable(APIException):
    status_code = 409
    default_detail = "W tym mieście jest już zbyt wiele firm o tej nazwie."
    default_code = "catalog_slug_unavailable"


def validate_placement(*, city_slug: str, category: str, organization_type: str) -> None:
    """Refuse a value outside the dictionary rather than repairing it quietly.

    ADR-053 §7: both are public addresses and filter buckets. A silently
    corrected value would produce an address the owner never chose.
    """
    if city_slug and city_slug not in cities():
        raise ValidationError({"city_slug": "Nie ma takiego miasta na liście katalogu."})
    if category and category not in categories(organization_type):
        raise ValidationError({"category": "Nie ma takiej kategorii dla tego typu firmy."})


def _entries() -> QuerySet[CatalogEntry]:
    """Every catalogue row, regardless of tenant.

    The table carries no policy by declaration (ADR-053 §4), so the plain
    manager is the honest way to say "this read is cross-tenant on purpose".
    """
    return CatalogEntry.all_objects.all()


def _free_slug(*, city_slug: str, display_name: str, entry_id: UUID | None) -> str:
    base = slugify(display_name)[:110] or "firma"
    candidates = _entries().filter(city_slug=city_slug, slug__startswith=base)
    if entry_id is not None:
        candidates = candidates.exclude(pk=entry_id)
    taken = set(candidates.values_list("slug", flat=True))
    if base not in taken:
        return base
    for suffix in range(2, _SLUG_ATTEMPTS + 2):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            return candidate
    raise CatalogSlugUnavailable


def _organization_profile(organization_id: UUID | Any) -> PublicProfile:
    profile = (
        PublicProfile.all_objects.filter(
            organization_id=organization_id,
            subject_kind=ProfileSubjectKind.ORGANIZATION,
        )
        .select_related("photo")
        .first()
    )
    if profile is None:
        raise NotFound
    return profile


def _site_for(organization_id: UUID | Any) -> Any:
    """The organization's site, or None when it has none.

    ADR-053 §5: an entry with a site leads to that site's address, and an entry
    without one leads to the catalogue page. Which site is a question for the
    module that owns them, so the import is local — a deployment without
    `shared.sites` must not fail at import time.
    """
    if "shared.sites" not in settings.ACTIVE_MODULES:
        return None
    from saas_core.modules.shared.sites.models import Site

    return (
        Site.all_objects.filter(organization_id=organization_id)
        .exclude(current_publication=None)
        .order_by("slug")
        .first()
    )


@transaction.atomic
def publish_profile() -> CatalogEntry:
    context = authorize_entitled(PROFILES_MANAGE, PROFILES_ENABLED)
    organization = Organization.objects.get(pk=context.organization_id)
    profile = _organization_profile(context.organization_id)

    if not profile.display_name.strip() or not profile.city_slug or not profile.category:
        raise ProfileNotPublishable
    validate_placement(
        city_slug=profile.city_slug,
        category=profile.category,
        organization_type=organization.organization_type,
    )

    entry = _entries().select_for_update().filter(profile=profile).first()
    slug = _free_slug(
        city_slug=profile.city_slug,
        display_name=profile.display_name,
        entry_id=entry.pk if entry else None,
    )
    # An entry that moves town gets a new address; one that stays keeps the
    # address it earned, even when the company is renamed. Moving a URL that
    # search engines already know costs the position it earned — the same rule
    # sites follow for page addresses.
    if entry is not None and entry.city_slug == profile.city_slug:
        slug = entry.slug

    values = {
        "organization_id": context.organization_id,
        "profile": profile,
        "slug": slug,
        "city_slug": profile.city_slug,
        "city": cities()[profile.city_slug].name,
        "category": profile.category,
        "display_name": profile.display_name,
        "headline": profile.headline,
        "photo": profile.photo,
        "site": _site_for(context.organization_id),
    }
    if entry is None:
        entry = CatalogEntry(published_at=timezone.now(), **values)
    else:
        for field, value in values.items():
            setattr(entry, field, value)
    entry.save()
    _refresh_search(entry)

    record_audit(
        organization=organization,
        # ponytail: reuses profile.updated instead of its own audit action —
        # adding one means altering the enum in core.organizations, and another
        # session holds an uncommitted migration on that column. Give publish
        # and withdraw their own actions the next time that enum is touched.
        action=OrganizationAuditAction.PROFILE_UPDATED,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="catalog_entry",
        target_id=entry.id,
        metadata={"catalog": "published", "city_slug": entry.city_slug, "slug": entry.slug},
    )
    return entry


@transaction.atomic
def withdraw_profile() -> None:
    context = authorize(PROFILES_MANAGE)
    profile = _organization_profile(context.organization_id)
    entry = _entries().filter(profile=profile).first()
    if entry is None:
        return
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=OrganizationAuditAction.PROFILE_UPDATED,
        actor=User.objects.filter(pk=context.actor_id).first(),
        target_type="catalog_entry",
        target_id=entry.id,
        metadata={"catalog": "withdrawn", "city_slug": entry.city_slug, "slug": entry.slug},
    )
    entry.delete()


def catalog_entry_for(organization_id: UUID | Any) -> CatalogEntry | None:
    """The organization's own catalogue row, for the panel to show its state."""
    return _entries().filter(organization_id=organization_id).first()


def _refresh_search(entry: CatalogEntry) -> None:
    """Recompute the search vector for one row.

    ponytail: `simple` configuration, so no stemming and no typo tolerance —
    "fryzjer" finds "fryzjerstwo" through the prefix query in `search_catalog`,
    but "fryzer" finds nothing. Add `unaccent` and `pg_trgm` when the catalogue
    is full enough for that to be the complaint.
    """
    from django.contrib.postgres.search import SearchVector

    CatalogEntry.all_objects.filter(pk=entry.pk).update(
        search=SearchVector("display_name", "headline", "category", config="simple")
    )
