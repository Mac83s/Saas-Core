"""Settings for static checks, composed as the product this repository ships.

`test` defaults to the `business` profile. In a product repository that
composes no vertical at all: django-stubs does not see the vertical's models as
models — their managers read as ordinary class attributes and every queryset
raises "Access to generic instance variables via class is ambiguous", while the
real errors hide among them. `makemigrations --check` had the same blind spot.

So the profile comes from `product.json`, the one slot each repository fills
with its own product (ADR-049): `business` in Saas-Core, the product's profile
in a product repository. The OpenAPI contract is generated under these settings
too, so each repository's contract describes its own product.
"""

import os
from pathlib import Path

from saas_core.config.composition import product_profile

os.environ["DEPLOYMENT"] = product_profile(Path(__file__).resolve().parents[6])

from .test import *  # noqa: E402, F403
