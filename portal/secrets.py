from __future__ import annotations

import os
import shutil
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

with suppress(ImportError):
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient


class MissingSecretError(LookupError):
    pass


class SecretProvider(Protocol):
    def has_secret(self, name: str) -> bool: ...

    def get_secret(self, name: str) -> str: ...

    def materialize_secret_file(self, name: str, destination: Path) -> Path: ...


def redact_secret_values(text: str, secret_values: list[str] | tuple[str, ...]) -> str:
    redacted = text
    for secret in sorted({value for value in secret_values if value}, key=len, reverse=True):
        redacted = redacted.replace(secret, "[redacted]")
    return redacted


@dataclass(slots=True)
class LocalSecretProvider:
    secret_dir: Path

    def _secret_path(self, name: str) -> Path:
        return self.secret_dir / name

    def has_secret(self, name: str) -> bool:
        return name in os.environ or self._secret_path(name).exists()

    def get_secret(self, name: str) -> str:
        if name in os.environ:
            return os.environ[name]

        secret_path = self._secret_path(name)
        if secret_path.exists():
            return secret_path.read_text(encoding="utf-8").rstrip("\n")

        raise MissingSecretError(name)

    def materialize_secret_file(self, name: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)

        if name in os.environ:
            env_value = os.environ[name]
            env_path = Path(env_value)
            if env_path.exists():
                shutil.copy2(env_path, destination)
                return destination
            destination.write_text(env_value, encoding="utf-8")
            return destination

        secret_path = self._secret_path(name)
        if secret_path.exists():
            shutil.copy2(secret_path, destination)
            return destination

        raise MissingSecretError(name)


class KeyVaultSecretProvider:
    def __init__(self, vault_url: str) -> None:
        if "SecretClient" not in globals() or "DefaultAzureCredential" not in globals():
            raise RuntimeError("azure-keyvault-secrets is not installed")
        self.vault_url = vault_url
        self._client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())

    def has_secret(self, name: str) -> bool:
        try:
            self.get_secret(name)
        except MissingSecretError:
            return False
        return True

    def get_secret(self, name: str) -> str:
        secret = self._client.get_secret(name)
        if not secret.value:
            raise MissingSecretError(name)
        return secret.value

    def materialize_secret_file(self, name: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.get_secret(name), encoding="utf-8")
        return destination


def get_secret_provider() -> SecretProvider:
    source = getattr(settings, "SECRET_SOURCE", "env")
    if source in {"env", "file"}:
        return LocalSecretProvider(Path(settings.SECRET_DIR))

    if source == "keyvault":
        vault_url = settings.KEY_VAULT_URL
        if not vault_url and settings.KEY_VAULT_NAME:
            vault_url = f"https://{settings.KEY_VAULT_NAME}.vault.azure.net/"
        if not vault_url:
            raise ImproperlyConfigured("KEY_VAULT_URL or KEY_VAULT_NAME must be set")
        return KeyVaultSecretProvider(vault_url)

    raise ImproperlyConfigured(f"Unknown SECRET_SOURCE: {source}")
