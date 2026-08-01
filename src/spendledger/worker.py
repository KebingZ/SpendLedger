from __future__ import annotations

import asyncio
import signal
import socket
from collections.abc import Awaitable, Callable
from contextlib import suppress
from uuid import uuid4

import structlog

from spendledger.config import Settings, get_settings
from spendledger.database import SessionFactory, build_engine, build_session_factory
from spendledger.models import OutboxEvent
from spendledger.observability import configure_logging
from spendledger.outbox import (
    claim_batch,
    logging_publisher,
    mark_failed,
    mark_published,
)

logger = structlog.get_logger(__name__)
Publisher = Callable[[OutboxEvent], Awaitable[None]]


async def process_one_batch(
    factory: SessionFactory,
    *,
    settings: Settings,
    worker_id: str,
    publisher: Publisher = logging_publisher,
) -> int:
    async with factory() as session:
        events = await claim_batch(
            session,
            worker_id=worker_id,
            limit=settings.outbox_batch_size,
            lock_timeout_seconds=settings.outbox_lock_timeout_seconds,
        )
        await session.commit()

    for event in events:
        try:
            await publisher(event)
        except Exception as exc:
            async with factory() as session:
                await mark_failed(
                    session,
                    event_id=event.id,
                    error=exc,
                    max_attempts=settings.outbox_max_attempts,
                )
                await session.commit()
            logger.warning(
                "outbox_publish_failed",
                event_id=event.id,
                event_type=event.event_type,
                error=str(exc),
            )
        else:
            async with factory() as session:
                await mark_published(session, event_id=event.id)
                await session.commit()
    return len(events)


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    worker_id = f"{socket.gethostname()}-{uuid4().hex[:8]}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stop.set)

    logger.info("outbox_worker_started", worker_id=worker_id)
    try:
        while not stop.is_set():
            processed = await process_one_batch(
                factory,
                settings=settings,
                worker_id=worker_id,
            )
            if processed == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.outbox_poll_seconds)
                except TimeoutError:
                    pass
    finally:
        await engine.dispose()
        logger.info("outbox_worker_stopped", worker_id=worker_id)


if __name__ == "__main__":  # pragma: no cover - process entry point
    asyncio.run(run_worker())
