# WP-03 verification — 2026-09-05

## Automated tests

Executed from the repository root with the local virtual environment:

```powershell
.\.venv\Scripts\pytest.exe mock-services/bank
```

```text
============================= test session starts =============================
platform win32 -- Python 3.11.9, pytest-8.4.2, pluggy-1.6.0
rootdir: C:\Users\camagua\Documents\TI\Hackathon AWS\SIA-ChargeGuard
plugins: anyio-4.15.1
collected 31 items

mock-services\bank\test_bank.py ...............................          [100%]

============================= 31 passed in 25.51s =============================
```

Lint and formatting:

```text
$ python -m ruff check mock-services/bank
All checks passed!
$ python -m ruff format --check mock-services/bank
3 files already formatted
```

## Live Docker acceptance

`docker compose up -d --build --wait --wait-timeout 120 mock-bank` completed successfully.
Both mock-bank and LocalStack reported healthy.
`docker compose exec -T mock-bank id` returned:

```text
uid=100(app) gid=101(app) groups=101(app)
```

The host command `curl.exe -fsS 'http://localhost:8001/users/usr_demo/transactions?limit=5'`
returned the same response below. Since jq was unavailable on Windows, the exact
curl/jq pipeline was also run in a temporary Alpine container sharing the bank's
network namespace:

```powershell
docker run --rm --network container:chargeguard-mock-bank-1 alpine:3.22 sh -c 'apk add --no-cache curl jq >/dev/null && curl -s "localhost:8001/users/usr_demo/transactions?limit=5" | jq'
```

Complete stdout:

```json
{
  "items": [
    {
      "transaction_id": "txn_0031",
      "user_id": "usr_demo",
      "subscription_id": "sub_001",
      "merchant_id": "mrc_netflix",
      "merchant_name": "Netflix",
      "amount_usd": 19.99,
      "currency": "USD",
      "posted_at": "2026-09-14T09:10:00Z",
      "description": "NETFLIX.COM  LOS GATOS CA",
      "status": "posted",
      "invoice_key": "invoices/inv_0031.pdf"
    },
    {
      "transaction_id": "txn_0037",
      "user_id": "usr_demo",
      "subscription_id": "sub_006",
      "merchant_id": "mrc_safevault",
      "merchant_name": "SafeVault",
      "amount_usd": 2.99,
      "currency": "USD",
      "posted_at": "2026-09-12T09:15:00Z",
      "description": "SAFEVAULT  BOSTON MA",
      "status": "posted",
      "invoice_key": "invoices/inv_0037.pdf"
    },
    {
      "transaction_id": "txn_0036",
      "user_id": "usr_demo",
      "subscription_id": "sub_004",
      "merchant_id": "mrc_notion",
      "merchant_name": "Notion",
      "amount_usd": 12.0,
      "currency": "USD",
      "posted_at": "2026-09-08T09:13:00Z",
      "description": "NOTION LABS  SAN FRANCISCO CA",
      "status": "posted",
      "invoice_key": "invoices/inv_0036.pdf"
    },
    {
      "transaction_id": "txn_0035",
      "user_id": "usr_demo",
      "subscription_id": "sub_003",
      "merchant_id": "mrc_spotify",
      "merchant_name": "Spotify",
      "amount_usd": 10.99,
      "currency": "USD",
      "posted_at": "2026-09-03T09:20:00Z",
      "description": "SPOTIFY USA  NEW YORK NY",
      "status": "posted",
      "invoice_key": "invoices/inv_0035.pdf"
    },
    {
      "transaction_id": "txn_0034",
      "user_id": "usr_demo",
      "subscription_id": "sub_003",
      "merchant_id": "mrc_spotify",
      "merchant_name": "Spotify",
      "amount_usd": 10.99,
      "currency": "USD",
      "posted_at": "2026-09-03T09:12:00Z",
      "description": "SPOTIFY USA  NEW YORK NY",
      "status": "posted",
      "invoice_key": "invoices/inv_0034.pdf"
    }
  ],
  "next_cursor": "MjAyNi0wOS0wM1QwOToxMjowMFojdHhuXzAwMzQ="
}
```

The five posted_at timestamps descend from September 14 to September 3; the final
two records are the intentional Spotify duplicate charges, ordered 09:20 then 09:12.

## Live webhook smoke test

A temporary stdlib HTTPServer on the Compose network received a POST from
`/transactions/notify` for `txn_0031`. The success response was:

```text
HTTP 200 {"delivered":true,"status_code":200}
```

The receiver captured `event_type=transaction.posted`, an `evt_` ID,
`occurred_at=2026-09-14T09:10:00Z`, and the full transaction object.
A second request targeted the bank container's unused loopback port 65534:

```text
HTTP 200 {"delivered":false,"status_code":null,"error":"Webhook delivery failed"}
```

Finally, `POST /demo/reset` returned:

```text
HTTP 200 {"status":"ok"}
```

The temporary receiver container was removed after it exited. Mock-bank and its
LocalStack dependency were left running for local development.

## Test design references

Tests explicitly enter lifespan because HTTPX ASGITransport does not trigger it:
[HTTPX transports](https://www.python-httpx.org/advanced/transports/).
The service uses FastAPI lifespan for startup loading and client cleanup:
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/).
