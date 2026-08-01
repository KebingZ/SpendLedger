# Contributing

1. Create a focused branch and add tests for every behavioural change.
2. Run `make check`.
3. If the schema changes, generate and review an Alembic migration.
4. Document new financial invariants and failure modes.
5. Keep secrets and machine-specific paths out of commits.

Pull requests should explain the customer impact, correctness assumptions, rollback plan, and
observability changes.
