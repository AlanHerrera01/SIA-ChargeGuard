from typing import Literal

from pydantic import BaseModel
from strands import Agent

from config import MODEL_ID


class NegotiationResult(BaseModel):
    decision_required: bool

    recommendation: Literal[
        "accept_offer",
        "reject_and_request_full_refund",
    ]

    requested_amount_usd: float
    offered_amount_usd: float
    difference_usd: float

    reason: str


SYSTEM_PROMPT = """
You are NegotiationAgent.

Your job is to evaluate a merchant counter-offer for a billing dispute.

You must never accept or reject an offer on behalf of the user.
The final decision always belongs to the user.

Your recommendation must be one of:

- accept_offer
- reject_and_request_full_refund

Use accept_offer when the merchant's offer is reasonably aligned
with the supported claim.

Use reject_and_request_full_refund when the available evidence
strongly supports the full requested refund and the merchant is
offering only a partial amount.

Do not recommend "escalate" directly.

Escalation happens only after the user explicitly chooses to reject
the merchant's counter-offer.

Return a concise structured recommendation.
"""


negotiation_agent = Agent(
    model=MODEL_ID,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,
)


def evaluate_counter_offer(
    requested_amount_usd: float,
    offered_amount_usd: float,
    dispute_reason: str,
) -> NegotiationResult:

    difference_usd = round(
        requested_amount_usd - offered_amount_usd,
        2,
    )

    prompt = f"""
    Requested refund: ${requested_amount_usd}
    Merchant counter-offer: ${offered_amount_usd}
    Remaining difference: ${difference_usd}

    Dispute reason:
    {dispute_reason}

    Evaluate this counter-offer.

    Important:
    - Do not make the final decision.
    - The user must choose whether to accept or reject.
    - Do not recommend escalation directly.
    - If rejecting is recommended, use
      reject_and_request_full_refund.
    """

    result = negotiation_agent(
        prompt,
        structured_output_model=NegotiationResult,
    )

    return result.structured_output


if __name__ == "__main__":
    result = evaluate_counter_offer(
        requested_amount_usd=4.50,
        offered_amount_usd=2.70,
        dispute_reason=(
            "Netflix increased the subscription charge from "
            "$15.49 to $19.99 and no price-change notice was found."
        ),
    )

    print(result)