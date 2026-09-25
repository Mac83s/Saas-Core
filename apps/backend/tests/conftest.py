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
collect_ignore_glob = (
    []
    if "shared.image-generation" in settings.ACTIVE_MODULES
    else ["test_image_generation_*.py", "test_template_photos_command.py"]
)


@pytest.fixture(autouse=True)
def core_global_roles(settings: Any) -> None:
    settings.ORGANIZATION_TYPES = {
        key: replace(organization_type, roles=())
        for key, organization_type in settings.ORGANIZATION_TYPES.items()
    }
