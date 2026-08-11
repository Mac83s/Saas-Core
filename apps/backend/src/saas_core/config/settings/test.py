from .base import *  # noqa: F403

SECRET_KEY = "test-only-key"
MFA_ENCRYPTION_KEY = "test-mfa-encryption-key"
ALLOWED_HOSTS = ["testserver"]
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
