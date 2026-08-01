from __future__ import annotations

from datetime import UTC, datetime

from tests.conftest import ApiFixture
from tests.test_card_events import event_payload


async def test_console_overview_aggregates_live_tenant_data(api: ApiFixture) -> None:
    for event_id, transaction_id, amount_minor in (
        ("evt_console_1", "txn_console_1", 12_500),
        ("evt_console_2", "txn_console_2", 8_900),
    ):
        response = await api.client.post(
            "/v1/card-events",
            json=event_payload(
                event_id=event_id,
                event_type="capture",
                transaction_id=transaction_id,
                amount_minor=amount_minor,
            ),
            headers=api.headers(idempotency_key=f"idem-{event_id}"),
        )
        assert response.status_code == 201

    reconciliation = await api.client.post(
        "/v1/reconciliations",
        json={
            "source": "console-test",
            "settlement_date": "2026-07-29",
            "window_start": datetime(2026, 7, 28, tzinfo=UTC).isoformat(),
            "window_end": datetime(2026, 7, 30, tzinfo=UTC).isoformat(),
            "lines": [
                {
                    "line_id": "line-console-1",
                    "transaction_id": "txn_console_1",
                    "amount_minor": 12_500,
                    "currency": "AUD",
                },
                {
                    "line_id": "line-console-2",
                    "transaction_id": "txn_console_2",
                    "amount_minor": 9_000,
                    "currency": "AUD",
                },
            ],
        },
        headers=api.headers(idempotency_key="idem-console-reconciliation"),
    )
    assert reconciliation.status_code == 201

    response = await api.client.get(
        "/v1/console/overview",
        headers=api.headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["currency"] == "AUD"
    assert body["total_captured_minor"] == 21_400
    assert body["reconciliation_match_rate"] == 50.0
    assert body["pending_outbox"] == 3
    assert len(body["recent_transactions"]) == 2
    assert body["recent_transactions"][0]["card_label"].startswith("••••")
    assert body["recent_transactions"][0]["latest_journal_reference"]
    assert body["reconciliation_exceptions"][0]["status"] == "amount_mismatch"
    assert len(body["spend_series"]) == 7


async def test_console_cors_allows_local_frontend(api: ApiFixture) -> None:
    response = await api.client.options(
        "/v1/console/overview",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
