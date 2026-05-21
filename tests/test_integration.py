from __future__ import annotations

import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from portal.models import ApprovalState, Job, JobStatus, QueueMessageRecord


class IntegrationSmokeTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def _approved_user(self, username: str):
        user = self.User.objects.create_user(username=username, password="secret")
        profile = user.profile
        profile.approval_state = ApprovalState.APPROVED
        profile.save(update_fields=["approval_state"])
        return user

    def _artifact_root(self):
        return tempfile.TemporaryDirectory(dir=Path.cwd())

    @override_settings(QUEUE_BACKEND="database")
    def test_submit_runner_and_generated_code_flow(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
            ):
                user = self._approved_user("integration")
                self.client.force_login(user)

                submit_response = self.client.post(
                    "/submit/",
                    {
                        "original_prompt": "Make a plot of the sample",
                        "backend_profile": "rdf",
                        "resolved_dataset": "",
                    },
                )
                self.assertEqual(submit_response.status_code, 302)

                job = Job.objects.get(owner=user)
                call_command("run_local_job_runner", once=True, poll_interval=0, verbosity=0)

                job.refresh_from_db()
                self.assertEqual(job.status, JobStatus.COMPLETED)
                self.assertEqual(QueueMessageRecord.objects.count(), 0)
                self.assertGreaterEqual(job.artifacts.count(), 4)

                detail_response = self.client.get(f"/jobs/{job.submission_id}/")
                self.assertContains(
                    detail_response,
                    "Status: <strong>completed</strong>",
                    html=True,
                )
                self.assertContains(detail_response, "Generated code")

                code_response = self.client.get(
                    f"/jobs/{job.submission_id}/generated-code/"
                )
                self.assertContains(
                    code_response,
                    "hello from the local plot driver",
                )
