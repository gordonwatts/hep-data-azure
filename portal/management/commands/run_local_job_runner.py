from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F

from portal.models import JobStatus, QueueMessageRecord
from portal.queue import QueuePayload, get_queue_client
from portal.runner import run_command_plot_job


class Command(BaseCommand):
    help = "Poll the local queue and execute queued plot jobs."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--poll-interval", type=float, default=1.0)
        parser.add_argument("--visibility-timeout", type=int, default=None)

    def _bump_retry_count(self, job):
        job.__class__.objects.filter(pk=job.pk).update(retry_count=F("retry_count") + 1)

    def handle(self, *args, **options):
        once = options["once"]
        poll_interval = options["poll_interval"]
        visibility_timeout = (
            options["visibility_timeout"] or settings.QUEUE_VISIBILITY_TIMEOUT_SECONDS
        )
        queue_client = get_queue_client()

        while True:
            messages = queue_client.receive_messages(
                max_messages=1,
                visibility_timeout_seconds=visibility_timeout,
            )
            if not messages:
                if once:
                    break
                time.sleep(poll_interval)
                continue

            message = messages[0]
            delete_message = False
            abandon_message = False
            try:
                payload = QueuePayload.from_body(message.body)
            except ValueError:
                delete_message = True
            else:
                queue_record = (
                    QueueMessageRecord.objects.filter(
                        message_id=message.message_id
                    ).first()
                )
                if queue_record is None:
                    delete_message = True
                else:
                    job = queue_record.job
                    if job.status in JobStatus.terminal_values():
                        delete_message = True
                    elif job.status != JobStatus.QUEUED:
                        abandon_message = True
                    else:
                        try:
                            result = run_command_plot_job(payload.job_id)
                        except Exception:
                            self._bump_retry_count(job)
                            abandon_message = True
                        else:
                            result.job.refresh_from_db()
                            if result.job.status in JobStatus.terminal_values():
                                delete_message = True
                            else:
                                self._bump_retry_count(result.job)
                                abandon_message = True

            if delete_message:
                queue_client.delete_message(message)
            elif abandon_message:
                queue_client.abandon_message(message)

            if once:
                break
