import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Boxes,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock3,
  Copy,
  CreditCard,
  Database,
  LayoutDashboard,
  Menu,
  MoreVertical,
  Plus,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  SlidersHorizontal,
  WalletCards,
  Wrench,
  X,
} from "lucide-react";
import {useEffect, useMemo, useState} from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {demoSnapshot, fetchOverview, submitCardEvent} from "./api";
import {buildDemoTransaction} from "./demoData";
import type {
  CardEventForm,
  ConnectionSettings,
  DashboardData,
  ExceptionStatus,
  ServiceHealth,
  Transaction,
  TransactionState,
  ViewName,
} from "./types";

const navItems: Array<{
  id: ViewName;
  label: string;
  icon: typeof LayoutDashboard;
}> = [
  {id: "overview", label: "Overview", icon: LayoutDashboard},
  {id: "transactions", label: "Transactions", icon: CreditCard},
  {id: "reconciliation", label: "Reconciliation", icon: SlidersHorizontal},
  {id: "ledger", label: "Ledger", icon: Database},
  {id: "operations", label: "Operations", icon: Wrench},
];

const stateLabels: Record<TransactionState, string> = {
  authorized: "Authorized",
  captured: "Captured",
  partially_refunded: "Partially refunded",
  refunded: "Refunded",
  reversed: "Reversed",
};

const exceptionLabels: Record<ExceptionStatus, string> = {
  amount_mismatch: "Amount mismatch",
  currency_mismatch: "Currency mismatch",
  missing_internal: "Missing internal",
  missing_settlement: "Missing settlement",
};

function formatMoney(amount: number, currency = "AUD"): string {
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
  }).format(amount);
}

function formatCompactMoney(amount: number, currency = "AUD"): string {
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(amount);
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat("en-AU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function shortId(value: string): string {
  if (value.length <= 20) return value;
  return `${value.slice(0, 11)}…${value.slice(-6)}`;
}

function makeForm(): CardEventForm {
  const suffix = crypto.randomUUID().slice(0, 8);
  return {
    eventType: "capture",
    transactionId: `txn_console_${suffix}`,
    eventId: `evt_console_${suffix}`,
    cardId: "card_demo_2048",
    merchantName: "Melbourne Office Supplies",
    amount: "129.90",
    currency: "AUD",
  };
}

function Panel({
  title,
  eyebrow,
  action,
  children,
  className = "",
}: {
  title: string;
  eyebrow?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-header">
        <div>
          {eyebrow ? <span className="panel-eyebrow">{eyebrow}</span> : null}
          <h2>{title}</h2>
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

function MetricCard({
  label,
  value,
  detail,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "cyan" | "green" | "amber" | "blue";
  icon: typeof WalletCards;
}) {
  return (
    <article className={`metric-card metric-${tone}`}>
      <div>
        <span className="metric-label">{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
      <span className="metric-icon" aria-hidden="true">
        <Icon size={21} />
      </span>
    </article>
  );
}

function StatusPill({state}: {state: TransactionState}) {
  return <span className={`status-pill status-${state}`}>{stateLabels[state]}</span>;
}

function Sparkline({service}: {service: ServiceHealth}) {
  if (service.trend.length < 2) {
    return <span className="telemetry-empty">Live adapter required</span>;
  }
  const min = Math.min(...service.trend);
  const max = Math.max(...service.trend);
  const points = service.trend
    .map((value, index) => {
      const x = (index / (service.trend.length - 1)) * 90;
      const y = 25 - ((value - min) / Math.max(1, max - min)) * 18;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg className="sparkline" viewBox="0 0 90 30" aria-hidden="true">
      <polyline points={points} />
    </svg>
  );
}

function HealthTable({services}: {services: ServiceHealth[]}) {
  return (
    <div className="health-table" role="table" aria-label="Operational health">
      <div className="health-row health-head" role="row">
        <span>Service</span>
        <span>p95 latency</span>
        <span>Error rate</span>
        <span>Saturation</span>
      </div>
      {services.map((service) => (
        <div className="health-row" role="row" key={service.name}>
          <span className="service-name">
            <i className={`health-dot ${service.status}`} />
            <span>
              {service.name} <small>({service.instances})</small>
            </span>
          </span>
          <span className="latency-cell">
            <b>{service.p95 === null ? "—" : `${service.p95} ms`}</b>
            <Sparkline service={service} />
          </span>
          <span>{service.errorRate === null ? "—" : `${service.errorRate.toFixed(2)}%`}</span>
          <span className="saturation-cell">
            <span>{service.saturation === null ? "—" : `${service.saturation}%`}</span>
            <i>
              <em style={{width: `${service.saturation ?? 0}%`}} />
            </i>
          </span>
        </div>
      ))}
    </div>
  );
}

function TransactionsTable({
  transactions,
  onSelect,
  compact = false,
}: {
  transactions: Transaction[];
  onSelect: (transaction: Transaction) => void;
  compact?: boolean;
}) {
  return (
    <div className="table-scroll">
      <table className="data-table transactions-table">
        <thead>
          <tr>
            <th>Transaction ID</th>
            <th>Merchant</th>
            <th>Card</th>
            <th className="numeric">Amount</th>
            <th>Status</th>
            <th>Time (AEST)</th>
            <th aria-label="Open" />
          </tr>
        </thead>
        <tbody>
          {transactions.slice(0, compact ? 6 : undefined).map((transaction) => (
            <tr
              key={transaction.id}
              tabIndex={0}
              onClick={() => onSelect(transaction)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  onSelect(transaction);
                }
              }}
            >
              <td className="mono" title={transaction.id}>
                {shortId(transaction.id)}
              </td>
              <td className="merchant-cell">{transaction.merchant}</td>
              <td>{transaction.cardLabel}</td>
              <td className="numeric amount-cell">
                {formatMoney(transaction.amount, transaction.currency)}
              </td>
              <td>
                <StatusPill state={transaction.state} />
              </td>
              <td>{formatTime(transaction.occurredAt)}</td>
              <td>
                <ChevronRight size={16} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ExceptionsTable({
  exceptions,
  compact = false,
}: {
  exceptions: DashboardData["exceptions"];
  compact?: boolean;
}) {
  return (
    <div className="table-scroll">
      <table className="data-table exceptions-table">
        <thead>
          <tr>
            <th>Time (AEST)</th>
            <th>Type</th>
            <th>Details</th>
            <th className="numeric">Amount</th>
            <th>Reference</th>
          </tr>
        </thead>
        <tbody>
          {exceptions.slice(0, compact ? 5 : undefined).map((exception) => (
            <tr key={exception.id}>
              <td>
                <span className="exception-time">
                  <AlertTriangle size={15} />
                  {formatTime(exception.timestamp)}
                </span>
              </td>
              <td>
                <span className="exception-label">
                  {exceptionLabels[exception.status]}
                </span>
              </td>
              <td>{exception.detail}</td>
              <td className="numeric">{formatMoney(exception.amount, exception.currency)}</td>
              <td className="mono" title={exception.reference}>
                {shortId(exception.reference)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SpendChart({
  data,
  currency,
}: {
  data: DashboardData["spendSeries"];
  currency: string;
}) {
  const [range, setRange] = useState("6H");
  return (
    <>
      <div className="chart-toolbar">
        <div className="range-tabs" aria-label="Chart range">
          {["1H", "6H", "24H", "7D", "30D"].map((item) => (
            <button
              className={range === item ? "active" : ""}
              key={item}
              onClick={() => setRange(item)}
            >
              {item}
            </button>
          ))}
        </div>
        <div className="chart-legend">
          <i /> Captured ({currency})
          <strong>
            {formatCompactMoney(
              data.reduce((total, point) => total + point.amount, 0),
              currency,
            )}
          </strong>
        </div>
      </div>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data} margin={{top: 12, right: 8, bottom: 0, left: 0}}>
            <defs>
              <linearGradient id="spendGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#35c8e8" stopOpacity={0.34} />
                <stop offset="100%" stopColor="#35c8e8" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#24303d" strokeDasharray="3 5" vertical={false} />
            <XAxis
              dataKey="label"
              axisLine={false}
              tickLine={false}
              tick={{fill: "#718296", fontSize: 11}}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              tick={{fill: "#718296", fontSize: 11}}
              width={46}
              tickFormatter={(value: number) => `${Math.round(value / 1000)}K`}
            />
            <Tooltip
              cursor={{stroke: "#35c8e8", strokeDasharray: "3 3"}}
              formatter={(value) => [
                formatMoney(Number(value ?? 0), currency),
                "Captured",
              ]}
              contentStyle={{
                background: "#151e29",
                border: "1px solid #304052",
                borderRadius: 6,
                color: "#f2f6fa",
                fontSize: 12,
              }}
            />
            <Area
              type="monotone"
              dataKey="amount"
              stroke="#35c8e8"
              strokeWidth={2}
              fill="url(#spendGradient)"
              activeDot={{r: 4, fill: "#35c8e8", stroke: "#090d12", strokeWidth: 2}}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

function OverviewView({
  data,
  onSelectTransaction,
  onNavigate,
}: {
  data: DashboardData;
  onSelectTransaction: (transaction: Transaction) => void;
  onNavigate: (view: ViewName) => void;
}) {
  return (
    <>
      <div className="metric-grid">
        <MetricCard
          label="Total captured"
          value={formatCompactMoney(data.totalCaptured, data.currency)}
          detail="Gross captured volume"
          tone="cyan"
          icon={WalletCards}
        />
        <MetricCard
          label="Reconciliation match"
          value={
            data.reconciliationMatch === null
              ? "No run"
              : `${data.reconciliationMatch.toFixed(2)}%`
          }
          detail="Latest settlement window"
          tone="green"
          icon={CheckCircle2}
        />
        <MetricCard
          label="Pending outbox"
          value={data.pendingOutbox.toLocaleString("en-AU")}
          detail="Awaiting publication"
          tone="amber"
          icon={Boxes}
        />
        <MetricCard
          label="API p95"
          value={data.apiP95 === null ? "Adapter required" : `${data.apiP95} ms`}
          detail="Last five minutes"
          tone="blue"
          icon={Activity}
        />
      </div>

      <div className="overview-middle">
        <Panel
          title="Spend volume"
          action={
            <button className="icon-button" aria-label="Chart options">
              <MoreVertical size={17} />
            </button>
          }
        >
          <SpendChart data={data.spendSeries} currency={data.currency} />
        </Panel>
        <Panel
          title="Operational health"
          action={<span className="panel-caption">Last 60 minutes</span>}
        >
          <HealthTable services={data.services} />
        </Panel>
      </div>

      <div className="overview-bottom">
        <Panel
          title="Recent transactions"
          action={
            <button className="text-button" onClick={() => onNavigate("transactions")}>
              View all <ArrowUpRight size={14} />
            </button>
          }
        >
          <TransactionsTable
            transactions={data.transactions}
            onSelect={onSelectTransaction}
            compact
          />
        </Panel>
        <Panel
          title="Reconciliation exceptions"
          action={
            <button className="text-button" onClick={() => onNavigate("reconciliation")}>
              View all <ArrowUpRight size={14} />
            </button>
          }
        >
          <ExceptionsTable exceptions={data.exceptions} compact />
        </Panel>
      </div>
    </>
  );
}

function TransactionsView({
  data,
  onSelect,
}: {
  data: DashboardData;
  onSelect: (transaction: Transaction) => void;
}) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | TransactionState>("all");
  const filtered = data.transactions.filter((transaction) => {
    const matchesQuery = `${transaction.id} ${transaction.merchant}`
      .toLowerCase()
      .includes(query.toLowerCase());
    return matchesQuery && (filter === "all" || transaction.state === filter);
  });
  return (
    <Panel
      title="Transactions"
      eyebrow={`${filtered.length} records in current view`}
      className="workspace-panel"
      action={
        <button className="secondary-button">
          <RefreshCw size={15} /> Refresh
        </button>
      }
    >
      <div className="workspace-toolbar">
        <label className="search-field">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search transaction or merchant"
          />
        </label>
        <div className="filter-tabs">
          {(["all", "captured", "authorized", "partially_refunded"] as const).map(
            (state) => (
              <button
                key={state}
                className={filter === state ? "active" : ""}
                onClick={() => setFilter(state)}
              >
                {state === "all" ? "All" : stateLabels[state]}
              </button>
            ),
          )}
        </div>
      </div>
      <TransactionsTable transactions={filtered} onSelect={onSelect} />
    </Panel>
  );
}

function ReconciliationView({data}: {data: DashboardData}) {
  const matchRate = data.reconciliationMatch ?? 0;
  return (
    <>
      <div className="section-intro">
        <div>
          <span className="eyebrow">Settlement control</span>
          <h2>Reconciliation workspace</h2>
          <p>Investigate discrepancies without mutating the financial ledger.</p>
        </div>
        <button className="secondary-button">
          <RefreshCw size={15} /> Run reconciliation
        </button>
      </div>
      <div className="reconciliation-stats">
        <MetricCard
          label="Match rate"
          value={`${matchRate.toFixed(2)}%`}
          detail="Latest completed run"
          tone="green"
          icon={CheckCircle2}
        />
        <MetricCard
          label="Open exceptions"
          value={data.exceptions.length.toString()}
          detail="Require investigation"
          tone="amber"
          icon={AlertTriangle}
        />
        <MetricCard
          label="Control status"
          value="Within policy"
          detail="No aged critical items"
          tone="blue"
          icon={ShieldCheck}
        />
      </div>
      <div className="reconciliation-layout">
        <Panel title="Exception queue" eyebrow="Latest settlement window">
          <ExceptionsTable exceptions={data.exceptions} />
        </Panel>
        <Panel title="Control policy" eyebrow="Automated checks">
          <div className="policy-list">
            {[
              ["Transaction coverage", "All captured transactions evaluated", "healthy"],
              ["Amount tolerance", "Exact minor-unit match required", "healthy"],
              ["Currency validation", "Settlement and capture must agree", "healthy"],
              ["Exception ageing", "Escalate after one business day", "warning"],
            ].map(([title, description, status]) => (
              <div className="policy-item" key={title}>
                {status === "healthy" ? (
                  <CheckCircle2 size={18} />
                ) : (
                  <Clock3 size={18} />
                )}
                <div>
                  <strong>{title}</strong>
                  <span>{description}</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}

function LedgerView({
  data,
  onSelect,
}: {
  data: DashboardData;
  onSelect: (transaction: Transaction) => void;
}) {
  const transactionsWithJournal = data.transactions.filter(
    (transaction) => transaction.journal.length > 0 || transaction.journalReference,
  );
  const [activeId, setActiveId] = useState(transactionsWithJournal[0]?.id ?? "");
  const active =
    transactionsWithJournal.find((transaction) => transaction.id === activeId) ??
    transactionsWithJournal[0];
  return (
    <>
      <div className="section-intro">
        <div>
          <span className="eyebrow">Immutable accounting</span>
          <h2>Double-entry ledger</h2>
          <p>Every posted journal preserves balanced, append-only financial history.</p>
        </div>
        <span className="integrity-badge">
          <ShieldCheck size={16} /> Balance constraint active
        </span>
      </div>
      <div className="ledger-layout">
        <Panel title="Posted journals" className="journal-list-panel">
          <div className="journal-list">
            {transactionsWithJournal.map((transaction) => (
              <button
                key={transaction.id}
                className={active?.id === transaction.id ? "active" : ""}
                onClick={() => setActiveId(transaction.id)}
              >
                <span className="journal-icon">
                  <Database size={16} />
                </span>
                <span>
                  <strong>{transaction.merchant}</strong>
                  <small>{transaction.journalReference ?? "Journal available via API"}</small>
                </span>
                <b>{formatMoney(transaction.amount, transaction.currency)}</b>
              </button>
            ))}
          </div>
        </Panel>
        <Panel
          title={active ? `Journal · ${active.merchant}` : "Journal"}
          eyebrow={active?.journalReference ?? "Select a journal"}
          action={
            active ? (
              <button className="text-button" onClick={() => onSelect(active)}>
                Audit trail <ArrowUpRight size={14} />
              </button>
            ) : null
          }
        >
          {active ? (
            <div className="journal-detail">
              <div className="journal-meta">
                <div>
                  <span>Transaction</span>
                  <strong className="mono">{shortId(active.id)}</strong>
                </div>
                <div>
                  <span>Currency</span>
                  <strong>{active.currency}</strong>
                </div>
                <div>
                  <span>Posted</span>
                  <strong>{formatTime(active.occurredAt)}</strong>
                </div>
              </div>
              <table className="journal-table">
                <thead>
                  <tr>
                    <th>Account</th>
                    <th className="numeric">Debit</th>
                    <th className="numeric">Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {(active.journal.length
                    ? active.journal
                    : [
                        {
                          account: "Employee expense clearing",
                          direction: "debit" as const,
                          amount: active.amount,
                        },
                        {
                          account: "Card payable",
                          direction: "credit" as const,
                          amount: active.amount,
                        },
                      ]
                  ).map((line) => (
                    <tr key={`${line.account}-${line.direction}`}>
                      <td>{line.account}</td>
                      <td className="numeric">
                        {line.direction === "debit"
                          ? formatMoney(line.amount, active.currency)
                          : "—"}
                      </td>
                      <td className="numeric">
                        {line.direction === "credit"
                          ? formatMoney(line.amount, active.currency)
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th>Totals</th>
                    <th className="numeric">
                      {formatMoney(active.amount, active.currency)}
                    </th>
                    <th className="numeric">
                      {formatMoney(active.amount, active.currency)}
                    </th>
                  </tr>
                </tfoot>
              </table>
              <div className="balanced-callout">
                <CheckCircle2 size={17} />
                Debits equal credits. The database balance constraint is satisfied.
              </div>
            </div>
          ) : (
            <div className="empty-state">No posted journals are available.</div>
          )}
        </Panel>
      </div>
    </>
  );
}

function OperationsView({data, live}: {data: DashboardData; live: boolean}) {
  return (
    <>
      <div className="section-intro">
        <div>
          <span className="eyebrow">Runtime reliability</span>
          <h2>Operations</h2>
          <p>Service health, delivery backlog, and recovery semantics in one view.</p>
        </div>
        <span className={`environment-badge ${live ? "live" : ""}`}>
          <i /> {live ? "Live API" : "Synthetic telemetry"}
        </span>
      </div>
      <div className="operations-layout">
        <Panel title="Service health" eyebrow="Dependency overview">
          <HealthTable services={data.services} />
        </Panel>
        <Panel title="Outbox delivery" eyebrow="At-least-once semantics">
          <div className="outbox-grid">
            {data.outboxCounts.map((item) => (
              <article key={item.status} className={`outbox-card outbox-${item.status}`}>
                <span>{item.status}</span>
                <strong>{item.count.toLocaleString("en-AU")}</strong>
                <small>
                  {item.status === "pending" && "Ready for a worker"}
                  {item.status === "processing" && "Lease currently held"}
                  {item.status === "published" && "Delivered successfully"}
                  {item.status === "dead" && "Operator attention"}
                </small>
              </article>
            ))}
          </div>
        </Panel>
      </div>
      <div className="operations-cards">
        <article>
          <RefreshCw size={20} />
          <div>
            <strong>Exponential retry</strong>
            <span>Transient failures return to pending with bounded backoff.</span>
          </div>
        </article>
        <article>
          <Clock3 size={20} />
          <div>
            <strong>Lease recovery</strong>
            <span>Another worker reclaims events after a stale processing lease.</span>
          </div>
        </article>
        <article>
          <ShieldCheck size={20} />
          <div>
            <strong>Atomic hand-off</strong>
            <span>Business state and the outbox record commit together.</span>
          </div>
        </article>
      </div>
    </>
  );
}

function TransactionDrawer({
  transaction,
  onClose,
}: {
  transaction: Transaction | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  if (!transaction) return null;
  const copyId = async () => {
    await navigator.clipboard.writeText(transaction.id);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1_300);
  };
  return (
    <div className="drawer-layer" role="presentation" onMouseDown={onClose}>
      <aside
        className="drawer transaction-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Transaction details"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="drawer-header">
          <div>
            <span className="eyebrow">Transaction detail</span>
            <h2>{transaction.merchant}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close details">
            <X size={19} />
          </button>
        </header>
        <div className="drawer-body">
          <div className="transaction-hero">
            <div>
              <span>Amount</span>
              <strong>{formatMoney(transaction.amount, transaction.currency)}</strong>
            </div>
            <StatusPill state={transaction.state} />
          </div>
          <div className="detail-grid">
            <div>
              <span>Transaction ID</span>
              <button className="copy-value" onClick={copyId}>
                <b className="mono">{shortId(transaction.id)}</b>
                {copied ? <Check size={14} /> : <Copy size={14} />}
              </button>
            </div>
            <div>
              <span>Card</span>
              <b>{transaction.cardLabel}</b>
            </div>
            <div>
              <span>Occurred</span>
              <b>{formatTime(transaction.occurredAt)}</b>
            </div>
            <div>
              <span>Journal reference</span>
              <b className="mono">{transaction.journalReference ?? "Not posted"}</b>
            </div>
          </div>

          <section className="drawer-section">
            <h3>Lifecycle</h3>
            {transaction.lifecycle.length ? (
              <div className="timeline">
                {transaction.lifecycle.map((item) => (
                  <div className="timeline-item" key={item.eventId}>
                    <i />
                    <div>
                      <strong>{item.label}</strong>
                      <span>{formatTime(item.timestamp)}</span>
                      <small className="mono">{item.eventId}</small>
                    </div>
                    <b>{formatMoney(item.amount, transaction.currency)}</b>
                  </div>
                ))}
              </div>
            ) : (
              <div className="data-note">
                Lifecycle details are available when the processor-events adapter is
                enabled.
              </div>
            )}
          </section>

          <section className="drawer-section">
            <h3>Journal entries</h3>
            {transaction.journal.length ? (
              <div className="drawer-journal">
                {transaction.journal.map((line) => (
                  <div key={`${line.account}-${line.direction}`}>
                    <span>
                      <i className={line.direction} />
                      {line.account}
                    </span>
                    <b>
                      {line.direction === "debit" ? "DR" : "CR"}{" "}
                      {formatMoney(line.amount, transaction.currency)}
                    </b>
                  </div>
                ))}
              </div>
            ) : (
              <div className="data-note">
                {transaction.journalReference
                  ? `Fetch ${transaction.journalReference} from the ledger API.`
                  : "Authorizations do not create accounting entries."}
              </div>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}

function NewEventDrawer({
  open,
  busy,
  onClose,
  onSubmit,
}: {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onSubmit: (form: CardEventForm) => Promise<void>;
}) {
  const [form, setForm] = useState<CardEventForm>(makeForm);
  if (!open) return null;
  const update = (field: keyof CardEventForm, value: string) => {
    setForm((current) => ({...current, [field]: value}));
  };
  return (
    <div className="drawer-layer" role="presentation" onMouseDown={onClose}>
      <aside
        className="drawer event-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="New card event"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="drawer-header">
          <div>
            <span className="eyebrow">Processor simulator</span>
            <h2>New card event</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close form">
            <X size={19} />
          </button>
        </header>
        <form
          className="event-form"
          onSubmit={async (event) => {
            event.preventDefault();
            await onSubmit(form);
            setForm(makeForm());
          }}
        >
          <label>
            Event type
            <span className="select-field">
              <select
                value={form.eventType}
                onChange={(event) => update("eventType", event.target.value)}
              >
                <option value="authorization">Authorization</option>
                <option value="capture">Capture</option>
                <option value="refund">Refund</option>
                <option value="reversal">Reversal</option>
              </select>
              <ChevronDown size={15} />
            </span>
          </label>
          <label>
            Transaction ID
            <input
              required
              minLength={3}
              value={form.transactionId}
              onChange={(event) => update("transactionId", event.target.value)}
            />
          </label>
          <label>
            Processor event ID
            <input
              required
              minLength={3}
              value={form.eventId}
              onChange={(event) => update("eventId", event.target.value)}
            />
          </label>
          <label>
            Card ID
            <input
              required
              minLength={3}
              value={form.cardId}
              onChange={(event) => update("cardId", event.target.value)}
            />
          </label>
          <label>
            Merchant
            <input
              required
              value={form.merchantName}
              onChange={(event) => update("merchantName", event.target.value)}
            />
          </label>
          <div className="form-row">
            <label>
              Amount
              <input
                required
                inputMode="decimal"
                value={form.amount}
                onChange={(event) => update("amount", event.target.value)}
              />
            </label>
            <label>
              Currency
              <span className="select-field">
                <select
                  value={form.currency}
                  onChange={(event) => update("currency", event.target.value)}
                >
                  <option>AUD</option>
                  <option>USD</option>
                </select>
                <ChevronDown size={15} />
              </span>
            </label>
          </div>
          <div className="form-callout">
            <ShieldCheck size={17} />
            Writes use a unique idempotency key. Amounts are converted to integer minor
            units before submission.
          </div>
          <div className="drawer-actions">
            <button type="button" className="secondary-button" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="primary-button" disabled={busy}>
              {busy ? <RefreshCw className="spin" size={16} /> : <Plus size={16} />}
              {busy ? "Submitting…" : "Submit event"}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}

function ConnectionModal({
  open,
  busy,
  error,
  initial,
  onClose,
  onConnect,
  onDemo,
}: {
  open: boolean;
  busy: boolean;
  error: string | null;
  initial: ConnectionSettings;
  onClose: () => void;
  onConnect: (settings: ConnectionSettings) => Promise<void>;
  onDemo: () => void;
}) {
  const [settings, setSettings] = useState(initial);
  useEffect(() => setSettings(initial), [initial, open]);
  if (!open) return null;
  return (
    <div className="modal-layer" role="presentation" onMouseDown={onClose}>
      <section
        className="connection-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Data connection"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <span className="connection-icon">
            <Server size={22} />
          </span>
          <div>
            <span className="eyebrow">Data source</span>
            <h2>Connect SpendLedger API</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>
        <p>
          Connect a locally running API or continue with clearly labelled synthetic
          data. The API key remains in this browser session and is never bundled.
        </p>
        <label>
          API base URL
          <input
            value={settings.apiUrl}
            onChange={(event) =>
              setSettings((current) => ({...current, apiUrl: event.target.value}))
            }
            placeholder="http://localhost:8000"
          />
        </label>
        <label>
          API key
          <input
            type="password"
            value={settings.apiKey}
            onChange={(event) =>
              setSettings((current) => ({...current, apiKey: event.target.value}))
            }
            placeholder="sl_live_..."
          />
        </label>
        {error ? <div className="connection-error">{error}</div> : null}
        <footer>
          <button className="secondary-button" onClick={onDemo}>
            Use demo data
          </button>
          <button
            className="primary-button"
            disabled={busy || !settings.apiUrl || !settings.apiKey}
            onClick={() => onConnect(settings)}
          >
            {busy ? <RefreshCw className="spin" size={16} /> : <Server size={16} />}
            {busy ? "Connecting…" : "Connect API"}
          </button>
        </footer>
      </section>
    </div>
  );
}

export default function App() {
  const [view, setView] = useState<ViewName>("overview");
  const [data, setData] = useState<DashboardData>(demoSnapshot);
  const [selectedTransaction, setSelectedTransaction] = useState<Transaction | null>(
    null,
  );
  const [eventDrawerOpen, setEventDrawerOpen] = useState(false);
  const [connectionOpen, setConnectionOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [connection, setConnection] = useState<ConnectionSettings>({
    apiUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
    apiKey: "",
  });
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [clock, setClock] = useState(new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setClock(new Date()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const apiUrl = sessionStorage.getItem("spendledger.apiUrl");
    const apiKey = sessionStorage.getItem("spendledger.apiKey");
    if (apiUrl && apiKey) {
      const saved = {apiUrl, apiKey};
      setConnection(saved);
      fetchOverview(saved)
        .then((overview) => {
          setData(overview);
          setLive(true);
        })
        .catch(() => {
          sessionStorage.removeItem("spendledger.apiKey");
        });
    }
  }, []);

  const pageTitle = useMemo(
    () => navItems.find((item) => item.id === view)?.label ?? "Overview",
    [view],
  );

  const showToast = (message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 2_600);
  };

  const handleConnect = async (settings: ConnectionSettings) => {
    setBusy(true);
    setConnectionError(null);
    try {
      const overview = await fetchOverview(settings);
      setData(overview);
      setConnection(settings);
      setLive(true);
      sessionStorage.setItem("spendledger.apiUrl", settings.apiUrl);
      sessionStorage.setItem("spendledger.apiKey", settings.apiKey);
      setConnectionOpen(false);
      showToast("Live SpendLedger API connected");
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "Connection failed.");
    } finally {
      setBusy(false);
    }
  };

  const useDemo = () => {
    sessionStorage.removeItem("spendledger.apiUrl");
    sessionStorage.removeItem("spendledger.apiKey");
    setData(demoSnapshot());
    setLive(false);
    setConnectionOpen(false);
    setConnectionError(null);
    showToast("Switched to synthetic demo data");
  };

  const handleEvent = async (form: CardEventForm) => {
    setBusy(true);
    try {
      if (live) {
        await submitCardEvent(connection, form);
        setData(await fetchOverview(connection));
        showToast("Card event committed to the live API");
      } else {
        const amount = Number(form.amount);
        const state: TransactionState =
          form.eventType === "authorization"
            ? "authorized"
            : form.eventType === "reversal"
              ? "reversed"
              : form.eventType === "refund"
                ? "partially_refunded"
                : "captured";
        const created = buildDemoTransaction(
          form.transactionId,
          form.merchantName,
          amount,
          state,
          form.cardId,
        );
        setData((current) => ({
          ...current,
          generatedAt: new Date().toISOString(),
          totalCaptured:
            state === "captured" ? current.totalCaptured + amount : current.totalCaptured,
          pendingOutbox: current.pendingOutbox + 1,
          transactions: [created, ...current.transactions],
          outboxCounts: current.outboxCounts.map((item) =>
            item.status === "pending" ? {...item, count: item.count + 1} : item,
          ),
        }));
        showToast("Synthetic card event added to the console");
      }
      setEventDrawerOpen(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Unable to submit the event.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileNavOpen ? "mobile-open" : ""}`}>
        <div className="brand">
          <span className="brand-mark">
            <i />
            <i />
            <i />
          </span>
          <strong>
            Spend<span>Ledger</span>
          </strong>
          <button
            className="mobile-close"
            onClick={() => setMobileNavOpen(false)}
            aria-label="Close navigation"
          >
            <X size={18} />
          </button>
        </div>
        <nav aria-label="Primary">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.id}
                className={view === item.id ? "active" : ""}
                onClick={() => {
                  setView(item.id);
                  setMobileNavOpen(false);
                }}
              >
                <Icon size={18} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="sidebar-status">
          <span>
            <i /> All systems operational
          </span>
          <small>Updated {formatTime(data.generatedAt)}</small>
        </div>
        <div className="operator">
          <span>AO</span>
          <div>
            <strong>Alex Operator</strong>
            <small>Operations workspace</small>
          </div>
          <ChevronDown size={15} />
        </div>
      </aside>

      {mobileNavOpen ? (
        <button
          className="mobile-scrim"
          onClick={() => setMobileNavOpen(false)}
          aria-label="Close navigation"
        />
      ) : null}

      <div className="app-main">
        <header className="topbar">
          <div className="topbar-title">
            <button
              className="mobile-menu"
              onClick={() => setMobileNavOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={19} />
            </button>
            <div>
              <span>SpendLedger Operations Console</span>
              <strong>{pageTitle}</strong>
            </div>
          </div>
          <div className="topbar-actions">
            <button
              className={`data-source ${live ? "live" : ""}`}
              onClick={() => setConnectionOpen(true)}
            >
              <i />
              {live ? "Live API" : "Demo Data"}
              <ChevronDown size={14} />
            </button>
            <div className="clock">
              <Clock3 size={18} />
              <span>
                <b>
                  {clock.toLocaleTimeString("en-AU", {
                    hour12: false,
                    timeZone: "Australia/Sydney",
                  })}{" "}
                  AEST
                </b>
                <small>
                  {clock.toLocaleDateString("en-AU", {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                  })}
                </small>
              </span>
            </div>
            <button className="primary-button" onClick={() => setEventDrawerOpen(true)}>
              <Plus size={17} /> New card event
            </button>
          </div>
        </header>

        <main className="content">
          {view === "overview" ? (
            <OverviewView
              data={data}
              onSelectTransaction={setSelectedTransaction}
              onNavigate={setView}
            />
          ) : null}
          {view === "transactions" ? (
            <TransactionsView data={data} onSelect={setSelectedTransaction} />
          ) : null}
          {view === "reconciliation" ? <ReconciliationView data={data} /> : null}
          {view === "ledger" ? (
            <LedgerView data={data} onSelect={setSelectedTransaction} />
          ) : null}
          {view === "operations" ? <OperationsView data={data} live={live} /> : null}
        </main>

        <footer className="statusbar">
          <span>All times shown in AEST (UTC+10)</span>
          <i />
          <span>Data latency: {live ? "live request" : "2.1s sample"}</span>
          <i />
          <span>
            API status: <b>{live ? "Connected" : "Demo mode"}</b>
          </span>
          <i />
          <span>Build: 2026.07.30.1</span>
        </footer>
      </div>

      <TransactionDrawer
        transaction={selectedTransaction}
        onClose={() => setSelectedTransaction(null)}
      />
      <NewEventDrawer
        open={eventDrawerOpen}
        busy={busy}
        onClose={() => setEventDrawerOpen(false)}
        onSubmit={handleEvent}
      />
      <ConnectionModal
        open={connectionOpen}
        busy={busy}
        error={connectionError}
        initial={connection}
        onClose={() => setConnectionOpen(false)}
        onConnect={handleConnect}
        onDemo={useDemo}
      />
      {toast ? (
        <div className="toast" role="status">
          <CheckCircle2 size={17} />
          {toast}
        </div>
      ) : null}
    </div>
  );
}
