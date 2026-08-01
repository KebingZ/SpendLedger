from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.config import get_settings
from spendledger.database import build_engine, build_session_factory
from spendledger.ledger import CARD_PAYABLE, EXPENSE_CLEARING
from spendledger.models import (
    Account,
    AccountType,
    CardEventType,
    ReconciliationRun,
    SpendTransaction,
    Tenant,
    TransactionState,
)
from spendledger.reconciliation import reconcile
from spendledger.schemas import CardEventCommand, ReconciliationRequest
from spendledger.security import create_api_key
from spendledger.transactions import process_card_event


@dataclass(frozen=True)
class SampleTransaction:
    transaction_id: str
    merchant: str
    card_id: str
    amount_minor: int
    state: TransactionState
    minutes_ago: int
    refund_minor: int = 0


SAMPLE_TRANSACTIONS = (
    SampleTransaction(
        "txn_seed_uber_001",
        "Uber Technologies",
        "card_seed_2048",
        3_427,
        TransactionState.CAPTURED,
        5,
    ),
    SampleTransaction(
        "txn_seed_woolworths_002",
        "Woolworths Group",
        "card_seed_7712",
        12_864,
        TransactionState.PARTIALLY_REFUNDED,
        12,
        2_995,
    ),
    SampleTransaction(
        "txn_seed_bp_003",
        "BP Australia",
        "card_seed_1094",
        7_500,
        TransactionState.AUTHORIZED,
        18,
    ),
    SampleTransaction(
        "txn_seed_amazon_004",
        "Amazon Australia",
        "card_seed_6281",
        19_999,
        TransactionState.CAPTURED,
        26,
    ),
    SampleTransaction(
        "txn_seed_qantas_005",
        "Qantas Airways",
        "card_seed_0518",
        42_130,
        TransactionState.CAPTURED,
        35,
    ),
    SampleTransaction(
        "txn_seed_canva_006",
        "Canva",
        "card_seed_1184",
        3_600,
        TransactionState.CAPTURED,
        44,
    ),
    SampleTransaction(
        "txn_seed_azure_007",
        "Microsoft Azure",
        "card_seed_6725",
        28_742,
        TransactionState.CAPTURED,
        58,
    ),
    SampleTransaction(
        "txn_seed_hotel_008",
        "The Langham Melbourne",
        "card_seed_3066",
        68_450,
        TransactionState.CAPTURED,
        73,
    ),
    SampleTransaction(
        "txn_seed_virgin_009",
        "Virgin Australia",
        "card_seed_2237",
        31_820,
        TransactionState.REFUNDED,
        89,
        31_820,
    ),
    SampleTransaction(
        "txn_seed_jbhifi_010",
        "JB Hi-Fi",
        "card_seed_9002",
        14_900,
        TransactionState.REVERSED,
        105,
    ),
    SampleTransaction(
        "txn_seed_aws_011",
        "AWS Asia Pacific",
        "card_seed_3471",
        52_684,
        TransactionState.CAPTURED,
        124,
    ),
    SampleTransaction(
        "txn_seed_davidjones_012",
        "David Jones",
        "card_seed_1846",
        21_995,
        TransactionState.PARTIALLY_REFUNDED,
        146,
        4_995,
    ),
)


def _event_plan(sample: SampleTransaction) -> list[tuple[CardEventType, int]]:
    if sample.state == TransactionState.AUTHORIZED:
        return [(CardEventType.AUTHORIZATION, sample.amount_minor)]
    if sample.state == TransactionState.REVERSED:
        return [
            (CardEventType.AUTHORIZATION, sample.amount_minor),
            (CardEventType.REVERSAL, sample.amount_minor),
        ]
    if sample.state == TransactionState.PARTIALLY_REFUNDED:
        return [
            (CardEventType.CAPTURE, sample.amount_minor),
            (CardEventType.REFUND, sample.refund_minor),
        ]
    if sample.state == TransactionState.REFUNDED:
        return [
            (CardEventType.CAPTURE, sample.amount_minor),
            (CardEventType.REFUND, sample.amount_minor),
        ]
    return [(CardEventType.CAPTURE, sample.amount_minor)]


async def seed_sample_transactions(session: AsyncSession, *, tenant_id: str) -> int:
    sample_ids = [sample.transaction_id for sample in SAMPLE_TRANSACTIONS]
    existing_ids = set(
        await session.scalars(
            select(SpendTransaction.external_transaction_id).where(
                SpendTransaction.tenant_id == tenant_id,
                SpendTransaction.external_transaction_id.in_(sample_ids),
            )
        )
    )
    base_time = datetime.now(UTC).replace(second=0, microsecond=0)
    created = 0
    for sample in SAMPLE_TRANSACTIONS:
        if sample.transaction_id in existing_ids:
            continue
        initial_time = base_time - timedelta(minutes=sample.minutes_ago)
        for event_index, (event_type, amount_minor) in enumerate(_event_plan(sample), start=1):
            command = CardEventCommand(
                event_id=f"evt_{sample.transaction_id}_{event_type.value}_{event_index}",
                transaction_id=sample.transaction_id,
                event_type=event_type,
                card_id=sample.card_id,
                merchant_name=sample.merchant,
                amount_minor=amount_minor,
                currency="AUD",
                occurred_at=initial_time + timedelta(minutes=event_index - 1),
            )
            await process_card_event(
                session,
                tenant_id=tenant_id,
                actor="portfolio-seed",
                command=command,
            )
        created += 1
    return created


async def seed_reconciliation(session: AsyncSession, *, tenant_id: str) -> bool:
    existing = await session.scalar(
        select(ReconciliationRun.id).where(
            ReconciliationRun.tenant_id == tenant_id,
            ReconciliationRun.source == "portfolio-seed",
        )
    )
    if existing is not None:
        return False
    now = datetime.now(UTC)
    request = ReconciliationRequest(
        source="portfolio-seed",
        settlement_date=now.date(),
        window_start=now - timedelta(days=1),
        window_end=now + timedelta(hours=1),
        lines=[
            {
                "line_id": "seed-line-matched",
                "transaction_id": "txn_seed_uber_001",
                "amount_minor": 3_427,
                "currency": "AUD",
            },
            {
                "line_id": "seed-line-amount-mismatch",
                "transaction_id": "txn_seed_amazon_004",
                "amount_minor": 20_499,
                "currency": "AUD",
            },
            {
                "line_id": "seed-line-currency-mismatch",
                "transaction_id": "txn_seed_qantas_005",
                "amount_minor": 42_130,
                "currency": "USD",
            },
            {
                "line_id": "seed-line-missing-internal",
                "transaction_id": "txn_processor_only_013",
                "amount_minor": 11_240,
                "currency": "AUD",
            },
        ],
    )
    await reconcile(
        session,
        tenant_id=tenant_id,
        actor="portfolio-seed",
        request=request,
    )
    return True


async def seed() -> None:
    settings = get_settings()
    engine = build_engine(settings)
    factory = build_session_factory(engine)
    async with factory() as session:
        tenant = await session.scalar(
            select(Tenant).where(Tenant.name == settings.seed_tenant_name)
        )
        if tenant is None:
            tenant = Tenant(name=settings.seed_tenant_name)
            session.add(tenant)
            await session.flush()

        for currency in ("AUD", "USD"):
            existing_codes = set(
                await session.scalars(
                    select(Account.code).where(
                        Account.tenant_id == tenant.id,
                        Account.currency == currency,
                    )
                )
            )
            accounts = [
                Account(
                    tenant_id=tenant.id,
                    code=EXPENSE_CLEARING,
                    name="Employee Expense Clearing",
                    account_type=AccountType.EXPENSE,
                    currency=currency,
                ),
                Account(
                    tenant_id=tenant.id,
                    code=CARD_PAYABLE,
                    name="Card Payable",
                    account_type=AccountType.LIABILITY,
                    currency=currency,
                ),
            ]
            session.add_all([account for account in accounts if account.code not in existing_codes])

        created_transactions = await seed_sample_transactions(session, tenant_id=tenant.id)
        created_reconciliation = await seed_reconciliation(session, tenant_id=tenant.id)

        _, raw_key = await create_api_key(
            session,
            settings=settings,
            tenant_id=tenant.id,
            name="demo-admin",
            scopes=[
                "spend:write",
                "spend:read",
                "ledger:read",
                "reconciliation:write",
                "reconciliation:read",
            ],
        )
        await session.commit()
    await engine.dispose()
    print(f"Sample transactions created: {created_transactions}")
    print(f"Sample reconciliation created: {created_reconciliation}")
    print("Demo API key (shown once):")
    print(raw_key)


if __name__ == "__main__":
    asyncio.run(seed())
