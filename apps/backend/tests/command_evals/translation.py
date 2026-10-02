"""Evals of the assistant's translation commands
(`shared/translation/command_declarations.py`, ADR-069 pkt 28).

Translation needs more than a company: a source with content, a model the port
may call, a price and a worker. `around` sets those up for the process — an
in-memory source in the registry, a fake model selected for the task — and
`prepare` gives the company its languages, credits, the processing
acknowledgement and, for the commands that act on them, a job or a waiting
result.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

from saas_core.content_protocol.policy import PublicationFacts
from saas_core.content_protocol.sources import ContentContext, WriteOutcome
from saas_core.modules.core.organizations.context import TenantContext, activate_tenant_context
from saas_core.modules.core.organizations.models import Organization
from saas_core.modules.shared.billing.models import (
    AccessMode,
    CreditOperation,
    EntitlementSnapshot,
    Plan,
    SubscriptionState,
)
from saas_core.modules.shared.model_port.matrix import MODELS, ModelProfile, register_model
from saas_core.modules.shared.translation.jobs import (
    TargetRequest,
    order_translation,
    quote_translation,
)
from saas_core.modules.shared.translation.models import (
    TranslationGlossaryTerm,
    TranslationJob,
    TranslationReviewItem,
    TranslationSettings,
)
from saas_core.modules.shared.translation.tasks import WORKER_SEEN
from saas_core.testing.translation_sources import (
    FakeDraftSource,
    FakeSourceDriver,
    registered_translation_source,
)

from . import CommandEval

SOURCE = "testing.eval_pages"
MODEL = "fake/eval-translator"


class EvalPages(FakeDraftSource):
    """Pages that let the company's people in; a decision passes the engine's
    person gate, which the consent opens for the assistant."""

    def __init__(self) -> None:
        super().__init__(SOURCE)

    def authorize(self, *, context: ContentContext, action: str, object_ids: Any) -> None:
        return None

    def facts(self, context: ContentContext, obj: Any, locale: str) -> PublicationFacts:
        return PublicationFacts(
            legal_document=False, locale_live=locale in self.live_locales, actor_may_publish=True
        )

    def review(
        self, *, context: ContentContext, action: Any, items: Any, idempotency_key: str
    ) -> tuple[WriteOutcome, ...]:
        plain = _without_acting(context)
        return super().review(
            context=plain, action=action, items=items, idempotency_key=idempotency_key
        )


def _without_acting(context: Any) -> Any:
    from dataclasses import replace

    return replace(
        context, acting_via="", acting_ref="", acting_trigger="", acting_opened=frozenset()
    )


PAGES = EvalPages()
#: The page each company translates, by organization.
_PAGE: dict[UUID, UUID] = {}


@contextmanager
def translation_ready() -> Iterator[None]:
    """A source, a selected model, a price and a worker, for one test."""
    saved = {
        name: os.environ.get(name)
        for name in (
            "MODEL_PORT_TASK_TRANSLATION_TEXT_ADAPTER",
            "MODEL_PORT_TASK_TRANSLATION_TEXT_MODEL",
        )
    }
    register_model(
        ModelProfile(
            adapter="fake",
            model=MODEL,
            capabilities=frozenset({"json_schema", "json_mode", "zdr"}),
            forbidden_parameters=frozenset(),
            input_usd_per_mtok=1.0,
            output_usd_per_mtok=5.0,
            context_window=100_000,
            max_output_tokens=16_000,
            probed="2026-10-03",
            dated_variants=frozenset(),
        )
    )
    os.environ["MODEL_PORT_TASK_TRANSLATION_TEXT_ADAPTER"] = "fake"
    os.environ["MODEL_PORT_TASK_TRANSLATION_TEXT_MODEL"] = MODEL
    cache.set(WORKER_SEEN, 1, 300)
    CreditOperation.objects.filter(key="translation.characters").update(is_active=True, cost=1)
    try:
        with registered_translation_source(PAGES):
            yield
    finally:
        MODELS.pop(("fake", MODEL), None)
        cache.delete(WORKER_SEEN)
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _company(context: TenantContext) -> None:
    """Languages, credits, the processing acknowledgement and one page."""
    organization = Organization.objects.get(pk=context.organization_id)
    organization.public_locales = ["pl", "de"]
    organization.save(update_fields=["public_locales"])
    EntitlementSnapshot.all_objects.create(
        organization=organization,
        plan_version=Plan.objects.get(key="starter").current_version,
        subscription_state=SubscriptionState.ACTIVE,
        access_mode=AccessMode.FULL,
        features={},
        quotas={"credits.monthly": 100},
        sources={"credits.monthly": {"kind": "plan"}},
    )
    TranslationSettings.all_objects.create(
        organization=organization,
        processing_ack_membership_id=context.membership_id,
        processing_ack_at=timezone.now(),
        version=1,
    )
    driver = FakeSourceDriver(PAGES)
    page = driver.create(["Strzyżenie psów", "Kąpiel i suszenie"])
    driver.publish(page)
    _PAGE[organization.id] = page


def _with_job(context: TenantContext) -> None:
    """A company with a job in the queue."""
    _company(context)
    targets = _targets(context)
    with activate_tenant_context(context):
        quoted = quote_translation(targets=targets)
        order_translation(
            targets=targets,
            digest=quoted.quote.digest,
            expected_credits=quoted.quote.credits,
            idempotency_key=f"eval-{context.organization_id}",
        )


def _with_review(context: TenantContext) -> None:
    _company(context)
    TranslationReviewItem.all_objects.create(
        organization_id=context.organization_id,
        source_key=SOURCE,
        object_id=_PAGE[context.organization_id],
        locale="de",
        basis="published",
        basis_version="published:1",
        target_version="0",
        reason="review_mode",
        keys=2,
    )


def _targets(context: TenantContext) -> list[TargetRequest]:
    return [TargetRequest(source_key=SOURCE, object_id=_PAGE[context.organization_id], locale="de")]


def _quote_arguments(context: TenantContext) -> dict[str, Any]:
    return {
        "targets": [
            {
                "source_key": SOURCE,
                "object_id": str(_PAGE[context.organization_id]),
                "locale": "de",
                "basis": None,
            }
        ],
        "protected": None,
        "include_unverified": None,
    }


def _edit_page(context: TenantContext) -> None:
    driver = FakeSourceDriver(PAGES)
    page = _PAGE[context.organization_id]
    driver.edit(page, 0, "Strzyżenie psów i kotów")
    driver.publish(page)


def _jobs(context: TenantContext) -> list[Any]:
    return list(
        TranslationJob.all_objects.filter(organization_id=context.organization_id)
        .order_by("created_at")
        .values_list("state", "units", "credits", "error_code")
    )


def _job_id(context: TenantContext) -> str:
    job = TranslationJob.all_objects.filter(organization_id=context.organization_id).first()
    return str(job.id) if job is not None else ""


def _finish_job(context: TenantContext) -> None:
    TranslationJob.all_objects.filter(organization_id=context.organization_id).update(
        state="running"
    )


def _reviews(context: TenantContext) -> list[Any]:
    return list(
        TranslationReviewItem.all_objects.filter(organization_id=context.organization_id)
        .order_by("created_at")
        .values_list("state", "version")
    )


def _review_ids(context: TenantContext) -> dict[str, Any]:
    ids = TranslationReviewItem.all_objects.filter(
        organization_id=context.organization_id
    ).values_list("id", flat=True)
    return {"item_ids": [str(value) for value in ids]}


def _bump_reviews(context: TenantContext) -> None:
    TranslationReviewItem.all_objects.filter(organization_id=context.organization_id).update(
        version=F("version") + 1
    )


def _settings(context: TenantContext) -> list[Any]:
    return list(
        TranslationSettings.all_objects.filter(organization_id=context.organization_id).values_list(
            "mode", "auto_changes", "auto_monthly_limit", "version"
        )
    )


def _bump_settings(context: TenantContext) -> None:
    TranslationSettings.all_objects.filter(organization_id=context.organization_id).update(
        version=F("version") + 1
    )


def _glossary(context: TenantContext) -> list[Any]:
    return list(
        TranslationGlossaryTerm.all_objects.filter(
            organization_id=context.organization_id
        ).values_list("term", "rule", "version")
    )


def _review_entry(action: str) -> CommandEval:
    return CommandEval(
        arguments=_review_ids,
        wrong_arguments={"item_ids": "wszystkie"},
        wrong_field="item_ids",
        stale=_bump_reviews,
        state=_reviews,
        prepare=_with_review,
        around=translation_ready,
    )


NOT_A_VERSION = "nie dotyczy: odczyt nie sprawdza wersji"
ROLLED_BACK = (
    "ADR-078 pkt 9: the settings and glossary previews run the write in a savepoint they "
    "roll back, so a preview refuses exactly what the write would"
)

EVALS = {
    "translation.offer.read@1": CommandEval(
        arguments=lambda _context: {},
        wrong_arguments={"locale": "de"},
        wrong_field="locale",
        stale=NOT_A_VERSION,
        state=_settings,
        prepare=_company,
        around=translation_ready,
    ),
    "translation.quote@1": CommandEval(
        arguments=_quote_arguments,
        wrong_arguments=lambda context: {**_quote_arguments(context), "protected": "always"},
        wrong_field="protected",
        stale=NOT_A_VERSION,
        state=_jobs,
        prepare=_company,
        around=translation_ready,
    ),
    "translation.status.read@1": CommandEval(
        arguments=lambda _context: {"job_id": None},
        wrong_arguments={"job_id": 7},
        wrong_field="job_id",
        stale=NOT_A_VERSION,
        state=_jobs,
        prepare=_with_job,
        around=translation_ready,
    ),
    "translation.review.list@1": CommandEval(
        arguments=lambda _context: {"reason": None},
        wrong_arguments={"reason": 3},
        wrong_field="reason",
        stale=NOT_A_VERSION,
        state=_reviews,
        prepare=_with_review,
        around=translation_ready,
    ),
    "translation.job.create@1": CommandEval(
        arguments=_quote_arguments,
        wrong_arguments=lambda context: {
            **_quote_arguments(context),
            "targets": [{"source_key": SOURCE, "object_id": "x", "basis": None}],
        },
        wrong_field="targets.0.locale",
        stale=_edit_page,
        state=_jobs,
        prepare=_company,
        around=translation_ready,
    ),
    "translation.job.cancel@1": CommandEval(
        arguments=lambda context: {"job_id": _job_id(context)},
        wrong_arguments={"job_id": 7},
        wrong_field="job_id",
        stale=lambda context: TranslationJob.all_objects.filter(
            organization_id=context.organization_id
        ).update(state="queued"),
        state=_jobs,
        prepare=_with_job,
        around=translation_ready,
    ),
    "translation.review.accept@1": _review_entry("accept"),
    "translation.review.reject@1": _review_entry("discard"),
    "translation.settings.update@1": CommandEval(
        arguments=lambda _context: {
            "mode": "review",
            "auto_changes": None,
            "auto_monthly_limit": None,
            "reset": None,
        },
        wrong_arguments={
            "mode": "sometimes",
            "auto_changes": None,
            "auto_monthly_limit": None,
            "reset": None,
        },
        wrong_field="mode",
        stale=_bump_settings,
        state=_settings,
        prepare=_company,
        around=translation_ready,
        preview_rolls_back=ROLLED_BACK,
    ),
    "translation.glossary.update@1": CommandEval(
        arguments=lambda _context: {
            "operation": "add",
            "term_id": None,
            "term": "Psi Fryzjer",
            "rule": "keep",
            "source_locale": "pl",
            "target_locale": None,
            "translation": None,
            "forms": None,
        },
        wrong_arguments={
            "operation": "rename",
            "term_id": None,
            "term": "Psi Fryzjer",
            "rule": "keep",
            "source_locale": "pl",
            "target_locale": None,
            "translation": None,
            "forms": None,
        },
        wrong_field="operation",
        stale="nie dotyczy: dodanie terminu nie czyta żadnej wersji",
        state=_glossary,
        prepare=_company,
        around=translation_ready,
        preview_rolls_back=ROLLED_BACK,
    ),
}
