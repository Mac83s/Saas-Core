"""A business card through the translation engine (TL12a): privacy on the
real `profiles.public_profile` source — a person's card goes to a model only
where the deployment lists `public_personal`, and never with the person's
name. Needs shared.translation: on conftest's list for profiles without it.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings

from saas_core.modules.shared.billing.models import EntitlementSnapshot
from saas_core.modules.shared.profiles.models import PublicProfileTranslation
from test_model_port import fake_models  # noqa: F401 — the port's fake models
from test_profiles_translation_source import (  # noqa: F401
    ProfilesDriver,
    _as,
    german_on_the_platform,
)

pytestmark = pytest.mark.django_db


def _engine_ready(monkeypatch: pytest.MonkeyPatch, driver: ProfilesDriver) -> None:
    """The engine of TL6 around the real card source: the port's fake model,
    a worker seen, a price, credits and the company's acknowledgement."""
    from saas_core.modules.shared.billing.models import CreditOperation
    from saas_core.modules.shared.model_port.adapters.fake import FAKE
    from saas_core.modules.shared.translation.services import change_settings
    from saas_core.modules.shared.translation.tasks import WORKER_SEEN
    from test_translation_jobs import translator

    monkeypatch.setattr(FAKE, "complete", translator())
    cache.set(WORKER_SEEN, 1, 300)
    CreditOperation.objects.filter(key="translation.characters").update(is_active=True, cost=2)
    EntitlementSnapshot.all_objects.filter(organization=driver.organization).update(
        quotas={"credits.monthly": 100},
        sources={"profiles.enabled": {"kind": "plan"}, "credits.monthly": {"kind": "plan"}},
    )
    with _as(driver.publisher):
        change_settings(
            changes={"translation.settings.processing_acknowledged": True},
            expected_version=0,
            idempotency_key=f"ack-{driver.organization.id}",
        )


@override_settings(MODEL_PORT_PROCESSOR_LISTED=True)
def test_a_persons_name_and_unlisted_personal_data_never_reach_the_model(
    monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    """Through the engine on the real source: a person's card is quoted empty
    while the deployment does not list `public_personal`; once it does, the
    job translates the card, and the model never sees the person's name."""
    from saas_core.modules.shared.model_port.adapters.fake import FAKE
    from saas_core.modules.shared.translation import worker
    from saas_core.modules.shared.translation.jobs import (
        TargetRequest,
        order_translation,
        quote_translation,
    )

    driver = ProfilesDriver()
    driver.create(["Cennik"])
    person = driver.create(["Portfolio"])
    _engine_ready(monkeypatch, driver)
    targets = [TargetRequest(source_key="profiles.public_profile", object_id=person, locale="de")]

    settings.MODEL_PORT_SENDABLE_DATA_CLASSES = ["public"]
    with _as(driver.publisher):
        assert quote_translation(targets=targets).quote.units == 0

    settings.MODEL_PORT_SENDABLE_DATA_CLASSES = ["public", "public_personal"]
    FAKE.calls.clear()
    with _as(driver.publisher):
        quoted = quote_translation(targets=targets)
        assert quoted.available, quoted.reasons
        job = order_translation(
            targets=targets,
            digest=quoted.quote.digest,
            expected_credits=quoted.quote.credits,
            idempotency_key="tl12a-person",
        ).value
    worker.run_job(job.organization_id, job.id)
    sent = "".join(str(message.content) for call in FAKE.calls for message in call.request.messages)
    assert "Stylistka" in sent and "Anna Nowak" not in sent
    row = PublicProfileTranslation.all_objects.get(profile_id=person, locale="de")
    assert row.headline and row.provenance["headline"]["origin"] == "ai"
