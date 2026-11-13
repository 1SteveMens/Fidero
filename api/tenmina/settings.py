"""Django settings for the Tenmina API (document 02, ADR-01).

Every value that differs between environments comes from an environment
variable. Defaults are for local development and tests only.
"""
import ctypes.util
import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    v = os.environ.get(name)
    return default if v is None else v.lower() in ("1", "true", "yes")


SECRET_KEY = env("TENMINA_SECRET_KEY", "dev-only-not-a-secret-change-me-in-every-real-environment")
DEBUG = env_bool("TENMINA_DEBUG", True)
ALLOWED_HOSTS = env("TENMINA_ALLOWED_HOSTS", "*").split(",")
ENVIRONMENT = env("TENMINA_ENV", "dev")  # dev | test | staging | prod

GDAL_LIBRARY_PATH = env("GDAL_LIBRARY_PATH") or ctypes.util.find_library("gdal") or "/usr/lib/x86_64-linux-gnu/libgdal.so.34"
GEOS_LIBRARY_PATH = env("GEOS_LIBRARY_PATH") or ctypes.util.find_library("geos_c") or "/usr/lib/x86_64-linux-gnu/libgeos_c.so.1"

# One Django app per SRS module (document 02, section 4.2). Order matters only
# for readability; dependencies are declared in migrations.
TENMINA_MODULES = [
    "core",          # shared kernel: ids, money, outbox, idempotency, approvals, transitions
    "audit",         # AUD
    "countries",     # CTY
    "accounts",      # ACC
    "administration",  # ADM
    "notifications",   # NTF
    "evidence",        # EVD
    "dataprotection",  # DPR
    "orders",          # ORD
    "payments",        # PAY
    "geo",             # GEO
    "cases",           # CASE
    "reports",         # RPT
    "escrow",          # ESC
    "fees",            # FEE
    "mobile",          # MOB
    "construction",    # BLD
    "projectfunds",    # PRJ
    "listings",        # LST
    "ratings",         # RAT
    "disputes",        # DSP
    "partners",        # PTR
    "analytics",       # ANL
    "care",            # CARE
    "propertymgmt",    # PMG
    "errands",         # TSK
    "insurance",       # INS
    "events",          # EVT
    "records",         # REC
    "profpay",         # PRO
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    *TENMINA_MODULES,
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "core.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # FR-APP-006: 426 for an app below the minimum version (Tenmina-App header); evidence paths apply the
    # 30-day grace in their views.
    "mobile.appversion.AppVersionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.TraceMiddleware",
]

ROOT_URLCONF = "tenmina.urls"
WSGI_APPLICATION = "tenmina.wsgi.application"

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
            ]
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": env("TENMINA_DB_NAME", "tenmina"),
        "USER": env("TENMINA_DB_USER", "tenmina"),
        "PASSWORD": env("TENMINA_DB_PASSWORD", "tenmina"),
        "HOST": env("TENMINA_DB_HOST", "localhost"),
        "PORT": env("TENMINA_DB_PORT", "5432"),
        "ATOMIC_REQUESTS": True,
        # Parallel test runs (one per module) use their own database.
        "TEST": {"NAME": env("TEST_DB_NAME", "test_tenmina")},
    }
}

AUTH_USER_MODEL = "accounts.Person"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
PASSWORD_HASHERS = (
    ["django.contrib.auth.hashers.MD5PasswordHasher"]
    if env("TENMINA_FAST_HASHER") == "1"
    else ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]
)

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_ROOT = Path(env("TENMINA_MEDIA_ROOT", str(BASE_DIR / "var")))
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.auth.BearerTokenAuthentication",
        "accounts.auth.CsrfSessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.CursorPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "EXCEPTION_HANDLER": "core.errors.problem_exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Tenmina API",
    "DESCRIPTION": "One API for the portal, back office and the two apps (document 02, section 7).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "OAS_VERSION": "3.1.0",
}

SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_TRUSTED_ORIGINS = env("TENMINA_CSRF_ORIGINS", "http://localhost:3000,http://localhost:3001").split(",")
CORS_ALLOWED_ORIGINS = env("TENMINA_CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:8081").split(",")

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", True)
CELERY_TIMEZONE = "UTC"
# Every periodic job (02 section 7.12). Run one by hand: python manage.py run_jobs <name>.
from .celery_schedule import CELERY_BEAT_SCHEDULE  # noqa: E402

TENMINA = {
    # How outbox events reach their consumers: "immediate" (same transaction,
    # dev and tests), "on_commit" or "celery" (production relay, ADR-08).
    "EVENT_DISPATCH": env("TENMINA_EVENT_DISPATCH", "immediate"),
    # Step-up MFA freshness for approvals (6.3, assumption).
    "MFA_FRESHNESS": timedelta(minutes=5),
    "ACCESS_TOKEN_TTL": timedelta(minutes=15),
    "REFRESH_TOKEN_TTL": timedelta(days=30),
    # Integration adapters (ADR-10). Every port has a "fake" adapter that
    # behaves like the manual path. Real adapters replace these one by one.
    "ADAPTERS": {
        "payments": env("TENMINA_ADAPTER_PAYMENTS", "payments.adapters.FakePaymentProvider"),
        "national_id": env("TENMINA_ADAPTER_NATIONAL_ID", "accounts.adapters.FakeNationalIdProvider"),
        "bank_name_check": env("TENMINA_ADAPTER_BANK_NAME", "escrow.adapters.FakeBankNameCheck"),
        "bank_instructions": env("TENMINA_ADAPTER_BANK", "escrow.adapters.ManualBankInstructions"),
        "fx_rates": env("TENMINA_ADAPTER_FX", "escrow.adapters.FakeRateSource"),
        "messaging": env("TENMINA_ADAPTER_MESSAGING", "notifications.adapters.ConsoleMessaging"),
        "push": env("TENMINA_ADAPTER_PUSH", "notifications.adapters.ConsolePush"),
        "evidence_store": env("TENMINA_ADAPTER_EVIDENCE", "evidence.adapters.LocalWriteOnceStore"),
        "malware_scan": env("TENMINA_ADAPTER_SCAN", "evidence.adapters.NoopScanner"),
        "registry_search": env("TENMINA_ADAPTER_REGISTRY", "cases.adapters.ManualRegistrySearch"),
        "satellite": env("TENMINA_ADAPTER_SATELLITE", "geo.adapters.FakeSatellite"),
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("TENMINA_LOG_LEVEL", "INFO")},
}
