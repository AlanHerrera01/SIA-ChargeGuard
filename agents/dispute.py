from typing import Literal

from pydantic import BaseModel
from strands import Agent

from config import MODEL_ID


class EvidenceItem(BaseModel):
    type: Literal[
        "invoice",
        "email",
        "transaction_history",
        "subscription_terms",
        "other",
    ]
    uri: str | None
    description: str


class DisputeResult(BaseModel):
    case_id: str
    merchant_id: str
    user_id: str
    transaction_id: str

    claim_type: Literal[
        "price_hike",
        "duplicate_charge",
        "charge_after_cancellation",
        "other",
    ]

    requested_amount_usd: float
    currency: str

    message: str
    evidence: list[EvidenceItem]


SYSTEM_PROMPT = """
You are DisputeAgent.

Your job is to prepare a clear and professional billing dispute
using the anomaly analysis and supporting evidence provided.

The dispute must:
- clearly explain the billing issue
- mention the expected and actual charge
- request only the justified refund amount
- reference only evidence that actually exists
- never invent facts
- use plain language suitable for a merchant support team

Return a concise structured result.
"""


dispute_agent = Agent(
    model=MODEL_ID,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,
)


def prepare_dispute(
    case_id: str,
    merchant_id: str,
    merchant_name: str,
    user_id: str,
    transaction_id: str,
    claim_type: str,
    expected_amount_usd: float,
    actual_amount_usd: float,
    requested_amount_usd: float,
    currency: str,
    anomaly_reason: str,
    evidence: list[EvidenceItem],
) -> DisputeResult:

    evidence_text = "\n".join(
        f"- {item.type}: {item.description} | URI: {item.uri}"
        for item in evidence
    )

    prompt = f"""
    Case ID: {case_id}
    Merchant ID: {merchant_id}
    Merchant name: {merchant_name}
    User ID: {user_id}
    Transaction ID: {transaction_id}

    Claim type: {claim_type}
    Expected amount: ${expected_amount_usd}
    Actual amount: ${actual_amount_usd}
    Requested refund: ${requested_amount_usd}
    Currency: {currency}

    Anomaly analysis:
    {anomaly_reason}

    Available evidence:
    {evidence_text}

    Prepare the billing dispute.
    """

    result = dispute_agent(
        prompt,
        structured_output_model=DisputeResult,
    )

    return result.structured_output


if __name__ == "__main__":
    evidence = [
        EvidenceItem(
            type="invoice",
            uri="datasets/invoices/inv_0031.txt",
            description="Current Netflix invoice showing a charge of $19.99.",
        ),
        EvidenceItem(
            type="invoice",
            uri="datasets/invoices/inv_0030.txt",
            description="Previous Netflix invoice showing a charge of $15.49.",
        ),
        EvidenceItem(
            type="transaction_history",
            uri=None,
            description="Five previous Netflix charges were consistently $15.49.",
        ),
        EvidenceItem(
            type="subscription_terms",
            uri="datasets/terms/sub_001.txt",
            description="Subscription terms show the Standard plan price as $15.49.",
        ),
    ]

    result = prepare_dispute(
        case_id="case_demo_001",
        merchant_id="mrc_netflix",
        merchant_name="Netflix",
        user_id="usr_demo",
        transaction_id="txn_0031",
        claim_type="price_hike",
        expected_amount_usd=15.49,
        actual_amount_usd=19.99,
        requested_amount_usd=4.50,
        currency="USD",
        anomaly_reason=(
            "Netflix increased the recurring charge from $15.49 "
            "to $19.99 with no price-change notice found."
        ),
        evidence=evidence,
    )

    print(result)