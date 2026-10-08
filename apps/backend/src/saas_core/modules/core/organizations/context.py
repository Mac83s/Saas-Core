from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass, replace
from uuid import UUID

from django.db import DatabaseError, connection, transaction

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
    # Accepting or discarding an AI translation, and consenting to translate
    # changes without a click — each with the click on the consent that names
    # it (ADR-069 pkt 28); the automation also needs a second factor.
    "assistant": frozenset({
        "Usunięcie języka firmy",
        "Decyzja o tłumaczeniu AI",
        "Zgoda na automat tłumaczeń",
    }),
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


@contextmanager
def only_tenant_context_of(organization_id: UUID) -> Iterator[None]:
    """Nobody's membership of another organization is in force in the block.

    A visitor signed in to the panel carries their own company's context on
    every request of that origin. Where a block works in another tenant, a
    service in it that asked for the context would act as that company while
    the database is set to the other — so the context is hidden, and such a
    service refuses exactly as it does for a visitor nobody knows.
    """
    active = _active_tenant.get()
    if active is None or active.organization_id == organization_id:
        yield
        return
    token = _active_tenant.set(None)
    try:
        yield
    finally:
        _active_tenant.reset(token)


def set_local_organization_id(organization_id: UUID) -> None:
    if not connection.in_atomic_block:
        raise TenantContextTransactionRequired(
            "SET LOCAL tenant context wymaga aktywnej transakcji."
        )
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL app.organization_id = %s", [str(organization_id)])


def local_organization_setting() -> str:
    """What `app.organization_id` is set to now; "" when nothing set it."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.organization_id', true)")
        row = cursor.fetchone()
    return str(row[0] or "") if row else ""


def restore_local_organization_setting(value: str) -> None:
    """Puts back what `local_organization_setting` read, for the rest of the
    transaction: a setting made inside a savepoint outlives its release."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.organization_id', %s, true)", [value])


@contextmanager
def tenant_setting_kept() -> Iterator[None]:
    """Whatever the block sets `app.organization_id` to, the caller has back
    what it had.

    `SET LOCAL` lasts to the end of the transaction, not of the savepoint it
    was made in. Work that sets a tenant inside somebody's open transaction
    would leave the rest of that transaction running as that tenant; this
    reads the setting on the way in and puts it back on the way out.

    Nothing is asked where no transaction is open — the work's own
    transaction then ends, and its setting with it. A transaction is open
    inside `atomic()` and also where the caller switched autocommit off: the
    work's `atomic()` is only a savepoint there too.
    """
    if not (connection.in_atomic_block or not connection.get_autocommit()):
        yield
        return
    found = local_organization_setting()
    try:
        yield
    except BaseException:
        # A savepoint rolled back took its setting with it, but one released
        # earlier in the work did not. Where the whole transaction is lost
        # the setting is lost with it, and there is nothing to ask.
        with suppress(DatabaseError):
            restore_local_organization_setting(found)
        raise
    restore_local_organization_setting(found)


@contextmanager
def tenant_block(organization_id: UUID) -> Iterator[None]:
    """One transaction inside that organization's tenant, leaving nothing of
    it behind: the caller's own tenant setting is put back
    (`tenant_setting_kept`) and nobody's membership of another organization
    is in force meanwhile (`only_tenant_context_of`).

    For the places that enter a tenant no request named — the platform's
    workspace on its own host. A request that has its tenant sets it as ever.
    """
    with tenant_setting_kept(), only_tenant_context_of(organization_id), transaction.atomic():
        set_local_organization_id(organization_id)
        yield
