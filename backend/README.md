# Backend

FastAPI service. Exposes REST API for the frontend, handles webhooks from the mock bank, coordinates the agent orchestrator.

## Owner
Stephani Rivera

## Endpoints
- `POST /transactions/webhook` - receives events from mock bank
- `GET /cases` - list all cases
- `GET /cases/{id}` - case detail
- `GET /decisions/pending` - pending human decisions
- `POST /decisions/{id}/resolve` - resolve a pending decision
- `POST /demo/reset` - reload synthetic dataset

## Setup
```bash
cd backend
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
pip install -r requirements.txt
uvicorn main:app --reload
```
