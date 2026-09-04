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

    previous_invoice_uri: str | None
    current_invoice_uri: str | None
    subscription_terms_uri: str | None

    summary: str


SYSTEM_PROMPT = """
You are EvidenceAgent.

Your job is to summarize evidence already collected for a suspicious
recurring subscription charge.

Possible anomaly types:

- PRICE_INCREASE
- DUPLICATE_CHARGE
- POST_CANCELLATION
- NONE

For PRICE_INCREASE, useful evidence can include:
- previous invoice
- current invoice
- historical transaction amounts
- price change notification emails
- subscription terms

For DUPLICATE_CHARGE, useful evidence can include:
- two transactions for the same subscription
- same merchant
- same amount
- same day or very short time interval
- transaction history
- invoices, if available

Do not invent evidence.

Do not call or attempt to use any tools.
Do not attempt to open or read file paths.
Only reason from the evidence information explicitly provided in the prompt.

Return a concise structured result.
"""


evidence_agent = Agent(
    model=MODEL_ID,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,
)


def search_price_change_notice(merchant_name: str) -> bool:
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

        if merchant_name.lower() in content:
            if any(keyword in content for keyword in keywords):
                return True

    return False


def invoice_exists(invoice_key: str | None) -> bool:
    if not invoice_key:
        return False

    invoice_name = Path(invoice_key).name

    pdf_path = Path("datasets/invoices") / invoice_name
    txt_path = pdf_path.with_suffix(".txt")

    return pdf_path.exists() or txt_path.exists()


def get_local_invoice_uri(
    invoice_key: str | None,
) -> str | None:

    if not invoice_key:
        return None

    invoice_name = Path(invoice_key).name

    pdf_path = Path("datasets/invoices") / invoice_name

    if pdf_path.exists():
        return str(pdf_path)

    txt_path = pdf_path.with_suffix(".txt")

    if txt_path.exists():
        return str(txt_path)

    return None


def subscription_terms_found(
    terms_key: str | None,
) -> bool:

    if not terms_key:
        return False

    terms_name = Path(terms_key).name

    pdf_path = Path("datasets/terms") / terms_name
    txt_path = pdf_path.with_suffix(".txt")

    return pdf_path.exists() or txt_path.exists()


def get_subscription_terms_uri(
    terms_key: str | None,
) -> str | None:

    if not terms_key:
        return None

    terms_name = Path(terms_key).name

    pdf_path = Path("datasets/terms") / terms_name

    if pdf_path.exists():
        return str(pdf_path)

    txt_path = pdf_path.with_suffix(".txt")

    if txt_path.exists():
        return str(txt_path)

    return None


def parse_timestamp(timestamp: str) -> datetime:
    return datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
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
        return False, None, None, None

    same_subscription = (
        previous_transaction["subscription_id"]
        == current_transaction["subscription_id"]
    )

    same_merchant = (
        previous_transaction["merchant_id"]
        == current_transaction["merchant_id"]
    )

    same_amount = (
        previous_transaction["amount_usd"]
        == current_transaction["amount_usd"]
    )

    previous_time = parse_timestamp(
        previous_transaction["posted_at"]
    )

    current_time = parse_timestamp(
        current_transaction["posted_at"]
    )

    seconds_apart = abs(
        (current_time - previous_time).total_seconds()
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
        return False, None, None, None

    return (
        True,
        previous_transaction["transaction_id"],
        current_transaction["amount_usd"],
        seconds_apart,
    )


def gather_evidence(
    anomaly_type: str,
    current_transaction: dict,
    previous_transaction: dict | None,
    terms_key: str | None,
) -> EvidenceResult:

    merchant_id = current_transaction["merchant_id"]
    merchant_name = current_transaction["merchant_name"]
    subscription_id = current_transaction["subscription_id"]
    transaction_id = current_transaction["transaction_id"]

    previous_invoice_key = (
        previous_transaction["invoice_key"]
        if previous_transaction
        else None
    )

    current_invoice_key = current_transaction.get(
        "invoice_key"
    )

    previous_invoice_found = invoice_exists(
        previous_invoice_key
    )

    current_invoice_found = invoice_exists(
        current_invoice_key
    )

    price_change_notice_found = (
        search_price_change_notice(merchant_name)
        if anomaly_type == "PRICE_INCREASE"
        else False
    )

    terms_found = subscription_terms_found(
        terms_key
    )

    previous_invoice_uri = get_local_invoice_uri(
        previous_invoice_key
    )

    current_invoice_uri = get_local_invoice_uri(
        current_invoice_key
    )

    terms_uri = get_subscription_terms_uri(
        terms_key
    )

    (
        duplicate_transaction_found,
        duplicate_transaction_id,
        duplicate_amount_usd,
        duplicate_seconds_apart,
    ) = analyze_duplicate_evidence(
        current_transaction=current_transaction,
        previous_transaction=previous_transaction,
    )

    prompt = f"""
Anomaly type:
{anomaly_type}

Merchant ID:
{merchant_id}

Merchant name:
{merchant_name}

Subscription ID:
{subscription_id}

Current transaction:
{json.dumps(current_transaction, indent=2)}

Previous transaction:
{
    json.dumps(previous_transaction, indent=2)
    if previous_transaction
    else "Not available"
}

Previous invoice found:
{previous_invoice_found}

Current invoice found:
{current_invoice_found}

Price change notice found:
{price_change_notice_found}

Subscription terms found:
{terms_found}

Duplicate transaction found:
{duplicate_transaction_found}

Duplicate transaction ID:
{duplicate_transaction_id}

Duplicate amount:
{duplicate_amount_usd}

Seconds between suspicious transactions:
{duplicate_seconds_apart}

Previous invoice URI:
{previous_invoice_uri}

Current invoice URI:
{current_invoice_uri}

Subscription terms URI:
{terms_uri}

Summarize only the evidence that is actually available
and relevant to the anomaly type.
"""

    result = evidence_agent(
        prompt,
        structured_output_model=EvidenceResult,
    )

    return result.structured_output


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

    # CASO 2: Spotify duplicate charge
    transaction_id = "txn_0044"
    anomaly_type = "DUPLICATE_CHARGE"

    current_transaction = next(
        tx
        for tx in transactions
        if tx["transaction_id"] == transaction_id
    )

    previous_transactions = sorted(
        [
            tx
            for tx in transactions
            if tx["subscription_id"]
            == current_transaction["subscription_id"]
            and tx["posted_at"]
            < current_transaction["posted_at"]
        ],
        key=lambda tx: tx["posted_at"],
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
            if sub["subscription_id"]
            == current_transaction["subscription_id"]
        ),
        None,
    )

    terms_key = (
        subscription.get("terms_key")
        if subscription
        else None
    )

    result = gather_evidence(
        anomaly_type=anomaly_type,
        current_transaction=current_transaction,
        previous_transaction=previous_transaction,
        terms_key=terms_key,
    )

    print(result)