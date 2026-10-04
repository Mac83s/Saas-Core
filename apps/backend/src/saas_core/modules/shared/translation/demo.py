"""Translation's part of the demo (core/organizations/demo.py): one
translation left waiting for a person — and no paid model call, ever.

Two things, both from `TranslationConfig.ready`:

- before anything is written (`guard`): a company that has its automatic
  translations switched on would have the seed's own writes — a document
  approved, a page published — ordered for translation by a real model. The
  seed does not go on with such a company unless the model's stand-in answers
  for it;
- after the content is there (`seed_waiting`): what the other parts noted in
  the run's memo (`translation.wanted`: a document's missing language) is
  ordered the way a person orders it from the panel — but only where the
  stack runs the model's stand-in (`MODEL_PORT_TEST_DOUBLE`, never on a stack
  served over https). The company is put on the stand-in's list first, so the
  job is answered by `fake/echo` („[en] tekst źródłowy”), costs no model call
  and waits in „Tłumaczenia → Do akceptacji”. Elsewhere the step is skipped
  and the run says so.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework.exceptions import APIException

from saas_core.content_protocol.registry import translation_sources
from saas_core.modules.core.organizations.context import set_local_organization_id
from saas_core.modules.shared.model_port.models import TestDoubleCompany
from saas_core.modules.shared.model_port.test_double import enabled, uses_stand_in

from .demand import automation_on
from .jobs import TargetRequest, order_translation, quote_translation
from .services import PROCESSING_ACK, change_settings, read_settings

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import DemoRun

#: The run's memo key the content modules' parts write to.
WANTED = "translation.wanted"
#: Who put a company on the stand-in's list.
ADDED_BY = "seed_demo"


def guard(run: DemoRun) -> None:
    """No company whose own automation would send the seed's texts to a real
    model: one answered by the stand-in is safe, any other is left out."""
    for key, organization in list(run.organizations.items()):
        with transaction.atomic():
            set_local_organization_id(organization.id)
            automatic = any(
                automation_on(organization.id, source.key) for source in translation_sources()
            )
        if automatic and not uses_stand_in(organization.id):
            run.leave_out(
                key,
                "firma ma włączone automatyczne tłumaczenia, więc zapisy danych demo zleciłyby "
                "płatne tłumaczenia prawdziwemu modelowi — wyłącz je w Ustawieniach › "
                "Tłumaczenia i uruchom ponownie",
            )


def seed_waiting(run: DemoRun) -> None:
    wanted: list[dict[str, Any]] = [
        item for item in run.memo.get(WANTED, ()) if item["company"] in run.organizations
    ]
    if not wanted:
        return
    if not enabled():
        run.log(
            f"= tłumaczenia „Do akceptacji” pominięte ({len(wanted)}): atrapa modelu "
            "(MODEL_PORT_TEST_DOUBLE) nie działa na tym stosie, a prawdziwego modelu dane "
            "demo nie wołają"
        )
        return
    for item in wanted:
        key = item["company"]
        if not any(spec.key == key for spec in run.scenario.organizations):
            continue
        try:
            with run.acting(key, step_up=True):
                _order(run, key, item)
        except (APIException, DjangoValidationError) as error:
            name = run.spec(key).name
            run.log(
                f"! tłumaczenie {item['label']} ({item['locale']}) {name}: "
                f"{getattr(error, 'detail', error)}"
            )


def _order(run: DemoRun, key: str, item: dict[str, Any]) -> None:
    organization = run.organizations[key]
    # The stand-in first: from here on this company's translations cost no
    # model call, whatever orders them.
    TestDoubleCompany.objects.get_or_create(
        organization_id=organization.id, defaults={"added_by": ADDED_BY}
    )
    settings = read_settings()
    if not settings["processing_acknowledged"]:
        change_settings(
            changes={PROCESSING_ACK: True},
            expected_version=settings["version"],
            idempotency_key=str(run.stable_id("translation-ack", organization.slug)),
        )
    targets = [
        TargetRequest(
            source_key=item["source_key"], object_id=item["object_id"], locale=item["locale"]
        )
    ]
    quoted = quote_translation(targets=targets)
    name = run.spec(key).name
    if not quoted.available or quoted.quote.units == 0:
        why = ", ".join(quoted.reasons) or "nie ma nic do przetłumaczenia"
        run.log(f"= tłumaczenie {item['label']} ({item['locale']}) {name} pominięte: {why}")
        return
    order_translation(
        targets=targets,
        digest=quoted.quote.digest,
        expected_credits=quoted.quote.credits,
        idempotency_key=str(
            run.stable_id(
                "translation",
                organization.slug,
                str(item["object_id"]),
                item["locale"],
                quoted.quote.digest,
            )
        ),
    )
    run.log(
        f"+ tłumaczenie {item['label']} ({item['locale']}) {name}: zlecone atrapie modelu, "
        "poczeka w „Tłumaczenia → Do akceptacji”"
    )
