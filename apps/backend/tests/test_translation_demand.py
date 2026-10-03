"""Demand for automatic translation (TL21a, translation-sources.md §8.2–8.3).

The source is the in-memory one behind the real registry, as a module the
company's type composes; the notice goes through `notify_source_changed`
exactly as a module's service sends it.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.conf import settings as django_settings
from django.db import connection, transaction
from django.utils import timezone

from saas_core.content_protocol.registry import notify_source_changed
from saas_core.modules.core.organizations.models import Membership
from saas_core.modules.shared.translation.models import TranslationDemand
from saas_core.modules.shared.translation.services import change_settings
from saas_core.modules.shared.translation.settings_spec import demand_max_wait, demand_wait
from saas_core.testing.translation_sources import FakeDraftSource, registered_translation_source
from test_booking import membership, tenant

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("pages", "processor_listed")]

SOURCE = "testing.pages"


class Pages(FakeDraftSource):
    # A module the company's type composes (ADR-050).
    module_id = "shared.sites"


@pytest.fixture
def processor_listed(settings: Any) -> None:
    settings.MODEL_PORT_PROCESSOR_LISTED = True
    settings.SETTINGS_DEFAULTS = {}


@pytest.fixture
def pages() -> Iterator[Pages]:
    source = Pages(SOURCE)
    with registered_translation_source(source):
        yield source


def company(slug: str, *, automation: bool = True, kind: str | None = None) -> Membership:
    owner = membership(slug)
    organization = owner.organization
    organization.organization_type = (
        django_settings.DEFAULT_ORGANIZATION_TYPE if kind is None else kind
    )
    organization.save(update_fields=["organization_type"])
    if automation:
        with tenant(owner):
            change_settings(
                changes={
                    "translation.settings.processing_acknowledged": True,
                    "translation.settings.auto_changes": True,
                },
                expected_version=0,
                idempotency_key=f"auto-{slug}",
            )
    return owner


def changed(owner: Membership, *object_ids: UUID, change: str = "changed") -> None:
    with tenant(owner) as context:
        notify_source_changed(
            context=context,
            source_key=SOURCE,
            object_ids=list(object_ids),
            change=change,  # type: ignore[arg-type]
            cause="user",
        )


def demand(owner: Membership) -> list[TranslationDemand]:
    return list(
        TranslationDemand.all_objects.filter(organization=owner.organization).order_by("created_at")
    )


def test_a_change_waits_five_minutes_and_repeats_join_one_row(
    django_capture_on_commit_callbacks: object,
) -> None:
    owner = company("tl21-demand")
    first = uuid4()
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        changed(owner, first)
    (row,) = demand(owner)
    assert row.source_key == SOURCE and row.object_id == first
    assert row.state == "waiting"
    assert row.cause == f"user:{owner.user_id}"
    assert row.due_at - row.first_at == demand_wait()
    # Another publication of the same page moves the start, never past 30 minutes.
    TranslationDemand.all_objects.filter(pk=row.pk).update(
        first_at=timezone.now() - timedelta(minutes=28)
    )
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        changed(owner, first)
    (row,) = demand(owner)
    assert row.due_at == row.first_at + demand_max_wait()


def test_a_rolled_back_save_leaves_no_demand(django_capture_on_commit_callbacks: object) -> None:
    owner = company("tl21-rollback")
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        try:
            with transaction.atomic():
                changed(owner, uuid4())
                raise RuntimeError("the company's save failed")
        except RuntimeError:
            pass
    assert demand(owner) == []


@pytest.mark.parametrize(
    ("automation", "kind"),
    [
        (False, None),  # no consent
        (True, ""),  # a type that does not compose the translation module
    ],
)
def test_without_consent_or_the_module_nothing_is_recorded(
    django_capture_on_commit_callbacks: object, automation: bool, kind: str | None
) -> None:
    owner = company(f"tl21-off-{automation}-{kind}", automation=automation, kind=kind)
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        changed(owner, uuid4())
    assert demand(owner) == []


def test_a_monthly_limit_of_zero_turns_the_automation_off(
    django_capture_on_commit_callbacks: object,
) -> None:
    owner = company("tl21-zero")
    with tenant(owner):
        change_settings(
            changes={"translation.settings.auto_monthly_limit": 0},
            expected_version=1,
            idempotency_key="tl21-zero-limit",
        )
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        changed(owner, uuid4())
    assert demand(owner) == []


@pytest.mark.parametrize("change", ["withdrawn", "deleted"])
def test_a_withdrawn_or_deleted_object_drops_its_demand(
    django_capture_on_commit_callbacks: object, change: str
) -> None:
    owner = company(f"tl21-{change}")
    kept, gone = uuid4(), uuid4()
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        changed(owner, kept, gone)
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        changed(owner, gone, change=change)
    assert [row.object_id for row in demand(owner)] == [kept]


def test_demand_is_the_companys_own(django_capture_on_commit_callbacks: object) -> None:
    owner, other = company("tl21-own"), company("tl21-other")
    with django_capture_on_commit_callbacks(execute=True):  # type: ignore[operator]
        changed(owner, uuid4())
    assert len(demand(owner)) == 1 and demand(other) == []


def test_the_demand_table_forces_rls() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = %s",
            ["translation_translationdemand"],
        )
        assert cursor.fetchone() == (True, True)
