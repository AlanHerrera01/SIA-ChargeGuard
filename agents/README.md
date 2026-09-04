# Agents

Strands Agents SDK implementation. Multi-agent architecture using the *Agents-as-Tools* pattern.

## Owner
Stephani Rivera

## Structure
- `orchestrator.py` - `DisputeOrchestrator` (coordinates sub-agents)
- `charge_analysis.py` - `ChargeAnalysisAgent` (detects anomalies)
- `evidence.py` - `EvidenceAgent` (gathers supporting artifacts)
- `dispute.py` - `DisputeAgent` (files and monitors disputes)
- `negotiation.py` - `NegotiationAgent` (evaluates counter-offers)

## Model
`anthropic.claude-sonnet-5` via Amazon Bedrock.
