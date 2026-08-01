from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.models import (
    Journal,
    OutboxEvent,
    OutboxStatus,
    ReconciliationItem,
    ReconciliationItemStatus,
    ReconciliationRun,
    SpendTransaction,
    TransactionState,
)
from spendledger.schemas import (
    ConsoleExceptionResponse,
    ConsoleOutboxCount,
    ConsoleOverviewResponse,
    ConsoleSpendPoint,
    ConsoleTransactionResponse,
)


def _card_label(card_id: str) -> str:
    suffix = card_id[-4:] if len(card_id) >= 4 else card_id
    return f"•••• {suffix.upper()}"


def _transaction_amount(transaction: SpendTransaction) -> int:
    if transaction.captured_amount_minor > 0:
        return transaction.captured_amount_minor
    return transaction.authorized_amount_minor


async def get_console_overview(
    session: AsyncSession,
    *,
    tenant_id: str,
    currency: str = "AUD",
) -> ConsoleOverviewResponse:
    transactions = list(
        await session.scalars(
            select(SpendTransaction)
            .where(
                SpendTransaction.tenant_id == tenant_id,
                SpendTransaction.currency == currency,
            )
            .order_by(SpendTransaction.occurred_at.desc())
            .limit(1_000)
        )
    )
    recent = transactions[:8]
    transaction_ids = [transaction.id for transaction in recent]
    journal_reference_by_transaction: dict[str, str] = {}
    if transaction_ids:
        journal_rows = await session.execute(
            select(Journal.transaction_id, Journal.reference)
            .where(Journal.transaction_id.in_(transaction_ids))
            .order_by(Journal.posted_at.desc())
        )
        for transaction_id, reference in journal_rows:
            journal_reference_by_transaction.setdefault(transaction_id, reference)

    captured_states = {
        TransactionState.CAPTURED,
        TransactionState.PARTIALLY_REFUNDED,
        TransactionState.REFUNDED,
    }
    total_captured_minor = sum(
        transaction.captured_amount_minor
        for transaction in transactions
        if transaction.state in captured_states
    )

    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=6)
    daily_totals: defaultdict[date, int] = defaultdict(int)
    for transaction in transactions:
        occurred_date = transaction.occurred_at.date()
        if transaction.state in captured_states and occurred_date >= start_date:
            daily_totals[occurred_date] += transaction.captured_amount_minor
    spend_series = [
        ConsoleSpendPoint(
            date=start_date + timedelta(days=offset),
            amount_minor=daily_totals[start_date + timedelta(days=offset)],
        )
        for offset in range(7)
    ]

    latest_run = await session.scalar(
        select(ReconciliationRun)
        .where(ReconciliationRun.tenant_id == tenant_id)
        .order_by(ReconciliationRun.created_at.desc())
        .limit(1)
    )
    reconciliation_match_rate: float | None = None
    reconciliation_exceptions: list[ConsoleExceptionResponse] = []
    if latest_run is not None:
        if latest_run.total_lines > 0:
            reconciliation_match_rate = round(
                latest_run.matched_lines / latest_run.total_lines * 100,
                2,
            )
        exception_items = list(
            await session.scalars(
                select(ReconciliationItem)
                .where(
                    ReconciliationItem.run_id == latest_run.id,
                    ReconciliationItem.status != ReconciliationItemStatus.MATCHED,
                )
                .order_by(ReconciliationItem.id)
                .limit(8)
            )
        )
        reconciliation_exceptions = [
            ConsoleExceptionResponse(
                external_transaction_id=item.external_transaction_id,
                status=item.status,
                detail=item.detail,
                settlement_amount_minor=item.settlement_amount_minor,
                internal_amount_minor=item.internal_amount_minor,
                currency=item.settlement_currency or item.internal_currency,
            )
            for item in exception_items
        ]

    outbox_rows = list(
        (
            await session.execute(
                select(OutboxEvent.status, func.count(OutboxEvent.id))
                .where(OutboxEvent.tenant_id == tenant_id)
                .group_by(OutboxEvent.status)
            )
        ).all()
    )
    outbox_by_status = {status: count for status, count in outbox_rows}
    outbox_counts = [
        ConsoleOutboxCount(status=status, count=outbox_by_status.get(status, 0))
        for status in OutboxStatus
    ]

    return ConsoleOverviewResponse(
        generated_at=datetime.now(UTC),
        currency=currency,
        total_captured_minor=total_captured_minor,
        reconciliation_match_rate=reconciliation_match_rate,
        latest_reconciliation_id=latest_run.id if latest_run is not None else None,
        pending_outbox=outbox_by_status.get(OutboxStatus.PENDING, 0),
        outbox_counts=outbox_counts,
        spend_series=spend_series,
        recent_transactions=[
            ConsoleTransactionResponse(
                external_transaction_id=transaction.external_transaction_id,
                merchant_name=transaction.merchant_name,
                card_label=_card_label(transaction.card_id),
                currency=transaction.currency,
                amount_minor=_transaction_amount(transaction),
                state=transaction.state,
                occurred_at=transaction.occurred_at,
                latest_journal_reference=journal_reference_by_transaction.get(transaction.id),
            )
            for transaction in recent
        ],
        reconciliation_exceptions=reconciliation_exceptions,
    )
