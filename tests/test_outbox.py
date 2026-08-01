from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from spendledger.models import OutboxEvent, OutboxStatus
from spendledger.outbox import claim_batch, mark_failed, mark_published
from tests.conftest import ApiFixture
from tests.test_card_events import event_payload


def aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def test_outbox_claim_publish_and_retry(api: ApiFixture) -> None:
    response = await api.client.post(
        "/v1/card-events",
        json=event_payload(event_id="evt_outbox", event_type="capture"),
        headers=api.headers(idempotency_key="idem-outbox-001"),
    )
    assert response.status_code == 201

    now = datetime.now(UTC)
    async with api.session_factory() as session:
        claimed = await claim_batch(
            session,
            worker_id="worker-a",
            limit=10,
            now=now,
        )
        assert len(claimed) == 1
        event_id = claimed[0].id
        assert claimed[0].status == OutboxStatus.PROCESSING
        await session.commit()

    async with api.session_factory() as session:
        await mark_failed(
            session,
            event_id=event_id,
            error=RuntimeError("temporary broker failure"),
            max_attempts=3,
            now=now,
        )
        await session.commit()

    async with api.session_factory() as session:
        event = await session.get(OutboxEvent, event_id)
        assert event is not None
        assert event.status == OutboxStatus.PENDING
        assert event.attempts == 1
        assert aware(event.available_at) > now

        too_early = await claim_batch(
            session,
            worker_id="worker-b",
            limit=10,
            now=now,
        )
        assert too_early == []

        event.available_at = now - timedelta(seconds=1)
        await session.commit()

    async with api.session_factory() as session:
        claimed_again = await claim_batch(
            session,
            worker_id="worker-b",
            limit=10,
            now=now,
        )
        assert len(claimed_again) == 1
        await session.commit()

    async with api.session_factory() as session:
        await mark_published(session, event_id=event_id, now=now)
        await session.commit()
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id))
        assert event is not None
        assert event.status == OutboxStatus.PUBLISHED
        assert event.published_at is not None
        assert aware(event.published_at) == now


async def test_outbox_enters_dead_letter_state(api: ApiFixture) -> None:
    response = await api.client.post(
        "/v1/card-events",
        json=event_payload(event_id="evt_dead", event_type="capture"),
        headers=api.headers(idempotency_key="idem-dead-001"),
    )
    assert response.status_code == 201

    async with api.session_factory() as session:
        event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == "txn_001")
        )
        assert event is not None
        event.status = OutboxStatus.PROCESSING
        event.attempts = 2
        await session.commit()
        event_id = event.id

    async with api.session_factory() as session:
        await mark_failed(
            session,
            event_id=event_id,
            error=RuntimeError("permanent failure"),
            max_attempts=3,
        )
        await session.commit()
        event = await session.get(OutboxEvent, event_id)
        assert event is not None
        assert event.status == OutboxStatus.DEAD
        assert event.attempts == 3


async def test_outbox_reclaims_stale_worker_lock(api: ApiFixture) -> None:
    response = await api.client.post(
        "/v1/card-events",
        json=event_payload(event_id="evt_stale", event_type="capture"),
        headers=api.headers(idempotency_key="idem-stale-001"),
    )
    assert response.status_code == 201

    now = datetime.now(UTC)
    async with api.session_factory() as session:
        event = await session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == "txn_001")
        )
        assert event is not None
        event.status = OutboxStatus.PROCESSING
        event.locked_by = "crashed-worker"
        event.locked_at = now - timedelta(minutes=2)
        await session.commit()
        event_id = event.id

    async with api.session_factory() as session:
        reclaimed = await claim_batch(
            session,
            worker_id="replacement-worker",
            limit=10,
            lock_timeout_seconds=60,
            now=now,
        )
        assert [event.id for event in reclaimed] == [event_id]
        assert reclaimed[0].locked_by == "replacement-worker"
