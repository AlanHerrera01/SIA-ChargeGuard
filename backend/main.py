"""
ChargeGuard Backend FastAPI Application

Main entry point for the ChargeGuard backend API.
Integrates with orchestrator to handle charge analysis and dispute workflow.
"""

import os
import sys
import json
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add project root to path for imports
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from agents.orchestrator import run_chargeguard_case
from datasets import load_transactions, load_subscriptions, load_merchants

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


# Data loading (cached)
TRANSACTIONS = None
SUBSCRIPTIONS = None
MERCHANTS = None


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
    
    # transactions.json has a "transactions" array
    tx_list = TRANSACTIONS.get("transactions", [])
    transaction = next((tx for tx in tx_list if tx.get("id") == transaction_id), None)
    
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
    
    # subscriptions.json has a "subscriptions" array
    sub_list = SUBSCRIPTIONS.get("subscriptions", [])
    subscription = next((sub for sub in sub_list if sub.get("id") == subscription_id), None)
    
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
        # Run the orchestrator (blocks until merchant decision)
        result = run_chargeguard_case(transaction_id)
        
        # Convert result to JSON-serializable format
        # Result is a CaseResult object from orchestrator
        return {
            "case_id": result.case_id if hasattr(result, "case_id") else None,
            "transaction_id": transaction_id,
            "charge_analysis": result.charge_analysis.__dict__ if hasattr(result, "charge_analysis") else {},
            "evidence": result.evidence.__dict__ if hasattr(result, "evidence") else {},
            "dispute": result.dispute.__dict__ if hasattr(result, "dispute") else {},
            "merchant_response": result.merchant_response.__dict__ if hasattr(result, "merchant_response") else {},
            "negotiation": result.negotiation.__dict__ if hasattr(result, "negotiation") else {},
            "status": result.status if hasattr(result, "status") else "completed",
        }
    
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Case analysis failed: {str(e)}")


# Case status endpoint
@app.get("/cases/{case_id}")
async def get_case_status(case_id: str):
    """
    Get status of an existing case.
    
    Note: For hackathon MVP, we don't have persistent storage yet.
    Cases only exist during the synchronous analysis call.
    Future: integrate with DynamoDB for persistence.
    """
    # Placeholder for future implementation with persistence
    raise HTTPException(
        status_code=501,
        detail="Case status queries require persistent storage (future feature)"
    )


# Case decision endpoint
@app.post("/cases/{case_id}/decision")
async def submit_case_decision(case_id: str, request: CaseDecisionRequest):
    """
    Submit user decision on a case (accept/reject counter-offer).
    
    Note: For hackathon MVP, decisions are made during the analyze call.
    Future: support async workflow with separate decision endpoint.
    """
    # Placeholder for future implementation with persistence
    raise HTTPException(
        status_code=501,
        detail="Async case decisions require persistent storage (future feature)"
    )


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
