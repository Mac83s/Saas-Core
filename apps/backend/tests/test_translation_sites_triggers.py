"""The engine and company sites together (plan TL11d): a failing handler of a
source's notice never stops the site's publication or its webhook, and the
daily repair still starts the job; the automation publishes at most N pages
of one job, the rest wait as mass publication; the support overview names
states, never the company's texts, and stays in the company's history.

Imports the engine at the top, so `conftest.collect_ignore_glob` leaves it out
where the profile does not compose `shared.translation`.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings
from django.utils import timezone

# The module, not its contract class: importing the class would collect the
# whole page contract here a second time.
import test_sites_page_translation_source as page_tests
from saas_core.content_protocol.sources import ReviewItem
from saas_core.modules.core.organizations.context import activate_tenant_context
from saas_core.modules.core.organizations.models import OrganizationAuditEntry
from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.sites.models import PageTranslation, Site, SiteOutboxEvent
from saas_core.modules.shared.sites.translation_source import PAGE_SOURCE
from saas_core.modules.shared.translation import demand as demand_module
from saas_core.modules.shared.translation import engine_policy
from saas_core.modules.shared.translation.automation import start_due_demand
from saas_core.modules.shared.translation.demand import reconcile_demand
from saas_core.modules.shared.translation.models import (
    DemandState,
    JobState,
    ReviewState,
    TranslationDemand,
    TranslationJob,
    TranslationReviewItem,
)
from saas_core.modules.shared.translation.services import change_settings
from test_model_port import fake_models  # noqa: F401 — the port's fake models
from test_sites_ai_badge import operator
from test_translation_jobs import german, installed_source, run

pytestmark = pytest.mark.django_db

AUTO = "translation.settings.auto_changes"


def _automated(driver: page_tests.SitesPageDriver) -> None:
    """The company pays for translations and consented to the automation."""
    organization_id = driver.publisher.organization_id
    EntitlementSnapshot.all_objects.filter(organization_id=organization_id).update(
        quotas={"sites.max": 1000, "credits.monthly": 100},
        sources={
            "sites.enabled": {"kind": "plan"},
            "sites.max": {"kind": "plan"},
            "credits.monthly": {"kind": "plan"},
        },
    )
    with activate_tenant_context(driver.publisher):
        change_settings(
            changes={"translation.settings.processing_acknowledged": True, AUTO: True},
            expected_version=0,
            idempotency_key=f"consent-{organization_id}",
        )


@override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de"))
def test_a_failing_notice_handler_stops_neither_the_site_nor_the_repair(
    monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Any
) -> None:
    contract, driver = page_tests.TestSitesPageSource(), page_tests.SitesPageDriver()
    home = driver.create(["Witamy w studiu"])
    driver.publish(home)
    page_tests._job(contract, driver, home)  # German is live on the site
    _automated(driver)
    organization_id = driver.publisher.organization_id

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the engine is down")

    with installed_source(monkeypatch):
        with pytest.MonkeyPatch.context() as failing:
            failing.setattr(demand_module, "record_demand", broken)
            driver.edit(home, 0, "Zapraszamy do studia")
            with django_capture_on_commit_callbacks(execute=True):
                driver.publish(home)
        # The company's publication and its webhook went out regardless.
        site = Site.all_objects.get(pk=driver.site_id)
        assert SiteOutboxEvent.all_objects.filter(publication=site.current_publication).exists()
        assert not TranslationDemand.all_objects.filter(organization_id=organization_id).exists()

        # The daily repair finds the change whose notice got lost.
        assert reconcile_demand() >= 1
        (row,) = TranslationDemand.all_objects.filter(organization_id=organization_id)
        assert (row.source_key, row.object_id, row.cause) == ("sites.page", home, "schedule")
        job_id = start_due_demand(organization_id, row.due_at + timedelta(seconds=1))
        assert job_id is not None
        assert run(TranslationJob.all_objects.get(pk=job_id)).state == JobState.SUCCEEDED
    assert driver.public_texts(home, "de") == [german("Zapraszamy do studia")]


@override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de"))
def test_one_automatic_job_publishes_at_most_the_cap_and_the_rest_wait_together(
    monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Any
) -> None:
    contract, driver = page_tests.TestSitesPageSource(), page_tests.SitesPageDriver()
    # No digits: the stand-in translator changes every word, a number too.
    names = ["pierwsza", "druga", "trzecia", "czwarta"]
    pages = [driver.create([f"Strona {name}"]) for name in names]
    driver.publish(pages[0])
    for page in pages:
        page_tests._job(contract, driver, page)
    _automated(driver)
    organization_id = driver.publisher.organization_id
    monkeypatch.setattr(engine_policy, "mass_publication_cap", lambda: 2)

    with installed_source(monkeypatch):
        for name, page in zip(names, pages, strict=True):
            driver.edit(page, 0, f"Nowa strona {name}")
        with django_capture_on_commit_callbacks(execute=True):
            driver.publish(pages[0])
        rows = list(TranslationDemand.all_objects.filter(organization_id=organization_id))
        assert len(rows) == 4
        due = max(row.due_at for row in rows) + timedelta(seconds=1)
        job_id = start_due_demand(organization_id, due)
        assert job_id is not None
        assert run(TranslationJob.all_objects.get(pk=job_id)).state == JobState.SUCCEEDED

    live = [
        page
        for name, page in zip(names, pages, strict=True)
        if driver.public_texts(page, "de") == [german(f"Nowa strona {name}")]
    ]
    waiting = TranslationReviewItem.all_objects.filter(
        organization_id=organization_id, reason="mass_publication", state=ReviewState.OPEN
    )
    assert len(live) == 2
    assert pages[0] in live  # the home page goes first
    assert sorted(item.object_id for item in waiting) == sorted(set(pages) - set(live))

    # One decision takes the rest out together, in one publication.
    publications = Site.all_objects.get(pk=driver.site_id).publications.count()
    PAGE_SOURCE.review(
        context=driver.publisher,
        action="accept",
        items=[ReviewItem(item.object_id, item.locale, None) for item in waiting],
        idempotency_key=f"mass-{organization_id}",
    )
    assert Site.all_objects.get(pk=driver.site_id).publications.count() == publications + 1
    assert all(
        driver.public_texts(page, "de") == [german(f"Nowa strona {name}")]
        for name, page in zip(names, pages, strict=True)
    )


@override_settings(SITES_SUPPORTED_LOCALES=("pl", "en", "de"))
def test_the_support_overview_names_states_and_is_in_the_companys_history() -> None:
    driver = page_tests.SitesPageDriver()
    home = driver.create(["Tajna treść firmy"])
    driver.publish(home)
    organization_id = driver.publisher.organization_id
    now = timezone.now()
    TranslationDemand.all_objects.create(
        organization_id=organization_id,
        source_key="sites.page",
        object_id=home,
        cause="schedule",
        first_at=now,
        due_at=now,
        state=DemandState.BLOCKED,
        reason="monthly_limit",
    )
    staff = operator("support-overview@example.test")
    plain = operator("support-plain@example.test", staff=False)

    with pytest.raises(CommandError):
        call_command(
            "translation_support_overview",
            "--organization",
            str(organization_id),
            "--operator",
            staff.email,
        )
    with pytest.raises(CommandError):
        call_command(
            "translation_support_overview",
            "--organization",
            str(organization_id),
            "--operator",
            plain.email,
            "--reason",
            "zgłoszenie",
        )
    out = StringIO()
    call_command(
        "translation_support_overview",
        "--organization",
        str(organization_id),
        "--operator",
        staff.email,
        "--reason",
        "Zgłoszenie 123: tłumaczenia stoją",
        stdout=out,
    )

    report = out.getvalue()
    assert "Źródło sites.page:" in report
    assert "popyt automatu: monthly_limit 1" in report
    assert "Tajna treść" not in report and "Strona testowa" not in report
    (entry,) = OrganizationAuditEntry.objects.filter(
        organization_id=organization_id, action="translation.support_overview_viewed"
    )
    assert entry.actor_user_id == staff.id
    assert entry.metadata == {"reason": "Zgłoszenie 123: tłumaczenia stoją"}
    assert PageTranslation.all_objects.filter(page_id=home).exists()
