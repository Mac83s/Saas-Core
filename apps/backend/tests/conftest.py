"""Core's tests describe core's global system roles (ADR-050).

A product that gives its organization types their own roles (HoofCare's
trimming company: owner, office, trimmer…) would otherwise send every core test
that invites a "manager" or a "staff" member into a type where no such role
exists. So by default the suite runs with the types' own roles set aside; the
tests of typed roles (`test_organization_roles.py`) configure the types they
need themselves.
"""

from dataclasses import replace
from typing import Any

import pytest
from django.conf import settings

# A module's tests that import its models at the top cannot even be collected
# where the profile does not compose the module (a product repository runs
# the core suite under its own profile); `skipif` comes too late for them.
collect_ignore_glob = [
    *(
        []
        if "shared.image-generation" in settings.ACTIVE_MODULES
        else ["test_image_generation_*.py", "test_template_photos_command.py"]
    ),
    # HoofCare and MedPlano compose neither the model port nor translation; a new
    # test file importing either module at the top belongs on these lists.
    *([] if "shared.model-port" in settings.ACTIVE_MODULES else ["test_model_port.py"]),
    # Nor the assistant, whose tests script the model port's fake adapter.
    *(
        []
        if "shared.assistant" in settings.ACTIVE_MODULES
        else ["test_assistant_*.py"]
    ),
    # MedPlano does not compose the farm register.
    *([] if "shared.farms" in settings.ACTIVE_MODULES else ["test_farms_today.py"]),
    *(
        []
        if "shared.translation" in settings.ACTIVE_MODULES
        else [
            "test_platform_ai_settings.py",
            "test_profiles_translation_engine.py",
            "test_translation_automation.py",
            "test_translation_commands.py",
            "test_translation_demand.py",
            "test_translation_e2e_fixture.py",
            "test_translation_engine.py",
            "test_translation_evals.py",
            "test_translation_jobs.py",
            "test_translation_notify.py",
            "test_translation_review.py",
            "test_translation_settings.py",
            "test_translation_sites_triggers.py",
            "test_translation_withdrawal.py",
        ]
    ),
]


@pytest.fixture(autouse=True)
def core_global_roles(settings: Any) -> None:
    settings.ORGANIZATION_TYPES = {
        key: replace(organization_type, roles=())
        for key, organization_type in settings.ORGANIZATION_TYPES.items()
    }
