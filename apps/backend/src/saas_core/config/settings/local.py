from .base import *  # noqa: F403

DEBUG = True
SECRET_KEY = SECRET_KEY or "unsafe-local-development-key"  # noqa: F405
MFA_ENCRYPTION_KEY = MFA_ENCRYPTION_KEY or SECRET_KEY  # noqa: F405
ALLOWED_HOSTS = ALLOWED_HOSTS or ["127.0.0.1", "localhost"]  # noqa: F405
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
