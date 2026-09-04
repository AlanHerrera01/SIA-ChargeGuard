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


def run_chargeguard_case(transaction_id: str):
    transactions_path = Path("datasets/transactions.json")
    subscriptions_path = Path("datasets/subscriptions.json")

    with open(transactions_path, "r", encoding="utf-8") as file:
        transactions = json.load(file)

    with open(subscriptions_path, "r", encoding="utf-8") as file:
        subscriptions = json.load(file)

    current_transaction = next(
        tx
        for tx in transactions
        if tx["transaction_id"] == transaction_id
    )

    subscription = next(
        sub
        for sub in subscriptions
        if sub["subscription_id"]
        == current_transaction["subscription_id"]
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

    previous_charges = [
        tx["amount_usd"]
        for tx in previous_transactions
    ]

    # 1. Analyze charge
    charge_result = analyze_charge(
        merchant=current_transaction["merchant_name"],
        current_charge=current_transaction["amount_usd"],
        previous_charges=previous_charges,
    )

    if not charge_result.is_anomaly:
        return {
            "charge_analysis": charge_result,
            "evidence": None,
            "dispute": None,
            "merchant_response": None,
            "negotiation": None,
        }

    previous_transaction = (
        previous_transactions[-1]
        if previous_transactions
        else None
    )

    # 2. Gather evidence
    evidence_result = gather_evidence(
        merchant_id=current_transaction["merchant_id"],
        merchant_name=current_transaction["merchant_name"],
        subscription_id=current_transaction["subscription_id"],
        transaction_id=current_transaction["transaction_id"],
        previous_invoice_key=(
            previous_transaction["invoice_key"]
            if previous_transaction
            else None
        ),
        current_invoice_key=current_transaction["invoice_key"],
        terms_key=subscription["terms_key"],
    )

    evidence_items = []

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

    evidence_items.append(
        EvidenceItem(
            type="transaction_history",
            uri=None,
            description=(
                f"Previous charges for the subscription: "
                f"{previous_charges}"
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

    # 3. Prepare dispute
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

    # 4. Submit dispute
    submitted_dispute = submit_dispute(dispute_result)

    # 5. Poll merchant until meaningful response
    merchant_response = wait_for_merchant_response(
        submitted_dispute["dispute_id"]
    )

    negotiation_result = None

    # 6. Human-in-the-loop
    if merchant_response["status"] == "counter_offer":
        offer = merchant_response["offer"]

        negotiation_result = evaluate_counter_offer(
            requested_amount_usd=(
                merchant_response["requested_amount_usd"]
            ),
            offered_amount_usd=offer["amount_usd"],
            dispute_reason=charge_result.reason,
        )

    return {
        "charge_analysis": charge_result,
        "evidence": evidence_result,
        "dispute": dispute_result,
        "merchant_response": merchant_response,
        "negotiation": negotiation_result,
    }


if __name__ == "__main__":
    result = run_chargeguard_case("txn_0031")

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