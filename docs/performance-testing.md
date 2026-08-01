# Performance test plan

The repository includes a k6 workload in `load/k6.js`. It mixes direct captures, reads, and a small
percentage of deliberate idempotent replays.

Run against a disposable environment:

```bash
docker run --rm -i \
  -e BASE_URL=http://host.docker.internal:8000 \
  -e API_KEY="$SPENDLEDGER_API_KEY" \
  grafana/k6 run - < load/k6.js
```

The default thresholds require fewer than 1% unexpected failures and p95 below 500 ms. Those are
portfolio test thresholds, not claimed production SLOs.

## Methodology

1. Start with a five-minute warm-up so pools and caches stabilize.
2. Ramp virtual users gradually and record throughput, p95/p99, CPU, memory, pool use, and lock wait.
3. Identify the saturation point rather than reporting only an easy low-load number.
4. Repeat each run three times against a clean, equivalent dataset.
5. Inspect query plans and database waits before changing application code.
6. Run a failure case with the worker or downstream publisher unavailable.

Do not publish invented benchmark numbers. Add the machine/database specification, dataset size,
commit SHA, workload parameters, and raw k6 summary when a real run is performed.
