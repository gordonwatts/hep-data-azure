from __future__ import annotations

from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from portal.models import Job, QueueMessageRecord
from portal.queue import AzureQueueClient, InMemoryQueueClient, QueuePayload, get_queue_client


class FakeAzureQueueMessage:
    def __init__(
        self,
        *,
        message_id: str,
        pop_receipt: str,
        content: str,
        dequeue_count: int = 1,
    ) -> None:
        self.id = message_id
        self.pop_receipt = pop_receipt
        self.content = content
        self.dequeue_count = dequeue_count


class FakeAzureQueueClient:
    def __init__(self, messages: list[FakeAzureQueueMessage] | None = None) -> None:
        self.messages = list(messages or [])
        self.created = False
        self.sent_bodies: list[str] = []
        self.deleted_messages: list[tuple[str, str]] = []
        self.updated_messages: list[tuple[str, str, int]] = []
        self.receive_requests: list[tuple[int, int]] = []

    def create_queue(self) -> None:
        self.created = True

    def send_message(self, body: str):
        self.sent_bodies.append(body)
        return mock.Mock(
            id=(
                "azure-message-"
                f"{len(self.sent_bodies):02d}-"
                "0123456789abcdef0123456789abcdef"
            )
        )

    def receive_messages(self, max_messages: int = 1, visibility_timeout: int = 30):
        self.receive_requests.append((max_messages, visibility_timeout))
        return self.messages[:max_messages]

    def delete_message(self, message_id: str, pop_receipt: str) -> None:
        self.deleted_messages.append((message_id, pop_receipt))

    def update_message(
        self,
        message_id: str,
        *,
        pop_receipt: str,
        visibility_timeout: int,
    ) -> None:
        self.updated_messages.append((message_id, pop_receipt, visibility_timeout))


class FakeQueueServiceClient:
    def __init__(self, queue_client: FakeAzureQueueClient, connection_string: str, api_version):
        self.queue_client = queue_client
        self.connection_string = connection_string
        self.api_version = api_version
        self.queue_name = ""

    @classmethod
    def from_connection_string(cls, connection_string: str, api_version=None):
        queue_client = cls.queue_client
        return cls(
            queue_client=queue_client,
            connection_string=connection_string,
            api_version=api_version,
        )

    def get_queue_client(self, queue_name: str) -> FakeAzureQueueClient:
        self.queue_name = queue_name
        return self.queue_client


class AzureQueueClientTests(TestCase):
    def setUp(self):
        self.User = get_user_model()

    def test_azure_queue_client_tracks_queue_messages(self):
        user = self.User.objects.create_user(username="alice", password="secret")
        job = Job.objects.create(
            owner=user,
            original_prompt="Make a plot",
            backend_profile="rdf",
        )
        queue_client = FakeAzureQueueClient()
        FakeQueueServiceClient.queue_client = queue_client

        with mock.patch(
            "portal.queue.QueueServiceClient",
            FakeQueueServiceClient,
            create=True,
        ):
            client = AzureQueueClient("UseDevelopmentStorage=true", "plot-jobs")
            message_id = client.enqueue_job(str(job.submission_id), "rdf")

            self.assertTrue(queue_client.created)
            self.assertEqual(
                queue_client.sent_bodies,
                [
                    QueuePayload(
                        job_id=str(job.submission_id),
                        backend_profile="rdf",
                    ).to_body()
                ],
            )
            self.assertGreater(len(message_id), 32)
            record = QueueMessageRecord.objects.get(job=job)
            self.assertEqual(record.message_id, message_id)

            queue_client.messages = [
                FakeAzureQueueMessage(
                    message_id=message_id,
                    pop_receipt="receipt-1",
                    content=record.body,
                    dequeue_count=1,
                )
            ]
            received = client.receive_messages(max_messages=1, visibility_timeout_seconds=45)

            self.assertEqual(queue_client.receive_requests, [(1, 45)])
            self.assertEqual(len(received), 1)
            self.assertEqual(received[0].message_id, message_id)
            self.assertEqual(
                received[0].payload,
                QueuePayload(
                    job_id=str(job.submission_id),
                    backend_profile="rdf",
                ),
            )

            record.refresh_from_db()
            self.assertEqual(record.dequeue_count, 1)
            self.assertEqual(record.pop_receipt, "receipt-1")
            self.assertEqual(record.backend_profile, "rdf")

            client.abandon_message(received[0])
            self.assertEqual(queue_client.updated_messages, [(message_id, "receipt-1", 0)])

            client.delete_message(received[0])
            self.assertEqual(queue_client.deleted_messages, [(message_id, "receipt-1")])
            self.assertFalse(QueueMessageRecord.objects.filter(message_id=message_id).exists())


class QueueClientSelectionTests(TestCase):
    @override_settings(QUEUE_BACKEND="memory")
    def test_get_queue_client_returns_memory_backend(self):
        client = get_queue_client()

        self.assertIsInstance(client, InMemoryQueueClient)


def test_queue_payload_serialization_is_minimal():
    body = QueuePayload(job_id="job-123", backend_profile="servicex_awkward").to_body()

    assert body == '{"backend_profile":"servicex_awkward","job_id":"job-123"}'
    assert QueuePayload.from_body(body) == QueuePayload(
        job_id="job-123",
        backend_profile="servicex_awkward",
    )


@pytest.mark.parametrize(
    "body",
    [
        "{}",
        '{"job_id":"job-123"}',
        '{"job_id":"","backend_profile":"servicex_awkward"}',
        "not json",
    ],
)
def test_queue_payload_rejects_invalid_messages(body):
    with pytest.raises(ValueError):
        QueuePayload.from_body(body)


def test_in_memory_queue_supports_visibility_delete_and_abandon():
    client = InMemoryQueueClient()
    message_id = client.enqueue_job("job-123", "rdf")

    first_batch = client.receive_messages()
    assert len(first_batch) == 1
    assert first_batch[0].message_id == message_id
    assert first_batch[0].payload.backend_profile == "rdf"
    assert first_batch[0].body == '{"backend_profile":"rdf","job_id":"job-123"}'
    assert client.receive_messages() == []

    client.abandon_message(first_batch[0])
    second_batch = client.receive_messages()
    assert len(second_batch) == 1
    assert second_batch[0].dequeue_count == 2

    client.delete_message(second_batch[0])
    assert client.receive_messages() == []
