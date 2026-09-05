from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from email import policy
from email.parser import BytesParser
from pathlib import Path


DATASET_DIR = Path(__file__).resolve().parent
GENERATOR = DATASET_DIR / "generate.py"
ANOMALY_KEYS = {
    "anomaly_id",
    "anomaly_type",
    "type",
    "expected_amount_usd",
    "actual_amount_usd",
    "delta_usd",
    "notice_given",
    "expected_claim_amount_usd",
}


def _load_json(name: str):
    return json.loads((DATASET_DIR / name).read_text(encoding="utf-8"))


def _generated_hashes(root: Path) -> dict[str, str]:
    files = [
        *[
            root / name
            for name in (
                "merchants.json",
                "subscriptions.json",
                "transactions.json",
                "ground_truth.json",
            )
        ],
        *sorted((root / "invoices").glob("inv_*.pdf")),
        *sorted((root / "emails").glob("eml_*.eml")),
        *sorted((root / "terms").glob("sub_*.pdf")),
    ]
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }


def test_dataset_counts_and_references() -> None:
    merchants = _load_json("merchants.json")
    subscriptions = _load_json("subscriptions.json")
    transactions = _load_json("transactions.json")
    anomalies = _load_json("ground_truth.json")["anomalies"]
    transaction_ids = {transaction["transaction_id"] for transaction in transactions}

    assert len(merchants) == 10
    assert len(subscriptions) == 6
    assert {subscription["user_id"] for subscription in subscriptions} == {"usr_demo"}
    assert len(transactions) == 37
    assert len(anomalies) == 3
    assert {anomaly["anomaly_id"] for anomaly in anomalies} == {
        "anm_001",
        "anm_002",
        "anm_003",
    }
    assert all(anomaly["transaction_id"] in transaction_ids for anomaly in anomalies)


def test_transactions_never_expose_ground_truth() -> None:
    transactions = _load_json("transactions.json")
    for transaction in transactions:
        assert ANOMALY_KEYS.isdisjoint(transaction)


def test_clean_subscriptions_have_at_most_half_percent_drift() -> None:
    subscriptions = {
        subscription["subscription_id"]: subscription
        for subscription in _load_json("subscriptions.json")
    }
    anomalies = _load_json("ground_truth.json")["anomalies"]
    anomalous_subscription_ids = {anomaly["subscription_id"] for anomaly in anomalies}

    for transaction in _load_json("transactions.json"):
        if transaction["subscription_id"] in anomalous_subscription_ids:
            continue
        base_amount = subscriptions[transaction["subscription_id"]]["base_amount_usd"]
        drift = abs(transaction["amount_usd"] - base_amount) / base_amount
        assert drift <= 0.005


def test_document_keys_exist() -> None:
    for transaction in _load_json("transactions.json"):
        invoice = DATASET_DIR / transaction["invoice_key"]
        assert invoice.is_file()
        assert invoice.read_bytes().startswith(b"%PDF")

    for subscription in _load_json("subscriptions.json"):
        terms = DATASET_DIR / subscription["terms_key"]
        assert terms.is_file()
        assert terms.read_bytes().startswith(b"%PDF")


def test_exact_anomaly_scenarios_and_evidence() -> None:
    subscriptions = {
        subscription["subscription_id"]: subscription
        for subscription in _load_json("subscriptions.json")
    }
    transactions = {
        transaction["transaction_id"]: transaction
        for transaction in _load_json("transactions.json")
    }
    anomalies = {
        anomaly["anomaly_id"]: anomaly
        for anomaly in _load_json("ground_truth.json")["anomalies"]
    }

    price_hike = anomalies["anm_001"]
    assert price_hike == {
        "anomaly_id": "anm_001",
        "type": "price_hike",
        "transaction_id": "txn_0031",
        "subscription_id": "sub_001",
        "expected_amount_usd": 15.49,
        "actual_amount_usd": 19.99,
        "delta_usd": 4.5,
        "notice_given": False,
        "expected_claim_amount_usd": 4.5,
    }
    assert transactions["txn_0031"]["amount_usd"] == 19.99

    duplicate = anomalies["anm_002"]
    duplicate_transaction = transactions[duplicate["transaction_id"]]
    same_charge = [
        transaction
        for transaction in transactions.values()
        if transaction["subscription_id"] == "sub_003"
        and transaction["posted_at"][:10] == duplicate_transaction["posted_at"][:10]
        and transaction["amount_usd"] == duplicate_transaction["amount_usd"]
    ]
    assert len(same_charge) == 2
    assert duplicate["expected_claim_amount_usd"] == duplicate_transaction["amount_usd"]

    cancelled = anomalies["anm_003"]
    cancelled_transaction = transactions[cancelled["transaction_id"]]
    cancellation_date = date.fromisoformat(subscriptions["sub_005"]["cancelled_at"])
    posted_date = date.fromisoformat(cancelled_transaction["posted_at"][:10])
    assert (posted_date - cancellation_date).days == 6
    assert cancelled["expected_claim_amount_usd"] == cancelled_transaction["amount_usd"]

    anomaly_dates = [
        date.fromisoformat(transactions[anomaly["transaction_id"]]["posted_at"][:10])
        for anomaly in anomalies.values()
    ]
    assert all(
        date(2026, 8, 1) <= anomaly_date <= date(2026, 9, 14)
        for anomaly_date in anomaly_dates
    )


def test_emails_are_valid_and_contain_required_evidence() -> None:
    parsed_messages = [
        BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        for path in sorted((DATASET_DIR / "emails").glob("eml_*.eml"))
    ]
    assert len(parsed_messages) == 15
    assert all(message["From"] for message in parsed_messages)
    assert all(message["To"] == "demo@chargeguard.dev" for message in parsed_messages)
    assert all(message["Date"] and message["Message-ID"] for message in parsed_messages)
    assert all(
        message.get_content_type() == "text/plain" for message in parsed_messages
    )

    message_types: dict[str, list] = defaultdict(list)
    for message in parsed_messages:
        message_types[message["X-ChargeGuard-Message-Type"]].append(message)

    assert len(message_types["receipt"]) == 8
    assert len(message_types["cancellation_confirmation"]) == 1
    assert len(message_types["price_change_notice"]) == 2
    assert len(message_types["marketing"]) == 4
    assert "sub_005" in message_types["cancellation_confirmation"][0].get_content()

    price_notice_text = "\n".join(
        f"{message['Subject']}\n{message.get_content()}"
        for message in message_types["price_change_notice"]
    ).lower()
    assert "sub_002" in price_notice_text
    assert "sub_004" in price_notice_text
    assert "sub_001" not in price_notice_text
    assert "netflix" not in price_notice_text


def test_same_seed_regenerates_identical_hashes(tmp_path: Path) -> None:
    output = tmp_path / "dataset"
    command = [
        sys.executable,
        str(GENERATOR),
        "--seed",
        "42",
        "--as-of",
        "2026-09-14",
        "--out",
        str(output),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    first_hashes = _generated_hashes(output)
    subprocess.run(command, check=True, capture_output=True, text=True)
    second_hashes = _generated_hashes(output)

    assert first_hashes == second_hashes
    assert len(first_hashes) == 62


def test_as_of_controls_the_generated_timeline(tmp_path: Path) -> None:
    output = tmp_path / "shifted-dataset"
    shifted_as_of = date(2027, 1, 10)
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--seed",
            "42",
            "--as-of",
            shifted_as_of.isoformat(),
            "--out",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    transactions = {
        transaction["transaction_id"]: transaction
        for transaction in json.loads(
            (output / "transactions.json").read_text(encoding="utf-8")
        )
    }
    anomalies = json.loads((output / "ground_truth.json").read_text(encoding="utf-8"))[
        "anomalies"
    ]

    for anomaly in anomalies:
        anomaly_date = date.fromisoformat(
            transactions[anomaly["transaction_id"]]["posted_at"][:10]
        )
        assert 0 <= (shifted_as_of - anomaly_date).days <= 45

    cancellation = next(
        subscription
        for subscription in json.loads(
            (output / "subscriptions.json").read_text(encoding="utf-8")
        )
        if subscription["subscription_id"] == "sub_005"
    )
    assert date.fromisoformat(
        cancellation["cancelled_at"]
    ) == shifted_as_of - timedelta(days=25)
