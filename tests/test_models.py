from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from portal.models import (
    ApprovalState,
    ArtifactKind,
    Job,
    JobArtifact,
    JobStatus,
    UserProfile,
    UserRole,
)


class ModelTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def test_user_profile_defaults(self):
        user = self.User.objects.create_user(username="alice", password="secret")

        profile = UserProfile.objects.create(user=user)

        self.assertEqual(profile.role, UserRole.USER)
        self.assertEqual(profile.approval_state, ApprovalState.PENDING)
        self.assertIsNone(profile.approved_at)
        self.assertIsNone(profile.approved_by)
        self.assertIsNone(profile.rejected_at)
        self.assertIsNone(profile.rejected_by)
        self.assertEqual(profile.rejection_reason, "")
        self.assertEqual(str(profile), "alice (pending)")

    def test_job_defaults_and_terminal_helper(self):
        owner = self.User.objects.create_user(username="bob", password="secret")

        job = Job.objects.create(
            owner=owner,
            original_prompt="Make a plot of the spectrum",
            backend_profile="servicex_awkward",
        )

        self.assertIsNotNone(job.submission_id)
        self.assertEqual(job.status, JobStatus.QUEUED)
        self.assertEqual(job.retry_count, 0)
        self.assertEqual(job.queue_message_id, "")
        self.assertIsNone(job.queue_position)
        self.assertIsNone(job.queue_depth)
        self.assertIsNone(job.execution_timeout_seconds)
        self.assertIsNone(job.started_at)
        self.assertIsNone(job.completed_at)
        self.assertIsNone(job.runtime_seconds)
        self.assertEqual(job.generated_code_preview, "")
        self.assertEqual(job.failure_message, "")
        self.assertEqual(job.result_metadata, {})
        self.assertEqual(str(job), f"{job.submission_id} [queued]")
        self.assertEqual(
            JobStatus.terminal_values(),
            {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
        )

    def test_job_artifact_defaults_and_string_representation(self):
        owner = self.User.objects.create_user(username="carol", password="secret")
        job = Job.objects.create(
            owner=owner,
            original_prompt="Generate a report",
            backend_profile="rdf",
        )

        artifact = JobArtifact.objects.create(
            job=job,
            artifact_kind=ArtifactKind.REPORT,
            blob_container="plot-artifacts",
            blob_key="jobs/example/report.md",
            content_type="text/markdown",
            size_bytes=12,
            is_canonical=True,
        )

        self.assertEqual(artifact.artifact_kind, ArtifactKind.REPORT)
        self.assertEqual(artifact.blob_container, "plot-artifacts")
        self.assertEqual(artifact.blob_key, "jobs/example/report.md")
        self.assertEqual(artifact.content_type, "text/markdown")
        self.assertEqual(artifact.size_bytes, 12)
        self.assertTrue(artifact.is_canonical)
        self.assertEqual(str(artifact), f"{job.submission_id} [report]")
