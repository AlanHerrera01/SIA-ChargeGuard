"""Read-only synthetic bank feed. Only two explicitly named dataset files are read."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, TypeAdapter, field_validator
from starlette.exceptions import HTTPException

WEBHOOK_TIMEOUT_SECONDS = 5.0


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Subscription(Record):
    subscription_id: str
    user_id: str
    merchant_id: str
    plan_name: str
    billing_cycle: Literal["monthly"]
    billing_day: int = Field(ge=1, le=31)
    base_amount_usd: float
    currency: Literal["USD"]
    status: Literal["active", "cancelled"]
    started_at: date
    cancelled_at: date | None
    terms_key: str


class Transaction(Record):
    transaction_id: str
    user_id: str
    subscription_id: str
    merchant_id: str
    merchant_name: str
    amount_usd: float
    currency: Literal["USD"]
    posted_at: str
    description: str
    status: Literal["posted"]
    invoice_key: str

    @field_validator("posted_at")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        if not value.endswith("Z") or "T" not in value:
            raise ValueError("posted_at must be an ISO-8601 UTC timestamp ending in Z")
        datetime.fromisoformat(value)
        return value

    @property
    def sk(self) -> str:
        return f"{self.posted_at}#{self.transaction_id}"


class Page(BaseModel):
    items: list[Transaction]
    next_cursor: str | None


class NotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(min_length=1)
    webhook_url: HttpUrl | None = None


class BankError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


@dataclass
class BankState:
    subscriptions: list[Subscription]
    transactions: list[Transaction]
    by_id: dict[str, Transaction]
    notification_sequence: int = 0

    @classmethod
    def load(cls, directory: Path) -> BankState:
        subscriptions = TypeAdapter(list[Subscription]).validate_json(
            (directory / "subscriptions.json").read_bytes()
        )
        transactions = TypeAdapter(list[Transaction]).validate_json(
            (directory / "transactions.json").read_bytes()
        )
        by_id = {record.transaction_id: record for record in transactions}
        if len(by_id) != len(transactions):
            raise ValueError("Duplicate transaction IDs in dataset")
        # sk breaks timestamp ties without leaking a storage-only field into responses.
        transactions.sort(key=lambda record: record.sk, reverse=True)
        return cls(subscriptions, transactions, by_id)

    def transaction(self, transaction_id: str) -> Transaction:
        if transaction_id not in self.by_id:
            raise BankError(404, "transaction_not_found", "Transaction not found")
        return self.by_id[transaction_id]


def decode_cursor(cursor: str) -> str:
    try:
        raw = base64.b64decode(cursor, altchars=b"-_", validate=True).decode("utf-8")
        timestamp, transaction_id = raw.split("#")
        if not timestamp.endswith("Z") or "T" not in timestamp:
            raise ValueError("Invalid timestamp")
        datetime.fromisoformat(timestamp)
        if not transaction_id.startswith("txn_") or len(transaction_id) <= 4:
            raise ValueError("Invalid transaction ID")
        return raw
    except (ValueError, UnicodeError, binascii.Error):
        raise BankError(400, "invalid_cursor", "Invalid pagination cursor") from None


def error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message}}
    )


def create_app(
    dataset_dir: Path | None = None,
    *,
    webhook_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        directory = Path(dataset_dir or os.environ.get("DATASET_DIR", "./datasets"))
        app.state.dataset_dir = directory.resolve()
        app.state.bank = BankState.load(app.state.dataset_dir)
        app.state.webhook_url = os.environ.get("BACKEND_WEBHOOK_URL")
        async with httpx.AsyncClient(
            timeout=WEBHOOK_TIMEOUT_SECONDS,
            transport=webhook_transport,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            app.state.webhook_client = client
            yield

    app = FastAPI(title="ChargeGuard Mock Bank API", version="0.2.0", lifespan=lifespan)

    @app.exception_handler(BankError)
    async def bank_error_handler(request: Request, exc: BankError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Do not echo request bodies or rejected dataset fields into error responses.
        return error_response(
            422, "validation_error", "Invalid request parameters or body"
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        codes = {404: "not_found", 405: "method_not_allowed"}
        response = error_response(
            exc.status_code, codes.get(exc.status_code, "http_error"), str(exc.detail)
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception):
        return error_response(500, "internal_error", "Internal server error")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "dataset_version": "1"}

    @app.get("/users/{user_id}/subscriptions", response_model=list[Subscription])
    async def subscriptions(user_id: str):
        return [s for s in app.state.bank.subscriptions if s.user_id == user_id]

    @app.get("/users/{user_id}/transactions", response_model=Page)
    async def transactions(
        user_id: str,
        since: date | None = None,
        until: date | None = None,
        merchant_id: str | None = None,
        subscription_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        cursor: Annotated[str | None, Query(max_length=1024)] = None,
    ):
        if since and until and since > until:
            raise BankError(400, "invalid_date_range", "since must not be after until")
        last_sk = decode_cursor(cursor) if cursor is not None else None
        matches = [
            t
            for t in app.state.bank.transactions
            if t.user_id == user_id
            and (merchant_id is None or t.merchant_id == merchant_id)
            and (subscription_id is None or t.subscription_id == subscription_id)
            and (since is None or date.fromisoformat(t.posted_at[:10]) >= since)
            and (until is None or date.fromisoformat(t.posted_at[:10]) <= until)
            and (last_sk is None or t.sk < last_sk)
        ]
        items = matches[:limit]
        next_cursor = None
        if len(matches) > limit:
            next_cursor = base64.urlsafe_b64encode(items[-1].sk.encode()).decode(
                "ascii"
            )
        return Page(items=items, next_cursor=next_cursor)

    @app.get("/transactions/{transaction_id}", response_model=Transaction)
    async def transaction(transaction_id: str):
        return app.state.bank.transaction(transaction_id)

    @app.post("/transactions/notify")
    async def notify(body: NotifyRequest):
        bank = app.state.bank
        record = bank.transaction(body.transaction_id)
        url = str(body.webhook_url) if body.webhook_url else app.state.webhook_url
        if not url:
            return {
                "delivered": False,
                "status_code": None,
                "error": "Webhook URL not configured",
            }
        try:
            url = str(TypeAdapter(HttpUrl).validate_python(url))
        except ValueError:
            return {
                "delivered": False,
                "status_code": None,
                "error": "Invalid webhook configuration",
            }
        bank.notification_sequence += 1
        # Replayable synthetic event clock and IDs; reset restarts the sequence.
        event_key = f"{record.sk}#{bank.notification_sequence}"
        envelope = {
            "event_id": "evt_" + hashlib.sha256(event_key.encode()).hexdigest()[:24],
            "event_type": "transaction.posted",
            "occurred_at": record.posted_at,
            "data": record.model_dump(mode="json"),
        }
        try:
            # HTTPX timeouts bound each phase; wait_for also bounds the entire attempt.
            response = await asyncio.wait_for(
                app.state.webhook_client.post(url, json=envelope),
                timeout=WEBHOOK_TIMEOUT_SECONDS,
            )
        except (TimeoutError, httpx.TimeoutException):
            return {
                "delivered": False,
                "status_code": None,
                "error": "Webhook timed out",
            }
        except httpx.RequestError:
            return {
                "delivered": False,
                "status_code": None,
                "error": "Webhook delivery failed",
            }
        if not response.is_success:
            return {
                "delivered": False,
                "status_code": response.status_code,
                "error": f"Webhook returned HTTP {response.status_code}",
            }
        return {"delivered": True, "status_code": response.status_code}

    @app.post("/demo/reset")
    async def reset():
        try:
            # Replace only after both files validate, keeping a failed reload atomic.
            bank = BankState.load(app.state.dataset_dir)
        except (OSError, ValueError):
            raise BankError(
                503, "dataset_reload_failed", "Could not reload datasets"
            ) from None
        app.state.bank = bank
        return {"status": "ok"}

    return app
