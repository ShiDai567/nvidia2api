import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# The race engine performs short, serialized SQLite writes from an asyncio
# (single-thread) event loop. DB calls are brief and safe here.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-secret-change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "corsheaders",
    "rest_framework",
    "apps.core",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DATABASE_PATH", str(DATA_DIR / "db.sqlite3")),
        # Serialize writers & allow lock waits: protects per-key RPM counters under concurrency.
        "OPTIONS": {"timeout": 30},
        "TEST": {"NAME": str(DATA_DIR / "test_db.sqlite3")},
    }
}
TEMPLATES = []
USE_TZ = True
LANGUAGE_CODE = "en-us"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
}

# CORS: the console talks to the backend same-origin via Next.js rewrites in
# production, so CORS is only needed for local dev (Next :3000 -> Django :8000)
# or explicit API-base deployments. Restrictable via CORS_ALLOWED_ORIGINS.
_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
if _cors_origins:
    CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False
else:
    CORS_ALLOW_ALL_ORIGINS = True  # default deployment: single admin console, no cookies

# --- nvidia2api settings ---
NVIDIA_BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
DEFAULT_NVIDIA_RPM = int(os.environ.get("DEFAULT_NVIDIA_RPM", "40"))
PROXY_TIMEOUT = float(os.environ.get("PROXY_TIMEOUT", "10"))
UPSTREAM_CONNECT_TIMEOUT = float(os.environ.get("UPSTREAM_CONNECT_TIMEOUT", "10"))
UPSTREAM_READ_TIMEOUT = float(os.environ.get("UPSTREAM_READ_TIMEOUT", "120"))
MAX_CONCURRENT_REQUESTS = int(os.environ.get("MAX_CONCURRENT_REQUESTS", "100"))
MAX_ROUTES_PER_REQUEST = int(os.environ.get("MAX_ROUTES_PER_REQUEST", "50"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "dev-admin-token")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
}
