from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from spendledger.models import (
    CardEventType,
    OutboxStatus,
    ReconciliationItemStatus,
    TransactionState,
)

Currency = Annotated[str, StringConstraints(min_length=3, max_length=3, to_upper=True)]


class CardEventCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=3, max_length=120)
    transaction_id: str = Field(min_length=3, max_length=120)
    event_type: CardEventType
    card_id: str = Field(min_length=3, max_length=120)
    merchant_name: str = Field(min_length=1, max_length=200)
    amount_minor: int = Field(strict=True, gt=0)
    currency: Currency
    occurred_at: datetime

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("occurred_at must include a timezone")
        return value


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    external_transaction_id: str
    card_id: str
    merchant_name: str
    currency: str
    authorized_amount_minor: int
    captured_amount_minor: int
    refunded_amount_minor: int
    state: TransactionState
    version: int
    occurred_at: datetime
    created_at: datetime
    updated_at: datetime


class SettlementLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str = Field(min_length=1, max_length=120)
    transaction_id: str = Field(min_length=3, max_length=120)
    amount_minor: int = Field(strict=True, gt=0)
    currency: Currency


class ReconciliationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=2, max_length=100)
    settlement_date: date
    window_start: datetime
    window_end: datetime
    lines: list[SettlementLineInput] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="after")
    def validate_window(self) -> ReconciliationRequest:
        if self.window_start.tzinfo is None or self.window_end.tzinfo is None:
            raise ValueError("reconciliation window timestamps must include a timezone")
        if self.window_start >= self.window_end:
            raise ValueError("window_start must be earlier than window_end")
        line_ids = [line.line_id for line in self.lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("line_id values must be unique within a reconciliation request")
        transaction_ids = [line.transaction_id for line in self.lines]
        if len(transaction_ids) != len(set(transaction_ids)):
            raise ValueError("transaction_id values must be unique within a reconciliation request")
        return self


class ReconciliationItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    external_line_id: str | None
    external_transaction_id: str
    status: ReconciliationItemStatus
    settlement_amount_minor: int | None
    internal_amount_minor: int | None
    settlement_currency: str | None
    internal_currency: str | None
    detail: str


class ReconciliationResponse(BaseModel):
    id: str
    source: str
    settlement_date: date
    window_start: datetime
    window_end: datetime
    total_lines: int
    matched_lines: int
    exception_lines: int
    items: list[ReconciliationItemResponse]


class LedgerEntryResponse(BaseModel):
    account_code: str
    direction: str
    amount_minor: int


class JournalResponse(BaseModel):
    id: str
    reference: str
    description: str
    currency: str
    total_debits_minor: int
    total_credits_minor: int
    entries: list[LedgerEntryResponse]


class ConsoleSpendPoint(BaseModel):
    date: date
    amount_minor: int


class ConsoleTransactionResponse(BaseModel):
    external_transaction_id: str
    merchant_name: str
    card_label: str
    currency: str
    amount_minor: int
    state: TransactionState
    occurred_at: datetime
    latest_journal_reference: str | None = None


class ConsoleExceptionResponse(BaseModel):
    external_transaction_id: str
    status: ReconciliationItemStatus
    detail: str
    settlement_amount_minor: int | None
    internal_amount_minor: int | None
    currency: str | None


class ConsoleOutboxCount(BaseModel):
    status: OutboxStatus
    count: int


class ConsoleOverviewResponse(BaseModel):
    generated_at: datetime
    currency: str
    total_captured_minor: int
    reconciliation_match_rate: float | None
    latest_reconciliation_id: str | None
    pending_outbox: int
    outbox_counts: list[ConsoleOutboxCount]
    spend_series: list[ConsoleSpendPoint]
    recent_transactions: list[ConsoleTransactionResponse]
    reconciliation_exceptions: list[ConsoleExceptionResponse]


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    code: str
    request_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
