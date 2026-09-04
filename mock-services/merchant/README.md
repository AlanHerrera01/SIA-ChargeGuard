# Mock Merchant Support API

FastAPI service simulating a merchant's dispute support channel.

## Endpoints
- `POST /disputes` - create dispute
- `GET /disputes/{id}` - get dispute status (auto-transitions to `counter_offer` after ~3s)
- `POST /disputes/{id}/accept` - accept counter-offer
- `POST /disputes/{id}/reject` - reject and escalate

## Run
```bash
cd mock-services/merchant
uvicorn main:app --port 8002 --reload
```
