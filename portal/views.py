from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from portal.auth import approval_required, ensure_user_profile, is_user_approved, staff_required
from portal.backend import default_backend_profile, load_example_prompts
from portal.forms import ApprovalDecisionForm, JobSubmissionForm
from portal.models import ApprovalState, ArtifactKind, Job, JobArtifact, UserProfile
from portal.queue import get_queue_client
from portal.services import (
    QueueEnqueueError,
    create_queued_job,
    list_jobs_for_user,
    mark_cancelled,
)


def can_access_job(user, job: Job) -> bool:
    return user.is_staff or user.is_superuser or job.owner_id == user.id


def home(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated and not is_user_approved(request.user):
        return redirect("account-status")

    form = JobSubmissionForm()
    jobs = []
    examples = load_example_prompts()
    profile = None
    if request.user.is_authenticated:
        jobs = list_jobs_for_user(request.user)
        profile = ensure_user_profile(request.user)
        form = JobSubmissionForm(
            initial={
                "backend_profile": default_backend_profile().name,
            }
        )

    return render(
        request,
        "portal/home.html",
        {
            "examples": examples,
            "form": form,
            "jobs": jobs,
            "profile": profile,
            "page_title": "Plot Portal",
        },
    )


@approval_required
def submit_job(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect("home")

    form = JobSubmissionForm(request.POST)
    if not form.is_valid():
        return render(
            request,
            "portal/home.html",
            {
                "examples": load_example_prompts(),
                "form": form,
                "jobs": list_jobs_for_user(request.user),
                "profile": ensure_user_profile(request.user),
                "page_title": "Plot Portal",
            },
            status=400,
        )

    try:
        result = create_queued_job(
            owner=request.user,
            original_prompt=form.cleaned_data["original_prompt"],
            backend_profile=form.cleaned_data["backend_profile"],
            resolved_dataset=form.cleaned_data["resolved_dataset"] or None,
            queue_client=get_queue_client(),
        )
    except QueueEnqueueError as exc:
        messages.error(request, str(exc))
        return render(
            request,
            "portal/home.html",
            {
                "examples": load_example_prompts(),
                "form": form,
                "jobs": list_jobs_for_user(request.user),
                "profile": ensure_user_profile(request.user),
                "page_title": "Plot Portal",
            },
            status=500,
        )

    messages.success(request, "Job queued.")
    return redirect("job-detail", submission_id=result.job.submission_id)


@approval_required
def job_detail(request: HttpRequest, submission_id: str) -> HttpResponse:
    job = get_object_or_404(Job.objects.prefetch_related("artifacts"), submission_id=submission_id)
    if not can_access_job(request.user, job):
        return HttpResponseForbidden("You do not have access to this job.")

    canonical_artifacts = list(job.artifacts.all().order_by("artifact_kind", "created_at"))
    return render(
        request,
        "portal/job_detail.html",
        {
            "job": job,
            "artifacts": canonical_artifacts,
            "poll_interval_ms": settings.JOB_POLL_INTERVAL_MILLISECONDS,
        },
    )


@approval_required
def job_status_partial(request: HttpRequest, submission_id: str) -> HttpResponse:
    job = get_object_or_404(Job, submission_id=submission_id)
    if not can_access_job(request.user, job):
        return HttpResponseForbidden("You do not have access to this job.")
    return render(request, "portal/_job_status.html", {"job": job})


@approval_required
def job_generated_code(request: HttpRequest, submission_id: str) -> HttpResponse:
    job = get_object_or_404(Job, submission_id=submission_id)
    if not can_access_job(request.user, job):
        return HttpResponseForbidden("You do not have access to this job.")
    script_artifact = (
        job.artifacts.filter(artifact_kind=ArtifactKind.SCRIPT)
        .order_by("-created_at", "-id")
        .first()
    )
    generated_code = None
    if script_artifact:
        artifact_root = Path(settings.ARTIFACT_STORAGE_ROOT)
        local_path = artifact_root / script_artifact.blob_container / script_artifact.blob_key
        if local_path.exists():
            generated_code = local_path.read_text(encoding="utf-8")
    return render(
        request,
        "portal/_generated_code.html",
        {
            "generated_code": generated_code,
            "job": job,
        },
    )


@approval_required
def clone_job(request: HttpRequest, submission_id: str) -> HttpResponse:
    job = get_object_or_404(Job, submission_id=submission_id)
    if not can_access_job(request.user, job):
        return HttpResponseForbidden("You do not have access to this job.")

    if request.method == "POST":
        form = JobSubmissionForm(request.POST)
        if form.is_valid():
            result = create_queued_job(
                owner=request.user,
                original_prompt=form.cleaned_data["original_prompt"],
                backend_profile=form.cleaned_data["backend_profile"],
                resolved_dataset=form.cleaned_data["resolved_dataset"] or None,
                queue_client=get_queue_client(),
            )
            return redirect("job-detail", submission_id=result.job.submission_id)
    else:
        form = JobSubmissionForm(
            initial={
                "original_prompt": job.original_prompt,
                "backend_profile": job.backend_profile,
                "resolved_dataset": job.resolved_dataset,
            }
        )

    return render(
        request,
        "portal/job_clone.html",
        {
            "job": job,
            "form": form,
        },
    )


@approval_required
def job_artifact(request: HttpRequest, submission_id: str, artifact_id: int) -> HttpResponse:
    job = get_object_or_404(Job, submission_id=submission_id)
    if not can_access_job(request.user, job):
        return HttpResponseForbidden("You do not have access to this artifact.")

    artifact = get_object_or_404(JobArtifact, pk=artifact_id, job=job)
    artifact_root = Path(settings.ARTIFACT_STORAGE_ROOT)
    local_path = artifact_root / artifact.blob_container / artifact.blob_key
    if not local_path.exists():
        raise Http404("Artifact content is not available locally.")

    response = HttpResponse(local_path.read_bytes(), content_type=artifact.content_type)
    disposition = (
        "inline"
        if artifact.artifact_kind in {ArtifactKind.REPORT, ArtifactKind.PLOT}
        else "attachment"
    )
    response["Content-Disposition"] = f'{disposition}; filename="{local_path.name}"'
    return response


@approval_required
def cancel_job(request: HttpRequest, submission_id: str) -> HttpResponse:
    job = get_object_or_404(Job, submission_id=submission_id)
    if request.method != "POST":
        return redirect("job-detail", submission_id=submission_id)
    if not can_access_job(request.user, job):
        return HttpResponseForbidden("You do not have access to this job.")

    mark_cancelled(job, failure_message="Cancelled by user.")
    messages.success(request, "Job cancelled.")
    return redirect("job-detail", submission_id=submission_id)


@login_required
def account_status(request: HttpRequest) -> HttpResponse:
    profile = ensure_user_profile(request.user)
    return render(request, "portal/auth_status.html", {"profile": profile})


@staff_required
def admin_users(request: HttpRequest) -> HttpResponse:
    profiles = UserProfile.objects.select_related("user", "approved_by", "rejected_by").order_by(
        "approval_state", "user__username"
    )
    return render(
        request,
        "portal/admin_users.html",
        {
            "profiles": profiles,
            "decision_form": ApprovalDecisionForm(),
        },
    )


@staff_required
def approve_user(request: HttpRequest, user_id: int) -> HttpResponse:
    profile = get_object_or_404(UserProfile.objects.select_related("user"), user_id=user_id)
    if request.method != "POST":
        return redirect("admin-users")

    profile.approval_state = ApprovalState.APPROVED
    profile.approved_at = timezone.now()
    profile.approved_by = request.user
    profile.rejected_at = None
    profile.rejected_by = None
    profile.rejection_reason = ""
    profile.save(
        update_fields=[
            "approval_state",
            "approved_at",
            "approved_by",
            "rejected_at",
            "rejected_by",
            "rejection_reason",
        ]
    )
    messages.success(request, f"Approved {profile.user.username}.")
    return redirect("admin-users")


@staff_required
def reject_user(request: HttpRequest, user_id: int) -> HttpResponse:
    profile = get_object_or_404(UserProfile.objects.select_related("user"), user_id=user_id)
    if request.method != "POST":
        return redirect("admin-users")

    form = ApprovalDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Rejection reason is required.")
        return redirect("admin-users")

    profile.approval_state = ApprovalState.REJECTED
    profile.rejected_at = timezone.now()
    profile.rejected_by = request.user
    profile.approved_at = None
    profile.approved_by = None
    profile.rejection_reason = form.cleaned_data["reason"]
    profile.save(
        update_fields=[
            "approval_state",
            "approved_at",
            "approved_by",
            "rejected_at",
            "rejected_by",
            "rejection_reason",
        ]
    )
    messages.success(request, f"Rejected {profile.user.username}.")
    return redirect("admin-users")


class PortalLogoutView(LogoutView):
    next_page = "home"
