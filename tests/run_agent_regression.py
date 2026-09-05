from agents.orchestrator import run_chargeguard_case


CASES = [
    {
        "name": "Price increase",
        "transaction_id": "txn_0031",
        "expected_type": "PRICE_INCREASE",
        "expected_claim_type": "price_hike",
        "expected_amount": 4.50,
    },
    {
        "name": "Duplicate charge",
        "transaction_id": "txn_0044",
        "expected_type": "DUPLICATE_CHARGE",
        "expected_claim_type": "duplicate_charge",
        "expected_amount": 10.99,
    },
    {
        "name": "Charge after cancellation",
        "transaction_id": "txn_0053",
        "expected_type": "POST_CANCELLATION",
        "expected_claim_type": "charge_after_cancellation",
        "expected_amount": 12.99,
    },
]


def assert_equal(label, actual, expected):
    if actual != expected:
        raise AssertionError(
            f"{label}: expected {expected!r}, got {actual!r}"
        )


def assert_money(label, actual, expected):
    if round(float(actual), 2) != round(float(expected), 2):
        raise AssertionError(
            f"{label}: expected ${expected:.2f}, "
            f"got ${actual:.2f}"
        )


def run_case(case):
    print()
    print("=" * 70)
    print(
        f"TESTING: {case['name']} "
        f"({case['transaction_id']})"
    )
    print("=" * 70)

    result = run_chargeguard_case(
        case["transaction_id"]
    )

    analysis = result["charge_analysis"]
    evidence = result["evidence"]
    dispute = result["dispute"]
    merchant = result["merchant_response"]
    negotiation = result["negotiation"]

    # ---------------------------------------------------------
    # CHARGE ANALYSIS
    # ---------------------------------------------------------
    assert_equal(
        "is_anomaly",
        analysis.is_anomaly,
        True,
    )

    assert_equal(
        "anomaly type",
        analysis.type,
        case["expected_type"],
    )

    assert_money(
        "anomaly amount",
        analysis.difference,
        case["expected_amount"],
    )

    # ---------------------------------------------------------
    # EVIDENCE
    # ---------------------------------------------------------
    if evidence is None:
        raise AssertionError(
            "EvidenceAgent returned no evidence."
        )

    assert_equal(
        "evidence anomaly type",
        evidence.anomaly_type,
        case["expected_type"],
    )

    if case["expected_type"] == "PRICE_INCREASE":
        assert_equal(
            "price change notice",
            evidence.price_change_notice_found,
            False,
        )

    elif case["expected_type"] == "DUPLICATE_CHARGE":
        assert_equal(
            "duplicate transaction found",
            evidence.duplicate_transaction_found,
            True,
        )

        assert_equal(
            "duplicate transaction id",
            evidence.duplicate_transaction_id,
            "txn_0043",
        )

    elif case["expected_type"] == "POST_CANCELLATION":
        assert_equal(
            "cancellation confirmation",
            evidence.cancellation_confirmation_found,
            True,
        )

        assert_equal(
            "days after cancellation",
            evidence.days_after_cancellation,
            6,
        )

    # ---------------------------------------------------------
    # DISPUTE
    # ---------------------------------------------------------
    if dispute is None:
        raise AssertionError(
            "DisputeAgent returned no dispute."
        )

    assert_equal(
        "claim type",
        dispute.claim_type,
        case["expected_claim_type"],
    )

    assert_money(
        "requested refund",
        dispute.requested_amount_usd,
        case["expected_amount"],
    )

    # ---------------------------------------------------------
    # MERCHANT
    # ---------------------------------------------------------
    if merchant is None:
        raise AssertionError(
            "Merchant returned no response."
        )

    if merchant["status"] not in {
        "counter_offer",
        "resolved_full",
        "denied",
    }:
        raise AssertionError(
            "Unexpected merchant status: "
            f"{merchant['status']}"
        )

    # ---------------------------------------------------------
    # HUMAN-IN-THE-LOOP
    # ---------------------------------------------------------
    if merchant["status"] == "counter_offer":
        if negotiation is None:
            raise AssertionError(
                "Counter-offer exists but "
                "NegotiationAgent did not run."
            )

        assert_equal(
            "decision required",
            negotiation.decision_required,
            True,
        )

    print()
    print(
        f"PASS ✅  {case['name']}"
    )


def main():
    passed = 0
    failed = 0

    print()
    print("CHARGEGUARD AGENT REGRESSION")
    print("=" * 70)

    for case in CASES:
        try:
            run_case(case)
            passed += 1

        except Exception as exc:
            failed += 1

            print()
            print(
                f"FAIL ❌  {case['name']}"
            )
            print(
                f"Reason: {exc}"
            )

    print()
    print("=" * 70)
    print("FINAL RESULT")
    print("=" * 70)

    print(
        f"Passed: {passed}/{len(CASES)}"
    )

    print(
        f"Failed: {failed}/{len(CASES)}"
    )

    if failed == 0:
        print()
        print(
            "ALL CHARGEGUARD AGENT SCENARIOS PASSED ✅"
        )
    else:
        raise SystemExit(1)


if __name__ == "__main__":
    main()