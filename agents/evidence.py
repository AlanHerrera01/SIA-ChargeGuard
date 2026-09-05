import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from strands import Agent

from config import MODEL_ID


class EvidenceResult(BaseModel):
    merchant_id: str
    merchant_name: str
    subscription_id: str
    transaction_id: str

    anomaly_type: Literal[
        "PRICE_INCREASE",
        "DUPLICATE_CHARGE",
        "POST_CANCELLATION",
        "NONE",
    ]

    previous_invoice_found: bool
    current_invoice_found: bool
    price_change_notice_found: bool
    subscription_terms_found: bool

    duplicate_transaction_found: bool
    duplicate_transaction_id: str | None
    duplicate_amount_usd: float | None
    duplicate_seconds_apart: float | None

    cancellation_confirmation_found: bool
    cancellation_email_uri: str | None
    cancelled_at: str | None
    days_after_cancellation: int | None

    previous_invoice_uri: str | None
    current_invoice_uri: str | None
    subscription_terms_uri: str | None

    summary: str


# -------------------------------------------------------------------
# STRANDS SPECIALIST
#
# We keep this Agent registered so EvidenceAgent still exists as one
# of the specialized tools available to ChargeGuardOrchestrator.
#
# The deterministic production flow does NOT need to invoke Sonnet
# just to calculate evidence that Python can establish reliably.
# -------------------------------------------------------------------

SYSTEM_PROMPT = """
You are EvidenceAgent.

You specialize in reasoning about evidence for suspicious recurring
subscription charges.

Possible anomaly types:

- PRICE_INCREASE
- DUPLICATE_CHARGE
- POST_CANCELLATION
- NONE

You must never invent evidence, IDs, dates, amounts, files,
notifications or subscription facts.

Only reason from explicitly provided information.
"""


evidence_agent = Agent(
    name="evidence_agent",
    description=(
        "Investigates and reasons about supporting evidence for a "
        "subscription billing anomaly, including invoices, emails, "
        "transaction history, cancellation evidence and subscription terms."
    ),
    model=MODEL_ID,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,
)


# -------------------------------------------------------------------
# EMAIL EVIDENCE
# -------------------------------------------------------------------

def search_price_change_notice(
    merchant_name: str,
) -> bool:

    emails_path = Path("datasets/emails")

    if not emails_path.exists():
        return False

    keywords = [
        "price increase",
        "price change",
        "new price",
        "pricing update",
        "rate change",
    ]

    for email_file in emails_path.glob("*.eml"):

        content = email_file.read_text(
            encoding="utf-8",
            errors="ignore",
        ).lower()

        merchant_matches = (
            merchant_name.lower() in content
        )

        price_change_matches = any(
            keyword in content
            for keyword in keywords
        )

        if (
            merchant_matches
            and price_change_matches
        ):
            return True

    return False


def search_cancellation_confirmation(
    subscription_id: str,
    merchant_name: str,
) -> tuple[bool, str | None]:

    emails_path = Path("datasets/emails")

    if not emails_path.exists():
        return False, None

    cancellation_keywords = [
        "cancelled",
        "canceled",
        "cancellation",
        "subscription has been cancelled",
        "subscription has been canceled",
        "will not renew",
        "no future recurring charges",
    ]

    for email_file in emails_path.glob("*.eml"):

        content = email_file.read_text(
            encoding="utf-8",
            errors="ignore",
        ).lower()

        subscription_matches = (
            subscription_id.lower()
            in content
        )

        merchant_matches = (
            merchant_name.lower()
            in content
        )

        cancellation_matches = any(
            keyword in content
            for keyword in cancellation_keywords
        )

        if (
            cancellation_matches
            and (
                subscription_matches
                or merchant_matches
            )
        ):
            return True, str(email_file)

    return False, None


# -------------------------------------------------------------------
# INVOICES
# -------------------------------------------------------------------

def invoice_exists(
    invoice_key: str | None,
) -> bool:

    if not invoice_key:
        return False

    invoice_name = Path(
        invoice_key
    ).name

    pdf_path = (
        Path("datasets/invoices")
        / invoice_name
    )

    txt_path = pdf_path.with_suffix(
        ".txt"
    )

    return (
        pdf_path.exists()
        or txt_path.exists()
    )


def get_local_invoice_uri(
    invoice_key: str | None,
) -> str | None:

    if not invoice_key:
        return None

    invoice_name = Path(
        invoice_key
    ).name

    pdf_path = (
        Path("datasets/invoices")
        / invoice_name
    )

    if pdf_path.exists():
        return str(pdf_path)

    txt_path = pdf_path.with_suffix(
        ".txt"
    )

    if txt_path.exists():
        return str(txt_path)

    return None


# -------------------------------------------------------------------
# SUBSCRIPTION TERMS
# -------------------------------------------------------------------

def subscription_terms_found(
    terms_key: str | None,
) -> bool:

    if not terms_key:
        return False

    terms_name = Path(
        terms_key
    ).name

    pdf_path = (
        Path("datasets/terms")
        / terms_name
    )

    txt_path = pdf_path.with_suffix(
        ".txt"
    )

    return (
        pdf_path.exists()
        or txt_path.exists()
    )


def get_subscription_terms_uri(
    terms_key: str | None,
) -> str | None:

    if not terms_key:
        return None

    terms_name = Path(
        terms_key
    ).name

    pdf_path = (
        Path("datasets/terms")
        / terms_name
    )

    if pdf_path.exists():
        return str(pdf_path)

    txt_path = pdf_path.with_suffix(
        ".txt"
    )

    if txt_path.exists():
        return str(txt_path)

    return None


# -------------------------------------------------------------------
# DATE / TRANSACTION HELPERS
# -------------------------------------------------------------------

def parse_timestamp(
    timestamp: str,
) -> datetime:

    return datetime.fromisoformat(
        timestamp.replace(
            "Z",
            "+00:00",
        )
    )


def analyze_duplicate_evidence(
    current_transaction: dict,
    previous_transaction: dict | None,
) -> tuple[
    bool,
    str | None,
    float | None,
    float | None,
]:

    if previous_transaction is None:
        return (
            False,
            None,
            None,
            None,
        )

    same_subscription = (
        previous_transaction[
            "subscription_id"
        ]
        == current_transaction[
            "subscription_id"
        ]
    )

    same_merchant = (
        previous_transaction[
            "merchant_id"
        ]
        == current_transaction[
            "merchant_id"
        ]
    )

    same_amount = (
        previous_transaction[
            "amount_usd"
        ]
        == current_transaction[
            "amount_usd"
        ]
    )

    previous_time = parse_timestamp(
        previous_transaction[
            "posted_at"
        ]
    )

    current_time = parse_timestamp(
        current_transaction[
            "posted_at"
        ]
    )

    seconds_apart = abs(
        (
            current_time
            - previous_time
        ).total_seconds()
    )

    same_day = (
        previous_time.date()
        == current_time.date()
    )

    duplicate_found = (
        same_subscription
        and same_merchant
        and same_amount
        and same_day
        and seconds_apart <= 3600
    )

    if not duplicate_found:
        return (
            False,
            None,
            None,
            None,
        )

    return (
        True,
        previous_transaction[
            "transaction_id"
        ],
        current_transaction[
            "amount_usd"
        ],
        seconds_apart,
    )


def calculate_days_after_cancellation(
    cancelled_at: str | None,
    posted_at: str,
) -> int | None:

    if not cancelled_at:
        return None

    cancellation_date = (
        datetime.fromisoformat(
            cancelled_at
        ).date()
    )

    transaction_date = (
        parse_timestamp(
            posted_at
        ).date()
    )

    return (
        transaction_date
        - cancellation_date
    ).days


# -------------------------------------------------------------------
# DETERMINISTIC SUMMARY
#
# This replaces the previous Sonnet call.
# -------------------------------------------------------------------

def build_evidence_summary(
    anomaly_type: str,
    current_transaction: dict,
    previous_transaction: dict | None,
    previous_invoice_found: bool,
    current_invoice_found: bool,
    price_change_notice_found: bool,
    terms_found: bool,
    duplicate_transaction_found: bool,
    duplicate_transaction_id: str | None,
    duplicate_seconds_apart: float | None,
    cancellation_confirmation_found: bool,
    cancelled_at: str | None,
    days_after_cancellation: int | None,
    subscription: dict | None,
) -> str:

    merchant_name = (
        current_transaction[
            "merchant_name"
        ]
    )

    subscription_id = (
        current_transaction[
            "subscription_id"
        ]
    )

    transaction_id = (
        current_transaction[
            "transaction_id"
        ]
    )

    amount = float(
        current_transaction[
            "amount_usd"
        ]
    )

    currency = (
        current_transaction[
            "currency"
        ]
    )

    # ---------------------------------------------------------
    # PRICE INCREASE
    # ---------------------------------------------------------

    if anomaly_type == "PRICE_INCREASE":

        previous_amount = None

        if previous_transaction:
            previous_amount = float(
                previous_transaction[
                    "amount_usd"
                ]
            )

        parts = []

        if previous_amount is not None:
            parts.append(
                (
                    f"The previous recurring charge "
                    f"for {merchant_name} was "
                    f"${previous_amount:.2f} {currency}, "
                    f"while transaction {transaction_id} "
                    f"charged ${amount:.2f} {currency}."
                )
            )

        if (
            previous_invoice_found
            and current_invoice_found
        ):
            parts.append(
                "Previous and current invoices are available."
            )
        elif current_invoice_found:
            parts.append(
                "The current invoice is available."
            )
        elif previous_invoice_found:
            parts.append(
                "The previous invoice is available."
            )

        if price_change_notice_found:
            parts.append(
                "A price-change notification was found."
            )
        else:
            parts.append(
                "No price-change notification was found."
            )

        if terms_found:
            parts.append(
                "Subscription terms are available."
            )

        return " ".join(parts)

    # ---------------------------------------------------------
    # DUPLICATE CHARGE
    # ---------------------------------------------------------

    if anomaly_type == "DUPLICATE_CHARGE":

        parts = []

        if (
            duplicate_transaction_found
            and duplicate_transaction_id
            and previous_transaction
        ):
            parts.append(
                (
                    f"Transactions "
                    f"{duplicate_transaction_id} "
                    f"and {transaction_id} charged "
                    f"${amount:.2f} {currency} "
                    f"for the same {merchant_name} "
                    f"subscription."
                )
            )

            if duplicate_seconds_apart is not None:
                parts.append(
                    (
                        f"The charges occurred "
                        f"{duplicate_seconds_apart:.0f} "
                        f"seconds apart."
                    )
                )

        if (
            previous_invoice_found
            and current_invoice_found
        ):
            parts.append(
                "Invoices for both transactions are available."
            )
        elif current_invoice_found:
            parts.append(
                "The current transaction invoice is available."
            )
        elif previous_invoice_found:
            parts.append(
                "The previous transaction invoice is available."
            )

        return " ".join(parts)

    # ---------------------------------------------------------
    # POST CANCELLATION
    # ---------------------------------------------------------

    if anomaly_type == "POST_CANCELLATION":

        parts = []

        if cancelled_at:
            parts.append(
                (
                    f"{merchant_name} subscription "
                    f"{subscription_id} was cancelled "
                    f"on {cancelled_at}."
                )
            )

        parts.append(
            (
                f"Transaction {transaction_id} "
                f"charged ${amount:.2f} {currency} "
                f"on {current_transaction['posted_at']}."
            )
        )

        if days_after_cancellation is not None:
            parts.append(
                (
                    f"The charge occurred "
                    f"{days_after_cancellation} days "
                    f"after cancellation."
                )
            )

        if cancellation_confirmation_found:
            parts.append(
                "A cancellation confirmation email is available."
            )
        else:
            parts.append(
                "No cancellation confirmation email was found."
            )

        if subscription:
            status = subscription.get(
                "status"
            )

            if status:
                parts.append(
                    (
                        f"The subscription status is "
                        f"{status}."
                    )
                )

        if current_invoice_found:
            parts.append(
                "The post-cancellation invoice is available."
            )

        if terms_found:
            parts.append(
                "Subscription terms are available."
            )

        return " ".join(parts)

    return (
        "No relevant anomaly evidence "
        "was identified."
    )


# -------------------------------------------------------------------
# MAIN EVIDENCE PIPELINE
# -------------------------------------------------------------------

def gather_evidence(
    anomaly_type: str,
    current_transaction: dict,
    previous_transaction: dict | None,
    terms_key: str | None,
    subscription: dict | None = None,
) -> EvidenceResult:

    merchant_id = (
        current_transaction[
            "merchant_id"
        ]
    )

    merchant_name = (
        current_transaction[
            "merchant_name"
        ]
    )

    subscription_id = (
        current_transaction[
            "subscription_id"
        ]
    )

    transaction_id = (
        current_transaction[
            "transaction_id"
        ]
    )

    previous_invoice_key = (
        previous_transaction.get(
            "invoice_key"
        )
        if previous_transaction
        else None
    )

    current_invoice_key = (
        current_transaction.get(
            "invoice_key"
        )
    )

    previous_invoice_found = (
        invoice_exists(
            previous_invoice_key
        )
    )

    current_invoice_found = (
        invoice_exists(
            current_invoice_key
        )
    )

    price_change_notice_found = (
        search_price_change_notice(
            merchant_name
        )
        if anomaly_type
        == "PRICE_INCREASE"
        else False
    )

    terms_found = (
        subscription_terms_found(
            terms_key
        )
    )

    previous_invoice_uri = (
        get_local_invoice_uri(
            previous_invoice_key
        )
    )

    current_invoice_uri = (
        get_local_invoice_uri(
            current_invoice_key
        )
    )

    terms_uri = (
        get_subscription_terms_uri(
            terms_key
        )
    )

    (
        duplicate_transaction_found,
        duplicate_transaction_id,
        duplicate_amount_usd,
        duplicate_seconds_apart,
    ) = analyze_duplicate_evidence(
        current_transaction=(
            current_transaction
        ),
        previous_transaction=(
            previous_transaction
        ),
    )

    cancellation_confirmation_found = False
    cancellation_email_uri = None
    cancelled_at = None
    days_after_cancellation = None

    if (
        anomaly_type
        == "POST_CANCELLATION"
        and subscription
    ):

        cancelled_at = (
            subscription.get(
                "cancelled_at"
            )
        )

        (
            cancellation_confirmation_found,
            cancellation_email_uri,
        ) = search_cancellation_confirmation(
            subscription_id=(
                subscription_id
            ),
            merchant_name=(
                merchant_name
            ),
        )

        days_after_cancellation = (
            calculate_days_after_cancellation(
                cancelled_at=(
                    cancelled_at
                ),
                posted_at=(
                    current_transaction[
                        "posted_at"
                    ]
                ),
            )
        )

    summary = build_evidence_summary(
        anomaly_type=anomaly_type,
        current_transaction=(
            current_transaction
        ),
        previous_transaction=(
            previous_transaction
        ),
        previous_invoice_found=(
            previous_invoice_found
        ),
        current_invoice_found=(
            current_invoice_found
        ),
        price_change_notice_found=(
            price_change_notice_found
        ),
        terms_found=terms_found,
        duplicate_transaction_found=(
            duplicate_transaction_found
        ),
        duplicate_transaction_id=(
            duplicate_transaction_id
        ),
        duplicate_seconds_apart=(
            duplicate_seconds_apart
        ),
        cancellation_confirmation_found=(
            cancellation_confirmation_found
        ),
        cancelled_at=cancelled_at,
        days_after_cancellation=(
            days_after_cancellation
        ),
        subscription=subscription,
    )

    return EvidenceResult(
        merchant_id=merchant_id,
        merchant_name=merchant_name,
        subscription_id=subscription_id,
        transaction_id=transaction_id,
        anomaly_type=anomaly_type,

        previous_invoice_found=(
            previous_invoice_found
        ),

        current_invoice_found=(
            current_invoice_found
        ),

        price_change_notice_found=(
            price_change_notice_found
        ),

        subscription_terms_found=(
            terms_found
        ),

        duplicate_transaction_found=(
            duplicate_transaction_found
        ),

        duplicate_transaction_id=(
            duplicate_transaction_id
        ),

        duplicate_amount_usd=(
            duplicate_amount_usd
        ),

        duplicate_seconds_apart=(
            duplicate_seconds_apart
        ),

        cancellation_confirmation_found=(
            cancellation_confirmation_found
        ),

        cancellation_email_uri=(
            cancellation_email_uri
        ),

        cancelled_at=(
            cancelled_at
        ),

        days_after_cancellation=(
            days_after_cancellation
        ),

        previous_invoice_uri=(
            previous_invoice_uri
        ),

        current_invoice_uri=(
            current_invoice_uri
        ),

        subscription_terms_uri=(
            terms_uri
        ),

        summary=summary,
    )


# -------------------------------------------------------------------
# MANUAL DEVELOPMENT TEST
# -------------------------------------------------------------------

if __name__ == "__main__":

    transactions_path = Path(
        "datasets/transactions.json"
    )

    subscriptions_path = Path(
        "datasets/subscriptions.json"
    )

    with open(
        transactions_path,
        "r",
        encoding="utf-8",
    ) as file:
        transactions = json.load(file)

    with open(
        subscriptions_path,
        "r",
        encoding="utf-8",
    ) as file:
        subscriptions = json.load(file)

    transaction_id = "txn_0053"
    anomaly_type = "POST_CANCELLATION"

    current_transaction = next(
        tx
        for tx in transactions
        if tx["transaction_id"]
        == transaction_id
    )

    previous_transactions = sorted(
        [
            tx
            for tx in transactions
            if (
                tx["subscription_id"]
                == current_transaction[
                    "subscription_id"
                ]
                and tx["posted_at"]
                < current_transaction[
                    "posted_at"
                ]
            )
        ],
        key=lambda tx: tx[
            "posted_at"
        ],
    )

    previous_transaction = (
        previous_transactions[-1]
        if previous_transactions
        else None
    )

    subscription = next(
        (
            sub
            for sub in subscriptions
            if (
                sub["subscription_id"]
                == current_transaction[
                    "subscription_id"
                ]
            )
        ),
        None,
    )

    terms_key = (
        subscription.get(
            "terms_key"
        )
        if subscription
        else None
    )

    result = gather_evidence(
        anomaly_type=anomaly_type,
        current_transaction=(
            current_transaction
        ),
        previous_transaction=(
            previous_transaction
        ),
        terms_key=terms_key,
        subscription=subscription,
    )

    print(result)