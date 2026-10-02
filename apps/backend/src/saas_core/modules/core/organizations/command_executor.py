"""Running registered commands for a membership acting through a channel
(ADR-076 §1–§3).

`preview_plan` turns the calls a model proposed into what a person can consent
to. Every call is admitted (exposure, permission, module, arguments), previewed
without a write, passed by every registered gate and placed in the group one
click may cover; each group carries the digest its consent will bind.
`execute_plan` admits and previews everything again and runs what needs no
consent — reads, inside a transaction rolled back afterwards, so a read cannot
write whatever its declaration says. Groups that need consent are refused until
the consent token exists (A1b-5).

Nothing here trusts the list of tools a model was offered: a call by key or
tool name is checked as if it came from nowhere.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from django.core.exceptions import ImproperlyConfigured
from django.db import connection, transaction
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaViolation
from rest_framework.exceptions import (
    APIException,
    ErrorDetail,
    NotFound,
    PermissionDenied,
    ValidationError,
)
from rest_framework.settings import api_settings

from saas_core.http.exceptions import problem_code, problem_errors

from .authorization import authorize
from .canonical import canonical_json_hash
from .command_consent import ConsentDigestMismatch, read_consent
from .command_registry import (
    RISKS,
    CommandSpec,
    Preview,
    UnknownCommand,
    command,
    command_for_tool,
    organization_modules,
)
from .context import (
    ACTING_PERSON_GATE_ALLOWED,
    TenantContext,
    activate_tenant_context,
    require_tenant_context,
)
from .models import CommandReceipt

logger = logging.getLogger(__name__)

#: Raised whenever what a digest covers changes, so a consent given under the
#: old shape never matches a new preview.
CONTRACT_VERSION = 1
#: The plan features each channel needs on every call (ADR-076 §1, §8). A
#: downgrade during a conversation stops the next call, not the next login.
CHANNEL_FEATURES: dict[str, tuple[str, ...]] = {"assistant": ("assistant.text.enabled",)}
#: Gates without which nothing runs. Without billing a profile cannot say
#: whether a plan includes the assistant, so in core-only nothing does.
REQUIRED_GATES = frozenset({"features"})
#: Risks that need a click, and what makes a call need a click of its own.
_SHARED_RISKS = frozenset({"draft", "apply"})
_OWN_CLICK_MODIFIERS = frozenset({"bulk", "spends_credits"})
_STEP_UP_MODIFIERS = frozenset({"legal_document", "changes_billing"})
_KEY_NAMESPACE = uuid.UUID("5d3c7a52-8f0e-4b8e-9a43-2f6f1c0b7e11")

#: `gate(spec, context, arguments, preview)` → a refusal code, or None to pass.
CommandGate = Callable[[CommandSpec, TenantContext, Mapping[str, Any], Preview | None], str | None]
_gates: dict[str, CommandGate] = {}


class CommandUnavailable(NotFound):
    default_detail = "To polecenie nie jest dostępne."
    default_code = "command_unavailable"


class CommandArgumentsInvalid(ValidationError):
    problem_code = "command_args_invalid"


class CommandGateRefused(APIException):
    status_code = 403
    default_detail = "Polecenie jest teraz niedostępne."
    default_code = "command_gate_refused"

    def __init__(self, code: str) -> None:
        super().__init__()
        self.problem_code = code


class CommandPlanConflict(ValidationError):
    problem_code = "command_plan_conflict"


class ConsentRequired(PermissionDenied):
    default_detail = "To polecenie wymaga zgody osoby."
    default_code = "consent_required"


class StepUpRequired(PermissionDenied):
    default_detail = "To polecenie wymaga ponownego potwierdzenia kodem z aplikacji."
    default_code = "step_up_required"


class CommandIdempotencyConflict(APIException):
    status_code = 409
    default_detail = "Ten krok planu został już wykonany z innymi argumentami."
    default_code = "command_idempotency_conflict"


class CommandPartiallyApplied(APIException):
    status_code = 409
    default_detail = "Część planu została już wykonana; resztę trzeba zaproponować od nowa."
    default_code = "command_partially_applied"


class CommandInternalError(APIException):
    status_code = 500
    default_detail = "Polecenie nie powiodło się z powodu błędu po naszej stronie."
    default_code = "command_internal_error"


@dataclass(frozen=True, slots=True)
class Invocation:
    #: `name@version` or the tool name a model called.
    command: str
    arguments: Mapping[str, Any]
    #: Assigned by the server when it records the step, never by the model or
    #: the provider: the idempotency key derives from it (ADR-076 §3).
    step_id: str


@dataclass(frozen=True, slots=True)
class CommandCall:
    """What a command's preview and run get besides the arguments."""

    context: TenantContext
    idempotency_key: str
    #: The preview the consent bound; None while previewing.
    preview: Preview | None = None


@dataclass(frozen=True, slots=True)
class PlannedCall:
    step_id: str
    spec: CommandSpec
    arguments: Mapping[str, Any]
    idempotency_key: str
    preview: Preview | None
    risk: str
    step_up_required: bool

    def describe(self) -> dict[str, Any]:
        """The call as the digest binds it."""
        preview = self.preview
        return {
            "command": self.spec.key,
            "arguments": self.arguments,
            "idempotency_key": self.idempotency_key,
            "observed_versions": dict(preview.observed_versions) if preview else {},
            "effects": [
                {
                    "kind": effect.kind,
                    "resource": effect.resource,
                    "resource_id": effect.resource_id,
                    "summary": dict(effect.summary),
                }
                for effect in (preview.effects if preview else ())
            ],
            "quote": dict(preview.quote) if preview and preview.quote is not None else None,
            "risk": self.risk,
            "modifiers": sorted(self.spec.modifiers),
            "person_gates": sorted(preview.person_gates) if preview else [],
            "step_up_required": self.step_up_required,
        }


@dataclass(frozen=True, slots=True)
class ConsentGroup:
    """What one click covers, and the digest that click's token will bind."""

    digest: str
    calls: tuple[PlannedCall, ...]
    risk: str
    step_up_required: bool

    @property
    def id(self) -> str:
        """The group's first step: what a consent is handed back under."""
        return self.calls[0].step_id


@dataclass(frozen=True, slots=True)
class CallRefusal:
    step_id: str
    status: int
    code: str
    errors: tuple[Mapping[str, str | None], ...]


@dataclass(frozen=True, slots=True)
class Plan:
    """Reads run without a click; groups wait for one. A plan with any refusal
    has neither: the model fixes the refused calls and proposes the plan again,
    because a consent must cover the plan the person actually sees."""

    reads: tuple[PlannedCall, ...]
    groups: tuple[ConsentGroup, ...]
    refusals: tuple[CallRefusal, ...]


@dataclass(frozen=True, slots=True)
class CallResult:
    step_id: str
    #: done | refused | failed | skipped
    status: str
    output: Mapping[str, Any] | None = None
    code: str | None = None
    errors: tuple[Mapping[str, str | None], ...] = ()


def register_command_gate(name: str, gate: CommandGate) -> None:
    """One more check every call must pass, after its preview.

    Billing registers `features` (the channel's features, the command's extra
    features and entitlement); the company-settings registry adds its own for
    switches down to a single offer. Every gate must pass; a gate that raises
    refuses.
    """
    existing = _gates.get(name)
    if existing is not None and existing is not gate:
        raise ImproperlyConfigured(f"Bramka poleceń {name} jest już zarejestrowana.")
    _gates[name] = gate


def preview_plan(invocations: Sequence[Invocation]) -> Plan:
    context = _acting_context()
    planned: list[PlannedCall] = []
    refusals: list[CallRefusal] = []
    for invocation in invocations:
        try:
            planned.append(_plan_call(context, invocation))
        except APIException as error:
            refusals.append(_refusal(invocation.step_id, error))
        except Exception:
            logger.exception("command_internal_error", extra={"step_id": invocation.step_id})
            refusals.append(_refusal(invocation.step_id, CommandInternalError()))
    refusals += _conflicts(planned)
    if refusals:
        return Plan(reads=(), groups=(), refusals=tuple(refusals))
    reads = tuple(call for call in planned if call.risk == "read")
    return Plan(reads=reads, groups=_groups(context, planned), refusals=())


def execute_plan(
    invocations: Sequence[Invocation],
    consents: Mapping[str, str] | None = None,
) -> tuple[CallResult, ...]:
    """Runs a plan a person consented to, group by group (ADR-076 §3).

    `consents` maps a group's `id` to the token its click minted. Order matters:
    receipts first — a step that already ran answers with what it returned,
    because its own write changed the state a new preview would read; then a
    fresh preview of every group on the state before the plan, every token
    read against it, and only then any write. A group runs in a savepoint of
    its own: the first that fails is undone and the groups after it do not run,
    while the groups before it stay done.
    """
    context = _acting_context()
    replayed = _replayed(context, invocations)
    if replayed is not None:
        return replayed
    plan = preview_plan(invocations)
    if plan.refusals:
        refused = {refusal.step_id: refusal for refusal in plan.refusals}
        return tuple(
            _refused(refused[invocation.step_id])
            if invocation.step_id in refused
            else CallResult(step_id=invocation.step_id, status="skipped")
            for invocation in invocations
        )
    results = {call.step_id: _run_read(call) for call in plan.reads}
    verdicts = {group.id: _consent_verdict(context, group, consents or {}) for group in plan.groups}
    halted = False
    for group in plan.groups:
        verdict = verdicts[group.id]
        if halted:
            results.update({
                call.step_id: CallResult(step_id=call.step_id, status="skipped")
                for call in group.calls
            })
        elif verdict is not None:
            results.update({
                call.step_id: _refused(_refusal(call.step_id, verdict)) for call in group.calls
            })
        else:
            group_results = _run_group(context, group)
            results.update(group_results)
            halted = any(result.status != "done" for result in group_results.values())
    return tuple(results[invocation.step_id] for invocation in invocations)


def idempotency_key(context: TenantContext, spec: CommandSpec, step_id: str) -> str:
    return str(
        uuid.uuid5(
            _KEY_NAMESPACE,
            f"{context.organization_id}:{context.acting_ref}:{spec.key}:{step_id}",
        )
    )


def _acting_context() -> TenantContext:
    context = require_tenant_context()
    if not context.acting_via:
        # Commands are what a channel does for its person; the person in the
        # panel uses the panel's own endpoints.
        raise CommandUnavailable
    return context


def _plan_call(context: TenantContext, invocation: Invocation) -> PlannedCall:
    spec = _resolve(invocation.command)
    if context.acting_via not in spec.exposure:
        raise CommandUnavailable
    authorize(spec.permission)
    if spec.module not in organization_modules(context.organization_id):
        raise CommandUnavailable(code="module_not_available")
    arguments = _validated(spec, invocation.arguments)
    key = idempotency_key(context, spec, _step_id(invocation.step_id))
    preview = _preview(spec, arguments, CommandCall(context=context, idempotency_key=key))
    _pass_gates(spec, context, arguments, preview)
    risk, step_up_required = _risk(spec, preview)
    return PlannedCall(
        step_id=invocation.step_id,
        spec=spec,
        arguments=arguments,
        idempotency_key=key,
        preview=preview,
        risk=risk,
        step_up_required=step_up_required,
    )


def _resolve(name: str) -> CommandSpec:
    try:
        return command(name) if "@" in name else command_for_tool(name)
    except UnknownCommand:
        raise CommandUnavailable from None


def _step_id(value: str) -> str:
    if str(uuid.UUID(value)) != value:
        raise ValueError("step_id nadaje serwer jako kanoniczny UUID.")
    return value


def _validated(spec: CommandSpec, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    validator = Draft202012Validator(spec.input_schema)
    violations = sorted(validator.iter_errors(arguments), key=lambda error: list(error.path))
    if violations:
        raise CommandArgumentsInvalid(detail=_detail(violations))
    return arguments


def _detail(violations: list[SchemaViolation]) -> dict[str, Any]:
    """Violations as a DRF detail, so `problem_errors` names each field the way
    every other 400 does: `address.city`, `items.1.name` (ADR-076 §5)."""
    detail: dict[str, Any] = {}
    for violation in violations:
        for path in _paths(violation):
            node = detail
            for segment in path[:-1]:
                node = node.setdefault(segment, {})
            node.setdefault(path[-1], []).append(
                ErrorDetail(violation.message, code=str(violation.validator))
            )
    return detail


def _paths(violation: SchemaViolation) -> list[tuple[str, ...]]:
    base = tuple(str(segment) for segment in violation.path)
    instance = violation.instance if isinstance(violation.instance, Mapping) else {}
    if violation.validator == "required" and isinstance(violation.validator_value, list):
        # One violation per missing field; the field is the one it names.
        named = [name for name in violation.validator_value if name not in instance]
        missing = next((name for name in named if repr(name) in violation.message), None)
        return [(*base, str(missing))] if missing is not None else [base or (_whole(),)]
    if violation.validator == "additionalProperties" and isinstance(violation.schema, Mapping):
        known = set(violation.schema.get("properties") or {})
        return [(*base, str(name)) for name in instance if name not in known] or [base]
    return [base or (_whole(),)]


def _whole() -> str:
    return str(api_settings.NON_FIELD_ERRORS_KEY)


def _preview(spec: CommandSpec, arguments: Mapping[str, Any], call: CommandCall) -> Preview | None:
    if spec.preview is None:
        return None
    # Rolled back whatever happens: a preview that writes is a bug the evals
    # catch, and until then it changes nothing.
    with transaction.atomic():
        preview = spec.preview(arguments, call)
        transaction.set_rollback(True)
    if not isinstance(preview, Preview):
        raise TypeError(f"{spec.key}: podgląd zwrócił {type(preview).__name__}.")
    return preview


def _pass_gates(
    spec: CommandSpec,
    context: TenantContext,
    arguments: Mapping[str, Any],
    preview: Preview | None,
) -> None:
    if missing := REQUIRED_GATES - set(_gates):
        raise CommandGateRefused(f"command_{sorted(missing)[0]}_unavailable")
    for name in sorted(_gates):
        try:
            refusal = _gates[name](spec, context, arguments, preview)
        except Exception:
            logger.exception("command_gate_failed", extra={"gate": name, "command": spec.key})
            refusal = f"command_{name}_unavailable"
        if refusal is not None:
            raise CommandGateRefused(refusal)


def _risk(spec: CommandSpec, preview: Preview | None) -> tuple[str, bool]:
    """The class the preview found, never lower than the declared one, and
    whether the service will ask for a step-up."""
    risk = spec.risk
    if preview is not None and preview.escalate_to is not None:
        if preview.escalate_to not in RISKS:
            raise TypeError(f"{spec.key}: nieznana klasa eskalacji {preview.escalate_to!r}.")
        risk = max(risk, preview.escalate_to, key=RISKS.index)
    if preview is not None and not preview.person_gates <= spec.person_gates:
        raise TypeError(f"{spec.key}: podgląd zgłasza bramki osoby spoza deklaracji.")
    step_up = bool(spec.modifiers & _STEP_UP_MODIFIERS) or bool(
        preview is not None and preview.step_up_required
    )
    return risk, step_up


def _conflicts(planned: list[PlannedCall]) -> list[CallRefusal]:
    """One resource at most once among a plan's writes: every preview read the
    state before the plan, so a second write to the same resource would only
    meet a version conflict after the first one ran."""
    seen: set[str] = set()
    refusals: list[CallRefusal] = []
    for call in planned:
        if call.risk == "read" or call.preview is None:
            continue
        resources = set(call.preview.observed_versions)
        if resources & seen:
            refusals.append(
                _refusal(
                    call.step_id,
                    CommandPlanConflict(
                        detail="Jeden zasób może zmienić tylko jedno polecenie planu."
                    ),
                )
            )
        seen |= resources
    return refusals


def _groups(context: TenantContext, planned: list[PlannedCall]) -> tuple[ConsentGroup, ...]:
    """Draft and apply calls share one click; publish, irreversible, bulk,
    credit spending, a person-only gate and a step-up each get their own
    (ADR-076 §2)."""
    buckets: list[list[PlannedCall]] = []
    shared: list[PlannedCall] | None = None
    for call in planned:
        if call.risk == "read":
            continue
        own_click = (
            call.risk not in _SHARED_RISKS
            or bool(call.spec.modifiers & _OWN_CLICK_MODIFIERS)
            or bool(call.preview is not None and call.preview.person_gates)
            or call.step_up_required
        )
        if own_click:
            buckets.append([call])
        elif shared is None:
            shared = [call]
            buckets.append(shared)
        else:
            shared.append(call)
    return tuple(
        ConsentGroup(
            digest=_digest(context, calls),
            calls=tuple(calls),
            risk=max((call.risk for call in calls), key=RISKS.index),
            step_up_required=any(call.step_up_required for call in calls),
        )
        for calls in buckets
    )


def _digest(context: TenantContext, calls: list[PlannedCall]) -> str:
    """ADR-076 §3: who consents, for which conversation, to exactly these
    calls on exactly the state their previews read."""
    return canonical_json_hash({
        "contract_version": CONTRACT_VERSION,
        "organization": str(context.organization_id),
        "membership": str(context.membership_id),
        "actor": str(context.actor_id),
        "acting_via": context.acting_via,
        "acting_ref": context.acting_ref,
        "calls": [call.describe() for call in calls],
    })


def _run_read(call: PlannedCall) -> CallResult:
    context = require_tenant_context()
    try:
        with transaction.atomic():
            output = call.spec.run(
                call.arguments,
                CommandCall(context=context, idempotency_key=call.idempotency_key),
            )
            # A read is executed without a click, so it may not write, whatever
            # its declaration says.
            transaction.set_rollback(True)
        Draft202012Validator(call.spec.output_schema).validate(output)
    except APIException as error:
        refusal = _refusal(call.step_id, error)
        return CallResult(
            step_id=call.step_id, status="refused", code=refusal.code, errors=refusal.errors
        )
    except Exception:
        logger.exception(
            "command_internal_error", extra={"command": call.spec.key, "step_id": call.step_id}
        )
        return CallResult(step_id=call.step_id, status="failed", code="command_internal_error")
    return CallResult(step_id=call.step_id, status="done", output=output)


def receipt_for(context: TenantContext, spec: CommandSpec, step_id: str) -> CommandReceipt | None:
    """What a step did, read by its key: an ambiguous outcome is settled by
    reading, not by running again (ADR-035, ADR-076 §3)."""
    return CommandReceipt.objects.filter(
        organization_id=context.organization_id,
        membership_id=context.membership_id,
        command=spec.key,
        idempotency_key=idempotency_key(context, spec, step_id),
    ).first()


def _replayed(
    context: TenantContext, invocations: Sequence[Invocation]
) -> tuple[CallResult, ...] | None:
    """Stored results when the plan's writes already ran; None when none did."""
    stored: dict[str, CallResult] = {}
    writes: list[str] = []
    for invocation in invocations:
        try:
            spec = _resolve(invocation.command)
            receipt = receipt_for(context, spec, _step_id(invocation.step_id))
        except (CommandUnavailable, ValueError):
            continue
        if spec.risk == "read":
            continue
        writes.append(invocation.step_id)
        if receipt is None:
            continue
        if receipt.request_hash != _request_hash(spec, invocation.arguments):
            stored[invocation.step_id] = _refused(
                _refusal(invocation.step_id, CommandIdempotencyConflict())
            )
        else:
            stored[invocation.step_id] = CallResult(
                step_id=invocation.step_id, status="done", output=receipt.result
            )
    if not stored:
        return None
    partial = CommandPartiallyApplied()
    return tuple(
        stored.get(invocation.step_id)
        or (
            _refused(_refusal(invocation.step_id, partial))
            if invocation.step_id in writes
            else CallResult(step_id=invocation.step_id, status="skipped")
        )
        for invocation in invocations
    )


def _consent_verdict(
    context: TenantContext, group: ConsentGroup, consents: Mapping[str, str]
) -> APIException | None:
    token = consents.get(group.id)
    if token is None:
        return ConsentRequired()
    try:
        consent = read_consent(token, context=context)
    except APIException as error:
        return error
    if consent.digest != group.digest:
        return ConsentDigestMismatch()
    if group.step_up_required and consent.step_up_at is None:
        # Until the step-up exists (A1b-7) nothing that needs one runs.
        return StepUpRequired()
    return None


def _run_group(context: TenantContext, group: ConsentGroup) -> dict[str, CallResult]:
    done: dict[str, CallResult] = {}
    current = group.calls[0]
    try:
        with transaction.atomic():
            for current in group.calls:
                done[current.step_id] = CallResult(
                    step_id=current.step_id, status="done", output=_run_write(context, current)
                )
    except APIException as error:
        failed = _refused(_refusal(current.step_id, error))
    except Exception:
        logger.exception(
            "command_internal_error",
            extra={"command": current.spec.key, "step_id": current.step_id},
        )
        failed = CallResult(step_id=current.step_id, status="failed", code="command_internal_error")
    else:
        return done
    # The savepoint took every call of the group with it, receipts included.
    return {
        call.step_id: failed
        if call.step_id == current.step_id
        else CallResult(step_id=call.step_id, status="skipped")
        for call in group.calls
    }


def _run_write(context: TenantContext, call: PlannedCall) -> Mapping[str, Any]:
    with connection.cursor() as cursor:
        # A second execution of the same step waits here and finds the
        # receipt, instead of running the step again.
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"command:{context.organization_id}:{context.membership_id}:{call.idempotency_key}"],
        )
    receipt = receipt_for(context, call.spec, call.step_id)
    request_hash = _request_hash(call.spec, call.arguments)
    if receipt is not None:
        if receipt.request_hash != request_hash:
            raise CommandIdempotencyConflict
        return cast(Mapping[str, Any], receipt.result)
    # The person-only labels this call's own consent covers, and only those
    # its channel may ever reach: open for this run, closed again after it.
    opened = (
        call.spec.person_gates
        & (call.preview.person_gates if call.preview is not None else frozenset())
        & ACTING_PERSON_GATE_ALLOWED.get(context.acting_via, frozenset())
    )
    with activate_tenant_context(replace(context, acting_opened=opened)) as running:
        output = call.spec.run(
            call.arguments,
            CommandCall(
                context=running, idempotency_key=call.idempotency_key, preview=call.preview
            ),
        )
    Draft202012Validator(call.spec.output_schema).validate(output)
    CommandReceipt.objects.create(
        organization_id=context.organization_id,
        membership_id=context.membership_id,
        command=call.spec.key,
        idempotency_key=call.idempotency_key,
        request_hash=request_hash,
        acting_ref=context.acting_ref,
        result=output,
    )
    return cast(Mapping[str, Any], output)


def _request_hash(spec: CommandSpec, arguments: Mapping[str, Any]) -> str:
    """What the step asked for. The versions it observed are the digest's to
    bind, not the receipt's: its own write moves them."""
    return canonical_json_hash({"command": spec.key, "arguments": arguments})


def _refused(refusal: CallRefusal) -> CallResult:
    return CallResult(
        step_id=refusal.step_id, status="refused", code=refusal.code, errors=refusal.errors
    )


def _refusal(step_id: str, error: APIException) -> CallRefusal:
    return CallRefusal(
        step_id=step_id,
        status=error.status_code,
        code=problem_code(error),
        errors=tuple(problem_errors(error)),
    )
