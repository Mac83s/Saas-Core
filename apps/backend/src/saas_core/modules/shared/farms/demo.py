"""The farms' part of the demo (core/organizations/demo.py): a company's card of
a farm, and the farmer's account linked to it by an activation code.

Scenario data (between organizations): `{"links": [{"company": key, "farm": key,
"card": {"name", "keeper_name", "email", "phone", "village"}}]}`. The company
issues the code and the farm redeems it, the way the two of them would in the
panel; a card that is already linked is left as it is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import Farm
from .services import create_farm
from .sharing import _share_of_card, issue_activation_code, redeem_activation_code

if TYPE_CHECKING:
    from saas_core.modules.core.organizations.demo import DemoRun


def seed_farm_links(run: DemoRun) -> None:
    for link in (run.scenario.data.get("farms") or {}).get("links", []):
        _link(run, link)


def _link(run: DemoRun, link: dict[str, Any]) -> None:
    company = run.organizations[link["company"]]
    card = link["card"]
    with run.acting(link["company"]) as request:
        farm = Farm.all_objects.filter(organization=company, name=card["name"]).first()
        if farm is None:
            farm = create_farm(request=request, data=dict(card))
            run.log(f"+ karta gospodarstwa {farm.name} u {company.name}")
        if _share_of_card(company.id, farm.id) is not None:
            run.log(f"= {farm.name} połączone z kontem rolnika")
            return
        code, _expires = issue_activation_code(request=request, farm_id=farm.id)
    with run.acting(link["farm"]) as request:
        redeem_activation_code(request=request, code=code)
    run.log(f"+ {farm.name} połączone kodem z {run.organizations[link['farm']].name}")
