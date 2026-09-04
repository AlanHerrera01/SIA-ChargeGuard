# ChargeGuard — Interface Contracts (v1)

**Owner of this document:** Ismael (Infrastructure & DevOps)
**Status:** frozen for the hackathon. Any change requires a PR labeled `contract-change` plus a heads-up to Stephani (agents/backend) and Alan (frontend).

Everything below is the source of truth for how the mock services, the synthetic datasets and the storage layer look. Agents, backend and frontend code against **this file**, not against implementation details.

Conventions:
- Money fields are `*_usd`, JSON `number`, 2 decimals.
- Timestamps are ISO-8601 UTC with `Z` (`2026-08-14T09:12:00Z`). Date-only fields: `YYYY-MM-DD`.
- IDs are opaque strings with a type prefix: `mrc_`, `sub_`, `txn_`, `inv_`, `dsp_`, `case_`, `dec_`, `usr_`.
- The demo user is always `usr_demo`.
- Errors: HTTP status + `{"error": {"code": "snake_case_code", "message": "human readable"}}`.

---

## 1. Synthetic datasets (`datasets/`)

Generated deterministically by `datasets/generate.py --seed 42`. Regenerating with the same seed must produce byte-identical JSON.

### 1.1 `merchants.json` — 10 merchants

```json
[
  {
    "merchant_id": "mrc_netflix",
    "name": "Netflix",
    "category": "streaming",
    "support_channel": "api",
    "dispute_policy": {
      "auto_counter_offer": true,
      "counter_offer_ratio": 0.6,
      "response_delay_seconds": 3,
      "max_refund_usd": 50.00,
      "escalation_outcome": "resolved_full"
    }
  }
]
```

`category`: `streaming | cloud_storage | saas | fitness | music | news | gaming | delivery | education | security`
`escalation_outcome`: what the merchant does if the user rejects the counter-offer — `resolved_full | denied`.

### 1.2 `subscriptions.json` — 6 subscriptions, all for `usr_demo`

```json
[
  {
    "subscription_id": "sub_001",
    "user_id": "usr_demo",
    "merchant_id": "mrc_netflix",
    "plan_name": "Standard",
    "billing_cycle": "monthly",
    "billing_day": 14,
    "base_amount_usd": 15.49,
    "currency": "USD",
    "status": "active",
    "started_at": "2026-03-14",
    "cancelled_at": null,
    "terms_key": "terms/sub_001.pdf"
  }
]
```

`status`: `active | cancelled`. `terms_key` is an S3 key inside `S3_BUCKET_EVIDENCE`.

### 1.3 `transactions.json` — 6 months of history

```json
[
  {
    "transaction_id": "txn_0001",
    "user_id": "usr_demo",
    "subscription_id": "sub_001",
    "merchant_id": "mrc_netflix",
    "merchant_name": "Netflix",
    "amount_usd": 15.49,
    "currency": "USD",
    "posted_at": "2026-08-14T09:12:00Z",
    "description": "NETFLIX.COM  LOS GATOS CA",
    "status": "posted",
    "invoice_key": "invoices/inv_0001.pdf"
  }
]
```

**A transaction object never carries an anomaly label.** The agent has to earn the detection. Ground truth lives in a separate file used only for evaluation.

### 1.4 `ground_truth.json` — evaluation only, never served by any API

```json
{
  "anomalies": [
    {
      "anomaly_id": "anm_001",
      "type": "price_hike",
      "transaction_id": "txn_0031",
      "subscription_id": "sub_001",
      "expected_amount_usd": 15.49,
      "actual_amount_usd": 19.99,
      "delta_usd": 4.50,
      "notice_given": false,
      "expected_claim_amount_usd": 4.50
    }
  ]
}
```

The three injected anomalies — exactly these, all inside the last 45 days of the dataset:

| id | type | scenario | expected claim |
|----|------|----------|----------------|
| `anm_001` | `price_hike` | `sub_001` (Netflix) jumps 15.49 to 19.99 on the latest cycle. **No** price-change email exists in `emails/`. | 4.50 |
| `anm_002` | `duplicate_charge` | `sub_003` (Spotify) charged twice the same day, same amount. | the duplicated amount |
| `anm_003` | `charge_after_cancellation` | `sub_005` was cancelled (`cancelled_at` set) yet a charge posts 6 days later. A cancellation-confirmation email **does** exist in `emails/`. | the full charge |

Every other subscription must be clean — no near-misses that would provoke false positives (cent-level rounding drift is fine, nothing more).

### 1.5 `invoices/` — one PDF per transaction

`invoices/inv_XXXX.pdf`, generated with `fpdf2`. Contains merchant name, invoice id, transaction id, plan name, billing period, line item, amount, date. The price-hike invoice must show the **new** price so the agent can cite it as evidence.

### 1.6 `emails/` — synthetic `.eml` files

`emails/eml_XXX.eml`, valid RFC-822 with `From`, `To: demo@chargeguard.dev`, `Subject`, `Date`, `Message-ID`, plain-text body. About 15 emails:
- receipts for several charges,
- one cancellation confirmation for `sub_005` (supports `anm_003`),
- price-change notices for **two other** subscriptions (so the agent can distinguish "notified" from "silent"),
- some marketing noise so search is not trivial,
- **no** price-change notice for `sub_001` — that absence is the evidence for `anm_001`.

---

## 2. Mock Bank API — `http://localhost:8001`

Read-only feed over the synthetic dataset, plus a webhook trigger. It never invents data at runtime.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | `{"status":"ok","dataset_version":"1"}` |
| `GET` | `/users/{user_id}/subscriptions` | all subscriptions for the user |
| `GET` | `/users/{user_id}/transactions` | query: `since`, `until` (ISO date), `merchant_id`, `subscription_id`, `limit` (default 100, max 500), `cursor` |
| `GET` | `/transactions/{transaction_id}` | single transaction, 404 `transaction_not_found` |
| `POST` | `/transactions/notify` | fires a webhook (below) |
| `POST` | `/demo/reset` | reload datasets from disk, clear runtime state |

`GET /users/{user_id}/transactions` response, sorted by `posted_at` **descending**:
```json
{ "items": [ /* transaction objects */ ], "next_cursor": null }
```

`POST /transactions/notify` request:
```json
{ "transaction_id": "txn_0031", "webhook_url": "http://backend:8000/transactions/webhook" }
```
`webhook_url` is optional and defaults to env `BACKEND_WEBHOOK_URL`. The service POSTs this envelope and returns `{"delivered": true, "status_code": 200}`:
```json
{
  "event_id": "evt_...",
  "event_type": "transaction.posted",
  "occurred_at": "2026-09-10T18:00:00Z",
  "data": { /* full transaction object */ }
}
```
Delivery is fire-and-forget with a 5s timeout. On failure return `{"delivered": false, "status_code": null, "error": "..."}` with HTTP 200 — the demo must not crash because the backend is down.

---

## 3. Mock Merchant Support API — `http://localhost:8002`

Simulates a merchant dispute desk as a deterministic, time-based state machine.

### 3.1 State machine

```
submitted --(+1s)--> under_review --(+3s)--> counter_offer
                                                  |
                              accept -------------+------------- reject
                                 |                                   |
                          resolved_accepted                      escalated --(+3s)--> resolved_full | denied
```

Transitions are computed from `created_at` on every `GET` — no background workers, so the demo is reproducible. If the merchant's `dispute_policy.auto_counter_offer` is `false`, `under_review` goes straight to `resolved_full`.

Statuses: `submitted | under_review | counter_offer | resolved_accepted | escalated | resolved_full | denied`.

### 3.2 Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | liveness |
| `POST` | `/disputes` | file a dispute |
| `GET` | `/disputes/{dispute_id}` | current status (drives transitions) |
| `POST` | `/disputes/{dispute_id}/accept` | accept the counter-offer |
| `POST` | `/disputes/{dispute_id}/reject` | reject and escalate |
| `GET` | `/disputes` | list for debug/UI, query `case_id`, `status` |
| `POST` | `/demo/reset` | drop all disputes |

`POST /disputes` request:
```json
{
  "case_id": "case_a1b2c3",
  "merchant_id": "mrc_netflix",
  "user_id": "usr_demo",
  "transaction_id": "txn_0031",
  "claim_type": "price_hike",
  "requested_amount_usd": 4.50,
  "currency": "USD",
  "message": "Plain-language claim written by the agent.",
  "evidence": [
    { "type": "invoice", "uri": "s3://bucket/invoices/inv_0031.pdf", "description": "Invoice showing 19.99" },
    { "type": "transaction_history", "uri": null, "description": "12 prior charges at 15.49" }
  ]
}
```
`claim_type`: `price_hike | duplicate_charge | charge_after_cancellation | other`.
`evidence[].type`: `invoice | email | transaction_history | subscription_terms | other`.
Validation: 400 `invalid_claim_amount` when `requested_amount_usd <= 0`; 404 `merchant_not_found`.

Dispute object, returned by every dispute endpoint:
```json
{
  "dispute_id": "dsp_7f3a91",
  "case_id": "case_a1b2c3",
  "merchant_id": "mrc_netflix",
  "transaction_id": "txn_0031",
  "status": "counter_offer",
  "requested_amount_usd": 4.50,
  "created_at": "2026-09-10T18:00:00Z",
  "updated_at": "2026-09-10T18:00:04Z",
  "offer": {
    "amount_usd": 2.70,
    "message": "We can offer a one-time courtesy credit of $2.70.",
    "expires_at": "2026-09-17T18:00:04Z"
  },
  "resolution": null,
  "history": [
    { "at": "2026-09-10T18:00:00Z", "status": "submitted", "note": "Dispute received" }
  ]
}
```
`offer` is `null` outside `counter_offer`. Offer amount = `round(requested_amount_usd * counter_offer_ratio, 2)`, capped at `max_refund_usd`.

`resolution` once terminal:
```json
{ "outcome": "accepted", "refund_amount_usd": 2.70, "refund_eta_days": 5, "closed_at": "2026-09-10T18:01:00Z" }
```
`outcome`: `accepted | full_refund | denied`.

`POST /disputes/{id}/reject` body: `{"reason": "Requesting the full 4.50 as originally charged."}`.
Accept or reject from a state that does not allow it: 409 `invalid_state_transition`.

### 3.3 Demo overrides (required for the video)

Header `X-Demo-Scenario` on `POST /disputes` forces the outcome regardless of policy:
`full_refund` (skip the counter-offer, resolve fully) · `counter_offer` (default path) · `denied` · `slow` (delays x4, to show polling).
Header `X-Demo-Speed: instant` collapses all delays to zero for automated tests.

---

## 4. Storage contracts

### 4.1 DynamoDB — identical schema in LocalStack and in AWS

**`chargeguard-transactions`** — PK `user_id` (S), SK `sk` (S) = `"{posted_at}#{transaction_id}"`.
GSI `merchant-index`: PK `merchant_id`, SK `sk`. Item attributes mirror §1.3.

**`chargeguard-cases`** — PK `case_id` (S).
GSI `user-index`: PK `user_id`, SK `created_at`. GSI `status-index`: PK `status`, SK `created_at`.
Attributes: `case_id, user_id, subscription_id, merchant_id, transaction_id, anomaly_type, confidence (0-1), claimed_amount_usd, status, dispute_id, timeline (list of {at, actor, event, detail}), created_at, updated_at`.
Case `status`: `detected | investigating | dispute_filed | awaiting_merchant | awaiting_human | resolved | dismissed`.

**`chargeguard-decisions`** — PK `decision_id` (S).
GSI `case-index`: PK `case_id`, SK `created_at`. GSI `pending-index`: PK `status`, SK `created_at`.
Attributes: `decision_id, case_id, question, context, options (list of {option_id, label, detail}), status (pending|resolved|expired), chosen_option_id, resolved_at, created_at`.

All tables: `PAY_PER_REQUEST`, point-in-time recovery off, deletion protection off (hackathon — the stack must stay destroyable).

### 4.2 S3 — `S3_BUCKET_EVIDENCE`

Prefixes: `invoices/`, `emails/`, `terms/`, `evidence/{case_id}/`.
Block Public Access on, SSE-S3, versioning off, lifecycle expiry at 30 days. Bucket name in AWS: `chargeguard-evidence-${account_id}`.

### 4.3 Environment variables

`.env.example` is the contract: adding a variable means updating `.env.example` in the same PR. Variables this plan introduces:

```
BACKEND_WEBHOOK_URL=http://localhost:8000/transactions/webhook
DATASET_DIR=./datasets
DEMO_USER_ID=usr_demo
AWS_ENDPOINT_URL=http://localhost:4566
AWS_PROFILE=default
```

### 4.4 Model selection

Two models, both verified by CLI on 2026-09-04. Agents read these from the environment; no model id is ever hardcoded in Python.

| Variable | Value | Use it for |
|---|---|---|
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | The orchestrator, ChargeAnalysisAgent and NegotiationAgent — anything that reasons, judges confidence, or writes text a merchant will read. |
| `BEDROCK_MODEL_ID_FAST` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | High-volume, low-reasoning steps: polling dispute status, extracting fields from an invoice, classifying an email. Optional — if a sub-agent's quality drops, move it to `BEDROCK_MODEL_ID`. |

Claude Sonnet 5 is **not** invocable from the team's accounts (`AccessDeniedException`) and Claude Sonnet 4 is retired as Legacy. Do not switch to either without re-running the `converse` check first. Verified alternates, swappable via the variable alone: `us.anthropic.claude-sonnet-4-6`, `us.anthropic.claude-opus-4-5-20251101-v1:0`.
