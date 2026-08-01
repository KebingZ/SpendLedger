from __future__ import annotations

from sqlalchemy import select

from spendledger.config import Settings
from spendledger.models import OutboxEvent, OutboxStatus
from spendledger.outbox import emit_event
from spendledger.worker import process_one_batch
from tests.conftest import ApiFixture


async def add_event(api: ApiFixture, aggregate_id: str) -> str:
    async with api.session_factory() as session:
        event = emit_event(
            session,
            tenant_id=api.tenant_id,
            aggregate_type="test",
            aggregate_id=aggregate_id,
            event_type="test.created",
            payload={"aggregate_id": aggregate_id},
        )
        await session.commit()
        return event.id


async def test_worker_publishes_claimed_batch(api: ApiFixture) -> None:
    event_id = await add_event(api, "aggregate-success")
    published: list[str] = []

    async def publisher(event: OutboxEvent) -> None:
        published.append(event.id)

    processed = await process_one_batch(
        api.session_factory,
        settings=Settings(),
        worker_id="test-worker",
        publisher=publisher,
    )
    assert processed == 1
    assert published == [event_id]

    async with api.session_factory() as session:
        event = await session.get(OutboxEvent, event_id)
        assert event is not None
        assert event.status == OutboxStatus.PUBLISHED

    empty = await process_one_batch(
        api.session_factory,
        settings=Settings(),
        worker_id="test-worker",
        publisher=publisher,
    )
    assert empty == 0


async def test_worker_retries_publisher_failure(api: ApiFixture) -> None:
    event_id = await add_event(api, "aggregate-failure")

    async def failing_publisher(event: OutboxEvent) -> None:
        raise RuntimeError(f"broker unavailable for {event.id}")

    processed = await process_one_batch(
        api.session_factory,
        settings=Settings(outbox_max_attempts=3),
        worker_id="test-worker",
        publisher=failing_publisher,
    )
    assert processed == 1

    async with api.session_factory() as session:
        event = await session.scalar(select(OutboxEvent).where(OutboxEvent.id == event_id))
        assert event is not None
        assert event.status == OutboxStatus.PENDING
        assert event.attempts == 1
        assert "broker unavailable" in (event.last_error or "")
