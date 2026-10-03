import os

from django.core.exceptions import ImproperlyConfigured

from .staging import *  # noqa: F403

APP_ENV = os.environ.get("APP_ENV", "staging")

if APP_ENV not in {"local", "staging"}:
    raise ImproperlyConfigured("APP_ENV musi mieć wartość local albo staging")
if APP_ENV == "staging" and not CSRF_TRUSTED_ORIGINS:  # noqa: F405
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS jest wymagany na stagingu")

if APP_ENV == "local":
    globals().update(
        local_transport_security(PUBLIC_SITE_SCHEME, SECURE_HSTS_SECONDS)  # noqa: F405
    )
