from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from spendledger.database import Base


def uuid_string() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class AccountType(StrEnum):
    ASSET = "asset"
    LIABILITY = "liability"
    EXPENSE = "expense"
    REVENUE = "revenue"


class EntryDirection(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class TransactionState(StrEnum):
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    REVERSED = "reversed"


class CardEventType(StrEnum):
    AUTHORIZATION = "authorization"
    CAPTURE = "capture"
    REFUND = "refund"
    REVERSAL = "reversal"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    DEAD = "dead"


class ReconciliationItemStatus(StrEnum):
    MATCHED = "matched"
    MISSING_INTERNAL = "missing_internal"
    MISSING_SETTLEMENT = "missing_settlement"
    AMOUNT_MISMATCH = "amount_mismatch"
    CURRENCY_MISMATCH = "currency_mismatch"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "currency", name="uq_account_tenant_code_currency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, native_enum=False, length=20), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SpendTransaction(Base):
    __tablename__ = "spend_transactions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "external_transaction_id", name="uq_transaction_tenant_external"
        ),
        CheckConstraint(
            "authorized_amount_minor >= 0",
            name="ck_transaction_authorized_nonnegative",
        ),
        CheckConstraint("captured_amount_minor >= 0", name="ck_transaction_captured_nonnegative"),
        CheckConstraint("refunded_amount_minor >= 0", name="ck_transaction_refunded_nonnegative"),
        CheckConstraint(
            "refunded_amount_minor <= captured_amount_minor",
            name="ck_transaction_refund_not_over_capture",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_transaction_id: Mapped[str] = mapped_column(String(120), nullable=False)
    card_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    merchant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    authorized_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    captured_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refunded_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    state: Mapped[TransactionState] = mapped_column(
        Enum(TransactionState, native_enum=False, length=30), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class ProcessorEvent(Base):
    __tablename__ = "processor_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_event_id", name="uq_event_tenant_external"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("spend_transactions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[CardEventType] = mapped_column(
        Enum(CardEventType, native_enum=False, length=30), nullable=False
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Journal(Base):
    __tablename__ = "journals"
    __table_args__ = (
        UniqueConstraint("tenant_id", "reference", name="uq_journal_tenant_reference"),
        CheckConstraint("total_debits_minor > 0", name="ck_journal_debits_positive"),
        CheckConstraint("total_debits_minor = total_credits_minor", name="ck_journal_balanced"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[str] = mapped_column(
        ForeignKey("spend_transactions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reference: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    total_debits_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_credits_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="ck_ledger_entry_positive"),
        Index("ix_ledger_entry_account_posted", "account_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    journal_id: Mapped[str] = mapped_column(
        ForeignKey("journals.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    direction: Mapped[EntryDirection] = mapped_column(
        Enum(EntryDirection, native_enum=False, length=10), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "endpoint", "key", name="uq_idempotency_scope"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_ready", "status", "available_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(120), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[OutboxStatus] = mapped_column(
        Enum(OutboxStatus, native_enum=False, length=20),
        nullable=False,
        default=OutboxStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(100))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_lines: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_lines: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exception_lines: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReconciliationItem(Base):
    __tablename__ = "reconciliation_items"
    __table_args__ = (Index("ix_reconciliation_item_run_status", "run_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_line_id: Mapped[str | None] = mapped_column(String(120))
    external_transaction_id: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[ReconciliationItemStatus] = mapped_column(
        Enum(ReconciliationItemStatus, native_enum=False, length=30), nullable=False
    )
    settlement_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    internal_amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    settlement_currency: Mapped[str | None] = mapped_column(String(3))
    internal_currency: Mapped[str | None] = mapped_column(String(3))
    detail: Mapped[str] = mapped_column(String(400), nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_string)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(120), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
