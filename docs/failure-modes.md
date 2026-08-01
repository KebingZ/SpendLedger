# Failure modes and operational response

| Failure | Detection | Automatic behaviour | Operator action |
| --- | --- | --- | --- |
| Duplicate HTTP retry | Existing idempotency record | Replay original status/body | None |
| Idempotency key reused with changed payload | Request hash mismatch | Return `409` | Fix client key generation |
| Duplicate processor event | Provider-event hash lookup | Return existing transaction | None |
| Concurrent state transition | PostgreSQL row lock | Serialize per transaction | Investigate only if latency alerts |
| Invalid financial transition | State-machine guard | Return `422`, rollback all writes | Correct upstream event/order |
| Ledger imbalance | Service check and DB constraint | Reject transaction | Page if generated internally |
| Database unavailable | Readiness query | Remove pod from service endpoints | Restore primary/fail over |
| Publisher unavailable | Worker exception | Exponential retry, then dead letter | Restore broker and replay dead letters |
| Worker crashes after claim | Expired processing lease | Another worker reclaims event | None unless backlog grows |
| Consumer processes event twice | Consumer sees repeated event ID | Consumer must deduplicate | Repair consumer contract |
| Settlement line absent internally | Reconciliation exception | Persist `missing_internal` | Investigate processor/import gap |
| Internal capture absent from settlement | Reconciliation exception | Persist `missing_settlement` | Investigate delayed settlement |

## Suggested service-level indicators

- availability: successful non-4xx requests / eligible requests;
- latency: p50, p95, and p99 per route;
- correctness: ledger constraint violations and rejected illegal transitions;
- reconciliation: exception count and age by status;
- outbox: oldest pending age, retry rate, dead-letter count, stale lock reclaim count;
- database: connection saturation, lock wait, slow transactions, and replication lag.

## Initial alert policy

- page: readiness unavailable for five minutes across more than one replica;
- page: ledger imbalance or dead-letter count increases;
- ticket: reconciliation exception remains unresolved for one business day;
- ticket: oldest pending outbox event exceeds five minutes;
- investigate: p95 write latency exceeds the agreed SLO for three windows.

Thresholds are intentionally described as starting points. A production team should derive final
values from customer impact, traffic shape, and error-budget policy.

## Recovery drills

1. Stop the downstream publisher and confirm outbox backlog grows without losing API writes.
2. Restart a worker after it claims a row and confirm the lease is reclaimed.
3. Send duplicate events concurrently and verify one financial effect.
4. Restore PostgreSQL from backup into an isolated environment and reconcile a known settlement.
5. Reprocess a dead-letter event with the same event ID and confirm consumer deduplication.
