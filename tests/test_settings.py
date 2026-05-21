from __future__ import annotations

import importlib
from pathlib import Path

from hep_data_azure.settings import base
from hep_data_azure.settings import test as test_settings


def test_base_settings_defaults(monkeypatch):
    for name in [
        "DATABASE_URL",
        "QUEUE_NAME",
        "BLOB_CONTAINER_NAME",
        "QUEUE_VISIBILITY_TIMEOUT_SECONDS",
        "JOB_POLL_INTERVAL_SECONDS",
        "LOCAL_JOB_RUNNER_POLL_INTERVAL_SECONDS",
        "PLOT_RUNNER_TIMEOUT_SECONDS",
        "PLOT_RUNNER_ROOT",
        "JOB_RETRY_LIMIT",
        "PLOT_RUNNER_DRIVER",
        "PLOT_DRIVER_EXECUTOR",
        "SECRET_SOURCE",
        "SERVICEX_CONFIG_PATH",
    ]:
        monkeypatch.delenv(name, raising=False)

    settings = importlib.reload(base)

    assert settings.database_settings()["ENGINE"] == "django.db.backends.sqlite3"
    assert settings.QUEUE_NAME == "plot-jobs"
    assert settings.BLOB_CONTAINER_NAME == "plot-artifacts"
    assert settings.QUEUE_VISIBILITY_TIMEOUT_SECONDS == 120
    assert settings.JOB_POLL_INTERVAL_SECONDS == 2.0
    assert settings.JOB_POLL_INTERVAL_MILLISECONDS == 2000
    assert settings.LOCAL_JOB_RUNNER_POLL_INTERVAL_SECONDS == 1.0
    assert settings.PLOT_RUNNER_TIMEOUT_SECONDS == 600
    assert Path(settings.PLOT_RUNNER_ROOT).as_posix().endswith("tmp/plot-runner")
    assert settings.JOB_RETRY_LIMIT == 3
    assert settings.PLOT_RUNNER_DRIVER == "python -m portal.plot_driver"
    assert settings.PLOT_DRIVER_EXECUTOR == "fake"
    assert settings.SECRET_SOURCE == "env"
    assert Path(settings.SERVICEX_CONFIG_PATH).as_posix().endswith(
        "secrets/servicex.yaml"
    )


def test_test_settings_use_memory_database():
    assert test_settings.SECRET_KEY == "test-secret-key"
    assert test_settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert "memory" in test_settings.DATABASES["default"]["NAME"]
    assert test_settings.ALLOWED_HOSTS == ["testserver", "localhost", "127.0.0.1"]
