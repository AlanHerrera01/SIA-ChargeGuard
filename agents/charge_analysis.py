import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from strands import Agent

from config import MODEL_ID


class ChargeAnalysisResult(BaseModel):
    is_anomaly: bool
    type: Literal[
        "PRICE_INCREASE",
        "DUPLICATE_CHARGE",
        "POST_CANCELLATION",
        "NONE",
    ]
    expected_amount: float
    actual_amount: float
    difference: float
    confidence: float
    reason: str


SYSTEM_PROMPT = """
You are ChargeAnalysisAgent.

Your job is to analyze recurring subscription charges and determine
whether the current charge is anomalous.

Possible anomaly types:
- PRICE_INCREASE
- DUPLICATE_CHARGE
- POST_CANCELLATION
- NONE

Do not invent missing information.
"""


charge_analysis_agent = Agent(
    model=MODEL_ID,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,
)


def analyze_charge(
    merchant: str,
    current_charge: float,
    previous_charges: list[float],
) -> ChargeAnalysisResult:

    prompt = f"""
    Merchant: {merchant}
    Current charge: ${current_charge}
    Previous charges: {previous_charges}

    Analyze whether this charge is anomalous.
    """

    result = charge_analysis_agent(
        prompt,
        structured_output_model=ChargeAnalysisResult,
    )

    return result.structured_output


if __name__ == "__main__":
    transactions_path = Path("datasets/transactions.json")

    with open(transactions_path, "r", encoding="utf-8") as file:
        transactions = json.load(file)

    merchant_id = "mrc_netflix"

    merchant_transactions = [
        tx
        for tx in transactions
        if tx["merchant_id"] == merchant_id
    ]

    merchant_transactions = sorted(
        merchant_transactions,
        key=lambda tx: tx["posted_at"],
    )

    previous_charges = [
        tx["amount_usd"]
        for tx in merchant_transactions[:-1]
    ]

    current_transaction = merchant_transactions[-1]

    result = analyze_charge(
        merchant=current_transaction["merchant_name"],
        current_charge=current_transaction["amount_usd"],
        previous_charges=previous_charges,
    )

    print(result)