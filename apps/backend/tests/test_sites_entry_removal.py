"""Removing an entry and erasing the removed with their type (ADR-079,
„Uzupełnienie CT2"): a removed entry leaves every surface in the same moment
and its address answers 404; its rows stay until its whole type is deleted,
which a person confirms by typing the type's name."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.utils import timezone

from saas_core.modules.core.organizations.context import (
    acting_context,
    activate_tenant_context,
    context_from_membership,
)
from saas_core.modules.core.organizations.models import Membership, OrganizationAuditEntry
from saas_core.modules.core.organizations.person_gate import PersonRequired
from saas_core.modules.shared.sites.content_types import delete_content_type
from saas_core.modules.shared.sites.entry_removal import remove_entry
from saas_core.modules.shared.sites.entry_translation_source import ENTRY_SOURCE
from saas_core.modules.shared.sites.models import (
    ContentCollection,
    ContentEntry,
    ContentEntryPublication,
    ContentEntryState,
    ContentEntryTag,
    ContentEntryVersion,
    ContentTag,
    ContentTaxonomy,
    EntryScheduleState,
    SiteOutboxEvent,
)
from test_sites_api import automation_context, csrf_value
from test_sites_blog_languages import _feed, _get, _items
from test_sites_collections import create_entry, publish, save_entry_draft, schedule
from test_sites_llms import _llms
from test_sites_taxonomies import World, _code, _send, _sitemap, _status

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_throttle() -> None:
    cache.clear()


@pytest.fixture(autouse=True)
def a_company_in_three_languages(settings: Any) -> None:
    settings.SITES_SUPPORTED_LOCALES = ("pl", "en", "de")
    settings.CONTENT_TYPES_OFFERED = True


def _remove(world: World, entry_id: str, *, preview: bool = False) -> Any:
    url = f"/api/v1/sites/entries/{entry_id}/"
    if preview:
        return _send(world.client, "post", url + "removal/preview/")
    return _send(world.client, "delete", url)


def _person(world: World) -> Any:
    membership = Membership.objects.filter(organization_id=world.organization_id).first()
    assert membership is not None
    return context_from_membership(membership)


def _listed(world: World, type_id: str) -> list[str]:
    response = world.client.get(f"/api/v1/sites/collections/{type_id}/entries/")
    return [item["slug"] for item in response.json()["items"]]


def test_a_removed_entry_leaves_every_surface_at_once_and_its_rows_stay() -> None:
    world = World("removal-surfaces")
    host, origin = world.host, f"https://{world.host}"
    wood = world.category(world.blog_id, "Drewno")
    polish = world.entry(world.blog_id, "wpis-o-drewnie", categories=(wood,), tags=("Stolarka",))
    english = world.translated(
        polish, "en", "about-wood", "About wood", categories=(wood,), tags=("Stolarka",)
    )
    path, sibling = "/blog/wpis-o-drewnie/", "/en/blog/about-wood/"
    surfaces = ("/blog/kategoria/drewno/", "/blog/tag/stolarka/")
    assert _get(host, sibling).data["hreflang"] == {
        "pl": f"{origin}{path}",
        "en": f"{origin}{sibling}",
    }
    for address in (path, *surfaces):
        assert _status(host, address) == 200, address
    assert path in _feed(host, "feed.xml").content.decode()
    counted = lambda: {  # noqa: E731
        "publications": ContentEntryPublication.all_objects.filter(entry_id=polish).count(),
        "versions": ContentEntryVersion.all_objects.filter(entry_id=polish).count(),
        "filed": ContentEntryTag.all_objects.filter(entry_id=polish).count(),
    }
    before = counted()

    look = _remove(world, polish, preview=True)
    assert look.status_code == 200, look.json()
    assert look.json() == {
        "entry_id": polish,
        "title": "Wpis O Drewnie",
        "locale": "pl",
        "removed": False,
        "published": True,
        "path": path,
        "scheduled": False,
        "machine_translation": False,
        "other_languages": [{"locale": "en", "title": "About wood", "state": "published"}],
    }
    assert _status(host, path) == 200

    done = _remove(world, polish)

    assert done.status_code == 200, done.json()
    assert done.json()["removed"] is True
    # Gone like a withdrawn entry: 404, and off every list in the same moment.
    assert _status(host, path) == 404
    for address in surfaces:
        assert _status(host, address) == 404, address
    assert path not in " ".join(_items(_get(host, "/blog/")))
    for document in (
        _sitemap(host),
        _feed(host, "feed.xml").content.decode(),
        _feed(host, "atom.xml").content.decode(),
        _llms(host)[1],
    ):
        assert path not in document
    # The English version stays, and no longer names a Polish one.
    remaining = _get(host, sibling)
    assert remaining.status_code == 200
    assert remaining.data["hreflang"] == {"en": f"{origin}{sibling}"}
    assert remaining.data["x_default"] == f"{origin}{sibling}"
    assert _status(host, "/en/blog/category/drewno/") == 200
    # The panel: off the list and the counters, and nothing reaches it by id.
    assert "wpis-o-drewnie" not in _listed(world, world.blog_id)
    types = world.client.get(f"/api/v1/sites/{world.site_id}/content-types/").json()["types"]
    blog = next(item for item in types if item["collection"]["id"] == world.blog_id)
    assert (blog["entries"], blog["published"]) == (2, 2)
    row = world.term(world.blog_id, wood)
    assert (row["entries"], row["published"]) == (1, {"en": 1})
    for refused in (
        world.client.get(f"/api/v1/sites/entries/{polish}/draft/"),
        publish(world.client, polish, idempotency_key="again"),
        _send(world.client, "put", f"/api/v1/sites/entries/{polish}/tags/", {"names": ["X"]}),
        _send(world.client, "put", f"/api/v1/sites/entries/{polish}/categories/", {"term_ids": []}),
        _remove(world, polish),
        _remove(world, polish, preview=True),
    ):
        assert refused.status_code == 404, refused.json()
    # Translations: no longer offered, by anybody's list.
    person = _person(world)
    with activate_tenant_context(person):
        offered = {
            item.object_id
            for item in ENTRY_SOURCE.list_objects(context=person, cursor=None, limit=100).items
        }
    assert polish not in {str(found) for found in offered}

    # Nothing was erased: the rows are history, hidden.
    kept = ContentEntry.with_removed.get(pk=polish)
    assert (kept.state, kept.current_publication_id) == (ContentEntryState.REMOVED, None)
    assert counted() == before
    assert not ContentEntry.all_objects.filter(pk=polish).exists()
    audit = OrganizationAuditEntry.objects.get(action="sites.entry.removed")
    assert audit.metadata["title"] == "Wpis O Drewnie"
    assert (audit.metadata["slug"], audit.metadata["path"]) == ("wpis-o-drewnie", path)
    assert audit.metadata["was_published"] is True
    # Its address and its language in the article are free again.
    again = create_entry(world.client, world.blog_id, slug="wpis-o-drewnie", idempotency_key="new")
    assert again.status_code == 201, again.data
    back = world.client.post(
        f"/api/v1/sites/entries/{english}/translations/",
        {"locale": "pl", "slug": "o-drewnie", "title": "O drewnie"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(world.client),
        HTTP_IDEMPOTENCY_KEY="back-to-polish",
    )
    assert back.status_code == 201, back.data
    # A term the removed entry was filed under is not held by it.
    lonely = world.category(world.blog_id, "Samotna")
    only = world.entry(world.blog_id, "wpis-samotny", categories=(lonely,), out=False)
    assert world.remove(world.blog_id, lonely, preview=True).json()["removable"] is False
    assert _remove(world, only).status_code == 200
    assert world.remove(world.blog_id, lonely).json()["removed"] is True


def test_removing_calls_off_a_planned_publication_and_works_in_a_switched_off_type() -> None:
    world = World("removal-states")
    host = world.host
    waiting = world.entry(world.projects, "dom-czeka", out=False)
    moment = (timezone.now() + timedelta(days=2)).isoformat()
    assert schedule(world.client, waiting, moment).status_code == 200
    out = world.entry(world.projects, "dom-a")
    look = _remove(world, waiting, preview=True).json()
    assert (look["published"], look["path"], look["scheduled"]) == (False, None, True)

    assert _remove(world, waiting).status_code == 200

    called_off = ContentEntry.with_removed.get(pk=waiting)
    assert called_off.schedule_state == EntryScheduleState.CANCELLED
    assert "usunięty" in called_off.schedule_error
    # A switched-off type's entry can be removed: that is how the type is
    # emptied before it is deleted.
    switched = _send(
        world.client, "post", f"/api/v1/sites/collections/{world.projects}/switch-off/"
    )
    assert switched.status_code == 200, switched.json()
    assert _remove(world, out).status_code == 200
    back = _send(world.client, "post", f"/api/v1/sites/collections/{world.projects}/switch-on/")
    assert back.status_code == 200, back.json()
    assert _status(host, "/realizacje/dom-a/") == 404
    assert _listed(world, world.projects) == []


def test_only_a_person_removes_an_entry_or_deletes_a_type() -> None:
    world = World("removal-people")
    entry = world.entry(world.projects, "dom-a")
    person = _person(world)
    key = automation_context(
        world.organization_id, person.actor_id, credential_id=uuid4(), may_publish=True
    )
    assistant = acting_context(person, via="assistant", ref=f"conversation:{uuid4()}")
    for context in (key, assistant):
        with activate_tenant_context(context):
            with pytest.raises(PersonRequired):
                remove_entry(entry_id=entry)  # type: ignore[arg-type]
            with pytest.raises(PersonRequired):
                remove_entry(entry_id=entry, dry_run=True)  # type: ignore[arg-type]
            with pytest.raises(PersonRequired):
                delete_content_type(collection_id=world.projects, confirm_name="Realizacje")  # type: ignore[arg-type]
    assert ContentEntry.all_objects.get(pk=entry).state == ContentEntryState.PUBLISHED
    # Another company reaches neither.
    stranger = World("removal-people-other")
    assert _remove(stranger, entry).status_code == 404
    assert _remove(stranger, entry, preview=True).status_code == 404
    assert (
        _send(stranger.client, "delete", f"/api/v1/sites/collections/{world.projects}/").status_code
        == 404
    )
    assert ContentEntry.all_objects.filter(pk=entry).exists()


def _delete_type(
    world: World, type_id: str, name: str | None = None, *, preview: bool = False
) -> Any:
    url = f"/api/v1/sites/collections/{type_id}/"
    if preview:
        return _send(world.client, "post", url + "removal/preview/")
    return world.client.delete(
        url + (f"?confirm_name={name}" if name is not None else ""),
        HTTP_X_CSRFTOKEN=csrf_value(world.client),
    )


def test_a_type_whose_every_entry_is_removed_is_deleted_and_they_are_erased_for_good() -> None:
    world = World("removal-erase")
    host = world.host
    bathrooms = world.category(world.projects, "Łazienki")
    # A tree goes whole: the category under it too.
    small = world.category(world.projects, "Małe", bathrooms)
    first = world.entry(world.projects, "dom-a", categories=(bathrooms,), tags=("Porady",))
    english = world.translated(first, "en", "house-a", "House A", categories=(bathrooms,))
    draft = world.entry(world.projects, "dom-szkic", categories=(small,), out=False)
    ids = [first, english, draft]

    # With entries it is not deletable, whatever is typed.
    look = _delete_type(world, world.projects, preview=True).json()
    assert (look["deletable"], look["entries"], look["removed_entries"]) == (False, 3, 0)
    assert _code(_delete_type(world, world.projects, "Realizacje")) == (
        409,
        "content_type_not_empty",
    )
    for entry_id in (first, english):
        assert _remove(world, entry_id).status_code == 200
    assert _code(_delete_type(world, world.projects, "Realizacje")) == (
        409,
        "content_type_not_empty",
    )
    assert _remove(world, draft).status_code == 200

    look = _delete_type(world, world.projects, preview=True).json()
    assert look == {
        "collection_id": world.projects,
        "name": "Realizacje",
        "deletable": True,
        "entries": 0,
        "removed_entries": 3,
        "removed_publications": 2,
        "categories": 2,
        "paths": {"pl": "/realizacje/", "en": "/en/projects/", "de": "/de/referenzen/"},
        "confirmation_required": True,
    }
    # Erasing takes the type's name, typed — nothing less.
    for name in (None, "", "realizacje", "Realizacje 2"):
        refused = _delete_type(world, world.projects, name)
        assert _code(refused) == (400, "confirmation_required"), name
        assert refused.json()["errors"][0]["field"] == "confirm_name"
    assert ContentEntry.with_removed.filter(pk__in=ids).count() == 3
    publications = list(
        ContentEntryPublication.all_objects.filter(entry_id__in=ids).values_list("id", flat=True)
    )
    assert len(publications) == 2
    assert SiteOutboxEvent.all_objects.filter(entry_publication_id__in=publications).count() == 2

    gone = _delete_type(world, world.projects, "Realizacje")

    assert gone.status_code == 204, gone.content
    assert not ContentCollection.all_objects.filter(pk=world.projects).exists()
    assert not ContentEntry.with_removed.filter(pk__in=ids).exists()
    assert not ContentEntryVersion.all_objects.filter(entry_id__in=ids).exists()
    assert not ContentEntryPublication.all_objects.filter(entry_id__in=ids).exists()
    assert not SiteOutboxEvent.all_objects.filter(entry_publication_id__in=publications).exists()
    assert not ContentEntryTag.all_objects.filter(entry_id__in=ids).exists()
    # Its categories went with it; the site's tags are the site's.
    assert not ContentTag.all_objects.filter(pk__in=[bathrooms, small]).exists()
    assert not ContentTaxonomy.all_objects.filter(collection_id=world.projects).exists()
    assert ContentTag.all_objects.filter(site_id=world.site_id, slug="porady").exists()
    # What outlives the rows: who, when, which type, how many, and which.
    audit = OrganizationAuditEntry.objects.get(action="sites.content_type.deleted")
    assert audit.actor_user_id is not None and audit.occurred_at is not None
    assert (audit.metadata["name"], audit.metadata["base_path"]) == ("Realizacje", "realizacje")
    assert (
        audit.metadata["erased_entries"],
        audit.metadata["erased_publications"],
        audit.metadata["erased_versions"],
        audit.metadata["categories"],
    ) == (3, 2, 3, 2)
    assert sorted(item["title"] for item in audit.metadata["entries"]) == [
        "Dom A",
        "Dom Szkic",
        "House A",
    ]
    # The rest of the site is as it was, and the names are free.
    assert _status(host, "/blog/wpis-jeden/") == 200
    assert _status(host, "/realizacje/") == 404
    again = world.client.post(
        f"/api/v1/sites/{world.site_id}/collections/",
        {"key": "realizacje", "name": "Realizacje", "kind": "blog", "base_path": "realizacje"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(world.client),
        HTTP_IDEMPOTENCY_KEY="projects-again",
    )
    assert again.status_code == 201, again.data
    # A type that never had an entry is deleted as before: nothing to confirm.
    empty = str(again.data["id"])
    assert _delete_type(world, empty, preview=True).json()["confirmation_required"] is False
    assert _delete_type(world, empty).status_code == 204


def test_saving_a_draft_of_a_removed_entry_is_not_found() -> None:
    world = World("removal-draft")
    entry = world.entry(world.projects, "dom-a", out=False)
    assert _remove(world, entry).status_code == 200
    saved = save_entry_draft(
        world.client, entry, expected_version=1, text="Jeszcze raz.", idempotency_key="late"
    )
    assert saved.status_code == 404, saved.data


def test_erasing_an_entry_with_a_picture_leaves_the_picture_in_the_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Media references are append-only: an erased entry's pictures stay the
    company's, and the erasure does not stumble over them."""
    from rest_framework.test import APIClient

    from saas_core.modules.core.identity.models import User
    from saas_core.modules.core.organizations.models import Organization
    from saas_core.modules.shared.media.models import MediaAsset, MediaReference
    from test_media_api import MemoryStorage
    from test_sites_api import create_media_asset

    world = World("removal-media")
    organization = Organization.objects.get(pk=world.organization_id)
    user = User.objects.get(pk=_person(world).actor_id)
    asset = create_media_asset(organization, user)
    storage = MemoryStorage()
    storage.objects[asset.object_key] = (b"\x89PNG\r\n\x1a\n", "image/png")
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.public_media.get_object_storage", lambda: storage
    )
    entry = str(
        create_entry(world.client, world.projects, slug="ze-zdjeciem", idempotency_key="m").data[
            "id"
        ]
    )
    saved = world.client.put(
        f"/api/v1/sites/entries/{entry}/draft/",
        {
            "expected_version": 0,
            "blocks": [
                {
                    "block_type": "core.hero",
                    "schema_version": 3,
                    "data": {
                        "title": "Wpis ze zdjęciem",
                        "image": {"asset_id": str(asset.id), "alt": "Zdjęcie"},
                    },
                }
            ],
            "media_asset_ids": [str(asset.id)],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(world.client),
        HTTP_IDEMPOTENCY_KEY="m-draft",
    )
    assert saved.status_code == 201, saved.data
    world.out(entry)

    def picture() -> int:
        return int(
            APIClient()
            .get(f"/api/v1/public/site/media/{asset.id}/", HTTP_HOST=world.host)
            .status_code
        )

    assert picture() == 200
    references = MediaReference.all_objects.filter(asset_id=asset.id).count()
    assert references >= 1

    assert _remove(world, entry).status_code == 200
    # Removed: a visitor gets the picture no more than the entry.
    assert picture() == 404
    assert _delete_type(world, world.projects, "Realizacje").status_code == 204

    assert not ContentEntry.with_removed.filter(pk=entry).exists()
    assert MediaAsset.all_objects.filter(pk=asset.id, deleted_at__isnull=True).exists()
    assert MediaReference.all_objects.filter(asset_id=asset.id).count() == references


def test_an_organization_with_categories_and_removed_entries_can_be_erased() -> None:
    """Erasing a company deletes every row of it — a removed entry too, which
    no reader of entries sees, and a tree of categories holding each other."""
    from saas_core.modules.core.organizations.erasure import erase_organization
    from saas_core.modules.core.organizations.models import Organization

    world = World("removal-company")
    top = world.category(world.projects, "Wnętrza")
    under = world.category(world.projects, "Łazienki", top)
    kept = world.entry(world.projects, "dom-a", categories=(under,), tags=("Porady",))
    gone = world.entry(world.projects, "dom-b", categories=(top,))
    assert world.names(world.projects, under, en="Bathrooms").status_code == 200
    assert _remove(world, gone).status_code == 200
    organization = Organization.objects.get(pk=world.organization_id)

    receipt = erase_organization(
        organization=organization, requested_by=None, reason="Synthetic test"
    )

    assert receipt.row_counts["sites.ContentTaxonomy"] == 1
    assert receipt.row_counts["sites.ContentEntry"] == 3
    for model in (ContentEntry.with_removed, ContentTag.all_objects, ContentTaxonomy.all_objects):
        assert not model.filter(organization_id=organization.id).exists()
    assert not ContentEntryPublication.all_objects.filter(entry_id__in=[kept, gone]).exists()
