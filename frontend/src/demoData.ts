import type {
  DashboardData,
  JournalLine,
  LifecycleEvent,
  Transaction,
  TransactionState,
} from "./types";

const now = new Date();

function minutesAgo(minutes: number): string {
  return new Date(now.getTime() - minutes * 60_000).toISOString();
}

function event(
  type: LifecycleEvent["type"],
  label: string,
  minutes: number,
  amount: number,
  suffix: string,
): LifecycleEvent {
  return {
    type,
    label,
    timestamp: minutesAgo(minutes),
    amount,
    eventId: `evt_${type}_${suffix}`,
  };
}

function journal(amount: number, reversed = false): JournalLine[] {
  return [
    {
      account: reversed ? "Card payable" : "Employee expense clearing",
      direction: "debit",
      amount,
    },
    {
      account: reversed ? "Employee expense clearing" : "Card payable",
      direction: "credit",
      amount,
    },
  ];
}

function transaction(
  id: string,
  merchant: string,
  amount: number,
  state: TransactionState,
  minutes: number,
  card: string,
  refundAmount = 29.95,
): Transaction {
  const suffix = id.slice(-5);
  const lifecycle: LifecycleEvent[] = [
    event("authorization", "Authorization approved", minutes + 3, amount, suffix),
  ];
  if (state === "reversed") {
    lifecycle.push(event("reversal", "Authorization reversed", minutes, amount, suffix));
  } else if (state !== "authorized") {
    lifecycle.push(event("capture", "Capture settled", minutes, amount, suffix));
  }
  if (state === "partially_refunded") {
    lifecycle.push(
      event("refund", "Partial refund posted", Math.max(1, minutes - 2), refundAmount, suffix),
    );
  } else if (state === "refunded") {
    lifecycle.push(
      event("refund", "Full refund posted", Math.max(1, minutes - 2), amount, suffix),
    );
  }
  const hasJournal = !["authorized", "reversed"].includes(state);
  return {
    id,
    merchant,
    amount,
    currency: "AUD",
    cardLabel: `•••• ${card}`,
    state,
    occurredAt: minutesAgo(minutes),
    journalReference: hasJournal ? `capture:evt_capture_${suffix}` : null,
    lifecycle,
    journal: hasJournal ? journal(amount) : [],
  };
}

export const demoData: DashboardData = {
  generatedAt: now.toISOString(),
  currency: "AUD",
  totalCaptured: 482_760,
  reconciliationMatch: 99.82,
  pendingOutbox: 12,
  apiP95: 86,
  spendSeries: [
    {label: "04:30", amount: 21_000},
    {label: "05:00", amount: 29_000},
    {label: "05:30", amount: 47_000},
    {label: "06:00", amount: 45_000},
    {label: "06:30", amount: 63_000},
    {label: "07:00", amount: 61_000},
    {label: "07:30", amount: 70_000},
    {label: "08:00", amount: 82_000},
    {label: "08:30", amount: 77_000},
    {label: "09:00", amount: 66_000},
    {label: "09:30", amount: 69_000},
    {label: "10:00", amount: 72_000},
    {label: "10:30", amount: 71_000},
  ],
  transactions: [
    transaction("txn_01JVT5CZ8Q4KX2S9Y6M1P3W2E", "Uber Technologies", 34.27, "captured", 2, "2048"),
    transaction(
      "txn_01JVT5BSP2F7H1Q8D4L9N7R3T6",
      "Woolworths Group",
      128.64,
      "partially_refunded",
      5,
      "7712",
    ),
    transaction("txn_01JVT5A1M6K3D9Z4X7Q8H2N5V1", "BP Australia", 75, "authorized", 8, "1094"),
    transaction("txn_01JVT59XJ8R2L6C3V5B7M0P4H9", "Amazon Australia", 199.99, "captured", 11, "6281"),
    transaction("txn_01JVT58D7T1N4H6E9Y3Q2R8K5L", "Coles Supermarkets", 85.16, "captured", 14, "4420"),
    transaction("txn_01JVT57QF3G9P8H1L4Z6X0M7B2", "Officeworks", 56.99, "authorized", 18, "9307"),
    transaction("txn_01JVT56M2A8F4K7C1Q9D3N6R5T", "Qantas Airways", 421.3, "captured", 24, "0518"),
    transaction("txn_01JVT55K8P2S6N9D4H7R1M3X0", "Atlassian", 164, "captured", 31, "8831"),
    transaction("txn_01JVT54A7E9N2C5K8M1P6R3X4Q", "Canva", 36, "captured", 38, "1184"),
    transaction("txn_01JVT53P4B8D1H6L9S2W5Y7K0M", "Microsoft Azure", 287.42, "captured", 43, "6725"),
    transaction("txn_01JVT52M9X3F7Q1C6N8R4T2V5A", "The Langham Melbourne", 684.5, "captured", 51, "3066"),
    transaction("txn_01JVT51R2K6A9D3H7M4P8S0W5B", "Bunnings Warehouse", 243.18, "captured", 58, "4519"),
    transaction("txn_01JVT50C8N1F5L2Q9T6X3Y7M4D", "Google Cloud", 412.76, "captured", 66, "7952"),
    transaction("txn_01JVT4ZK5P9B2G7R1V8C3N6A0H", "Virgin Australia", 318.2, "refunded", 74, "2237"),
    transaction("txn_01JVT4YH3M7D1K6Q9S2W5X8B4F", "JB Hi-Fi", 149, "reversed", 83, "9002"),
    transaction("txn_01JVT4XQ8A2N5F9L3R7T1V6C0P", "AWS Asia Pacific", 526.84, "captured", 92, "3471"),
    transaction("txn_01JVT4W6C1K8M3P7D2H9S5Y0R4", "DiDi Australia", 28.7, "captured", 104, "6358"),
    transaction("txn_01JVT4V9F2B6N1Q8X3A7L5M0K4", "David Jones", 219.95, "partially_refunded", 117, "1846", 49.95),
    transaction("txn_01JVT4T5R8D2H6P1C9K3W7X0M4", "Zoom Video", 32.99, "captured", 129, "7701"),
    transaction("txn_01JVT4S1N7A3F9L5Q2V8B6C0K4", "Australia Post", 18.45, "captured", 143, "5520"),
    transaction("txn_01JVT4R8K2M6D1P9H3X7S5V0A4", "Hilton Sydney", 742, "authorized", 158, "6093"),
    transaction("txn_01JVT4Q3C9F5N1R7A2L8W6M0B4", "Slack Technologies", 96, "captured", 176, "8214"),
    transaction("txn_01JVT4P7H1K8D3Q6T2X9V5A0M4", "Chemist Warehouse", 67.35, "captured", 194, "4380"),
    transaction("txn_01JVT4N2M6B9F1C8R3W7S5K0A4", "Adobe Systems", 79.99, "captured", 218, "9962"),
  ],
  exceptions: [
    {
      id: "exc_001",
      timestamp: minutesAgo(3),
      status: "amount_mismatch",
      detail: "Captured amount differs from settlement",
      amount: 125,
      currency: "AUD",
      reference: "txn_01JVT5BSP2F7H1Q8D4L9",
    },
    {
      id: "exc_002",
      timestamp: minutesAgo(6),
      status: "missing_settlement",
      detail: "No settlement record received",
      amount: 75,
      currency: "AUD",
      reference: "txn_01JVT5A1M6K3D9Z4X7Q8",
    },
    {
      id: "exc_003",
      timestamp: minutesAgo(9),
      status: "currency_mismatch",
      detail: "Internal AUD capture, settlement reported USD",
      amount: 199.99,
      currency: "AUD",
      reference: "txn_01JVT59XJ8R2L6C3V5B7",
    },
    {
      id: "exc_004",
      timestamp: minutesAgo(15),
      status: "missing_internal",
      detail: "Settlement line has no internal capture",
      amount: 56.99,
      currency: "AUD",
      reference: "txn_external_9835",
    },
    {
      id: "exc_005",
      timestamp: minutesAgo(21),
      status: "amount_mismatch",
      detail: "Settlement includes an unexpected surcharge",
      amount: 287.92,
      currency: "AUD",
      reference: "txn_01JVT53P4B8D1H6L9S2W5",
    },
    {
      id: "exc_006",
      timestamp: minutesAgo(28),
      status: "missing_settlement",
      detail: "Captured hotel transaction is absent from the batch",
      amount: 684.5,
      currency: "AUD",
      reference: "txn_01JVT52M9X3F7Q1C6N8R",
    },
    {
      id: "exc_007",
      timestamp: minutesAgo(36),
      status: "currency_mismatch",
      detail: "Internal AUD transaction settled as NZD",
      amount: 318.2,
      currency: "AUD",
      reference: "txn_01JVT4ZK5P9B2G7R1V8C",
    },
    {
      id: "exc_008",
      timestamp: minutesAgo(48),
      status: "missing_internal",
      detail: "Processor settlement reference is unknown",
      amount: 112.4,
      currency: "AUD",
      reference: "txn_external_11742",
    },
  ],
  services: [
    {
      name: "API Gateway",
      instances: 3,
      p95: 86,
      errorRate: 0.02,
      saturation: 28,
      trend: [34, 28, 31, 27, 35, 29, 32, 26, 30, 28],
      status: "healthy",
    },
    {
      name: "Card Service",
      instances: 4,
      p95: 92,
      errorRate: 0.03,
      saturation: 34,
      trend: [25, 31, 29, 36, 34, 30, 38, 32, 35, 33],
      status: "healthy",
    },
    {
      name: "Ledger Service",
      instances: 3,
      p95: 78,
      errorRate: 0.01,
      saturation: 26,
      trend: [20, 18, 24, 21, 23, 19, 22, 20, 24, 21],
      status: "healthy",
    },
    {
      name: "Reconciliation",
      instances: 2,
      p95: 110,
      errorRate: 0.04,
      saturation: 41,
      trend: [32, 35, 39, 37, 42, 40, 45, 43, 41, 44],
      status: "warning",
    },
    {
      name: "Outbox Processor",
      instances: 2,
      p95: 71,
      errorRate: 0.01,
      saturation: 18,
      trend: [16, 19, 17, 21, 18, 16, 20, 17, 19, 18],
      status: "healthy",
    },
  ],
  outboxCounts: [
    {status: "pending", count: 12},
    {status: "processing", count: 4},
    {status: "published", count: 18_429},
    {status: "dead", count: 0},
  ],
};

export function buildDemoTransaction(
  id: string,
  merchant: string,
  amount: number,
  state: TransactionState,
  cardId: string,
): Transaction {
  return transaction(id, merchant, amount, state, 0, cardId.slice(-4).padStart(4, "0"));
}
