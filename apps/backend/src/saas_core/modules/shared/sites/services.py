from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid7
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.api import (
    DomainEvent,
    ResourceReferenceConflict,
    ResourceReferenceRejected,
    copy_resource_references,
    dispatch_domain_event,
    list_resource_reference_ids,
    record_resource_references,
)
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import (
    TenantContext,
    require_tenant_context,
)
from saas_core.modules.core.organizations.models import Organization, WorkspaceKind
from saas_core.modules.core.organizations.tasks import issue_tenant_task_contract
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
    consume_quota,
    decide_quota,
)
from saas_core.modules.shared.media.api import (
    discard_approved_media_asset_objects,
    materialize_approved_media_asset,
)
from saas_core.observability import correlation_id

from .block_contracts import validate_site_block
from .block_decoration import (
    normalize_block,
    stored_block_payload,
    validate_decoration,
    validate_page_presentation,
    validate_presentation,
)
from .domains import InvalidHostname, link_host, normalize_hostname
from .localization import (
    SiteLocalizationReport,
    build_localization_report,
    localized_path,
)
from .metrics import OUTBOX_EVENTS
from .models import (
    AutomationGrantMode,
    ContentAutomationGrant,
    ContentCollection,
    ContentEntryVersion,
    Domain,
    DomainStatus,
    NavigationItem,
    Page,
    PageAutomationPolicy,
    PageBlock,
    PageTranslation,
    PageTranslationMutation,
    PageType,
    PageVersion,
    Publication,
    Site,
    SiteOutboxEvent,
    SitePurpose,
    SiteRedirect,
    canonical_json_hash,
)
from .permissions import PAGES_MAX, SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED, SITES_MAX
from .real_media import assert_real_media_slots
from .rich_content import assert_unique_anchors, block_asset_ids, block_links

SITE_CREATED = "sites.site.created"
PAGE_CREATED = "sites.page.created"
PAGE_DRAFT_SAVED = "sites.page.draft_saved"
PAGE_TRANSLATION_SAVED = "sites.page.translation_saved"
SITE_PUBLISHED = "sites.site.published"
SITE_ROLLED_BACK = "sites.site.rolled_back"
SITE_NAVIGATION_SAVED = "sites.navigation.saved"
SITE_PURPOSE_SET = "sites.site.purpose_set"
PAGE_TYPE_SET = "sites.page.type_set"
PAGE_URL_CHANGED = "sites.page.url_changed"
REDIRECT_DELETED = "sites.redirect.deleted"
PAGE_AUTOMATION_POLICY_SET = "sites.page.automation_policy_set"
PAGE_TEMPLATE_IMPORTED = "sites.page.template_imported"
SITE_PUBLISHED_EVENT = "sites.site.published"
#: A rollback is a publication in mechanism and the opposite of one in meaning.
#: Sending it as `sites.site.published` left a subscriber unable to tell that
#: its own change had just been undone.
SITE_ROLLED_BACK_EVENT = "sites.site.rolled_back"
PAGE_DRAFT_SAVED_EVENT = "sites.page.draft_saved"
GRANT_REVOKED_EVENT = "sites.automation_grant.revoked"
GRANT_REVOKED = "sites.automation_grant.revoked"
MEDIA_ASSET_RESOURCE_TYPE = "shared.media.asset"
PAGE_VERSION_REFERENCE_OWNER = "sites.page_version"
PUBLICATION_REFERENCE_OWNER = "sites.publication"
PUBLICATION_SNAPSHOT_SCHEMA_VERSION = 1
# `save_draft(page_presentation=UNSET)` keeps the current draft's page
# presentation; None clears it. Older clients, change sets and blueprints
# never send the field, so they must not reset what a person chose.
UNSET: Any = object()
DEFAULT_DESIGN_TOKENS = {
    "schemaVersion": 1,
    "palette": "neutral",
    "typography": "sans",
    "radius": "medium",
    "spacing": "comfortable",
}


class SitesIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Klucz idempotencji wskazuje inne żądanie."
    default_code = "sites_idempotency_conflict"


class SiteSlugConflict(APIException):
    status_code = 409
    default_detail = "Slug strony jest już używany w tej organizacji."
    default_code = "site_slug_conflict"


class PageKeyConflict(APIException):
    status_code = 409
    default_detail = "Klucz podstrony jest już używany w tej stronie."
    default_code = "page_key_conflict"


class PageLimitReached(APIException):
    status_code = 409
    default_code = "page_limit_reached"

    def __init__(self, limit: int) -> None:
        super().__init__(
            detail=(
                f"Plan pozwala na {limit} podstron na jednej stronie. Usuń podstronę "
                "albo wybierz wyższy plan, żeby dodać kolejną."
            ),
            code=self.default_code,
        )


def _ensure_page_capacity(site: Site) -> None:
    """Refuses a page the plan has no room for; pages already there stay.

    ponytail: a snapshot without `pages.max` (a plan version older than billing
    0024, the E2E fixture) has no page limit — the limit arrives with the plan
    version that names it, not by refusing everyone else.
    """
    decision = decide_quota(PAGES_MAX)
    if not decision.available:
        return
    pages = Page.all_objects.filter(organization_id=site.organization_id, site_id=site.id)
    if pages.count() >= decision.value:
        raise PageLimitReached(decision.value)


class DraftVersionConflict(APIException):
    status_code = 409
    default_detail = "Draft został w międzyczasie zmieniony."
    default_code = "draft_version_conflict"


class NavigationVersionConflict(APIException):
    status_code = 409
    default_detail = "Nawigacja została w międzyczasie zmieniona."
    default_code = "navigation_version_conflict"


class NavigationInvalidTree(APIException):
    status_code = 400
    default_detail = "Nawigacja zawiera nieprawidłowe drzewo pozycji."
    default_code = "navigation_invalid_tree"


class AutomationGrantMissing(APIException):
    status_code = 403
    default_detail = "Klucz nie ma grantu obejmującego ten zasób."
    default_code = "automation_grant_missing"


class RedirectReasonRequired(APIException):
    status_code = 400
    default_detail = "Zmiana adresu wymaga uzasadnienia."
    default_code = "redirect_reason_required"


class RedirectTargetUnchanged(APIException):
    status_code = 400
    default_detail = "Nowy adres jest taki sam jak obecny."
    default_code = "redirect_target_unchanged"


class RedirectNotFound(NotFound):
    default_detail = "Przekierowanie nie istnieje."
    default_code = "redirect_not_found"


class TranslationSlugInvalid(APIException):
    status_code = 400
    default_detail = "Slug może zawierać małe litery, cyfry i łączniki."
    default_code = "translation_slug_invalid"


class TranslationNotFound(NotFound):
    default_detail = "Tłumaczenie strony nie istnieje."
    default_code = "translation_not_found"


class PageInvalidType(APIException):
    status_code = 400
    default_detail = "Nieznany typ podstrony."
    default_code = "page_invalid_type"


class SiteInvalidPurpose(APIException):
    status_code = 400
    default_detail = "Nieznane przeznaczenie strony."
    default_code = "site_invalid_purpose"


class SitePurposeMismatch(APIException):
    status_code = 403
    default_detail = "Przeznaczenie nie odpowiada rodzajowi workspace'u."
    default_code = "site_purpose_mismatch"


class AutomationGrantModeUnknown(APIException):
    status_code = 403
    default_detail = "Tryb grantu nie jest obsługiwany przez tę wersję."
    default_code = "automation_grant_mode_unknown"


class AutomationSuggestOnly(APIException):
    status_code = 403
    default_detail = "Ten grant pozwala tylko proponować, nie zapisywać."
    default_code = "automation_suggest_only"


class AutomationApprovalRequired(APIException):
    status_code = 403
    default_detail = "Publikacja tym grantem wymaga akceptacji człowieka."
    default_code = "automation_approval_required"


class AutomationAutonomyNotPiloted(APIException):
    status_code = 403
    default_detail = (
        "Tryb autonomiczny działa na razie tylko w workspace platformowym."
    )
    default_code = "automation_autonomy_not_piloted"


class AutomationOutsideWindow(APIException):
    status_code = 409
    default_detail = "Poza dozwolonym oknem czasowym tego grantu."
    default_code = "automation_outside_window"


class AutomationPayloadTooLarge(APIException):
    status_code = 400
    default_detail = "Zmiana przekracza dozwoloną objętość."
    default_code = "automation_payload_too_large"


class AutomationChangeLimitReached(APIException):
    status_code = 429
    default_detail = "Dzienny limit zmian tego grantu został wyczerpany."
    default_code = "automation_change_limit_reached"


class AutomationLinkHostForbidden(APIException):
    status_code = 403
    default_detail = "Grant nie pozwala linkować do tego hosta."
    default_code = "automation_link_host_forbidden"


class PersonRequired(APIException):
    status_code = 403
    default_detail = "Ta operacja wymaga decyzji człowieka."
    default_code = "person_required"


class PageAutomationForbidden(APIException):
    status_code = 403
    default_detail = "Ta podstrona nie jest udostępniona automatyzacji treści."
    default_code = "page_automation_forbidden"


class PageEditingLocked(APIException):
    status_code = 409
    default_detail = "Podstrona jest właśnie edytowana ręcznie."
    default_code = "page_editing_locked"


class SiteMediaReferenceUnavailable(APIException):
    status_code = 409
    default_detail = "Wybrane media nie są gotowe albo nie są dostępne w tej organizacji."
    default_code = "site_media_reference_unavailable"


class SitePublicationNotReady(APIException):
    status_code = 409
    default_detail = "Site nie ma kompletnego draftu i bazowych tłumaczeń."
    default_code = "site_publication_not_ready"


class SitePublicationConflict(APIException):
    status_code = 409
    default_detail = "Zawartość site zmieniła się podczas publikacji."
    default_code = "site_publication_conflict"


class SitePublicationNotFound(NotFound):
    default_detail = "Publikacja nie istnieje."
    default_code = "site_publication_not_found"


class SitePublicationAlreadyCurrent(APIException):
    status_code = 409
    default_detail = "Wybrana publikacja jest już bieżąca."
    default_code = "site_publication_already_current"


class UnsupportedSiteLocale(APIException):
    status_code = 400
    default_detail = "Locale nie należy do profilu deploymentu."
    default_code = "unsupported_site_locale"


class TranslationFallbackConflict(APIException):
    status_code = 400
    default_detail = "Locale bazowe nie może korzystać z fallbacku."
    default_code = "translation_fallback_conflict"


class TranslationVersionConflict(APIException):
    status_code = 409
    default_detail = "Metadane tłumaczenia zostały w międzyczasie zmienione."
    default_code = "translation_version_conflict"


class TranslationSlugConflict(APIException):
    status_code = 409
    default_detail = "Slug jest już używany w tym site i locale."
    default_code = "translation_slug_conflict"


class TranslationSlugLocked(APIException):
    status_code = 409
    default_detail = "Slug opublikowanego tłumaczenia jest zablokowany."
    default_code = "translation_slug_locked"


class SiteNotFound(NotFound):
    default_detail = "Strona nie istnieje."
    default_code = "site_not_found"


class PageNotFound(NotFound):
    default_detail = "Podstrona nie istnieje."
    default_code = "page_not_found"


class PageVersionNotFound(NotFound):
    default_detail = "Wersja draftu nie istnieje."
    default_code = "page_version_not_found"


@dataclass(frozen=True, slots=True)
class MutationResult[T]:
    value: T
    created: bool


@dataclass(frozen=True, slots=True)
class PageDraft:
    page: Page
    version: PageVersion | None
    blocks: tuple[PageBlock, ...]
    media_asset_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PageTranslations:
    page: Page
    supported_locales: tuple[str, ...]
    translations: tuple[PageTranslation, ...]


@dataclass(frozen=True, slots=True)
class SiteNavigation:
    site: Site
    items: tuple[NavigationItem, ...]


@dataclass(frozen=True, slots=True)
class SitePublication:
    publication: Publication
    created: bool


def list_sites(*, cursor: UUID | None, limit: int) -> tuple[list[Site], UUID | None]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    queryset = Site.all_objects.filter(organization_id=context.organization_id).order_by("id")
    if cursor is not None:
        queryset = queryset.filter(id__gt=cursor)
    rows = list(queryset[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


@transaction.atomic
def create_site(
    *,
    name: str,
    slug: str,
    default_locale: str,
    idempotency_key: str,
    subdomain_label: str | None = None,
) -> MutationResult[Site]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if default_locale not in _supported_locales():
        raise UnsupportedSiteLocale
    normalized_key = _idempotency_key(idempotency_key)
    normalized_slug = slug.strip().lower()
    request_hash = canonical_json_hash({
        "name": name,
        "slug": normalized_slug,
        "default_locale": default_locale,
        "subdomain_label": subdomain_label or "",
    })
    existing = Site.all_objects.filter(
        organization_id=context.organization_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)

    consume_quota(
        SITES_MAX,
        amount=1,
        idempotency_key=_quota_idempotency_key(context.actor_id, normalized_key),
    )
    existing = Site.all_objects.filter(
        organization_id=context.organization_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    if Site.all_objects.filter(
        organization_id=context.organization_id,
        slug=normalized_slug,
    ).exists():
        raise SiteSlugConflict

    organization = Organization.objects.get(pk=context.organization_id)
    actor = User.objects.get(pk=context.actor_id)
    site = Site.all_objects.create(
        organization=organization,
        name=name,
        slug=normalized_slug,
        default_locale=default_locale,
        created_by=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
    )
    from .domain_services import create_platform_domain

    platform_domain = create_platform_domain(
        site=site,
        actor=actor,
        idempotency_key=normalized_key,
        preferred_label=subdomain_label,
    )
    record_audit(
        organization=organization,
        action=SITE_CREATED,
        actor=actor,
        target_type="site",
        target_id=site.id,
        metadata={
            "slug": site.slug,
            "default_locale": site.default_locale,
            "platform_hostname": platform_domain.hostname,
        },
    )
    return MutationResult(site, True)


def list_pages(
    *,
    site_id: UUID,
    cursor: UUID | None,
    limit: int,
) -> tuple[list[Page], UUID | None]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    if not Site.all_objects.filter(
        pk=site_id,
        organization_id=context.organization_id,
    ).exists():
        raise SiteNotFound
    queryset = (
        Page.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site_id,
        )
        .select_related("current_draft")
        .order_by("id")
    )
    if cursor is not None:
        queryset = queryset.filter(id__gt=cursor)
    rows = list(queryset[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


@transaction.atomic
def create_page(
    *,
    site_id: UUID,
    name: str,
    key: str,
    idempotency_key: str,
) -> MutationResult[Page]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_idempotency_key = _idempotency_key(idempotency_key)
    normalized_page_key = key.strip().lower()
    request_hash = canonical_json_hash({
        "site_id": str(site_id),
        "name": name,
        "key": normalized_page_key,
    })
    try:
        site = Site.all_objects.select_for_update().get(
            pk=site_id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    existing = Page.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_idempotency_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    if Page.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        key=normalized_page_key,
    ).exists():
        raise PageKeyConflict
    _ensure_page_capacity(site)

    actor = User.objects.get(pk=context.actor_id)
    page = Page.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        name=name,
        key=normalized_page_key,
        created_by=actor,
        idempotency_key=normalized_idempotency_key,
        request_hash=request_hash,
    )
    record_audit(
        organization=site.organization,
        action=PAGE_CREATED,
        actor=actor,
        target_type="page",
        target_id=page.id,
        metadata={"site_id": str(site.id), "key": page.key},
    )
    return MutationResult(page, True)


def get_draft(*, page_id: UUID) -> PageDraft:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    try:
        page = Page.all_objects.select_related("current_draft").get(
            pk=page_id,
            organization_id=context.organization_id,
        )
    except Page.DoesNotExist as error:
        raise PageNotFound from error
    if page.current_draft is None:
        assert_within_grant(context, site_id=page.site_id)
        return PageDraft(page, None, (), ())
    assert_within_grant(context, site_id=page.site_id)
    blocks = tuple(
        PageBlock.all_objects.filter(
            organization_id=context.organization_id,
            page_version_id=page.current_draft_id,
        ).order_by("position")
    )
    return PageDraft(
        page,
        page.current_draft,
        blocks,
        _page_version_media_asset_ids(context=context, version_id=page.current_draft.id),
    )


def read_site_audit_target(*, site_id: UUID) -> dict[str, str]:
    """An owned canonical public surface, for an explicitly authorized audit."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    site = Site.all_objects.filter(pk=site_id, organization_id=context.organization_id).first()
    if site is None:
        raise SiteNotFound
    assert_within_grant(context, site_id=site.id)
    from .models import Domain, DomainStatus

    domain = Domain.all_objects.filter(
        site_id=site.id, organization_id=context.organization_id,
        status=DomainStatus.VERIFIED, is_canonical=True,
    ).first()
    if domain is None:
        raise SitePublicationNotReady(detail="Strona nie ma zweryfikowanej domeny kanonicznej.")
    return {"site_id": str(site.id), "name": site.slug, "root_url": f"https://{domain.hostname}/"}


def get_draft_preview(*, page_id: UUID, version_id: UUID) -> PageDraft:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    try:
        page = Page.all_objects.get(
            pk=page_id,
            organization_id=context.organization_id,
        )
        version = PageVersion.all_objects.get(
            pk=version_id,
            page_id=page.id,
            organization_id=context.organization_id,
        )
    except (Page.DoesNotExist, PageVersion.DoesNotExist) as error:
        raise PageVersionNotFound from error
    assert_within_grant(context, site_id=page.site_id)
    blocks = tuple(
        PageBlock.all_objects.filter(
            organization_id=context.organization_id,
            page_version_id=version.id,
        ).order_by("position")
    )
    validate_page_presentation(version.presentation)
    for block in blocks:
        validate_decoration(block.decoration)
        validate_presentation(block.presentation)
        validate_site_block(
            block_type=block.block_type,
            schema_version=block.schema_version,
            data=block.data,
        )
    return PageDraft(
        page,
        version,
        blocks,
        _page_version_media_asset_ids(context=context, version_id=version.id),
    )


PAGE_EDITING_LOCK_TTL_SECONDS = 300


def _is_automation(context: TenantContext) -> bool:
    """An integration acting on its own, as opposed to a signed-in person.

    Everything below keys off this rather than off the endpoint, so a future
    channel — MCP, a workflow — inherits the same limits without restating them.
    """
    return context.principal_kind != "membership"


#: Modes in which an automation may publish without a person approving the
#: individual change. `publish_with_approval` is deliberately absent: the
#: approval digest it needs is W9.6.6, so until then it refuses rather than
#: quietly behaving like `autonomous`.
PUBLISHING_MODES = frozenset({AutomationGrantMode.AUTONOMOUS})

#: Modes in which an automation may write a draft at all.
WRITING_MODES = frozenset({
    AutomationGrantMode.DRAFT_WRITE,
    AutomationGrantMode.PUBLISH_WITH_APPROVAL,
    AutomationGrantMode.AUTONOMOUS,
})


def assert_within_grant(
    context: TenantContext,
    *,
    site_id: UUID,
    collection_id: UUID | None = None,
    writing: bool = False,
    publishing: bool = False,
    payload_bytes: int | None = None,
) -> ContentAutomationGrant | None:
    """Checks that this credential was granted this resource (ADR-035 §4).

    A credential with no grant reaches nothing. That is the point: authenticating
    proves which organization is calling, not what it was hired to do, and the
    agreement with a customer is normally "the blog" rather than "the website".

    The grant's mode and bounds are checked here too, so every caller gets them
    without having to remember: one place decides what an automation may do,
    and a new endpoint cannot forget to ask.
    """
    if not _is_automation(context):
        return None
    if context.credential_id is None:
        raise AutomationGrantMissing
    grants = ContentAutomationGrant.all_objects.filter(
        organization_id=context.organization_id,
        credential_id=context.credential_id,
        revoked_at__isnull=True,
    )
    for grant in grants:
        if not grant.active:
            continue
        # A site-wide grant covers its collections; a collection grant covers
        # only itself, never the pages around it.
        matches = (grant.site_id is not None and grant.site_id == site_id) or (
            collection_id is not None and grant.collection_id == collection_id
        )
        if not matches:
            continue
        _assert_grant_permits(
            grant,
            context,
            writing=writing or publishing,
            publishing=publishing,
            payload_bytes=payload_bytes,
        )
        return grant
    raise AutomationGrantMissing


def _assert_grant_permits(
    grant: ContentAutomationGrant,
    context: TenantContext,
    *,
    writing: bool,
    publishing: bool,
    payload_bytes: int | None,
) -> None:
    # An unknown mode is not a permissive one. A value this build does not
    # implement — `auto_publish_limited`, or anything a future version writes —
    # stops the call rather than falling back to the nearest thing it knows.
    if grant.mode not in set(AutomationGrantMode.values):
        raise AutomationGrantModeUnknown
    if publishing:
        if grant.mode not in PUBLISHING_MODES:
            raise AutomationApprovalRequired
        # ADR-035 §4: autonomy starts on our own content, where a bad article
        # costs us rather than a customer who never asked for the experiment.
        # A setting rather than a hard rule, because lifting the pilot is a
        # decision somebody makes and records once it has been earned.
        if settings.SITES_AUTONOMOUS_PILOT_ONLY and not Organization.objects.filter(
            pk=context.organization_id, workspace_kind=WorkspaceKind.PLATFORM
        ).exists():
            raise AutomationAutonomyNotPiloted
    elif writing and grant.mode not in WRITING_MODES:
        raise AutomationSuggestOnly
    if not writing:
        # `suggest_only` exists to read the state it is proposing against, and
        # a window is about when an automation may act rather than when it may
        # look. Reading stops at the scope check above.
        return

    organization = Organization.objects.get(pk=context.organization_id)
    local_now = timezone.localtime(
        timezone.now(), ZoneInfo(organization.timezone or "UTC")
    )
    if not grant.within_window(local_now.time()):
        raise AutomationOutsideWindow(
            detail=(
                "Ten klucz działa między "
                f"{grant.window_start} a {grant.window_end} czasu klienta."
            )
        )
    if (
        payload_bytes is not None
        and grant.max_payload_bytes is not None
        and payload_bytes > grant.max_payload_bytes
    ):
        raise AutomationPayloadTooLarge
    if grant.max_changes_per_day is not None and writing and not publishing:
        since = timezone.now() - timedelta(days=1)
        written = PageVersion.all_objects.filter(
            organization_id=context.organization_id,
            created_by_credential=context.credential_id,
            created_at__gte=since,
        ).count() + ContentEntryVersion.all_objects.filter(
            organization_id=context.organization_id,
            created_by_credential=context.credential_id,
            created_at__gte=since,
        ).count()
        if written >= grant.max_changes_per_day:
            raise AutomationChangeLimitReached


def assert_links_within_grant(
    context: TenantContext,
    *,
    site_id: UUID,
    blocks: Any,
    base_blocks: Any,
    collection_id: UUID | None = None,
) -> None:
    """Refuses an automation's link to a host its grant does not name.

    A link is a recommendation made in the customer's name, so an automation
    links only to this site's own hostnames and to the grant's
    `allowed_link_hosts`, compared exactly after IDNA normalization: a listed
    host does not bring its subdomains. An empty list means internal links only.

    Only links the change introduces are checked. One already in the draft it
    replaces was put there by somebody else, and rewriting the paragraph around
    it is not a new recommendation.
    """
    if not _is_automation(context):
        return
    introduced = block_links(blocks)
    if not introduced:
        return
    kept = block_links(base_blocks)
    leaving = {
        href: host
        for href in introduced
        if href not in kept and (host := link_host(href)) is not None
    }
    if not leaving:
        return
    grant = assert_within_grant(context, site_id=site_id, collection_id=collection_id)
    own = Domain.all_objects.filter(
        organization_id=context.organization_id, site_id=site_id
    ).exclude(status=DomainStatus.RELEASED)
    allowed = _hostnames(list(own.values_list("hostname", flat=True)))
    allowed |= _hostnames(grant.allowed_link_hosts if grant else [])
    for href, host in leaving.items():
        if host not in allowed:
            raise AutomationLinkHostForbidden(
                detail=f"{introduced[href]}: grant nie pozwala linkować do {host}."
            )


def _hostnames(values: Any) -> set[str]:
    # A stored value that is not a list of hostnames names nothing, so it
    # allows nothing.
    found = set()
    for value in values if isinstance(values, list) else []:
        try:
            found.add(normalize_hostname(str(value)))
        except InvalidHostname:
            continue
    return found


#: Policies under which an automation may write a draft. `PROPOSED` allows the
#: draft and nothing further: turning it into what visitors see stays a
#: person's act, which is the whole point of the setting.
DRAFTABLE_POLICIES = frozenset({
    PageAutomationPolicy.AUTOMATED,
    PageAutomationPolicy.PROPOSED,
})


#: Page types an automation never writes, whatever its grant or the surface
#: policy says. A wrong sentence on a legal page or a price list is a different
#: kind of wrong from a clumsy blog post, and no mode buys past it.
PERSON_ONLY_PAGE_TYPES = frozenset({PageType.LEGAL})

#: Blocks that carry commitments to a customer's customers rather than prose.
PERSON_ONLY_BLOCK_TYPES = frozenset({"core.pricing"})


def _statements(blocks: Iterable[Any]) -> Counter[str]:
    """The words of every attributed statement, fingerprinted: a quote block's
    quote and attribution, each testimonial, each quote node in rich text.
    Anything else in those blocks (a layout, a title, a bound photo) is not
    somebody's words."""
    found: Counter[str] = Counter()

    def add(words: dict[str, Any]) -> None:
        found[canonical_json_hash({key: value for key, value in words.items() if value})] += 1

    for block in blocks:
        if not isinstance(block, dict) or not isinstance(block.get("data"), dict):
            continue
        data = block["data"]
        if block.get("block_type") == "core.quote":
            add({key: data.get(key) for key in ("quote", "author", "role", "context", "source")})
        if block.get("block_type") == "core.testimonials":
            for item in data.get("items") or []:
                if isinstance(item, dict):
                    add({key: item.get(key) for key in ("quote", "author", "role")})
        content = data.get("content")
        for node in content if isinstance(content, list) else []:
            if isinstance(node, dict) and node.get("type") == "quote":
                add({key: node.get(key) for key in ("content", "author", "source")})
    return found


def _catalogue_statements() -> Counter[str]:
    """Statements that ship in the page recipes (in the offered ones only
    [Uzupełnij: …] slots): a blueprint importing a recipe carries them in,
    which is the catalogue speaking, not the automation."""
    from .page_templates import page_template_catalog

    found: Counter[str] = Counter()
    for versions in page_template_catalog().templates.values():
        for template in versions.values():
            for blocks in (template.blocks, *template.localized_blocks.values()):
                for key in _statements(blocks):
                    found[key] = len(blocks) + 1  # as many as a page may hold
    return found


def assert_person_blocks(
    context: TenantContext,
    blocks: list[dict[str, Any]],
    previous: Callable[[], Iterable[Any]],
) -> None:
    """One check for every way blocks are written — page and entry drafts, and
    the change sets routed through them. `previous` is read only for an
    automation: the blocks of the draft being replaced.

    Pricing blocks an automation outright. Attributed statements only when
    their words are new: an automation may carry them over unchanged, drop
    them or import them with a recipe, but never put words into anyone's
    mouth (catalogue rule 4, docs/architecture/site-section-catalog.md), so
    a page with a quote stays open to it."""
    if not _is_automation(context):
        return
    if any(
        isinstance(block, dict) and block.get("block_type") in PERSON_ONLY_BLOCK_TYPES
        for block in blocks
    ):
        assert_person_required(context, "Cennik")
    if _statements(blocks) - _statements(previous()) - _catalogue_statements():
        assert_person_required(context, "Cytaty i opinie")


def assert_person_required(context: TenantContext, what: str) -> None:
    """Refuses an automation outright, with the reason in the message.

    These are the operations ADR-035 §4 keeps for a person no matter which mode
    the grant carries: domains, the main menu, legal pages, the price list,
    removals and anything site-wide. A grant is a limit on what an integration
    may do routinely, not a way of buying past the short list of things nobody
    wants a machine deciding alone.
    """
    if not _is_automation(context):
        return
    raise PersonRequired(detail=f"{what} wymaga decyzji człowieka.")


def assert_page_writable(
    page: Page,
    context: TenantContext,
    *,
    publishing: bool = False,
    payload_bytes: int | None = None,
) -> None:
    """Refuses an automated write the operator has not allowed, or that would
    land on a page a person currently has open."""
    if not _is_automation(context):
        return
    assert_within_grant(
        context,
        site_id=page.site_id,
        writing=True,
        publishing=publishing,
        payload_bytes=payload_bytes,
    )
    if page.page_type in PERSON_ONLY_PAGE_TYPES:
        assert_person_required(context, "Strona prawna")
    allowed = (
        {PageAutomationPolicy.AUTOMATED} if publishing else DRAFTABLE_POLICIES
    )
    if page.automation_policy not in allowed:
        raise PageAutomationForbidden
    if page.editing_locked_until is not None and page.editing_locked_until > timezone.now():
        raise PageEditingLocked(
            detail=(
                "Podstrona jest edytowana ręcznie do "
                f"{page.editing_locked_until.isoformat()}."
            )
        )


@transaction.atomic
def hold_page_editing_lock(*, page_id: UUID) -> Page:
    """Claims or extends the human editing lock. Called while the editor is
    open; lapses on its own, so a closed tab does not block the automation
    forever."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    page = (
        Page.all_objects.select_for_update()
        .filter(pk=page_id, organization_id=context.organization_id)
        .first()
    )
    if page is None:
        raise PageNotFound
    page.editing_locked_until = timezone.now() + timedelta(
        seconds=PAGE_EDITING_LOCK_TTL_SECONDS
    )
    page.editing_locked_by_id = context.actor_id
    page.save(update_fields=["editing_locked_until", "editing_locked_by", "updated_at"])
    return page


@transaction.atomic
def set_page_automation_policy(*, page_id: UUID, policy: str) -> Page:
    """Only a person changes this. The automation authenticates with a grant, and
    a grant that could widen its own scope would not be a limit at all."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        raise PageAutomationForbidden
    if policy not in PageAutomationPolicy.values:
        raise NavigationInvalidTree
    page = (
        Page.all_objects.select_for_update()
        .filter(pk=page_id, organization_id=context.organization_id)
        .first()
    )
    if page is None:
        raise PageNotFound
    page.automation_policy = policy
    page.save(update_fields=["automation_policy", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=PAGE_AUTOMATION_POLICY_SET,
        actor=User.objects.get(pk=context.actor_id),
        target_type="page",
        target_id=page.id,
        metadata={"automation_policy": policy},
    )
    return page


@transaction.atomic
def save_draft(
    *,
    page_id: UUID,
    expected_version: int,
    blocks: list[dict[str, Any]],
    media_asset_ids: list[UUID],
    idempotency_key: str,
    request_context: dict[str, Any] | None = None,
    page_presentation: dict[str, Any] | None = UNSET,
) -> MutationResult[PageVersion]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    normalized_blocks = [normalize_block(block) for block in blocks]
    for block in normalized_blocks:
        validate_site_block(
            block_type=block["block_type"],
            schema_version=block["schema_version"],
            data=block["data"],
        )
    assert_unique_anchors(normalized_blocks)
    assert_real_media_slots(organization_id=context.organization_id, blocks=normalized_blocks)
    if page_presentation is not UNSET:
        validate_page_presentation(page_presentation)
    # Images nested in block data (figures, galleries, blocks a change set
    # inserted) are referenced even when the client did not list them. A
    # client that already lists them all keeps the same hash.
    normalized_media_asset_ids = tuple(
        sorted(
            {*(UUID(str(asset_id)) for asset_id in media_asset_ids),
             *block_asset_ids(normalized_blocks)},
            key=str,
        )
    )
    request_payload: dict[str, Any] = {
        "page_id": str(page_id),
        "expected_version": expected_version,
        "blocks": normalized_blocks,
        "media_asset_ids": [str(asset_id) for asset_id in normalized_media_asset_ids],
    }
    if request_context is not None:
        request_payload["context"] = request_context
    if page_presentation is not UNSET:
        request_payload["page_presentation"] = page_presentation
    request_hash = canonical_json_hash(request_payload)
    existing = PageVersion.all_objects.filter(
        organization_id=context.organization_id,
        page_id=page_id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    try:
        page = (
            Page.all_objects.select_for_update()
            .select_related("site")
            .get(
                pk=page_id,
                organization_id=context.organization_id,
            )
        )
    except Page.DoesNotExist as error:
        raise PageNotFound from error
    # Checked here rather than in the view, so every channel that saves a draft
    # inherits it — the panel, the automation, and anything added later.
    assert_page_writable(
        page,
        context,
        payload_bytes=len(json.dumps(blocks, ensure_ascii=False, separators=(",", ":"))),
    )
    assert_person_blocks(
        context,
        blocks,
        lambda: PageBlock.all_objects.filter(
            organization_id=context.organization_id, page_version_id=page.current_draft_id
        )
        .order_by("position")
        .values("block_type", "data"),
    )
    assert_links_within_grant(
        context,
        site_id=page.site_id,
        blocks=normalized_blocks,
        base_blocks=PageBlock.all_objects.filter(
            organization_id=context.organization_id,
            page_version_id=page.current_draft_id,
        ).values("data"),
    )
    existing = PageVersion.all_objects.filter(
        organization_id=context.organization_id,
        page_id=page.id,
        created_by_id=context.actor_id,
        idempotency_key=normalized_key,
    ).first()
    if existing is not None:
        return MutationResult(_same_request(existing, request_hash), False)
    if page.version != expected_version:
        raise DraftVersionConflict
    if page_presentation is UNSET:
        page_presentation = (
            PageVersion.all_objects.filter(
                pk=page.current_draft_id, organization_id=context.organization_id
            )
            .values_list("presentation", flat=True)
            .first()
            if page.current_draft_id is not None
            else None
        )
    content_hash = canonical_json_hash({
        "blocks": normalized_blocks,
        "media_asset_ids": [str(asset_id) for asset_id in normalized_media_asset_ids],
        **({"page_presentation": page_presentation} if page_presentation is not None else {}),
    })

    actor = User.objects.get(pk=context.actor_id)
    version = PageVersion.all_objects.create(
        organization_id=context.organization_id,
        page=page,
        number=expected_version + 1,
        created_by=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
        content_hash=content_hash,
        created_by_credential=context.credential_id if _is_automation(context) else None,
        presentation=page_presentation,
    )
    PageBlock.all_objects.bulk_create([
        PageBlock(
            organization_id=context.organization_id,
            page_version=version,
            position=position,
            block_type=block["block_type"],
            schema_version=block["schema_version"],
            data=block["data"],
            decoration=block.get("decoration"),
            presentation=block.get("presentation"),
        )
        for position, block in enumerate(normalized_blocks)
    ])
    try:
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=PAGE_VERSION_REFERENCE_OWNER,
            owner_id=version.id,
            resource_ids=normalized_media_asset_ids,
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error
    updated = Page.all_objects.filter(
        pk=page.id,
        organization_id=context.organization_id,
        version=expected_version,
    ).update(
        version=version.number,
        current_draft=version,
        updated_at=timezone.now(),
    )
    if updated != 1:
        raise DraftVersionConflict
    emit_draft_saved_event(
        context=context,
        event_type=PAGE_DRAFT_SAVED_EVENT,
        resource_type="site_page",
        resource_id=page.id,
        version=version.number,
    )
    record_audit(
        organization=page.site.organization,
        action=PAGE_DRAFT_SAVED,
        actor=actor,
        target_type="page_version",
        target_id=version.id,
        metadata={
            "site_id": str(page.site_id),
            "page_id": str(page.id),
            "version": version.number,
            "block_count": len(normalized_blocks),
            "media_asset_count": len(normalized_media_asset_ids),
            "content_hash": version.content_hash,
        },
    )
    return MutationResult(version, True)


@transaction.atomic
def import_page_template(
    *,
    page_id: UUID,
    template_id: str,
    template_version: int,
    expected_version: int,
    idempotency_key: str,
    text_values: dict[str, str] | None = None,
    locale: str = "pl",
) -> MutationResult[PageVersion]:
    from .page_templates import page_template_catalog

    authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    template = page_template_catalog().get(
        template_id=template_id,
        version=template_version,
    )
    for entitlement in template.required_entitlements:
        authorize_entitled(SITE_CONTENT_EDIT, entitlement)
    if locale not in ("pl", "en"):
        raise ValidationError({"locale": "Unsupported template locale"})
    blocks = template.draft_blocks(locale)
    request_context: dict[str, Any] = {
        "operation": "page_template_import",
        "template_id": template.id,
        "template_version": template.version,
    }
    if locale != "pl":
        request_context["locale"] = locale
    if text_values is not None:
        from .blueprints import render_slots

        blocks = render_slots(template, text_values)
        request_context["text_values"] = text_values
    materializations = []
    try:
        for medium in template.media:
            materializations.append(
                materialize_approved_media_asset(
                    source_key=(
                        "template:"
                        + hashlib.sha256(
                            (
                                f"{template.id}:{template.version}:"
                                f"{medium.id}:{medium.sha256}"
                            ).encode()
                        ).hexdigest()
                    ),
                    filename=medium.filename,
                    content_type=medium.content_type,
                    content=medium.read(),
                    ai_origin="generated" if medium.ai_generated else "none",
                )
            )
        template.bind_media(
            blocks,
            {medium.id: str(item.asset.id)
             for medium, item in zip(template.media, materializations, strict=True)},
            locale,
        )
        result = save_draft(
            page_id=page_id,
            expected_version=expected_version,
            blocks=blocks,
            media_asset_ids=[item.asset.id for item in materializations],
            idempotency_key=idempotency_key,
            request_context=request_context,
            # A recipe without its own page presentation keeps the current one.
            **(
                {"page_presentation": template.page_presentation}
                if template.page_presentation is not None
                else {}
            ),
        )
        if result.created:
            context = require_tenant_context()
            record_audit(
                organization=Organization.objects.get(pk=context.organization_id),
                action=PAGE_TEMPLATE_IMPORTED,
                actor=User.objects.get(pk=context.actor_id),
                target_type="page_version",
                target_id=result.value.id,
                metadata={
                    "page_id": str(page_id),
                    "template_id": template.id,
                    "template_version": template.version,
                    "media_asset_count": len(materializations),
                },
            )
    except Exception:
        for item in materializations:
            if item.created:
                discard_approved_media_asset_objects(asset=item.asset)
        raise
    return result


def list_page_translations(*, page_id: UUID) -> PageTranslations:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    try:
        page = Page.all_objects.select_related("site").get(
            pk=page_id,
            organization_id=context.organization_id,
        )
    except Page.DoesNotExist as error:
        raise PageNotFound from error
    translations = tuple(
        PageTranslation.all_objects.filter(
            organization_id=context.organization_id,
            page_id=page.id,
        )
        .select_related("site")
        .order_by("locale")
    )
    return PageTranslations(page, _supported_locales(), translations)


@transaction.atomic
def save_page_translation(
    *,
    page_id: UUID,
    locale: str,
    expected_version: int,
    slug: str,
    title: str,
    description: str,
    social_title: str,
    social_description: str,
    allow_title_fallback: bool,
    allow_description_fallback: bool,
    allow_social_title_fallback: bool,
    allow_social_description_fallback: bool,
    idempotency_key: str,
) -> MutationResult[PageTranslation]:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    normalized_locale = locale.strip().lower()
    if normalized_locale not in _supported_locales():
        raise UnsupportedSiteLocale
    normalized_key = _idempotency_key(idempotency_key)
    values: dict[str, str | bool] = {
        "slug": slug.strip().lower(),
        "title": title.strip(),
        "description": description.strip(),
        "social_title": social_title.strip(),
        "social_description": social_description.strip(),
        "allow_title_fallback": allow_title_fallback,
        "allow_description_fallback": allow_description_fallback,
        "allow_social_title_fallback": allow_social_title_fallback,
        "allow_social_description_fallback": allow_social_description_fallback,
    }
    request_hash = canonical_json_hash({
        "page_id": str(page_id),
        "locale": normalized_locale,
        "expected_version": expected_version,
        **values,
    })
    try:
        page = (
            Page.all_objects.select_for_update()
            .select_related("site__organization")
            .get(pk=page_id, organization_id=context.organization_id)
        )
    except Page.DoesNotExist as error:
        raise PageNotFound from error
    site = Site.all_objects.select_for_update().get(
        pk=page.site_id,
        organization_id=context.organization_id,
    )
    if site.default_locale not in _supported_locales():
        raise UnsupportedSiteLocale
    if normalized_locale == site.default_locale and any((
        allow_title_fallback,
        allow_description_fallback,
        allow_social_title_fallback,
        allow_social_description_fallback,
    )):
        raise TranslationFallbackConflict

    translation = (
        PageTranslation.all_objects.select_for_update()
        .filter(
            organization_id=context.organization_id,
            page_id=page.id,
            locale=normalized_locale,
        )
        .first()
    )
    if translation is not None:
        receipt = PageTranslationMutation.all_objects.filter(
            organization_id=context.organization_id,
            translation_id=translation.id,
            created_by_id=context.actor_id,
            idempotency_key=normalized_key,
        ).first()
        if receipt is not None:
            if receipt.request_hash != request_hash:
                raise SitesIdempotencyConflict
            return MutationResult(translation, False)
    if translation is None and expected_version != 0:
        raise TranslationVersionConflict
    if translation is not None and translation.version != expected_version:
        raise TranslationVersionConflict
    if (
        translation is not None
        and translation.slug_locked_at is not None
        and translation.slug != values["slug"]
    ):
        raise TranslationSlugLocked
    duplicate_slug = PageTranslation.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        locale=normalized_locale,
        slug=values["slug"],
    )
    if translation is not None:
        duplicate_slug = duplicate_slug.exclude(pk=translation.id)
    if duplicate_slug.exists():
        raise TranslationSlugConflict

    actor = User.objects.get(pk=context.actor_id)
    resulting_version = expected_version + 1
    if translation is None:
        translation = PageTranslation.all_objects.create(
            organization_id=context.organization_id,
            site=site,
            page=page,
            locale=normalized_locale,
            version=resulting_version,
            **values,
        )
    else:
        for field, value in values.items():
            setattr(translation, field, value)
        translation.version = resulting_version
        translation.save(update_fields=[*values.keys(), "version", "updated_at"])
    PageTranslationMutation.all_objects.create(
        organization_id=context.organization_id,
        translation=translation,
        created_by=actor,
        idempotency_key=normalized_key,
        request_hash=request_hash,
        resulting_version=resulting_version,
    )
    record_audit(
        organization=page.site.organization,
        action=PAGE_TRANSLATION_SAVED,
        actor=actor,
        target_type="page_translation",
        target_id=translation.id,
        metadata={
            "site_id": str(site.id),
            "page_id": str(page.id),
            "locale": normalized_locale,
            "version": resulting_version,
            "fallback_fields": [
                field.removeprefix("allow_").removesuffix("_fallback")
                for field, value in values.items()
                if field.startswith("allow_") and value
            ],
        },
    )
    return MutationResult(translation, True)


def get_site_localization_report(*, site_id: UUID) -> SiteLocalizationReport:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    try:
        site = Site.all_objects.get(
            pk=site_id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    supported_locales = _supported_locales()
    if site.default_locale not in supported_locales:
        raise UnsupportedSiteLocale
    pages = list(
        Page.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
        ).order_by("key", "id")
    )
    translations = list(
        PageTranslation.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
            locale__in=supported_locales,
        ).select_related("site")
    )
    return build_localization_report(
        site=site,
        pages=pages,
        translations=translations,
        supported_locales=supported_locales,
    )


def list_site_publications(
    *,
    site_id: UUID,
    cursor: UUID | None,
    limit: int,
) -> tuple[list[Publication], UUID | None]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    if not Site.all_objects.filter(
        pk=site_id,
        organization_id=context.organization_id,
    ).exists():
        raise SiteNotFound
    queryset = Publication.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
    ).select_related("created_by", "source_publication")
    if cursor is not None:
        cursor_publication = queryset.filter(pk=cursor).first()
        if cursor_publication is None:
            raise SitePublicationNotFound
        queryset = queryset.filter(sequence__lt=cursor_publication.sequence)
    rows = list(queryset.order_by("-sequence")[: limit + 1])
    next_cursor = rows[limit - 1].id if len(rows) > limit else None
    return rows[:limit], next_cursor


def get_site_navigation(*, site_id: UUID) -> SiteNavigation:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    site = Site.all_objects.filter(
        pk=site_id,
        organization_id=context.organization_id,
    ).first()
    if site is None:
        raise SiteNotFound
    items = tuple(
        NavigationItem.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site_id,
        ).order_by("position", "id")
    )
    return SiteNavigation(site=site, items=items)


@transaction.atomic
def save_site_navigation(
    *,
    site_id: UUID,
    expected_version: int,
    items: list[dict[str, Any]],
) -> SiteNavigation:
    """Replaces the whole menu.

    Navigation is one object even though it is stored as rows: moving an entry
    renumbers its siblings, so a per-entry API would let two editors interleave
    partial moves into a tree neither of them intended. The version guards the
    menu as a whole.
    """
    # The menu is what a visitor is steered by; an integration able to rewrite
    # it could route a customer's traffic wherever it liked.
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Główna nawigacja")
    site = (
        Site.all_objects.select_for_update()
        .filter(pk=site_id, organization_id=context.organization_id)
        .first()
    )
    if site is None:
        raise SiteNotFound
    if site.navigation_version != expected_version:
        raise NavigationVersionConflict

    page_ids = [UUID(str(item["page_id"])) for item in items]
    if len(set(page_ids)) != len(page_ids):
        raise NavigationInvalidTree
    known_pages = set(
        Page.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site_id,
            pk__in=page_ids,
        ).values_list("pk", flat=True)
    )
    if known_pages != set(page_ids):
        raise NavigationInvalidTree

    parents = {
        UUID(str(item["page_id"])): (
            UUID(str(item["parent_page_id"]))
            if item.get("parent_page_id") is not None
            else None
        )
        for item in items
    }
    for page_id, parent_id in parents.items():
        if parent_id is None:
            continue
        if parent_id not in parents or parent_id == page_id:
            raise NavigationInvalidTree
        # One level of nesting, matching what the editor and the public menu
        # render. A deeper tree would publish links the renderer cannot show.
        if parents[parent_id] is not None:
            raise NavigationInvalidTree

    NavigationItem.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
    ).delete()
    created: dict[UUID, NavigationItem] = {}
    for position, item in enumerate(items):
        page_id = UUID(str(item["page_id"]))
        if parents[page_id] is not None:
            continue
        created[page_id] = NavigationItem.all_objects.create(
            organization_id=context.organization_id,
            site_id=site_id,
            page_id=page_id,
            parent=None,
            position=position,
            visible=bool(item.get("visible", True)),
        )
    for position, item in enumerate(items):
        page_id = UUID(str(item["page_id"]))
        parent_page_id = parents[page_id]
        if parent_page_id is None:
            continue
        created[page_id] = NavigationItem.all_objects.create(
            organization_id=context.organization_id,
            site_id=site_id,
            page_id=page_id,
            parent=created[parent_page_id],
            position=position,
            visible=bool(item.get("visible", True)),
        )

    site.navigation_version += 1
    site.save(update_fields=["navigation_version", "updated_at"])
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=SITE_NAVIGATION_SAVED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="site",
        target_id=site.id,
        metadata={
            "navigation_version": site.navigation_version,
            "items": len(items),
        },
    )
    return SiteNavigation(
        site=site,
        items=tuple(
            NavigationItem.all_objects.filter(
                organization_id=context.organization_id,
                site_id=site_id,
            ).order_by("position", "id")
        ),
    )


@transaction.atomic
def publish_site(*, site_id: UUID, idempotency_key: str) -> SitePublication:
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    try:
        initial_site = Site.all_objects.get(
            pk=site_id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    existing = _existing_site_publication(
        context=context,
        site_id=site_id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing

    pages = list(
        Page.all_objects.select_for_update(of=("self",))
        .select_related("current_draft")
        .filter(
            organization_id=context.organization_id,
            site_id=initial_site.id,
        )
        .order_by("id")
    )
    # Publishing a whole site is the bulk operation ADR-035 §4 keeps for a
    # person: it ships every page at once, including ones nobody looked at.
    assert_person_required(context, "Publikacja całej witryny")
    if _is_automation(context) and any(
        page.automation_policy == PageAutomationPolicy.PROPOSED for page in pages
    ):
        raise PageAutomationForbidden(
            detail=(
                "Witryna zawiera propozycje czekające na akceptację; "
                "publikuje je człowiek."
            )
        )
    from .models import ContentProposal

    current_versions = {page.id: page.version for page in pages}
    if any(current_versions.get(proposal.resource_id) == proposal.version
           for proposal in ContentProposal.all_objects.filter(
               organization_id=context.organization_id, resource_type="site_page",
               resource_id__in=current_versions, review_state="pending", metadata_pending=True,
           )):
        raise AutomationApprovalRequired(
            detail="Najpierw zaakceptuj lub odrzuć propozycję metadanych."
        )
    site = Site.all_objects.select_for_update().get(
        pk=initial_site.id,
        organization_id=context.organization_id,
    )
    existing = _existing_site_publication(
        context=context,
        site_id=site.id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing
    current_page_ids = tuple(
        Page.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
        )
        .order_by("id")
        .values_list("id", flat=True)
    )
    if current_page_ids != tuple(page.id for page in pages):
        raise SitePublicationConflict
    if not pages or any(page.current_draft_id is None for page in pages):
        raise SitePublicationNotReady

    translations = list(
        PageTranslation.all_objects.select_for_update()
        .filter(
            organization_id=context.organization_id,
            site_id=site.id,
            locale__in=_supported_locales(),
        )
        .select_related("site")
        .order_by("page_id", "locale")
    )
    localization = build_localization_report(
        site=site,
        pages=pages,
        translations=translations,
        supported_locales=_supported_locales(),
    )
    if not localization.ready_to_publish:
        raise SitePublicationNotReady

    version_ids = tuple(_current_version_id(page) for page in pages)
    blocks = list(
        PageBlock.all_objects.filter(
            organization_id=context.organization_id,
            page_version_id__in=version_ids,
        ).order_by("page_version_id", "position")
    )
    for page in pages:
        validate_page_presentation(page.current_draft.presentation if page.current_draft else None)
    blocks_by_version: dict[UUID, list[PageBlock]] = {}
    for block in blocks:
        validate_decoration(block.decoration)
        validate_presentation(block.presentation)
        validate_site_block(
            block_type=block.block_type,
            schema_version=block.schema_version,
            data=block.data,
        )
        blocks_by_version.setdefault(block.page_version_id, []).append(block)
    # Drafts saved before the guard existed are checked again on the way out.
    assert_real_media_slots(
        organization_id=context.organization_id,
        blocks=[{"block_type": block.block_type, "data": block.data} for block in blocks],
    )

    page_media_ids = {
        page.id: _page_version_media_asset_ids(
            context=context,
            version_id=_current_version_id(page),
        )
        for page in pages
    }
    all_media_ids = tuple(
        sorted(
            {asset_id for asset_ids in page_media_ids.values() for asset_id in asset_ids},
            key=str,
        )
    )
    snapshot = _publication_snapshot(
        site=site,
        pages=pages,
        blocks_by_version=blocks_by_version,
        localization=localization,
        page_media_ids=page_media_ids,
        navigation=_navigation_snapshot(
            site=site,
            organization_id=context.organization_id,
            published_page_ids={page.id for page in pages},
        ),
    )
    previous = (
        Publication.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
        )
        .order_by("-sequence")
        .first()
    )
    actor = User.objects.get(pk=context.actor_id)
    publication = Publication.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        sequence=(previous.sequence + 1 if previous is not None else 1),
        snapshot_schema_version=PUBLICATION_SNAPSHOT_SCHEMA_VERSION,
        snapshot=snapshot,
        snapshot_hash="",
        created_by=actor,
        idempotency_key=normalized_key,
    )
    try:
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=PUBLICATION_REFERENCE_OWNER,
            owner_id=publication.id,
            resource_ids=all_media_ids,
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error

    published_at = timezone.now()
    published_translation_ids = [
        locale.translation_id
        for page in localization.pages
        for locale in page.locales
        if locale.complete and locale.translation_id is not None
    ]
    PageTranslation.all_objects.filter(
        organization_id=context.organization_id,
        id__in=published_translation_ids,
        slug_locked_at__isnull=True,
    ).update(slug_locked_at=published_at, updated_at=published_at)
    Site.all_objects.filter(
        pk=site.id,
        organization_id=context.organization_id,
    ).update(current_publication=publication, updated_at=published_at)
    from .tls import invalidate_site_tls_decisions

    transaction.on_commit(lambda: invalidate_site_tls_decisions(site_id=site.id))

    active_correlation_id = correlation_id.get()
    event = SiteOutboxEvent.all_objects.create(
        organization_id=context.organization_id,
        publication=publication,
        event_type=SITE_PUBLISHED_EVENT,
        version=1,
        actor=actor,
        correlation_id=UUID(active_correlation_id) if active_correlation_id else uuid7(),
        causation_id=f"sites-publish:{publication.id}",
        payload={
            "site_id": str(site.id),
            "publication_id": str(publication.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
        },
    )
    _schedule_site_outbox_delivery(event)
    record_audit(
        organization=site.organization,
        action=SITE_PUBLISHED,
        actor=actor,
        target_type="publication",
        target_id=publication.id,
        metadata={
            "site_id": str(site.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
            "page_count": len(pages),
            "media_asset_count": len(all_media_ids),
        },
    )
    return SitePublication(publication, True)


@transaction.atomic
def rollback_site(
    *,
    site_id: UUID,
    publication_id: UUID,
    idempotency_key: str,
) -> SitePublication:
    context = authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    normalized_key = _idempotency_key(idempotency_key)
    existing = _existing_site_rollback(
        context=context,
        site_id=site_id,
        source_publication_id=publication_id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing

    try:
        site = Site.all_objects.select_for_update().get(
            pk=site_id,
            organization_id=context.organization_id,
        )
        source = Publication.all_objects.get(
            pk=publication_id,
            site_id=site.id,
            organization_id=context.organization_id,
        )
    except Site.DoesNotExist as error:
        raise SiteNotFound from error
    except Publication.DoesNotExist as error:
        raise SitePublicationNotFound from error
    existing = _existing_site_rollback(
        context=context,
        site_id=site.id,
        source_publication_id=source.id,
        idempotency_key=normalized_key,
    )
    if existing is not None:
        return existing
    if site.current_publication_id == source.id:
        raise SitePublicationAlreadyCurrent
    # A snapshot from before the guard may carry AI media in an evidence slot.
    assert_real_media_slots(
        organization_id=context.organization_id,
        blocks=[
            block for page in source.snapshot.get("pages", []) for block in page.get("blocks", [])
        ],
    )

    previous = (
        Publication.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
        )
        .order_by("-sequence")
        .first()
    )
    if previous is None:
        raise SitePublicationNotFound
    actor = User.objects.get(pk=context.actor_id)
    publication = Publication.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        sequence=previous.sequence + 1,
        snapshot_schema_version=source.snapshot_schema_version,
        snapshot=source.snapshot,
        snapshot_hash="",
        created_by=actor,
        source_publication=source,
        idempotency_key=normalized_key,
    )
    try:
        media_ids = copy_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=PUBLICATION_REFERENCE_OWNER,
            source_owner_id=source.id,
            target_owner_id=publication.id,
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error

    activated_at = timezone.now()
    Site.all_objects.filter(
        pk=site.id,
        organization_id=context.organization_id,
    ).update(current_publication=publication, updated_at=activated_at)
    from .tls import invalidate_site_tls_decisions

    transaction.on_commit(lambda: invalidate_site_tls_decisions(site_id=site.id))
    active_correlation_id = correlation_id.get()
    event = SiteOutboxEvent.all_objects.create(
        organization_id=context.organization_id,
        publication=publication,
        event_type=SITE_ROLLED_BACK_EVENT,
        version=1,
        actor=actor,
        correlation_id=UUID(active_correlation_id) if active_correlation_id else uuid7(),
        causation_id=f"sites-rollback:{publication.id}",
        payload={
            "site_id": str(site.id),
            "publication_id": str(publication.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
            "source_publication_id": str(source.id),
        },
    )
    _schedule_site_outbox_delivery(event)
    record_audit(
        organization=site.organization,
        action=SITE_ROLLED_BACK,
        actor=actor,
        target_type="publication",
        target_id=publication.id,
        metadata={
            "site_id": str(site.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
            "source_publication_id": str(source.id),
            "media_asset_count": len(media_ids),
        },
    )
    return SitePublication(publication, True)


def emit_draft_saved_event(
    *,
    context: TenantContext,
    event_type: str,
    resource_type: str,
    resource_id: UUID,
    version: int,
) -> None:
    """Tells a subscriber that a proposal landed.

    Only for automation-authored drafts. A person saving their own work does
    not need to be told about it, and an operator's queue is meant to show what
    arrived while they were not looking.
    """
    if not _is_automation(context):
        return
    active_correlation_id = correlation_id.get()
    event = SiteOutboxEvent.all_objects.create(
        organization_id=context.organization_id,
        event_type=event_type,
        version=1,
        actor_id=context.actor_id,
        correlation_id=(
            UUID(active_correlation_id) if active_correlation_id else uuid7()
        ),
        causation_id=f"sites-draft:{resource_id}:{version}",
        payload={
            "resource_type": resource_type,
            "resource_id": str(resource_id),
            "version": version,
            "credential_id": str(context.credential_id) if context.credential_id else "",
        },
    )
    _schedule_site_outbox_delivery(event)


@transaction.atomic
def revoke_automation_grant(*, grant_id: UUID, reason: str) -> ContentAutomationGrant:
    """Stops a credential now, without deleting the row.

    The emergency stop of ADR-035 §4: the grant stays for the audit trail that
    the incident will need, and the revocation reaches a subscriber so the
    connector learns it has been cut off rather than discovering it one 403 at
    a time.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Odwołanie grantu")
    grant = (
        ContentAutomationGrant.all_objects.select_for_update()
        .filter(pk=grant_id, organization_id=context.organization_id)
        .first()
    )
    if grant is None:
        raise AutomationGrantMissing
    if grant.revoked_at is None:
        grant.revoked_at = timezone.now()
        grant.save(update_fields=["revoked_at", "updated_at"])
    active_correlation_id = correlation_id.get()
    event = SiteOutboxEvent.all_objects.create(
        organization_id=context.organization_id,
        event_type=GRANT_REVOKED_EVENT,
        version=1,
        actor_id=context.actor_id,
        correlation_id=(
            UUID(active_correlation_id) if active_correlation_id else uuid7()
        ),
        causation_id=f"sites-grant-revoked:{grant.id}",
        payload={
            "grant_id": str(grant.id),
            "credential_id": str(grant.credential_id),
            "mode": grant.mode,
        },
    )
    _schedule_site_outbox_delivery(event)
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=GRANT_REVOKED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="content_automation_grant",
        target_id=grant.id,
        metadata={"reason": reason[:500]},
    )
    return grant


def _schedule_site_outbox_delivery(event: SiteOutboxEvent) -> None:
    OUTBOX_EVENTS.labels(event_type=event.event_type).inc()
    task_contract = issue_tenant_task_contract(causation_id=f"sites-outbox:{event.id}")

    def enqueue_outbox() -> None:
        from .tasks import publish_site_outbox_event_task

        publish_site_outbox_event_task.delay(str(event.id), task_contract)

    transaction.on_commit(enqueue_outbox, robust=True)


def _existing_site_publication(
    *,
    context: TenantContext,
    site_id: UUID,
    idempotency_key: str,
) -> SitePublication | None:
    publication = Publication.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
        created_by_id=context.actor_id,
        idempotency_key=idempotency_key,
    ).first()
    if publication is None:
        return None
    pending_event = SiteOutboxEvent.all_objects.filter(
        organization_id=context.organization_id,
        publication_id=publication.id,
        published_at__isnull=True,
    ).first()
    if pending_event is not None:
        _schedule_site_outbox_delivery(pending_event)
    return SitePublication(publication, False)


def _existing_site_rollback(
    *,
    context: TenantContext,
    site_id: UUID,
    source_publication_id: UUID,
    idempotency_key: str,
) -> SitePublication | None:
    publication = Publication.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site_id,
        created_by_id=context.actor_id,
        idempotency_key=idempotency_key,
    ).first()
    if publication is None:
        return None
    if publication.source_publication_id != source_publication_id:
        raise SitesIdempotencyConflict
    pending_event = SiteOutboxEvent.all_objects.filter(
        organization_id=context.organization_id,
        publication_id=publication.id,
        published_at__isnull=True,
    ).first()
    if pending_event is not None:
        _schedule_site_outbox_delivery(pending_event)
    return SitePublication(publication, False)


@transaction.atomic
def publish_site_outbox_event(*, event_id: UUID) -> SiteOutboxEvent | None:
    context = require_tenant_context()
    event = (
        SiteOutboxEvent.all_objects.select_for_update()
        .filter(
            pk=event_id,
            organization_id=context.organization_id,
        )
        .first()
    )
    if event is None or event.published_at is not None:
        return event
    dispatch_domain_event(
        context=context,
        event=DomainEvent(
            id=event.id,
            event_type=event.event_type,
            version=event.version,
            organization_id=event.organization_id,
            actor_id=event.actor_id,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload=event.payload,
        ),
    )
    event.published_at = timezone.now()
    event.save(update_fields=["published_at"])
    return event


def _idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 120:
        raise SitesIdempotencyConflict
    return normalized


def _quota_idempotency_key(actor_id: UUID, idempotency_key: str) -> str:
    digest = canonical_json_hash({
        "endpoint": "sites.create",
        "actor_id": str(actor_id),
        "key": idempotency_key,
    })
    return f"sites-create:{digest}"


def _supported_locales() -> tuple[str, ...]:
    return tuple(settings.SITES_SUPPORTED_LOCALES)


def _page_version_media_asset_ids(
    *,
    context: TenantContext,
    version_id: UUID,
) -> tuple[UUID, ...]:
    return list_resource_reference_ids(
        context=context,
        resource_type=MEDIA_ASSET_RESOURCE_TYPE,
        owner_type=PAGE_VERSION_REFERENCE_OWNER,
        owner_id=version_id,
    )


def _navigation_snapshot(
    *,
    site: Site,
    organization_id: UUID,
    published_page_ids: set[UUID],
) -> list[dict[str, Any]]:
    """The menu as published: hidden entries and entries pointing at pages that
    did not make this publication are dropped, so the snapshot never links to
    something the renderer cannot show. A child whose parent was dropped is
    dropped with it rather than silently promoted to the top level."""
    items = list(
        NavigationItem.all_objects.filter(
            organization_id=organization_id,
            site_id=site.id,
            visible=True,
        ).order_by("position", "id")
    )
    kept = {
        item.id: item
        for item in items
        if item.page_id in published_page_ids
    }

    def reachable(item: NavigationItem) -> bool:
        seen: set[UUID] = set()
        current = item
        while current.parent_id is not None:
            if current.parent_id in seen or current.parent_id not in kept:
                return False
            seen.add(current.parent_id)
            current = kept[current.parent_id]
        return True

    # Addressed by page, not by navigation-item id: the public payload and the
    # panel both speak in pages, and mixing the two id spaces silently drops
    # every nested entry when the renderer tries to match them up.
    entries: list[dict[str, Any]] = [
        {
            "page_id": str(item.page_id),
            "parent_page_id": (
                str(kept[item.parent_id].page_id) if item.parent_id else None
            ),
            "position": item.position,
        }
        for item in items
        if item.id in kept and reachable(item)
    ]
    # A collection carries its own title and address because it has no page in
    # the snapshot to look them up from. Older snapshots simply have no entries
    # of this shape, so the renderer's page lookup keeps working unchanged.
    position = len(entries)
    for collection in ContentCollection.all_objects.filter(
        organization_id=organization_id,
        site_id=site.id,
        show_in_navigation=True,
    ).order_by("base_path"):
        entries.append({
            "page_id": None,
            "parent_page_id": None,
            "position": position,
            "collection_id": str(collection.id),
            "title": collection.name,
            "path": "/" + collection.base_path + "/",
        })
        position += 1
    return entries


def _publication_snapshot(
    *,
    site: Site,
    pages: list[Page],
    blocks_by_version: dict[UUID, list[PageBlock]],
    localization: SiteLocalizationReport,
    page_media_ids: dict[UUID, tuple[UUID, ...]],
    navigation: list[dict[str, Any]],
) -> dict[str, Any]:
    from .appearance import appearance_snapshot

    appearance = appearance_snapshot(site)
    localization_by_page = {page.page.id: page for page in localization.pages}
    return {
        "site_id": str(site.id),
        "site_slug": site.slug,
        "default_locale": site.default_locale,
        "design_tokens": appearance["designTokens"] if appearance else DEFAULT_DESIGN_TOKENS,
        **({"appearance": appearance} if appearance else {}),
        "navigation": navigation,
        # Redirects travel with the publication for the same reason pages do:
        # what a visitor gets has to come from the snapshot, not from a working
        # copy somebody is halfway through editing.
        "redirects": [
            {
                "from_path": redirect.from_path,
                "to_path": redirect.to_path,
                "locale": redirect.locale,
            }
            for redirect in SiteRedirect.all_objects.filter(
                organization_id=site.organization_id, site_id=site.id
            ).order_by("from_path")
        ],
        "pages": [
            {
                "page_id": str(page.id),
                "key": page.key,
                # Optional for backward compatibility with existing snapshots.
                # The public root uses it to choose the intended home page.
                "page_type": page.page_type,
                "version_id": str(_current_version_id(page)),
                "version": page.current_draft.number if page.current_draft else 0,
                "blocks": [
                    stored_block_payload(block)
                    for block in blocks_by_version.get(_current_version_id(page), [])
                ],
                "media_asset_ids": [str(asset_id) for asset_id in page_media_ids.get(page.id, ())],
                # Optional like `appearance`: snapshots without it keep their meaning.
                **(
                    {"page_presentation": page.current_draft.presentation}
                    if page.current_draft and page.current_draft.presentation is not None
                    else {}
                ),
                "locales": [
                    {
                        "locale": locale.locale,
                        "translation_id": (
                            str(locale.translation_id)
                            if locale.translation_id is not None
                            else None
                        ),
                        "version": locale.version,
                        "slug": locale.slug,
                        "path": locale.path,
                        "canonical_path": locale.canonical_path,
                        "title": locale.title,
                        "description": locale.description,
                        "social_title": locale.social_title,
                        "social_description": locale.social_description,
                        "fallback_fields": list(locale.fallback_fields),
                    }
                    for locale in localization_by_page[page.id].locales
                    if locale.complete
                ],
                "hreflang": localization_by_page[page.id].hreflang,
                "x_default": localization_by_page[page.id].x_default,
            }
            for page in pages
        ],
    }


def _current_version_id(page: Page) -> UUID:
    if page.current_draft_id is None:
        raise SitePublicationNotReady
    return page.current_draft_id


def _same_request[T: Site | Page | PageVersion](value: T, request_hash: str) -> T:
    if value.request_hash != request_hash:
        raise SitesIdempotencyConflict
    return value


@transaction.atomic
def set_site_purpose(*, site_id: UUID, purpose: str) -> Site:
    """Marks what a site is for.

    Session-only at the route, and refused for a credential here as well: the
    label is what inventory and SeoContentRank reason about, so an integration
    able to relabel its own surface could describe a customer's site as ours.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        raise PageAutomationForbidden
    if purpose not in SitePurpose.values:
        raise SiteInvalidPurpose
    site = (
        Site.all_objects.select_for_update()
        .filter(pk=site_id, organization_id=context.organization_id)
        .first()
    )
    if site is None:
        raise SiteNotFound
    organization = Organization.objects.get(pk=context.organization_id)
    platform_workspace = organization.workspace_kind == WorkspaceKind.PLATFORM
    platform_purpose = purpose in {
        SitePurpose.PLATFORM_MARKETING,
        SitePurpose.PLATFORM_BLOG,
    }
    if platform_purpose != platform_workspace:
        # The label has to agree with whose workspace this is, in both
        # directions: a customer cannot claim to be the platform, and the
        # platform's own site is not a customer's.
        raise SitePurposeMismatch
    if site.purpose != purpose:
        site.purpose = purpose
        site.save(update_fields=["purpose", "updated_at"])
        record_audit(
            organization=organization,
            action=SITE_PURPOSE_SET,
            actor=User.objects.get(pk=context.actor_id),
            target_type="site",
            target_id=site.id,
            metadata={"purpose": purpose},
        )
    return site


@transaction.atomic
def set_page_type(*, page_id: UUID, page_type: str) -> Page:
    """Marks what kind of page this is.

    A person's call, like the automation policy: the type is what an optimiser
    reasons about, so a credential able to set it could re-describe the page it
    is about to rewrite.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        raise PageAutomationForbidden
    if page_type not in PageType.values:
        raise PageInvalidType
    page = (
        Page.all_objects.select_for_update(of=("self",))
        .select_related("current_draft")
        .filter(pk=page_id, organization_id=context.organization_id)
        .first()
    )
    if page is None:
        raise PageNotFound
    if page.page_type != page_type:
        page.page_type = page_type
        page.save(update_fields=["page_type", "updated_at"])
        record_audit(
            organization=Organization.objects.get(pk=context.organization_id),
            action=PAGE_TYPE_SET,
            actor=User.objects.get(pk=context.actor_id),
            target_type="page",
            target_id=page.id,
            metadata={"page_type": page_type},
        )
    return page


@transaction.atomic
def change_page_url(
    *,
    page_id: UUID,
    locale: str,
    slug: str,
    reason: str,
) -> tuple[PageTranslation, SiteRedirect]:
    """Moves a published page to a new address, leaving a redirect behind.

    The slug lock exists because every link, bookmark and search result points
    at the published address. This is the single deliberate way past it: a
    person, a stated reason, an audit entry, and an address that keeps
    answering.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        # Moving a URL costs whatever ranking it had. Whether that trade is
        # worth it is not a decision an optimiser makes for its customer.
        raise PageAutomationForbidden
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise RedirectReasonRequired
    normalized_locale = locale.strip().lower()
    normalized_slug = slug.strip().lower()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized_slug):
        raise TranslationSlugInvalid

    translation = (
        PageTranslation.all_objects.select_for_update()
        .select_related("page", "site")
        .filter(
            organization_id=context.organization_id,
            page_id=page_id,
            locale=normalized_locale,
        )
        .first()
    )
    if translation is None:
        raise TranslationNotFound
    site = Site.all_objects.select_for_update().get(
        pk=translation.site_id, organization_id=context.organization_id
    )
    if translation.slug == normalized_slug:
        raise RedirectTargetUnchanged
    if PageTranslation.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        locale=normalized_locale,
        slug=normalized_slug,
    ).exclude(pk=translation.id).exists():
        raise TranslationSlugConflict

    old_path = localized_path(
        default_locale=site.default_locale,
        locale=normalized_locale,
        slug=translation.slug,
    )
    new_path = localized_path(
        default_locale=site.default_locale,
        locale=normalized_locale,
        slug=normalized_slug,
    )

    # The lock is a database trigger, not just an application rule, so this
    # path has to open it deliberately and close it again — two statements in
    # one transaction. Written as one update the trigger would still refuse it,
    # and that refusal is what stops a published address moving by accident.
    locked_at = translation.slug_locked_at
    if locked_at is not None:
        PageTranslation.all_objects.filter(pk=translation.id).update(
            slug_locked_at=None
        )
    PageTranslation.all_objects.filter(pk=translation.id).update(
        slug=normalized_slug,
        version=translation.version + 1,
        slug_locked_at=locked_at,
        updated_at=timezone.now(),
    )
    translation.refresh_from_db()

    # The new address answers directly from now on, so nothing may still point
    # away from it. Without this a page moved back to a name it once had would
    # leave a redirect from that name to itself, which the database refuses.
    SiteRedirect.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        from_path=new_path,
    ).delete()

    # An address that already pointed here follows the page rather than
    # becoming a second hop: two redirects in a row lose a little of whatever
    # the first one was carrying, and search engines stop following long chains.
    SiteRedirect.all_objects.filter(
        organization_id=context.organization_id,
        site_id=site.id,
        to_path=old_path,
    ).update(to_path=new_path, updated_at=timezone.now())

    redirect, _created = SiteRedirect.all_objects.update_or_create(
        organization_id=context.organization_id,
        site_id=site.id,
        from_path=old_path,
        defaults={
            "page_id": page_id,
            "locale": normalized_locale,
            "to_path": new_path,
            "reason": normalized_reason,
            "created_by_id": context.actor_id,
        },
    )
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=PAGE_URL_CHANGED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="page",
        target_id=page_id,
        metadata={
            "locale": normalized_locale,
            "from_path": old_path,
            "to_path": new_path,
            "reason": normalized_reason,
        },
    )
    return translation, redirect


def delete_site_redirect(*, redirect_id: UUID) -> None:
    """Drops one redirect for good.

    Needed because a mistyped slug otherwise leaves a permanent redirect from
    an address nobody ever linked to. Session-only and audited like the change
    that created it: whatever still points at the old address stops arriving.
    """
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    if _is_automation(context):
        raise PageAutomationForbidden
    redirect = SiteRedirect.all_objects.filter(
        pk=redirect_id, organization_id=context.organization_id
    ).first()
    if redirect is None:
        raise RedirectNotFound
    site_id = redirect.site_id
    from_path = redirect.from_path
    to_path = redirect.to_path
    redirect.delete()
    record_audit(
        organization=Organization.objects.get(pk=context.organization_id),
        action=REDIRECT_DELETED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="site",
        target_id=site_id,
        metadata={"from_path": from_path, "to_path": to_path},
    )


def list_site_redirects(*, site_id: UUID) -> list[SiteRedirect]:
    context = authorize_entitled(
        SITE_CONTENT_EDIT,
        SITES_ENABLED,
        operation=FeatureOperation.READ,
    )
    if not Site.all_objects.filter(
        pk=site_id, organization_id=context.organization_id
    ).exists():
        raise SiteNotFound
    assert_within_grant(context, site_id=site_id)
    return list(
        SiteRedirect.all_objects.filter(
            organization_id=context.organization_id, site_id=site_id
        ).order_by("from_path")
    )
