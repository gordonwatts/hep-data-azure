from __future__ import annotations

import pytest

from portal.queue import InMemoryQueueClient, QueuePayload


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
