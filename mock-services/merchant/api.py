"""In-memory merchant desk. Polling projects state; it never schedules work."""

import os
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter
from starlette.exceptions import HTTPException

Status = Literal[
    "submitted",
    "under_review",
    "counter_offer",
    "resolved_accepted",
    "escalated",
    "resolved_full",
    "denied",
]
Scenario = Literal["full_refund", "counter_offer", "denied", "slow"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Policy(Model):
    auto_counter_offer: bool
    counter_offer_ratio: float = Field(ge=0, le=1)
    response_delay_seconds: float = Field(ge=0)
    max_refund_usd: float = Field(ge=0)
    escalation_outcome: Literal["resolved_full", "denied"]


class Merchant(Model):
    merchant_id: str
    name: str
    category: str
    support_channel: Literal["api"]
    dispute_policy: Policy


class Evidence(Model):
    type: Literal[
        "invoice", "email", "transaction_history", "subscription_terms", "other"
    ]
    uri: str | None
    description: str


class Claim(Model):
    case_id: str
    merchant_id: str
    user_id: str
    transaction_id: str
    claim_type: Literal[
        "price_hike", "duplicate_charge", "charge_after_cancellation", "other"
    ]
    requested_amount_usd: float
    currency: Literal["USD"]
    message: str
    evidence: list[Evidence]


class Rejection(Model):
    reason: str


class Offer(Model):
    amount_usd: float
    message: str
    expires_at: str


class Resolution(Model):
    outcome: Literal["accepted", "full_refund", "denied"]
    refund_amount_usd: float
    refund_eta_days: int
    closed_at: str


class Transition(Model):
    at: str
    status: Status
    note: str


class Dispute(Model):
    dispute_id: str
    case_id: str
    merchant_id: str
    transaction_id: str
    status: Status
    requested_amount_usd: float
    created_at: str
    updated_at: str
    offer: Offer | None = None
    resolution: Resolution | None = None
    history: list[Transition]


@dataclass
class Record:
    dispute_id: str
    claim: Claim
    policy: Policy
    created_at: datetime
    delay_factor: int
    decision: Literal["accept", "reject"] | None = None
    decision_at: datetime | None = None
    reason: str = ""


def timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def project(record: Record, now: datetime, *, advance: bool = True) -> Dispute:
    """Pure projection: identical record/time => identical timeline, regardless of polls.

    POST responses expose the explicit command (submitted/escalated); subsequent
    GETs materialize every due transition, including when delays are zero.
    """
    claim, policy = record.claim, record.policy
    created = timestamp(record.created_at)
    view = Dispute(
        dispute_id=record.dispute_id,
        case_id=claim.case_id,
        merchant_id=claim.merchant_id,
        transaction_id=claim.transaction_id,
        status="submitted",
        requested_amount_usd=claim.requested_amount_usd,
        created_at=created,
        updated_at=created,
        history=[Transition(at=created, status="submitted", note="Dispute received.")],
    )

    def transition(status: Status, at: datetime, note: str) -> None:
        view.status = status
        view.updated_at = timestamp(at)
        view.offer = None
        view.history.append(Transition(at=timestamp(at), status=status, note=note))

    def resolve(
        outcome: Literal["accepted", "full_refund", "denied"],
        amount: float,
        at: datetime,
    ) -> None:
        status: Status = {
            "accepted": "resolved_accepted",
            "full_refund": "resolved_full",
            "denied": "denied",
        }[outcome]
        note = (
            "The merchant denied the escalated claim; no refund will be issued."
            if outcome == "denied"
            else f"{'Agreed' if outcome == 'accepted' else 'Full'} refund of ${amount:.2f} approved; expected within 5 days."
        )
        transition(status, at, note)
        view.resolution = Resolution(
            outcome=outcome,
            refund_amount_usd=amount,
            refund_eta_days=0 if outcome == "denied" else 5,
            closed_at=timestamp(at),
        )

    if not advance and record.decision is None:
        return view
    review_at = record.created_at + timedelta(seconds=record.delay_factor)
    response_at = review_at + timedelta(
        seconds=policy.response_delay_seconds * record.delay_factor
    )
    if now < review_at:
        return view
    transition(
        "under_review",
        review_at,
        "The merchant is reviewing the claim and supporting evidence.",
    )
    if now < response_at:
        return view
    if not policy.auto_counter_offer:
        resolve("full_refund", claim.requested_amount_usd, response_at)
        return view
    amount = min(
        round(claim.requested_amount_usd * policy.counter_offer_ratio, 2),
        policy.max_refund_usd,
    )
    transition(
        "counter_offer",
        response_at,
        f"The merchant offered ${amount:.2f}. Please accept or request a full refund.",
    )
    view.offer = Offer(
        amount_usd=amount,
        message=f"We can offer a one-time courtesy credit of ${amount:.2f}.",
        expires_at=timestamp(response_at + timedelta(days=7)),
    )
    if record.decision is None:
        return view
    assert record.decision_at is not None
    if record.decision == "accept":
        resolve("accepted", amount, record.decision_at)
    else:
        transition(
            "escalated",
            record.decision_at,
            f"Counter-offer rejected; a specialist will review the full claim. Reason: {record.reason}",
        )
        # Human decisions can arrive much later than creation. Anchor this delay
        # to the decision, not the original response, or late rejection resolves early.
        resolved_at = record.decision_at + timedelta(
            seconds=policy.response_delay_seconds * record.delay_factor
        )
        if advance and now >= resolved_at:
            denied = policy.escalation_outcome == "denied"
            resolve(
                "denied" if denied else "full_refund",
                0.0 if denied else claim.requested_amount_usd,
                resolved_at,
            )
    return view


class APIError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


def create_app(
    dataset_dir: Path | None = None, *, clock: Callable[[], datetime] | None = None
) -> FastAPI:
    now = clock or (lambda: datetime.now(timezone.utc))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        directory = Path(dataset_dir or os.getenv("DATASET_DIR", "./datasets"))
        # Deliberately load only merchants; evaluation labels never enter the API.
        merchants = TypeAdapter(list[Merchant]).validate_json(
            (directory / "merchants.json").read_bytes()
        )
        app.state.merchants = {merchant.merchant_id: merchant for merchant in merchants}
        if len(app.state.merchants) != len(merchants):
            raise ValueError("Duplicate merchant IDs in dataset")
        app.state.disputes = {}
        app.state.sequence = 0
        yield

    app = FastAPI(
        title="ChargeGuard Mock Merchant API", version="1.0.0", lifespan=lifespan
    )

    @app.exception_handler(APIError)
    async def api_error_handler(_, exc):
        return error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_, exc):
        return error(
            422,
            "validation_error",
            "Invalid request body, query parameter or demo header.",
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(_, exc):
        return error(
            exc.status_code,
            {404: "not_found", 405: "method_not_allowed"}.get(
                exc.status_code, "http_error"
            ),
            str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_, exc):
        return error(500, "internal_error", "An unexpected error occurred.")

    def lookup(dispute_id: str) -> Record:
        record = app.state.disputes.get(dispute_id)
        if record is None:
            raise APIError(404, "dispute_not_found", "Dispute not found.")
        return record

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/disputes", response_model=Dispute)
    async def create_dispute(
        claim: Claim,
        x_demo_scenario: Annotated[Scenario | None, Header()] = None,
        x_demo_speed: Annotated[Literal["instant"] | None, Header()] = None,
    ):
        if claim.requested_amount_usd <= 0:
            raise APIError(
                400,
                "invalid_claim_amount",
                "Requested amount must be greater than zero.",
            )
        merchant = app.state.merchants.get(claim.merchant_id)
        if merchant is None:
            raise APIError(404, "merchant_not_found", "Merchant not found.")
        policy = merchant.dispute_policy.model_copy(deep=True)
        if x_demo_scenario == "full_refund":
            policy.auto_counter_offer = False
        elif x_demo_scenario in ("counter_offer", "denied"):
            policy.auto_counter_offer = True
            policy.escalation_outcome = (
                "denied" if x_demo_scenario == "denied" else "resolved_full"
            )
        factor = (
            0 if x_demo_speed == "instant" else (4 if x_demo_scenario == "slow" else 1)
        )
        app.state.sequence += 1
        record = Record(f"dsp_{app.state.sequence:06d}", claim, policy, now(), factor)
        app.state.disputes[record.dispute_id] = record
        return project(record, record.created_at, advance=False)

    @app.get("/disputes", response_model=list[Dispute])
    async def list_disputes(case_id: str | None = None, status: Status | None = None):
        at = now()
        views = [
            project(record, at)
            for record in app.state.disputes.values()
            if case_id is None or record.claim.case_id == case_id
        ]
        return [view for view in views if status is None or view.status == status]

    @app.get("/disputes/{dispute_id}", response_model=Dispute)
    async def get_dispute(dispute_id: str):
        return project(lookup(dispute_id), now())

    def decide(
        dispute_id: str, decision: Literal["accept", "reject"], reason: str = ""
    ) -> Dispute:
        record, at = lookup(dispute_id), now()
        if project(record, at).status != "counter_offer":
            raise APIError(
                409,
                "invalid_state_transition",
                "Only a pending counter-offer can be accepted or rejected.",
            )
        # No awaits between validation and mutation: one worker serializes commands.
        record.decision, record.decision_at, record.reason = decision, at, reason
        return project(record, at, advance=False)

    @app.post("/disputes/{dispute_id}/accept", response_model=Dispute)
    async def accept(dispute_id: str):
        return decide(dispute_id, "accept")

    @app.post("/disputes/{dispute_id}/reject", response_model=Dispute)
    async def reject(dispute_id: str, body: Rejection):
        return decide(dispute_id, "reject", body.reason)

    @app.post("/demo/reset")
    async def reset() -> dict[str, str]:
        app.state.disputes.clear()
        app.state.sequence = 0
        return {"status": "ok"}

    return app
