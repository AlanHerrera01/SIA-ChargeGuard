# Synthetic datasets

Deterministic, entirely synthetic data used by ChargeGuard for local development, the
demo, and agent evaluation. No record represents a real customer or financial account.

## Regenerate

From the repository root:

```bash
python -m pip install -r datasets/requirements.txt
python datasets/generate.py --seed 42 --as-of 2026-09-14 --out datasets/
python -m pytest datasets/test_datasets.py -q
```

Both `--seed` and `--as-of` are explicit inputs. The defaults are `42` and
`2026-09-14`, so `python datasets/generate.py --seed 42` produces the committed demo
dataset. Running the same command twice produces byte-identical files, including PDFs and
emails.

## Outputs

- `merchants.json`: 10 deterministic merchant policies.
- `subscriptions.json`: 6 monthly subscriptions owned by `usr_demo`.
- `transactions.json`: six billing cycles per subscription plus one duplicate charge.
- `ground_truth.json`: evaluation-only labels; mock APIs must never serve this file.
- `invoices/`: one synthetic PDF invoice per transaction.
- `terms/`: one synthetic PDF terms document per subscription.
- `emails/`: 15 RFC-822 messages containing receipts, evidence, notices, and noise.

## Evaluation anomalies

| ID | Type | Evidence and expected claim |
|---|---|---|
| `anm_001` | `price_hike` | `sub_001` rises from $15.49 to $19.99 on `txn_0031`; no price-change notice exists. Claim: $4.50. |
| `anm_002` | `duplicate_charge` | `sub_003` posts twice on the same day for $10.99. Claim: $10.99. |
| `anm_003` | `charge_after_cancellation` | `sub_005` posts $39.99 six days after cancellation; a cancellation-confirmation email exists. Claim: $39.99. |

The other three subscriptions have no amount drift, duplicate billing day, or
post-cancellation charge. Price-change notices for `sub_002` and `sub_004` announce future
prices outside the dataset window and therefore are not anomalies.

## Ownership

Infrastructure & DevOps (Ismael).
