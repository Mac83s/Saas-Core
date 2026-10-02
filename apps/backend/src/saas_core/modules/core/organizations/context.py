from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from uuid import UUID

from django.db import connection

from .models import Membership

#: What a person's membership may act through, each with the one kind of
#: reference it names: `conversation:<uuid>`, `translation_job:<uuid>`
#: (ADR-076 §6). A new channel — `mcp`, say — is one entry here.
ACTING_VIA: dict[str, str] = {
    "assistant": "conversation",
    "ai_translation": "translation_job",
}

#: What set acting work going when the person did not click: `<kind>:<uuid>`.
ACTING_TRIGGER_KINDS = frozenset({"user", "api_key", "schedule", "conversation"})

#: The person-only operations (`assert_person_required` labels, ADR-035 §4)
#: an acting context may ever reach, per `acting_via` — a ceiling, not an
#: opening. A label opens only for one run that a person's consent covers: the
#: command executor sets `acting_opened` for the call it runs (assistant), and
#: the translation worker from the consent stored on its job (ADR-069).
ACTING_PERSON_GATE_ALLOWED: dict[str, frozenset[str]] = {
    # Removing a company language, with the person's click on the consent that
    # shows which language goes (ADR-071 pkt 5: a high-risk command).
    "assistant": frozenset({"Usunięcie języka firmy"}),
}


class MissingTenantContext(RuntimeError):
    pass


class TenantContextTransactionRequired(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TenantContext:
    organization_id: UUID
    membership_id: UUID
    actor_id: UUID
    role_key: str
    permissions: frozenset[str]
    principal_kind: str = "membership"
    # Which credential is acting, when one is. `core` deliberately does not know
    # what kind of credential that is — it only carries the id so a module that
    # does can narrow what this request may touch.
    credential_id: UUID | None = None
    # The membership acting for its person through something else (ADR-076
    # §6): through what, for which conversation or job, and what set it going.
    # Only server code sets them, from server rows; they never widen the
    # role, the permissions or the principal. See `acting_context`.
    acting_via: str = ""
    acting_ref: str = ""
    acting_trigger: str = ""
    #: The person-only labels this one run may pass, within the ceiling
    #: `ACTING_PERSON_GATE_ALLOWED[acting_via]`. Never carried into deferred
    #: work: a task rebuilt from the membership starts with none.
    acting_opened: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.acting_via or self.acting_ref or self.acting_trigger or self.acting_opened:
            _check_acting(self)

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


def acting_context(
    context: TenantContext,
    *,
    via: str,
    ref: str,
    trigger: str = "",
) -> TenantContext:
    """The same membership, acting for its person through `via` (ADR-076 §6).

    Rights stay exactly the membership's; the person-only gates refuse it
    unless a consent opens a label for one run (`acting_opened`).
    """
    if context.acting_via:
        raise ValueError("Kontekst już działa w imieniu osoby; bez zagnieżdżania.")
    if via not in ACTING_VIA:
        raise ValueError(f"Nieznany kanał działania w imieniu osoby: {via!r}.")
    return replace(
        context, acting_via=via, acting_ref=ref, acting_trigger=trigger, acting_opened=frozenset()
    )


def _check_acting(context: TenantContext) -> None:
    ref_kind = ACTING_VIA.get(context.acting_via)
    if ref_kind is None:
        raise ValueError(f"Nieznany kanał działania w imieniu osoby: {context.acting_via!r}.")
    if context.principal_kind != "membership":
        raise ValueError("W imieniu osoby działa tylko jej membership.")
    if not _is_reference(context.acting_ref, frozenset({ref_kind})):
        raise ValueError(f"acting_ref musi mieć postać {ref_kind}:<uuid>.")
    if context.acting_trigger and not _is_reference(context.acting_trigger, ACTING_TRIGGER_KINDS):
        raise ValueError("acting_trigger musi być pusty albo mieć postać <rodzaj>:<uuid>.")
    if context.acting_opened - ACTING_PERSON_GATE_ALLOWED.get(context.acting_via, frozenset()):
        raise ValueError("acting_opened wykracza poza etykiety dozwolone dla tego kanału.")


def _is_reference(value: object, kinds: frozenset[str]) -> bool:
    """`<kind>:<uuid>` with a known kind and the uuid in canonical form, so
    one conversation or job is always the same string in the history."""
    if not isinstance(value, str):
        return False
    kind, separator, identifier = value.partition(":")
    if not separator or kind not in kinds:
        return False
    try:
        return str(UUID(identifier)) == identifier
    except ValueError:
        return False


_active_tenant: ContextVar[TenantContext | None] = ContextVar(
    "active_tenant",
    default=None,
)


def context_from_membership(membership: Membership) -> TenantContext:
    permissions = frozenset(
        permission
        for permission in membership.role.permissions
        if isinstance(permission, str) and permission
    )
    return TenantContext(
        organization_id=membership.organization_id,
        membership_id=membership.id,
        actor_id=membership.user_id,
        role_key=membership.role.key,
        permissions=permissions,
    )


def current_tenant_context() -> TenantContext | None:
    return _active_tenant.get()


def require_tenant_context() -> TenantContext:
    context = current_tenant_context()
    if context is None:
        raise MissingTenantContext("Operacja wymaga aktywnego tenant context.")
    return context


@contextmanager
def activate_tenant_context(context: TenantContext) -> Iterator[TenantContext]:
    token = _active_tenant.set(context)
    try:
        yield context
    finally:
        _active_tenant.reset(token)


def set_local_organization_id(organization_id: UUID) -> None:
    if not connection.in_atomic_block:
        raise TenantContextTransactionRequired(
            "SET LOCAL tenant context wymaga aktywnej transakcji."
        )
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.organization_id = %s", [str(organization_id)])
