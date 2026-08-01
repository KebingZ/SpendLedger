from __future__ import annotations

from datetime import UTC, datetime

from tests.conftest import ApiFixture
from tests.test_card_events import event_payload


async def create_capture(
    api: ApiFixture,
    *,
    transaction_id: str,
    event_id: str,
    amount_minor: int,
    currency: str = "AUD",
) -> None:
    response = await api.client.post(
        "/v1/card-events",
        json=event_payload(
            event_id=event_id,
            event_type="capture",
            amount_minor=amount_minor,
            transaction_id=transaction_id,
            currency=currency,
        ),
        headers=api.headers(idempotency_key=f"idem-{event_id}"),
    )
    assert response.status_code == 201, response.text


async def test_reconciliation_classifies_financial_exceptions(api: ApiFixture) -> None:
    await create_capture(
        api,
        transaction_id="txn_match",
        event_id="evt_match",
        amount_minor=10_000,
    )
    await create_capture(
        api,
        transaction_id="txn_amount",
        event_id="evt_amount",
        amount_minor=20_000,
    )
    await create_capture(
        api,
        transaction_id="txn_currency",
        event_id="evt_currency",
        amount_minor=30_000,
        currency="AUD",
    )
    await create_capture(
        api,
        transaction_id="txn_missing_settlement",
        event_id="evt_missing_settlement",
        amount_minor=40_000,
    )

    payload = {
        "source": "visa-demo",
        "settlement_date": "2026-07-30",
        "window_start": datetime(2026, 7, 28, tzinfo=UTC).isoformat(),
        "window_end": datetime(2026, 7, 31, tzinfo=UTC).isoformat(),
        "lines": [
            {
                "line_id": "line_match",
                "transaction_id": "txn_match",
                "amount_minor": 10_000,
                "currency": "AUD",
            },
            {
                "line_id": "line_amount",
                "transaction_id": "txn_amount",
                "amount_minor": 19_000,
                "currency": "AUD",
            },
            {
                "line_id": "line_currency",
                "transaction_id": "txn_currency",
                "amount_minor": 30_000,
                "currency": "USD",
            },
            {
                "line_id": "line_missing_internal",
                "transaction_id": "txn_unknown",
                "amount_minor": 50_000,
                "currency": "AUD",
            },
        ],
    }
    response = await api.client.post(
        "/v1/reconciliations",
        json=payload,
        headers=api.headers(idempotency_key="idem-reconciliation-001"),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["total_lines"] == 5
    assert body["matched_lines"] == 1
    assert body["exception_lines"] == 4
    statuses = {item["external_transaction_id"]: item["status"] for item in body["items"]}
    assert statuses == {
        "txn_match": "matched",
        "txn_amount": "amount_mismatch",
        "txn_currency": "currency_mismatch",
        "txn_unknown": "missing_internal",
        "txn_missing_settlement": "missing_settlement",
    }

    replay = await api.client.post(
        "/v1/reconciliations",
        json=payload,
        headers=api.headers(idempotency_key="idem-reconciliation-001"),
    )
    assert replay.status_code == 201
    assert replay.headers["Idempotent-Replayed"] == "true"
    assert replay.json() == body

    read_back = await api.client.get(
        f"/v1/reconciliations/{body['id']}",
        headers=api.headers(),
    )
    assert read_back.status_code == 200
    assert read_back.json()["exception_lines"] == 4
