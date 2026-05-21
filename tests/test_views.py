from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from portal.models import ApprovalState, Job, UserProfile


class ViewTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def make_user(self, username: str, *, is_staff: bool = False):
        user = self.User.objects.create_user(username=username, password="secret")
        if is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        profile = UserProfile.objects.get(user=user)
        return user, profile

    def test_home_prompts_for_login(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, "Please sign in to submit a job.")

    def test_pending_user_is_redirected_to_account_status(self):
        user, profile = self.make_user("pending")
        profile.approval_state = ApprovalState.PENDING
        profile.save(update_fields=["approval_state"])
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertRedirects(response, reverse("account-status"))

    def test_approved_user_can_submit_and_view_job(self):
        user, profile = self.make_user("approved")
        profile.approval_state = ApprovalState.APPROVED
        profile.save(update_fields=["approval_state"])
        self.client.force_login(user)

        response = self.client.post(
            reverse("submit"),
            {
                "original_prompt": "Make a plot of the sample",
                "backend_profile": "rdf",
                "resolved_dataset": "",
            },
        )

        job = Job.objects.get(owner=user)
        self.assertRedirects(
            response, reverse("job-detail", kwargs={"submission_id": job.submission_id})
        )

        detail = self.client.get(reverse("job-detail", kwargs={"submission_id": job.submission_id}))
        self.assertContains(detail, "Status: <strong>queued</strong>", html=True)
        self.assertContains(detail, "Make a plot of the sample")
        self.assertContains(detail, "Generated code will appear here after the runner finishes.")
        status_partial = self.client.get(
            reverse("job-status", kwargs={"submission_id": job.submission_id})
        )
        self.assertContains(status_partial, "Status: <strong>queued</strong>", html=True)

    def test_approved_user_sees_job_history(self):
        user, profile = self.make_user("history")
        profile.approval_state = ApprovalState.APPROVED
        profile.save(update_fields=["approval_state"])
        Job.objects.create(owner=user, original_prompt="Plot", backend_profile="rdf")
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertContains(response, "Your jobs")
        self.assertContains(response, "queued")

    def test_staff_can_approve_and_reject_users(self):
        staff, _ = self.make_user("admin", is_staff=True)
        target, profile = self.make_user("target")
        self.client.force_login(staff)

        approve_response = self.client.post(reverse("approve-user", kwargs={"user_id": target.id}))
        self.assertRedirects(approve_response, reverse("admin-users"))

        profile.refresh_from_db()
        self.assertEqual(profile.approval_state, ApprovalState.APPROVED)

        reject_response = self.client.post(
            reverse("reject-user", kwargs={"user_id": target.id}),
            {"reason": "Not a fit"},
        )
        self.assertRedirects(reject_response, reverse("admin-users"))

        profile.refresh_from_db()
        self.assertEqual(profile.approval_state, ApprovalState.REJECTED)
        self.assertEqual(profile.rejection_reason, "Not a fit")

    def test_non_owner_cannot_view_job_detail(self):
        owner, profile = self.make_user("owner")
        profile.approval_state = ApprovalState.APPROVED
        profile.save(update_fields=["approval_state"])
        job = Job.objects.create(owner=owner, original_prompt="Plot", backend_profile="rdf")
        other, other_profile = self.make_user("other")
        other_profile.approval_state = ApprovalState.APPROVED
        other_profile.save(update_fields=["approval_state"])
        self.client.force_login(other)

        response = self.client.get(
            reverse("job-detail", kwargs={"submission_id": job.submission_id})
        )

        self.assertEqual(response.status_code, 403)

    def test_account_status_view_shows_state(self):
        user, profile = self.make_user("status")
        profile.approval_state = ApprovalState.REJECTED
        profile.rejection_reason = "Too vague"
        profile.save(update_fields=["approval_state", "rejection_reason"])
        self.client.force_login(user)

        response = self.client.get(reverse("account-status"))

        self.assertContains(response, "rejected")
        self.assertContains(response, "Your account was rejected.")
