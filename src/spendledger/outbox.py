from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.models import OutboxEvent, OutboxStatus

Publisher = Callable[[OutboxEvent], Awaitable[None]]

logger = logging.getLogger(__name__)


def emit_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    event = OutboxEvent(
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    return event


async def claim_batch(
    session: AsyncSession,
    *,
    worker_id: str,
    limit: int,
    lock_timeout_seconds: int = 60,
    now: datetime | None = None,
) -> list[OutboxEvent]:
    current_time = now or datetime.now(UTC)
    stale_before = current_time - timedelta(seconds=lock_timeout_seconds)
    events = list(
        await session.scalars(
            select(OutboxEvent)
            .where(
                or_(
                    and_(
                        OutboxEvent.status == OutboxStatus.PENDING,
                        OutboxEvent.available_at <= current_time,
                    ),
                    and_(
                        OutboxEvent.status == OutboxStatus.PROCESSING,
                        OutboxEvent.locked_at <= stale_before,
                    ),
                )
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for event in events:
        event.status = OutboxStatus.PROCESSING
        event.locked_at = current_time
        event.locked_by = worker_id
    await session.flush()
    return events


async def mark_published(
    session: AsyncSession,
    *,
    event_id: str,
    now: datetime | None = None,
) -> None:
    event = await session.get(OutboxEvent, event_id, with_for_update=True)
    if event is None:
        return
    event.status = OutboxStatus.PUBLISHED
    event.published_at = now or datetime.now(UTC)
    event.locked_at = None
    event.locked_by = None
    event.last_error = None


async def mark_failed(
    session: AsyncSession,
    *,
    event_id: str,
    error: Exception,
    max_attempts: int,
    now: datetime | None = None,
) -> None:
    current_time = now or datetime.now(UTC)
    event = await session.get(OutboxEvent, event_id, with_for_update=True)
    if event is None:
        return
    event.attempts += 1
    event.last_error = str(error)[:2_000]
    event.locked_at = None
    event.locked_by = None
    if event.attempts >= max_attempts:
        event.status = OutboxStatus.DEAD
        return
    event.status = OutboxStatus.PENDING
    backoff_seconds = min(300, 2 ** max(0, event.attempts - 1))
    event.available_at = current_time + timedelta(seconds=backoff_seconds)


async def logging_publisher(event: OutboxEvent) -> None:
    logger.info(
        "domain_event_published",
        extra={
            "event_id": event.id,
            "event_type": event.event_type,
            "aggregate_id": event.aggregate_id,
        },
    )
    await asyncio.sleep(0)
