import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from django.core.exceptions import ImproperlyConfigured

from saas_core.config.composition import (
    CompositionError,
    compose,
    django_apps_for,
    load_catalog,
    select_by_module,
    verify_artifact,
)


def _deployment_billing_plan_keys(profile: dict[str, Any], modules: list[str]) -> tuple[str, ...]:
    if "shared.billing" not in modules:
        return ()
    billing = profile.get("billing")
    raw_plan_keys = billing.get("planKeys") if isinstance(billing, dict) else None
    if not isinstance(raw_plan_keys, list) or not all(
        isinstance(value, str) and value.strip() for value in raw_plan_keys
    ):
        raise ImproperlyConfigured("Profil z shared.billing wymaga listy billing.planKeys")
    plan_keys = tuple(value.strip() for value in raw_plan_keys)
    if len(plan_keys) != 3 or len(plan_keys) != len(set(plan_keys)):
        raise ImproperlyConfigured(
            "Profil z shared.billing wymaga dokładnie 3 unikalnych billing.planKeys"
        )
    return plan_keys


def _settings_environment() -> str:
    configured = os.environ.get("APP_ENV")
    if configured is not None:
        return configured.strip().lower()
    module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    if module.endswith((".test", ".migration_check", ".typecheck")):
        return "test"
    if module.endswith(".local"):
        return "local"
    return "staging"


def _validate_billing_provider(
    provider: str,
    *,
    app_env: str,
    stripe_livemode: bool,
) -> str:
    if provider not in {"stripe", "simulated"}:
        raise ImproperlyConfigured("BILLING_PROVIDER musi mieć wartość stripe albo simulated")
    if provider == "simulated" and app_env not in {"local", "test", "staging"}:
        raise ImproperlyConfigured(
            "BILLING_PROVIDER=simulated jest dozwolony tylko w local, test albo staging"
        )
    if provider == "simulated" and stripe_livemode:
        raise ImproperlyConfigured(
            "BILLING_PROVIDER=simulated nie może działać z STRIPE_LIVEMODE=true"
        )
    return provider


BASE_DIR = Path(__file__).resolve().parents[4]
APP_ENV = _settings_environment()

DEPLOYMENT = os.environ.get("DEPLOYMENT", "core-only")
_deployment_profile_setting = os.environ.get("DEPLOYMENT_PROFILE_PATH")
DEPLOYMENT_PROFILE_PATH = (
    Path(_deployment_profile_setting)
    if _deployment_profile_setting is not None
    else BASE_DIR.parent.parent / "deployments" / DEPLOYMENT / "deployment.json"
)
try:
    _deployment_profile = json.loads(DEPLOYMENT_PROFILE_PATH.read_text(encoding="utf-8"))
    _deployment_product = _deployment_profile["product"]
    _deployment_id = _deployment_profile["id"]
    _deployment_default_locale = _deployment_product["defaultLocale"]
    _deployment_supported_locales = _deployment_product["supportedLocales"]
    _deployment_platform_domain = _deployment_product["platformDomain"]
    _deployment_modules = _deployment_profile["modules"]
    _deployment_features = _deployment_profile["features"]
except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
    raise ImproperlyConfigured(
        f"Nie można odczytać profilu deploymentu: {DEPLOYMENT_PROFILE_PATH}"
    ) from error
if _deployment_id != DEPLOYMENT:
    raise ImproperlyConfigured(f"Profil {_deployment_id} nie odpowiada deploymentowi {DEPLOYMENT}")
BILLING_PLAN_KEYS = _deployment_billing_plan_keys(_deployment_profile, _deployment_modules)
if (
    not isinstance(_deployment_supported_locales, list)
    or not _deployment_supported_locales
    or any(locale not in {"pl", "en"} for locale in _deployment_supported_locales)
    or _deployment_default_locale not in _deployment_supported_locales
):
    raise ImproperlyConfigured("Profil deploymentu zawiera nieobsługiwaną konfigurację locale")
SITES_SUPPORTED_LOCALES = tuple(dict.fromkeys(_deployment_supported_locales))
SITES_DEFAULT_LOCALE = _deployment_default_locale
SITES_PLATFORM_DOMAIN = str(_deployment_platform_domain).strip().lower().rstrip(".")
SITES_RESERVED_SUBDOMAIN_LABELS = tuple(
    value.strip().casefold()
    for value in os.environ.get("SITES_RESERVED_SUBDOMAIN_LABELS", "").split(",")
    if value.strip()
)
#: The catalog the profile names its modules from. Read from disk rather than
#: duplicated here so the rules CI checks and the rules that boot the process
#: are the same rules over the same file.
MODULE_CATALOG_PATH = Path(
    os.environ.get(
        "MODULE_CATALOG_PATH",
        BASE_DIR.parent.parent / "packages" / "contracts" / "modules",
    )
)
try:
    _module_catalog = load_catalog(MODULE_CATALOG_PATH)
    #: This deployment's modules, dependencies first. Everything composed below
    #: — apps, middleware, URLs, scheduled work — is selected by this tuple.
    ACTIVE_MODULES = compose(_deployment_modules, _module_catalog)
except CompositionError as error:
    raise ImproperlyConfigured(
        f"Profil {DEPLOYMENT} nie składa się z katalogu {MODULE_CATALOG_PATH}: {error}"
    ) from error
KNOWN_MODULES = frozenset(_module_catalog)

#: The fingerprint of this composed product, generated once by
#: `pnpm deployment:artifact` and carried into every image built from that tree.
#: Backend, worker, scheduler and frontend are separate images; comparing this
#: is how a frontend built from one tree notices it is talking to a backend
#: built from another, instead of showing a menu whose routes answer 404.
MODULE_ARTIFACT_PATH = Path(
    os.environ.get(
        "MODULE_ARTIFACT_PATH",
        BASE_DIR.parent.parent / "deployments" / DEPLOYMENT / "module-artifact.json",
    )
)
try:
    PROFILE_HASH = verify_artifact(
        json.loads(MODULE_ARTIFACT_PATH.read_text(encoding="utf-8")),
        deployment=DEPLOYMENT,
        modules=ACTIVE_MODULES,
        catalog=_module_catalog,
    )
except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
    raise ImproperlyConfigured(
        f"Nie można odczytać artefaktu modułów: {MODULE_ARTIFACT_PATH}"
    ) from error
except CompositionError as error:
    # An image whose artifact does not describe what it composed was built from
    # a tree that no longer exists. Starting it would mean serving a product
    # nobody assembled.
    raise ImproperlyConfigured(f"Artefakt modułów nie opisuje tego deploymentu: {error}") from error

BOOKING_MODULE_ENABLED = "shared.booking" in ACTIVE_MODULES
PUBLIC_BOOKING_ENABLED = bool(_deployment_features.get("publicBooking", False))
if not SITES_PLATFORM_DOMAIN:
    raise ImproperlyConfigured("Profil deploymentu wymaga platformDomain")
DOMAIN_DNS_CNAME_TARGET = (
    os.environ.get("DOMAIN_DNS_CNAME_TARGET", SITES_PLATFORM_DOMAIN).strip().lower().rstrip(".")
)
DOMAIN_DNS_EXPECTED_IPV4 = tuple(
    value.strip()
    for value in os.environ.get("DOMAIN_DNS_EXPECTED_IPV4", "").split(",")
    if value.strip()
)
DOMAIN_DNS_EXPECTED_IPV6 = tuple(
    value.strip()
    for value in os.environ.get("DOMAIN_DNS_EXPECTED_IPV6", "").split(",")
    if value.strip()
)
DOMAIN_DNS_TIMEOUT_SECONDS = float(os.environ.get("DOMAIN_DNS_TIMEOUT_SECONDS", "3"))
DOMAIN_REVERIFY_SECONDS = int(os.environ.get("DOMAIN_REVERIFY_SECONDS", "3600"))
DOMAIN_TRANSIENT_GRACE_SECONDS = int(os.environ.get("DOMAIN_TRANSIENT_GRACE_SECONDS", "86400"))
DOMAIN_RELEASE_QUARANTINE_DAYS = int(os.environ.get("DOMAIN_RELEASE_QUARANTINE_DAYS", "7"))
DOMAIN_TLS_DECISION_CACHE_SECONDS = int(os.environ.get("DOMAIN_TLS_DECISION_CACHE_SECONDS", "10"))
DOMAIN_TLS_RATE_LIMIT_PER_MINUTE = int(os.environ.get("DOMAIN_TLS_RATE_LIMIT_PER_MINUTE", "30"))
PUBLIC_SITE_SCHEME = os.environ.get("PUBLIC_SITE_SCHEME", "https").strip().lower()
if (
    DOMAIN_DNS_TIMEOUT_SECONDS <= 0
    or DOMAIN_REVERIFY_SECONDS <= 0
    or DOMAIN_TRANSIENT_GRACE_SECONDS <= 0
    or DOMAIN_RELEASE_QUARANTINE_DAYS < 1
    or not 1 <= DOMAIN_TLS_DECISION_CACHE_SECONDS <= 60
    or DOMAIN_TLS_RATE_LIMIT_PER_MINUTE <= 0
    or PUBLIC_SITE_SCHEME not in {"http", "https"}
):
    raise ImproperlyConfigured("Konfiguracja domen i DNS jest nieprawidłowa")
#: How many articles one page of a blog index carries. A blog outgrows one page
#: quickly, and a single page listing a thousand entries is slow to render, slow
#: to read and crawled as one enormous document.
#: Whether autonomous publication is still confined to the deployment's own
#: publisher workspace. ADR-035 §4 asks for a documented pilot before it
#: reaches customer sites, and lifting a pilot should be a decision somebody
#: makes and records, not a code change and a deploy.
SITES_AUTONOMOUS_PILOT_ONLY = os.environ.get(
    "SITES_AUTONOMOUS_PILOT_ONLY", "true"
).strip().lower() not in {"0", "false", "no"}
SITES_ENTRY_INDEX_PAGE_SIZE = int(os.environ.get("SITES_ENTRY_INDEX_PAGE_SIZE", "10"))
if not 1 <= SITES_ENTRY_INDEX_PAGE_SIZE <= 100:
    raise ImproperlyConfigured("SITES_ENTRY_INDEX_PAGE_SIZE musi być z zakresu 1-100")
SITE_BLOCK_CONTRACTS_PATH = Path(
    os.environ.get(
        "SITE_BLOCK_CONTRACTS_PATH",
        BASE_DIR.parent.parent / "packages" / "contracts" / "site-blocks",
    )
)
PAGE_TEMPLATE_CONTRACTS_PATH = Path(
    os.environ.get(
        "PAGE_TEMPLATE_CONTRACTS_PATH",
        BASE_DIR.parent.parent / "packages" / "contracts" / "page-templates",
    )
)
CONTENT_OPERATIONS_CONTRACTS_PATH = Path(
    os.environ.get(
        "CONTENT_OPERATIONS_CONTRACTS_PATH",
        BASE_DIR.parent.parent / "packages" / "contracts" / "content-operations",
    )
)
#: How long an approval digest stands. Long enough for a person to look at the
#: diff and decide, short enough that an approval cannot be banked and spent
#: against a site that has moved on since.
CONTENT_APPROVAL_DIGEST_TTL = timedelta(
    minutes=int(os.environ.get("CONTENT_APPROVAL_DIGEST_TTL_MINUTES", "30"))
)


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
INTEGRATIONS_ENCRYPTION_KEY = secret_setting("INTEGRATIONS_ENCRYPTION_KEY")
MFA_ISSUER_NAME = os.environ.get("MFA_ISSUER_NAME", "SaaS Core")
MFA_CHALLENGE_TTL_SECONDS = int(os.environ.get("MFA_CHALLENGE_TTL_SECONDS", "300"))
if MFA_CHALLENGE_TTL_SECONDS <= 0:
    raise ImproperlyConfigured("Czas ważności wyzwania MFA musi być dodatni")
DEBUG = False
CONFIGURED_ALLOWED_HOSTS = tuple(
    host.strip().lower() for host in os.environ.get("ALLOWED_HOSTS", "").split(",") if host.strip()
)
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.postgres",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    *django_apps_for(ACTIVE_MODULES, _module_catalog),
]

#: Middleware a module brings with it, mounted only where that module is.
#: The API-key middleware belongs to Notifications and has nothing to answer in
#: a deployment without it; the tenant middleware is Core and is always there.
_MODULE_MIDDLEWARE = {
    "shared.notifications": (
        "saas_core.modules.shared.notifications.api_key_middleware."
        "ApiKeyTenantContextMiddleware"
    ),
}

MIDDLEWARE = [
    "saas_core.http.middleware.CorrelationIdMiddleware",
    "saas_core.http.hosts.DynamicHostValidationMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "saas_core.modules.core.identity.middleware.ManagedUserSessionMiddleware",
    *(
        middleware
        for module_id, middleware in _MODULE_MIDDLEWARE.items()
        if module_id in ACTIVE_MODULES
    ),
    "saas_core.modules.core.organizations.middleware.TenantContextMiddleware",
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

#: The connection every request uses. It cannot bypass row-level security, so
#: a query without a tenant answers with nothing rather than with somebody
#: else's rows.
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

#: The door from ADR-041. Same database, a different role, and policies that
#: name that role on exactly the tables which have to be read before a tenant
#: is known — logging in, the organization switcher, an invitation found by its
#: token, the Stripe processor identifying a customer, the background sweeps.
#: The role holds no BYPASSRLS: its reach is whatever the policies grant it and
#: nothing else, so adding a seventh table is a migration somebody has to write.
PRE_TENANT_DATABASE_ALIAS = "pre_tenant"
DATABASES[PRE_TENANT_DATABASE_ALIAS] = {
    **DATABASES["default"],
    "USER": os.environ.get("POSTGRES_IDENTITY_USER", "saas_core_identity"),
    "PASSWORD": secret_setting("POSTGRES_IDENTITY_PASSWORD", "saas_core"),
    # Django refuses to run tests against two aliases pointing at one database
    # unless the second is declared a mirror of the first.
    "TEST": {"MIRROR": "default"},
}
DATABASE_ROUTERS = ["saas_core.config.db_router.PreTenantRouter"]

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
OBJECT_STORAGE_ENDPOINT_URL = os.environ.get("OBJECT_STORAGE_ENDPOINT_URL", "")
OBJECT_STORAGE_PUBLIC_ENDPOINT_URL = os.environ.get("OBJECT_STORAGE_PUBLIC_ENDPOINT_URL", "")
OBJECT_STORAGE_BUCKET = os.environ.get("OBJECT_STORAGE_BUCKET", "")
OBJECT_STORAGE_REGION = os.environ.get("OBJECT_STORAGE_REGION", "us-east-1")
OBJECT_STORAGE_FORCE_PATH_STYLE = os.environ.get(
    "OBJECT_STORAGE_FORCE_PATH_STYLE", "false"
).lower() in {"1", "true", "yes"}
OBJECT_STORAGE_ACCESS_KEY_ID = secret_setting("OBJECT_STORAGE_ACCESS_KEY_ID")
OBJECT_STORAGE_SECRET_ACCESS_KEY = secret_setting("OBJECT_STORAGE_SECRET_ACCESS_KEY")
if bool(OBJECT_STORAGE_ACCESS_KEY_ID) != bool(OBJECT_STORAGE_SECRET_ACCESS_KEY):
    raise ImproperlyConfigured("Ustaw oba sekrety object storage albo żaden")
if OBJECT_STORAGE_ENDPOINT_URL and not (
    OBJECT_STORAGE_PUBLIC_ENDPOINT_URL
    and OBJECT_STORAGE_BUCKET
    and OBJECT_STORAGE_ACCESS_KEY_ID
    and OBJECT_STORAGE_SECRET_ACCESS_KEY
):
    raise ImproperlyConfigured("Lokalny object storage wymaga endpointu, bucketa i sekretów")
MEDIA_UPLOAD_URL_TTL_SECONDS = int(os.environ.get("MEDIA_UPLOAD_URL_TTL_SECONDS", "900"))
MEDIA_MAX_UPLOAD_BYTES = int(os.environ.get("MEDIA_MAX_UPLOAD_BYTES", str(10 * 1024**2)))
MEDIA_MAX_IMAGE_PIXELS = int(os.environ.get("MEDIA_MAX_IMAGE_PIXELS", "40000000"))
MEDIA_PROCESSING_RESERVATION_TTL_SECONDS = int(
    os.environ.get("MEDIA_PROCESSING_RESERVATION_TTL_SECONDS", "3600")
)
CLAMAV_HOST = os.environ.get("CLAMAV_HOST", "")
CLAMAV_PORT = int(os.environ.get("CLAMAV_PORT", "3310"))
CLAMAV_TIMEOUT_SECONDS = float(os.environ.get("CLAMAV_TIMEOUT_SECONDS", "30"))
if MEDIA_UPLOAD_URL_TTL_SECONDS <= 0 or MEDIA_UPLOAD_URL_TTL_SECONDS > 3600:
    raise ImproperlyConfigured("Czas ważności signed upload musi mieścić się w 1..3600 s")
if MEDIA_MAX_UPLOAD_BYTES <= 0 or MEDIA_MAX_IMAGE_PIXELS <= 0:
    raise ImproperlyConfigured("Limity uploadu i obrazu muszą być dodatnie")
if MEDIA_PROCESSING_RESERVATION_TTL_SECONDS <= 0:
    raise ImproperlyConfigured("Czas rezerwacji przetwarzania mediów musi być dodatni")
if not 1 <= CLAMAV_PORT <= 65535 or CLAMAV_TIMEOUT_SECONDS <= 0:
    raise ImproperlyConfigured("Konfiguracja połączenia ClamAV jest nieprawidłowa")
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
TENANT_TASK_CONTEXT_TTL_SECONDS = int(os.environ.get("TENANT_TASK_CONTEXT_TTL_SECONDS", "3888000"))
ORGANIZATION_INVITATION_TTL_SECONDS = int(
    os.environ.get("ORGANIZATION_INVITATION_TTL_SECONDS", "604800")
)
if SESSION_IDLE_TIMEOUT_SECONDS <= 0 or SESSION_MAX_LIFETIME_SECONDS <= 0:
    raise ImproperlyConfigured("Limity czasu sesji muszą być dodatnie")
if TENANT_TASK_CONTEXT_TTL_SECONDS <= 0:
    raise ImproperlyConfigured("Czas ważności tenant task context musi być dodatni")
if ORGANIZATION_INVITATION_TTL_SECONDS <= 0:
    raise ImproperlyConfigured("Czas ważności zaproszenia musi być dodatni")
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = True
CSRF_FAILURE_VIEW = "saas_core.http.csrf.csrf_failure"

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = secret_setting("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "false").lower() in {"1", "true", "yes"}
EMAIL_FILE_PATH = os.environ.get("EMAIL_FILE_PATH")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "SaaS Core <noreply@localhost>")
NOTIFICATIONS_EMAIL_PROVIDER = os.environ.get(
    "NOTIFICATIONS_EMAIL_PROVIDER",
    "saas_core.modules.shared.notifications.providers.DjangoEmailProvider",
)
NOTIFICATIONS_PROVIDER_WEBHOOK_SECRET = secret_setting("NOTIFICATIONS_PROVIDER_WEBHOOK_SECRET")
NOTIFICATIONS_WEBHOOK_TOLERANCE_SECONDS = int(
    os.environ.get("NOTIFICATIONS_WEBHOOK_TOLERANCE_SECONDS", "300")
)
NOTIFICATIONS_RETENTION_DAYS = int(os.environ.get("NOTIFICATIONS_RETENTION_DAYS", "30"))
NOTIFICATIONS_EXPORT_TTL_HOURS = int(os.environ.get("NOTIFICATIONS_EXPORT_TTL_HOURS", "24"))
NOTIFICATIONS_EXPORT_MAX_ROWS = int(os.environ.get("NOTIFICATIONS_EXPORT_MAX_ROWS", "10000"))
BOOKING_PUBLIC_RATE = os.environ.get("BOOKING_PUBLIC_RATE", "30/min")
BOOKING_SELF_SERVICE_TTL_DAYS = int(os.environ.get("BOOKING_SELF_SERVICE_TTL_DAYS", "30"))
BOOKING_SLOT_HORIZON_DAYS = int(os.environ.get("BOOKING_SLOT_HORIZON_DAYS", "62"))
BOOKING_REMINDER_LEAD_HOURS = int(os.environ.get("BOOKING_REMINDER_LEAD_HOURS", "24"))
if (
    NOTIFICATIONS_WEBHOOK_TOLERANCE_SECONDS <= 0
    or NOTIFICATIONS_RETENTION_DAYS <= 0
    or NOTIFICATIONS_EXPORT_TTL_HOURS <= 0
    or NOTIFICATIONS_EXPORT_MAX_ROWS <= 0
    or BOOKING_SELF_SERVICE_TTL_DAYS <= 0
    or not 1 <= BOOKING_SLOT_HORIZON_DAYS <= 62
    or BOOKING_REMINDER_LEAD_HOURS <= 0
):
    raise ImproperlyConfigured("Ustawienia notifications muszą być dodatnie")
if (
    max(
        NOTIFICATIONS_RETENTION_DAYS * 86400,
        NOTIFICATIONS_EXPORT_TTL_HOURS * 3600,
    )
    > TENANT_TASK_CONTEXT_TTL_SECONDS
):
    raise ImproperlyConfigured(
        "Tenant task context musi obejmować retencję notifications i eksportów"
    )
FRONTEND_BASE_URL = os.environ.get("FRONTEND_BASE_URL", "http://localhost:8080")
EMAIL_VERIFICATION_TTL_SECONDS = int(os.environ.get("EMAIL_VERIFICATION_TTL_SECONDS", "86400"))
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS = int(
    os.environ.get("EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS", "60")
)
PASSWORD_RESET_TTL_SECONDS = int(os.environ.get("PASSWORD_RESET_TTL_SECONDS", "3600"))
PASSWORD_RESET_RESEND_COOLDOWN_SECONDS = int(
    os.environ.get("PASSWORD_RESET_RESEND_COOLDOWN_SECONDS", "60")
)
STRIPE_SECRET_KEY = secret_setting("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = secret_setting("STRIPE_WEBHOOK_SECRET")
#: The one API version this deployment speaks — used for outgoing calls and
#: required of every incoming webhook, so a payload shaped by a version we have
#: not read cannot be parsed as if it were ours. Stripe sends events in the
#: version pinned on the webhook endpoint, or in the account default when the
#: endpoint pins none; `stripe listen` always uses the account default. So a
#: production endpoint must be created with this exact api_version, and moving
#: the account default forward means moving this line — the mismatch shows up
#: as every event refused with 400, which is loud but easy to misread.
STRIPE_API_VERSION = (
    os.environ.get("STRIPE_API_VERSION", "").strip() or "2026-08-26.dahlia"
)
#: Stripe's tax code for what we sell. "General - Electronically Supplied
#: Services" is the EU category a SaaS subscription falls into, and it taxes
#: the same way for business and private buyers.
STRIPE_TAX_CODE = os.environ.get("STRIPE_TAX_CODE", "txcd_10000000").strip()
STRIPE_LIVEMODE = os.environ.get("STRIPE_LIVEMODE", "false").lower() in {
    "1",
    "true",
    "yes",
}
BILLING_PROVIDER = _validate_billing_provider(
    os.environ.get("BILLING_PROVIDER", "stripe").strip().lower(),
    app_env=APP_ENV,
    stripe_livemode=STRIPE_LIVEMODE,
)
#: The portal configuration this deployment opens sessions against (ADR-040).
#: Pinned rather than left to the account default, because the default can be
#: changed in the Stripe dashboard without any code review noticing.
STRIPE_PORTAL_CONFIGURATION_ID = os.environ.get("STRIPE_PORTAL_CONFIGURATION_ID", "").strip()
if STRIPE_PORTAL_CONFIGURATION_ID and not STRIPE_PORTAL_CONFIGURATION_ID.startswith("bpc_"):
    raise ImproperlyConfigured("STRIPE_PORTAL_CONFIGURATION_ID musi zaczynać się od bpc_")
if BILLING_PROVIDER == "stripe" and APP_ENV != "test" and "shared.billing" in ACTIVE_MODULES:
    # ADR-034 asks for a start that refuses rather than a runtime that
    # discovers the gap at the first payment. Tests are exempt on purpose:
    # they run against the real provider name with empty credentials to prove
    # the services report the missing configuration instead of crashing. So is
    # a deployment without Billing: asking it for a payment provider's
    # credentials would be demanding keys to something it does not have.
    _missing_stripe = [
        name
        for name, value in (
            ("STRIPE_SECRET_KEY", STRIPE_SECRET_KEY),
            ("STRIPE_WEBHOOK_SECRET", STRIPE_WEBHOOK_SECRET),
            ("STRIPE_PORTAL_CONFIGURATION_ID", STRIPE_PORTAL_CONFIGURATION_ID),
        )
        if not value
    ]
    if _missing_stripe:
        raise ImproperlyConfigured(
            "BILLING_PROVIDER=stripe wymaga kompletnej konfiguracji; brakuje: "
            + ", ".join(_missing_stripe)
        )
STRIPE_WEBHOOK_TOLERANCE_SECONDS = int(os.environ.get("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "300"))
STRIPE_WEBHOOK_MAX_BYTES = int(os.environ.get("STRIPE_WEBHOOK_MAX_BYTES", "262144"))
if STRIPE_WEBHOOK_TOLERANCE_SECONDS <= 0 or STRIPE_WEBHOOK_MAX_BYTES <= 0:
    raise ImproperlyConfigured("Limity webhooka Stripe muszą być dodatnie")
BILLING_CHECKOUT_SUCCESS_URL = os.environ.get(
    "BILLING_CHECKOUT_SUCCESS_URL",
    f"{FRONTEND_BASE_URL.rstrip('/')}/settings/billing?checkout=success"
    "&session_id={CHECKOUT_SESSION_ID}",
)
BILLING_CHECKOUT_CANCEL_URL = os.environ.get(
    "BILLING_CHECKOUT_CANCEL_URL",
    f"{FRONTEND_BASE_URL.rstrip('/')}/settings/billing?checkout=canceled",
)
BILLING_CREDITS_CHECKOUT_SUCCESS_URL = os.environ.get(
    "BILLING_CREDITS_CHECKOUT_SUCCESS_URL",
    f"{FRONTEND_BASE_URL.rstrip('/')}/panel/settings/credits?checkout=success"
    "&session_id={CHECKOUT_SESSION_ID}",
)
BILLING_CREDITS_CHECKOUT_CANCEL_URL = os.environ.get(
    "BILLING_CREDITS_CHECKOUT_CANCEL_URL",
    f"{FRONTEND_BASE_URL.rstrip('/')}/panel/settings/credits?checkout=canceled",
)
BILLING_PORTAL_RETURN_URL = os.environ.get(
    "BILLING_PORTAL_RETURN_URL",
    f"{FRONTEND_BASE_URL.rstrip('/')}/settings/billing",
)
BILLING_LIFECYCLE_WARNING_LEAD_SECONDS = int(
    os.environ.get("BILLING_LIFECYCLE_WARNING_LEAD_SECONDS", "86400")
)
BILLING_LIFECYCLE_MAX_ATTEMPTS = int(os.environ.get("BILLING_LIFECYCLE_MAX_ATTEMPTS", "5"))
BILLING_RECONCILIATION_INTERVAL_SECONDS = int(
    os.environ.get("BILLING_RECONCILIATION_INTERVAL_SECONDS", "3600")
)
BILLING_RECONCILIATION_MAX_ATTEMPTS = int(
    os.environ.get("BILLING_RECONCILIATION_MAX_ATTEMPTS", "5")
)
BILLING_RECONCILIATION_BATCH_SIZE = int(os.environ.get("BILLING_RECONCILIATION_BATCH_SIZE", "100"))
BILLING_INVOICE_ADAPTER = os.environ.get(
    "BILLING_INVOICE_ADAPTER",
    "saas_core.modules.shared.billing.invoicing.InternalInvoiceAdapter",
)
if BILLING_LIFECYCLE_WARNING_LEAD_SECONDS <= 0 or BILLING_LIFECYCLE_MAX_ATTEMPTS <= 0:
    raise ImproperlyConfigured("Ustawienia lifecycle Billing muszą być dodatnie")
if (
    BILLING_RECONCILIATION_INTERVAL_SECONDS <= 0
    or BILLING_RECONCILIATION_MAX_ATTEMPTS <= 0
    or BILLING_RECONCILIATION_BATCH_SIZE <= 0
):
    raise ImproperlyConfigured("Ustawienia rekonsyliacji Billing muszą być dodatnie")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TASK_TRACK_STARTED = True
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
#: Scheduled work, grouped by the module whose code it calls. A deployment
#: without Sites must not run Sites' sweeps: the scheduler would enqueue jobs
#: against tables that are not there, once a minute, forever.
#: What kind of visit a service sells, contributed by the module that knows the
#: shape of that visit. Core has no business knowing what a herd visit is; it
#: only knows that a deployment which composes that module may offer one, and
#: that a key from a module this product does not have is a typo rather than a
#: feature. Same mechanism as the routes and the beat schedule below.
_MODULE_APPOINTMENT_KINDS: dict[str, dict[str, Any]] = {
    "vertical.hoofcare": {
        "hoofcare.herd_visit": "Korekcja stada w gospodarstwie",
    },
}

_MODULE_BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "shared.seo": {
        "seo-reconcile-audits": {
            "task": "saas_core.modules.shared.seo.tasks.reconcile_audits",
            "schedule": 30.0,
        }
    },
    "shared.sites": {
        "sites-verify-domains": {
            "task": "saas_core.modules.shared.sites.tasks.schedule_domain_verifications",
            "schedule": 60.0,
        },
        # Every minute, so "publish at 7:00" means 7:00 and not some time that
        # morning. The scan is indexed and returns nothing on a quiet site.
        "sites-publish-due-entries": {
            "task": "saas_core.modules.shared.sites.tasks.publish_due_entries",
            "schedule": 60.0,
        },
    },
    "shared.billing": {
        "billing-process-lifecycle": {
            "task": "saas_core.modules.shared.billing.tasks.process_billing_lifecycle",
            "schedule": 60.0,
        },
        "billing-reconcile-subscriptions": {
            "task": "saas_core.modules.shared.billing.tasks.reconcile_billing_subscriptions",
            "schedule": 300.0,
        },
        # The simulator's counterpart to reconciliation: without it a local
        # deployment never leaves the trial it started.
        "billing-advance-simulated": {
            "task": "saas_core.modules.shared.billing.tasks.advance_simulated_billing",
            "schedule": 300.0,
        },
        "billing-expire-overrides": {
            "task": "saas_core.modules.shared.billing.tasks.expire_billing_overrides",
            "schedule": 60.0,
        },
        "billing-release-expired-reservations": {
            "task": ("saas_core.modules.shared.billing.tasks.release_expired_quota_reservations"),
            "schedule": 60.0,
        },
        "billing-release-expired-credit-reservations": {
            "task": ("saas_core.modules.shared.billing.tasks.release_expired_credit_reservations"),
            "schedule": 60.0,
        },
        # Hourly, not at midnight: reading a balance grants the month's
        # allowance anyway, so the sweep only has to make the ledger tell a
        # truthful story for organizations nobody looked at.
        "billing-refresh-credit-allowances": {
            "task": "saas_core.modules.shared.billing.tasks.refresh_credit_allowances",
            "schedule": 3600.0,
        },
    },
    "shared.notifications": {
        # Billing records the warning; notifications is what makes it arrive.
        # It belongs to Notifications because that is the code it calls — a
        # deployment with Billing and no Notifications has nowhere to deliver.
        "notifications-deliver-billing-notices": {
            "task": "saas_core.modules.shared.notifications.tasks.deliver_billing_notices",
            "schedule": 60.0,
        },
        "notifications-recover-pending": {
            "task": "saas_core.modules.shared.notifications.tasks.recover_pending",
            "schedule": 60.0,
        },
    },
    "shared.media": {
        # ADR-042: an erased tenant's files are deleted after the rows commit,
        # so something has to finish the job and say when it is finished.
        "media-purge-erased-objects": {
            "task": "saas_core.modules.shared.media.tasks.purge_erased_objects",
            "schedule": 300.0,
        },
    },
    "shared.booking": {
        "booking-dispatch-reminders": {
            "task": "saas_core.modules.shared.booking.tasks.dispatch_booking_reminders",
            "schedule": 60.0,
        },
    },
}

try:
    CELERY_BEAT_SCHEDULE = select_by_module(
        _MODULE_BEAT_SCHEDULE, ACTIVE_MODULES, KNOWN_MODULES
    )
    #: {key: label} for the kinds this deployment actually composes.
    APPOINTMENT_KINDS = select_by_module(
        _MODULE_APPOINTMENT_KINDS, ACTIVE_MODULES, KNOWN_MODULES
    )
except CompositionError as error:
    raise ImproperlyConfigured(str(error)) from error

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
        "booking_public": BOOKING_PUBLIC_RATE,
        "sites_subdomain_availability": "30/min",
    },
}
SPECTACULAR_SETTINGS = {
    "TITLE": "SaaS Core API",
    "DESCRIPTION": "Wersjonowane API modularnej platformy SaaS Core.",
    "VERSION": "1.0.0",
    "OAS_VERSION": "3.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "ENUM_NAME_OVERRIDES": {
        "LocaleEnum": ["pl", "en"],
    },
}

APPLICATION_VERSION = os.environ.get("APPLICATION_VERSION", "0.1.0")
HEALTH_CHECK_DEPENDENCIES = True

# One explicitly configured SSA service source per deployment.
SEO_SSA_BASE_URL = os.environ.get("SEO_SSA_BASE_URL", "")
SEO_SSA_SOURCE_ID = os.environ.get("SEO_SSA_SOURCE_ID", "")
SEO_SSA_PRODUCT_ID = os.environ.get("SEO_SSA_PRODUCT_ID", "")
SEO_SSA_DEPLOYMENT_ID = os.environ.get("SEO_SSA_DEPLOYMENT_ID", "")
SEO_SSA_SERVICE_KEY = secret_setting("SEO_SSA_SERVICE_KEY")
SEO_SSA_CALLBACK_SECRET = secret_setting("SEO_SSA_CALLBACK_SECRET")
SEO_AUDIT_CREDIT_OPERATION = os.environ.get("SEO_AUDIT_CREDIT_OPERATION", "")
SEO_AUDIT_MAX_PAGES = int(os.environ.get("SEO_AUDIT_MAX_PAGES", "100"))
SEO_REPORT_MAX_ISSUES = int(os.environ.get("SEO_REPORT_MAX_ISSUES", "5000"))
SEO_GSC_REDIRECT_URI = os.environ.get("SEO_GSC_REDIRECT_URI", "")
