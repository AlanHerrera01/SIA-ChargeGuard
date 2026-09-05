# Mock Merchant Support API

FastAPI + Pydantic v2 implementation of [contracts §3](../../docs/contracts.md).
Synthetic claims only; no real merchant integrations. One process, in-memory
state, no background workers, sleeps, scheduled tasks or network calls.

## Run and test

From the repository root (Docker Desktop must be running):

```bash
docker compose up -d --build --wait mock-merchant
curl -s http://localhost:8002/health
# {"status":"ok"}
```

Compose mounts `datasets/` read-only. Startup validates **only**
`DATASET_DIR/merchants.json` (`DATASET_DIR=./datasets` by default). The service
never loads or exposes `ground_truth.json`. Missing/invalid merchant data fails
startup; restart after editing policies. No other datasets are needed.

Without Docker, from the root with an activated Python 3.12 virtual environment:

```bash
python -m pip install -r mock-services/merchant/requirements-dev.txt
python -m uvicorn main:app --app-dir mock-services/merchant --port 8002
# In another terminal:
python -m pytest mock-services/merchant
python -m ruff check mock-services/merchant
python -m ruff format --check mock-services/merchant
```

Use a single Uvicorn worker: multiple processes would have separate stores.
Docker runs as the non-root `app` user. Restart/reset drops all claims;
this mock is not a durable production dispute desk.

## Endpoints

| Method | Path | Result |
|---|---|---|
| GET | `/health` | `{"status":"ok"}` |
| POST | `/disputes` | Submitted dispute object (HTTP 200) |
| GET | `/disputes/{dispute_id}` | Current dispute, including every due transition |
| POST | `/disputes/{dispute_id}/accept` | `resolved_accepted` with the offered refund |
| POST | `/disputes/{dispute_id}/reject` | `escalated`; body `{"reason":"..."}` |
| GET | `/disputes?case_id=...&status=...` | Array, insertion order; filters combine with AND |
| POST | `/demo/reset` | Clears disputes and ID sequence, returns `{"status":"ok"}` |

Errors use `{"error":{"code":"...","message":"..."}}`:

- 400 `invalid_claim_amount`: zero or negative amount.
- 404 `merchant_not_found` / `dispute_not_found`: unknown IDs.
- 409 `invalid_state_transition`: accept/reject without a pending counter-offer,
  including repeated decisions. Failed actions do not change history.
- 422 `validation_error`: malformed fields, unknown enums, non-finite amounts,
  invalid filters or demo headers. Currency is `USD` only.
- Routing errors: 404 `not_found`, 405 `method_not_allowed`.

## State machine

```text
submitted --(+1s)--> under_review --(+policy delay)--> counter_offer
                           |                         |           |
             auto_counter_offer=false             accept       reject
                           |                         |           |
                     resolved_full          resolved_accepted  escalated
                                                                 |
                                                          (+policy delay)
                                                                 |
                                                        resolved_full / denied
```

Policy delay = `dispute_policy.response_delay_seconds` (3 seconds in the dataset).
Review starts at creation + 1s; the offer at creation + 1s + policy delay.
Escalation finishes at **rejection time** + policy delay, so a delayed human
decision cannot consume the escalation waiting period early.

Every GET, including list/filter queries, projects the timeline from creation,
the stored decision and current UTC time. It never changes the record.
Transition timestamps are scheduled times, not polling times. Sparse and frequent
polling produce identical history without missing or duplicate steps.
`updated_at` is the latest transition time. Notes explain actions and dollar
amounts for the frontend timeline; rejection notes include the supplied reason.

Offer = `min(round(requested_amount_usd * counter_offer_ratio, 2), max_refund_usd)`.
It exists only in `counter_offer`; acceptance preserves that amount in resolution.
Full resolution refunds the requested amount (the contract caps **offers**, not
full refunds). Approved refunds have a 5-day ETA; denial has amount 0 and ETA 0.
`expires_at` is offer time + 7 days; the contract defines no expiry transition.
IDs are sequential `dsp_000001`, resettable and unique per runtime.

## Demo controls

Set headers on **POST /disputes**; they are retained per dispute, so GET/decision
requests do not repeat them. Supporting the scenario header is required; sending
it is optional, as in §3.3. Omitting it uses the merchant policy.

| X-Demo-Scenario | Behavior |
|---|---|
| `full_refund` | Skip the offer, resolve fully after review |
| `counter_offer` | Force an offer, then full refund on rejection, even if policy normally denies |
| `denied` | Force an offer, then denial after rejection/escalation; acceptance still accepts the offer |
| `slow` | Keep policy outcomes, multiply **all** delays (including initial review) by 4 |

`X-Demo-Speed: instant` sets all delays to zero, including `slow` and escalation.
Creation still responds `submitted`, rejection responds `escalated`: these
acknowledge the explicit command. The next GET materializes due transitions.
Accept/reject also check projected state without requiring a prior GET.
Overrides copy the policy; they never change another dispute or merchant.

Runtime timestamps use UTC wall time. Tests inject a fixed clock and advance it
arithmetically, without sleeps. Identical clock/commands produce identical objects;
independent real-time sessions have different dates.

## curl walkthroughs

Examples use Bash (Git Bash on Windows, or macOS/Linux) and `jq`. Reset only when
it is safe to discard local demo cases. In PowerShell use `curl.exe` and put the
JSON body in a file, passing `--data-binary '@claim.json'`.

```bash
base=http://localhost:8002
claim='{"case_id":"case_demo","merchant_id":"mrc_netflix","user_id":"usr_demo","transaction_id":"txn_0031","claim_type":"price_hike","requested_amount_usd":4.50,"currency":"USD","message":"Unannounced price increase.","evidence":[{"type":"invoice","uri":"s3://example/invoices/inv_0031.pdf","description":"Invoice shows $19.99."}]}'
curl -sS -X POST "$base/demo/reset"

# Reject to full refund: submitted -> counter_offer -> escalated -> resolved_full.
created=$(curl -sS "$base/disputes" -H 'Content-Type: application/json' \
  -H 'X-Demo-Scenario: counter_offer' -H 'X-Demo-Speed: instant' -d "$claim")
echo "$created" | jq '.status'
id=$(echo "$created" | jq -r '.dispute_id')
curl -sS "$base/disputes/$id" | jq '.status'
curl -sS -X POST "$base/disputes/$id/reject" -H 'Content-Type: application/json' \
  -d '{"reason":"Requesting the full $4.50."}' | jq '.status'
curl -sS "$base/disputes/$id" | jq '{status,resolution,history}'

# Accept an offer.
id=$(curl -sS "$base/disputes" -H 'Content-Type: application/json' \
  -H 'X-Demo-Scenario: counter_offer' -H 'X-Demo-Speed: instant' -d "$claim" | jq -r '.dispute_id')
curl -sS -X POST "$base/disputes/$id/accept" | jq

# Direct full refund, without a decision.
id=$(curl -sS "$base/disputes" -H 'Content-Type: application/json' \
  -H 'X-Demo-Scenario: full_refund' -H 'X-Demo-Speed: instant' -d "$claim" | jq -r '.dispute_id')
curl -sS "$base/disputes/$id" | jq

# Denial after escalation.
id=$(curl -sS "$base/disputes" -H 'Content-Type: application/json' \
  -H 'X-Demo-Scenario: denied' -H 'X-Demo-Speed: instant' -d "$claim" | jq -r '.dispute_id')
curl -sS -X POST "$base/disputes/$id/reject" -H 'Content-Type: application/json' \
  -d '{"reason":"Please refund the whole charge."}' | jq '.status'
curl -sS "$base/disputes/$id" | jq

# Slow: poll after 4s for review, after 16s total for the offer.
id=$(curl -sS "$base/disputes" -H 'Content-Type: application/json' \
  -H 'X-Demo-Scenario: slow' -d "$claim" | jq -r '.dispute_id')
curl -sS "$base/disputes/$id" | jq
curl -sS "$base/disputes?case_id=case_demo&status=counter_offer" | jq
```

The unspecified list envelope (array), HTTP 200 creation/reset shape, denial ETA,
scenario branch selection and command-response timing are documented implementation
choices; no fields in the frozen contract are renamed or added.
