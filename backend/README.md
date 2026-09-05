# Backend

FastAPI service for the frontend. It receives bank events, coordinates the
agent orchestrator, stores demo cases in memory, and applies human decisions
to the mock merchant.

## Owner
Stephani Rivera

## Endpoints
- `POST /transactions/webhook` - receives events from mock bank
- `POST /cases/analyze` - synchronously analyzes a transaction
- `GET /cases` - list all cases
- `GET /cases/{id}` - case detail
- `GET /decisions/pending` - pending human decisions
- `POST /decisions/{id}/resolve` - resolve a pending decision
- `POST /demo/reset` - reload synthetic dataset

The case store is intentionally in memory for the hackathon MVP. Restarting
the backend clears cases and pending decisions.

## Setup
```bash
cd backend
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
uvicorn main:app --reload
```

From the repository root, use:

```bash
python -m uvicorn backend.main:app --reload --port 8000
```

The merchant mock must be available at `http://127.0.0.1:8002`. Override it
with `MERCHANT_API_URL` when needed.

## Example flow

```bash
curl -X POST http://localhost:8000/cases/analyze \
	-H "Content-Type: application/json" \
	-d '{"transaction_id":"txn_0031"}'

curl http://localhost:8000/decisions/pending

curl -X POST http://localhost:8000/decisions/case_123/resolve \
	-H "Content-Type: application/json" \
	-d '{"decision":"accept_offer"}'
```
