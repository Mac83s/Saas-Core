"""Erasing a tenant, for real (ADR-042).

Article 17 is not satisfied by an organization that cannot be removed. Until
this existed, one that had ever attached a file or written an audit entry — so
every real one — was undeletable, and the personal data of *its customers'
customers* stayed in reservations, notification payloads and publication
snapshots.

The append-only guards are not weakened in general. They open for a delete of
rows belonging to the organization named in ``app.erasing_organization_id`` and
for nothing else, and that name is set in exactly one place: `_erasing` below.
A test counts the call sites, the same way ADR-041 counts the pre-tenant door.

What this does not defend against: somebody who already holds the application's
database credentials can set the same variable. No layer inside the database
changes that. It defends against a bug, and it makes the intent visible in
review and in the receipt.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import DatabaseError, ProgrammingError, connection, transaction
from django.db.models import ForeignKey, Model

from saas_core.modules.core.identity.models import User

from .context import TenantContext, activate_tenant_context, set_local_organization_id
from .erasure_checks import check_erasure_preconditions
from .models import ErasureReceipt, Organization
from .pre_tenant import PRE_TENANT_DB

#: The one session variable that opens the append-only guards.
ERASURE_SETTING = "app.erasing_organization_id"


class ErasureBlocked(RuntimeError):
    """The database refused, and an operator command may not talk its way past."""


@contextmanager
def _erasing(organization_id: uuid.UUID) -> Iterator[None]:
    """Declares which organization is being erased, for this transaction only.

    `SET LOCAL` dies with the transaction, so nothing can leave the flag on. The
    value is the organization's identifier rather than a boolean: a flag turned
    on by mistake would open every tenant's history at once.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"SET LOCAL {ERASURE_SETTING} = %s", [str(organization_id)])
    yield


def organization_scoped_models() -> list[tuple[type[Model], str]]:
    """Every model that names an organization, with the field that names it.

    Discovered from the model metadata rather than declared, so a module added
    later is covered without touching this file. Where a model has more than one
    such field the first one wins — that is the tenant it belongs to.
    """
    scoped: list[tuple[type[Model], str]] = []
    for model in apps.get_models():
        if model is Organization:
            continue
        for field in model._meta.get_fields():
            if isinstance(field, ForeignKey) and field.related_model is Organization:
                scoped.append((model, field.name))
                break
    return scoped


def _erasure_context(organization_id: uuid.UUID) -> TenantContext:
    """A context that exists only so tenant-scoped managers can answer.

    Deletion reads through ``TenantScopedManager``, which refuses without one.
    It grants no permission: authorization happened before this was called.
    """
    return TenantContext(
        organization_id=organization_id,
        membership_id=uuid.uuid7(),
        actor_id=uuid.uuid7(),
        role_key="erasure",
        permissions=frozenset(),
    )


def stored_object_keys(organization_id: uuid.UUID) -> list[str]:
    """Object-storage keys the tenant owns, found by convention.

    Core may not import Shared, so this asks the model metadata rather than the
    media module: any tenant model with an ``object_key`` column holds something
    outside PostgreSQL. Deleting those objects is the media module's job — this
    only writes down what has to go.
    """
    keys: list[str] = []
    for model, field_name in organization_scoped_models():
        columns = {field.name for field in model._meta.fields}
        if "object_key" not in columns:
            continue
        keys.extend(
            model._base_manager.filter(**{f"{field_name}_id": organization_id})
            .exclude(object_key="")
            .values_list("object_key", flat=True)
        )
    return sorted(set(keys))


def _break_reference_cycles(organization_id: uuid.UUID) -> None:
    """Clear the nullable links tenant rows hold to each other.

    A site points at its current publication and the publication points back at
    its site, so neither can be deleted first. Nulling the optional half of such
    a pair costs nothing — the row is going away — and turns the graph into
    something that can be emptied in passes.
    """
    scoped = {model for model, _field in organization_scoped_models()}
    for model, field_name in organization_scoped_models():
        optional = {
            field.name: None
            for field in model._meta.fields
            if isinstance(field, ForeignKey) and field.null and field.related_model in scoped
        }
        if not optional:
            continue
        try:
            with transaction.atomic():
                model._base_manager.filter(**{f"{field_name}_id": organization_id}).update(
                    **optional
                )
        except (DatabaseError, ValidationError):
            continue


def row_counts(organization_id: uuid.UUID) -> dict[str, int]:
    """What is there to erase, per table. Also the proof afterwards: all zero."""
    counts: dict[str, int] = {}
    for model, field_name in organization_scoped_models():
        found = model._base_manager.filter(**{f"{field_name}_id": organization_id}).count()
        if found:
            counts[model._meta.label] = found
    return counts


def erase_organization(
    *,
    organization: Organization,
    requested_by: User | None,
    reason: str,
) -> ErasureReceipt:
    """Delete a tenant's rows, then say what is left to delete outside the database.

    Order is a decision, not a detail: PostgreSQL cannot roll back object
    storage, so the rows go first and commit, and only then does anything remove
    a file. The other order would destroy files even when the transaction failed.
    """
    organization_id = organization.id
    slug = organization.slug
    with transaction.atomic():
        set_local_organization_id(organization_id)
        with activate_tenant_context(_erasure_context(organization_id)), _erasing(
            organization_id
        ):
            Organization.objects.select_for_update().get(pk=organization_id)
            check_erasure_preconditions(organization_id)
            counts = row_counts(organization_id)
            object_keys = stored_object_keys(organization_id)
            _break_reference_cycles(organization_id)

            remaining = organization_scoped_models()
            while remaining:
                blocked: list[tuple[type[Model], str]] = []
                progressed = False
                for model, field_name in remaining:
                    rows = model._base_manager.filter(**{f"{field_name}_id": organization_id})
                    try:
                        with transaction.atomic():
                            deleted, _by_model = rows.delete()
                    except (ProgrammingError, DatabaseError):
                        blocked.append((model, field_name))
                        continue
                    if deleted:
                        progressed = True
                if not progressed and blocked:
                    labels = ", ".join(model._meta.label for model, _field in blocked)
                    raise ErasureBlocked(
                        f"Nie da się usunąć organizacji {slug}: baza odmawia dla {labels}."
                    )
                remaining = blocked

            Organization.objects.filter(pk=organization_id).delete()

        receipt = ErasureReceipt.objects.create(
            organization_id=organization_id,
            requested_by=requested_by,
            reason=reason.strip(),
            row_counts=counts,
            pending_object_keys=object_keys,
        )
    return receipt


def erasure_is_complete(organization_id: uuid.UUID) -> dict[str, Any]:
    """The four conditions from ADR-042 §8, answered as data.

    Storage is answered by the media sweep rather than here; what this reports is
    what the database can see: rows left, and objects still waiting.
    """
    receipt = (
        ErasureReceipt.objects.filter(organization_id=organization_id)
        .order_by("-started_at")
        .first()
    )
    return {
        "rows": row_counts(organization_id),
        # Through the door: "does this organization still exist" is a
        # question about the registry, and after erasure there is no tenant
        # it could be asked inside.
        "organization": Organization.objects.using(PRE_TENANT_DB)
        .filter(pk=organization_id)
        .count(),
        "receipt": receipt.id if receipt is not None else None,
        "pending_objects": list(receipt.pending_object_keys) if receipt else None,
    }
