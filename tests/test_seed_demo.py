from __future__ import annotations

from scripts.seed_demo import (
    SAMPLE_TRANSACTIONS,
    seed_reconciliation,
    seed_sample_transactions,
)
from sqlalchemy import func, select

from spendledger.models import ReconciliationRun, SpendTransaction, TransactionState
from tests.conftest import ApiFixture


async def test_portfolio_seed_is_rich_and_repeatable(api: ApiFixture) -> None:
    async with api.session_factory() as session:
        created = await seed_sample_transactions(session, tenant_id=api.tenant_id)
        reconciliation_created = await seed_reconciliation(
            session,
            tenant_id=api.tenant_id,
        )
        await session.commit()

    assert created == len(SAMPLE_TRANSACTIONS)
    assert reconciliation_created is True

    async with api.session_factory() as session:
        transaction_count = await session.scalar(
            select(func.count(SpendTransaction.id)).where(
                SpendTransaction.tenant_id == api.tenant_id
            )
        )
        states = set(
            await session.scalars(
                select(SpendTransaction.state).where(SpendTransaction.tenant_id == api.tenant_id)
            )
        )
        reconciliation_count = await session.scalar(
            select(func.count(ReconciliationRun.id)).where(
                ReconciliationRun.tenant_id == api.tenant_id
            )
        )
        repeated = await seed_sample_transactions(session, tenant_id=api.tenant_id)
        repeated_reconciliation = await seed_reconciliation(
            session,
            tenant_id=api.tenant_id,
        )

    assert transaction_count == len(SAMPLE_TRANSACTIONS)
    assert states == set(TransactionState)
    assert reconciliation_count == 1
    assert repeated == 0
    assert repeated_reconciliation is False
