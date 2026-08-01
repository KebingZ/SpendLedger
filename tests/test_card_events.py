from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from spendledger.models import (
    Journal,
    LedgerEntry,
    OutboxEvent,
    ProcessorEvent,
    SpendTransaction,
)
from tests.conftest import ApiFixture


def event_payload(
    *,
    event_id: str,
    event_type: str,
    amount_minor: int = 12_990,
    transaction_id: str = "txn_001",
    currency: str = "AUD",
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "transaction_id": transaction_id,
        "event_type": event_type,
        "card_id": "card_001",
        "merchant_name": "Melbourne Office Supplies",
        "amount_minor": amount_minor,
        "currency": currency,
        "occurred_at": datetime(2026, 7, 29, 0, 0, tzinfo=UTC).isoformat(),
    }


async def test_authorization_capture_and_refund_lifecycle(api: ApiFixture) -> None:
    authorization = await api.client.post(
        "/v1/card-events",
        json=event_payload(event_id="evt_auth_001", event_type="authorization"),
        headers=api.headers(idempotency_key="idem-auth-001"),
    )
    assert authorization.status_code == 201, authorization.text
    assert authorization.json()["state"] == "authorized"
    assert authorization.json()["captured_amount_minor"] == 0

    capture = await api.client.post(
        "/v1/card-events",
        json=event_payload(event_id="evt_capture_001", event_type="capture"),
        headers=api.headers(idempotency_key="idem-capture-001"),
    )
    assert capture.status_code == 201, capture.text
    assert capture.json()["state"] == "captured"
    assert capture.json()["version"] == 2

    partial_refund = await api.client.post(
        "/v1/card-events",
        json=event_payload(
            event_id="evt_refund_001",
            event_type="refund",
            amount_minor=2_990,
        ),
        headers=api.headers(idempotency_key="idem-refund-001"),
    )
    assert partial_refund.status_code == 201, partial_refund.text
    assert partial_refund.json()["state"] == "partially_refunded"
    assert partial_refund.json()["refunded_amount_minor"] == 2_990

    full_refund = await api.client.post(
        "/v1/card-events",
        json=event_payload(
            event_id="evt_refund_002",
            event_type="refund",
            amount_minor=10_000,
        ),
        headers=api.headers(idempotency_key="idem-refund-002"),
    )
    assert full_refund.status_code == 201, full_refund.text
    assert full_refund.json()["state"] == "refunded"
    assert full_refund.json()["refunded_amount_minor"] == 12_990

    invalid_refund = await api.client.post(
        "/v1/card-events",
        json=event_payload(
            event_id="evt_refund_003",
            event_type="refund",
            amount_minor=1,
        ),
        headers=api.headers(idempotency_key="idem-refund-003"),
    )
    assert invalid_refund.status_code == 422
    assert invalid_refund.json()["code"] == "invalid_transaction_transition"


async def test_capture_creates_balanced_immutable_journal(api: ApiFixture) -> None:
    response = await api.client.post(
        "/v1/card-events",
        json=event_payload(event_id="evt_capture_direct", event_type="capture"),
        headers=api.headers(idempotency_key="idem-capture-direct"),
    )
    assert response.status_code == 201, response.text

    journal = await api.client.get(
        "/v1/journals/capture:evt_capture_direct",
        headers=api.headers(),
    )
    assert journal.status_code == 200, journal.text
    body = journal.json()
    assert body["total_debits_minor"] == 12_990
    assert body["total_credits_minor"] == 12_990
    assert {
        (entry["account_code"], entry["direction"], entry["amount_minor"])
        for entry in body["entries"]
    } == {
        ("employee_expense_clearing", "debit", 12_990),
        ("card_payable", "credit", 12_990),
    }


async def test_idempotency_replays_response_without_duplicate_writes(api: ApiFixture) -> None:
    payload = event_payload(event_id="evt_idempotent", event_type="capture")
    first = await api.client.post(
        "/v1/card-events",
        json=payload,
        headers=api.headers(idempotency_key="idem-repeat-001"),
    )
    second = await api.client.post(
        "/v1/card-events",
        json=payload,
        headers=api.headers(idempotency_key="idem-repeat-001"),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json() == second.json()

    async with api.session_factory() as session:
        assert await session.scalar(select(func.count(SpendTransaction.id))) == 1
        assert await session.scalar(select(func.count(ProcessorEvent.id))) == 1
        assert await session.scalar(select(func.count(Journal.id))) == 1
        assert await session.scalar(select(func.count(LedgerEntry.id))) == 2
        assert await session.scalar(select(func.count(OutboxEvent.id))) == 1


async def test_idempotency_key_with_different_payload_is_rejected(api: ApiFixture) -> None:
    first = await api.client.post(
        "/v1/card-events",
        json=event_payload(event_id="evt_conflict_001", event_type="capture"),
        headers=api.headers(idempotency_key="idem-conflict-001"),
    )
    assert first.status_code == 201

    changed = await api.client.post(
        "/v1/card-events",
        json=event_payload(
            event_id="evt_conflict_002",
            event_type="capture",
            amount_minor=500,
        ),
        headers=api.headers(idempotency_key="idem-conflict-001"),
    )
    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_key_reused"


async def test_processor_event_id_is_a_second_idempotency_boundary(api: ApiFixture) -> None:
    payload = event_payload(event_id="evt_provider_repeat", event_type="capture")
    first = await api.client.post(
        "/v1/card-events",
        json=payload,
        headers=api.headers(idempotency_key="idem-provider-001"),
    )
    second = await api.client.post(
        "/v1/card-events",
        json=payload,
        headers=api.headers(idempotency_key="idem-provider-002"),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert second.headers["Idempotent-Replayed"] == "true"
    async with api.session_factory() as session:
        assert await session.scalar(select(func.count(ProcessorEvent.id))) == 1
        assert await session.scalar(select(func.count(OutboxEvent.id))) == 1


async def test_money_rejects_floating_point_amounts(api: ApiFixture) -> None:
    payload = event_payload(event_id="evt_float", event_type="capture")
    payload["amount_minor"] = 129.90
    response = await api.client.post(
        "/v1/card-events",
        json=payload,
        headers=api.headers(idempotency_key="idem-float-001"),
    )
    assert response.status_code == 422
    assert response.json()["code"] == "request_validation_failed"
