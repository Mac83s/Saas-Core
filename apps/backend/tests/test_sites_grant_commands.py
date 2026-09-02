"""The operator's grant commands under forced row-level security (ADR-039).

`notifications_apikey` and `sites_contentautomationgrant` carry forced RLS, so
a read that happens before `SET LOCAL app.organization_id` returns nothing —
and the test database, which connects as the table owner, would never notice.
What can be asserted regardless of role is the order of the queries: the
tenant setting must come before the first touch of either table.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.auth.hashers import make_password
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from test_platform_workspace import confirm_mfa, operator
from test_sites_api import create_site, sites_client

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_cache() -> None:
    """Each test signs several people in; the login limiter lives in the cache."""
    cache.clear()


GUARDED_TABLES = ("notifications_apikey", "sites_contentautomationgrant")


def _api_key(organization: Any, user: Any) -> Any:
    from saas_core.modules.shared.notifications.models import ApiKey

    raw = "sc_live_" + "g" * 32
    return ApiKey.all_objects.create(
        organization=organization,
        name="SeoContentRank",
        prefix=raw[:18],
        secret_hash=make_password(raw),
        scopes=["content:read", "content:draft"],
        created_by=user,
    )


def _assert_tenant_set_before_guarded_reads(
    queries: list[dict[str, str]], *, tables: tuple[str, ...] = GUARDED_TABLES
) -> None:
    sql = [query["sql"] for query in queries]
    tenant_index = next(
        (index for index, statement in enumerate(sql) if "app.organization_id" in statement),
        None,
    )
    assert tenant_index is not None, "komenda nigdy nie ustawiła tenanta"
    for table in tables:
        first_touch = next(
            (index for index, statement in enumerate(sql) if table in statement), None
        )
        assert first_touch is not None, f"komenda nie dotknęła {table}"
        assert tenant_index < first_touch, (
            f"{table} odczytana przed SET LOCAL — pod rolą aplikacji odpowiedź byłaby pusta"
        )


def test_issuing_a_grant_sets_the_tenant_before_reading_the_key() -> None:
    client, organization, user = sites_client(slug="grant-issue", role_key="owner")
    site_id = create_site(client).data["id"]
    key = _api_key(organization, user)
    person = operator(email="grant-operator@example.test")
    confirm_mfa(person)

    with CaptureQueriesContext(connection) as captured:
        call_command(
            "issue_content_grant",
            operator=person.email,
            organization=str(organization.id),
            api_key=str(key.id),
            site=site_id,
            mode="draft_write",
        )

    from saas_core.modules.shared.sites.models import ContentAutomationGrant

    grant = ContentAutomationGrant.all_objects.get(credential_id=key.id)
    assert grant.organization_id == organization.id
    assert grant.mode == "draft_write"
    _assert_tenant_set_before_guarded_reads(captured.captured_queries)


def test_issuing_refuses_a_key_from_another_organization() -> None:
    client, organization, user = sites_client(slug="grant-own", role_key="owner")
    site_id = create_site(client).data["id"]
    _other_client, other_organization, other_user = sites_client(
        slug="grant-other", role_key="owner"
    )
    foreign_key = _api_key(other_organization, other_user)
    person = operator(email="grant-operator-2@example.test")
    confirm_mfa(person)

    with pytest.raises(CommandError, match="nie istnieje w tej organizacji"):
        call_command(
            "issue_content_grant",
            operator=person.email,
            organization=str(organization.id),
            api_key=str(foreign_key.id),
            site=site_id,
            mode="draft_write",
        )


def test_revoking_a_grant_sets_the_tenant_before_reading_it() -> None:
    from saas_core.modules.shared.sites.models import ContentAutomationGrant

    client, organization, user = sites_client(slug="grant-revoke", role_key="owner")
    site_id = create_site(client).data["id"]
    key = _api_key(organization, user)
    grant = ContentAutomationGrant.all_objects.create(
        organization=organization,
        credential_id=key.id,
        site_id=site_id,
        mode="draft_write",
        created_by=user,
    )
    # The operator revokes from inside the organization, so the member who
    # owns it is also the operator here.
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    confirm_mfa(user)

    with CaptureQueriesContext(connection) as captured:
        call_command(
            "revoke_content_grant",
            operator=user.email,
            organization=str(organization.id),
            grant=str(grant.id),
            reason="Test odwołania.",
        )

    grant.refresh_from_db()
    assert grant.revoked_at is not None
    # Revocation never looks at the key itself; the grant is the only guarded read.
    _assert_tenant_set_before_guarded_reads(
        captured.captured_queries, tables=("sites_contentautomationgrant",)
    )

    # Safe to repeat, and the wrong organization is a refusal, not a search.
    call_command(
        "revoke_content_grant",
        operator=user.email,
        organization=str(organization.id),
        grant=str(grant.id),
        reason="Ponownie.",
    )
    _other_client, other_organization, _other_user = sites_client(
        slug="grant-elsewhere", role_key="owner"
    )
    with pytest.raises(CommandError, match="członkostwa"):
        call_command(
            "revoke_content_grant",
            operator=user.email,
            organization=str(other_organization.id),
            grant=str(grant.id),
            reason="Nie moja organizacja.",
        )
