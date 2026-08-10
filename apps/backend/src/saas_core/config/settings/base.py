import os
from pathlib import Path
from urllib.parse import quote

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parents[4]


def secret_setting(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    file_path = os.environ.get(f"{name}_FILE")
    if value is not None and file_path is not None:
        raise ImproperlyConfigured(f"Ustaw tylko {name} albo {name}_FILE, nie oba")
    if file_path is None:
        return value if value is not None else default
    try:
        return Path(file_path).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ImproperlyConfigured(f"Nie można odczytać sekretu {name}_FILE") from error


SECRET_KEY = secret_setting("DJANGO_SECRET_KEY")
MFA_ENCRYPTION_KEY = secret_setting("MFA_ENCRYPTION_KEY")
MFA_ISSUER_NAME = os.environ.get("MFA_ISSUER_NAME", "SaaS Core")
MFA_CHALLENGE_TTL_SECONDS = int(os.environ.get("MFA_CHALLENGE_TTL_SECONDS", "300"))
if MFA_CHALLENGE_TTL_SECONDS <= 0:
    raise ImproperlyConfigured("Czas ważności wyzwania MFA musi być dodatni")
DEBUG = False
ALLOWED_HOSTS = [host for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "saas_core.modules.core.health",
    "saas_core.modules.core.identity",
    "saas_core.modules.core.organizations",
]

MIDDLEWARE = [
    "saas_core.http.middleware.CorrelationIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "saas_core.modules.core.identity.middleware.ManagedUserSessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "saas_core.config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
WSGI_APPLICATION = "saas_core.config.wsgi.application"
ASGI_APPLICATION = "saas_core.config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "saas_core"),
        "USER": os.environ.get("POSTGRES_USER", "saas_core"),
        "PASSWORD": secret_setting("POSTGRES_PASSWORD", "saas_core"),
        "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        "PORT": int(os.environ.get("POSTGRES_PORT", "5432")),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pl"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "identity.User"

REDIS_URL = secret_setting("REDIS_URL")
if not REDIS_URL:
    redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
    redis_port = int(os.environ.get("REDIS_PORT", "6379"))
    redis_database = int(os.environ.get("REDIS_DATABASE", "0"))
    redis_password = secret_setting("REDIS_PASSWORD")
    redis_credentials = f"default:{quote(redis_password, safe='')}@" if redis_password else ""
    REDIS_URL = f"redis://{redis_credentials}{redis_host}:{redis_port}/{redis_database}"
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_NAME = os.environ.get(
    "SESSION_COOKIE_NAME",
    f"saas_core_{os.environ.get('DEPLOYMENT', 'core-only').replace('-', '_')}_session",
)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_PATH = "/"
SESSION_IDLE_TIMEOUT_SECONDS = int(os.environ.get("SESSION_IDLE_TIMEOUT_SECONDS", "1800"))
SESSION_MAX_LIFETIME_SECONDS = int(os.environ.get("SESSION_MAX_LIFETIME_SECONDS", "86400"))
if SESSION_IDLE_TIMEOUT_SECONDS <= 0 or SESSION_MAX_LIFETIME_SECONDS <= 0:
    raise ImproperlyConfigured("Limity czasu sesji muszą być dodatnie")
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_FAILURE_VIEW = "saas_core.http.csrf.csrf_failure"

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = secret_setting("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() in {"1", "true", "yes"}
EMAIL_FILE_PATH = os.environ.get("EMAIL_FILE_PATH")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "SaaS Core <noreply@localhost>")
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:8080")
EMAIL_VERIFICATION_TTL_SECONDS = int(os.environ.get("EMAIL_VERIFICATION_TTL_SECONDS", "86400"))
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS = int(
    os.environ.get("EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS", "60")
)
PASSWORD_RESET_TTL_SECONDS = int(os.environ.get("PASSWORD_RESET_TTL_SECONDS", "3600"))
PASSWORD_RESET_RESEND_COOLDOWN_SECONDS = int(
    os.environ.get("PASSWORD_RESET_RESEND_COOLDOWN_SECONDS", "60")
)

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {"()": "saas_core.observability.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        }
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

LOG_DIRECTORY = os.environ.get("LOG_DIRECTORY")
if LOG_DIRECTORY:
    log_service = os.environ.get("LOG_SERVICE", "process")
    if not log_service.replace("-", "").replace("_", "").isalnum():
        raise ImproperlyConfigured("LOG_SERVICE zawiera niedozwolone znaki")
    LOGGING["handlers"]["file"] = {  # type: ignore[index]
        "class": "logging.FileHandler",
        "filename": str(Path(LOG_DIRECTORY) / f"{log_service}.jsonl"),
        "formatter": "json",
    }
    LOGGING["root"]["handlers"].append("file")  # type: ignore[index]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "saas_core.http.exceptions.problem_details_exception_handler",
    "NUM_PROXIES": int(os.environ.get("TRUSTED_PROXY_COUNT", "1")),
    "DEFAULT_THROTTLE_RATES": {
        "identity_login": "5/min",
        "identity_mfa_challenge": "10/min",
        "identity_mfa_enrollment": "10/min",
        "identity_password_reset_request": "5/min",
        "identity_password_reset_confirm": "10/min",
        "identity_register": "5/min",
        "identity_verification_resend": "5/min",
        "identity_verification_confirm": "10/min",
    },
}
SPECTACULAR_SETTINGS = {
    "TITLE": "SaaS Core API",
    "DESCRIPTION": "Wersjonowane API modularnej platformy SaaS Core.",
    "VERSION": "1.0.0",
    "OAS_VERSION": "3.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

DEPLOYMENT = os.environ.get("DEPLOYMENT", "core-only")
APPLICATION_VERSION = os.environ.get("APPLICATION_VERSION", "0.1.0")
HEALTH_CHECK_DEPENDENCIES = True
