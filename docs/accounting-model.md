# Accounting model

SpendLedger uses immutable double-entry journals. Amounts are positive integer minor units and the
entry direction carries the sign.

## Capture

For a 129.90 AUD card capture:

| Account | Type | Debit | Credit |
| --- | --- | ---: | ---: |
| Employee expense clearing | Expense | 12,990 | |
| Card payable | Liability | | 12,990 |

The journal constraint requires total debit = total credit = 12,990.

## Refund

A 20.00 AUD refund posts a new reversing journal:

| Account | Type | Debit | Credit |
| --- | --- | ---: | ---: |
| Card payable | Liability | 2,000 | |
| Employee expense clearing | Expense | | 2,000 |

The original capture journal is not edited or deleted. This preserves history and lets an auditor
rebuild balances from entries.

## Authorization and reversal

An authorization is a hold, not a settled accounting movement in this simplified model, so it
changes transaction state without posting to the ledger. A reversal releases that hold. Capture
is the point at which the payable and expense-clearing entries are recognized.

## Explicit limitations

- account coding is a simplified clearing model, not a full customer general ledger;
- tax, tips, split tender, chargebacks, interchange, and FX are outside the current boundary;
- partial captures and incremental authorizations would require additional lifecycle states;
- the reconciliation model assumes one settlement line per captured transaction.

These are product decisions, not hidden implementation omissions. Each would be introduced with a
new invariant, migration, and test matrix.
