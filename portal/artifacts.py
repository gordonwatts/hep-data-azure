from __future__ import annotations

import mimetypes
import shutil
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse
from urllib.request import url2pathname, urlopen

from django.conf import settings

AZURITE_BLOB_API_VERSION = "2023-01-03"

with suppress(ImportError):
    from azure.storage.blob import BlobServiceClient, ContentSettings


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    job_id: str
    artifact_kind: str
    blob_container: str
    blob_key: str
    content_type: str
    size_bytes: int
    is_canonical: bool
    created_at: datetime


class ArtifactStore(Protocol):
    def put_artifact(
        self,
        job_id: str,
        local_path: Path,
        artifact_kind: str,
        content_type: str | None = None,
        *,
        is_canonical: bool = False,
    ) -> ArtifactRef: ...

    def get_read_url(self, artifact_ref: ArtifactRef) -> str: ...

    def delete_artifacts_for_job(self, job_id: str) -> None: ...


def artifact_ref_from_model(job_id: str, artifact) -> ArtifactRef:
    return ArtifactRef(
        job_id=job_id,
        artifact_kind=artifact.artifact_kind,
        blob_container=artifact.blob_container,
        blob_key=artifact.blob_key,
        content_type=artifact.content_type,
        size_bytes=artifact.size_bytes,
        is_canonical=artifact.is_canonical,
        created_at=artifact.created_at,
    )


def build_blob_key(job_id: str, artifact_kind: str, filename: str) -> str:
    safe_filename = Path(filename).name or "artifact"
    return f"jobs/{job_id}/{artifact_kind}/{safe_filename}"


class LocalArtifactStore:
    def __init__(self, root: Path, container_name: str = "plot-artifacts") -> None:
        self.root = root
        self.container_name = container_name
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, blob_key: str) -> Path:
        return self.root / self.container_name / blob_key

    def put_artifact(
        self,
        job_id: str,
        local_path: Path,
        artifact_kind: str,
        content_type: str | None = None,
        *,
        is_canonical: bool = False,
    ) -> ArtifactRef:
        source_path = Path(local_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)

        detected_content_type = content_type or mimetypes.guess_type(source_path.name)[0]
        normalized_content_type = detected_content_type or "application/octet-stream"
        blob_key = build_blob_key(job_id, artifact_kind, source_path.name)
        destination = self._resolve_path(blob_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)

        return ArtifactRef(
            job_id=job_id,
            artifact_kind=artifact_kind,
            blob_container=self.container_name,
            blob_key=blob_key,
            content_type=normalized_content_type,
            size_bytes=destination.stat().st_size,
            is_canonical=is_canonical,
            created_at=datetime.now(UTC),
        )

    def get_read_url(self, artifact_ref: ArtifactRef) -> str:
        return self._resolve_path(artifact_ref.blob_key).resolve().as_uri()

    def read_artifact_bytes(self, artifact_ref: ArtifactRef) -> bytes:
        return self._resolve_path(artifact_ref.blob_key).read_bytes()

    def delete_artifacts_for_job(self, job_id: str) -> None:
        job_root = self.root / self.container_name / "jobs" / job_id
        if job_root.exists():
            shutil.rmtree(job_root)

    def list_artifacts_for_job(self, job_id: str) -> tuple[ArtifactRef, ...]:
        job_root = self.root / self.container_name / "jobs" / job_id
        if not job_root.exists():
            return ()

        refs = []
        for artifact_file in job_root.rglob("*"):
            if not artifact_file.is_file():
                continue
            relative_key = artifact_file.relative_to(self.root / self.container_name).as_posix()
            artifact_kind = relative_key.split("/", 3)[2]
            refs.append(
                ArtifactRef(
                    job_id=job_id,
                    artifact_kind=artifact_kind,
                    blob_container=self.container_name,
                    blob_key=relative_key,
                    content_type=mimetypes.guess_type(artifact_file.name)[0]
                    or "application/octet-stream",
                    size_bytes=artifact_file.stat().st_size,
                    is_canonical=False,
                    created_at=datetime.now(UTC),
                )
            )
        return tuple(refs)


class AzureBlobArtifactStore:
    def __init__(
        self,
        connection_string: str,
        container_name: str = "plot-artifacts",
    ) -> None:
        if "BlobServiceClient" not in globals():  # pragma: no cover - defensive
            raise RuntimeError("azure-storage-blob is not installed")
        self.container_name = container_name
        self._service_client = BlobServiceClient.from_connection_string(
            connection_string,
            api_version=AZURITE_BLOB_API_VERSION,
        )
        self._container_client = self._service_client.get_container_client(container_name)
        with suppress(Exception):
            self._container_client.create_container()

    def put_artifact(
        self,
        job_id: str,
        local_path: Path,
        artifact_kind: str,
        content_type: str | None = None,
        *,
        is_canonical: bool = False,
    ) -> ArtifactRef:
        source_path = Path(local_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)

        detected_content_type = content_type or mimetypes.guess_type(source_path.name)[0]
        normalized_content_type = detected_content_type or "application/octet-stream"
        blob_key = build_blob_key(job_id, artifact_kind, source_path.name)
        blob_client = self._container_client.get_blob_client(blob_key)
        with source_path.open("rb") as handle:
            blob_client.upload_blob(
                handle,
                overwrite=True,
                content_settings=ContentSettings(content_type=normalized_content_type),
            )
        properties = blob_client.get_blob_properties()
        return ArtifactRef(
            job_id=job_id,
            artifact_kind=artifact_kind,
            blob_container=self.container_name,
            blob_key=blob_key,
            content_type=normalized_content_type,
            size_bytes=properties.size,
            is_canonical=is_canonical,
            created_at=datetime.now(UTC),
        )

    def get_read_url(self, artifact_ref: ArtifactRef) -> str:
        return self._container_client.get_blob_client(artifact_ref.blob_key).url

    def read_artifact_bytes(self, artifact_ref: ArtifactRef) -> bytes:
        blob_client = self._container_client.get_blob_client(artifact_ref.blob_key)
        return blob_client.download_blob().readall()

    def delete_artifacts_for_job(self, job_id: str) -> None:
        prefix = f"jobs/{job_id}/"
        for blob in self._container_client.list_blobs(name_starts_with=prefix):
            self._container_client.delete_blob(blob.name)


def get_artifact_store() -> ArtifactStore:
    backend = getattr(settings, "ARTIFACT_STORAGE_BACKEND", "local")
    if backend == "azure":
        connection_string = (
            settings.BLOB_CONNECTION_STRING
            or settings.AZURE_STORAGE_CONNECTION_STRING
            or "UseDevelopmentStorage=true"
        )
        return AzureBlobArtifactStore(connection_string, settings.BLOB_CONTAINER_NAME)
    return LocalArtifactStore(Path(settings.ARTIFACT_STORAGE_ROOT), settings.BLOB_CONTAINER_NAME)


def read_artifact_bytes(artifact_ref: ArtifactRef, store: ArtifactStore) -> bytes:
    if hasattr(store, "read_artifact_bytes"):
        return store.read_artifact_bytes(artifact_ref)

    read_url = store.get_read_url(artifact_ref)
    parsed = urlparse(read_url)
    if parsed.scheme == "file":
        return Path(url2pathname(parsed.path)).read_bytes()
    with urlopen(read_url) as response:
        return response.read()


def read_artifact_text(artifact_ref: ArtifactRef, store: ArtifactStore) -> str:
    return read_artifact_bytes(artifact_ref, store).decode("utf-8")
