from strands import Agent

from config import MODEL_ID

from agents.charge_analysis import charge_analysis_agent
from agents.evidence import evidence_agent
from agents.dispute import dispute_agent
from agents.negotiation import negotiation_agent


ORCHESTRATOR_SYSTEM_PROMPT = """
You are ChargeGuardOrchestrator.

You coordinate specialized agents for recurring subscription
billing disputes.

Available specialists:

- charge_analysis:
  analyzes suspicious recurring charges.

- evidence_investigation:
  reviews and summarizes supporting evidence.

- dispute_drafting:
  writes professional billing dispute messages.

- counter_offer_evaluation:
  evaluates merchant counter-offers while preserving
  the user's final authority.

Important rules:

- Never invent transaction IDs, merchant IDs, dates, amounts or evidence.
- Never change validated refund amounts.
- Never accept or reject merchant offers on behalf of the user.
- Contract-critical values remain controlled by deterministic code.
- Human approval is required for merchant counter-offers.
"""


chargeguard_orchestrator_agent = Agent(
    name="chargeguard_orchestrator",
    description=(
        "Coordinates ChargeGuard specialized agents for recurring "
        "subscription billing disputes."
    ),
    model=MODEL_ID,
    system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
    tools=[
        charge_analysis_agent.as_tool(
            name="charge_analysis",
            description=(
                "Analyze a recurring subscription transaction "
                "for billing anomalies."
            ),
        ),
        evidence_agent.as_tool(
            name="evidence_investigation",
            description=(
                "Review and summarize available evidence "
                "for a billing anomaly."
            ),
        ),
        dispute_agent.as_tool(
            name="dispute_drafting",
            description=(
                "Draft a billing dispute using validated "
                "facts and supporting evidence."
            ),
        ),
        negotiation_agent.as_tool(
            name="counter_offer_evaluation",
            description=(
                "Evaluate a merchant counter-offer while "
                "leaving the final decision to the user."
            ),
        ),
    ],
    callback_handler=None,
)


if __name__ == "__main__":
    print("ChargeGuard Strands Orchestrator")
    print("Registered agent tools:")

    for tool_name in chargeguard_orchestrator_agent.tool_names:
        print(f"- {tool_name}")