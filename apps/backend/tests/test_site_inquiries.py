from dataclasses import replace
from uuid import uuid7

import pytest
from django.core.cache import cache
from django.db import DatabaseError, connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from saas_core.modules.core.organizations.context import (
    activate_tenant_context,
    current_tenant_context,
)
from saas_core.modules.core.organizations.models import (
    Membership,
    OrganizationAuditEntry,
    OrganizationStatus,
)
from saas_core.modules.core.organizations.tasks import (
    InvalidTenantTaskContext,
    issue_tenant_task_contract,
    tenant_task_context,
)
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.notifications.models import NotificationMessage, PendingTaskRoute
from saas_core.modules.shared.notifications.templates import render_template
from saas_core.modules.shared.sites.inquiries import public_inquiry_context
from saas_core.modules.shared.sites.models import Domain, Site, SiteInquiry
from test_sites_api import (
    create_page,
    create_site,
    csrf_value,
    publish_site_request,
    save_translation,
    sites_client,
)

pytestmark = pytest.mark.django_db
PUBLIC_URL = "/api/v1/public/site/inquiries/"


@pytest.fixture(autouse=True)
def isolate_cache_and_delivery(monkeypatch):
    cache.clear()
    # No SMTP, broker or eager Celery delivery can escape these tests.
    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay",
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def published_form():
    client, organization, owner = sites_client(slug="inquiry-owner", role_key="owner")
    EntitlementSnapshot.all_objects.filter(organization=organization).update(
        features={"sites.enabled": True, "notifications.enabled": True}
    )
    site_id = create_site(client).data["id"]
    page_id = create_page(client, site_id).data["id"]
    draft = client.put(
        f"/api/v1/sites/pages/{page_id}/draft/",
        {
            "expected_version": 0,
            "blocks": [
                {"block_type": "core.hero", "schema_version": 1, "data": {"heading": "Hi"}},
                {
                    "block_type": "core.contact_form",
                    "schema_version": 1,
                    "data": {"title": "Napisz do nas"},
                },
            ],
            "media_asset_ids": [],
        },
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="form-draft",
    )
    assert draft.status_code in (200, 201), draft.data
    assert save_translation(
        client,
        page_id,
        "pl",
        expected_version=0,
        slug="contact",
        title="Contact",
        description="Contact our team",
        idempotency_key="translation",
    ).status_code in (200, 201)
    publication = publish_site_request(client, site_id, idempotency_key="publish-form")
    assert publication.status_code in (200, 201), publication.data
    site = Site.all_objects.get(id=site_id)
    hostname = Domain.all_objects.get(site=site, is_canonical=True).hostname
    return client, organization, owner, site, hostname


def payload(site, **overrides):
    return {
        "publication_id": str(site.current_publication_id),
        "path": "/",
        "block_position": 1,
        "name": "Jane Visitor",
        "email": "visitor@example.test",
        "phone": "+48123456789",
        "message": "Please tell me more about your services.",
        "website": "",
        **overrides,
    }


def submit(site, hostname, *, key="inquiry-one", origin=None, client=None, **overrides):
    return (client or APIClient(enforce_csrf_checks=True)).post(
        PUBLIC_URL,
        payload(site, **overrides),
        format="json",
        HTTP_HOST=hostname,
        HTTP_ORIGIN=f"https://{hostname}" if origin is None else origin,
        HTTP_IDEMPOTENCY_KEY=key,
    )


def test_public_form_persists_once_and_queues_private_owner_notification(published_form):
    _, organization, owner, site, host = published_form
    with CaptureQueriesContext(connection) as queries:
        first = submit(site, host, name="<script>not HTML</script>")
    sql = [q["sql"] for q in queries.captured_queries]
    assert first.status_code == 201, first.data
    assert set(first.data) == {"accepted", "reference"}
    inquiry = SiteInquiry.all_objects.get(id=first.data["reference"])
    assert inquiry.organization_id == organization.id
    assert inquiry.publication_id == site.current_publication_id
    assert inquiry.page_path == "/contact/"
    message = inquiry.notification_message
    assert message.recipient_email == owner.email
    assert message.recipient_email != inquiry.email
    assert message.status == "queued"
    assert PendingTaskRoute.objects.filter(kind="email", object_key=str(message.id)).exists()
    _, html = render_template(
        key=message.template_key, version=1, locale=message.locale, context=message.context
    )
    assert "<script>" not in html and "&lt;script&gt;" in html
    with tenant_task_context(
        message.signed_tenant_context, expected_causation_id=f"email:{message.id}"
    ) as ctx:
        assert ctx.organization_id == organization.id
        assert ctx.permissions == frozenset({"sites.inquiry.submit"})
    retry = submit(site, host, name="<script>not HTML</script>")
    assert retry.status_code == 200 and retry.data == first.data
    conflict = submit(site, host, name="Changed")
    assert conflict.status_code == 409
    assert conflict.data["code"] == "site_inquiry_idempotency_conflict"
    assert SiteInquiry.all_objects.count() == NotificationMessage.all_objects.count() == 1
    audit = OrganizationAuditEntry.objects.get(action="sites.inquiry.received")
    assert audit.actor_user_id is None
    assert set(audit.metadata) == {"site_id", "publication_id"}
    first_tenant = next(i for i, q in enumerate(sql) if "SET LOCAL app.organization_id" in q)
    assert first_tenant < next(i for i, q in enumerate(sql) if 'FROM "sites_siteinquiry"' in q)
    assert first_tenant < next(
        i for i, q in enumerate(sql) if 'FROM "organizations_membership"' in q
    )


@pytest.mark.parametrize(
    "origin",
    ["", "null", "https://attacker.test", "https://test@victim.test", "https://victim.test/path"],
)
def test_public_origin_denied_before_private_reads(published_form, origin):
    _, _, _, site, host = published_form
    with CaptureQueriesContext(connection) as queries:
        response = submit(site, host, origin=origin)
    assert response.status_code == 403
    assert not any('FROM "sites_siteinquiry"' in q["sql"] for q in queries.captured_queries)
    assert not SiteInquiry.all_objects.exists()


@pytest.mark.parametrize(
    "overrides",
    [
        {"organization_id": str(uuid7())},
        {"recipient_email": "intruder@example.test"},
        {"website": "bot filled this"},
        {"email": "invalid"},
        {"name": ""},
        {"message": "x" * 5001},
        {"path": "//evil.test/"},
        {"block_position": -1},
    ],
)
def test_public_payload_validation(published_form, overrides):
    _, _, _, site, host = published_form
    assert submit(site, host, **overrides).status_code == 400
    assert not SiteInquiry.all_objects.exists()


@pytest.mark.parametrize(
    "change,status",
    [
        ({"publication_id": str(uuid7())}, 409),
        ({"block_position": 0}, 404),
        ({"block_position": 999}, 404),
        ({"path": "/missing/"}, 404),
        ({"key": ""}, 409),
    ],
)
def test_submit_requires_current_published_form(published_form, change, status):
    _, _, _, site, host = published_form
    assert submit(site, host, **change).status_code == status
    assert not SiteInquiry.all_objects.exists()


def test_public_payload_size_and_throttle(published_form):
    _, _, _, site, host = published_form
    assert submit(site, host, message="x" * 70_000).status_code == 413
    for _ in range(5):
        assert submit(site, host, website="bot").status_code == 400
    assert submit(site, host).status_code == 429
    assert not SiteInquiry.all_objects.exists()


@pytest.mark.parametrize("unavailable", ["feature", "owner"])
def test_mail_unavailable_still_persists_inquiry(published_form, unavailable):
    client, org, _, site, host = published_form
    if unavailable == "feature":
        EntitlementSnapshot.all_objects.filter(organization=org).update(
            features={"sites.enabled": True}
        )
    else:
        Membership.objects.filter(organization=org).update(
            status="revoked", revoked_at=timezone.now()
        )
    result = submit(site, host)
    assert result.status_code == 201, result.data
    inquiry = SiteInquiry.all_objects.get(id=result.data["reference"])
    assert inquiry.notification_message_id is None
    assert not NotificationMessage.all_objects.exists()
    if unavailable == "feature":
        detail = client.get(f"/api/v1/sites/inquiries/{inquiry.id}/")
        assert detail.data["email_status"] == "unavailable"


def test_inbox_pagination_mark_read_csrf_and_foreign_tenant(published_form):
    client, org, _, site, host = published_form
    first = submit(site, host).data["reference"]
    second = submit(site, host, key="inquiry-two").data["reference"]
    listing = client.get(f"/api/v1/sites/{site.id}/inquiries/?limit=1")
    assert listing.status_code == 200, listing.data
    assert [str(row["id"]) for row in listing.data["items"]] == [str(second)]
    cursor = listing.data["next_cursor"]
    page2 = client.get(f"/api/v1/sites/{site.id}/inquiries/?limit=1&cursor={cursor}")
    assert str(page2.data["items"][0]["id"]) == str(first)
    assert page2.data["next_cursor"] is None
    detail_url = f"/api/v1/sites/inquiries/{first}/"
    assert client.get(detail_url).data["read_at"] is None
    assert client.post(f"{detail_url}read/", {}, format="json").status_code == 403
    read = client.post(
        f"{detail_url}read/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="read-one",
    )
    assert read.status_code == 200 and read.data["read_at"] is not None, read.data
    retry = client.post(
        f"{detail_url}read/",
        {},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
        HTTP_IDEMPOTENCY_KEY="read-two",
    )
    assert retry.data == read.data
    assert (
        OrganizationAuditEntry.objects.filter(organization=org, action="sites.inquiry.read").count()
        == 1
    )
    other, _, _ = sites_client(slug="inquiry-other", role_key="owner")
    assert other.get(f"/api/v1/sites/{site.id}/inquiries/").status_code == 404
    assert other.get(detail_url).status_code == 404
    assert (
        other.post(
            f"{detail_url}read/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=csrf_value(other),
            HTTP_IDEMPOTENCY_KEY="foreign-read",
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "denial", ["anonymous", "permission", "entitlement", "context", "suspended"]
)
@pytest.mark.parametrize("method", ["list", "detail", "read"])
def test_inbox_denials_do_not_read_inquiries(denial, method):
    client, org, _ = sites_client(
        slug=f"inquiry-{denial}",
        role_key="viewer" if denial == "permission" else "owner",
        feature_enabled=denial != "entitlement",
    )
    if denial == "anonymous":
        client = APIClient()
    elif denial == "context":
        Membership.objects.filter(organization=org).delete()
    elif denial == "suspended":
        org.status = OrganizationStatus.SUSPENDED
        org.save()
    identifier = uuid7()
    with CaptureQueriesContext(connection) as queries:
        if method == "list":
            result = client.get(f"/api/v1/sites/{identifier}/inquiries/")
        elif method == "detail":
            result = client.get(f"/api/v1/sites/inquiries/{identifier}/")
        else:
            headers = {} if denial == "anonymous" else {"HTTP_X_CSRFTOKEN": csrf_value(client)}
            result = client.post(
                f"/api/v1/sites/inquiries/{identifier}/read/",
                {},
                format="json",
                HTTP_IDEMPOTENCY_KEY="denied",
                **headers,
            )
    assert result.status_code in (403, 409), result.data
    assert not any('FROM "sites_siteinquiry"' in q["sql"] for q in queries.captured_queries)


def test_public_denies_disabled_suspended_and_unpublished_site(published_form):
    _, org, _, site, host = published_form
    EntitlementSnapshot.all_objects.filter(organization=org).update(
        features={"sites.enabled": False}
    )
    assert submit(site, host).status_code == 403
    org.status = OrganizationStatus.SUSPENDED
    org.save()
    assert submit(site, host).status_code == 404
    org.status = OrganizationStatus.ACTIVE
    org.save()
    Site.all_objects.filter(id=site.id).update(current_publication=None)
    assert submit(site, host).status_code == 404
    assert not SiteInquiry.all_objects.exists()


def test_anonymous_form_ignores_foreign_logged_in_tenant(published_form):
    _, org, _, site, host = published_form
    other, _, _ = sites_client(slug="foreign-submit", role_key="owner")
    response = submit(site, host, client=other)
    assert response.status_code == 201, response.data
    assert SiteInquiry.all_objects.get(id=response.data["reference"]).organization_id == org.id


def test_inquiry_rls_and_cross_tenant_foreign_keys(published_form):
    _, org, _, site, host = published_form
    assert submit(site, host).status_code == 201
    inquiry = SiteInquiry.all_objects.get()
    other, foreign, _ = sites_client(slug="inquiry-foreign", role_key="owner")
    foreign_site = create_site(other).data["id"]
    with pytest.raises(DatabaseError), transaction.atomic():
        SiteInquiry.all_objects.filter(id=inquiry.id).update(site_id=foreign_site)
    with pytest.raises(DatabaseError), transaction.atomic():
        SiteInquiry.all_objects.filter(id=inquiry.id).update(
            organization_id=foreign.id, site_id=foreign_site
        )
    role = connection.ops.quote_name(f"inquiry_rls_{uuid7().hex}")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE oid = 'sites_siteinquiry'::regclass"
        )
        assert cursor.fetchone() == (True, True)
        cursor.execute(f"CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS NOLOGIN")
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
        cursor.execute(f"GRANT SELECT ON sites_siteinquiry TO {role}")
        cursor.execute(f"SET LOCAL ROLE {role}")
        for tenant, expected in [("", 0), (str(foreign.id), 0), (str(org.id), 1)]:
            cursor.execute("SET LOCAL app.organization_id = %s", [tenant])
            cursor.execute("SELECT COUNT(*) FROM sites_siteinquiry")
            assert cursor.fetchone()[0] == expected
        cursor.execute("RESET ROLE")


def test_inquiry_and_notification_roll_back_together(published_form, monkeypatch):
    _, _, _, site, host = published_form

    def fail_audit(**kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr("saas_core.modules.shared.sites.inquiries.record_audit", fail_audit)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        submit(site, host)
    assert not SiteInquiry.all_objects.exists()
    assert not NotificationMessage.all_objects.exists()
    assert not PendingTaskRoute.objects.filter(kind="email").exists()


@pytest.mark.parametrize(
    "permissions", [set(), {"sites.inquiry.submit", "site.publish"}, {"booking.public.read"}]
)
def test_inquiry_service_task_rejects_wrong_scope(permissions):
    _, organization, _ = sites_client(slug="inquiry-task", role_key="owner")
    with (
        public_inquiry_context(organization.id) as context,
        activate_tenant_context(replace(context, permissions=frozenset(permissions))),
    ):
        contract = issue_tenant_task_contract(causation_id="inquiry-task")
    with pytest.raises(InvalidTenantTaskContext), tenant_task_context(contract):
        pass
    assert current_tenant_context() is None


def test_inquiry_service_task_rechecks_organization_activity():
    _, org, _ = sites_client(slug="inquiry-task-inactive", role_key="owner")
    with public_inquiry_context(org.id):
        contract = issue_tenant_task_contract(causation_id="inquiry-task")
    with tenant_task_context(contract) as context:
        assert context.role_key == "public_site_inquiry"
    org.status = OrganizationStatus.SUSPENDED
    org.save()
    with pytest.raises(InvalidTenantTaskContext), tenant_task_context(contract):
        pass


def test_stale_address_is_a_conflict_and_existing_receipt_survives_republish(published_form):
    client, _, _, site, host = published_form
    accepted = submit(site, host)
    assert accepted.status_code == 201
    original_publication = str(site.current_publication_id)
    # Same address, newer publication: replay returns the original receipt.
    assert (
        publish_site_request(client, str(site.id), idempotency_key="publish-again").status_code
        == 201
    )
    retry = submit(site, host)
    assert retry.status_code == 200 and retry.data == accepted.data
    stale = submit(site, host, key="new-stale-request")
    assert stale.status_code == 409
    page_id = site.pages.get().id
    moved = client.put(
        f"/api/v1/sites/pages/{page_id}/url/",
        {"locale": "pl", "slug": "new-contact", "reason": "Rename contact page"},
        format="json",
        HTTP_X_CSRFTOKEN=csrf_value(client),
    )
    assert moved.status_code == 200, moved.data
    assert (
        publish_site_request(client, str(site.id), idempotency_key="publish-renamed").status_code
        == 201
    )
    response = submit(
        site, host, key="renamed-form", publication_id=original_publication, path="/contact/"
    )
    assert response.status_code == 409
    assert response.data["code"] == "site_inquiry_publication_changed"
    assert SiteInquiry.all_objects.count() == 1


def test_broker_failure_keeps_outbox_and_retry_does_not_duplicate(
    published_form, monkeypatch, django_capture_on_commit_callbacks
):
    _, _, _, site, host = published_form

    def unavailable(*args, **kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(
        "saas_core.modules.shared.notifications.tasks.deliver_email_task.delay", unavailable
    )
    with (
        pytest.raises(RuntimeError, match="broker unavailable"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = submit(site, host)
        assert response.status_code == 201
    assert SiteInquiry.all_objects.count() == NotificationMessage.all_objects.count() == 1
    assert PendingTaskRoute.objects.filter(kind="email").count() == 1
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        retry = submit(site, host)
    assert retry.status_code == 200
    assert callbacks == []
    assert retry.data == response.data


def test_host_throttle_normalizes_ports_case_and_trailing_dot():
    from rest_framework.request import Request
    from rest_framework.test import APIRequestFactory

    from saas_core.modules.shared.sites.inquiry_views import InquiryHostThrottle

    throttle = InquiryHostThrottle()
    keys = {
        throttle.get_cache_key(Request(APIRequestFactory().post(PUBLIC_URL, HTTP_HOST=host)), None)
        for host in [
            "form.example.test",
            "FORM.EXAMPLE.TEST",
            "form.example.test.",
            "form.example.test:443",
            "form.example.test:8443",
        ]
    }
    assert len(keys) == 1


def test_automation_cannot_read_private_inquiries(published_form):
    from saas_core.modules.core.organizations.context import context_from_membership
    from saas_core.modules.shared.sites.inquiries import list_site_inquiries
    from saas_core.modules.shared.sites.services import PersonRequired

    _, org, _, site, _ = published_form
    member = Membership.objects.select_related("role").get(organization=org)
    context = replace(context_from_membership(member), principal_kind="service")
    with (
        activate_tenant_context(context),
        CaptureQueriesContext(connection) as queries,
        pytest.raises(PersonRequired),
    ):
        list_site_inquiries(site_id=site.id)
    assert not any('FROM "sites_siteinquiry"' in q["sql"] for q in queries.captured_queries)
