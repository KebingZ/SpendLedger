from __future__ import annotations

from spendledger.config import Settings
from spendledger.security import hash_api_key
from tests.conftest import ApiFixture, seed_tenant


async def test_health_and_metrics_are_public(api: ApiFixture) -> None:
    live = await api.client.get("/health/live")
    ready = await api.client.get("/health/ready")
    metrics = await api.client.get("/metrics")
    assert live.status_code == 200
    assert ready.status_code == 200
    assert metrics.status_code == 200
    assert "spendledger_http_requests_total" in metrics.text
    assert live.headers.get("x-request-id")

    supplied = await api.client.get(
        "/health/live",
        headers={"X-Request-ID": "caller-request-123"},
    )
    assert supplied.headers["x-request-id"] == "caller-request-123"

    await api.client.get(
        "/v1/transactions/sensitive-card-path",
        headers=api.headers(),
    )
    updated_metrics = await api.client.get("/metrics")
    assert "sensitive-card-path" not in updated_metrics.text
    assert "/v1/transactions/{external_transaction_id}" in updated_metrics.text


async def test_invalid_api_key_is_rejected(api: ApiFixture) -> None:
    response = await api.client.get(
        "/v1/transactions/txn_unknown",
        headers=api.headers(api_key="invalid"),
    )
    assert response.status_code == 401
    assert response.json()["code"] == "authentication_failed"


async def test_scope_is_enforced(api: ApiFixture) -> None:
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        auto_create_schema=True,
    )
    async with api.session_factory() as session:
        _, read_only_key = await seed_tenant(
            session,
            settings=settings,
            name="Read Only Tenant",
            scopes=["spend:read"],
        )
    response = await api.client.post(
        "/v1/card-events",
        json={
            "event_id": "evt_denied",
            "transaction_id": "txn_denied",
            "event_type": "capture",
            "card_id": "card_denied",
            "merchant_name": "Denied Merchant",
            "amount_minor": 100,
            "currency": "AUD",
            "occurred_at": "2026-07-29T00:00:00+00:00",
        },
        headers=api.headers(
            idempotency_key="idem-denied-001",
            api_key=read_only_key,
        ),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_api_keys_are_not_stored_as_plaintext() -> None:
    raw = "sl_live_secret-example"
    digest = hash_api_key(raw)
    assert raw not in digest
    assert len(digest) == 64
