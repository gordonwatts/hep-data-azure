from __future__ import annotations

from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserRole(models.TextChoices):
    USER = "user", "User"
    ADMIN = "admin", "Admin"
    SERVICE = "service", "Service"


class ApprovalState(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class JobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"

    @classmethod
    def terminal_values(cls) -> set[str]:
        return {cls.COMPLETED, cls.FAILED, cls.CANCELLED}


class ArtifactKind(models.TextChoices):
    REPORT = "report", "Report"
    PLOT = "plot", "Plot"
    SCRIPT = "script", "Script"
    LOG = "log", "Log"
    BUNDLE = "bundle", "Bundle"


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(max_length=16, choices=UserRole.choices, default=UserRole.USER)
    approval_state = models.CharField(
        max_length=16,
        choices=ApprovalState.choices,
        default=ApprovalState.PENDING,
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_user_profiles",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rejected_user_profiles",
    )
    rejection_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["approval_state"], name="profile_state_idx"),
            models.Index(fields=["role"], name="profile_role_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user!s} ({self.approval_state})"


class Job(models.Model):
    submission_id = models.UUIDField(default=uuid4, unique=True, editable=False, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="jobs",
    )
    original_prompt = models.TextField()
    resolved_dataset = models.TextField(blank=True, default="")
    backend_profile = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=JobStatus.choices,
        default=JobStatus.QUEUED,
    )
    queue_message_id = models.CharField(max_length=128, blank=True, default="")
    retry_count = models.PositiveSmallIntegerField(default=0)
    queue_position = models.PositiveIntegerField(null=True, blank=True)
    queue_depth = models.PositiveIntegerField(null=True, blank=True)
    execution_timeout_seconds = models.PositiveIntegerField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    runtime_seconds = models.FloatField(null=True, blank=True)
    generated_code_preview = models.TextField(blank=True, default="")
    failure_message = models.TextField(blank=True, default="")
    result_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "status"], name="job_owner_status_idx"),
            models.Index(fields=["submission_id"], name="job_submission_id_idx"),
            models.Index(fields=["status", "submitted_at"], name="job_status_submitted_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(retry_count__gte=0),
                name="job_retry_count_nonnegative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.submission_id} [{self.status}]"


class JobArtifact(models.Model):
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="artifacts")
    artifact_kind = models.CharField(max_length=16, choices=ArtifactKind.choices)
    blob_container = models.CharField(max_length=128)
    blob_key = models.CharField(max_length=512)
    content_type = models.CharField(max_length=255)
    size_bytes = models.PositiveBigIntegerField(default=0)
    is_canonical = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["job", "artifact_kind"], name="artifact_job_kind_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(size_bytes__gte=0),
                name="artifact_size_nonnegative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.job.submission_id} [{self.artifact_kind}]"


def _queue_message_id() -> str:
    return uuid4().hex


class QueueMessageRecord(models.Model):
    message_id = models.CharField(
        max_length=32,
        unique=True,
        default=_queue_message_id,
        editable=False,
    )
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="queue_messages")
    backend_profile = models.CharField(max_length=64)
    body = models.TextField()
    dequeue_count = models.PositiveIntegerField(default=0)
    pop_receipt = models.CharField(max_length=64, blank=True, default="")
    visible_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["visible_at", "created_at"], name="queue_visible_created_idx"),
            models.Index(fields=["job"], name="queue_job_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.message_id} ({self.job.submission_id})"
