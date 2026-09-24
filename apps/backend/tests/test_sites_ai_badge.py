"""The visible AI marking and the operator's switch (ADR-059 pkt 7).

The public payload names the AI images of a page, read at render time. Only a
platform operator (is_staff with confirmed MFA) hides the list, through a
management command that leaves a row of history; no API writes the switch.
"""

from __future__ import annotations

import inspect
from io import StringIO
from typing import Any

import pytest
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.identity.models import User, UserMfaMethod, UserStatus
from saas_core.modules.shared.media.models import AiOrigin, MediaAsset
from saas_core.modules.shared.sites.models import AiBadgeSwitch
from test_site_rich_content import public_home, publish_home
from test_sites_api import create_media_asset, create_page, create_site, csrf_value, sites_client
from test_sites_collections import (
    _tagged_entry,
    _verified_platform_domain,
    create_collection,
    create_entry,
    publish,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_login_limiter() -> None:
    cache.clear()


def operator(email: str = "operator@example.test", *, staff: bool = True, mfa: bool = True):
    user = User.objects.create_user(email=email, password="Operator-Haslo-2026!")
    user.status = UserStatus.ACTIVE
    user.is_staff = staff
    user.save()
    if mfa:
        UserMfaMethod.objects.create(
            user=user, secret_ciphertext="not-used", confirmed_at=timezone.now()
        )
    return user


def switch(*args: str) -> str:
    out = StringIO()
    call_command("set_ai_badge", *args, stdout=out)
    return out.getvalue()


def hero(asset: MediaAsset) -> dict[str, Any]:
    return {
        "block_type": "core.hero",
        "schema_version": 3,
        "data": {"title": "Oferta", "image": {"asset_id": str(asset.id), "alt": "Pracownia"}},
    }


def put(client: APIClient, url: str, blocks: list[dict[str, Any]], key: str):
    response = client.put(
        url,
        {"expected_version": 0, "blocks": blocks, "media_asset_ids": []},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY=key,
    )
    assert response.status_code == 201, response.data
    return response


def test_page_payload_lists_ai_images_until_the_operator_hides_the_badge() -> None:
    client, org, owner = sites_client(slug="ai-badge-page", role_key="owner")
    site = create_site(client).data["id"]
    page = create_page(client, site).data["id"]
    ai_asset = create_media_asset(org, owner)
    real_asset = create_media_asset(org, owner)
    put(
        client,
        f"/api/v1/sites/pages/{page}/draft/",
        [hero(ai_asset), hero(real_asset)],
        "draft",
    )
    publish_home(client, site, page, key="publish")
    # Marked after publication: provenance is read at render time.
    MediaAsset.all_objects.filter(pk=ai_asset.id).update(ai_origin=AiOrigin.GENERATED)

    with CaptureQueriesContext(connection) as captured:
        assert public_home(site)["ai_media_ids"] == [str(ai_asset.id)]
    statements = [query["sql"] for query in captured.captured_queries]
    switch_read = next(i for i, sql in enumerate(statements) if "sites_aibadgeswitch" in sql)
    media_read = next(i for i, sql in enumerate(statements) if 'FROM "media_mediaasset"' in sql)
    # The tenant is set again inside the badge block, before the media read.
    assert any("SET LOCAL app.organization_id" in sql for sql in statements[switch_read:media_read])

    staff = operator()
    switch("--operator", staff.email, "--off", "--reason", "Przegląd prawny oznaczeń.")
    assert public_home(site)["ai_media_ids"] == []
    switch("--operator", staff.email, "--on", "--reason", "Wracamy do oznaczania.")
    assert public_home(site)["ai_media_ids"] == [str(ai_asset.id)]


def test_entry_payload_lists_ai_images() -> None:
    client, org, owner = sites_client(slug="ai-badge-entry", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    entry = create_entry(client, collection.data["id"], slug="wpis", idempotency_key="entry")
    asset = create_media_asset(org, owner)
    MediaAsset.all_objects.filter(pk=asset.id).update(ai_origin=AiOrigin.GENERATED)
    put(client, f"/api/v1/sites/entries/{entry.data['id']}/draft/", [hero(asset)], "draft")
    publish(client, entry.data["id"], idempotency_key="publish")
    platform = _verified_platform_domain(site.data["id"])

    found = APIClient().get(
        "/api/v1/public/site/", {"path": "/blog/wpis/"}, HTTP_HOST=platform.hostname
    )

    assert found.status_code == 200, found.data
    assert found.data["ai_media_ids"] == [str(asset.id)]


def test_blog_index_and_tag_archive_render_with_the_badge_visible() -> None:
    # Pages nobody published stand in for a publication; the badge must not
    # ask them for more than they carry.
    client, _, _ = sites_client(slug="ai-badge-index", role_key="owner")
    site = create_site(client)
    collection = create_collection(client, site.data["id"])
    _tagged_entry(client, collection.data["id"], "jeden", ["Porady"])
    _tagged_entry(client, collection.data["id"], "dwa", ["Porady"])
    platform = _verified_platform_domain(site.data["id"])

    for path in ("/blog/", "/blog/tag/porady/"):
        found = APIClient().get("/api/v1/public/site/", {"path": path}, HTTP_HOST=platform.hostname)
        assert found.status_code == 200, (path, found.content[:200])
        assert found.data["ai_media_ids"] == []


def test_only_an_active_staff_operator_with_mfa_flips_the_switch() -> None:
    no_staff = operator("customer@example.test", staff=False)
    no_mfa = operator("staff-no-mfa@example.test", mfa=False)
    staff = operator()

    for user in (no_staff, no_mfa):
        with pytest.raises(CommandError):
            switch("--operator", user.email, "--off", "--reason", "Próba bez uprawnień.")
    with pytest.raises(CommandError):
        switch("--operator", "nobody@example.test", "--off", "--reason", "Nie ma takiego.")
    with pytest.raises(CommandError):
        switch("--operator", staff.email, "--off")
    with pytest.raises(CommandError):
        switch("--operator", staff.email, "--off", "--reason", "   ")
    assert not AiBadgeSwitch.objects.exists()


def test_every_change_is_a_row_and_show_prints_the_history(caplog) -> None:
    staff = operator()
    switch("--operator", staff.email, "--off", "--reason", "Pierwszy powód wyłączenia.")
    switch("--operator", staff.email, "--off", "--reason", "Drugi powód, ten sam stan.")

    assert AiBadgeSwitch.objects.count() == 2
    shown = switch("--show")
    assert "wyłączona" in shown
    assert "Pierwszy powód" in shown and "Drugi powód" in shown
    assert staff.email in shown
    event = next(
        r for r in caplog.records if getattr(r, "security_event", "") == "sites.ai_badge_switched"
    )
    assert event.user_id == str(staff.id)
    assert event.visible is False
    # The reason is history in the table, never a log line.
    assert not any("powód" in str(vars(record)) for record in caplog.records)


def _views(patterns: list[Any], prefix: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            found += _views(pattern.url_patterns, prefix + str(pattern.pattern))
        elif isinstance(pattern, URLPattern):
            found.append((prefix + str(pattern.pattern), pattern.callback))
    return found


def test_no_api_url_reaches_the_switch() -> None:
    """Customers have no endpoint, permission or panel field for the badge."""
    api_views = [
        (path, view)
        for path, view in _views(get_resolver().url_patterns)
        if path.startswith("api/")
    ]
    assert api_views
    for path, view in api_views:
        target = getattr(view, "cls", None) or getattr(view, "view_class", None) or view
        source = inspect.getsource(inspect.getmodule(target))
        assert "AiBadgeSwitch" not in source, path
        assert "set_ai_badge" not in source, path
