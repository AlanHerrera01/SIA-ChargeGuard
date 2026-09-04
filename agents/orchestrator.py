import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

from agents.charge_analysis import analyze_charge
from agents.evidence import gather_evidence
from agents.dispute import EvidenceItem, prepare_dispute
from agents.negotiation import evaluate_counter_offer


MERCHANT_API_URL = "http://127.0.0.1:8002"


def map_claim_type(anomaly_type: str) -> str:
    mapping = {
        "PRICE_INCREASE": "price_hike",
        "DUPLICATE_CHARGE": "duplicate_charge",
        "POST_CANCELLATION": "charge_after_cancellation",
    }

    return mapping.get(anomaly_type, "other")


def submit_dispute(dispute):
    response = httpx.post(
        f"{MERCHANT_API_URL}/disputes",
        json=dispute.model_dump(),
        timeout=10.0,
    )

    response.raise_for_status()

    return response.json()


def get_dispute(dispute_id: str):
    response = httpx.get(
        f"{MERCHANT_API_URL}/disputes/{dispute_id}",
        timeout=10.0,
    )

    response.raise_for_status()

    return response.json()


def wait_for_merchant_response(
    dispute_id: str,
    max_attempts: int = 10,
    interval_seconds: int = 1,
):
    for _ in range(max_attempts):
        dispute = get_dispute(dispute_id)

        status = dispute["status"]

        print(f"Merchant status: {status}")

        if status in {
            "counter_offer",
            "resolved_full",
            "denied",
        }:
            return dispute

        time.sleep(interval_seconds)

    raise TimeoutError(
        "Merchant did not reach a decision state in time."
    )


def build_evidence_items(
    anomaly_type: str,
    current_transaction: dict,
    previous_transaction: dict | None,
    previous_transactions: list[dict],
    evidence_result,
    subscription: dict | None,
) -> list[EvidenceItem]:

    evidence_items = []

    if anomaly_type == "PRICE_INCREASE":

        if evidence_result.current_invoice_found:
            evidence_items.append(
                EvidenceItem(
                    type="invoice",
                    uri=evidence_result.current_invoice_uri,
                    description=(
                        f"Current invoice for transaction "
                        f"{current_transaction['transaction_id']}."
                    ),
                )
            )

        if evidence_result.previous_invoice_found:
            evidence_items.append(
                EvidenceItem(
                    type="invoice",
                    uri=evidence_result.previous_invoice_uri,
                    description=(
                        "Previous invoice showing the historical "
                        "subscription charge."
                    ),
                )
            )

        previous_amounts = [
            tx["amount_usd"]
            for tx in previous_transactions
        ]

        evidence_items.append(
            EvidenceItem(
                type="transaction_history",
                uri=None,
                description=(
                    "Previous recurring charges for the "
                    f"subscription: {previous_amounts}"
                ),
            )
        )

        if evidence_result.subscription_terms_found:
            evidence_items.append(
                EvidenceItem(
                    type="subscription_terms",
                    uri=evidence_result.subscription_terms_uri,
                    description=(
                        "Subscription terms associated "
                        "with this subscription."
                    ),
                )
            )

    elif anomaly_type == "DUPLICATE_CHARGE":

        if (
            evidence_result.duplicate_transaction_found
            and previous_transaction
        ):
            evidence_items.append(
                EvidenceItem(
                    type="transaction_history",
                    uri=None,
                    description=(
                        f"Transaction "
                        f"{previous_transaction['transaction_id']} "
                        f"charged "
                        f"${previous_transaction['amount_usd']:.2f} "
                        f"{previous_transaction['currency']} "
                        f"at {previous_transaction['posted_at']}."
                    ),
                )
            )

            evidence_items.append(
                EvidenceItem(
                    type="transaction_history",
                    uri=None,
                    description=(
                        f"Transaction "
                        f"{current_transaction['transaction_id']} "
                        f"charged another "
                        f"${current_transaction['amount_usd']:.2f} "
                        f"{current_transaction['currency']} "
                        f"at {current_transaction['posted_at']}, "
                        f"only "
                        f"{evidence_result.duplicate_seconds_apart:.0f} "
                        f"seconds after the previous charge."
                    ),
                )
            )

        if evidence_result.previous_invoice_found:
            evidence_items.append(
                EvidenceItem(
                    type="invoice",
                    uri=evidence_result.previous_invoice_uri,
                    description=(
                        "Invoice associated with the first "
                        "same-day transaction."
                    ),
                )
            )

        if evidence_result.current_invoice_found:
            evidence_items.append(
                EvidenceItem(
                    type="invoice",
                    uri=evidence_result.current_invoice_uri,
                    description=(
                        "Invoice associated with the suspected "
                        "duplicate transaction."
                    ),
                )
            )

    elif anomaly_type == "POST_CANCELLATION":

        if evidence_result.cancellation_confirmation_found:
            evidence_items.append(
                EvidenceItem(
                    type="email",
                    uri=evidence_result.cancellation_email_uri,
                    description=(
                        f"Cancellation confirmation for "
                        f"subscription "
                        f"{current_transaction['subscription_id']} "
                        f"dated {evidence_result.cancelled_at}."
                    ),
                )
            )

        evidence_items.append(
            EvidenceItem(
                type="transaction_history",
                uri=None,
                description=(
                    f"Transaction "
                    f"{current_transaction['transaction_id']} "
                    f"charged "
                    f"${current_transaction['amount_usd']:.2f} "
                    f"{current_transaction['currency']} "
                    f"on {current_transaction['posted_at']}, "
                    f"{evidence_result.days_after_cancellation} "
                    f"days after cancellation."
                ),
            )
        )

        if subscription:
            evidence_items.append(
                EvidenceItem(
                    type="other",
                    uri=None,
                    description=(
                        f"Subscription "
                        f"{subscription['subscription_id']} "
                        f"has status "
                        f"{subscription['status']} "
                        f"with cancelled_at "
                        f"{subscription['cancelled_at']}."
                    ),
                )
            )

        if evidence_result.current_invoice_found:
            evidence_items.append(
                EvidenceItem(
                    type="invoice",
                    uri=evidence_result.current_invoice_uri,
                    description=(
                        "Invoice associated with the "
                        "post-cancellation transaction."
                    ),
                )
            )

        if evidence_result.subscription_terms_found:
            evidence_items.append(
                EvidenceItem(
                    type="subscription_terms",
                    uri=evidence_result.subscription_terms_uri,
                    description=(
                        "Subscription terms associated "
                        "with the cancelled subscription."
                    ),
                )
            )

    return evidence_items


def run_chargeguard_case(transaction_id: str):
    transactions_path = Path(
        "datasets/transactions.json"
    )

    subscriptions_path = Path(
        "datasets/subscriptions.json"
    )

    with open(
        transactions_path,
        "r",
        encoding="utf-8",
    ) as file:
        transactions = json.load(file)

    with open(
        subscriptions_path,
        "r",
        encoding="utf-8",
    ) as file:
        subscriptions = json.load(file)

    current_transaction = next(
        tx
        for tx in transactions
        if tx["transaction_id"] == transaction_id
    )

    subscription = next(
        (
            sub
            for sub in subscriptions
            if sub["subscription_id"]
            == current_transaction["subscription_id"]
        ),
        None,
    )

    previous_transactions = sorted(
        [
            tx
            for tx in transactions
            if tx["subscription_id"]
            == current_transaction["subscription_id"]
            and tx["posted_at"]
            < current_transaction["posted_at"]
        ],
        key=lambda tx: tx["posted_at"],
    )

    previous_transaction = (
        previous_transactions[-1]
        if previous_transactions
        else None
    )

    charge_result = analyze_charge(
        current_transaction=current_transaction,
        previous_transactions=previous_transactions,
        subscription=subscription,
    )

    if not charge_result.is_anomaly:
        return {
            "charge_analysis": charge_result,
            "evidence": None,
            "dispute": None,
            "merchant_response": None,
            "negotiation": None,
        }

    terms_key = (
        subscription.get("terms_key")
        if subscription
        else None
    )

    evidence_result = gather_evidence(
        anomaly_type=charge_result.type,
        current_transaction=current_transaction,
        previous_transaction=previous_transaction,
        terms_key=terms_key,
        subscription=subscription,
    )

    evidence_items = build_evidence_items(
        anomaly_type=charge_result.type,
        current_transaction=current_transaction,
        previous_transaction=previous_transaction,
        previous_transactions=previous_transactions,
        evidence_result=evidence_result,
        subscription=subscription,
    )

    dispute_result = prepare_dispute(
        case_id=f"case_{uuid4().hex[:8]}",
        merchant_id=current_transaction["merchant_id"],
        merchant_name=current_transaction["merchant_name"],
        user_id=current_transaction["user_id"],
        transaction_id=current_transaction["transaction_id"],
        claim_type=map_claim_type(charge_result.type),
        expected_amount_usd=charge_result.expected_amount,
        actual_amount_usd=charge_result.actual_amount,
        requested_amount_usd=charge_result.difference,
        currency=current_transaction["currency"],
        anomaly_reason=charge_result.reason,
        evidence=evidence_items,
    )

    submitted_dispute = submit_dispute(
        dispute_result
    )

    merchant_response = wait_for_merchant_response(
        submitted_dispute["dispute_id"]
    )

    negotiation_result = None

    if merchant_response["status"] == "counter_offer":

        offer = merchant_response["offer"]

        negotiation_result = evaluate_counter_offer(
            requested_amount_usd=(
                merchant_response[
                    "requested_amount_usd"
                ]
            ),
            offered_amount_usd=offer["amount_usd"],
            dispute_reason=charge_result.reason,
            evidence_summary=evidence_result.summary,
        )

    return {
        "charge_analysis": charge_result,
        "evidence": evidence_result,
        "dispute": dispute_result,
        "merchant_response": merchant_response,
        "negotiation": negotiation_result,
    }


if __name__ == "__main__":

    transaction_id = "txn_0053"

    result = run_chargeguard_case(
        transaction_id
    )

    print("\n--- CHARGE ANALYSIS ---")
    print(result["charge_analysis"])

    print("\n--- EVIDENCE ---")
    print(result["evidence"])

    print("\n--- DISPUTE ---")
    print(result["dispute"])

    print("\n--- MERCHANT RESPONSE ---")
    print(result["merchant_response"])

    print("\n--- HUMAN DECISION REQUIRED ---")
    print(result["negotiation"])