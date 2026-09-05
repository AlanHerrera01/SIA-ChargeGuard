# Mock Banking API

FastAPI + Pydantic v2 feed over the synthetic WP-2 dataset, implementing
`docs/contracts.md` section 2. Startup validates and loads only `subscriptions.json`
and `transactions.json` into memory. No AWS account or database is required.
The evaluation file is never opened, and no directory is exposed as static files.

## Run from the repository root

Python 3.11+ (Docker uses 3.12):

```bash
python -m pip install -r mock-services/bank/requirements-dev.txt
python -m uvicorn main:app --app-dir mock-services/bank --port 8001
```

`DATASET_DIR` defaults to `./datasets`, relative to the working directory.
`BACKEND_WEBHOOK_URL` provides the optional default webhook destination.
Set these in your shell or use the `.env` loaded by Docker Compose; the standalone
command does not automatically load `.env`. Run one worker because state is in memory.
Missing or invalid datasets prevent startup instead of reporting a false healthy state.

With the Compose configuration from WP-1:

```bash
docker compose up -d --build --wait --wait-timeout 120 mock-bank
docker compose ps mock-bank
```

Compose mounts `./datasets` read-only at `/app/datasets`. Keep `DATASET_DIR=./datasets`
inside this container. From mock-bank, the backend destination is
`http://backend:8000/transactions/webhook` when using the `app` profile, or
`http://host.docker.internal:8000/transactions/webhook` for a backend on the
Docker Desktop host. `localhost` inside a container refers to that container.

## Endpoints

| Method | Path | Response |
|---|---|---|
| GET | `/health` | `{"status":"ok","dataset_version":"1"}` |
| GET | `/users/{user_id}/subscriptions` | Subscription array; unknown user returns `[]`. |
| GET | `/users/{user_id}/transactions` | `{"items":[...],"next_cursor":null}` |
| GET | `/transactions/{transaction_id}` | Full transaction; missing ID returns 404 `transaction_not_found`. |
| POST | `/transactions/notify` | Outcome of one webhook delivery attempt. |
| POST | `/demo/reset` | Reload both feed files, clear the event sequence, return `{"status":"ok"}`. |

Transaction filters: `since`, `until` (inclusive UTC dates), `merchant_id`,
`subscription_id`, `limit` (default 100; 1-500), `cursor`.
Results are ordered by `posted_at` descending, with `transaction_id` descending as
the tie-breaker. Filters are applied before pagination. A cursor is URL-safe base64
of the last returned `sk` (`posted_at#transaction_id`); pass it back unchanged with
the same filters. It is a position, not an authentication token or snapshot.
`next_cursor` is null for empty results and the last page. Neither `sk` nor any
evaluation labels appear in the transaction object.

```bash
curl -s localhost:8001/health | jq
curl -s localhost:8001/users/usr_demo/subscriptions | jq
curl -s 'localhost:8001/users/usr_demo/transactions?limit=5' | jq
curl -sG localhost:8001/users/usr_demo/transactions \
  --data-urlencode 'merchant_id=mrc_spotify' \
  --data-urlencode 'since=2026-08-01' --data-urlencode 'until=2026-09-14' | jq
curl -sG localhost:8001/users/usr_demo/transactions \
  --data-urlencode 'subscription_id=sub_001' | jq
cursor=$(curl -s 'localhost:8001/users/usr_demo/transactions?limit=5' | jq -r .next_cursor)
curl -sG localhost:8001/users/usr_demo/transactions \
  --data-urlencode 'limit=5' --data-urlencode "cursor=$cursor" | jq
curl -s localhost:8001/transactions/txn_0031 | jq
curl -s -X POST localhost:8001/transactions/notify \
  -H 'Content-Type: application/json' \
  -d '{"transaction_id":"txn_0031","webhook_url":"http://backend:8000/transactions/webhook"}' | jq
curl -s -X POST localhost:8001/transactions/notify \
  -H 'Content-Type: application/json' -d '{"transaction_id":"txn_0031"}' | jq
curl -s -X POST localhost:8001/demo/reset | jq
```

These examples use Bash/Git Bash and `jq`. In PowerShell use `curl.exe` to avoid
the `curl` alias; `python -m json.tool` is an alternative if `jq` is unavailable.

## Webhook and errors

The envelope has `event_id`, `event_type: transaction.posted`, `occurred_at`, and
`data` (the full transaction). To preserve deterministic demo replay, `occurred_at`
is the transaction's synthetic `posted_at`, and event IDs derive from its `sk`
and an in-memory attempt sequence. Reset restarts that sequence; consumers should
reset their demo deduplication state too. These are synthetic event timestamps,
not the current wall clock.

There is one awaited POST, no retries, no redirects, and a five-second total limit.
Waiting is necessary to return the contract's `delivered` result. Any 2xx is success:
`{"delivered":true,"status_code":200}` (the actual status is retained). Connection
errors, timeout, missing configuration, and non-2xx responses return HTTP 200 with
`{"delivered":false,"status_code":null,"error":"..."}`. Remote response bodies and
URLs are not echoed in errors. A provided URL overrides `BACKEND_WEBHOOK_URL`.

API errors use `{"error":{"code":"...","message":"..."}}`, including routing and
validation errors. Invalid cursors and reversed date ranges return 400
(`invalid_cursor`, `invalid_date_range`); invalid query/body values return 422
`validation_error`. A failed reset returns 503 `dataset_reload_failed` and preserves
the complete previous snapshot. The reset success body and these unspecified error
codes are documented implementation choices; the frozen fields are unchanged.

## Verify

```bash
pytest mock-services/bank
curl -s 'localhost:8001/users/usr_demo/transactions?limit=5' | jq
```

Tests use `httpx.ASGITransport` and explicitly enter FastAPI lifespan. They cover
all-page traversal, timestamp ties, filters, boundaries, user isolation, defaults,
error envelopes, an ASGI webhook receiver, failure/timeout, disk reload, reset
replay and atomic failure, and a guard that rejects reads of any non-feed file.

Runtime dependencies are in `requirements.txt`; test tools are in
`requirements-dev.txt`. The image copies only the application and runs as `app`,
without embedding datasets or credentials. This local synthetic mock has no auth;
do not expose its webhook trigger to untrusted users.
