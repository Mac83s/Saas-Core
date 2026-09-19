"""A generated page has an owned receipt, bounded structure, and human publication gate."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from psycopg import sql

import test_content_base_integrity as base_tests
from saas_core.modules.shared.sites.blueprints import canonical_hash
from saas_core.modules.shared.sites.models import (
    BlueprintImportReceipt,
    ContentProposal,
    Page,
    PageBlock,
    PageVersion,
    Publication,
)
from test_content_preview_authorization import connector, grant_for
from test_content_proposal_review import accept, detail, reject
from test_sites_api import create_site, csrf_value, save_draft, sites_client

surface = base_tests.surface
clear_cache = base_tests.clear_cache
pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("boundary", ["permission", "feature", "suspended", "anonymous", "csrf"])
def test_blueprint_authorization_matrix(surface: Any, blueprint: Any, boundary: str) -> None:
    from django.test import Client

    from saas_core.modules.core.organizations.models import Membership, Organization, Role
    from saas_core.modules.shared.billing.models import EntitlementSnapshot

    person, organization, owner, _ = surface
    _, _, url, document = blueprint
    client = person
    if boundary == "permission":
        Membership.objects.filter(organization=organization, user=owner).update(
            role=Role.objects.get(key="viewer", organization=None, organization_type="")
        )
    elif boundary == "feature":
        EntitlementSnapshot.all_objects.filter(organization=organization).update(
            features={"sites.enabled": False}
        )
    elif boundary == "suspended":
        Organization.objects.filter(pk=organization.pk).update(status="suspended")
    elif boundary == "anonymous":
        client = Client()
    headers = {} if boundary in {"anonymous", "csrf"} else {"HTTP_X_CSRFTOKEN": csrf_value(person)}
    with CaptureQueriesContext(connection) as queries:
        response = client.post(url, document, content_type="application/json", **headers)
    assert response.status_code in ({409} if boundary == "suspended" else {401, 403}), (
        response.content
    )
    if boundary == "anonymous":
        assert not any('"sites_' in query["sql"] for query in queries)
    assert not BlueprintImportReceipt.all_objects.exists()


@pytest.fixture
def blueprint(surface: Any) -> tuple[Any, Any, str, dict[str, Any]]:
    automation, key = connector(surface, scope="content:draft")
    grant = grant_for(surface, key)
    grant.mode = "draft_write"
    grant.save(update_fields=["mode"])
    site = surface[3]["target"]["site_id"]
    response = automation.get("/api/v1/sites/blueprint-catalog/", {"site_id": site})
    assert response.status_code == 200, response.content
    catalog = response.json()
    assert catalog["catalog_hash"] == canonical_hash({
        k: v for k, v in catalog.items() if k != "catalog_hash"
    })
    template = catalog["templates"][0]
    document = {
        "generation_id": str(uuid4()),
        "catalog_hash": catalog["catalog_hash"],
        "template_id": template["id"],
        "template_version": template["version"],
        "slots": {slot["key"]: "Przygotowana treść" for slot in template["slots"]},
        "locale": "pl",
        "name": "Nowa strona",
        "key": "nowa-strona",
        "idempotency_key": "blueprint-test",
    }
    return automation, grant, f"/api/v1/sites/{site}/blueprint-draft/", document


def send(blueprint: Any) -> Any:
    client, _, url, document = blueprint
    return client.post(url, document, content_type="application/json")


def test_new_blueprint_is_only_a_proposed_draft_with_durable_replay(
    surface: Any, blueprint: Any
) -> None:
    person = surface[0]
    client, _, url, document = blueprint
    old_pages = Page.all_objects.count()
    old_versions = PageVersion.all_objects.count()
    old_publications = Publication.all_objects.count()
    first = send(blueprint)
    assert first.status_code == 201, first.content
    receipt = first.json()
    assert receipt["request_hash"] == canonical_hash(document)
    assert receipt["published"] is False
    assert Page.all_objects.count() == old_pages + 1
    assert PageVersion.all_objects.count() == old_versions + 1
    assert Publication.all_objects.count() == old_publications
    proposal = ContentProposal.all_objects.get(pk=receipt["proposal_id"])
    assert detail(person, proposal)["blocks_before"] == []
    assert "Przygotowana treść" in str(detail(person, proposal)["blocks_after"])
    blocked = person.post(
        f"/api/v1/sites/{receipt['site_id']}/publications/",
        format="json",
        HTTP_IDEMPOTENCY_KEY="blueprint-pub",
        HTTP_X_CSRFTOKEN=csrf_value(person),
    )
    assert blocked.status_code == 403, blocked.content
    assert accept(person, proposal, detail(person, proposal)["review_token"]).status_code == 200
    save_draft(
        person,
        receipt["page_id"],
        expected_version=1,
        idempotency_key="human-after-brief",
        heading="Human edit",
    )
    assert send(blueprint).status_code == 200
    assert send(blueprint).json() == receipt
    with CaptureQueriesContext(connection) as queries:
        reconciled = client.get(url, {"idempotency_key": document["idempotency_key"]})
    assert reconciled.json() == {"found": True, "result": receipt}
    statements = [q["sql"] for q in queries]
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements
    )
    assert next(i for i, s in enumerate(statements) if "app.organization_id" in s) < next(
        i for i, s in enumerate(statements) if '"sites_blueprintimportreceipt"' in s
    )
    assert Publication.all_objects.count() == old_publications


@pytest.mark.parametrize(
    "tamper",
    ["extra", "slot_missing", "slot_extra", "html", "long", "stale", "template", "existing"],
)
def test_invalid_generation_has_no_partial_page(surface: Any, blueprint: Any, tamper: str) -> None:
    _, _, _, document = blueprint
    old = (Page.all_objects.count(), PageVersion.all_objects.count())
    slot = next(iter(document["slots"]))
    if tamper == "extra":
        document["blocks"] = []
    elif tamper == "slot_missing":
        document["slots"].pop(slot)
    elif tamper == "slot_extra":
        document["slots"]["/0/data/href"] = "https://untrusted.test"
    elif tamper == "html":
        document["slots"][slot] = "<script>x</script>"
    elif tamper == "long":
        document["slots"][slot] = "x" * 2001
    elif tamper == "stale":
        document["catalog_hash"] = "0" * 64
    elif tamper == "template":
        document["template_version"] = 100
    else:
        document["key"] = Page.all_objects.get(pk=surface[3]["target"]["page_id"]).key
    response = send(blueprint)
    assert response.status_code in {400, 409, 422}, response.content
    assert (Page.all_objects.count(), PageVersion.all_objects.count()) == old
    assert not BlueprintImportReceipt.all_objects.exists()


@pytest.mark.parametrize("boundary", ["revoked", "suggest_only", "limit", "payload", "other_site"])
def test_blueprint_obeys_grant_boundaries(surface: Any, blueprint: Any, boundary: str) -> None:
    client, grant, _, document = blueprint
    if boundary == "revoked":
        grant.revoked_at = timezone.now()
    elif boundary == "suggest_only":
        grant.mode = "suggest_only"
    elif boundary == "limit":
        grant.max_changes_per_day = 0
    elif boundary == "payload":
        grant.max_payload_bytes = 1
    else:
        grant.site_id = create_site(surface[0], slug="ungranted", idempotency_key="ungranted").data[
            "id"
        ]
    grant.save()
    assert send(blueprint).status_code == {"limit": 429, "payload": 400}.get(boundary, 403)
    assert not BlueprintImportReceipt.all_objects.exists()


def test_receipt_is_scoped_and_immutable_and_reject_restores_empty_draft(
    surface: Any, blueprint: Any
) -> None:
    first = send(blueprint)
    assert first.status_code == 201, first.content
    result = first.json()
    client, _, url, document = blueprint
    changed = deepcopy(document)
    changed["name"] = "Other intent"
    assert client.post(url, changed, content_type="application/json").status_code == 409
    other, _, _ = sites_client(slug="blueprint-other", role_key="owner")
    assert other.get(url, {"idempotency_key": document["idempotency_key"]}).status_code == 404
    proposal = ContentProposal.all_objects.get(pk=result["proposal_id"])
    assert reject(surface[0], proposal).status_code == 200
    page = Page.all_objects.get(pk=result["page_id"])
    assert not PageBlock.all_objects.filter(page_version_id=page.current_draft_id).exists()
    assert BlueprintImportReceipt.all_objects.count() == 1
    for operation in (
        lambda: BlueprintImportReceipt.all_objects.update(result={}),
        lambda: BlueprintImportReceipt.all_objects.all().delete(),
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            operation()


def test_blueprint_receipt_rls_relations_erasure_and_rollback(surface: Any, blueprint: Any) -> None:
    from importlib import import_module

    from django.apps import apps

    from saas_core.modules.core.organizations.erasure import erase_organization
    from test_sites_api import create_page

    assert send(blueprint).status_code == 201
    other, organization, owner = sites_client(slug="blueprint-rls-b", role_key="owner")
    site_id = create_site(other).data["id"]
    page_id = create_page(other, site_id, idempotency_key="b-page").data["id"]
    proposal = ContentProposal.all_objects.create(
        organization=organization,
        resource_type="site_page",
        resource_id=page_id,
        version=1,
        summary="Synthetic B",
        risk="low",
    )
    BlueprintImportReceipt.all_objects.create(
        organization=organization,
        site_id=site_id,
        page_id=page_id,
        proposal=proposal,
        created_by=owner,
        idempotency_key="b",
        request_hash="b" * 64,
    )
    with pytest.raises(DatabaseError), transaction.atomic():
        BlueprintImportReceipt.all_objects.create(
            organization=surface[1],
            site_id=site_id,
            page_id=page_id,
            proposal=proposal,
            created_by=owner,
            idempotency_key="cross-tenant",
            request_hash="a" * 64,
        )
    role = sql.Identifier(f"saas_core_blueprint_probe_{uuid4().hex}")
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(role))
        try:
            cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(role))
            cursor.execute(
                sql.SQL("GRANT SELECT ON sites_blueprintimportreceipt TO {}").format(role)
            )
            with transaction.atomic():
                cursor.execute(sql.SQL("SET LOCAL ROLE {}").format(role))
                cursor.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                )
                assert cursor.fetchone() == (False, False)
                for tenant in [None, surface[1].id, organization.id]:
                    cursor.execute(
                        "SELECT set_config('app.organization_id', %s, true)",
                        [str(tenant) if tenant else ""],
                    )
                    cursor.execute("SELECT organization_id FROM sites_blueprintimportreceipt")
                    assert cursor.fetchall() == ([] if tenant is None else [(tenant,)])
                cursor.execute("RESET ROLE")
        finally:
            cursor.execute("RESET ROLE")
            cursor.execute(
                sql.SQL("REVOKE SELECT ON sites_blueprintimportreceipt FROM {}").format(role)
            )
            cursor.execute(sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(role))
            cursor.execute(sql.SQL("DROP ROLE {}").format(role))
    migration = import_module(
        "saas_core.modules.shared.sites.migrations.0028_blueprint_receipt_isolation"
    )
    with pytest.raises(RuntimeError, match="receipts exist"):
        migration.preserve_receipts(apps, connection.schema_editor())
    erased = erase_organization(organization=surface[1], requested_by=None, reason="Synthetic test")
    assert erased.row_counts["sites.BlueprintImportReceipt"] == 1
    assert list(BlueprintImportReceipt.all_objects.values_list("organization_id", flat=True)) == [
        organization.id
    ]
