"""Settings for static checks: every module this repository ships.

mypy, `makemigrations --check` and the OpenAPI contract read the code, not a
running product, so they compose the whole catalogue in
`packages/contracts/modules/` rather than one profile. A profile is what runs;
the catalogue is what the repository carries and has to compile. MedPlano
leaves the farm register out of its product, yet the core's api-client and
panel still type against the register's endpoints.

django-stubs does not see models of an app missing from INSTALLED_APPS as
models — their managers read as ordinary class attributes and every queryset
raises "Access to generic instance variables via class is ambiguous", while the
real errors hide among them. Installing the whole catalogue removes that blind
spot for every module at once.

The process itself still starts as the repository's main profile from
`product.json` (ADR-049): its artifact is verified as usual, and only the module
list is widened afterwards.
"""

import os
from pathlib import Path

from saas_core.config.composition import compose, django_apps_for, product_profile

os.environ["DEPLOYMENT"] = product_profile(Path(__file__).resolve().parents[6])

from .test import *  # noqa: E402, F403
from .test import ACTIVE_MODULES, INSTALLED_APPS, MODULE_CATALOG  # noqa: E402

_shipped = compose(tuple(MODULE_CATALOG), MODULE_CATALOG)
INSTALLED_APPS = [
    *INSTALLED_APPS,
    *django_apps_for(tuple(m for m in _shipped if m not in ACTIVE_MODULES), MODULE_CATALOG),
]
ACTIVE_MODULES = _shipped
