from __future__ import annotations

import json
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from portal.models import Job, QueueMessageRecord

with suppress(ImportError):
    from azure.storage.queue import QueueServiceClient


AZURITE_QUEUE_API_VERSION = "2023-01-03"


@dataclass(frozen=True, slots=True)
class QueuePayload:
    job_id: str
    backend_profile: str

    def to_body(self) -> str:
        return json.dumps(
            {
                "backend_profile": self.backend_profile,
                "job_id": self.job_id,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_body(cls, body: str) -> QueuePayload:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive validation
            raise ValueError("Queue message is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("Queue message must decode to an object")

        expected_keys = {"job_id", "backend_profile"}
        if set(payload) != expected_keys:
            raise ValueError("Queue message must contain only job_id and backend_profile")

        job_id = payload["job_id"]
        backend_profile = payload["backend_profile"]
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("Queue message job_id must be a non-empty string")
        if not isinstance(backend_profile, str) or not backend_profile.strip():
            raise ValueError("Queue message backend_profile must be a non-empty string")

        return cls(job_id=job_id, backend_profile=backend_profile)


@dataclass(frozen=True, slots=True)
class QueueMessage:
    message_id: str
    pop_receipt: str
    body: str
    payload: QueuePayload
    dequeue_count: int


class QueueClient(Protocol):
    def enqueue_job(self, job_id: str, backend_profile: str) -> str: ...

    def receive_messages(
        self,
        max_messages: int = 1,
        visibility_timeout_seconds: int = 30,
    ) -> list[QueueMessage]: ...

    def delete_message(self, message: QueueMessage) -> None: ...

    def abandon_message(self, message: QueueMessage) -> None: ...


@dataclass(slots=True)
class _StoredMessage:
    message_id: str
    body: str
    payload: QueuePayload
    dequeue_count: int = 0
    visible_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    pop_receipt: str = ""


class InMemoryQueueClient:
    def __init__(self) -> None:
        self._messages: list[_StoredMessage] = []
        self._clock_offset = timedelta(0)

    def advance_time(self, seconds: float) -> None:
        self._clock_offset += timedelta(seconds=seconds)

    def _now(self) -> datetime:
        return datetime.now(UTC) + self._clock_offset

    def enqueue_job(self, job_id: str, backend_profile: str) -> str:
        payload = QueuePayload(job_id=job_id, backend_profile=backend_profile)
        message_id = uuid4().hex
        self._messages.append(
            _StoredMessage(
                message_id=message_id,
                body=payload.to_body(),
                payload=payload,
            )
        )
        return message_id

    def receive_messages(
        self,
        max_messages: int = 1,
        visibility_timeout_seconds: int = 30,
    ) -> list[QueueMessage]:
        if max_messages < 1:
            return []

        now = self._now()
        received: list[QueueMessage] = []
        for record in self._messages:
            if len(received) >= max_messages:
                break
            if record.visible_at > now:
                continue

            record.dequeue_count += 1
            record.pop_receipt = uuid4().hex
            record.visible_at = now + timedelta(seconds=visibility_timeout_seconds)
            received.append(
                QueueMessage(
                    message_id=record.message_id,
                    pop_receipt=record.pop_receipt,
                    body=record.body,
                    payload=record.payload,
                    dequeue_count=record.dequeue_count,
                )
            )
        return received

    def delete_message(self, message: QueueMessage) -> None:
        for index, record in enumerate(self._messages):
            same_message = record.message_id == message.message_id
            same_receipt = record.pop_receipt == message.pop_receipt
            if same_message and same_receipt:
                del self._messages[index]
                return
        raise KeyError("Queue message not found or receipt expired")

    def abandon_message(self, message: QueueMessage) -> None:
        for record in self._messages:
            same_message = record.message_id == message.message_id
            same_receipt = record.pop_receipt == message.pop_receipt
            if same_message and same_receipt:
                record.visible_at = self._now()
                return
        raise KeyError("Queue message not found or receipt expired")

    def snapshot(self) -> tuple[QueueMessage, ...]:
        messages: list[QueueMessage] = []
        for record in self._messages:
            messages.append(
                QueueMessage(
                    message_id=record.message_id,
                    pop_receipt=record.pop_receipt,
                    body=record.body,
                    payload=record.payload,
                    dequeue_count=record.dequeue_count,
                )
            )
        return tuple(messages)


class DatabaseQueueClient:
    def enqueue_job(self, job_id: str, backend_profile: str) -> str:
        payload = QueuePayload(job_id=job_id, backend_profile=backend_profile)
        job = Job.objects.get(submission_id=job_id)
        record = QueueMessageRecord.objects.create(
            job=job,
            backend_profile=backend_profile,
            body=payload.to_body(),
        )
        return record.message_id

    def receive_messages(
        self,
        max_messages: int = 1,
        visibility_timeout_seconds: int = 30,
    ) -> list[QueueMessage]:
        if max_messages < 1:
            return []

        now = timezone.now()
        received: list[QueueMessage] = []
        with transaction.atomic():
            candidates = list(
                QueueMessageRecord.objects.select_for_update()
                .filter(visible_at__lte=now)
                .order_by("created_at", "id")[:max_messages]
            )
            for record in candidates:
                record.dequeue_count += 1
                record.pop_receipt = uuid4().hex
                record.visible_at = now + timedelta(seconds=visibility_timeout_seconds)
                record.save(
                    update_fields=["dequeue_count", "pop_receipt", "visible_at"]
                )
                payload = QueuePayload.from_body(record.body)
                received.append(
                    QueueMessage(
                        message_id=record.message_id,
                        pop_receipt=record.pop_receipt,
                        body=record.body,
                        payload=payload,
                        dequeue_count=record.dequeue_count,
                    )
                )
        return received

    def delete_message(self, message: QueueMessage) -> None:
        deleted, _ = QueueMessageRecord.objects.filter(
            message_id=message.message_id,
            pop_receipt=message.pop_receipt,
        ).delete()
        if deleted == 0:
            raise KeyError("Queue message not found or receipt expired")

    def abandon_message(self, message: QueueMessage) -> None:
        updated = QueueMessageRecord.objects.filter(
            message_id=message.message_id,
            pop_receipt=message.pop_receipt,
        ).update(visible_at=timezone.now())
        if updated == 0:
            raise KeyError("Queue message not found or receipt expired")


class AzureQueueClient:
    def __init__(self, connection_string: str, queue_name: str) -> None:
        if "QueueServiceClient" not in globals():  # pragma: no cover - defensive
            raise RuntimeError("azure-storage-queue is not installed")
        self.queue_name = queue_name
        self._service_client = QueueServiceClient.from_connection_string(
            connection_string,
            api_version=AZURITE_QUEUE_API_VERSION,
        )
        self._queue_client = self._service_client.get_queue_client(queue_name)
        with suppress(Exception):
            self._queue_client.create_queue()

    def enqueue_job(self, job_id: str, backend_profile: str) -> str:
        payload = QueuePayload(job_id=job_id, backend_profile=backend_profile)
        job = Job.objects.get(submission_id=job_id)
        message = self._queue_client.send_message(payload.to_body())
        message_id = getattr(message, "id", None) or getattr(message, "message_id", None)
        if not message_id:
            raise RuntimeError("Azure queue did not return a message id")
        QueueMessageRecord.objects.create(
            job=job,
            backend_profile=backend_profile,
            body=payload.to_body(),
            message_id=message_id,
        )
        return message_id

    def receive_messages(
        self,
        max_messages: int = 1,
        visibility_timeout_seconds: int = 30,
    ) -> list[QueueMessage]:
        if max_messages < 1:
            return []

        received: list[QueueMessage] = []
        messages = self._queue_client.receive_messages(
            max_messages=max_messages,
            visibility_timeout=visibility_timeout_seconds,
        )
        with transaction.atomic():
            for message in messages:
                message_id = getattr(message, "id", None) or getattr(
                    message, "message_id", ""
                )
                body = getattr(message, "content", "")
                payload = QueuePayload.from_body(body)
                queue_record = QueueMessageRecord.objects.filter(
                    message_id=message_id,
                ).first()
                if queue_record is not None:
                    queue_record.dequeue_count = getattr(message, "dequeue_count", 0) or (
                        queue_record.dequeue_count + 1
                    )
                    queue_record.pop_receipt = getattr(message, "pop_receipt", "")
                    queue_record.visible_at = timezone.now() + timedelta(
                        seconds=visibility_timeout_seconds
                    )
                    queue_record.body = body
                    queue_record.backend_profile = payload.backend_profile
                    queue_record.save(
                        update_fields=[
                            "dequeue_count",
                            "pop_receipt",
                            "visible_at",
                            "body",
                            "backend_profile",
                        ]
                    )
                received.append(
                    QueueMessage(
                        message_id=message_id,
                        pop_receipt=getattr(message, "pop_receipt", ""),
                        body=body,
                        payload=payload,
                        dequeue_count=getattr(message, "dequeue_count", 0) or 1,
                    )
                )
        return received

    def delete_message(self, message: QueueMessage) -> None:
        self._queue_client.delete_message(message.message_id, message.pop_receipt)
        deleted, _ = QueueMessageRecord.objects.filter(
            message_id=message.message_id,
            pop_receipt=message.pop_receipt,
        ).delete()
        if deleted == 0:
            raise KeyError("Queue message not found or receipt expired")

    def abandon_message(self, message: QueueMessage) -> None:
        self._queue_client.update_message(
            message.message_id,
            pop_receipt=message.pop_receipt,
            visibility_timeout=0,
        )
        updated = QueueMessageRecord.objects.filter(
            message_id=message.message_id,
            pop_receipt=message.pop_receipt,
        ).update(visible_at=timezone.now())
        if updated == 0:
            raise KeyError("Queue message not found or receipt expired")


def get_queue_client() -> QueueClient:
    backend = getattr(settings, "QUEUE_BACKEND", "database")
    if backend == "memory":
        return InMemoryQueueClient()
    if backend == "azure":
        connection_string = (
            settings.QUEUE_CONNECTION_STRING
            or settings.AZURE_STORAGE_CONNECTION_STRING
            or "UseDevelopmentStorage=true"
        )
        return AzureQueueClient(connection_string, settings.QUEUE_NAME)
    return DatabaseQueueClient()
