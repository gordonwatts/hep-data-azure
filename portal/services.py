from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from portal.backend import normalize_submission_input
from portal.models import Job, JobStatus
from portal.queue import QueueClient


class JobServiceError(RuntimeError):
    pass


class SingleActiveJobError(JobServiceError):
    pass


class JobNotClaimableError(JobServiceError):
    pass


class QueueEnqueueError(JobServiceError):
    pass


@dataclass(frozen=True, slots=True)
class JobSubmissionResult:
    job: Job
    queue_message_id: str


def create_queued_job(
    *,
    owner,
    original_prompt: str,
    backend_profile: str,
    queue_client: QueueClient,
    resolved_dataset: str | None = None,
    execution_timeout_seconds: int | None = None,
) -> JobSubmissionResult:
    normalized = normalize_submission_input(
        prompt=original_prompt,
        backend_profile=backend_profile,
        dataset=resolved_dataset,
    )

    with transaction.atomic():
        job = Job.objects.create(
            owner=owner,
            original_prompt=normalized.original_prompt,
            resolved_dataset=normalized.resolved_dataset,
            backend_profile=normalized.backend_profile,
            execution_timeout_seconds=execution_timeout_seconds
            or settings.PLOT_RUNNER_TIMEOUT_SECONDS,
            status=JobStatus.QUEUED,
        )

    try:
        queue_message_id = queue_client.enqueue_job(str(job.submission_id), job.backend_profile)
    except Exception as exc:  # pragma: no cover - defensive wrapper
        with transaction.atomic():
            Job.objects.filter(pk=job.pk).update(
                status=JobStatus.FAILED,
                completed_at=timezone.now(),
                failure_message=f"Queue enqueue failed: {exc}",
            )
        raise QueueEnqueueError("Failed to enqueue job") from exc

    job.queue_message_id = queue_message_id
    job.save(update_fields=["queue_message_id"])
    return JobSubmissionResult(job=job, queue_message_id=queue_message_id)


def claim_job(submission_id: UUID | str) -> Job:
    if isinstance(submission_id, UUID):
        lookup_value = submission_id
    else:
        lookup_value = UUID(str(submission_id))

    with transaction.atomic():
        job = Job.objects.select_for_update().get(submission_id=lookup_value)
        if job.status != JobStatus.QUEUED:
            raise JobNotClaimableError(f"Job {job.submission_id} is not queued")
        if Job.objects.filter(status=JobStatus.RUNNING).exclude(pk=job.pk).exists():
            raise SingleActiveJobError("Another job is already running")
        job.status = JobStatus.RUNNING
        job.started_at = timezone.now()
        job.save(update_fields=["status", "started_at"])
        return job


def mark_completed(job: Job, *, result_metadata: dict[str, Any] | None = None) -> Job:
    current = Job.objects.get(pk=job.pk)
    current.status = JobStatus.COMPLETED
    current.completed_at = timezone.now()
    current.result_metadata = result_metadata or {}
    current.failure_message = ""
    current.save(
        update_fields=[
            "status",
            "completed_at",
            "result_metadata",
            "failure_message",
        ]
    )
    return current


def mark_failed(
    job: Job,
    *,
    failure_message: str,
    result_metadata: dict[str, Any] | None = None,
) -> Job:
    current = Job.objects.get(pk=job.pk)
    current.status = JobStatus.FAILED
    current.completed_at = timezone.now()
    current.result_metadata = result_metadata or {}
    current.failure_message = failure_message
    current.save(
        update_fields=[
            "status",
            "completed_at",
            "result_metadata",
            "failure_message",
        ]
    )
    return current


def mark_cancelled(job: Job, *, failure_message: str = "") -> Job:
    current = Job.objects.get(pk=job.pk)
    if current.status != JobStatus.QUEUED:
        raise JobNotClaimableError(
            f"Job {current.submission_id} cannot be cancelled in {current.status}"
        )

    current.status = JobStatus.CANCELLED
    current.completed_at = timezone.now()
    current.failure_message = failure_message
    current.save(update_fields=["status", "completed_at", "failure_message"])
    return current


def list_jobs_for_user(user):
    return Job.objects.filter(owner=user).order_by("-submitted_at", "-id")


def list_all_jobs():
    return Job.objects.all().order_by("-submitted_at", "-id")
