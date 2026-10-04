"""What the company hears about translation (ADR-069 pkt 14, 20; TL6).

A job that ended with gaps tells the person who ordered it, in the panel and
by e-mail; once a day the people who manage translation hear how many results
wait for a decision; an automation that cannot run tells them once per period
(the month for its limit, the day for anything else). The panel words the
in-app notice in the reader's language from the kind and its facts; no
translated or source text is ever in a notice.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from saas_core.modules.core.organizations.context import (
    TenantContext,
    activate_tenant_context,
    current_tenant_context,
    set_local_organization_id,
)
from saas_core.modules.core.organizations.models import Membership, MembershipStatus, Organization
from saas_core.modules.shared.billing.api import billing_organization_ids
from saas_core.modules.shared.notifications.api import (
    AUDIENCE_STAFF,
    EmailTemplate,
    notify_in_app,
    queue_email,
    register_email_template,
    staff_locale,
)

from .models import ReviewState, TranslationJob, TranslationReviewItem
from .permissions import TRANSLATION_MANAGE

JOB_PROBLEM = "translation.job_problem"
REVIEW_WAITING = "translation.review_waiting"
AUTOMATION_PAUSED = "translation.automation_paused"
NOTIFY_ROLE = "translation_notifications"


@contextmanager
def _as_the_organization(organization_id: UUID) -> Iterator[None]:
    outer = current_tenant_context()
    # A person's context signs the mail as that person. Anything else — no
    # context in a sweep, the job's settlement context in the worker — is not
    # one the delivery task opens, so the notice goes as the organization's
    # own job (`NOTIFY_ROLE` in `core.organizations.tasks._service_context`).
    if (
        outer is not None
        and outer.organization_id == organization_id
        and outer.principal_kind == "membership"
    ):
        yield
        return
    context = TenantContext(
        organization_id=organization_id,
        membership_id=organization_id,
        actor_id=organization_id,
        role_key=NOTIFY_ROLE,
        permissions=frozenset(),
        principal_kind="service",
    )
    with activate_tenant_context(context):
        yield


#: Where a notice sends the person (TL16f): the job, what waits for a
#: decision, the settings the automation stopped on. The centre is a part of
#: the sites' section of the panel; a deployment without it gets the panel's
#: start, never an address that 404s.
PANEL_PATH = "/panel"
JOB_PATH = "/panel/sites/translations/jobs/{job_id}"
REVIEW_PATH = "/panel/sites/translations/review"
SETTINGS_PATH = "/panel/settings/languages"
CREDITS_PATH = "/panel/settings/credits"
_CENTRE_APP = "saas_core.modules.shared.sites"


def _panel(locale: str, path: str = PANEL_PATH) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/") + ("/en" if locale == "en" else "")
    if path.startswith("/panel/sites/") and not apps.is_installed(_CENTRE_APP):
        path = PANEL_PATH
    return f"{base}{path}"


def notify_job_problem(job: TranslationJob, *, written: int, total: int) -> None:
    """A job that ended partial or failed: the person who ordered it hears once."""
    user = job.created_by
    organization = Organization.objects.get(pk=job.organization_id)
    payload = {"job_id": str(job.id), "state": job.state, "count": total, "written": written}
    key = f"translation-job:{job.id}:{job.state}"
    with _as_the_organization(job.organization_id):
        notify_in_app(
            organization_id=job.organization_id,
            user_id=user.id,
            kind=JOB_PROBLEM,
            payload=payload,
            idempotency_key=key,
        )
        locale = staff_locale(organization_id=job.organization_id, user=user)
        queue_email(
            recipient_email=user.email,
            template_key=JOB_PROBLEM,
            template_version=2,
            locale=locale,
            template_context={
                "organization_name": organization.name,
                "written": str(written),
                "total": str(total),
                "panel_url": _panel(locale, JOB_PATH.format(job_id=job.id)),
            },
            idempotency_key=key,
            causation_id=f"translation_job:{job.id}",
            recipient_user=user,
        )


def notify_waiting_reviews() -> int:
    """Once a day: how many results wait for a decision, to whoever may decide.

    One notice per company and day; organizations one at a time, each inside
    its own tenant (ADR-039).
    """
    sent = 0
    today = timezone.now().date().isoformat()
    for organization_id in billing_organization_ids():
        with transaction.atomic():
            set_local_organization_id(organization_id)
            reasons = Counter(
                TranslationReviewItem.all_objects.filter(
                    organization_id=organization_id, state=ReviewState.OPEN
                ).values_list("reason", flat=True)
            )
            if not reasons:
                continue
            organization = Organization.objects.get(pk=organization_id)
            recipients = _managers(organization_id)
            count = sum(reasons.values())
            payload: dict[str, Any] = {"count": count, "reasons": dict(reasons)}
            key = f"translation-review:{organization_id}:{today}"
            with _as_the_organization(organization_id):
                for membership in recipients:
                    user = membership.user
                    sent += notify_in_app(
                        organization_id=organization_id,
                        user_id=user.id,
                        kind=REVIEW_WAITING,
                        payload=payload,
                        idempotency_key=key,
                    )
                    locale = staff_locale(organization_id=organization_id, user=user)
                    queue_email(
                        recipient_email=user.email,
                        template_key=REVIEW_WAITING,
                        template_version=2,
                        locale=locale,
                        template_context={
                            "organization_name": organization.name,
                            "count": str(count),
                            "panel_url": _panel(locale, REVIEW_PATH),
                        },
                        idempotency_key=f"{key}:{user.id}",
                        causation_id=f"translation_review:{today}",
                        recipient_user=user,
                    )
    return sent


def _managers(organization_id: UUID) -> list[Membership]:
    return [
        membership
        for membership in Membership.objects.select_related("role", "user").filter(
            organization_id=organization_id, status=MembershipStatus.ACTIVE
        )
        if TRANSLATION_MANAGE in (membership.role.permissions or [])
    ]


def notify_automation_paused(organization_id: UUID, *, reason: str, period: str) -> int:
    """The automation cannot run: who manages translation hears it once per
    period and reason; the published translations stay as they are."""
    organization = Organization.objects.get(pk=organization_id)
    key = f"translation-paused:{organization_id}:{reason}:{period}"
    sent = 0
    with _as_the_organization(organization_id):
        for membership in _managers(organization_id):
            user = membership.user
            sent += notify_in_app(
                organization_id=organization_id,
                user_id=user.id,
                kind=AUTOMATION_PAUSED,
                payload={"reason": reason},
                idempotency_key=key,
            )
            locale = staff_locale(organization_id=organization_id, user=user)
            queue_email(
                recipient_email=user.email,
                template_key=AUTOMATION_PAUSED,
                template_version=1,
                locale=locale,
                template_context={
                    "organization_name": organization.name,
                    # Where the cause is lifted: the credits, or the limit and
                    # the consent beside the automation's switch.
                    "panel_url": _panel(
                        locale, CREDITS_PATH if reason == "credits_exhausted" else SETTINGS_PATH
                    ),
                },
                idempotency_key=f"{key}:{user.id}",
                causation_id=f"translation_automation:{period}",
                recipient_user=user,
            )
    return sent


def register_templates() -> None:
    """The mails this module sends to the company's people; from `ready()`."""
    register_email_template(
        EmailTemplate(
            key=JOB_PROBLEM,
            version=1,
            category="required",
            subjects={
                "pl": "Tłumaczenie zakończone z brakami",
                "en": "A translation finished with gaps",
            },
            bodies={
                "pl": (
                    "<p>{organization_name}: zlecenie tłumaczenia objęło {total} pozycji, "
                    "przetłumaczono {written}. Za resztę nie pobrano kredytów.</p>"
                    '<p><a href="{panel_url}">Zobacz zlecenie</a></p>'
                ),
                "en": (
                    "<p>{organization_name}: the translation job covered {total} items and "
                    "translated {written}. No credits were taken for the rest.</p>"
                    '<p><a href="{panel_url}">Open the job</a></p>'
                ),
            },
            allowed_context=frozenset({"organization_name", "written", "total", "panel_url"}),
            audience=AUDIENCE_STAFF,
        )
    )
    # Version 2 of the two counted notices: the number stands apart, so the
    # sentence is right for 1, 2 and 5 alike ("1 tłumaczeń czeka" was not).
    register_email_template(
        EmailTemplate(
            key=JOB_PROBLEM,
            version=2,
            category="required",
            subjects={
                "pl": "Tłumaczenie zakończone z brakami",
                "en": "A translation finished with gaps",
            },
            bodies={
                "pl": (
                    "<p>{organization_name}: zlecenie tłumaczenia nie objęło wszystkiego. "
                    "Przetłumaczone pozycje: {written} z {total}. Za resztę nie pobrano "
                    "kredytów.</p>"
                    '<p><a href="{panel_url}">Zobacz zlecenie</a></p>'
                ),
                "en": (
                    "<p>{organization_name}: a translation job did not cover everything. "
                    "Items translated: {written} of {total}. No credits were taken for the "
                    "rest.</p>"
                    '<p><a href="{panel_url}">Open the job</a></p>'
                ),
            },
            allowed_context=frozenset({"organization_name", "written", "total", "panel_url"}),
            audience=AUDIENCE_STAFF,
        )
    )
    register_email_template(
        EmailTemplate(
            key=REVIEW_WAITING,
            version=2,
            category="required",
            subjects={
                "pl": "Tłumaczenia czekają na akceptację",
                "en": "Translations wait for approval",
            },
            bodies={
                "pl": (
                    "<p>{organization_name}: na Twoją decyzję czekają tłumaczenia "
                    "({count}).</p>"
                    '<p><a href="{panel_url}">Przejrzyj</a></p>'
                ),
                "en": (
                    "<p>{organization_name}: translations are waiting for your decision "
                    "({count}).</p>"
                    '<p><a href="{panel_url}">Review them</a></p>'
                ),
            },
            allowed_context=frozenset({"organization_name", "count", "panel_url"}),
            audience=AUDIENCE_STAFF,
        )
    )
    register_email_template(
        EmailTemplate(
            key=REVIEW_WAITING,
            version=1,
            category="required",
            subjects={
                "pl": "Tłumaczenia czekają na akceptację",
                "en": "Translations wait for approval",
            },
            bodies={
                "pl": (
                    "<p>{organization_name}: {count} tłumaczeń czeka na Twoją decyzję.</p>"
                    '<p><a href="{panel_url}">Przejrzyj</a></p>'
                ),
                "en": (
                    "<p>{organization_name}: {count} translations wait for your decision.</p>"
                    '<p><a href="{panel_url}">Review them</a></p>'
                ),
            },
            allowed_context=frozenset({"organization_name", "count", "panel_url"}),
            audience=AUDIENCE_STAFF,
        )
    )
    register_email_template(
        EmailTemplate(
            key=AUTOMATION_PAUSED,
            version=1,
            category="required",
            subjects={
                "pl": "Automatyczne tłumaczenie zmian jest wstrzymane",
                "en": "Automatic translation of changes is paused",
            },
            bodies={
                "pl": (
                    "<p>{organization_name}: zmiany na stronie nie są teraz tłumaczone "
                    "automatycznie. Opublikowane tłumaczenia zostają; nowe poczekają, aż "
                    "przyczyna minie. Szczegóły są w panelu.</p>"
                    '<p><a href="{panel_url}">Otwórz panel</a></p>'
                ),
                "en": (
                    "<p>{organization_name}: changes on the site are not being translated "
                    "automatically right now. Published translations stay; new ones wait "
                    "until the cause is gone. The panel has the details.</p>"
                    '<p><a href="{panel_url}">Open the panel</a></p>'
                ),
            },
            allowed_context=frozenset({"organization_name", "panel_url"}),
            audience=AUDIENCE_STAFF,
        )
    )
