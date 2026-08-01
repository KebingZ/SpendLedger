from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.errors import NotFoundError
from spendledger.models import (
    AuditLog,
    ReconciliationItem,
    ReconciliationItemStatus,
    ReconciliationRun,
    SpendTransaction,
    TransactionState,
)
from spendledger.outbox import emit_event
from spendledger.schemas import (
    ReconciliationItemResponse,
    ReconciliationRequest,
    ReconciliationResponse,
)


def _item_response(item: ReconciliationItem) -> ReconciliationItemResponse:
    return ReconciliationItemResponse.model_validate(item)


async def reconcile(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor: str,
    request: ReconciliationRequest,
) -> ReconciliationResponse:
    transactions = list(
        await session.scalars(
            select(SpendTransaction).where(
                SpendTransaction.tenant_id == tenant_id,
                SpendTransaction.occurred_at >= request.window_start,
                SpendTransaction.occurred_at < request.window_end,
                SpendTransaction.state.in_(
                    [
                        TransactionState.CAPTURED,
                        TransactionState.PARTIALLY_REFUNDED,
                        TransactionState.REFUNDED,
                    ]
                ),
            )
        )
    )
    transaction_by_external_id = {
        transaction.external_transaction_id: transaction for transaction in transactions
    }
    run = ReconciliationRun(
        tenant_id=tenant_id,
        source=request.source,
        settlement_date=request.settlement_date,
        window_start=request.window_start,
        window_end=request.window_end,
    )
    session.add(run)
    await session.flush()

    items: list[ReconciliationItem] = []
    settlement_transaction_ids: set[str] = set()
    for line in request.lines:
        settlement_transaction_ids.add(line.transaction_id)
        transaction = transaction_by_external_id.get(line.transaction_id)
        if transaction is None:
            item = ReconciliationItem(
                run_id=run.id,
                external_line_id=line.line_id,
                external_transaction_id=line.transaction_id,
                status=ReconciliationItemStatus.MISSING_INTERNAL,
                settlement_amount_minor=line.amount_minor,
                internal_amount_minor=None,
                settlement_currency=line.currency,
                internal_currency=None,
                detail="Settlement line has no internal captured transaction.",
            )
        elif transaction.currency != line.currency:
            item = ReconciliationItem(
                run_id=run.id,
                external_line_id=line.line_id,
                external_transaction_id=line.transaction_id,
                status=ReconciliationItemStatus.CURRENCY_MISMATCH,
                settlement_amount_minor=line.amount_minor,
                internal_amount_minor=transaction.captured_amount_minor,
                settlement_currency=line.currency,
                internal_currency=transaction.currency,
                detail="Settlement and internal transaction currencies differ.",
            )
        elif transaction.captured_amount_minor != line.amount_minor:
            item = ReconciliationItem(
                run_id=run.id,
                external_line_id=line.line_id,
                external_transaction_id=line.transaction_id,
                status=ReconciliationItemStatus.AMOUNT_MISMATCH,
                settlement_amount_minor=line.amount_minor,
                internal_amount_minor=transaction.captured_amount_minor,
                settlement_currency=line.currency,
                internal_currency=transaction.currency,
                detail="Settlement and internal captured amounts differ.",
            )
        else:
            item = ReconciliationItem(
                run_id=run.id,
                external_line_id=line.line_id,
                external_transaction_id=line.transaction_id,
                status=ReconciliationItemStatus.MATCHED,
                settlement_amount_minor=line.amount_minor,
                internal_amount_minor=transaction.captured_amount_minor,
                settlement_currency=line.currency,
                internal_currency=transaction.currency,
                detail="Settlement line matches the internal captured transaction.",
            )
        items.append(item)

    for transaction in transactions:
        if transaction.external_transaction_id in settlement_transaction_ids:
            continue
        items.append(
            ReconciliationItem(
                run_id=run.id,
                external_line_id=None,
                external_transaction_id=transaction.external_transaction_id,
                status=ReconciliationItemStatus.MISSING_SETTLEMENT,
                settlement_amount_minor=None,
                internal_amount_minor=transaction.captured_amount_minor,
                settlement_currency=None,
                internal_currency=transaction.currency,
                detail="Internal captured transaction is missing from the settlement file.",
            )
        )

    session.add_all(items)
    run.total_lines = len(items)
    run.matched_lines = sum(item.status == ReconciliationItemStatus.MATCHED for item in items)
    run.exception_lines = run.total_lines - run.matched_lines
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor=actor,
            action="reconciliation.completed",
            resource_type="reconciliation_run",
            resource_id=run.id,
            details={
                "source": request.source,
                "total_lines": run.total_lines,
                "matched_lines": run.matched_lines,
                "exception_lines": run.exception_lines,
            },
        )
    )
    emit_event(
        session,
        tenant_id=tenant_id,
        aggregate_type="reconciliation_run",
        aggregate_id=run.id,
        event_type="spend.reconciliation.completed",
        payload={
            "run_id": run.id,
            "settlement_date": request.settlement_date.isoformat(),
            "matched_lines": run.matched_lines,
            "exception_lines": run.exception_lines,
        },
    )
    await session.flush()
    return ReconciliationResponse(
        id=run.id,
        source=run.source,
        settlement_date=run.settlement_date,
        window_start=run.window_start,
        window_end=run.window_end,
        total_lines=run.total_lines,
        matched_lines=run.matched_lines,
        exception_lines=run.exception_lines,
        items=[_item_response(item) for item in items],
    )


async def get_reconciliation(
    session: AsyncSession,
    *,
    tenant_id: str,
    run_id: str,
) -> ReconciliationResponse:
    run = await session.scalar(
        select(ReconciliationRun).where(
            ReconciliationRun.id == run_id,
            ReconciliationRun.tenant_id == tenant_id,
        )
    )
    if run is None:
        raise NotFoundError("Reconciliation run")
    items = list(
        await session.scalars(
            select(ReconciliationItem)
            .where(ReconciliationItem.run_id == run.id)
            .order_by(ReconciliationItem.id)
        )
    )
    return ReconciliationResponse(
        id=run.id,
        source=run.source,
        settlement_date=run.settlement_date,
        window_start=run.window_start,
        window_end=run.window_end,
        total_lines=run.total_lines,
        matched_lines=run.matched_lines,
        exception_lines=run.exception_lines,
        items=[_item_response(item) for item in items],
    )
