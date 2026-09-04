from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


app = FastAPI(title="Mock Merchant Support API")

DISPUTES = {}


class EvidenceItem(BaseModel):
    type: str
    uri: str | None
    description: str


class DisputeRequest(BaseModel):
    case_id: str
    merchant_id: str
    user_id: str
    transaction_id: str
    claim_type: str
    requested_amount_usd: float
    currency: str
    message: str
    evidence: list[EvidenceItem]


class RejectRequest(BaseModel):
    reason: str


def utc_now():
    return datetime.now(timezone.utc)


def isoformat(dt: datetime):
    return dt.isoformat().replace("+00:00", "Z")


def update_dispute_status(dispute: dict):
    created_at = datetime.fromisoformat(
        dispute["created_at"].replace("Z", "+00:00")
    )

    elapsed = (utc_now() - created_at).total_seconds()

    # submitted -> under_review after 1 second
    if elapsed >= 1 and dispute["status"] == "submitted":
        now = utc_now()

        dispute["status"] = "under_review"
        dispute["updated_at"] = isoformat(now)

        dispute["history"].append(
            {
                "at": dispute["updated_at"],
                "status": "under_review",
                "note": "Dispute is being reviewed",
            }
        )

    # under_review -> counter_offer after 3 seconds total
    if elapsed >= 3 and dispute["status"] == "under_review":
        offer_amount = round(
            dispute["requested_amount_usd"] * 0.6,
            2,
        )

        now = utc_now()

        dispute["status"] = "counter_offer"
        dispute["updated_at"] = isoformat(now)

        dispute["offer"] = {
            "amount_usd": offer_amount,
            "message": (
                f"We can offer a one-time courtesy credit "
                f"of ${offer_amount:.2f}."
            ),
            "expires_at": isoformat(
                now + timedelta(days=7)
            ),
        }

        dispute["history"].append(
            {
                "at": dispute["updated_at"],
                "status": "counter_offer",
                "note": "Merchant sent a partial refund offer",
            }
        )

    # escalated -> resolved_full after 3 seconds from escalation
    if dispute["status"] == "escalated":
        escalated_at = datetime.fromisoformat(
            dispute["escalated_at"].replace("Z", "+00:00")
        )

        escalation_elapsed = (
            utc_now() - escalated_at
        ).total_seconds()

        if escalation_elapsed >= 3:
            now = utc_now()

            dispute["status"] = "resolved_full"
            dispute["updated_at"] = isoformat(now)

            dispute["resolution"] = {
                "outcome": "full_refund",
                "refund_amount_usd": dispute["requested_amount_usd"],
                "refund_eta_days": 5,
                "closed_at": isoformat(now),
            }

            dispute["history"].append(
                {
                    "at": dispute["updated_at"],
                    "status": "resolved_full",
                    "note": "Full refund approved after escalation",
                }
            )

    return dispute


@app.get("/health")
def health():
    return {
        "status": "ok",
    }


@app.post("/disputes")
def create_dispute(dispute: DisputeRequest):
    if dispute.requested_amount_usd <= 0:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "invalid_claim_amount",
                    "message": (
                        "requested_amount_usd must be greater than 0"
                    ),
                }
            },
        )

    now = utc_now()

    dispute_id = f"dsp_{uuid4().hex[:6]}"

    dispute_object = {
        "dispute_id": dispute_id,
        "case_id": dispute.case_id,
        "merchant_id": dispute.merchant_id,
        "transaction_id": dispute.transaction_id,
        "status": "submitted",
        "requested_amount_usd": dispute.requested_amount_usd,
        "created_at": isoformat(now),
        "updated_at": isoformat(now),
        "offer": None,
        "resolution": None,
        "history": [
            {
                "at": isoformat(now),
                "status": "submitted",
                "note": "Dispute received",
            }
        ],
    }

    DISPUTES[dispute_id] = dispute_object

    return dispute_object


@app.get("/disputes/{dispute_id}")
def get_dispute(dispute_id: str):
    dispute = DISPUTES.get(dispute_id)

    if dispute is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "dispute_not_found",
                    "message": "Dispute not found",
                }
            },
        )

    return update_dispute_status(dispute)


@app.post("/disputes/{dispute_id}/accept")
def accept_counter_offer(dispute_id: str):
    dispute = DISPUTES.get(dispute_id)

    if dispute is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "dispute_not_found",
                    "message": "Dispute not found",
                }
            },
        )

    update_dispute_status(dispute)

    if dispute["status"] != "counter_offer":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "invalid_state_transition",
                    "message": (
                        "Counter-offer can only be accepted "
                        "while dispute status is counter_offer"
                    ),
                }
            },
        )

    now = utc_now()

    offered_amount = dispute["offer"]["amount_usd"]

    dispute["status"] = "resolved_accepted"
    dispute["updated_at"] = isoformat(now)

    dispute["resolution"] = {
        "outcome": "accepted",
        "refund_amount_usd": offered_amount,
        "refund_eta_days": 5,
        "closed_at": isoformat(now),
    }

    dispute["history"].append(
        {
            "at": dispute["updated_at"],
            "status": "resolved_accepted",
            "note": (
                f"User accepted merchant offer of "
                f"${offered_amount:.2f}"
            ),
        }
    )

    return dispute


@app.post("/disputes/{dispute_id}/reject")
def reject_counter_offer(
    dispute_id: str,
    request: RejectRequest,
):
    dispute = DISPUTES.get(dispute_id)

    if dispute is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "dispute_not_found",
                    "message": "Dispute not found",
                }
            },
        )

    update_dispute_status(dispute)

    if dispute["status"] != "counter_offer":
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "invalid_state_transition",
                    "message": (
                        "Counter-offer can only be rejected "
                        "while dispute status is counter_offer"
                    ),
                }
            },
        )

    now = utc_now()

    dispute["status"] = "escalated"
    dispute["updated_at"] = isoformat(now)
    dispute["escalated_at"] = isoformat(now)

    dispute["history"].append(
        {
            "at": dispute["updated_at"],
            "status": "escalated",
            "note": request.reason,
        }
    )

    return dispute