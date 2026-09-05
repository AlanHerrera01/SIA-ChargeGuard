"""
ChargeGuard Backend FastAPI Application

Main entry point for the ChargeGuard backend API.
Integrates with orchestrator to handle charge analysis and dispute workflow.
"""

import os
import sys
import json
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root to path for imports
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)


from agents.orchestrator import run_chargeguard_case


# Initialize FastAPI app
app = FastAPI(
    title="ChargeGuard Backend API",
    description="API for autonomous charge dispute monitoring and management",
    version="0.1.0",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class CaseAnalysisRequest(BaseModel):
    """Request model for analyzing a charge"""
    transaction_id: str


class CaseDecisionRequest(BaseModel):
    """Request model for user decision on a case"""
    decision: str  # "accept_offer" or "reject_and_request_full_refund"


class TransactionWebhookRequest(BaseModel):
    """Event sent by the mock bank when a transaction is posted."""
    transaction_id: str
    event_type: str = "transaction.posted"


class DecisionResolutionRequest(BaseModel):
    """Human decision for a merchant counter-offer."""
    decision: str
    reason: str | None = None


# Data loading (cached)
TRANSACTIONS = None
SUBSCRIPTIONS = None
MERCHANTS = None
CASES: dict[str, dict] = {}
PENDING_DECISIONS: dict[str, dict] = {}
MERCHANT_API_URL = os.getenv("MERCHANT_API_URL", "http://127.0.0.1:8002")


def load_datasets():
    """Load dataset files once at startup"""
    global TRANSACTIONS, SUBSCRIPTIONS, MERCHANTS
    
    datasets_dir = Path(project_root) / "datasets"
    
    try:
        with open(datasets_dir / "transactions.json") as f:
            TRANSACTIONS = json.load(f)
    except Exception as e:
        print(f"Warning: Could not load transactions.json: {e}")
        TRANSACTIONS = {}
    
    try:
        with open(datasets_dir / "subscriptions.json") as f:
            SUBSCRIPTIONS = json.load(f)
    except Exception as e:
        print(f"Warning: Could not load subscriptions.json: {e}")
        SUBSCRIPTIONS = {}
    
    try:
        with open(datasets_dir / "merchants.json") as f:
            MERCHANTS = json.load(f)
    except Exception as e:
        print(f"Warning: Could not load merchants.json: {e}")
        MERCHANTS = {}


def dataset_items(dataset):
    """Return records for either a JSON array or a wrapped object."""
    if isinstance(dataset, list):
        return dataset
    return next(iter(dataset.values()), []) if isinstance(dataset, dict) else []


def to_dict(value):
    """Convert Pydantic models and plain objects into JSON-safe dictionaries."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return value.__dict__ if hasattr(value, "__dict__") else value


def transaction_exists(transaction_id: str) -> bool:
    return any(
        tx.get("transaction_id", tx.get("id")) == transaction_id
        for tx in dataset_items(TRANSACTIONS)
    )


def serialize_case(transaction_id: str, result: dict) -> dict:
    """Store one consistent case shape for all API consumers."""
    dispute = to_dict(result.get("dispute")) if result.get("dispute") else None
    merchant_response = to_dict(result.get("merchant_response"))
    case_id = (
        dispute.get("case_id") if dispute else None
    ) or f"case_{uuid4().hex[:8]}"
    merchant_status = (
        merchant_response.get("status")
        if isinstance(merchant_response, dict)
        else None
    )
    status = "awaiting_human" if merchant_status == "counter_offer" else (
        "completed" if merchant_status else "analyzed"
    )
    case = {
        "case_id": case_id,
        "transaction_id": transaction_id,
        "charge_analysis": to_dict(result.get("charge_analysis")),
        "evidence": to_dict(result.get("evidence")),
        "dispute": dispute,
        "merchant_response": merchant_response,
        "negotiation": to_dict(result.get("negotiation")),
        "status": status,
    }
    if isinstance(merchant_response, dict):
        case["dispute_id"] = merchant_response.get("dispute_id")
    CASES[case_id] = case
    if status == "awaiting_human":
        PENDING_DECISIONS[case_id] = {
            "case_id": case_id,
            "dispute_id": case.get("dispute_id"),
            "status": "pending",
            "offer": merchant_response.get("offer"),
        }
    return case


def require_case(case_id: str) -> dict:
    case = CASES.get(case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return case


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "ChargeGuard Backend API",
        "version": "0.1.0",
    }


# Data access endpoints
@app.get("/transactions")
async def get_transactions():
    """Get all transactions from dataset"""
    if TRANSACTIONS is None:
        raise HTTPException(status_code=500, detail="Transactions data not loaded")
    return TRANSACTIONS


@app.get("/transactions/{transaction_id}")
async def get_transaction(transaction_id: str):
    """Get a specific transaction by ID"""
    if TRANSACTIONS is None:
        raise HTTPException(status_code=500, detail="Transactions data not loaded")
    
    tx_list = dataset_items(TRANSACTIONS)
    transaction = next(
        (
            tx for tx in tx_list
            if tx.get("transaction_id", tx.get("id")) == transaction_id
        ),
        None,
    )
    
    if not transaction:
        raise HTTPException(status_code=404, detail=f"Transaction {transaction_id} not found")
    
    return transaction


@app.get("/subscriptions")
async def get_subscriptions():
    """Get all subscriptions from dataset"""
    if SUBSCRIPTIONS is None:
        raise HTTPException(status_code=500, detail="Subscriptions data not loaded")
    return SUBSCRIPTIONS


@app.get("/subscriptions/{subscription_id}")
async def get_subscription(subscription_id: str):
    """Get a specific subscription by ID"""
    if SUBSCRIPTIONS is None:
        raise HTTPException(status_code=500, detail="Subscriptions data not loaded")
    
    sub_list = dataset_items(SUBSCRIPTIONS)
    subscription = next(
        (
            sub for sub in sub_list
            if sub.get("subscription_id", sub.get("id")) == subscription_id
        ),
        None,
    )
    
    if not subscription:
        raise HTTPException(status_code=404, detail=f"Subscription {subscription_id} not found")
    
    return subscription


@app.get("/merchants")
async def get_merchants():
    """Get all merchants from dataset"""
    if MERCHANTS is None:
        raise HTTPException(status_code=500, detail="Merchants data not loaded")
    return MERCHANTS


# Case analysis endpoint - main workflow
@app.post("/cases/analyze")
async def analyze_case(request: CaseAnalysisRequest):
    """
    Analyze a charge and run the ChargeGuard workflow.
    
    This is the main endpoint that:
    1. Runs ChargeAnalysisAgent to classify the anomaly
    2. Gathers evidence deterministically
    3. Drafts dispute message with DisputeAgent
    4. Submits to Mock Merchant
    5. Polls for response
    6. Returns merchant response and next steps
    
    For hackathon: runs synchronously until merchant reaches counter_offer/resolved
    """
    transaction_id = request.transaction_id
    
    try:
        if not transaction_exists(transaction_id):
            raise HTTPException(
                status_code=404,
                detail=f"Transaction {transaction_id} not found",
            )

        # Run the orchestrator (blocks until merchant decision)
        result = run_chargeguard_case(transaction_id)
        return serialize_case(transaction_id, result)
    
    except HTTPException:
        raise
    except (StopIteration, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Case analysis failed: {str(e)}")


@app.post("/transactions/webhook")
async def transaction_webhook(
    request: TransactionWebhookRequest,
    background_tasks: BackgroundTasks,
):
    """Receive a bank event and start analysis in the background."""
    if not transaction_exists(request.transaction_id):
        raise HTTPException(
            status_code=404,
            detail=f"Transaction {request.transaction_id} not found",
        )

    background_tasks.add_task(analyze_case, CaseAnalysisRequest(
        transaction_id=request.transaction_id,
    ))
    return {
        "status": "accepted",
        "event_type": request.event_type,
        "transaction_id": request.transaction_id,
    }


@app.get("/cases")
async def list_cases():
    """List cases created during the current backend process."""
    return list(CASES.values())


# Case status endpoint
@app.get("/cases/{case_id}")
async def get_case_status(case_id: str):
    """
    Get status of an existing case.
    
    Note: For hackathon MVP, we don't have persistent storage yet.
    Cases only exist during the synchronous analysis call.
    Future: integrate with DynamoDB for persistence.
    """
    return require_case(case_id)


@app.get("/decisions/pending")
async def list_pending_decisions():
    """List counter-offers waiting for the user."""
    return list(PENDING_DECISIONS.values())


async def resolve_merchant_decision(
    case: dict,
    request: DecisionResolutionRequest,
) -> dict:
    if request.decision not in {
        "accept_offer",
        "reject_and_request_full_refund",
    }:
        raise HTTPException(status_code=400, detail="Unsupported decision")

    dispute_id = case.get("dispute_id")
    if not dispute_id:
        raise HTTPException(status_code=409, detail="Case has no merchant dispute")

    endpoint = "accept"
    payload = None
    if request.decision == "reject_and_request_full_refund":
        endpoint = "reject"
        payload = {"reason": request.reason or "User requested full refund"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{MERCHANT_API_URL}/disputes/{dispute_id}/{endpoint}",
                json=payload,
            )
            response.raise_for_status()
            merchant_response = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Merchant service unavailable: {exc}",
        ) from exc

    case["merchant_response"] = merchant_response
    case["status"] = "completed"
    case["negotiation"] = {
        "user_decision": request.decision,
        "reason": request.reason,
        "resolution": merchant_response.get("resolution"),
    }
    PENDING_DECISIONS.pop(case["case_id"], None)
    return case


@app.post("/decisions/{case_id}/resolve")
async def resolve_decision(
    case_id: str,
    request: DecisionResolutionRequest,
):
    """Apply the user's decision to the corresponding merchant dispute."""
    return await resolve_merchant_decision(require_case(case_id), request)


# Case decision endpoint
@app.post("/cases/{case_id}/decision")
async def submit_case_decision(case_id: str, request: CaseDecisionRequest):
    """
    Submit user decision on a case (accept/reject counter-offer).
    
    Note: For hackathon MVP, decisions are made during the analyze call.
    Future: support async workflow with separate decision endpoint.
    """
    return await resolve_merchant_decision(
        require_case(case_id),
        DecisionResolutionRequest(decision=request.decision),
    )


@app.post("/demo/reset")
async def reset_demo():
    """Clear in-memory cases and reload the synthetic datasets."""
    CASES.clear()
    PENDING_DECISIONS.clear()
    load_datasets()
    return {
        "status": "ok",
        "message": "Backend cases and pending decisions cleared",
    }


# Startup event
@app.on_event("startup")
async def startup_event():
    """Load datasets on startup"""
    load_datasets()
    print("✅ ChargeGuard Backend API started")
    print("📊 Datasets loaded successfully")


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API info"""
    return {
        "service": "ChargeGuard Backend API",
        "version": "0.1.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "analyze_case": "POST /cases/analyze",
            "webhook": "POST /transactions/webhook",
            "cases": "GET /cases",
            "pending_decisions": "GET /decisions/pending",
            "resolve_decision": "POST /decisions/{case_id}/resolve",
            "reset": "POST /demo/reset",
            "transactions": "GET /transactions",
            "subscriptions": "GET /subscriptions",
            "merchants": "GET /merchants",
        },
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("BACKEND_PORT", "8000"))
    host = os.getenv("BACKEND_HOST", "0.0.0.0")
    
    print(f"🚀 Starting ChargeGuard Backend on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
