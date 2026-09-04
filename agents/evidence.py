import json
from pathlib import Path

from pydantic import BaseModel
from strands import Agent

from config import MODEL_ID


class EvidenceResult(BaseModel):
    merchant_id: str
    merchant_name: str
    subscription_id: str
    transaction_id: str

    previous_invoice_found: bool
    current_invoice_found: bool
    price_change_notice_found: bool
    subscription_terms_found: bool

    previous_invoice_uri: str | None
    current_invoice_uri: str | None
    subscription_terms_uri: str | None

    summary: str


SYSTEM_PROMPT = """
You are EvidenceAgent.

Your job is to investigate a suspicious recurring subscription charge
and summarize the supporting evidence that is available.

You may evaluate:
- previous invoices
- current invoice
- price change notification emails
- subscription terms

Do not invent evidence that is not provided.

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


def get_local_invoice_uri(invoice_key: str | None) -> str | None:
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


def subscription_terms_found(terms_key: str | None) -> bool:
    if not terms_key:
        return False

    terms_name = Path(terms_key).name

    pdf_path = Path("datasets/terms") / terms_name

    if pdf_path.exists():
        return True

    txt_path = pdf_path.with_suffix(".txt")

    return txt_path.exists()


def get_subscription_terms_uri(terms_key: str | None) -> str | None:
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


def gather_evidence(
    merchant_id: str,
    merchant_name: str,
    subscription_id: str,
    transaction_id: str,
    previous_invoice_key: str | None,
    current_invoice_key: str | None,
    terms_key: str | None,
) -> EvidenceResult:

    previous_invoice_found = invoice_exists(previous_invoice_key)
    current_invoice_found = invoice_exists(current_invoice_key)

    price_change_notice_found = search_price_change_notice(
        merchant_name
    )

    terms_found = subscription_terms_found(terms_key)

    previous_invoice_uri = get_local_invoice_uri(
        previous_invoice_key
    )

    current_invoice_uri = get_local_invoice_uri(
        current_invoice_key
    )

    terms_uri = get_subscription_terms_uri(
        terms_key
    )

    prompt = f"""
    Merchant ID: {merchant_id}
    Merchant name: {merchant_name}
    Subscription ID: {subscription_id}
    Transaction ID: {transaction_id}

    Previous invoice found: {previous_invoice_found}
    Current invoice found: {current_invoice_found}
    Price change notice found: {price_change_notice_found}
    Subscription terms found: {terms_found}

    Previous invoice URI: {previous_invoice_uri}
    Current invoice URI: {current_invoice_uri}
    Subscription terms URI: {terms_uri}

    Summarize the available evidence for this suspicious charge.
    """

    result = evidence_agent(
        prompt,
        structured_output_model=EvidenceResult,
    )

    return result.structured_output


if __name__ == "__main__":
    transactions_path = Path("datasets/transactions.json")
    subscriptions_path = Path("datasets/subscriptions.json")

    with open(transactions_path, "r", encoding="utf-8") as file:
        transactions = json.load(file)

    with open(subscriptions_path, "r", encoding="utf-8") as file:
        subscriptions = json.load(file)

    transaction = next(
        tx
        for tx in transactions
        if tx["transaction_id"] == "txn_0031"
    )

    subscription = next(
        sub
        for sub in subscriptions
        if sub["subscription_id"] == transaction["subscription_id"]
    )

    previous_transactions = sorted(
        [
            tx
            for tx in transactions
            if tx["subscription_id"] == transaction["subscription_id"]
            and tx["posted_at"] < transaction["posted_at"]
        ],
        key=lambda tx: tx["posted_at"],
    )

    previous_transaction = (
        previous_transactions[-1]
        if previous_transactions
        else None
    )

    result = gather_evidence(
        merchant_id=transaction["merchant_id"],
        merchant_name=transaction["merchant_name"],
        subscription_id=transaction["subscription_id"],
        transaction_id=transaction["transaction_id"],
        previous_invoice_key=(
            previous_transaction["invoice_key"]
            if previous_transaction
            else None
        ),
        current_invoice_key=transaction["invoice_key"],
        terms_key=subscription["terms_key"],
    )

    print(result)