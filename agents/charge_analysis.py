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

Your job is to analyze recurring subscription transactions and determine
whether the current transaction is anomalous.

Possible anomaly types:

- PRICE_INCREASE:
  The current recurring charge is higher than the established historical
  amount for the same subscription.

- DUPLICATE_CHARGE:
  The same subscription was charged twice for the same amount within a
  very short period of time, indicating that the second charge may be
  duplicated.

- POST_CANCELLATION:
  A subscription was charged after it had already been cancelled.

- NONE:
  No anomaly is supported by the available information.

Important rules:

- Use only the information provided.
- Do not invent missing information.
- A duplicate charge should normally claim the FULL duplicated amount.
- For a price increase, the difference should represent the increase
  above the expected historical amount.
- If there is insufficient evidence for an anomaly, return NONE.
"""


charge_analysis_agent = Agent(
    model=MODEL_ID,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,
)


def analyze_charge(
    current_transaction: dict,
    previous_transactions: list[dict],
    subscription: dict | None = None,
) -> ChargeAnalysisResult:

    prompt = f"""
Current transaction:
{json.dumps(current_transaction, indent=2)}

Previous transactions for the same subscription:
{json.dumps(previous_transactions, indent=2)}

Subscription information:
{json.dumps(subscription, indent=2) if subscription else "Not provided"}

Analyze the CURRENT transaction.

Determine whether it is:
- PRICE_INCREASE
- DUPLICATE_CHARGE
- POST_CANCELLATION
- NONE

Return the appropriate monetary values:

For PRICE_INCREASE:
- expected_amount = normal historical charge
- actual_amount = current charge
- difference = actual_amount - expected_amount

For DUPLICATE_CHARGE:
- expected_amount = one normal legitimate charge
- actual_amount = current duplicated charge
- difference = full amount of the duplicated charge

For POST_CANCELLATION:
- expected_amount = 0
- actual_amount = charge after cancellation
- difference = full amount of that charge
"""

    result = charge_analysis_agent(
        prompt,
        structured_output_model=ChargeAnalysisResult,
    )

    return result.structured_output


if __name__ == "__main__":
    transactions_path = Path("datasets/transactions.json")
    subscriptions_path = Path("datasets/subscriptions.json")

    with open(transactions_path, "r", encoding="utf-8") as file:
        transactions = json.load(file)

    with open(subscriptions_path, "r", encoding="utf-8") as file:
        subscriptions = json.load(file)

    # Cambia este ID para probar cada escenario.
    transaction_id = "txn_0044"

    current_transaction = next(
        tx
        for tx in transactions
        if tx["transaction_id"] == transaction_id
    )

    subscription_id = current_transaction["subscription_id"]

    previous_transactions = sorted(
        [
            tx
            for tx in transactions
            if tx["subscription_id"] == subscription_id
            and tx["posted_at"] < current_transaction["posted_at"]
        ],
        key=lambda tx: tx["posted_at"],
    )

    subscription = next(
        (
            sub
            for sub in subscriptions
            if sub["subscription_id"] == subscription_id
        ),
        None,
    )

    result = analyze_charge(
        current_transaction=current_transaction,
        previous_transactions=previous_transactions,
        subscription=subscription,
    )

    print(result)