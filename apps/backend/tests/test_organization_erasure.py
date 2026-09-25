"""Erasing a tenant is real deletion, and the escape it needs is counted.

ADR-042 weakens an invariant on purpose: the append-only guards open for the
organization named in `app.erasing_organization_id`. A weakened invariant is
only acceptable while somebody can say exactly where it is weakened, so half of
this file is that count, and the other half is the proof that erasure leaves
nothing behind.

The suite connects as the owner of the tables, so it says nothing about
row-level security — but triggers apply to owners too, which is why the guard
and its escape *can* be tested here.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid7

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connection, transaction

from saas_core.modules.core.organizations.audit import record_audit
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.core.organizations.erasure import (
    ERASURE_SETTING,
    erase_organization,
    erasure_is_complete,
    row_counts,
    stored_object_keys,
)
from saas_core.modules.core.organizations.models import (
    ErasureReceipt,
    Membership,
    Organization,
    OrganizationAuditAction,
    OrganizationAuditEntry,
    OrganizationStatus,
    Role,
)

SOURCE = Path(settings.BASE_DIR) / "src" / "saas_core"

#: Where the append-only escape may be opened. One place, on purpose: the guard
#: exists so the application cannot rewrite history, and an escape that spreads
#: is the guard being removed slowly instead of at once.
DECLARED_ESCAPE = {
    "modules/core/organizations/erasure.py": (
        1,
        "usunięcie tenanta: jedyne miejsce, które nazywa organizację do skasowania",
    ),
}

pytestmark = pytest.mark.django_db


def _organization(slug: str) -> Organization:
    organization = Organization(
        name=slug.title(), slug=slug, status=OrganizationStatus.ACTIVE
    )
    set_local_organization_id(organization.id)
    organization.save()
    return organization


def _operator() -> object:
    user_model = get_user_model()
    return user_model.objects.create_user(
        email=f"operator-{uuid7()}@example.test", password="Erasure-2026!"
    )


def _member(organization: Organization) -> Membership:
    return Membership.objects.create(
        organization=organization,
        user=_operator(),
        role=Role.objects.get(key="admin", organization=None, organization_type=""),
    )


def _audit(organization: Organization) -> OrganizationAuditEntry:
    return record_audit(
        organization=organization,
        action=OrganizationAuditAction.ORGANIZATION_CREATED,
        actor=None,
        target_type="organization",
        target_id=organization.id,
    )


def _escape_usage() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted(SOURCE.rglob("*.py")):
        relative = path.relative_to(SOURCE).as_posix()
        # Migrations define the guard and its escape in SQL; they are the rule,
        # not a place that uses it.
        if "/migrations/" in relative:
            continue
        uses = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if ERASURE_SETTING in line and not line.lstrip().startswith("#")
        ]
        if uses:
            # The module that defines the constant names it once by definition.
            count = len(uses) - (1 if relative.endswith("erasure.py") else 0)
            if count:
                found[relative] = count
    return found


def test_only_one_place_opens_the_append_only_guard() -> None:
    actual = _escape_usage()
    expected = {path: count for path, (count, _reason) in DECLARED_ESCAPE.items()}

    assert actual == expected, (
        "Furtka z ADR-042 rozjechała się z deklaracją. Dopisz nowe miejsce razem "
        f"z powodem albo usuń wpis, którego już nie ma: {actual}"
    )


def test_the_audit_log_still_refuses_an_ordinary_delete() -> None:
    """Without the escape the guard is exactly what it was."""
    organization = _organization("kasowanie-straz")
    entry = _audit(organization)

    with pytest.raises(DatabaseError), transaction.atomic():
        OrganizationAuditEntry.objects.filter(pk=entry.id).delete()


def test_the_escape_opens_only_for_the_organization_it_names() -> None:
    mine = _organization("kasowanie-moje")
    stranger = _organization("kasowanie-obce")
    theirs = _audit(stranger)

    with pytest.raises(DatabaseError), transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(f"SET LOCAL {ERASURE_SETTING} = %s", [str(mine.id)])
        OrganizationAuditEntry.objects.filter(pk=theirs.id).delete()


def test_erasure_leaves_no_row_and_writes_a_receipt() -> None:
    organization = _organization("kasowanie-pelne")
    _member(organization)
    _audit(organization)
    operator = _operator()
    before = row_counts(organization.id)
    assert before, "test nie miałby czego usuwać"

    receipt = erase_organization(
        organization=organization,
        requested_by=operator,
        reason="Klient poprosił o usunięcie danych.",
    )

    state = erasure_is_complete(organization.id)
    assert state["rows"] == {}
    assert state["organization"] == 0
    assert receipt.row_counts == before
    assert receipt.reason.startswith("Klient poprosił")


def test_the_receipt_keeps_counts_and_no_content() -> None:
    """Accountability means showing it happened, not keeping a copy."""
    organization = _organization("kasowanie-pokwitowanie")
    _member(organization)
    erase_organization(
        organization=organization,
        requested_by=_operator(),
        reason="Zakończenie współpracy i żądanie usunięcia.",
    )

    receipt = ErasureReceipt.objects.get(organization_id=organization.id)
    stored = {
        field.name
        for field in receipt._meta.fields
        if isinstance(getattr(receipt, field.name, None), str)
    }

    assert "name" not in stored
    assert "slug" not in stored
    assert organization.name not in str(receipt.row_counts)
    assert set(receipt.row_counts) <= {
        label for label, _count in ((k, v) for k, v in receipt.row_counts.items())
    }


def test_erasing_a_tenant_does_not_erase_the_people() -> None:
    """An account belongs to its person and leaves by its own path (ADR-036 §8)."""
    organization = _organization("kasowanie-konta")
    membership = _member(organization)
    user_id = membership.user_id

    erase_organization(
        organization=organization,
        requested_by=_operator(),
        reason="Firma zamknięta, konta zostają ich właścicieli.",
    )

    assert get_user_model().objects.filter(pk=user_id).exists()
    assert Membership.objects.using("default").filter(user_id=user_id).count() == 0


def test_erasure_lists_every_stored_object_of_a_media_asset() -> None:
    """ADR-042 gap: only the `object_key` column used to be collected, so a
    kept source original and every WebP variant outlived the tenant."""
    from django.utils import timezone

    from saas_core.modules.shared.media.models import MediaAsset

    organization = _organization("kasowanie-media")
    member = _member(organization)
    asset_id = uuid7()
    prefix = f"{organization.id}"
    variant_keys = {
        f"{prefix}/variants/{asset_id}/preview.webp",
        f"{prefix}/variants/{asset_id}/thumbnail.webp",
    }
    asset = MediaAsset.all_objects.create(
        id=asset_id,
        organization=organization,
        original_filename="evidence.jpg",
        object_key=f"{prefix}/processed/{asset_id}/original.jpg",
        source_object_key=f"{prefix}/originals/{asset_id}.jpg",
        declared_mime="image/jpeg",
        expected_size=10,
        quota_reservation_key=f"erasure:{asset_id}",
        variants={
            key.rsplit("/", 1)[1].split(".")[0]: {"object_key": key} for key in variant_keys
        },
        upload_expires_at=timezone.now(),
        created_by=member.user,
        idempotency_key=f"erasure-{asset_id}",
        request_hash="0" * 64,
    )

    keys = stored_object_keys(organization.id)

    assert {asset.object_key, asset.source_object_key, *variant_keys} <= set(keys)
    assert keys == sorted(set(keys))


def test_erasure_takes_the_routing_indexes_that_name_the_tenant_without_a_key() -> None:
    """Pre-tenant routing rows keep a bare `organization_id`, so the discovery by
    foreign key missed them: a public slug outlived its tenant and would have
    routed a new organization of that slug to the erased one."""
    from django.utils import timezone

    from saas_core.modules.shared.booking.models import (
        PublicBookingRoute,
        ReminderRoute,
        SelfServiceRoute,
    )
    from saas_core.modules.shared.notifications.models import (
        ApiKeyCredentialRoute,
        ProviderMessageRoute,
    )

    other = _organization("trasa-zostaje")
    PublicBookingRoute.objects.create(public_slug=other.slug, organization_id=other.id)
    organization = _organization("trasa-znika")
    appointment_id = uuid7()
    PublicBookingRoute.objects.create(
        public_slug=organization.slug, organization_id=organization.id
    )
    SelfServiceRoute.objects.create(
        token_digest="a" * 64,
        organization_id=organization.id,
        appointment_id=appointment_id,
        expires_at=timezone.now(),
    )
    ReminderRoute.objects.create(
        appointment_id=appointment_id,
        organization_id=organization.id,
        signed_tenant_context="contract",
        due_at=timezone.now(),
    )
    ProviderMessageRoute.objects.create(
        provider_message_id="provider-1",
        organization_id=organization.id,
        message_id=uuid7(),
        tenant_context_ciphertext="contract",
    )
    ApiKeyCredentialRoute.objects.create(
        prefix="sck_test",
        api_key_id=uuid7(),
        organization_id=organization.id,
        secret_hash="hash",
    )
    before = row_counts(organization.id)
    for label in (
        "booking.PublicBookingRoute",
        "booking.SelfServiceRoute",
        "booking.ReminderRoute",
        "notifications.ProviderMessageRoute",
        "notifications.ApiKeyCredentialRoute",
    ):
        assert before[label] == 1, label

    receipt = erase_organization(
        organization=organization, requested_by=_operator(), reason="Test tras."
    )

    assert erasure_is_complete(organization.id)["rows"] == {}
    assert receipt.row_counts == before
    assert list(PublicBookingRoute.objects.values_list("organization_id", flat=True)) == [
        other.id
    ]
