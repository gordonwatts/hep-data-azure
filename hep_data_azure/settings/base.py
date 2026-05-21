from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return default if value is None else value


def env_int(name: str, default: int) -> int:
    value = env(name)
    return default if value is None else int(value)


def env_float(name: str, default: float) -> float:
    value = env(name)
    return default if value is None else float(value)


def database_settings() -> dict[str, Any]:
    database_url = env("DATABASE_URL")
    if not database_url:
        return {
            "ENGINE": env("DJANGO_DB_ENGINE", "django.db.backends.sqlite3"),
            "NAME": env("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
        }

    parsed = urlparse(database_url)
    scheme = parsed.scheme.split("+", 1)[0]

    if scheme in {"sqlite", "sqlite3"}:
        path = parsed.path.lstrip("/")
        if not path or path == ":memory:":
            name = ":memory:"
        else:
            name = f"/{path}" if parsed.netloc else path
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": name}

    if scheme in {"postgres", "postgresql"}:
        options = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        config: dict[str, Any] = {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": parsed.port or "",
        }
        if options:
            config["OPTIONS"] = options
        return config

    if scheme in {"mssql", "sqlserver"}:
        return {
            "ENGINE": env("DJANGO_DB_ENGINE", "mssql"),
            "NAME": parsed.path.lstrip("/"),
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": parsed.port or "",
        }

    return {
        "ENGINE": env("DJANGO_DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": env("DJANGO_DB_NAME", str(BASE_DIR / "db.sqlite3")),
    }


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-secret-key")
DEBUG = env("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
    host
    for host in (env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,::1") or "").split(",")
    if host
]

DATABASE_URL = env("DATABASE_URL")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "hep_data_azure.urls"
WSGI_APPLICATION = "hep_data_azure.wsgi.application"
ASGI_APPLICATION = "hep_data_azure.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {"default": database_settings()}

QUEUE_NAME = env("QUEUE_NAME", "plot-jobs")
QUEUE_CONNECTION_STRING = env("QUEUE_CONNECTION_STRING", env("AZURE_STORAGE_CONNECTION_STRING"))
QUEUE_VISIBILITY_TIMEOUT_SECONDS = env_int("QUEUE_VISIBILITY_TIMEOUT_SECONDS", 120)

BLOB_CONTAINER_NAME = env("BLOB_CONTAINER_NAME", "plot-artifacts")
BLOB_CONNECTION_STRING = env("BLOB_CONNECTION_STRING", env("AZURE_STORAGE_CONNECTION_STRING"))
BLOB_ACCOUNT_NAME = env("AZURE_STORAGE_ACCOUNT_NAME")
BLOB_ACCOUNT_KEY = env("AZURE_STORAGE_ACCOUNT_KEY")
BLOB_ENDPOINT = env("AZURE_BLOB_ENDPOINT", "http://127.0.0.1:10000/devstoreaccount1")
QUEUE_ENDPOINT = env("AZURE_QUEUE_ENDPOINT", "http://127.0.0.1:10001/devstoreaccount1")
AZURE_STORAGE_CONNECTION_STRING = env("AZURE_STORAGE_CONNECTION_STRING")
ARTIFACT_STORAGE_ROOT = env("ARTIFACT_STORAGE_ROOT", str(BASE_DIR / "artifacts"))

JOB_POLL_INTERVAL_SECONDS = env_float("JOB_POLL_INTERVAL_SECONDS", 2.0)
JOB_POLL_INTERVAL_MILLISECONDS = int(JOB_POLL_INTERVAL_SECONDS * 1000)
LOCAL_JOB_RUNNER_POLL_INTERVAL_SECONDS = env_float(
    "LOCAL_JOB_RUNNER_POLL_INTERVAL_SECONDS", 1.0
)
PLOT_RUNNER_TIMEOUT_SECONDS = env_int("PLOT_RUNNER_TIMEOUT_SECONDS", 600)
JOB_RETRY_LIMIT = env_int("JOB_RETRY_LIMIT", 3)
QUEUE_BACKEND = env("QUEUE_BACKEND", "database")

SECRET_SOURCE = env("SECRET_SOURCE", "env")
SECRET_DIR = env("SECRET_DIR", str(BASE_DIR / "secrets"))
SERVICEX_CONFIG_PATH = env("SERVICEX_CONFIG_PATH", str(BASE_DIR / "secrets" / "servicex.yaml"))
OPENAI_API_KEY = env("OPENAI_API_KEY")
GITHUB_CLIENT_ID = env("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = env("GITHUB_CLIENT_SECRET")
KEY_VAULT_URL = env("KEY_VAULT_URL")
KEY_VAULT_NAME = env("KEY_VAULT_NAME")

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"
