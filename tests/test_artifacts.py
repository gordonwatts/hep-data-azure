from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from portal.artifacts import AzureBlobArtifactStore, LocalArtifactStore, build_blob_key


def test_blob_key_shape_uses_job_and_kind():
    assert build_blob_key("job-123", "report", "../plot.md") == "jobs/job-123/report/plot.md"


def test_local_artifact_store_put_get_and_delete():
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
        root = Path(temp_dir)
        store = LocalArtifactStore(root)
        source = root / "result.txt"
        source.write_text("plot result", encoding="utf-8")

        ref = store.put_artifact(
            job_id="job-123",
            local_path=source,
            artifact_kind="report",
            content_type="text/plain",
            is_canonical=True,
        )

        assert ref.job_id == "job-123"
        assert ref.artifact_kind == "report"
        assert ref.blob_container == "plot-artifacts"
        assert ref.blob_key == "jobs/job-123/report/result.txt"
        assert ref.content_type == "text/plain"
        assert ref.size_bytes == len("plot result")
        assert ref.is_canonical is True
        assert store.get_read_url(ref).startswith("file:")
        assert (root / "plot-artifacts" / ref.blob_key).exists()

        store.delete_artifacts_for_job("job-123")
        assert not (root / "plot-artifacts" / "jobs" / "job-123").exists()


def test_azure_blob_artifact_store_uses_blob_clients():
    uploaded = {}
    deleted = []

    class FakeBlobClient:
        def __init__(self, blob_name: str):
            self.blob_name = blob_name

        def upload_blob(self, data, overwrite=False, content_settings=None):
            uploaded[self.blob_name] = data.read()

        def get_blob_properties(self):
            return SimpleNamespace(size=len(uploaded[self.blob_name]))

        @property
        def url(self):
            return f"https://example.blob.core.windows.net/plot-artifacts/{self.blob_name}"

    class FakeContainerClient:
        def create_container(self):
            return None

        def get_blob_client(self, blob_name: str):
            return FakeBlobClient(blob_name)

        def list_blobs(self, name_starts_with: str):
            return [
                SimpleNamespace(name=f"{name_starts_with}one.txt"),
                SimpleNamespace(name=f"{name_starts_with}two.txt"),
            ]

        def delete_blob(self, blob_name: str):
            deleted.append(blob_name)

    fake_service_client = SimpleNamespace(
        get_container_client=lambda container_name: FakeContainerClient()
    )

    with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp_dir:
        source = Path(temp_dir) / "result.txt"
        source.write_text("blob result", encoding="utf-8")

        with mock.patch(
            "portal.artifacts.BlobServiceClient.from_connection_string",
            return_value=fake_service_client,
        ):
            store = AzureBlobArtifactStore("UseDevelopmentStorage=true")
            ref = store.put_artifact(
                job_id="job-123",
                local_path=source,
                artifact_kind="report",
                content_type="text/plain",
                is_canonical=True,
            )

            assert ref.job_id == "job-123"
            assert ref.blob_container == "plot-artifacts"
            assert ref.blob_key == "jobs/job-123/report/result.txt"
            assert ref.content_type == "text/plain"
            assert ref.size_bytes == len("blob result")
            assert store.get_read_url(ref).endswith(ref.blob_key)
            assert uploaded[ref.blob_key] == b"blob result"

            store.delete_artifacts_for_job("job-123")
            assert deleted == ["jobs/job-123/one.txt", "jobs/job-123/two.txt"]
