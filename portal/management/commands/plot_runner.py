from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from portal.runner import run_fake_plot_job
from portal.services import JobNotClaimableError, SingleActiveJobError


class Command(BaseCommand):
    help = "Run the fake local plot runner for a single job."

    def add_arguments(self, parser):
        parser.add_argument("--job-id", required=True)
        parser.add_argument("--fail", action="store_true")

    def handle(self, *args, **options):
        job_id = options["job_id"]
        fail = options["fail"]
        try:
            result = run_fake_plot_job(job_id, fail=fail)
        except (JobNotClaimableError, SingleActiveJobError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {result.job.submission_id} -> {result.job.status}"
            )
        )
