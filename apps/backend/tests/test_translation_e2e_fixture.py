"""The stand-in translator of browser tests (TL15d): one company is translated
by `fake/echo`, without a script and without a real model — only where the
stack switches the stand-in on by name, and only while the company is listed."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from io import StringIO
from typing import Any

import pytest
from django.core.management import CommandError, call_command
from django.test import override_settings

from saas_core.modules.core.organizations.models import PlatformSettingEntry
from saas_core.modules.shared.model_port.adapters.fake import FAKE, FakeAdapter
from saas_core.modules.shared.model_port.api import ModelContext, task_status
from saas_core.modules.shared.model_port.matrix import MODELS, register_model
from saas_core.modules.shared.model_port.models import TestDoubleCompany, UsageEntry
from saas_core.modules.shared.model_port.registry import task_spec
from saas_core.modules.shared.model_port.test_double import (
    ECHO_MODEL,
    echo_profile,
    routed,
    uses_stand_in,
)
from saas_core.modules.shared.translation.models import (
    ItemState,
    JobState,
    TranslationJobItem,
)
from test_model_port import fake_models  # noqa: F401 — the port's fake models
from test_sites_ai_badge import operator
from test_translation_jobs import JobSource, company, installed_source, order, page, run

pytestmark = pytest.mark.django_db
TASK = "translation.text"


@pytest.fixture
def pages(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobSource]:
    """A stack that asked for the stand-in by name, as the e2e environment does."""
    with installed_source(monkeypatch) as installed, override_settings(MODEL_PORT_TEST_DOUBLE=True):
        # The adapter as it runs in a worker: no test answers for it.
        monkeypatch.setattr(FAKE, "complete", FakeAdapter.complete.__get__(FAKE))
        FAKE.reset()
        # `ready()` registers the model where the setting is on at startup.
        register_model(echo_profile())
        try:
            yield installed
        finally:
            MODELS.pop(("fake", ECHO_MODEL), None)


Fixture = Callable[..., str]


@pytest.fixture
def fixture() -> Fixture:
    def run_command(*args: str, **options: Any) -> str:
        out = StringIO()
        call_command("translation_e2e_fixture", *args, stdout=out, **options)
        return out.getvalue()

    return run_command


def test_a_listed_company_is_translated_by_the_stand_in(pages: JobSource, fixture: Fixture) -> None:
    owner = company("e2e-echo")
    staff = operator()
    said = fixture("on", organization=owner.organization.slug, operator=staff.email)
    assert said.strip() == "e2e-echo: tłumaczy atrapa."

    first = page(pages, "Zadzwoń: ⟦m:1⟧ po 15:00", "Oferta od 120 zł")
    job = run(order(owner, [first]))

    assert job.state == JobState.SUCCEEDED
    (item,) = TranslationJobItem.all_objects.filter(job=job)
    assert item.state == ItemState.WRITTEN
    # Every piece back with its language in front; tokens, numbers and all.
    written = {
        target.text
        for (locale, _basis), targets in pages.objects[first].targets.items()
        if locale == "de"
        for target in targets.values()
    }
    assert written == {"[de] Zadzwoń: ⟦m:1⟧ po 15:00", "[de] Oferta od 120 zł"}
    call = UsageEntry.objects.filter(organization_id=owner.organization_id, task=TASK).latest(
        "created_at"
    )
    assert (call.resolved_model, call.adapter, call.cost_usd_micros) == (ECHO_MODEL, "fake", 0)
    # A worker runs for days: the stand-in keeps no record of its calls.
    assert FAKE.calls == []


def test_only_the_listed_company_and_only_until_it_is_taken_off(
    pages: JobSource, fixture: Fixture
) -> None:
    owner, other = company("e2e-listed"), company("e2e-other")
    staff = operator()
    spec = task_spec(TASK)
    assert spec is not None

    fixture("on", organization=owner.organization.slug, operator=staff.email)
    # Twice is once.
    fixture("on", organization=owner.organization.slug, operator=staff.email)

    assert routed(spec, owner.organization_id).model == ECHO_MODEL
    assert routed(spec, other.organization_id) is spec
    assert routed(spec, None) is spec
    status = task_status(TASK, ModelContext(organization_id=owner.organization_id))
    assert (status.available, status.model) == (True, ECHO_MODEL)
    assert task_status(TASK).model == spec.model
    row = TestDoubleCompany.objects.get()
    assert (row.organization_id, row.added_by) == (owner.organization_id, staff.email)
    assert "e2e-listed" in fixture("show") and staff.email in fixture("show")
    # No model, price or any other platform value was written.
    assert not PlatformSettingEntry.objects.exists()

    said = fixture("off", organization=owner.organization.slug, operator=staff.email)
    assert said.strip() == "e2e-listed: tłumaczy prawdziwy model."
    assert routed(spec, owner.organization_id) is spec
    assert not TestDoubleCompany.objects.exists()
    assert "Żadna firma" in fixture("show")


def test_a_row_alone_changes_nothing_where_the_stack_did_not_ask_for_the_stand_in(
    pages: JobSource, fixture: Fixture
) -> None:
    """The dev VPS runs as APP_ENV=local, so the environment's name is no
    guard: a company listed there keeps the real model while the switch is off."""
    owner = company("e2e-switch-off")
    staff = operator()
    spec = task_spec(TASK)
    assert spec is not None
    fixture("on", organization=owner.organization.slug, operator=staff.email)
    assert uses_stand_in(owner.organization_id)

    with override_settings(MODEL_PORT_TEST_DOUBLE=False, APP_ENV="local"):
        # The row is still there…
        assert TestDoubleCompany.objects.filter(pk=owner.organization_id).exists()
        # …and nobody is routed by it,
        assert not uses_stand_in(owner.organization_id)
        assert routed(spec, owner.organization_id) is spec
        status = task_status(TASK, ModelContext(organization_id=owner.organization_id))
        assert status.model == spec.model
        # and the command refuses to add, remove or list.
        for action in ("on", "off"):
            with pytest.raises(CommandError, match="MODEL_PORT_TEST_DOUBLE"):
                fixture(action, organization=owner.organization.slug, operator=staff.email)
        with pytest.raises(CommandError, match="MODEL_PORT_TEST_DOUBLE"):
            fixture("show")


def test_the_switch_is_off_unless_the_stack_says_so() -> None:
    from django.conf import settings

    assert settings.MODEL_PORT_TEST_DOUBLE is False
    # Without it the stand-in's model is not even a row of the matrix.
    assert ("fake", ECHO_MODEL) not in MODELS


def test_the_command_takes_an_operator_and_a_company_that_exists(
    pages: JobSource, fixture: Fixture
) -> None:
    owner = company("e2e-who")
    staff = operator()
    with pytest.raises(CommandError, match="nie jest operatorem"):
        fixture("on", organization=owner.organization.slug, operator=owner.user.email)
    with pytest.raises(CommandError, match="Nie ma firmy o slugu e2e-nobody"):
        fixture("on", organization="e2e-nobody", operator=staff.email)
    with pytest.raises(CommandError, match="slug firmy testu"):
        fixture("on", operator=staff.email)
    assert not TestDoubleCompany.objects.exists()
