from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from portal.secrets import (
    KeyVaultSecretProvider,
    LocalSecretProvider,
    get_secret_provider,
    redact_secret_values,
)


class SecretProviderTests(TestCase):
    def _secret_dir(self):
        return tempfile.TemporaryDirectory(dir=Path.cwd())

    def test_local_secret_provider_reads_env_and_file_secrets(self):
        with self._secret_dir() as secret_dir:
            secret_root = Path(secret_dir)
            secret_root.joinpath("GITHUB_CLIENT_SECRET").write_text(
                "file-secret-value",
                encoding="utf-8",
            )
            with override_settings(SECRET_DIR=secret_dir, SECRET_SOURCE="env"):
                provider = LocalSecretProvider(secret_root)

                self.assertTrue(provider.has_secret("GITHUB_CLIENT_SECRET"))
                self.assertEqual(provider.get_secret("GITHUB_CLIENT_SECRET"), "file-secret-value")

                provider.materialize_secret_file(
                    "GITHUB_CLIENT_SECRET",
                    secret_root / "materialized.txt",
                )
                self.assertEqual(
                    (secret_root / "materialized.txt").read_text(encoding="utf-8"),
                    "file-secret-value",
                )

    def test_local_secret_provider_materializes_env_file_paths(self):
        with self._secret_dir() as secret_dir:
            secret_root = Path(secret_dir)
            source_file = secret_root / "servicex.yaml"
            source_file.write_text("service: config", encoding="utf-8")
            with override_settings(SECRET_DIR=secret_dir, SECRET_SOURCE="env"):
                provider = LocalSecretProvider(secret_root)

                with mock.patch.dict(
                    os.environ,
                    {"SERVICEX_CONFIG_PATH": str(source_file)},
                    clear=False,
                ):
                    destination = secret_root / "copy" / "servicex.yaml"
                    provider.materialize_secret_file(
                        "SERVICEX_CONFIG_PATH",
                        destination,
                    )

                self.assertEqual(destination.read_text(encoding="utf-8"), "service: config")

    def test_redact_secret_values_replaces_known_strings(self):
        redacted = redact_secret_values(
            "token=abc123 and secret=def456",
            ["def456", "abc123"],
        )

        self.assertEqual(redacted, "token=[redacted] and secret=[redacted]")

    @override_settings(SECRET_SOURCE="env")
    def test_get_secret_provider_returns_local_provider_by_default(self):
        provider = get_secret_provider()

        self.assertIsInstance(provider, LocalSecretProvider)

    def test_key_vault_secret_provider_uses_secret_client(self):
        class FakeSecret:
            def __init__(self, value: str | None) -> None:
                self.value = value

        class FakeSecretClient:
            def __init__(self, *, vault_url, credential) -> None:
                self.vault_url = vault_url
                self.credential = credential
                self.requests: list[str] = []

            def get_secret(self, name: str):
                self.requests.append(name)
                return FakeSecret("vault-value")

        class FakeCredential:
            pass

        with override_settings(SECRET_SOURCE="keyvault", KEY_VAULT_URL="https://vault.example"):
            with mock.patch("portal.secrets.SecretClient", FakeSecretClient, create=True):
                with mock.patch(
                    "portal.secrets.DefaultAzureCredential",
                    FakeCredential,
                    create=True,
                ):
                    provider = KeyVaultSecretProvider("https://vault.example")
                    self.assertTrue(provider.has_secret("OPENAI_API_KEY"))
                    self.assertEqual(provider.get_secret("OPENAI_API_KEY"), "vault-value")
