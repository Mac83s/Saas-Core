import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

from saas_core.config.composition import (
    CompositionError,
    appointment_kinds_for,
    beat_schedule_for,
    completed_explicitly_kinds_for,
    compose,
    django_apps_for,
    load_catalog,
    middleware_for,
    organization_types_from,
    others_permission_for,
    own_material_kinds_for,
    role_grants_for,
    select_by_module,
    verify_artifact,
)
from saas_core.config.locales import (
    LocaleRegistryError,
    load_locale_registry,
    profile_locales_problem,
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
    # Od 1 do 6: produkt sprzedaje tyle planów, ile ma typów organizacji razy
    # ich warianty — gospodarstwo dostaje darmowy i płatny obok planów firmy.
    if not 1 <= len(plan_keys) <= 6 or len(plan_keys) != len(set(plan_keys)):
        raise ImproperlyConfigured(
            "Profil z shared.billing wymaga od 1 do 6 unikalnych billing.planKeys"
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
#: The content languages the platform knows (ADR-071 pkt 2), from the same file
#: the Node deployment check reads, so CI and boot agree on what a code is.
LOCALE_REGISTRY_PATH = Path(
    os.environ.get(
        "LOCALE_REGISTRY_PATH",
        BASE_DIR.parent.parent / "packages" / "contracts" / "locales" / "registry.json",
    )
)
try:
    LOCALE_REGISTRY = load_locale_registry(LOCALE_REGISTRY_PATH)
except LocaleRegistryError as error:
    raise ImproperlyConfigured(str(error)) from error
#: The languages of the panel and of e-mails to the team (ADR-071 pkt 1).
APP_LOCALES = tuple(code for code, entry in LOCALE_REGISTRY.items() if entry.app_locale)
_locales_problem = profile_locales_problem(
    _deployment_supported_locales, _deployment_default_locale, LOCALE_REGISTRY
)
if _locales_problem is not None:
    raise ImproperlyConfigured(f"Profil deploymentu {DEPLOYMENT}: {_locales_problem}")
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
#: The descriptors themselves, for code that composes by module: routing reads
#: a vertical's `urlPrefix` from here instead of naming the vertical.
MODULE_CATALOG = _module_catalog
#: What the composed modules add to the system roles (ADR-049). Core owns the
#: roles; a product's module owns what its own permissions grant.
MODULE_ROLE_GRANTS = role_grants_for(ACTIVE_MODULES, _module_catalog)

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
    _module_artifact = json.loads(MODULE_ARTIFACT_PATH.read_text(encoding="utf-8"))
    PROFILE_HASH = verify_artifact(
        _module_artifact,
        deployment=DEPLOYMENT,
        modules=ACTIVE_MODULES,
        catalog=_module_catalog,
    )
    #: The kinds of organization this product has (ADR-050), keyed; the first
    #: one is the default. Each decides which shared and vertical modules its
    #: organizations may use and which plans they are offered.
    ORGANIZATION_TYPES = {
        organization_type.key: organization_type
        for organization_type in organization_types_from(_module_artifact, ACTIVE_MODULES)
    }
    DEFAULT_ORGANIZATION_TYPE = next(iter(ORGANIZATION_TYPES))
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
#: Whether the profile offers the company a removal of its booking customers'
#: data after a time (D1, 37a). Off where a visit hangs on another record of
#: the same person (a farm's card): stripping the customer alone would leave
#: them named there.
CUSTOMER_RETENTION_OFFERED = bool(_deployment_features.get("customerRetention", False))
#: The operator's pause for the nightly removal run. The run cannot be undone,
#: so it can be stopped from the environment without a release: the task reads
#: this each time, the schedule entry stays. The command run by hand ignores it.
PRIVACY_RETENTION_SCHEDULE_ENABLED = os.environ.get(
    "PRIVACY_RETENTION_SCHEDULE_ENABLED", "true"
).strip().lower() in {"1", "true", "yes"}
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


def local_transport_security(public_site_scheme: str, hsts_seconds: int) -> dict[str, object]:
    """What a stack named `local` does about https.

    The name says how it was started, not how it is reached: the dev VPS runs
    as `local` behind https and hands out real session cookies. So the cookie
    flags and HSTS follow the scheme the stack is served over, and only the
    redirect follows the name — the internal http hops (health checks, the
    frontend's server-side calls, metrics) cannot take one."""
    over_https = public_site_scheme == "https"
    return {
        "SECURE_SSL_REDIRECT": False,
        "SECURE_HSTS_SECONDS": hsts_seconds if over_https else 0,
        # Never includeSubDomains here: customers' own domains reach the same
        # backend, and the header would forbid plain http on subdomains of
        # theirs that the platform neither serves nor knows.
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
        "SESSION_COOKIE_SECURE": over_https,
        "CSRF_COOKIE_SECURE": over_https,
    }


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
#: Whether the public renderer counts page views (ADR-060). A number with no
#: visitor behind it, so on by default; the switch is for the day somebody has
#: to stop counting without a release.
SITES_PAGE_VIEW_COUNTER_ENABLED = os.environ.get(
    "SITES_PAGE_VIEW_COUNTER_ENABLED", "true"
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
#: ADR-053 §7: the closed city and category dictionary the public catalogue
#: filters and addresses by. Read from disk at first use, so it needs the same
#: image-plus-system-check treatment as the other contracts.
CATALOG_CONTRACTS_PATH = Path(
    os.environ.get(
        "CATALOG_CONTRACTS_PATH",
        BASE_DIR.parent.parent / "packages" / "contracts" / "catalog",
    )
)
#: ADR-072 §10: the booking presets a company starts an offer from — data, not
#: code. Read from disk at first use, so the image carries a copy and a system
#: check answers for the path (the default in the image needs no `.env` line).
BOOKING_PRESET_CONTRACTS_PATH = Path(
    os.environ.get(
        "BOOKING_PRESET_CONTRACTS_PATH",
        BASE_DIR.parent.parent / "packages" / "contracts" / "booking-presets",
    )
)
#: How long an approval digest stands. Long enough for a person to look at the
#: diff and decide, short enough that an approval cannot be banked and spent
#: against a site that has moved on since.
CONTENT_APPROVAL_DIGEST_TTL = timedelta(
    minutes=int(os.environ.get("CONTENT_APPROVAL_DIGEST_TTL_MINUTES", "30"))
)
#: How long, in seconds, a person's click lets the assistant run what it showed
#: (ADR-076 §3): enough to run the plan right after the click, too short to keep
#: a consent for later. A security time, not a platform setting.
COMMAND_CONSENT_TTL = 300
#: How long a plan shown for consent waits for its click, in seconds; after
#: that the assistant proposes it again on the state of that moment.
COMMAND_PENDING_TTL = 1800
#: How long a confirmed second factor stands for legal documents and billing,
#: in seconds (owner answer 31b). A security time, not a platform setting.
STEP_UP_MAX_AGE = 300
#: Wrong second-factor codes an account may give — at sign-in, when turning
#: MFA on and on a step-up together — before no code is taken for
#: `MFA_LOCK_SECONDS` (ADR-023; platform settings plan 0c). The per-address
#: throttle alone let guesses be spread over addresses. A protective limit.
MFA_FAILURE_LIMIT = 5
MFA_LOCK_SECONDS = 15 * 60


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
    # Django admin with a site that accepts only an MFA-checked panel session.
    "saas_core.config.admin_apps.MfaAdminConfig",
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
        "saas_core.modules.shared.notifications.api_key_middleware.ApiKeyTenantContextMiddleware"
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
    # ADR-050: the organization's type decides which modules it may call.
    "saas_core.config.module_gate.ModuleGateMiddleware",
    # A product's vertical declares its own in the descriptor (ADR-049). After
    # the tenant middleware: it sees the resolved tenant and cannot choose one.
    *middleware_for(ACTIVE_MODULES, _module_catalog),
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
DATABASE_ROUTERS = [
    "saas_core.config.db_router.ModelPortRouter",
    "saas_core.config.db_router.PreTenantRouter",
]

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
# ADR-072 §5 (T7): the widest one query of a stay calendar may span — a
# protective bound of the query, not the offer's booking window (its rules).
BOOKING_PERIOD_HORIZON_DAYS = int(os.environ.get("BOOKING_PERIOD_HORIZON_DAYS", "548"))
BOOKING_REMINDER_LEAD_HOURS = int(os.environ.get("BOOKING_REMINDER_LEAD_HOURS", "24"))
if (
    NOTIFICATIONS_WEBHOOK_TOLERANCE_SECONDS <= 0
    or NOTIFICATIONS_RETENTION_DAYS <= 0
    or NOTIFICATIONS_EXPORT_TTL_HOURS <= 0
    or NOTIFICATIONS_EXPORT_MAX_ROWS <= 0
    or BOOKING_SELF_SERVICE_TTL_DAYS <= 0
    or not 1 <= BOOKING_SLOT_HORIZON_DAYS <= 62
    or not 1 <= BOOKING_PERIOD_HORIZON_DAYS <= 731
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
STRIPE_API_VERSION = os.environ.get("STRIPE_API_VERSION", "").strip() or "2026-08-26.dahlia"
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
_MODULE_BEAT_SCHEDULE: dict[str, dict[str, Any]] = {
    "core.organizations": {
        # Once a night, 02:30 UTC: what the companies' own retention settings
        # ask for (D1–D2). By the clock, not every 24 hours — the scheduler's
        # timer starts over with each release, and a daily release would push
        # an interval ahead of itself for ever.
        "privacy-retention-run": {
            "task": "saas_core.modules.core.organizations.tasks.run_privacy_retention",
            "schedule": crontab(hour=2, minute=30),
        }
    },
    "shared.inventory": {
        # Hourly: each company hears once a day, from the hour of its own day it
        # chose (`inventory.alerts.hour`); off unless it switched the notice on.
        "inventory-notify-low-stock": {
            "task": "saas_core.modules.shared.inventory.tasks.notify_low_stock",
            "schedule": 3600.0,
        }
    },
    "shared.farms": {
        "farms-notify-pending-reviews": {
            "task": "saas_core.modules.shared.farms.tasks.notify_pending_reviews",
            "schedule": 86400.0,
        }
    },
    "shared.seo": {
        "seo-reconcile-audits": {
            "task": "saas_core.modules.shared.seo.tasks.reconcile_audits",
            "schedule": 30.0,
        }
    },
    "shared.profiles": {
        # ADR-064: the search index catches up with the catalogue table after
        # an engine outage or a lost task. Nothing to do when both agree.
        "profiles-reconcile-catalog-search": {
            "task": "saas_core.modules.shared.profiles.tasks.reconcile_catalog_search",
            "schedule": 600.0,
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
        # Retention is a system job per company, not a task tied to the
        # contract of whoever sent the message (found 03.10: such messages
        # stayed unscrubbed once their member left).
        "notifications-scrub-expired": {
            "task": "saas_core.modules.shared.notifications.tasks.scrub_expired",
            "schedule": 3600.0,
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
        # A request nobody answered in its time lets its time go (ADR-072 §9).
        "booking-expire-requests": {
            "task": "saas_core.modules.shared.booking.tasks.expire_pending_requests",
            "schedule": 60.0,
        },
    },
}

try:
    CELERY_BEAT_SCHEDULE = select_by_module(_MODULE_BEAT_SCHEDULE, ACTIVE_MODULES, KNOWN_MODULES)
    # A product's vertical declares its scheduled work in the descriptor.
    _declared_schedule = beat_schedule_for(ACTIVE_MODULES, _module_catalog)
    if clash := sorted(set(_declared_schedule) & set(CELERY_BEAT_SCHEDULE)):
        raise CompositionError(f"Zadania o tej samej nazwie co w rdzeniu: {', '.join(clash)}")
    CELERY_BEAT_SCHEDULE |= _declared_schedule
    #: {key: label} of the visit kinds this deployment composes. A module that
    #: knows the shape of a visit declares it in its descriptor; core only
    #: knows that a key from a module this product lacks is a typo.
    APPOINTMENT_KINDS = appointment_kinds_for(ACTIVE_MODULES, _module_catalog)
    #: Visits whose materials their module takes itself (HoofCare: per cow from
    #: the trimmer's own stock). Booking offers no products for them and does
    #: not settle any at completion, or the same material would go twice.
    APPOINTMENT_KINDS_OWN_MATERIALS = own_material_kinds_for(ACTIVE_MODULES, _module_catalog)
    #: Visits their module closes itself (HoofCare: when the field work ends).
    #: Their time passing is not their taking place, so only a completed one
    #: counts as done (UX-031).
    APPOINTMENT_KINDS_COMPLETED_EXPLICITLY = completed_explicitly_kinds_for(
        ACTIVE_MODULES, _module_catalog
    )
    #: Whose visits a person sees (UX-023): None — everyone's, as a small team
    #: plans together; a product's permission — without it, only one's own
    #: (MedPlano: a doctor does not see another doctor's patients).
    BOOKING_OTHERS_PERMISSION = others_permission_for(ACTIVE_MODULES, _module_catalog)
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
        "billing_public_catalog": "60/min",
        # The public catalogue searches as the visitor types (ADR-064).
        "catalog_search": "120/min",
        "identity_login": "5/min",
        "identity_mfa_challenge": "10/min",
        "identity_mfa_enrollment": "10/min",
        "identity_step_up": "10/min",
        "identity_password_reset_request": "5/min",
        "identity_password_reset_confirm": "10/min",
        "identity_register": "5/min",
        "identity_verification_resend": "5/min",
        "identity_verification_confirm": "10/min",
        "booking_public": BOOKING_PUBLIC_RATE,
        # A company's document at its public address (ADR-073 §9).
        "customers_public_document": "60/min",
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
        "StockDocumentKindEnum": "saas_core.modules.shared.inventory.models.DocumentKind",
        "CustomerDocumentKindEnum": "saas_core.modules.shared.customers.models.DocumentKind",
        # A second `state` enum (image jobs) must not rename the SEO one.
        "StateEnum": "saas_core.modules.shared.seo.models.AuditOrderState",
        "ImageGenerationJobStateEnum": "saas_core.modules.shared.image_generation.models.JobState",
        "ImageGenerationAspectEnum": ["16:9", "4:3", "3:2"],
        # One name for a lot's expiry state, on a balance and on a lot.
        "LotStatusEnum": "saas_core.modules.shared.inventory.serializers.LOT_STATUS",
        # A setting's type and unit, in the shape of the settings registry (ADR-078);
        # its `unit` and `type` must not rename the warehouse's unit and the SEO
        # callback's type.
        "UnitEnum": "saas_core.modules.shared.inventory.models.ItemUnit",
        "TypeEnum": ["module_run.finished"],
        "SettingTypeEnum": "saas_core.modules.core.organizations.options.SETTING_TYPES",
        "SettingUnitEnum": "saas_core.modules.core.organizations.options.SETTING_UNITS",
        # The translation mode must not rename the warehouse document's mode.
        "ModeEnum": ["consume", "sale"],
        "TranslationModeEnum": ["automatic", "review"],
        "SettingSourceEnum": "saas_core.modules.core.organizations.settings_registry.SOURCES",
        "SettingStrategyEnum": "saas_core.modules.core.organizations.options.SETTING_STRATEGIES",
        # A warehouse setting named `source` and a low-stock row's `location_kind`
        # must not rename the time-off source and the stock location's kind.
        "SourceEnum": "saas_core.modules.shared.booking.models.TimeOffSource",
        # A price's basis must not rename a translation target's basis, and how
        # a price list's amounts are read is one enum on the list and the setting.
        "BasisEnum": ["published", "working"],
        "PriceBasisEnum": "saas_core.modules.shared.booking.models.PriceBasis",
        "PriceAmountsEnum": ["gross", "net"],
        "QuoteLineKindEnum": ["price", "extra_person", "category", "discount", "extra"],
        # An extra's basis and kind must not rename a price's basis and other kinds.
        "ExtraBasisEnum": "saas_core.modules.shared.booking.models.ExtraBasis",
        "ExtraKindEnum": "saas_core.modules.shared.booking.models.ExtraKind",
        # An assistant turn's state must not get a hashed name. As values, not
        # an import path: a product that leaves the module out never loads it.
        "AssistantTurnStateEnum": [
            ("queued", "Queued"),
            ("running", "Running"),
            ("awaiting_consent", "Awaiting consent"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        "AssistantConversationKindEnum": [("operate", "Operate"), ("setup", "Setup")],
        "StockLocationKindEnum": "saas_core.modules.shared.inventory.models.LocationKind",
        # An order's status, channel, line kind and tax rate get their own names,
        # and its channel must not rename the history's. As values: a product
        # may leave commerce out.
        "ChannelEnum": ["panel", "api_key", "system"],
        "OrderTaxRateEnum": ["23", "8", "5", "0", "zw", "np"],
        "OrderConsentKindEnum": ["document", "marketing", "field"],
        "OrderPaymentKindEnum": ["deposit", "balance", "full", "security_deposit"],
        "OrderPaymentMethodEnum": ["online", "transfer", "cash", "cash_on_delivery"],
        "OrderPaymentStatusEnum": [
            "requires_payment",
            "processing",
            "authorized",
            "succeeded",
            "failed",
            "canceled",
            "expired",
        ],
        "ManualPaymentMethodEnum": ["cash", "transfer"],
        "OrderStatusEnum": [
            "draft",
            "awaiting_payment",
            "partially_paid",
            "paid",
            "fulfilled",
            "completed",
            "canceled",
            "refunded",
        ],
        "OrderChannelEnum": ["company_site", "catalog", "office"],
        "OrderLineKindEnum": [
            "booking",
            "product",
            "extra",
            "discount",
            "voucher",
            "delivery",
            "fee",
        ],
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

# ADR-064: the public catalogue's search engine (Meilisearch). No URL means no
# engine, and the catalogue searches PostgreSQL as it did before one existed —
# the same thing that happens while a configured engine does not answer.
SEARCH_URL = os.environ.get("SEARCH_URL", "")
SEARCH_API_KEY = secret_setting("SEARCH_API_KEY")
SEARCH_TIMEOUT_SECONDS = float(os.environ.get("SEARCH_TIMEOUT_SECONDS", "1.5"))
# ADR-064 §8: vectors for meaning-based search, computed by the backend.
# OpenRouter by default (owner's answer of 29.09); an empty key means words only.
CATALOG_EMBEDDING_API_KEY = secret_setting("CATALOG_EMBEDDING_API_KEY")
CATALOG_EMBEDDING_BASE_URL = os.environ.get(
    "CATALOG_EMBEDDING_BASE_URL", "https://openrouter.ai/api/v1"
)
CATALOG_EMBEDDING_MODEL = os.environ.get("CATALOG_EMBEDDING_MODEL", "qwen/qwen3-embedding-8b")
CATALOG_EMBEDDING_DIMENSIONS = int(os.environ.get("CATALOG_EMBEDDING_DIMENSIONS", "1024"))
#: Below this engine score a meaning-based match is not shown at all. The
#: engine scores (1 + cosine) / 2, so unrelated vectors sit near 0.5 and a
#: document without a vector at 0; provisional until tuned on real vectors.
CATALOG_SIMILAR_MIN_SCORE = float(os.environ.get("CATALOG_SIMILAR_MIN_SCORE", "0.75"))

# ADR-068: the model port. One OpenRouter key per deployment, mounted only in
# backend and worker-ai; an empty key means the tasks are unavailable. Reading
# it where it is not mounted is a program error, told apart from "not set".
MODEL_PORT_OPENROUTER_API_KEY = secret_setting("MODEL_PORT_OPENROUTER_API_KEY")
MODEL_PORT_OPENROUTER_API_KEY_MOUNTED = (
    "MODEL_PORT_OPENROUTER_API_KEY" in os.environ
    or "MODEL_PORT_OPENROUTER_API_KEY_FILE" in os.environ
)
MODEL_PORT_OPENROUTER_BASE_URL = os.environ.get(
    "MODEL_PORT_OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
)
#: OpenRouter is listed as a processor in the privacy policy and the data
#: processing agreement. Off until the operator says so through `memex ops`;
#: the platform workspace and evals do not need it (ADR-068 pkt 9).
MODEL_PORT_PROCESSOR_LISTED = os.environ.get(
    "MODEL_PORT_PROCESSOR_LISTED", "false"
).strip().lower() in {"1", "true", "yes"}
#: The stand-in translator of browser tests (`model_port.test_double`): on only
#: where an e2e or CI environment says so by name. Never derived from APP_ENV —
#: the dev VPS runs as `local` too.
MODEL_PORT_TEST_DOUBLE = os.environ.get("MODEL_PORT_TEST_DOUBLE", "false").strip().lower() in {
    "1",
    "true",
    "yes",
}
MODEL_PORT_WEB_CALLS_PER_PROCESS = int(os.environ.get("MODEL_PORT_WEB_CALLS_PER_PROCESS", "1"))
#: Accounts whose conversations with the assistant are proofs (browser
#: walk-throughs of a local stack), by e-mail, comma-separated. Their model
#: calls are counted with the evals — against the monthly ceilings only, in no
#: person's or company's day — so a proof never uses up the ceiling of the
#: account a person looks around with. Empty by default; a stack served over
#: https that names one does not start (`assistant.E001`).
ASSISTANT_PROOF_ACCOUNTS = tuple(
    sorted({
        account.strip().lower()
        for account in os.environ.get("ASSISTANT_PROOF_ACCOUNTS", "").split(",")
        if account.strip()
    })
)
#: The deployment's values of two translation engine keys (TL22): below an
#: operator's value in the „Platforma” panel, above the code's default
#: (`platform_env` of `translation.engine.*`).
TRANSLATION_MASS_PUBLICATION_CAP = int(os.environ.get("TRANSLATION_MASS_PUBLICATION_CAP", "20"))
TRANSLATION_PLATFORM_CONFIRM_USD = int(
    float(os.environ.get("TRANSLATION_PLATFORM_CONFIRM_USD", "5"))
)
if not 1 <= TRANSLATION_MASS_PUBLICATION_CAP <= 1000:
    raise ImproperlyConfigured("TRANSLATION_MASS_PUBLICATION_CAP musi być z zakresu 1–1000.")
if not 0 <= TRANSLATION_PLATFORM_CONFIRM_USD <= 1000:
    raise ImproperlyConfigured("TRANSLATION_PLATFORM_CONFIRM_USD musi być z zakresu 0–1000.")
#: The CMD of the backend image reads the same variable, so a call made from a
#: request is cut to what a graceful restart waits for.
GUNICORN_GRACEFUL_TIMEOUT = float(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "20"))
#: The product's starting values for settings (ADR-078 pkt 14): key → value.
#: A starting value, never a ceiling; each module checks its own keys at start.
SETTINGS_DEFAULTS: dict[str, Any] = dict(_deployment_profile.get("settingsDefaults") or {})
#: The profile's `ai.sendableDataClasses`: what may reach a model at all.
MODEL_PORT_SENDABLE_DATA_CLASSES = tuple(
    (_deployment_profile.get("ai") or {}).get("sendableDataClasses")
    or ("public", "public_personal")
)
#: The port's own connection: the same database and role, so a reservation is
#: visible to other processes at once and a telemetry row survives the rollback
#: of the request that paid for the call.
MODEL_PORT_DATABASE_ALIAS = "model_port"
DATABASES[MODEL_PORT_DATABASE_ALIAS] = {
    **DATABASES["default"],
    "TEST": {"MIRROR": "default"},
}

# ADR-059: the direct OpenAI Image API. An empty key means the feature is
# unavailable, not misconfigured, so there is no system check for it.
IMAGE_GENERATION_OPENAI_API_KEY = secret_setting("IMAGE_GENERATION_OPENAI_API_KEY")
IMAGE_GENERATION_BASE_URL = os.environ.get("IMAGE_GENERATION_BASE_URL", "https://api.openai.com/v1")
IMAGE_GENERATION_MODEL = os.environ.get("IMAGE_GENERATION_MODEL", "gpt-image-2.5-flare-2026-09-08")
IMAGE_GENERATION_TEMPLATE_MODEL = os.environ.get(
    "IMAGE_GENERATION_TEMPLATE_MODEL", "gpt-image-2.5-sunburst-2026-09-08"
)
