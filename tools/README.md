# Tools

Strands `@tool`-decorated functions the agents can call.

## Owner
Stephani Rivera

## Tools
- `get_transaction_history(merchant, months)` -> DynamoDB
- `get_subscription_terms(subscription_id)` -> S3
- `search_emails(merchant, keywords, date_range)` -> mock inbox
- `get_invoice(transaction_id)` -> S3
- `calculate_deviation(expected, actual)` -> math
- `submit_dispute(...)` -> Mock Merchant API
- `check_dispute_status(dispute_id)` -> Mock Merchant API
- `accept_offer(dispute_id)` -> Mock Merchant API
- `reject_offer(dispute_id)` -> Mock Merchant API
- `request_human_decision(case_id, options, context)` -> DynamoDB `decisions` table
