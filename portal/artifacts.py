from __future__ import annotations

import mimetypes
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


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
