from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from spendledger.errors import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    ValidationServiceError,
)
from spendledger.ledger import (
    EXPENSE_CLEARING,
    PostingLine,
    get_journal_response,
    post_journal,
)
from spendledger.models import EntryDirection, SpendTransaction, TransactionState
from spendledger.reconciliation import get_reconciliation, reconcile
from spendledger.schemas import CardEventCommand, ReconciliationRequest
from spendledger.transactions import get_transaction, process_card_event
from tests.conftest import ApiFixture
from tests.test_card_events import event_payload


def command(
    *,
    event_id: str,
    event_type: str,
    transaction_id: str = "txn_domain",
    amount_minor: int = 1_000,
    currency: str = "AUD",
    card_id: str = "card_domain",
) -> CardEventCommand:
    payload = event_payload(
        event_id=event_id,
        event_type=event_type,
        amount_minor=amount_minor,
        transaction_id=transaction_id,
        currency=currency,
    )
    payload["card_id"] = card_id
    return CardEventCommand.model_validate(payload)


async def apply(api: ApiFixture, event: CardEventCommand) -> SpendTransaction:
    async with api.session_factory() as session:
        transaction, _ = await process_card_event(
            session,
            tenant_id=api.tenant_id,
            actor="domain-test",
            command=event,
        )
        await session.commit()
        return transaction


async def test_authorization_reversal_and_invalid_reauthorization(api: ApiFixture) -> None:
    await apply(api, command(event_id="evt_auth_domain", event_type="authorization"))
    reversed_transaction = await apply(
        api,
        command(event_id="evt_reverse_domain", event_type="reversal"),
    )
    assert reversed_transaction.state == TransactionState.REVERSED

    async with api.session_factory() as session:
        with pytest.raises(InvalidTransitionError):
            await process_card_event(
                session,
                tenant_id=api.tenant_id,
                actor="domain-test",
                command=command(
                    event_id="evt_auth_again",
                    event_type="authorization",
                ),
            )


async def test_capture_cannot_exceed_authorization(api: ApiFixture) -> None:
    await apply(
        api,
        command(
            event_id="evt_small_auth",
            event_type="authorization",
            amount_minor=500,
        ),
    )
    async with api.session_factory() as session:
        with pytest.raises(ValidationServiceError, match="authorized amount"):
            await process_card_event(
                session,
                tenant_id=api.tenant_id,
                actor="domain-test",
                command=command(
                    event_id="evt_large_capture",
                    event_type="capture",
                    amount_minor=600,
                ),
            )


async def test_card_and_currency_mismatch_are_rejected(api: ApiFixture) -> None:
    await apply(api, command(event_id="evt_card_auth", event_type="authorization"))
    async with api.session_factory() as session:
        with pytest.raises(ConflictError, match="different card"):
            await process_card_event(
                session,
                tenant_id=api.tenant_id,
                actor="domain-test",
                command=command(
                    event_id="evt_wrong_card",
                    event_type="capture",
                    card_id="another-card",
                ),
            )
        with pytest.raises(ValidationServiceError, match="currency"):
            await process_card_event(
                session,
                tenant_id=api.tenant_id,
                actor="domain-test",
                command=command(
                    event_id="evt_wrong_currency",
                    event_type="capture",
                    currency="USD",
                ),
            )


async def test_refund_cannot_start_transaction_or_exceed_capture(api: ApiFixture) -> None:
    async with api.session_factory() as session:
        with pytest.raises(ValidationServiceError, match="must begin"):
            await process_card_event(
                session,
                tenant_id=api.tenant_id,
                actor="domain-test",
                command=command(event_id="evt_orphan_refund", event_type="refund"),
            )

    await apply(
        api,
        command(
            event_id="evt_refund_capture",
            event_type="capture",
            amount_minor=1_000,
        ),
    )
    async with api.session_factory() as session:
        with pytest.raises(ValidationServiceError, match="Cumulative refunds"):
            await process_card_event(
                session,
                tenant_id=api.tenant_id,
                actor="domain-test",
                command=command(
                    event_id="evt_over_refund",
                    event_type="refund",
                    amount_minor=1_001,
                ),
            )


async def test_processor_event_conflicting_reuse_is_rejected(api: ApiFixture) -> None:
    original = command(event_id="evt_payload_reuse", event_type="capture")
    await apply(api, original)
    async with api.session_factory() as session:
        with pytest.raises(ConflictError, match="different payload"):
            await process_card_event(
                session,
                tenant_id=api.tenant_id,
                actor="domain-test",
                command=command(
                    event_id="evt_payload_reuse",
                    event_type="capture",
                    amount_minor=999,
                ),
            )


async def test_missing_resources_and_unbalanced_journal_are_rejected(
    api: ApiFixture,
) -> None:
    async with api.session_factory() as session:
        with pytest.raises(NotFoundError):
            await get_transaction(
                session,
                tenant_id=api.tenant_id,
                external_transaction_id="missing",
            )
        with pytest.raises(NotFoundError):
            await get_journal_response(
                session,
                tenant_id=api.tenant_id,
                reference="missing",
            )
        with pytest.raises(NotFoundError):
            await get_reconciliation(
                session,
                tenant_id=api.tenant_id,
                run_id="missing",
            )

    transaction = await apply(
        api,
        command(event_id="evt_unbalanced_capture", event_type="capture"),
    )
    async with api.session_factory() as session:
        with pytest.raises(ValidationServiceError, match="equal positive"):
            await post_journal(
                session,
                tenant_id=api.tenant_id,
                transaction=transaction,
                reference="bad:journal",
                description="Deliberately unbalanced",
                lines=[
                    PostingLine(EXPENSE_CLEARING, EntryDirection.DEBIT, 100),
                    PostingLine(EXPENSE_CLEARING, EntryDirection.CREDIT, 99),
                ],
            )


def test_reconciliation_schema_rejects_invalid_windows_and_duplicates() -> None:
    base = {
        "source": "test",
        "settlement_date": "2026-07-29",
        "window_start": datetime(2026, 7, 30, tzinfo=UTC).isoformat(),
        "window_end": datetime(2026, 7, 29, tzinfo=UTC).isoformat(),
        "lines": [
            {
                "line_id": "line-1",
                "transaction_id": "txn-1",
                "amount_minor": 100,
                "currency": "AUD",
            }
        ],
    }
    with pytest.raises(ValidationError, match="window_start"):
        ReconciliationRequest.model_validate(base)

    base["window_start"] = datetime(2026, 7, 28, tzinfo=UTC).isoformat()
    base["lines"] = [base["lines"][0], dict(base["lines"][0])]
    with pytest.raises(ValidationError, match="line_id"):
        ReconciliationRequest.model_validate(base)

    base["lines"][1]["line_id"] = "line-2"
    with pytest.raises(ValidationError, match="transaction_id"):
        ReconciliationRequest.model_validate(base)


async def test_reconciliation_service_covers_all_outcomes(api: ApiFixture) -> None:
    for transaction_id, amount_minor, currency in (
        ("txn_match", 100, "AUD"),
        ("txn_amount", 200, "AUD"),
        ("txn_currency", 300, "AUD"),
        ("txn_missing_settlement", 400, "AUD"),
    ):
        await apply(
            api,
            command(
                event_id=f"evt_{transaction_id}",
                event_type="capture",
                transaction_id=transaction_id,
                amount_minor=amount_minor,
                currency=currency,
                card_id=f"card_{transaction_id}",
            ),
        )

    request = ReconciliationRequest.model_validate(
        {
            "source": "test-settlement",
            "settlement_date": "2026-07-29",
            "window_start": "2026-07-28T00:00:00Z",
            "window_end": "2026-07-30T00:00:00Z",
            "lines": [
                {
                    "line_id": "line-match",
                    "transaction_id": "txn_match",
                    "amount_minor": 100,
                    "currency": "AUD",
                },
                {
                    "line_id": "line-amount",
                    "transaction_id": "txn_amount",
                    "amount_minor": 201,
                    "currency": "AUD",
                },
                {
                    "line_id": "line-currency",
                    "transaction_id": "txn_currency",
                    "amount_minor": 300,
                    "currency": "USD",
                },
                {
                    "line_id": "line-missing-internal",
                    "transaction_id": "txn_missing_internal",
                    "amount_minor": 500,
                    "currency": "AUD",
                },
            ],
        }
    )
    async with api.session_factory() as session:
        response = await reconcile(
            session,
            tenant_id=api.tenant_id,
            actor="domain-test",
            request=request,
        )
        await session.commit()
        run_id = response.id

    statuses = {item.status.value for item in response.items}
    assert statuses == {
        "matched",
        "amount_mismatch",
        "currency_mismatch",
        "missing_internal",
        "missing_settlement",
    }
    assert response.total_lines == 5
    assert response.matched_lines == 1
    assert response.exception_lines == 4

    async with api.session_factory() as session:
        persisted = await get_reconciliation(
            session,
            tenant_id=api.tenant_id,
            run_id=run_id,
        )
    assert persisted.id == response.id
    assert persisted.total_lines == response.total_lines
    assert persisted.matched_lines == response.matched_lines
    assert persisted.exception_lines == response.exception_lines
    assert {item.status.value for item in persisted.items} == statuses
