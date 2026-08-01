from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.errors import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    ValidationServiceError,
)
from spendledger.idempotency import canonical_hash
from spendledger.ledger import post_capture, post_refund
from spendledger.models import (
    AuditLog,
    CardEventType,
    ProcessorEvent,
    SpendTransaction,
    TransactionState,
)
from spendledger.outbox import emit_event
from spendledger.schemas import CardEventCommand


def _ensure_currency(transaction: SpendTransaction, currency: str) -> None:
    if transaction.currency != currency:
        raise ValidationServiceError(
            "currency_mismatch",
            f"Transaction currency is {transaction.currency}, not {currency}.",
        )


async def _find_existing_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    command: CardEventCommand,
    payload_hash: str,
) -> SpendTransaction | None:
    event = await session.scalar(
        select(ProcessorEvent).where(
            ProcessorEvent.tenant_id == tenant_id,
            ProcessorEvent.external_event_id == command.event_id,
        )
    )
    if event is None:
        return None
    if event.payload_hash != payload_hash:
        raise ConflictError(
            "processor_event_reused",
            "The processor event ID was already used with a different payload.",
        )
    transaction = await session.get(SpendTransaction, event.transaction_id)
    if transaction is None:
        raise RuntimeError("Processor event references a missing transaction")
    return transaction


async def process_card_event(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor: str,
    command: CardEventCommand,
) -> tuple[SpendTransaction, bool]:
    payload_hash = canonical_hash(command.model_dump(mode="json"))
    replay = await _find_existing_event(
        session,
        tenant_id=tenant_id,
        command=command,
        payload_hash=payload_hash,
    )
    if replay is not None:
        return replay, True

    transaction = await session.scalar(
        select(SpendTransaction)
        .where(
            SpendTransaction.tenant_id == tenant_id,
            SpendTransaction.external_transaction_id == command.transaction_id,
        )
        .with_for_update()
    )

    if transaction is None:
        if command.event_type not in {CardEventType.AUTHORIZATION, CardEventType.CAPTURE}:
            raise ValidationServiceError(
                "transaction_not_initialized",
                "A transaction must begin with an authorization or capture event.",
            )
        direct_capture = command.event_type == CardEventType.CAPTURE
        transaction = SpendTransaction(
            tenant_id=tenant_id,
            external_transaction_id=command.transaction_id,
            card_id=command.card_id,
            merchant_name=command.merchant_name,
            currency=command.currency,
            authorized_amount_minor=command.amount_minor,
            captured_amount_minor=command.amount_minor if direct_capture else 0,
            refunded_amount_minor=0,
            state=(TransactionState.CAPTURED if direct_capture else TransactionState.AUTHORIZED),
            occurred_at=command.occurred_at,
        )
        session.add(transaction)
        await session.flush()
        if direct_capture:
            await post_capture(
                session,
                tenant_id=tenant_id,
                transaction=transaction,
                event_id=command.event_id,
                amount_minor=command.amount_minor,
            )
    else:
        _ensure_currency(transaction, command.currency)
        if transaction.card_id != command.card_id:
            raise ConflictError(
                "card_mismatch",
                "The transaction ID is already associated with a different card.",
            )

        if command.event_type == CardEventType.AUTHORIZATION:
            raise InvalidTransitionError(
                current=transaction.state.value,
                event=command.event_type.value,
            )
        if command.event_type == CardEventType.CAPTURE:
            if transaction.state != TransactionState.AUTHORIZED:
                raise InvalidTransitionError(
                    current=transaction.state.value,
                    event=command.event_type.value,
                )
            if command.amount_minor > transaction.authorized_amount_minor:
                raise ValidationServiceError(
                    "capture_exceeds_authorization",
                    "The capture amount cannot exceed the authorized amount.",
                )
            transaction.captured_amount_minor = command.amount_minor
            transaction.state = TransactionState.CAPTURED
            await post_capture(
                session,
                tenant_id=tenant_id,
                transaction=transaction,
                event_id=command.event_id,
                amount_minor=command.amount_minor,
            )
        elif command.event_type == CardEventType.REFUND:
            if transaction.state not in {
                TransactionState.CAPTURED,
                TransactionState.PARTIALLY_REFUNDED,
            }:
                raise InvalidTransitionError(
                    current=transaction.state.value,
                    event=command.event_type.value,
                )
            new_refund_total = transaction.refunded_amount_minor + command.amount_minor
            if new_refund_total > transaction.captured_amount_minor:
                raise ValidationServiceError(
                    "refund_exceeds_capture",
                    "Cumulative refunds cannot exceed the captured amount.",
                )
            transaction.refunded_amount_minor = new_refund_total
            transaction.state = (
                TransactionState.REFUNDED
                if new_refund_total == transaction.captured_amount_minor
                else TransactionState.PARTIALLY_REFUNDED
            )
            await post_refund(
                session,
                tenant_id=tenant_id,
                transaction=transaction,
                event_id=command.event_id,
                amount_minor=command.amount_minor,
            )
        elif command.event_type == CardEventType.REVERSAL:
            if transaction.state != TransactionState.AUTHORIZED:
                raise InvalidTransitionError(
                    current=transaction.state.value,
                    event=command.event_type.value,
                )
            transaction.state = TransactionState.REVERSED

        transaction.version += 1

    processor_event = ProcessorEvent(
        tenant_id=tenant_id,
        transaction_id=transaction.id,
        external_event_id=command.event_id,
        event_type=command.event_type,
        payload_hash=payload_hash,
        occurred_at=command.occurred_at,
    )
    session.add(processor_event)
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor=actor,
            action=f"card_event.{command.event_type.value}",
            resource_type="spend_transaction",
            resource_id=transaction.external_transaction_id,
            details={
                "event_id": command.event_id,
                "amount_minor": command.amount_minor,
                "currency": command.currency,
                "resulting_state": transaction.state.value,
            },
        )
    )
    emit_event(
        session,
        tenant_id=tenant_id,
        aggregate_type="spend_transaction",
        aggregate_id=transaction.external_transaction_id,
        event_type=f"spend.transaction.{command.event_type.value}",
        payload={
            "event_id": command.event_id,
            "transaction_id": transaction.external_transaction_id,
            "state": transaction.state.value,
            "amount_minor": command.amount_minor,
            "currency": command.currency,
            "version": transaction.version,
        },
    )
    await session.flush()
    return transaction, False


async def get_transaction(
    session: AsyncSession,
    *,
    tenant_id: str,
    external_transaction_id: str,
) -> SpendTransaction:
    transaction = await session.scalar(
        select(SpendTransaction).where(
            SpendTransaction.tenant_id == tenant_id,
            SpendTransaction.external_transaction_id == external_transaction_id,
        )
    )
    if transaction is None:
        raise NotFoundError("Transaction")
    return transaction
