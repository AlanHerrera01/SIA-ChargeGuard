# ChargeGuard

> Sleep through the price hike. Wake up to a refund.

**ChargeGuard** is an autonomous AI agent that monitors your recurring subscription charges, detects anomalies like silent price hikes and double charges, gathers evidence, and negotiates refunds with merchants on your behalf. It only surfaces you when there's a real decision to make.

Built for the [AWS Agents for Humans Hackathon 2026](https://agentsforhumans.devpost.com/) - **Everyday Agents** track.

---

## Table of Contents

1. [Problem](#problem)
2. [Solution](#solution)
3. [Target Users](#target-users)
4. [How It Works](#how-it-works)
5. [Architecture](#architecture)
6. [Strands Implementation](#strands-implementation)
7. [AWS Services Used](#aws-services-used)
8. [Human-in-the-Loop Design](#human-in-the-loop-design)
9. [Local Setup](#local-setup)
10. [AWS Deployment](#aws-deployment)
11. [Demo Scenario](#demo-scenario)
12. [Privacy & Safety](#privacy--safety)
13. [Demo Credentials](#demo-credentials)
14. [Future Work](#future-work)
15. [Team](#team)
16. [License](#license)

---

## Problem

*[TBD - fill in as we build]*

## Solution

*[TBD]*

## Target Users

Anyone with recurring subscriptions (streaming, cloud storage, SaaS tools, gym memberships) who has ever noticed a surprise charge and didn't have the time or energy to fight it.

## How It Works

*[TBD - include GIF of the flow]*

## Architecture

*[TBD - insert architecture diagram from docs/architecture.png]*

## Strands Implementation

*[TBD - describe multi-agent orchestration pattern]*

## AWS Services Used

- Amazon Bedrock (Claude Sonnet 5)
- Amazon Bedrock AgentCore Runtime
- Amazon DynamoDB
- Amazon S3
- Amazon EventBridge
- AWS Lambda
- Amazon API Gateway
- AWS Amplify Hosting
- Amazon CloudWatch

## Human-in-the-Loop Design

The agent acts autonomously for:
- Detecting anomalies
- Gathering evidence
- Filing initial disputes
- Polling merchant responses

The agent **always** pauses and asks the user when:
- The merchant responds with a counter-offer
- Confidence in the anomaly is below threshold
- The disputed amount exceeds a configurable limit

## Local Setup

*[TBD - full docker-compose instructions]*

Quick start:
```bash
git clone https://github.com/AlanHerrera01/SIA-ChargeGuard.git
cd SIA-ChargeGuard
cp .env.example .env
# fill in .env
docker-compose up
```

## AWS Deployment

*[TBD - Terraform instructions]*

## Demo Scenario

*[TBD - step-by-step walkthrough for judges]*

## Privacy & Safety

- All data used in the demo is synthetic.
- ChargeGuard does not perform bank-level fraud disputes.
- The agent never claims fraud or wrongdoing - only requests review of anomalous charges.
- Users always have the final say on whether to accept a settlement or escalate.

## Demo Credentials

*[TBD - publish credentials for judges once live]*

## Future Work

- Real bank integration via Plaid
- Real merchant channels (email, contact forms, chat)
- Expanded dispute types (undelivered purchases, trial-to-paid conversions)
- Mobile app with push notifications
- Multi-user family plans

## Team

- **Alan Herrera** - Frontend & UX
- **Ismael** - Infrastructure & DevOps
- **Stephani Rivera** - Agents & Backend

## License

MIT - see [LICENSE](./LICENSE).
