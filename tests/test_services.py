from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from portal.models import JobStatus
from portal.queue import InMemoryQueueClient
from portal.services import (
    JobNotClaimableError,
    QueueEnqueueError,
    SingleActiveJobError,
    claim_job,
    create_queued_job,
    list_all_jobs,
    list_jobs_for_user,
    mark_cancelled,
    mark_completed,
    mark_failed,
)


class FailingQueueClient:
    def enqueue_job(
        self, job_id: str, backend_profile: str
    ) -> str:  # pragma: no cover - simple fake
        raise RuntimeError("boom")


class ServiceTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def test_create_queued_job_writes_queue_message(self):
        user = self.User.objects.create_user(username="alice", password="secret")
        queue_client = InMemoryQueueClient()

        result = create_queued_job(
            owner=user,
            original_prompt="  Make a plot  ",
            backend_profile="servicex_awkward",
            queue_client=queue_client,
        )

        result.job.refresh_from_db()
        self.assertEqual(result.job.status, JobStatus.QUEUED)
        self.assertEqual(result.job.original_prompt, "Make a plot")
        self.assertEqual(result.job.resolved_dataset, "servicex-awkward-default-dataset")
        self.assertEqual(result.job.queue_message_id, result.queue_message_id)
        self.assertEqual(result.job.execution_timeout_seconds, 600)

        messages = queue_client.receive_messages()
        self.assertEqual(len(messages), 1)
        self.assertEqual(
            messages[0].body,
            (
                '{"backend_profile":"servicex_awkward","job_id":"'
                + str(result.job.submission_id)
                + '"}'
            ),
        )

    def test_create_queued_job_marks_failure_when_enqueue_fails(self):
        user = self.User.objects.create_user(username="bob", password="secret")

        with self.assertRaises(QueueEnqueueError):
            create_queued_job(
                owner=user,
                original_prompt="Make a plot",
                backend_profile="rdf",
                queue_client=FailingQueueClient(),
            )

        job = list_all_jobs().get()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertIn("Queue enqueue failed:", job.failure_message)

    def test_claim_job_requires_single_active_job(self):
        user = self.User.objects.create_user(username="carol", password="secret")
        queue_client = InMemoryQueueClient()
        first = create_queued_job(
            owner=user,
            original_prompt="First",
            backend_profile="rdf",
            queue_client=queue_client,
        ).job
        second = create_queued_job(
            owner=user,
            original_prompt="Second",
            backend_profile="rdf",
            queue_client=queue_client,
        ).job

        claimed_first = claim_job(first.submission_id)
        self.assertEqual(claimed_first.status, JobStatus.RUNNING)

        with self.assertRaises(SingleActiveJobError):
            claim_job(second.submission_id)

    def test_terminal_transitions_update_state_and_message(self):
        user = self.User.objects.create_user(username="dave", password="secret")
        queue_client = InMemoryQueueClient()
        job = create_queued_job(
            owner=user,
            original_prompt="Plot",
            backend_profile="rdf",
            queue_client=queue_client,
        ).job

        mark_completed(job, result_metadata={"ok": True})
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertEqual(job.result_metadata, {"ok": True})

        job = create_queued_job(
            owner=user,
            original_prompt="Plot again",
            backend_profile="rdf",
            queue_client=queue_client,
        ).job
        mark_failed(job, failure_message="boom")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.failure_message, "boom")

        job = create_queued_job(
            owner=user,
            original_prompt="Plot cancel",
            backend_profile="rdf",
            queue_client=queue_client,
        ).job
        mark_cancelled(job, failure_message="user cancelled")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.failure_message, "user cancelled")

    def test_cancel_rejects_running_job(self):
        user = self.User.objects.create_user(username="erin", password="secret")
        queue_client = InMemoryQueueClient()
        job = create_queued_job(
            owner=user,
            original_prompt="Plot",
            backend_profile="rdf",
            queue_client=queue_client,
        ).job
        claim_job(job.submission_id)

        with self.assertRaises(JobNotClaimableError):
            mark_cancelled(job, failure_message="too late")

    def test_user_job_listing_filters_by_owner(self):
        queue_client = InMemoryQueueClient()
        alice = self.User.objects.create_user(username="alice", password="secret")
        bob = self.User.objects.create_user(username="bob", password="secret")

        create_queued_job(
            owner=alice,
            original_prompt="Alice job",
            backend_profile="rdf",
            queue_client=queue_client,
        )
        create_queued_job(
            owner=bob,
            original_prompt="Bob job",
            backend_profile="rdf",
            queue_client=queue_client,
        )

        self.assertEqual(list_jobs_for_user(alice).count(), 1)
        self.assertEqual(list_jobs_for_user(bob).count(), 1)
        self.assertEqual(list_all_jobs().count(), 2)
