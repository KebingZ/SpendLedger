import {demoData} from "./demoData";
import type {
  CardEventForm,
  ConnectionSettings,
  DashboardData,
  ReconciliationException,
  Transaction,
} from "./types";

interface ConsoleOverview {
  generated_at: string;
  currency: string;
  total_captured_minor: number;
  reconciliation_match_rate: number | null;
  pending_outbox: number;
  spend_series: Array<{date: string; amount_minor: number}>;
  recent_transactions: Array<{
    external_transaction_id: string;
    merchant_name: string;
    card_label: string;
    currency: string;
    amount_minor: number;
    state: Transaction["state"];
    occurred_at: string;
    latest_journal_reference: string | null;
  }>;
  reconciliation_exceptions: Array<{
    external_transaction_id: string;
    status: ReconciliationException["status"];
    detail: string;
    settlement_amount_minor: number | null;
    internal_amount_minor: number | null;
    currency: string | null;
  }>;
  outbox_counts: DashboardData["outboxCounts"];
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
  }
}

async function request<T>(
  settings: ConnectionSettings,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${settings.apiUrl.replace(/\/$/, "")}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${settings.apiKey}`,
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}.`;
    try {
      const problem = (await response.json()) as {detail?: string};
      detail = problem.detail ?? detail;
    } catch {
      // Keep the stable fallback for non-JSON infrastructure errors.
    }
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

function liveTransaction(
  item: ConsoleOverview["recent_transactions"][number],
): Transaction {
  return {
    id: item.external_transaction_id,
    merchant: item.merchant_name,
    amount: item.amount_minor / 100,
    currency: item.currency,
    cardLabel: item.card_label,
    state: item.state,
    occurredAt: item.occurred_at,
    journalReference: item.latest_journal_reference,
    lifecycle: [],
    journal: [],
  };
}

export async function fetchOverview(
  settings: ConnectionSettings,
): Promise<DashboardData> {
  const overview = await request<ConsoleOverview>(settings, "/v1/console/overview");
  return {
    generatedAt: overview.generated_at,
    currency: overview.currency,
    totalCaptured: overview.total_captured_minor / 100,
    reconciliationMatch: overview.reconciliation_match_rate,
    pendingOutbox: overview.pending_outbox,
    apiP95: null,
    spendSeries: overview.spend_series.map((point) => ({
      label: new Date(`${point.date}T00:00:00`).toLocaleDateString("en-AU", {
        weekday: "short",
      }),
      amount: point.amount_minor / 100,
    })),
    transactions: overview.recent_transactions.map(liveTransaction),
    exceptions: overview.reconciliation_exceptions.map((item, index) => ({
      id: `live-exception-${index}`,
      timestamp: overview.generated_at,
      status: item.status,
      detail: item.detail,
      amount: (item.settlement_amount_minor ?? item.internal_amount_minor ?? 0) / 100,
      currency: item.currency ?? overview.currency,
      reference: item.external_transaction_id,
    })),
    services: [
      {
        name: "SpendLedger API",
        instances: 1,
        p95: null,
        errorRate: null,
        saturation: null,
        trend: [],
        status: "healthy",
      },
      {
        name: "PostgreSQL",
        instances: 1,
        p95: null,
        errorRate: null,
        saturation: null,
        trend: [],
        status: "healthy",
      },
      {
        name: "Outbox Processor",
        instances: 1,
        p95: null,
        errorRate: null,
        saturation: null,
        trend: [],
        status: overview.pending_outbox > 100 ? "warning" : "healthy",
      },
    ],
    outboxCounts: overview.outbox_counts,
  };
}

export async function submitCardEvent(
  settings: ConnectionSettings,
  form: CardEventForm,
): Promise<void> {
  await request(settings, "/v1/card-events", {
    method: "POST",
    headers: {
      "Idempotency-Key": `console-${crypto.randomUUID()}`,
    },
    body: JSON.stringify({
      event_id: form.eventId,
      transaction_id: form.transactionId,
      event_type: form.eventType,
      card_id: form.cardId,
      merchant_name: form.merchantName,
      amount_minor: Math.round(Number(form.amount) * 100),
      currency: form.currency,
      occurred_at: new Date().toISOString(),
    }),
  });
}

export function demoSnapshot(): DashboardData {
  return structuredClone(demoData);
}
