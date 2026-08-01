from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.errors import ConflictError
from spendledger.models import IdempotencyRecord


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def find_record(
    session: AsyncSession,
    *,
    tenant_id: str,
    endpoint: str,
    key: str,
) -> IdempotencyRecord | None:
    return cast(
        IdempotencyRecord | None,
        await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.endpoint == endpoint,
                IdempotencyRecord.key == key,
            )
        ),
    )


def validate_replay(record: IdempotencyRecord, request_hash: str) -> None:
    if record.request_hash != request_hash:
        raise ConflictError(
            "idempotency_key_reused",
            "The idempotency key was already used with a different request payload.",
        )


def store_record(
    session: AsyncSession,
    *,
    tenant_id: str,
    endpoint: str,
    key: str,
    request_hash: str,
    response_status: int,
    response_body: dict[str, Any],
) -> IdempotencyRecord:
    record = IdempotencyRecord(
        tenant_id=tenant_id,
        endpoint=endpoint,
        key=key,
        request_hash=request_hash,
        response_status=response_status,
        response_body=response_body,
    )
    session.add(record)
    return record
