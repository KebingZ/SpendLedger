from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spendledger.errors import NotFoundError, ValidationServiceError
from spendledger.models import (
    Account,
    EntryDirection,
    Journal,
    LedgerEntry,
    SpendTransaction,
)
from spendledger.schemas import JournalResponse, LedgerEntryResponse

EXPENSE_CLEARING = "employee_expense_clearing"
CARD_PAYABLE = "card_payable"


@dataclass(frozen=True)
class PostingLine:
    account_code: str
    direction: EntryDirection
    amount_minor: int


async def _accounts_by_code(
    session: AsyncSession,
    *,
    tenant_id: str,
    currency: str,
    codes: set[str],
) -> dict[str, Account]:
    rows = await session.scalars(
        select(Account).where(
            Account.tenant_id == tenant_id,
            Account.currency == currency,
            Account.code.in_(codes),
        )
    )
    accounts = {account.code: account for account in rows}
    missing = sorted(codes - set(accounts))
    if missing:
        raise ValidationServiceError(
            "ledger_accounts_missing",
            f"Required ledger accounts are missing for {currency}: {', '.join(missing)}.",
        )
    return accounts


async def post_journal(
    session: AsyncSession,
    *,
    tenant_id: str,
    transaction: SpendTransaction,
    reference: str,
    description: str,
    lines: list[PostingLine],
) -> Journal:
    debit_total = sum(line.amount_minor for line in lines if line.direction == EntryDirection.DEBIT)
    credit_total = sum(
        line.amount_minor for line in lines if line.direction == EntryDirection.CREDIT
    )
    if debit_total <= 0 or debit_total != credit_total:
        raise ValidationServiceError(
            "unbalanced_journal",
            "A journal must contain equal positive debit and credit totals.",
        )

    accounts = await _accounts_by_code(
        session,
        tenant_id=tenant_id,
        currency=transaction.currency,
        codes={line.account_code for line in lines},
    )
    journal = Journal(
        tenant_id=tenant_id,
        transaction_id=transaction.id,
        reference=reference,
        description=description,
        currency=transaction.currency,
        total_debits_minor=debit_total,
        total_credits_minor=credit_total,
    )
    session.add(journal)
    await session.flush()
    session.add_all(
        [
            LedgerEntry(
                journal_id=journal.id,
                account_id=accounts[line.account_code].id,
                direction=line.direction,
                amount_minor=line.amount_minor,
            )
            for line in lines
        ]
    )
    return journal


async def post_capture(
    session: AsyncSession,
    *,
    tenant_id: str,
    transaction: SpendTransaction,
    event_id: str,
    amount_minor: int,
) -> Journal:
    return await post_journal(
        session,
        tenant_id=tenant_id,
        transaction=transaction,
        reference=f"capture:{event_id}",
        description=f"Card capture at {transaction.merchant_name}",
        lines=[
            PostingLine(EXPENSE_CLEARING, EntryDirection.DEBIT, amount_minor),
            PostingLine(CARD_PAYABLE, EntryDirection.CREDIT, amount_minor),
        ],
    )


async def post_refund(
    session: AsyncSession,
    *,
    tenant_id: str,
    transaction: SpendTransaction,
    event_id: str,
    amount_minor: int,
) -> Journal:
    return await post_journal(
        session,
        tenant_id=tenant_id,
        transaction=transaction,
        reference=f"refund:{event_id}",
        description=f"Card refund from {transaction.merchant_name}",
        lines=[
            PostingLine(CARD_PAYABLE, EntryDirection.DEBIT, amount_minor),
            PostingLine(EXPENSE_CLEARING, EntryDirection.CREDIT, amount_minor),
        ],
    )


async def get_journal_response(
    session: AsyncSession,
    *,
    tenant_id: str,
    reference: str,
) -> JournalResponse:
    journal = await session.scalar(
        select(Journal).where(
            Journal.tenant_id == tenant_id,
            Journal.reference == reference,
        )
    )
    if journal is None:
        raise NotFoundError("Journal")
    result = await session.execute(
        select(LedgerEntry, Account)
        .join(Account, Account.id == LedgerEntry.account_id)
        .where(LedgerEntry.journal_id == journal.id)
        .order_by(LedgerEntry.created_at, LedgerEntry.id)
    )
    entries = [
        LedgerEntryResponse(
            account_code=account.code,
            direction=entry.direction.value,
            amount_minor=entry.amount_minor,
        )
        for entry, account in result.all()
    ]
    return JournalResponse(
        id=journal.id,
        reference=journal.reference,
        description=journal.description,
        currency=journal.currency,
        total_debits_minor=journal.total_debits_minor,
        total_credits_minor=journal.total_credits_minor,
        entries=entries,
    )
