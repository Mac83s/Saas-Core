"""Settings for static checks, composed so verticals are actually visible.

`test` defaults to the `business` profile, which composes no vertical at all.
Under it django-stubs does not see a vertical's models as models — their
managers read as ordinary class attributes and every queryset in the module
raises "Access to generic instance variables via class is ambiguous", while the
real errors hide among them. `makemigrations --check` had the same blind spot:
it reported no pending changes for models it never loaded.

`hoofcare` is the profile that composes the vertical carrying models today. When
a second vertical grows its own, this needs a profile that composes both, or the
check needs to run once per profile the way the test suite already does.
"""

import os

os.environ["DEPLOYMENT"] = "hoofcare"

from .test import *  # noqa: E402, F403
