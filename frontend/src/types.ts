export type ViewName =
  | "overview"
  | "transactions"
  | "reconciliation"
  | "ledger"
  | "operations";

export type TransactionState =
  | "authorized"
  | "captured"
  | "partially_refunded"
  | "refunded"
  | "reversed";

export type EventType = "authorization" | "capture" | "refund" | "reversal";

export type ExceptionStatus =
  | "missing_internal"
  | "missing_settlement"
  | "amount_mismatch"
  | "currency_mismatch";

export interface SpendPoint {
  label: string;
  amount: number;
}

export interface LifecycleEvent {
  type: EventType;
  label: string;
  timestamp: string;
  amount: number;
  eventId: string;
}

export interface JournalLine {
  account: string;
  direction: "debit" | "credit";
  amount: number;
}

export interface Transaction {
  id: string;
  merchant: string;
  amount: number;
  currency: string;
  cardLabel: string;
  state: TransactionState;
  occurredAt: string;
  journalReference?: string | null;
  lifecycle: LifecycleEvent[];
  journal: JournalLine[];
}

export interface ReconciliationException {
  id: string;
  timestamp: string;
  status: ExceptionStatus;
  detail: string;
  amount: number;
  currency: string;
  reference: string;
}

export interface ServiceHealth {
  name: string;
  instances: number;
  p95: number | null;
  errorRate: number | null;
  saturation: number | null;
  trend: number[];
  status: "healthy" | "warning";
}

export interface OutboxCount {
  status: "pending" | "processing" | "published" | "dead";
  count: number;
}

export interface DashboardData {
  generatedAt: string;
  currency: string;
  totalCaptured: number;
  reconciliationMatch: number | null;
  pendingOutbox: number;
  apiP95: number | null;
  spendSeries: SpendPoint[];
  transactions: Transaction[];
  exceptions: ReconciliationException[];
  services: ServiceHealth[];
  outboxCounts: OutboxCount[];
}

export interface CardEventForm {
  eventType: EventType;
  transactionId: string;
  eventId: string;
  cardId: string;
  merchantName: string;
  amount: string;
  currency: string;
}

export interface ConnectionSettings {
  apiUrl: string;
  apiKey: string;
}
