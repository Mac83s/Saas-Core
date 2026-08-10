from .test import *  # noqa: F403

# `makemigrations --check` is a static model-state check. It must not depend on
# whichever migration history happens to exist in a developer's runtime database.
DATABASES["default"]["HOST"] = "127.0.0.1"  # noqa: F405
DATABASES["default"]["PORT"] = 1  # noqa: F405
