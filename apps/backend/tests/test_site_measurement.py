"""Page views counted by the public renderer and read back as numbers (ADR-060)."""

from __future__ import annotations

import datetime
from typing import Any
from uuid import uuid7

import pytest
from django.db import DatabaseError, connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.shared.notifications.models import ApiKey, ApiKeyCredentialRoute
from saas_core.modules.shared.sites.models import (
    ContentAutomationGrant,
    PageViewDay,
    PageViewKind,
)
from test_site_inquiries import (  # noqa: F401 - fixtures travel by import
    isolate_cache_and_delivery,
    published_form,
    submit,
)
from test_sites_api import create_site, sites_client
from test_sites_collections import create_collection
from test_sites_operations import _api_key_client

pytestmark = pytest.mark.django_db
PAGE_URL = "/api/v1/public/site/"


@pytest.fixture
def form_site(request: pytest.FixtureRequest) -> Any:
    """The inquiry tests' published page with its contact form."""
    return request.getfixturevalue("published_form")


def open_page(hostname: str, path: str = "/", *, counted: bool = True) -> Any:
    extra = {"HTTP_X_SAAS_CORE_COUNT_VIEW": "1"} if counted else {}
    return APIClient().get(PAGE_URL, {"path": path}, HTTP_HOST=hostname, **extra)


def metrics_url(site_id: Any, since: datetime.date, until: datetime.date) -> str:
    return f"/api/v1/sites/{site_id}/metrics/?since={since}&until={until}"


def test_a_view_is_counted_only_when_the_renderer_says_a_person_opened_the_page(
    form_site: Any,
) -> None:
    _, organization, _, site, hostname = form_site

    first = open_page(hostname)
    assert first.status_code == 200, first.content
    assert open_page(hostname).status_code == 200
    # The panel's preview, a crawler or a prefetch reach the same endpoint
    # without the renderer's word, and are not a person reading the page.
    assert open_page(hostname, counted=False).status_code == 200
    assert open_page(hostname, "/nie-ma-takiej/").status_code == 404

    row = PageViewDay.all_objects.get(organization_id=organization.id)
    assert row.views == 2
    assert row.kind == PageViewKind.PAGE
    assert row.publication_id == site.current_publication_id
    assert row.day == timezone.now().astimezone(datetime.UTC).date()
    assert first.data["canonical_url"].endswith(row.path)


def test_a_view_is_written_inside_the_tenant_the_hostname_names(form_site: Any) -> None:
    """The test database bypasses row-level security, so the order of the
    statements is what proves the write happens inside the tenant."""
    _, _, _, _, hostname = form_site
    with CaptureQueriesContext(connection) as queries:
        assert open_page(hostname).status_code == 200
    sql = [query["sql"] for query in queries.captured_queries]
    write = next(i for i, q in enumerate(sql) if "INSERT INTO sites_pageviewday" in q)
    tenant_set = max(
        i for i, q in enumerate(sql[:write]) if "SET LOCAL app.organization_id" in q
    )
    assert tenant_set < write


def test_page_view_counts_are_separated_by_row_level_security(form_site: Any) -> None:
    _, organization, _, site, hostname = form_site
    assert open_page(hostname).status_code == 200
    other, foreign, _ = sites_client(slug="views-foreign", role_key="owner")
    foreign_site = create_site(other).data["id"]
    row = PageViewDay.all_objects.get()
    # The guard refuses a row naming another tenant's site, whatever the caller.
    with pytest.raises(DatabaseError), transaction.atomic():
        PageViewDay.all_objects.filter(id=row.id).update(site_id=foreign_site)
    role = connection.ops.quote_name(f"page_views_rls_{uuid7().hex}")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'sites_pageviewday'::regclass"
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute(f"CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cursor.execute(f"GRANT SELECT ON sites_pageviewday TO {role}")
        cursor.execute(f"SET LOCAL ROLE {role}")
        for tenant, expected in [("", 0), (str(foreign.id), 0), (str(organization.id), 1)]:
            cursor.execute("SET LOCAL app.organization_id = %s", [tenant])
            cursor.execute("SELECT COUNT(*) FROM sites_pageviewday")
            assert cursor.fetchone()[0] == expected
        cursor.execute("RESET ROLE")
    assert site.id == row.site_id


def test_a_count_that_fails_does_not_cost_the_visitor_the_page(
    form_site: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, _, _, hostname = form_site
    monkeypatch.setattr(
        "saas_core.modules.shared.sites.measurement._UPSERT", "SELECT * FROM no_such_table"
    )
    assert open_page(hostname).status_code == 200
    assert not PageViewDay.all_objects.exists()


def test_the_owner_reads_views_and_inquiry_counts_without_anybody_s_details(
    form_site: Any,
) -> None:
    client, _, _, site, hostname = form_site
    assert open_page(hostname).status_code == 200
    assert submit(site, hostname).status_code == 201
    today = timezone.now().astimezone(datetime.UTC).date()

    response = client.get(metrics_url(site.id, today - datetime.timedelta(days=6), today))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["counter_enabled"] is True
    assert [(row["views"], row["kind"]) for row in body["page_views"]] == [(1, "page")]
    # Both keyed by the page's canonical address, so a view and an inquiry on
    # the same page line up whichever alias the visitor used.
    assert body["inquiries"] == [
        {
            "day": str(today),
            "path": body["page_views"][0]["path"],
            "publication_id": str(site.current_publication_id),
            "block_position": 1,
            "count": 1,
        }
    ]
    # Counted, never read: nothing of the visitor travels with the number.
    assert "visitor@example.test" not in response.content.decode()
    assert "Jane Visitor" not in response.content.decode()


@pytest.mark.parametrize(("days", "status"), [(0, 200), (91, 200), (92, 400), (-1, 400)])
def test_the_range_is_bounded(form_site: Any, days: int, status: int) -> None:
    client, _, _, site, _ = form_site
    today = timezone.now().astimezone(datetime.UTC).date()
    since = today - datetime.timedelta(days=days)
    if days < 0:
        since, today = today, today - datetime.timedelta(days=1)
    response = client.get(metrics_url(site.id, since, today))
    assert response.status_code == status, response.content
    if status == 400:
        assert response.json()["code"] == "site_metrics_range_invalid"


def test_another_tenant_s_site_is_not_found(form_site: Any) -> None:
    client, _, _, _, _ = form_site
    other, _, _ = sites_client(slug="views-other", role_key="owner")
    foreign_site = create_site(other).data["id"]
    today = timezone.now().astimezone(datetime.UTC).date()
    assert client.get(metrics_url(foreign_site, today, today)).status_code == 404


def _metrics_key(organization: Any, owner: Any, scopes: list[str], marker: str) -> Client:
    client = _api_key_client(organization=organization, created_by=owner, marker=marker)
    key = ApiKey.all_objects.get(organization=organization, name=f"Status {marker}")
    ApiKey.all_objects.filter(pk=key.id).update(scopes=scopes)
    ApiKeyCredentialRoute.objects.filter(api_key_id=key.id).update(scopes=scopes)
    client.key_id = key.id  # type: ignore[attr-defined]
    return client


def test_a_key_needs_the_metrics_scope_and_a_grant_for_the_whole_site(
    form_site: Any,
) -> None:
    client, organization, owner, site, hostname = form_site
    assert open_page(hostname).status_code == 200
    today = timezone.now().astimezone(datetime.UTC).date()
    url = metrics_url(site.id, today, today)

    # A content key does not learn how the site does.
    reader = _metrics_key(organization, owner, ["content:read", "content:draft"], "r")
    assert reader.get(url).status_code == 401

    counter = _metrics_key(organization, owner, ["content:metrics"], "m")
    ungranted = counter.get(url)
    assert ungranted.status_code == 403, ungranted.content
    assert ungranted.json()["code"] == "automation_grant_missing"

    # One collection does not stand for the pages around it.
    collection = create_collection(client, str(site.id)).data["id"]
    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=counter.key_id,  # type: ignore[attr-defined]
        collection_id=collection,
        mode="suggest_only",
        created_by=owner,
    )
    assert counter.get(url).status_code == 403

    ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=counter.key_id,  # type: ignore[attr-defined]
        site_id=site.id,
        mode="suggest_only",
        created_by=owner,
    )
    answered = counter.get(url)
    assert answered.status_code == 200, answered.content
    assert answered.json()["page_views"][0]["views"] == 1
    # And the metrics scope opens nothing else.
    assert counter.get("/api/v1/sites/capabilities/").status_code == 401
