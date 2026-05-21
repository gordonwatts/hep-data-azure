from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from portal.models import ApprovalState, ArtifactKind, JobStatus, QueueMessageRecord
from portal.queue import DatabaseQueueClient, QueueMessage, QueuePayload
from portal.runner import (
    RunnerResult,
    build_codex_prompt,
    build_plot_driver_command,
    run_command_plot_job,
    run_fake_plot_job,
)
from portal.services import create_queued_job


class RunnerTests(TestCase):
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

    def _queue_message(
        self,
        message_id: str,
        *,
        body: str | None = None,
        job_id: str = "job-id",
        backend_profile: str = "rdf",
    ) -> QueueMessage:
        payload = QueuePayload(job_id=job_id, backend_profile=backend_profile)
        return QueueMessage(
            message_id=message_id,
            pop_receipt="receipt",
            body=body or payload.to_body(),
            payload=payload,
            dequeue_count=1,
        )

    @override_settings(QUEUE_BACKEND="database")
    def test_fake_runner_success_creates_artifacts_and_code_endpoint(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
            ):
                user = self._approved_user("runner-success")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot of the sample",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job

                result = run_fake_plot_job(str(job.submission_id))
                result.job.refresh_from_db()

                self.assertEqual(result.job.status, JobStatus.COMPLETED)
                self.assertGreaterEqual(result.job.artifacts.count(), 4)
                self.assertTrue(result.job.artifacts.filter(artifact_kind=ArtifactKind.SCRIPT).exists())

                self.client.force_login(user)
                code_response = self.client.get(
                    f"/jobs/{job.submission_id}/generated-code/",
                )
                self.assertIn(
                    "print(&#x27;hello from the fake plot runner&#x27;)",
                    code_response.content.decode("utf-8"),
                )
                self.assertTrue(result.work_dir.exists())
                self.assertTrue(result.prompt_path.exists())
                self.assertTrue(result.context_path.exists())
                self.assertEqual(
                    result.prompt_path.read_text(encoding="utf-8"),
                    build_codex_prompt(result.job),
                )
                context = json.loads(result.context_path.read_text(encoding="utf-8"))
                self.assertEqual(context["backend_profile"], "rdf")
                self.assertEqual(context["job_id"], str(job.submission_id))

    @override_settings(QUEUE_BACKEND="database")
    def test_fake_runner_failure_marks_job_failed_and_keeps_log(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
            ):
                user = self._approved_user("runner-fail")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job

                result = run_fake_plot_job(str(job.submission_id), fail=True)
                result.job.refresh_from_db()

                self.assertEqual(result.job.status, JobStatus.FAILED)
                self.assertIn("Simulated plot runner failure", result.job.failure_message)
                self.assertTrue(result.job.artifacts.filter(artifact_kind=ArtifactKind.LOG).exists())

    @override_settings(QUEUE_BACKEND="database")
    def test_local_job_runner_consumes_queue_and_deletes_message(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
            ):
                user = self._approved_user("runner-loop")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job

                call_command("run_local_job_runner", once=True, poll_interval=0, verbosity=0)

                job.refresh_from_db()
                self.assertEqual(job.status, JobStatus.COMPLETED)
                self.assertEqual(QueueMessageRecord.objects.count(), 0)
                self.assertGreaterEqual(job.artifacts.count(), 4)

    @override_settings(QUEUE_BACKEND="database")
    def test_local_job_runner_discards_invalid_payload(self):
        class StubQueueClient:
            def __init__(self, messages):
                self.messages = list(messages)
                self.deleted = []
                self.abandoned = []

            def receive_messages(self, max_messages=1, visibility_timeout_seconds=30):
                if not self.messages:
                    return []
                return [self.messages.pop(0)]

            def delete_message(self, message):
                self.deleted.append(message)

            def abandon_message(self, message):
                self.abandoned.append(message)

        invalid_message = self._queue_message(
            "invalid-message",
            body="{not-json",
        )
        queue_client = StubQueueClient([invalid_message])

        with mock.patch(
            "portal.management.commands.run_local_job_runner.get_queue_client",
            return_value=queue_client,
        ):
            call_command("run_local_job_runner", once=True, poll_interval=0, verbosity=0)

        self.assertEqual(queue_client.deleted, [invalid_message])
        self.assertEqual(queue_client.abandoned, [])

    @override_settings(QUEUE_BACKEND="database")
    def test_local_job_runner_discards_terminal_job_messages(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
            ):
                user = self._approved_user("runner-terminal")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job
                job.status = JobStatus.COMPLETED
                job.save(update_fields=["status"])

                call_command("run_local_job_runner", once=True, poll_interval=0, verbosity=0)

                job.refresh_from_db()
                self.assertEqual(job.status, JobStatus.COMPLETED)
                self.assertEqual(QueueMessageRecord.objects.count(), 0)

    @override_settings(QUEUE_BACKEND="database")
    def test_local_job_runner_retries_after_runner_failure(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
            ):
                user = self._approved_user("runner-retry")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job

                with mock.patch(
                    "portal.management.commands.run_local_job_runner.run_command_plot_job",
                    side_effect=RuntimeError("boom"),
                ):
                    call_command("run_local_job_runner", once=True, poll_interval=0, verbosity=0)

                job.refresh_from_db()
                self.assertEqual(job.status, JobStatus.QUEUED)
                self.assertEqual(job.retry_count, 1)
                self.assertEqual(QueueMessageRecord.objects.count(), 1)

                call_command("run_local_job_runner", once=True, poll_interval=0, verbosity=0)

                job.refresh_from_db()
                self.assertEqual(job.status, JobStatus.COMPLETED)
                self.assertEqual(job.retry_count, 1)
                self.assertEqual(QueueMessageRecord.objects.count(), 0)

    @override_settings(QUEUE_BACKEND="database")
    def test_build_plot_driver_command_uses_configured_driver(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
                PLOT_RUNNER_DRIVER="python -m portal.plot_driver",
            ):
                user = self._approved_user("runner-driver-command")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job
                work_dir = Path(artifact_dir) / "plot-runner" / str(job.submission_id)
                prompt_path = work_dir / "prompt.txt"
                context_path = work_dir / "context.json"

                command = build_plot_driver_command(job, work_dir, prompt_path, context_path)

                self.assertEqual(
                    command,
                    [
                        "python",
                        "-m",
                        "portal.plot_driver",
                        "--executor",
                        "fake",
                        "--job-id",
                        str(job.submission_id),
                        "--work-dir",
                        str(work_dir),
                        "--prompt-path",
                        str(prompt_path),
                        "--context-path",
                        str(context_path),
                    ],
                )

    @override_settings(QUEUE_BACKEND="database")
    def test_command_runner_success_records_artifacts(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
                PLOT_RUNNER_DRIVER="python -m portal.plot_driver",
            ):
                user = self._approved_user("runner-command-success")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job
                work_dir = Path(artifact_dir) / "plot-runner" / str(job.submission_id)

                def fake_run(command, cwd, env, capture_output, text, timeout, check):
                    Path(work_dir, "generated.py").write_text(
                        "print('from subprocess')\n",
                        encoding="utf-8",
                    )
                    Path(work_dir, "comments.md").write_text("notes\n", encoding="utf-8")
                    Path(work_dir, "plot.svg").write_text("<svg />\n", encoding="utf-8")
                    Path(work_dir, "run.log").write_text("driver log\n", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

                with mock.patch("portal.runner.subprocess.run", side_effect=fake_run):
                    result = run_command_plot_job(str(job.submission_id))

                result.job.refresh_from_db()
                self.assertEqual(result.job.status, JobStatus.COMPLETED)
                self.assertGreaterEqual(result.job.artifacts.count(), 4)
                self.assertTrue(result.work_dir.joinpath("generated.py").exists())
                self.assertTrue(result.work_dir.joinpath("run.log").exists())

    @override_settings(QUEUE_BACKEND="database")
    def test_command_runner_failure_marks_job_failed(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
                PLOT_RUNNER_DRIVER="python -m portal.plot_driver",
            ):
                user = self._approved_user("runner-command-fail")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job

                def fake_run(command, cwd, env, capture_output, text, timeout, check):
                    Path(cwd, "run.log").write_text("boom\n", encoding="utf-8")
                    return subprocess.CompletedProcess(command, 2, stdout="oops\n", stderr="bad\n")

                with mock.patch("portal.runner.subprocess.run", side_effect=fake_run):
                    result = run_command_plot_job(str(job.submission_id))

                result.job.refresh_from_db()
                self.assertEqual(result.job.status, JobStatus.FAILED)
                self.assertIn("exited with code 2", result.job.failure_message)
                self.assertTrue(result.job.artifacts.filter(artifact_kind=ArtifactKind.LOG).exists())

    @override_settings(QUEUE_BACKEND="database")
    def test_command_runner_timeout_marks_job_failed(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
                PLOT_DRIVER_EXECUTOR="fake",
                PLOT_RUNNER_DRIVER="python -m portal.plot_driver",
                PLOT_RUNNER_TIMEOUT_SECONDS=1,
            ):
                user = self._approved_user("runner-command-timeout")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job
                work_dir = Path(artifact_dir) / "plot-runner" / str(job.submission_id)

                def fake_run(command, cwd, env, capture_output, text, timeout, check):
                    Path(work_dir, "generated.py").write_text(
                        "print('partial')\n",
                        encoding="utf-8",
                    )
                    raise subprocess.TimeoutExpired(
                        command,
                        timeout,
                        output="partial\n",
                        stderr="still going\n",
                    )

                with mock.patch("portal.runner.subprocess.run", side_effect=fake_run):
                    result = run_command_plot_job(str(job.submission_id))

                result.job.refresh_from_db()
                self.assertEqual(result.job.status, JobStatus.FAILED)
                self.assertIn("timed out after 1s", result.job.failure_message)
                self.assertTrue(result.job.artifacts.filter(artifact_kind=ArtifactKind.SCRIPT).exists())

    @override_settings(QUEUE_BACKEND="database")
    def test_plot_runner_command_reports_workdir_paths(self):
        with self._artifact_root() as artifact_dir:
            with override_settings(
                ARTIFACT_STORAGE_ROOT=artifact_dir,
                PLOT_RUNNER_ROOT=Path(artifact_dir) / "plot-runner",
            ):
                user = self._approved_user("runner-command")
                queue_client = DatabaseQueueClient()
                job = create_queued_job(
                    owner=user,
                    original_prompt="Make a plot",
                    backend_profile="rdf",
                    queue_client=queue_client,
                ).job

                result = RunnerResult(
                    job=job,
                    artifact_refs=(),
                    work_dir=Path(artifact_dir) / "plot-runner" / str(job.submission_id),
                    prompt_path=Path(artifact_dir) / "prompt.txt",
                    context_path=Path(artifact_dir) / "context.json",
                )
                with mock.patch(
                    "portal.management.commands.plot_runner.run_command_plot_job",
                    return_value=result,
                ):
                    from io import StringIO

                    output = StringIO()
                    call_command(
                        "plot_runner",
                        job_id=str(job.submission_id),
                        stdout=output,
                        verbosity=0,
                    )

                self.assertIn("Processed", output.getvalue())
                self.assertIn("Work dir:", output.getvalue())
                self.assertIn("Prompt:", output.getvalue())
                self.assertIn("Context:", output.getvalue())
