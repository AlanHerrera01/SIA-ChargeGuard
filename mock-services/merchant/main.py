import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel


app = FastAPI(title="Mock Merchant Support API")

DISPUTES: dict[str, dict] = {}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MERCHANTS_PATH = PROJECT_ROOT / "datasets" / "merchants.json"


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


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def error_response(
    status_code: int,
    code: str,
    message: str,
):
    raise HTTPException(
        status_code=status_code,
        detail={
            "error": {
                "code": code,
                "message": message,
            }
        },
    )


def load_merchants() -> list[dict]:
    if not MERCHANTS_PATH.exists():
        return []

    with open(
        MERCHANTS_PATH,
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def get_merchant(
    merchant_id: str,
) -> dict | None:

    merchants = load_merchants()

    return next(
        (
            merchant
            for merchant in merchants
            if merchant["merchant_id"] == merchant_id
        ),
        None,
    )


def get_policy(
    dispute: dict,
) -> dict:

    merchant = get_merchant(
        dispute["merchant_id"]
    )

    if merchant is None:
        error_response(
            status_code=404,
            code="merchant_not_found",
            message="Merchant not found",
        )

    return merchant["dispute_policy"]


def get_effective_delay(
    base_delay_seconds: float,
    demo_speed: str | None,
    demo_scenario: str | None,
) -> float:

    if demo_speed == "instant":
        return 0

    if demo_scenario == "slow":
        return base_delay_seconds * 4

    return base_delay_seconds


def resolve_full(
    dispute: dict,
    note: str,
) -> dict:

    now = utc_now()

    dispute["status"] = "resolved_full"
    dispute["updated_at"] = isoformat(now)
    dispute["offer"] = None

    dispute["resolution"] = {
        "outcome": "full_refund",
        "refund_amount_usd": round(
            dispute["requested_amount_usd"],
            2,
        ),
        "refund_eta_days": 5,
        "closed_at": isoformat(now),
    }

    dispute["history"].append(
        {
            "at": dispute["updated_at"],
            "status": "resolved_full",
            "note": note,
        }
    )

    return dispute


def resolve_denied(
    dispute: dict,
    note: str,
) -> dict:

    now = utc_now()

    dispute["status"] = "denied"
    dispute["updated_at"] = isoformat(now)
    dispute["offer"] = None

    dispute["resolution"] = {
        "outcome": "denied",
        "refund_amount_usd": 0.00,
        "refund_eta_days": 0,
        "closed_at": isoformat(now),
    }

    dispute["history"].append(
        {
            "at": dispute["updated_at"],
            "status": "denied",
            "note": note,
        }
    )

    return dispute


def create_counter_offer(
    dispute: dict,
    policy: dict,
) -> dict:

    requested_amount = float(
        dispute["requested_amount_usd"]
    )

    ratio = float(
        policy["counter_offer_ratio"]
    )

    max_refund = float(
        policy["max_refund_usd"]
    )

    offer_amount = round(
        min(
            requested_amount * ratio,
            max_refund,
        ),
        2,
    )

    now = utc_now()

    dispute["status"] = "counter_offer"
    dispute["updated_at"] = isoformat(now)

    dispute["offer"] = {
        "amount_usd": offer_amount,
        "message": (
            "We can offer a one-time courtesy credit "
            f"of ${offer_amount:.2f}."
        ),
        "expires_at": isoformat(
            now + timedelta(days=7)
        ),
    }

    dispute["resolution"] = None

    dispute["history"].append(
        {
            "at": dispute["updated_at"],
            "status": "counter_offer",
            "note": (
                "Merchant sent a partial refund offer"
            ),
        }
    )

    return dispute


def update_dispute_status(
    dispute: dict,
) -> dict:

    if dispute["status"] in {
        "resolved_accepted",
        "resolved_full",
        "denied",
    }:
        return dispute

    created_at = datetime.fromisoformat(
        dispute["created_at"].replace(
            "Z",
            "+00:00",
        )
    )

    elapsed = (
        utc_now() - created_at
    ).total_seconds()

    policy = get_policy(dispute)

    demo_speed = dispute.get(
        "demo_speed"
    )

    demo_scenario = dispute.get(
        "demo_scenario"
    )

    review_delay = get_effective_delay(
        base_delay_seconds=1,
        demo_speed=demo_speed,
        demo_scenario=demo_scenario,
    )

    response_delay = get_effective_delay(
        base_delay_seconds=float(
            policy[
                "response_delay_seconds"
            ]
        ),
        demo_speed=demo_speed,
        demo_scenario=demo_scenario,
    )

    # ---------------------------------------------------------
    # submitted -> under_review
    # ---------------------------------------------------------

    if (
        elapsed >= review_delay
        and dispute["status"] == "submitted"
    ):
        now = utc_now()

        dispute["status"] = "under_review"
        dispute["updated_at"] = isoformat(now)

        dispute["history"].append(
            {
                "at": dispute["updated_at"],
                "status": "under_review",
                "note": (
                    "Dispute is being reviewed"
                ),
            }
        )

    # ---------------------------------------------------------
    # demo scenario overrides
    # ---------------------------------------------------------

    if (
        dispute["status"] == "under_review"
        and elapsed >= response_delay
    ):

        if demo_scenario == "full_refund":
            return resolve_full(
                dispute,
                "Demo scenario forced full refund",
            )

        if demo_scenario == "denied":
            return resolve_denied(
                dispute,
                "Demo scenario forced denial",
            )

        if demo_scenario == "counter_offer":
            return create_counter_offer(
                dispute,
                policy,
            )

        # -----------------------------------------------------
        # normal merchant policy
        # -----------------------------------------------------

        if not policy[
            "auto_counter_offer"
        ]:
            return resolve_full(
                dispute,
                "Merchant policy approved full refund",
            )

        return create_counter_offer(
            dispute,
            policy,
        )

    # ---------------------------------------------------------
    # escalated -> final merchant outcome
    # ---------------------------------------------------------

    if dispute["status"] == "escalated":

        escalated_at = datetime.fromisoformat(
            dispute[
                "escalated_at"
            ].replace(
                "Z",
                "+00:00",
            )
        )

        escalation_elapsed = (
            utc_now()
            - escalated_at
        ).total_seconds()

        escalation_delay = (
            get_effective_delay(
                base_delay_seconds=float(
                    policy[
                        "response_delay_seconds"
                    ]
                ),
                demo_speed=demo_speed,
                demo_scenario=demo_scenario,
            )
        )

        if (
            escalation_elapsed
            >= escalation_delay
        ):

            outcome = policy[
                "escalation_outcome"
            ]

            if outcome == "resolved_full":
                return resolve_full(
                    dispute,
                    (
                        "Full refund approved "
                        "after escalation"
                    ),
                )

            if outcome == "denied":
                return resolve_denied(
                    dispute,
                    (
                        "Refund denied "
                        "after escalation"
                    ),
                )

    return dispute


@app.get("/health")
def health():
    return {
        "status": "ok",
    }


@app.post("/disputes")
def create_dispute(
    dispute: DisputeRequest,
    x_demo_scenario: str | None = Header(
        default=None,
        alias="X-Demo-Scenario",
    ),
    x_demo_speed: str | None = Header(
        default=None,
        alias="X-Demo-Speed",
    ),
):
    if dispute.requested_amount_usd <= 0:
        error_response(
            status_code=400,
            code="invalid_claim_amount",
            message=(
                "requested_amount_usd "
                "must be greater than 0"
            ),
        )

    merchant = get_merchant(
        dispute.merchant_id
    )

    if merchant is None:
        error_response(
            status_code=404,
            code="merchant_not_found",
            message="Merchant not found",
        )

    allowed_demo_scenarios = {
        None,
        "full_refund",
        "counter_offer",
        "denied",
        "slow",
    }

    if (
        x_demo_scenario
        not in allowed_demo_scenarios
    ):
        error_response(
            status_code=400,
            code="invalid_demo_scenario",
            message=(
                "Unsupported X-Demo-Scenario value"
            ),
        )

    if (
        x_demo_speed
        not in {
            None,
            "instant",
        }
    ):
        error_response(
            status_code=400,
            code="invalid_demo_speed",
            message=(
                "Unsupported X-Demo-Speed value"
            ),
        )

    now = utc_now()

    dispute_id = (
        f"dsp_{uuid4().hex[:6]}"
    )

    dispute_object = {
        "dispute_id": dispute_id,
        "case_id": dispute.case_id,
        "merchant_id": dispute.merchant_id,
        "transaction_id": dispute.transaction_id,
        "status": "submitted",
        "requested_amount_usd": round(
            dispute.requested_amount_usd,
            2,
        ),
        "created_at": isoformat(now),
        "updated_at": isoformat(now),
        "offer": None,
        "resolution": None,
        "history": [
            {
                "at": isoformat(now),
                "status": "submitted",
                "note": (
                    "Dispute received"
                ),
            }
        ],
        "demo_scenario": x_demo_scenario,
        "demo_speed": x_demo_speed,
    }

    DISPUTES[
        dispute_id
    ] = dispute_object

    return dispute_object


@app.get("/disputes")
def list_disputes(
    case_id: str | None = Query(
        default=None
    ),
    status: str | None = Query(
        default=None
    ),
):
    disputes = []

    for dispute in DISPUTES.values():

        updated = update_dispute_status(
            dispute
        )

        if (
            case_id is not None
            and updated[
                "case_id"
            ] != case_id
        ):
            continue

        if (
            status is not None
            and updated[
                "status"
            ] != status
        ):
            continue

        disputes.append(updated)

    return disputes


@app.get("/disputes/{dispute_id}")
def get_dispute(
    dispute_id: str,
):
    dispute = DISPUTES.get(
        dispute_id
    )

    if dispute is None:
        error_response(
            status_code=404,
            code="dispute_not_found",
            message="Dispute not found",
        )

    return update_dispute_status(
        dispute
    )


@app.post(
    "/disputes/{dispute_id}/accept"
)
def accept_counter_offer(
    dispute_id: str,
):
    dispute = DISPUTES.get(
        dispute_id
    )

    if dispute is None:
        error_response(
            status_code=404,
            code="dispute_not_found",
            message="Dispute not found",
        )

    update_dispute_status(
        dispute
    )

    if (
        dispute["status"]
        != "counter_offer"
    ):
        error_response(
            status_code=409,
            code="invalid_state_transition",
            message=(
                "Counter-offer can only be accepted "
                "while dispute status is "
                "counter_offer"
            ),
        )

    now = utc_now()

    offered_amount = dispute[
        "offer"
    ][
        "amount_usd"
    ]

    dispute["status"] = (
        "resolved_accepted"
    )

    dispute["updated_at"] = (
        isoformat(now)
    )

    dispute["resolution"] = {
        "outcome": "accepted",
        "refund_amount_usd": (
            offered_amount
        ),
        "refund_eta_days": 5,
        "closed_at": isoformat(now),
    }

    dispute["history"].append(
        {
            "at": dispute[
                "updated_at"
            ],
            "status": (
                "resolved_accepted"
            ),
            "note": (
                "User accepted merchant "
                f"offer of ${offered_amount:.2f}"
            ),
        }
    )

    return dispute


@app.post(
    "/disputes/{dispute_id}/reject"
)
def reject_counter_offer(
    dispute_id: str,
    request: RejectRequest,
):
    dispute = DISPUTES.get(
        dispute_id
    )

    if dispute is None:
        error_response(
            status_code=404,
            code="dispute_not_found",
            message="Dispute not found",
        )

    update_dispute_status(
        dispute
    )

    if (
        dispute["status"]
        != "counter_offer"
    ):
        error_response(
            status_code=409,
            code="invalid_state_transition",
            message=(
                "Counter-offer can only be rejected "
                "while dispute status is "
                "counter_offer"
            ),
        )

    now = utc_now()

    dispute["status"] = (
        "escalated"
    )

    dispute["updated_at"] = (
        isoformat(now)
    )

    dispute["escalated_at"] = (
        isoformat(now)
    )

    dispute["history"].append(
        {
            "at": dispute[
                "updated_at"
            ],
            "status": "escalated",
            "note": request.reason,
        }
    )

    return dispute


@app.post("/demo/reset")
def reset_demo():
    DISPUTES.clear()

    return {
        "status": "ok",
        "message": (
            "All mock merchant disputes cleared"
        ),
    }