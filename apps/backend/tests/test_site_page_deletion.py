"""Deleting and restoring a page (decision 7, 2026-09-30; answers 7.1–7.9 = a)."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.sites.models import (
    NavigationItem,
    Page,
    PageTranslation,
    Site,
    SiteRedirect,
)
from test_sites_api import (
    automation_context,
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    rollback_site_request,
    save_draft,
    save_translation,
    sites_client,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_session_cache() -> None:
    cache.clear()


def _page(client: APIClient, site_id: str, key: str, slug: str, number: int) -> dict[str, Any]:
    page = create_page(client, site_id, key=key, idempotency_key=f"create-{key}")
    assert page.status_code == 201, page.data
    draft = save_draft(
        client,
        page.data["id"],
        expected_version=0,
        idempotency_key=f"draft-{key}",
        heading=f"Nagłówek {number}",
    )
    assert draft.status_code in (200, 201), draft.data
    translation = save_translation(
        client,
        page.data["id"],
        "pl",
        expected_version=0,
        slug=slug,
        title=key.title(),
        description=f"Opis: {key}",
        idempotency_key=f"translation-{key}",
    )
    assert translation.status_code in (200, 201), translation.data
    return {"id": page.data["id"], "key": key, "version": 1}


def _site(slug: str, *, role_key: str = "owner") -> tuple[APIClient, Any, dict[str, Any]]:
    """A published site: home (marked as the home page), offer and contact,
    offer and contact in the menu."""
    client, organization, _user = sites_client(slug=slug, role_key=role_key)
    site = create_site(client).data
    pages = {
        "home": _page(client, site["id"], "home", "start", 1),
        "offer": _page(client, site["id"], "offer", "oferta", 2),
        "contact": _page(client, site["id"], "contact", "kontakt", 3),
    }
    marked = client.put(
        f"/api/v1/sites/pages/{pages['home']['id']}/type/",
        {"page_type": "homepage"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert marked.status_code == 200, marked.data
    menu = client.put(
        f"/api/v1/sites/{site['id']}/navigation/",
        {
            "expected_version": 0,
            "items": [
                {"page_id": pages["offer"]["id"]},
                {"page_id": pages["contact"]["id"], "parent_page_id": pages["offer"]["id"]},
            ],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert menu.status_code == 200, menu.data
    if role_key in ("owner", "admin"):
        published = publish_site_request(client, site["id"], idempotency_key=f"{slug}-publish")
        assert published.status_code == 201, published.data
    return client, organization, {"site": site, **pages}


def _delete(
    client: APIClient, page: dict[str, Any], *, key: str, target: str | None = None, **extra: Any
) -> Any:
    body: dict[str, Any] = {"expected_version": page["version"], **extra}
    if target is not None:
        body["redirect_to_page_id"] = target
    return client.post(
        f"/api/v1/sites/pages/{page['id']}/delete/",
        body,
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def _restore(
    client: APIClient, page_id: str, *, key: str, slugs: dict[str, str] | None = None
) -> Any:
    return client.post(
        f"/api/v1/sites/pages/{page_id}/restore/",
        {"slugs": slugs} if slugs else {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )


def _snapshot(site_id: str) -> dict[str, Any]:
    site = Site.all_objects.select_related("current_publication").get(pk=site_id)
    assert site.current_publication is not None
    return site.current_publication.snapshot


def test_a_published_page_goes_off_the_site_at_once_and_its_address_redirects() -> None:
    client, organization, site = _site("delete-published")
    before = _snapshot(site["site"]["id"])
    # Work in progress elsewhere must not go out with the deletion.
    unpublished = save_draft(
        client,
        site["contact"]["id"],
        expected_version=1,
        idempotency_key="draft-contact-2",
        heading="Jeszcze nie do publikacji",
    )
    assert unpublished.status_code in (200, 201)

    response = _delete(client, site["offer"], key="delete-offer")

    assert response.status_code == 200, response.data
    assert response.data["redirects"] == [{"from_path": "/oferta/", "to_path": "/"}]
    assert response.data["page"]["deleted_at"] is not None
    assert response.data["page"]["path"] == "/oferta/"
    snapshot = _snapshot(site["site"]["id"])
    assert response.data["publication_id"] is not None
    assert [entry["key"] for entry in snapshot["pages"]] == ["home", "contact"]
    contact = next(entry for entry in snapshot["pages"] if entry["key"] == "contact")
    was = next(entry for entry in before["pages"] if entry["key"] == "contact")
    assert contact == was, "the contact page's new draft went out with the deletion"
    # The menu loses the entry; the one under it moves up to its place.
    assert [(entry["page_id"], entry["parent_page_id"]) for entry in snapshot["navigation"]] == [
        (str(site["contact"]["id"]), None)
    ]
    assert {"from_path": "/oferta/", "to_path": "/", "locale": "pl"} in snapshot["redirects"]
    assert not NavigationItem.all_objects.filter(page_id=site["offer"]["id"]).exists()
    assert NavigationItem.all_objects.get(page_id=site["contact"]["id"]).parent_id is None

    listed = client.get(f"/api/v1/sites/{site['site']['id']}/pages/")
    assert [item["key"] for item in listed.data["items"]] == ["home", "contact"]
    home = next(item for item in listed.data["items"] if item["key"] == "home")
    assert (home["path"], home["published_version"], home["in_navigation"]) == ("/start/", 1, False)
    deleted = client.get(f"/api/v1/sites/{site['site']['id']}/pages/?state=deleted")
    assert [item["key"] for item in deleted.data["items"]] == ["offer"]

    # Key and address are free for a new page.
    again = create_page(client, site["site"]["id"], key="offer", idempotency_key="offer-again")
    assert again.status_code == 201, again.data
    slug = save_translation(
        client,
        again.data["id"],
        "pl",
        expected_version=0,
        slug="oferta",
        title="Oferta",
        idempotency_key="offer-again-translation",
    )
    assert slug.status_code in (200, 201), slug.data
    assert OrganizationAuditEntry.objects.filter(
        organization=organization, action="sites.page.deleted", target_id=site["offer"]["id"]
    ).exists()
    # The deleted page is not there for editing any more.
    draft = client.get(f"/api/v1/sites/pages/{site['offer']['id']}/draft/")
    assert draft.status_code == 404


def test_a_chosen_page_is_the_redirect_target_and_older_redirects_follow() -> None:
    client, _organization, site = _site("delete-target")
    moved = client.put(
        f"/api/v1/sites/pages/{site['offer']['id']}/url/",
        {"locale": "pl", "slug": "uslugi", "reason": "Nowa nazwa działu"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert moved.status_code == 200, moved.data
    republished = publish_site_request(client, site["site"]["id"], idempotency_key="again")
    assert republished.status_code == 201

    response = _delete(client, site["offer"], key="delete-offer", target=site["contact"]["id"])

    assert response.status_code == 200, response.data
    redirects = {
        entry["from_path"]: entry["to_path"] for entry in _snapshot(site["site"]["id"])["redirects"]
    }
    # The old address from the move now leads to the target in one hop.
    assert redirects == {"/oferta/": "/kontakt/", "/uslugi/": "/kontakt/"}
    unknown = _delete(client, site["contact"], key="to-self", target=site["contact"]["id"])
    assert unknown.status_code == 400
    assert unknown.data["code"] == "redirect_target_unavailable"


def test_the_home_page_the_last_page_and_a_stale_version_are_refused() -> None:
    client, _organization, site = _site("delete-guards")

    home = _delete(client, site["home"], key="home")
    assert (home.status_code, home.data["code"]) == (409, "page_is_homepage")
    stale = _delete(client, {**site["offer"], "version": 0}, key="stale")
    assert stale.status_code == 409
    assert _delete(client, site["offer"], key="offer").status_code == 200
    assert _delete(client, site["offer"], key="offer").status_code == 200, "a replay"
    again = _delete(client, site["offer"], key="offer-other")
    assert (again.status_code, again.data["code"]) == (409, "page_already_deleted")
    assert _delete(client, site["contact"], key="contact").status_code == 200
    Page.all_objects.filter(pk=site["home"]["id"]).update(page_type="landing")
    last = _delete(client, site["home"], key="last")
    assert (last.status_code, last.data["code"]) == (409, "page_is_last")


def test_taking_a_page_off_the_site_needs_the_right_to_publish() -> None:
    client, organization, site = _site("delete-rights")
    Page.all_objects.filter(pk=site["home"]["id"]).update(page_type="landing")
    # A manager edits content but does not publish.
    from saas_core.modules.core.organizations.models import Membership, Role

    Membership.objects.filter(organization=organization).update(
        role=Role.objects.get(key="manager", organization=None, organization_type="")
    )
    published = _delete(client, site["offer"], key="as-manager")
    assert published.status_code == 403
    draft_only = create_page(client, site["site"]["id"], key="draft", idempotency_key="draft")
    removed = _delete(client, {"id": draft_only.data["id"], "version": 0}, key="draft-delete")
    assert removed.status_code == 200, removed.data
    assert removed.data["publication_id"] is None
    assert removed.data["redirects"] == []


def test_a_deleted_page_frees_its_place_in_the_page_limit() -> None:
    client, organization, site = _site("delete-quota")
    EntitlementSnapshot.all_objects.filter(organization=organization).update(
        quotas={"sites.max": 3, "pages.max": 3}
    )
    full = create_page(client, site["site"]["id"], key="more", idempotency_key="more")
    assert full.status_code == 409
    assert _delete(client, site["offer"], key="offer").status_code == 200
    room = create_page(client, site["site"]["id"], key="more", idempotency_key="more-2")
    assert room.status_code == 201
    # Restoring now would go past the limit.
    over = _restore(client, site["offer"]["id"], key="restore")
    assert (over.status_code, over.data["code"]) == (409, "page_limit_reached")


def test_a_restored_page_gets_its_address_back_or_asks_for_a_new_one() -> None:
    client, _organization, site = _site("restore")
    assert _delete(client, site["offer"], key="offer").status_code == 200

    restored = _restore(client, site["offer"]["id"], key="restore")

    assert restored.status_code == 200, restored.data
    assert (restored.data["deleted_at"], restored.data["path"]) == (None, "/oferta/")
    assert restored.data["in_navigation"] is False
    translation = PageTranslation.all_objects.get(page_id=site["offer"]["id"], locale="pl")
    assert translation.slug == "oferta"
    # The deletion's redirect from that address gives way to the page.
    assert not SiteRedirect.all_objects.filter(
        site_id=site["site"]["id"], from_path="/oferta/"
    ).exists()

    assert _delete(client, {**site["offer"], "version": 1}, key="offer-2").status_code == 200
    taken = create_page(client, site["site"]["id"], key="offer", idempotency_key="new-offer")
    save_translation(
        client,
        taken.data["id"],
        "pl",
        expected_version=0,
        slug="oferta",
        idempotency_key="new-offer-translation",
    )
    conflict = _restore(client, site["offer"]["id"], key="restore-2")
    assert (conflict.status_code, conflict.data["code"]) == (409, "page_restore_slug_taken")
    renamed = _restore(client, site["offer"]["id"], key="restore-3", slugs={"pl": "oferta-2020"})
    assert renamed.status_code == 200, renamed.data
    # The key was taken too, so the restored page takes the next free one.
    assert (renamed.data["key"], renamed.data["path"]) == ("offer-2", "/oferta-2020/")


def test_a_rollback_leaves_a_deleted_page_deleted() -> None:
    client, _organization, site = _site("delete-rollback")
    first = _snapshot(site["site"]["id"])
    first_id = Site.all_objects.get(pk=site["site"]["id"]).current_publication_id
    assert _delete(client, site["offer"], key="offer").status_code == 200

    rolled = rollback_site_request(client, site["site"]["id"], str(first_id), idempotency_key="rb")

    assert rolled.status_code == 201, rolled.data
    snapshot = _snapshot(site["site"]["id"])
    assert [entry["key"] for entry in snapshot["pages"]] == ["home", "contact"]
    assert len(first["pages"]) == 3
    assert {"from_path": "/oferta/", "to_path": "/", "locale": "pl"} in snapshot["redirects"]


def test_the_dialog_lists_the_pages_that_link_to_the_one_being_deleted() -> None:
    client, _organization, site = _site("delete-links")
    linking = client.put(
        f"/api/v1/sites/pages/{site['contact']['id']}/draft/",
        {
            "expected_version": 1,
            "blocks": [
                {
                    "block_type": "core.hero",
                    "schema_version": 6,
                    "data": {
                        "title": "Kontakt",
                        "action": {"label": "Zobacz ofertę", "href": "/oferta"},
                    },
                }
            ],
            "media_asset_ids": [],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="contact-links",
    )
    assert linking.status_code in (200, 201), linking.data

    links = client.get(f"/api/v1/sites/pages/{site['offer']['id']}/incoming-links/")

    assert links.status_code == 200
    assert links.data["items"] == [
        {"page_id": site["contact"]["id"], "name": "Contact", "links": 1}
    ]


def test_an_automation_never_deletes_or_restores_a_page() -> None:
    from saas_core.modules.core.organizations.context import activate_tenant_context
    from saas_core.modules.shared.sites.page_deletion import delete_page, restore_page
    from saas_core.modules.shared.sites.services import PersonRequired

    _client, organization, site = _site("delete-automation")
    from saas_core.modules.core.organizations.models import Membership

    user = Membership.objects.filter(organization=organization).first().user
    with activate_tenant_context(automation_context(organization.id, user.id, may_publish=True)):
        with pytest.raises(PersonRequired):
            delete_page(
                page_id=site["offer"]["id"],
                expected_version=1,
                redirect_to_page_id=None,
                idempotency_key="automation",
            )
        with pytest.raises(PersonRequired):
            restore_page(page_id=site["offer"]["id"], slugs=None, idempotency_key="automation")
    assert Page.all_objects.get(pk=site["offer"]["id"]).deleted_at is None


def test_marking_a_home_page_makes_the_previous_one_an_ordinary_page() -> None:
    client, _organization, site = _site("one-home")

    marked = client.put(
        f"/api/v1/sites/pages/{site['offer']['id']}/type/",
        {"page_type": "homepage"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )

    assert marked.status_code == 200
    types = dict(
        Page.all_objects.filter(site_id=site["site"]["id"]).values_list("key", "page_type")
    )
    assert types == {"home": "landing", "offer": "homepage", "contact": "landing"}
    # The former home page can now be deleted; the new one cannot.
    assert _delete(client, site["home"], key="old-home").status_code == 200
    refused = _delete(client, site["offer"], key="new-home")
    assert refused.data["code"] == "page_is_homepage"
