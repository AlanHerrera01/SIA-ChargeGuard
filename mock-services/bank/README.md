# Mock Bank API

FastAPI service simulating a bank's transaction feed.

## Endpoints
- `GET /transactions/{user_id}` - list transactions
- `POST /transactions/notify` - dispatch a new transaction event (webhook to backend)
- `GET /transactions/{id}` - get single transaction

## Run
```bash
cd mock-services/bank
uvicorn main:app --port 8001 --reload
```
