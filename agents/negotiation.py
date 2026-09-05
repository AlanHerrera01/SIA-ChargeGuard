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

Important:
- Evaluate BOTH the anomaly analysis and the collected evidence.
- Do not ignore evidence that supports the user's claim.
- Do not invent missing facts.
- Do not assume that a notice, authorization, cancellation, or other
  evidence exists unless it is explicitly provided.

Do not recommend "escalate" directly.

Escalation happens only after the user explicitly chooses to reject
the merchant's counter-offer.

Return a concise structured recommendation.
"""


negotiation_agent = Agent(
    name="negotiation_agent",
    description=(
        "Evaluates merchant counter-offers and recommends whether the user "
        "should accept the offer or request the full supported refund."
    ),
    model=MODEL_ID,
    system_prompt=SYSTEM_PROMPT,
    callback_handler=None,
)


def evaluate_counter_offer(
    requested_amount_usd: float,
    offered_amount_usd: float,
    dispute_reason: str,
    evidence_summary: str,
) -> NegotiationResult:

    difference_usd = round(
        requested_amount_usd - offered_amount_usd,
        2,
    )

    prompt = f"""
Requested refund:
${requested_amount_usd:.2f}

Merchant counter-offer:
${offered_amount_usd:.2f}

Remaining difference:
${difference_usd:.2f}

Anomaly analysis:
{dispute_reason}

Collected evidence:
{evidence_summary}

Evaluate this counter-offer using BOTH the anomaly analysis
and the collected evidence.

Important:
- Do not make the final decision.
- The user must choose whether to accept or reject.
- Do not recommend escalation directly.
- If the evidence strongly supports the full claim and the merchant
  is offering only a partial amount, recommend
  reject_and_request_full_refund.
- If accepting is recommended, explain why the evidence supports
  accepting less than the full requested amount.
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
            "Netflix increased the recurring subscription charge "
            "from $15.49 to $19.99."
        ),
        evidence_summary=(
            "Five previous recurring charges were $15.49. "
            "The previous and current invoices are available. "
            "Subscription terms are available. "
            "No price-change notification was found."
        ),
    )

    print(result)