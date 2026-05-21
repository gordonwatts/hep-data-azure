from __future__ import annotations

import tempfile
from pathlib import Path

from portal.artifacts import LocalArtifactStore, build_blob_key


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
