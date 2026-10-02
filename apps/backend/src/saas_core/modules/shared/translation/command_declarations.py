"""The assistant's translation commands (ADR-069 pkt 28, ADR-076 §1).

Thin adapters over the services `/api/v1/translation/` calls: the same
validation, the same receipts, the same person gates. Ordering binds the
quote's digest, so what the person clicked is what runs; turning the
automation on or raising its limit escalates to a step-up; accepting and
discarding are a person's decisions the assistant reaches only through the
click that covers them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from rest_framework.exceptions import NotFound, ValidationError

from saas_core.modules.core.organizations.api import CommandSpec, Effect, Preview, register_command

from .jobs import (
    TargetRequest,
    get_job,
    job_payload,
    list_jobs,
    order_translation,
    quote_payload,
    quote_translation,
)
from .models import (
    JOB_TERMINAL,
    GlossaryRule,
    ReviewState,
    TranslationGlossaryTerm,
    TranslationReviewItem,
)
from .permissions import TRANSLATION_MANAGE, TRANSLATION_REQUEST
from .review import (
    REVIEW_DECISION,
    ReviewChoice,
    cancel_job,
    decide_review,
    list_review,
    review_payload,
)
from .services import (
    AUTOMATION_CONSENT,
    change_settings,
    create_glossary_term,
    delete_glossary_term,
    read_settings,
    translation_offer,
    update_glossary_term,
)
from .settings_spec import AUTO_CHANGES, AUTO_MONTHLY_LIMIT, MODE

_MODULE = "shared.translation"
_PUBLIC = "public"


def _nullable(kind: str, description: str, **extra: Any) -> dict[str, Any]:
    return {"type": [kind, "null"], "description": description, **extra}


def _effect(kind: str, resource: str, resource_id: str, pl: str, en: str) -> Effect:
    return Effect(
        kind=kind, resource=resource, resource_id=resource_id, summary={"pl": pl, "en": en}
    )


def _id(arguments: Mapping[str, Any], field: str) -> UUID:
    try:
        return UUID(str(arguments[field]))
    except ValueError:
        raise ValidationError({field: ["To nie jest identyfikator."]}, code="invalid") from None


def _object(value: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], _jsonable(dict(value)))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


_TARGETS = {
    "type": "array",
    "description": "The (object, language) pairs, e.g. a site's pages in German.",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["source_key", "object_id", "locale", "basis"],
        "properties": {
            "source_key": {"type": "string", "description": "A source, e.g. sites.page."},
            "object_id": {"type": "string", "description": "The object's id in that source."},
            "locale": {"type": "string", "description": "A language enabled for the company."},
            "basis": _nullable(
                "string",
                "published (default): what visitors see; working: the draft open in the editor.",
                enum=["published", "working", None],
            ),
        },
    },
}
_PROTECTED = _nullable(
    "string",
    "Texts a person or an integration wrote: skip, propose changes that wait for a person "
    "(default), or overwrite (only when the person asked for it).",
    enum=["skip", "propose", "overwrite", None],
)
_UNVERIFIED = _nullable(
    "boolean", "Also propose over texts written before provenance existed; default false."
)
_QUOTE_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["targets", "protected", "include_unverified"],
    "properties": {
        "targets": _TARGETS,
        "protected": _PROTECTED,
        "include_unverified": _UNVERIFIED,
    },
}


def _targets(arguments: Mapping[str, Any]) -> list[TargetRequest]:
    targets = []
    for index, target in enumerate(arguments["targets"]):
        try:
            object_id = UUID(str(target["object_id"]))
        except ValueError:
            raise ValidationError(
                {"targets": {str(index): {"object_id": ["To nie jest identyfikator."]}}},
                code="invalid",
            ) from None
        targets.append(
            TargetRequest(
                source_key=target["source_key"],
                object_id=object_id,
                locale=target["locale"],
                basis=target.get("basis") or "published",
            )
        )
    return targets


def _options(arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "protected": arguments.get("protected") or "propose",
        "include_unverified": bool(arguments.get("include_unverified")),
    }


# translation.offer.read@1


def _offer(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    offer = translation_offer()
    return _object({
        "available": offer["available"],
        "reasons": offer["reasons"],
        "mode": offer["mode"]["effective"],
        "automation": {
            "enabled": offer["automation"]["enabled"],
            "monthly_limit": offer["automation"]["monthly_limit"],
        },
        "billing": offer["billing"],
        "settings": offer["settings"],
    })


OFFER_READ = CommandSpec(
    name="translation.offer.read",
    version=1,
    module=_MODULE,
    title={"pl": "Sprawdź tłumaczenia AI", "en": "Check AI translation"},
    summary={
        "pl": "Czy można teraz tłumaczyć, w jakim trybie i za ile.",
        "en": "Whether translation can be ordered now, in which mode and at what price.",
    },
    model_description=(
        "Says whether the company can order an AI translation now and why not (reasons such "
        "as model_not_selected, operation_unpriced, processing_ack_required), the publication "
        "mode in force, the automation's state and the price unit (credits per 1,000 source "
        "characters per language), and every translation setting with its allowed values. "
        "Use it before quoting."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {},
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "available": {"type": "boolean"},
            "reasons": {"type": "array"},
            "mode": {"type": "string"},
            "automation": {"type": "object"},
            "billing": {"type": "object"},
            "settings": {"type": "array"},
        },
    },
    permission=TRANSLATION_REQUEST,
    risk="read",
    run=_offer,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# translation.quote@1


def _quote(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    result = quote_translation(targets=_targets(arguments), **_options(arguments))
    return _object(quote_payload(result))


_QUOTE_OUTPUT = {
    "type": "object",
    "x-data-class": _PUBLIC,
    "properties": {
        "digest": {"type": "string"},
        "available": {"type": "boolean"},
        "reasons": {"type": "array"},
        "characters": {"type": "integer"},
        "units": {"type": "integer"},
        "unit_cost": {"type": "integer"},
        "credits": {"type": "integer"},
        "mode": {"type": "string"},
        "protected": {"type": "string"},
        "include_unverified": {"type": "boolean"},
        "parts": {"type": "array"},
        "waiting": {"type": "object"},
        "lines": {"type": "array"},
    },
}

QUOTE = CommandSpec(
    name="translation.quote",
    version=1,
    module=_MODULE,
    title={"pl": "Wyceń tłumaczenie", "en": "Quote a translation"},
    summary={
        "pl": "Ile znaków, jednostek i kredytów, co poczeka na akceptację i dlaczego.",
        "en": "How many characters, units and credits, and what will wait for approval and why.",
    },
    model_description=(
        "Counts what would be translated for each (object, language) pair, what it costs in "
        "credits, which results would wait for a person and why, and returns a digest. Nothing "
        "is saved. Show the person the credits and what waits before ordering with "
        "translation.job.create."
    ),
    input_schema=_QUOTE_INPUT,
    output_schema=_QUOTE_OUTPUT,
    permission=TRANSLATION_REQUEST,
    risk="read",
    run=_quote,
    undo="none:a read changes nothing",
    no_preview_reason="A quote saves nothing, so there is nothing to show first.",
    no_version_reason="A quote checks no version; the order checks its digest.",
)


# translation.status.read@1


def _status(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    if arguments.get("job_id"):
        jobs = [get_job(_id(arguments, "job_id"))]
    else:
        jobs, _ = list_jobs(cursor=None, limit=10)
    payloads = []
    for job in jobs:
        payload = job_payload(job)
        payload["items"] = [
            {key: item[key] for key in ("source_key", "object_id", "locale", "state", "error_code")}
            for item in payload["items"]
        ]
        payloads.append(payload)
    return _object({"jobs": payloads})


STATUS_READ = CommandSpec(
    name="translation.status.read",
    version=1,
    module=_MODULE,
    title={"pl": "Stan tłumaczeń", "en": "Translation status"},
    summary={
        "pl": "Ostatnie zlecenia albo jedno zlecenie: stan, części i pozycje.",
        "en": "The latest jobs or one job: state, parts and items.",
    },
    model_description=(
        "Returns the state of the company's latest ten translation jobs, or of one job by "
        "job_id: queued, running, succeeded, partial, failed or canceled, with credits held "
        "and settled per part and each (object, language) item's state. Pass null for the "
        "latest jobs."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["job_id"],
        "properties": {"job_id": _nullable("string", "One job; null for the latest ten.")},
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {"jobs": {"type": "array"}},
    },
    permission=TRANSLATION_REQUEST,
    risk="read",
    run=_status,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# translation.review.list@1


def _review_list(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    rows, _ = list_review(cursor=None, limit=50, reason=arguments.get("reason"))
    return _object({"items": [review_payload(row) for row in rows]})


REVIEW_LIST = CommandSpec(
    name="translation.review.list",
    version=1,
    module=_MODULE,
    title={"pl": "Tłumaczenia do akceptacji", "en": "Translations to approve"},
    summary={
        "pl": "Co czeka na decyzję osoby i dlaczego.",
        "en": "What waits for a person's decision and why.",
    },
    model_description=(
        "Lists up to 50 translation results waiting for a person, oldest first, each with its "
        "id, version, reason (legal_document, review_mode, overwrites_human, qa_flagged, "
        "locale_first_appearance…) and whether it can be accepted. Pass a reason to filter, or "
        "null. Accepting needs the person's click: translation.review.accept."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["reason"],
        "properties": {"reason": _nullable("string", "Only items waiting for this reason.")},
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {"items": {"type": "array"}},
    },
    permission=TRANSLATION_REQUEST,
    risk="read",
    run=_review_list,
    undo="none:a read changes nothing",
    no_preview_reason="A read changes nothing, so there is nothing to show first.",
    no_version_reason="A read checks no version.",
)


# translation.job.create@1


def _preview_order(arguments: Mapping[str, Any], call: Any) -> Preview:
    result = quote_translation(targets=_targets(arguments), **_options(arguments))
    quote = result.quote
    if not result.available:
        raise ValidationError(
            {"targets": [f"Tłumaczenie niedostępne: {', '.join(result.reasons)}."]},
            code="translation_unavailable",
        )
    waiting = ", ".join(f"{reason}: {count}" for reason, count in sorted(quote.waiting.items()))
    return Preview(
        effects=(
            _effect(
                "created",
                "translation.job",
                "",
                f"Tłumaczenie {len(quote.lines)} pozycji: {quote.units} jedn., "
                f"{quote.credits} kredytów" + (f"; poczeka: {waiting}" if waiting else ""),
                f"Translation of {len(quote.lines)} items: {quote.units} units, "
                f"{quote.credits} credits" + (f"; waiting: {waiting}" if waiting else ""),
            ),
        ),
        observed_versions={"translation.quote": quote.digest},
        quote=_jsonable(quote_payload(result)),
    )


def _order(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    quote = call.preview.quote or {}
    saved = order_translation(
        targets=_targets(arguments),
        digest=str(call.preview.observed_versions["translation.quote"]),
        expected_credits=int(quote.get("credits", 0)),
        idempotency_key=call.idempotency_key,
        **_options(arguments),
    )
    job = saved.value
    return {"job_id": str(job.id), "state": job.state, "units": job.units, "credits": job.credits}


_JOB_OUTPUT = {
    "type": "object",
    "x-data-class": _PUBLIC,
    "properties": {
        "job_id": {"type": "string"},
        "state": {"type": "string"},
        "units": {"type": "integer"},
        "credits": {"type": "integer"},
    },
}

JOB_CREATE = CommandSpec(
    name="translation.job.create",
    version=1,
    module=_MODULE,
    title={"pl": "Zleć tłumaczenie", "en": "Order a translation"},
    summary={
        "pl": "Tłumaczenie wycenionych pozycji za pokazane kredyty.",
        "en": "Translation of the quoted items for the credits shown.",
    },
    model_description=(
        "Orders the AI translation of the given (object, language) pairs for the credits the "
        "quote shows; the person's click binds that quote, and if the content changes before "
        "the click the order is refused. Results that wait for a person (legal documents, "
        "review mode, a person's own text) are billed when delivered. Quote first with "
        "translation.quote and show the person the credits."
    ),
    input_schema=_QUOTE_INPUT,
    output_schema=_JOB_OUTPUT,
    permission=TRANSLATION_REQUEST,
    risk="irreversible",
    modifiers=frozenset({"spends_credits"}),
    run=_order,
    undo="compensation:take the job back with POST /api/v1/translation/jobs/<id>/revert/",
    preview=_preview_order,
    no_version_reason="The quote's digest binds the consent and the order checks it again.",
)


# translation.job.cancel@1


def _open_job(arguments: Mapping[str, Any]) -> Any:
    job = get_job(_id(arguments, "job_id"))
    if job.state in JOB_TERMINAL:
        raise ValidationError({"job_id": ["Zlecenie już się zakończyło."]}, code="job_finished")
    return job


def _preview_cancel(arguments: Mapping[str, Any], call: Any) -> Preview:
    job = _open_job(arguments)
    return Preview(
        effects=(
            _effect(
                "updated",
                "translation.job",
                str(job.id),
                "Zatrzymanie zlecenia tłumaczenia: rozliczone zostanie tylko dostarczone",
                "Stopping the translation job: only what was delivered is billed",
            ),
        ),
        observed_versions={f"translation.job:{job.id}": job.state},
    )


def _cancel(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    job = cancel_job(job_id=_id(arguments, "job_id"), idempotency_key=call.idempotency_key).value
    return {"job_id": str(job.id), "state": job.state, "units": job.units, "credits": job.credits}


JOB_CANCEL = CommandSpec(
    name="translation.job.cancel",
    version=1,
    module=_MODULE,
    title={"pl": "Zatrzymaj tłumaczenie", "en": "Stop a translation"},
    summary={
        "pl": "Pozycje jeszcze nierozpoczęte są anulowane, rozliczone tylko dostarczone.",
        "en": "Items not started are cancelled; only what was delivered is billed.",
    },
    model_description=(
        "Stops a running translation job by job_id: items not started are cancelled, items in "
        "flight finish, delivered text is billed and the rest of the held credits are "
        "released. A stopped job cannot be resumed; order the rest again."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["job_id"],
        "properties": {"job_id": {"type": "string", "description": "The job to stop."}},
    },
    output_schema=_JOB_OUTPUT,
    permission=TRANSLATION_REQUEST,
    risk="apply",
    run=_cancel,
    undo="none:a stopped job cannot be resumed; order the rest again",
    preview=_preview_cancel,
    version_field="state",
)


# translation.review.accept@1 and translation.review.reject@1

_REVIEW_INPUT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["item_ids"],
    "properties": {
        "item_ids": {
            "type": "array",
            "description": "Ids from translation.review.list.",
            "items": {"type": "string"},
        }
    },
}


def _open_reviews(arguments: Mapping[str, Any], call: Any) -> list[TranslationReviewItem]:
    ids = []
    for index, value in enumerate(arguments["item_ids"]):
        try:
            ids.append(UUID(str(value)))
        except ValueError:
            raise ValidationError(
                {"item_ids": {str(index): ["To nie jest identyfikator."]}}, code="invalid"
            ) from None
    if not ids:
        raise ValidationError({"item_ids": ["Podaj co najmniej jedną pozycję."]}, code="required")
    rows = {
        row.id: row
        for row in TranslationReviewItem.all_objects.filter(
            organization_id=call.context.organization_id, pk__in=ids, state=ReviewState.OPEN
        )
    }
    missing = [index for index, row_id in enumerate(ids) if row_id not in rows]
    if missing:
        raise NotFound("Nie ma takiej pozycji przeglądu albo już ją rozstrzygnięto.")
    return [rows[row_id] for row_id in ids]


def _review_preview(action: str) -> Any:
    def preview(arguments: Mapping[str, Any], call: Any) -> Preview:
        rows = _open_reviews(arguments, call)
        if action == "accept":
            refused = [
                row for row in rows if row.reason in ("qa_failed", "model_refused", "gate_failed")
            ]
            if refused:
                raise ValidationError(
                    {"item_ids": ["Tej pozycji nie da się zaakceptować — nie ma tekstu."]},
                    code="not_acceptable",
                )
        verb = ("Akceptacja", "Accepting") if action == "accept" else ("Odrzucenie", "Discarding")
        return Preview(
            effects=tuple(
                _effect(
                    "updated",
                    "translation.review",
                    str(row.id),
                    f"{verb[0]} tłumaczenia ({row.locale}, powód: {row.reason})",
                    f"{verb[1]} a translation ({row.locale}, reason: {row.reason})",
                )
                for row in rows
            ),
            observed_versions={f"translation.review:{row.id}": row.version for row in rows},
            person_gates=frozenset({REVIEW_DECISION}),
        )

    return preview


def _review_run(action: str) -> Any:
    def run(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
        observed = call.preview.observed_versions
        choices = [
            ReviewChoice(id=UUID(str(value)), version=int(observed[f"translation.review:{value}"]))
            for value in arguments["item_ids"]
        ]
        saved = decide_review(action=action, choices=choices, idempotency_key=call.idempotency_key)
        return {
            "decided": len(saved.value),
            "state": "accepted" if action == "accept" else "discarded",
        }

    return run


_DECIDED_OUTPUT = {
    "type": "object",
    "x-data-class": _PUBLIC,
    "properties": {"decided": {"type": "integer"}, "state": {"type": "string"}},
}

REVIEW_ACCEPT = CommandSpec(
    name="translation.review.accept",
    version=1,
    module=_MODULE,
    title={"pl": "Zaakceptuj tłumaczenia", "en": "Approve translations"},
    summary={
        "pl": "Publikuje wybrane tłumaczenia tak, jak publikuje je ich źródło.",
        "en": "Publishes the chosen translations the way their source publishes.",
    },
    model_description=(
        "Publishes the chosen waiting translations (ids from translation.review.list). A "
        "person's decision: it runs only after the person's click that names these items. "
        "Items without text (qa_failed, model_refused, gate_failed) cannot be accepted."
    ),
    input_schema=_REVIEW_INPUT,
    output_schema=_DECIDED_OUTPUT,
    permission=TRANSLATION_REQUEST,
    risk="publish",
    run=_review_run("accept"),
    undo="compensation:take the translation back by reverting its job",
    preview=_review_preview("accept"),
    version_field="version",
    person_gates=frozenset({REVIEW_DECISION}),
)

REVIEW_REJECT = CommandSpec(
    name="translation.review.reject",
    version=1,
    module=_MODULE,
    title={"pl": "Odrzuć tłumaczenia", "en": "Discard translations"},
    summary={
        "pl": "Odrzuca wybrane tłumaczenia; to, co publiczne, zostaje.",
        "en": "Discards the chosen translations; what is public stays.",
    },
    model_description=(
        "Discards the chosen waiting translations (ids from translation.review.list); what is "
        "public stays as it is. A discarded result was billed when delivered. A person's "
        "decision: it runs only after the person's click."
    ),
    input_schema=_REVIEW_INPUT,
    output_schema=_DECIDED_OUTPUT,
    permission=TRANSLATION_REQUEST,
    risk="apply",
    run=_review_run("discard"),
    undo="none:a discarded result is gone; order the translation again",
    preview=_review_preview("discard"),
    version_field="version",
    person_gates=frozenset({REVIEW_DECISION}),
)


# translation.settings.update@1

_SETTING_KEYS = {
    "mode": MODE.key,
    "auto_changes": AUTO_CHANGES.key,
    "auto_monthly_limit": AUTO_MONTHLY_LIMIT.key,
}


def _settings_changes(arguments: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    changes = {
        key: arguments[name]
        for name, key in _SETTING_KEYS.items()
        if arguments.get(name) is not None
    }
    reset = list(dict.fromkeys(_SETTING_KEYS[name] for name in arguments.get("reset") or ()))
    return changes, reset


def _preview_settings(arguments: Mapping[str, Any], call: Any) -> Preview:
    current = read_settings()
    changes, reset = _settings_changes(arguments)
    saved = change_settings(
        changes=changes, reset=reset, expected_version=current["version"], preview=True
    )
    values = current["values"]
    enabling = changes.get(AUTO_CHANGES.key) is True and not values[AUTO_CHANGES.key]["effective"]
    limit = changes.get(AUTO_MONTHLY_LIMIT.key)
    raising = limit is not None and limit > values[AUTO_MONTHLY_LIMIT.key]["effective"]
    changed = ", ".join(sorted(saved.changes)) or "—"
    return Preview(
        effects=(
            _effect(
                "updated",
                "translation.settings",
                "",
                f"Ustawienia tłumaczeń: {changed}",
                f"Translation settings: {changed}",
            ),
        ),
        observed_versions={"translation.settings": current["version"]},
        # Spending without a click from now on: the strictest class and a
        # second factor (ADR-069 pkt 28).
        escalate_to="irreversible" if enabling or raising else None,
        step_up_required=enabling or raising,
        person_gates=frozenset({AUTOMATION_CONSENT}) if enabling else frozenset(),
    )


def _settings(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    changes, reset = _settings_changes(arguments)
    saved = change_settings(
        changes=changes,
        reset=reset,
        expected_version=int(call.preview.observed_versions["translation.settings"]),
        idempotency_key=call.idempotency_key,
    )
    values = saved.value["values"]
    return {
        "version": saved.version,
        "mode": values[MODE.key]["effective"],
        "auto_changes": values[AUTO_CHANGES.key]["effective"],
        "auto_monthly_limit": values[AUTO_MONTHLY_LIMIT.key]["effective"],
    }


SETTINGS_UPDATE = CommandSpec(
    name="translation.settings.update",
    version=1,
    module=_MODULE,
    title={"pl": "Zmień ustawienia tłumaczeń", "en": "Change translation settings"},
    summary={
        "pl": "Tryb publikacji, automat zmian i jego miesięczny limit.",
        "en": "Publication mode, the automation of changes and its monthly limit.",
    },
    model_description=(
        "Changes the company's translation settings: mode (automatic or review), auto_changes "
        "(translate changes of published content without a click, as the person who turns it "
        "on) and auto_monthly_limit (credits a month for that, 0 turns it off). Pass null for "
        "what stays; reset lists settings to take back to their default. Turning the "
        "automation on or raising its limit needs the person's click and a second factor."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["mode", "auto_changes", "auto_monthly_limit", "reset"],
        "properties": {
            "mode": _nullable(
                "string", "automatic or review; null leaves it.", enum=[*MODE.variants, None]
            ),
            "auto_changes": _nullable(
                "boolean", "Translate changes automatically; null leaves it."
            ),
            "auto_monthly_limit": _nullable(
                "integer", "Credits a month for the automation, 0 to 100000; null leaves it."
            ),
            "reset": {
                "type": ["array", "null"],
                "description": "Settings to take back to their default; null or [] resets none.",
                "items": {"type": "string", "enum": list(_SETTING_KEYS)},
            },
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "version": {"type": "integer"},
            "mode": {"type": "string"},
            "auto_changes": {"type": "boolean"},
            "auto_monthly_limit": {"type": "integer"},
        },
    },
    permission=TRANSLATION_MANAGE,
    risk="apply",
    run=_settings,
    undo="command:translation.settings.update@1",
    preview=_preview_settings,
    version_field="expected_version",
    person_gates=frozenset({AUTOMATION_CONSENT}),
)


# translation.glossary.update@1


def _glossary_data(arguments: Mapping[str, Any]) -> dict[str, Any]:
    fields = ("term", "rule", "source_locale", "target_locale", "translation", "forms")
    return {field: arguments[field] for field in fields if arguments.get(field) is not None}


def _term(arguments: Mapping[str, Any], call: Any) -> TranslationGlossaryTerm:
    term = TranslationGlossaryTerm.all_objects.filter(
        organization_id=call.context.organization_id, pk=_id(arguments, "term_id")
    ).first()
    if term is None:
        raise NotFound("Nie ma takiego terminu.")
    return term


def _preview_glossary(arguments: Mapping[str, Any], call: Any) -> Preview:
    operation = arguments["operation"]
    if operation == "add":
        create_glossary_term(data=_glossary_data(arguments), preview=True)
        return Preview(
            effects=(
                _effect(
                    "created",
                    "translation.glossary_term",
                    "",
                    "Nowy termin w glosariuszu",
                    "A new glossary term",
                ),
            ),
            observed_versions={},
        )
    if not arguments.get("term_id"):
        raise ValidationError({"term_id": ["Podaj termin do zmiany."]}, code="required")
    term = _term(arguments, call)
    if operation == "change":
        update_glossary_term(
            term_id=term.id,
            data=_glossary_data(arguments),
            expected_version=term.version,
            preview=True,
        )
    pl, en = (
        ("Zmiana terminu", "Changing a term")
        if operation == "change"
        else ("Usunięcie terminu", "Removing a term")
    )
    return Preview(
        effects=(
            _effect(
                "updated" if operation == "change" else "deleted",
                "translation.glossary_term",
                str(term.id),
                pl,
                en,
            ),
        ),
        observed_versions={f"translation.glossary_term:{term.id}": term.version},
    )


def _glossary(arguments: Mapping[str, Any], call: Any) -> dict[str, Any]:
    operation = arguments["operation"]
    if operation == "add":
        saved = create_glossary_term(
            data=_glossary_data(arguments), idempotency_key=call.idempotency_key
        )
        return {"term_id": str(saved.item_id), "version": saved.version, "removed": False}
    term_id = _id(arguments, "term_id")
    version = int(call.preview.observed_versions[f"translation.glossary_term:{term_id}"])
    if operation == "change":
        saved = update_glossary_term(
            term_id=term_id,
            data=_glossary_data(arguments),
            expected_version=version,
            idempotency_key=call.idempotency_key,
        )
        return {"term_id": str(term_id), "version": saved.version, "removed": False}
    delete_glossary_term(
        term_id=term_id, expected_version=version, idempotency_key=call.idempotency_key
    )
    return {"term_id": str(term_id), "version": version, "removed": True}


GLOSSARY_UPDATE = CommandSpec(
    name="translation.glossary.update",
    version=1,
    module=_MODULE,
    title={"pl": "Zmień glosariusz", "en": "Change the glossary"},
    summary={
        "pl": "Dodaj, zmień albo usuń termin, który tłumaczenie zachowuje lub tłumaczy po swojemu.",
        "en": "Add, change or remove a term a translation keeps or renders the company's way.",
    },
    model_description=(
        "Adds, changes or removes one glossary term. rule: keep (unchanged everywhere, e.g. a "
        "brand), name (a person's name, transliterated into Cyrillic) or translate_as (with "
        "translation). A term is one line of at most 120 characters, with up to 10 inflected "
        "forms in the source language. For change and remove pass term_id; pass null for "
        "fields that stay."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "operation",
            "term_id",
            "term",
            "rule",
            "source_locale",
            "target_locale",
            "translation",
            "forms",
        ],
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "change", "remove"],
                "description": "add, change or remove.",
            },
            "term_id": _nullable("string", "The term to change or remove; null to add."),
            "term": _nullable("string", "The term as written in the source."),
            "rule": _nullable(
                "string", "keep, name or translate_as.", enum=[*GlossaryRule.values, None]
            ),
            "source_locale": _nullable("string", "The language the term is written in."),
            "target_locale": _nullable("string", "Only for this language; null for every one."),
            "translation": _nullable("string", "translate_as only: the company's translation."),
            "forms": {
                "type": ["array", "null"],
                "description": "Inflected forms in the source language, at most 10.",
                "items": {"type": "string"},
            },
        },
    },
    output_schema={
        "type": "object",
        "x-data-class": _PUBLIC,
        "properties": {
            "term_id": {"type": "string"},
            "version": {"type": "integer"},
            "removed": {"type": "boolean"},
        },
    },
    permission=TRANSLATION_MANAGE,
    risk="apply",
    run=_glossary,
    undo="command:translation.glossary.update@1",
    preview=_preview_glossary,
    version_field="version",
)


COMMANDS = (
    OFFER_READ,
    QUOTE,
    STATUS_READ,
    REVIEW_LIST,
    JOB_CREATE,
    JOB_CANCEL,
    REVIEW_ACCEPT,
    REVIEW_REJECT,
    SETTINGS_UPDATE,
    GLOSSARY_UPDATE,
)


def register_translation_commands() -> None:
    for spec in COMMANDS:
        register_command(spec)
