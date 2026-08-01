from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000").rstrip("/")
API_KEY = os.getenv("SPENDLEDGER_API_KEY", "")


def call(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(
        f"{BASE_URL}{path}",
        method=method,
        headers=headers,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
    )
    try:
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path} failed ({exc.code}): {body}") from exc


def card_event(
    *,
    suffix: str,
    transaction_id: str,
    event_type: str,
    amount_minor: int,
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "event_id": f"evt_{event_type}_{suffix}",
        "transaction_id": transaction_id,
        "event_type": event_type,
        "card_id": "card_demo",
        "merchant_name": "Melbourne Office Supplies",
        "amount_minor": amount_minor,
        "currency": "AUD",
        "occurred_at": occurred_at.isoformat(),
    }


def main() -> None:
    if not API_KEY:
        sys.exit("Set SPENDLEDGER_API_KEY to the key printed by scripts/seed_demo.py.")

    suffix = uuid4().hex[:10]
    transaction_id = f"txn_demo_{suffix}"
    occurred_at = datetime.now(UTC)
    authorization = card_event(
        suffix=suffix,
        transaction_id=transaction_id,
        event_type="authorization",
        amount_minor=12_990,
        occurred_at=occurred_at,
    )
    capture = card_event(
        suffix=suffix,
        transaction_id=transaction_id,
        event_type="capture",
        amount_minor=12_990,
        occurred_at=occurred_at + timedelta(seconds=1),
    )
    refund = card_event(
        suffix=suffix,
        transaction_id=transaction_id,
        event_type="refund",
        amount_minor=2_000,
        occurred_at=occurred_at + timedelta(seconds=2),
    )

    print("1. Authorize")
    print(
        json.dumps(
            call(
                "POST",
                "/v1/card-events",
                payload=authorization,
                idempotency_key=f"idem-auth-{suffix}",
            ),
            indent=2,
        )
    )
    print("2. Capture and post the double-entry journal")
    print(
        json.dumps(
            call(
                "POST", "/v1/card-events", payload=capture, idempotency_key=f"idem-capture-{suffix}"
            ),
            indent=2,
        )
    )
    print("3. Replay the capture safely")
    print(
        json.dumps(
            call(
                "POST", "/v1/card-events", payload=capture, idempotency_key=f"idem-capture-{suffix}"
            ),
            indent=2,
        )
    )
    print("4. Apply a partial refund")
    print(
        json.dumps(
            call(
                "POST", "/v1/card-events", payload=refund, idempotency_key=f"idem-refund-{suffix}"
            ),
            indent=2,
        )
    )
    print("5. Read the final transaction projection")
    print(json.dumps(call("GET", f"/v1/transactions/{transaction_id}"), indent=2))
    print("6. Read the immutable capture journal")
    print(json.dumps(call("GET", f"/v1/journals/capture:{capture['event_id']}"), indent=2))


if __name__ == "__main__":
    main()
