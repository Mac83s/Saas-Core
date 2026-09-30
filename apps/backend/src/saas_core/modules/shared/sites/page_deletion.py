"""Deleting a page and bringing it back (decision 7, 2026-09-30).

A page's versions, blocks and publications are append-only history: rollback
serves old snapshots and the audit reads them, and the database opens those
tables only for erasing a whole organization (ADR-042). So a deleted page keeps
its row and is hidden instead — from the panel's list, the menu, the page limit
and every later publication — and can be restored.

What a visitor sees changes at once. A page that is on the public site is taken
off by a new publication built from the *published* state minus that page, not
from the drafts: nobody's half-finished work goes out with it. Its addresses
answer with a 301 to the page chosen when deleting (the home page by default).
Links to it in other pages are left as they are; the redirect keeps them
working, and the panel shows who links before the person confirms.

Removing content is one of the things ADR-035 keeps for a person, whatever the
grant, and taking a page off the public site needs the right to publish.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID, uuid7

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from saas_core.modules.core.identity.models import User
from saas_core.modules.core.organizations.api import (
    ResourceReferenceConflict,
    ResourceReferenceRejected,
    record_resource_references,
)
from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.shared.billing.api import (
    FeatureOperation,
    authorize_entitled,
)
from saas_core.observability import correlation_id

from .block_decoration import stored_block_payload
from .localization import localized_path
from .models import (
    NavigationItem,
    Page,
    PageBlock,
    PageTranslation,
    PageType,
    Publication,
    Site,
    SiteOutboxEvent,
    SiteRedirect,
)
from .permissions import SITE_CONTENT_EDIT, SITE_PUBLISH, SITES_ENABLED
from .rich_content import block_links
from .services import (
    MEDIA_ASSET_RESOURCE_TYPE,
    PUBLICATION_REFERENCE_OWNER,
    SITE_PUBLISHED_EVENT,
    DraftVersionConflict,
    PageNotFound,
    SiteMediaReferenceUnavailable,
    SitesIdempotencyConflict,
    TranslationSlugConflict,
    _ensure_page_capacity,
    _idempotency_key,
    _schedule_site_outbox_delivery,
    assert_person_required,
)

PAGE_DELETED = "sites.page.deleted"
PAGE_RESTORED = "sites.page.restored"


class PageIsHomepage(APIException):
    status_code = 409
    default_detail = "Strony głównej nie można usunąć. Najpierw wskaż inną stronę główną."
    default_code = "page_is_homepage"


class PageIsLast(APIException):
    status_code = 409
    default_detail = "To ostatnia podstrona witryny — witryna musi mieć co najmniej jedną."
    default_code = "page_is_last"


class PageAlreadyDeleted(APIException):
    status_code = 409
    default_detail = "Ta podstrona jest już usunięta."
    default_code = "page_already_deleted"


class PageNotDeleted(APIException):
    status_code = 409
    default_detail = "Ta podstrona nie jest usunięta."
    default_code = "page_not_deleted"


class RedirectTargetUnavailable(APIException):
    status_code = 400
    default_detail = "Przekierować można tylko na inną opublikowaną podstronę."
    default_code = "redirect_target_unavailable"


class RestoreSlugTaken(APIException):
    status_code = 409
    default_detail = "Adres tej podstrony zajęła inna podstrona. Podaj nowy adres."
    default_code = "page_restore_slug_taken"


@dataclass(frozen=True)
class PageDeletion:
    page: Page
    publication: Publication | None
    redirects: list[SiteRedirect]
    created: bool


def _tombstone(slug: str, page: Page) -> str:
    """The address a deleted page holds instead of its own, so the real one is
    free for a new page. Never public: deleted pages leave every publication."""
    return f"{slug[:50].strip('-')}-usunieta-{page.id.hex[-8:]}"


def _published_page(site: Site, page_id: UUID) -> dict[str, Any] | None:
    publication = site.current_publication
    if publication is None:
        return None
    return next(
        (
            entry
            for entry in publication.snapshot.get("pages", [])
            if isinstance(entry, dict) and entry.get("page_id") == str(page_id)
        ),
        None,
    )


def _target_paths(
    site: Site, snapshot: dict[str, Any], deleted: dict[str, Any], target_id: UUID | None
) -> dict[str, str]:
    """Where each address of the deleted page goes, per locale: to the chosen
    published page, the home page when none was chosen, the site root when
    the site has no home page marked. The home page in the site's own language
    is `/`, the address a visitor knows it by."""
    pages = [entry for entry in snapshot.get("pages", []) if isinstance(entry, dict)]
    if target_id is not None:
        target = next(
            (
                entry
                for entry in pages
                if entry.get("page_id") == str(target_id)
                and entry.get("page_id") != deleted.get("page_id")
            ),
            None,
        )
        if target is None:
            raise RedirectTargetUnavailable
    else:
        target = next(
            (
                entry
                for entry in pages
                if entry.get("page_type") == PageType.HOMEPAGE
                and entry.get("page_id") != deleted.get("page_id")
            ),
            None,
        )
    by_locale = {
        locale["locale"]: locale["path"]
        for locale in (target or {}).get("locales", [])
        if isinstance(locale, dict)
    }
    home = target is not None and target.get("page_type") == PageType.HOMEPAGE
    paths: dict[str, str] = {}
    for locale in deleted.get("locales", []):
        name = locale["locale"]
        if target is None or (home and name == site.default_locale):
            paths[name] = "/" if name == site.default_locale else f"/{name}/"
        else:
            paths[name] = by_locale.get(name) or by_locale.get(site.default_locale) or "/"
    return paths


def _without_page(snapshot: dict[str, Any], page_id: UUID) -> dict[str, Any]:
    """The published state minus one page: its menu entry goes, and entries
    under it move up to where it was, as they do in the working menu."""
    key = str(page_id)
    navigation = [entry for entry in snapshot.get("navigation", []) if isinstance(entry, dict)]
    removed = next((entry for entry in navigation if entry.get("page_id") == key), None)
    kept = []
    for entry in navigation:
        if entry.get("page_id") == key:
            continue
        if removed is not None and entry.get("parent_page_id") == key:
            entry = {**entry, "parent_page_id": removed.get("parent_page_id")}
        kept.append(entry)
    return {
        **snapshot,
        "navigation": kept,
        "pages": [
            entry
            for entry in snapshot.get("pages", [])
            if not (isinstance(entry, dict) and entry.get("page_id") == key)
        ],
    }


def _with_redirects(snapshot: dict[str, Any], redirects: list[SiteRedirect]) -> dict[str, Any]:
    """The snapshot's own redirects, followed through the new ones, plus those."""
    moved = {redirect.from_path: redirect.to_path for redirect in redirects}
    entries = [
        {**entry, "to_path": moved.get(str(entry.get("to_path")), entry.get("to_path"))}
        for entry in snapshot.get("redirects", [])
        if isinstance(entry, dict) and entry.get("from_path") not in moved
    ]
    entries += [
        {"from_path": redirect.from_path, "to_path": redirect.to_path, "locale": redirect.locale}
        for redirect in redirects
    ]
    return {**snapshot, "redirects": sorted(entries, key=lambda entry: entry["from_path"])}


def publish_derived(
    *,
    context: Any,
    site: Site,
    snapshot: dict[str, Any],
    actor: User,
    idempotency_key: str,
    reason: str,
) -> Publication:
    """A publication of an already-published state changed in one place — not
    of the drafts. Media references follow the pages it keeps."""
    previous = (
        Publication.all_objects.filter(organization_id=context.organization_id, site_id=site.id)
        .order_by("-sequence")
        .first()
    )
    publication = Publication.all_objects.create(
        organization_id=context.organization_id,
        site=site,
        sequence=(previous.sequence + 1 if previous is not None else 1),
        snapshot_schema_version=(
            site.current_publication.snapshot_schema_version if site.current_publication else 1
        ),
        snapshot=snapshot,
        snapshot_hash="",
        created_by=actor,
        idempotency_key=idempotency_key,
    )
    media_ids = sorted({
        asset_id
        for entry in snapshot.get("pages", [])
        if isinstance(entry, dict)
        for asset_id in entry.get("media_asset_ids", [])
    })
    try:
        record_resource_references(
            context=context,
            resource_type=MEDIA_ASSET_RESOURCE_TYPE,
            owner_type=PUBLICATION_REFERENCE_OWNER,
            owner_id=publication.id,
            resource_ids=tuple(UUID(asset_id) for asset_id in media_ids),
        )
    except ResourceReferenceRejected as error:
        raise SiteMediaReferenceUnavailable from error
    except ResourceReferenceConflict as error:
        raise SitesIdempotencyConflict from error
    Site.all_objects.filter(pk=site.id, organization_id=context.organization_id).update(
        current_publication=publication, updated_at=timezone.now()
    )
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
        causation_id=f"sites-{reason}:{publication.id}",
        payload={
            "site_id": str(site.id),
            "publication_id": str(publication.id),
            "sequence": publication.sequence,
            "snapshot_hash": publication.snapshot_hash,
        },
    )
    _schedule_site_outbox_delivery(event)
    return publication


def _lift_slug_lock(translation: PageTranslation, slug: str) -> None:
    """Moves a translation to another slug through the published-slug lock,
    which is a trigger: open it and close it again in one transaction, the way
    changing a published address does."""
    locked_at = translation.slug_locked_at
    if locked_at is not None:
        PageTranslation.all_objects.filter(pk=translation.id).update(slug_locked_at=None)
    PageTranslation.all_objects.filter(pk=translation.id).update(
        slug=slug, slug_locked_at=locked_at, updated_at=timezone.now()
    )


def _remove_from_navigation(site: Site, page: Page) -> bool:
    """Takes the page's menu entry out; entries under it take its place."""
    item = NavigationItem.all_objects.filter(
        organization_id=page.organization_id, site_id=site.id, page_id=page.id
    ).first()
    if item is None:
        return False
    NavigationItem.all_objects.filter(
        organization_id=page.organization_id, site_id=site.id, parent_id=item.id
    ).update(parent_id=item.parent_id, updated_at=timezone.now())
    item.delete()
    site.navigation_version += 1
    site.save(update_fields=["navigation_version", "updated_at"])
    return True


@transaction.atomic
def delete_page(
    *,
    page_id: UUID,
    expected_version: int,
    redirect_to_page_id: UUID | None,
    idempotency_key: str,
) -> PageDeletion:
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Usunięcie podstrony")
    key = _idempotency_key(idempotency_key)
    page = (
        Page.all_objects.select_for_update(of=("self",))
        .filter(pk=page_id, organization_id=context.organization_id)
        .first()
    )
    if page is None:
        raise PageNotFound
    if page.deleted_at is not None:
        if page.deletion_idempotency_key == key:
            return PageDeletion(page, None, [], False)
        raise PageAlreadyDeleted
    site = (
        Site.all_objects.select_for_update(of=("self",))
        .select_related("current_publication", "organization")
        .get(pk=page.site_id, organization_id=context.organization_id)
    )
    if page.version != expected_version:
        raise DraftVersionConflict
    if page.page_type == PageType.HOMEPAGE:
        raise PageIsHomepage
    if (
        Page.all_objects.filter(
            organization_id=context.organization_id, site_id=site.id, deleted_at__isnull=True
        ).count()
        <= 1
    ):
        raise PageIsLast
    published = _published_page(site, page.id)
    if published is not None:
        # Off the public site is a publication, and that needs the right to
        # publish; a page nobody sees is ordinary editing.
        authorize_entitled(SITE_PUBLISH, SITES_ENABLED)
    actor = User.objects.get(pk=context.actor_id)
    now = timezone.now()

    redirects: list[SiteRedirect] = []
    if published is not None:
        assert site.current_publication is not None
        targets = _target_paths(
            site, site.current_publication.snapshot, published, redirect_to_page_id
        )
        for locale in published.get("locales", []):
            from_path, to_path = locale["path"], targets[locale["locale"]]
            # An address that led here now leads where this page's own does,
            # rather than through it: one hop, not two.
            leading_here = SiteRedirect.all_objects.filter(
                organization_id=context.organization_id, site_id=site.id, to_path=from_path
            )
            # One that would now point at itself has nothing left to do.
            leading_here.filter(from_path=to_path).delete()
            leading_here.update(to_path=to_path, updated_at=now)
            redirect, _created = SiteRedirect.all_objects.update_or_create(
                organization_id=context.organization_id,
                site_id=site.id,
                from_path=from_path,
                defaults={
                    "page_id": page.id,
                    "locale": locale["locale"],
                    "to_path": to_path,
                    "reason": f"Usunięta podstrona: {page.name}"[:500],
                    "created_by_id": actor.id,
                },
            )
            redirects.append(redirect)

    slugs: dict[str, str] = {}
    for translation in PageTranslation.all_objects.select_for_update().filter(
        organization_id=context.organization_id, page_id=page.id
    ):
        slugs[translation.locale] = translation.slug
        _lift_slug_lock(translation, _tombstone(translation.slug, page))
    in_navigation = _remove_from_navigation(site, page)
    page.deleted_at = now
    page.deleted_by = actor
    page.deletion_idempotency_key = key
    page.deleted_slugs = slugs
    page.save(
        update_fields=[
            "deleted_at",
            "deleted_by",
            "deletion_idempotency_key",
            "deleted_slugs",
            "updated_at",
        ]
    )

    publication = None
    if published is not None:
        assert site.current_publication is not None
        publication = publish_derived(
            context=context,
            site=site,
            snapshot=_with_redirects(
                _without_page(site.current_publication.snapshot, page.id), redirects
            ),
            actor=actor,
            idempotency_key=f"page-delete:{key}"[:120],
            reason="page-delete",
        )
    record_audit(
        organization=site.organization,
        action=PAGE_DELETED,
        actor=actor,
        target_type="page",
        target_id=page.id,
        metadata={
            "site_id": str(site.id),
            "key": page.key,
            "was_published": published is not None,
            "publication_id": str(publication.id) if publication else None,
            "redirects": [
                {"from_path": redirect.from_path, "to_path": redirect.to_path}
                for redirect in redirects
            ],
            "removed_from_navigation": in_navigation,
        },
    )
    return PageDeletion(page, publication, redirects, True)


@transaction.atomic
def restore_page(
    *,
    page_id: UUID,
    slugs: dict[str, str] | None,
    idempotency_key: str,
) -> Page:
    """Brings a deleted page back as a draft: not in the menu and not public
    until it is published again. Its old addresses return when free; a taken
    one needs a new address from the person. The deletion's redirects from
    those addresses give way to the page."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED)
    assert_person_required(context, "Przywrócenie podstrony")
    _idempotency_key(idempotency_key)
    page = (
        Page.all_objects.select_for_update(of=("self",))
        .filter(pk=page_id, organization_id=context.organization_id)
        .first()
    )
    if page is None:
        raise PageNotFound
    if page.deleted_at is None:
        raise PageNotDeleted
    site = (
        Site.all_objects.select_for_update(of=("self",))
        .select_related("organization")
        .get(pk=page.site_id, organization_id=context.organization_id)
    )
    # A new page may have taken the key meanwhile; keys are the panel's own
    # names, so the restored page takes the next free one instead.
    base, key, suffix = page.key[:76], page.key, 2
    live = Page.all_objects.filter(
        organization_id=context.organization_id, site_id=site.id, deleted_at__isnull=True
    )
    while live.filter(key=key).exists():
        key, suffix = f"{base}-{suffix}", suffix + 1
    _ensure_page_capacity(site)
    wanted = {**page.deleted_slugs, **(slugs or {})}
    translations = list(
        PageTranslation.all_objects.select_for_update().filter(
            organization_id=context.organization_id, page_id=page.id
        )
    )
    for translation in translations:
        slug = wanted.get(translation.locale, translation.slug)
        if (
            PageTranslation.all_objects.filter(
                organization_id=context.organization_id,
                site_id=site.id,
                locale=translation.locale,
                slug=slug,
            )
            .exclude(pk=translation.id)
            .exists()
        ):
            raise (RestoreSlugTaken if slugs is None else TranslationSlugConflict)
        _lift_slug_lock(translation, slug)
        SiteRedirect.all_objects.filter(
            organization_id=context.organization_id,
            site_id=site.id,
            from_path=localized_path(
                default_locale=site.default_locale, locale=translation.locale, slug=slug
            ),
        ).delete()
    page.key = key
    page.deleted_at = None
    page.deleted_by = None
    page.deletion_idempotency_key = ""
    page.deleted_slugs = {}
    page.save(
        update_fields=[
            "key",
            "deleted_at",
            "deleted_by",
            "deletion_idempotency_key",
            "deleted_slugs",
            "updated_at",
        ]
    )
    record_audit(
        organization=site.organization,
        action=PAGE_RESTORED,
        actor=User.objects.get(pk=context.actor_id),
        target_type="page",
        target_id=page.id,
        metadata={"site_id": str(site.id), "key": page.key},
    )
    page.refresh_from_db()
    return page


def _comparable(path: str) -> str:
    parts = urlsplit(path)
    if parts.scheme or parts.netloc:
        return ""
    value = parts.path or "/"
    return value if value.endswith("/") else f"{value}/"


def incoming_links(*, page_id: UUID) -> list[dict[str, Any]]:
    """The other pages whose current draft links to this one's addresses, and
    how many links each has — what the person sees before deleting."""
    context = authorize_entitled(SITE_CONTENT_EDIT, SITES_ENABLED, operation=FeatureOperation.READ)
    page = (
        Page.all_objects.filter(
            pk=page_id, organization_id=context.organization_id, deleted_at__isnull=True
        )
        .select_related("site")
        .first()
    )
    if page is None:
        raise PageNotFound
    site = page.site
    paths = {
        localized_path(
            default_locale=site.default_locale, locale=translation.locale, slug=translation.slug
        )
        for translation in PageTranslation.all_objects.filter(
            organization_id=context.organization_id, page_id=page.id
        )
    }
    others = list(
        Page.all_objects.filter(
            organization_id=context.organization_id, site_id=site.id, deleted_at__isnull=True
        )
        .exclude(pk=page.id)
        .exclude(current_draft__isnull=True)
        .order_by("name", "id")
    )
    blocks_by_version: dict[UUID, list[dict[str, Any]]] = {}
    for block in PageBlock.all_objects.filter(
        organization_id=context.organization_id,
        page_version_id__in=[other.current_draft_id for other in others],
    ).order_by("page_version_id", "position"):
        blocks_by_version.setdefault(block.page_version_id, []).append(stored_block_payload(block))
    found = []
    for other in others:
        blocks = blocks_by_version.get(other.current_draft_id, [])  # type: ignore[arg-type]
        count = sum(1 for target in block_links(blocks) if _comparable(target) in paths)
        if count:
            found.append({"page_id": other.id, "name": other.name, "links": count})
    return found


def page_listing_facts(pages: list[Page]) -> dict[UUID, dict[str, Any]]:
    """What the panel's list shows beside each page: the title and address in
    the site's own language (a deleted page's address from before it went),
    the version visitors see, and whether the menu has it. Read inside the
    tenant the listing already authorized."""
    if not pages:
        return {}
    organization_id = pages[0].organization_id
    site = Site.all_objects.select_related("current_publication").get(
        pk=pages[0].site_id, organization_id=organization_id
    )
    published = {
        entry.get("page_id"): entry.get("version")
        for entry in (site.current_publication.snapshot if site.current_publication else {}).get(
            "pages", []
        )
        if isinstance(entry, dict)
    }
    translations = {
        translation.page_id: translation
        for translation in PageTranslation.all_objects.filter(
            organization_id=organization_id,
            page_id__in=[page.id for page in pages],
            locale=site.default_locale,
        )
    }
    in_navigation = set(
        NavigationItem.all_objects.filter(
            organization_id=organization_id,
            site_id=site.id,
            page_id__in=[page.id for page in pages],
        ).values_list("page_id", flat=True)
    )
    facts: dict[UUID, dict[str, Any]] = {}
    for page in pages:
        translation = translations.get(page.id)
        slug = (
            page.deleted_slugs.get(site.default_locale)
            if page.deleted_at is not None
            else (translation.slug if translation else None)
        )
        facts[page.id] = {
            "title": translation.title if translation else None,
            "path": (
                localized_path(
                    default_locale=site.default_locale, locale=site.default_locale, slug=slug
                )
                if slug
                else None
            ),
            "published_version": published.get(str(page.id)),
            "in_navigation": page.id in in_navigation,
            "deleted_at": page.deleted_at,
        }
    return facts
