from .base import *  # noqa: F403

SECRET_KEY = "test-only-key"
MFA_ENCRYPTION_KEY = "test-mfa-encryption-key"
CONFIGURED_ALLOWED_HOSTS = ("testserver",)
ALLOWED_HOSTS = ["*"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
MIDDLEWARE = [  # noqa: F405
    middleware
    for middleware in MIDDLEWARE  # noqa: F405
    if middleware != "whitenoise.middleware.WhiteNoiseMiddleware"
]
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
CELERY_TASK_ALWAYS_EAGER = True
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
OBJECT_STORAGE_ENDPOINT_URL = "http://object-storage.test"
OBJECT_STORAGE_PUBLIC_ENDPOINT_URL = "http://object-storage.test"
OBJECT_STORAGE_BUCKET = "test-media"
OBJECT_STORAGE_REGION = "us-east-1"
OBJECT_STORAGE_FORCE_PATH_STYLE = True
OBJECT_STORAGE_ACCESS_KEY_ID = "test-access-key"
OBJECT_STORAGE_SECRET_ACCESS_KEY = "test-secret-key"
CLAMAV_HOST = "clamav.test"

# ADR-041: the door and the front door are the same connection here. The test
# database connects as an owner that row-level security does not apply to, so a
# second identity would prove nothing about isolation and would only force every
# API test to declare a second database. What the door is for — a countable list
# of reads that happen before a tenant is known — is checked by
# tests/test_pre_tenant_door.py against the source, and its behaviour is checked
# where it exists: on a running deployment, under the unprivileged app role.
PRE_TENANT_DATABASE_ALIAS = "default"
# A new mapping rather than a mutation: `from .base import *` shares the object,
# and popping from it would rewrite the deployment's own configuration.
DATABASES = {"default": DATABASES["default"]}  # noqa: F405
