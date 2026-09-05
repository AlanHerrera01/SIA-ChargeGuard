from __future__ import annotations

import argparse
import calendar
import json
import random
from datetime import date, datetime, time, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos


DEFAULT_SEED = 42
DEFAULT_AS_OF = date(2026, 9, 14)
DEMO_USER_ID = "usr_demo"
GENERATED_PATTERNS = {
    "invoices": "inv_*.pdf",
    "emails": "eml_*.eml",
    "terms": "sub_*.pdf",
}


def _merchant(
    merchant_id: str,
    name: str,
    category: str,
    *,
    auto_counter_offer: bool,
    counter_offer_ratio: float,
    max_refund_usd: float,
    escalation_outcome: str,
) -> dict[str, Any]:
    return {
        "merchant_id": merchant_id,
        "name": name,
        "category": category,
        "support_channel": "api",
        "dispute_policy": {
            "auto_counter_offer": auto_counter_offer,
            "counter_offer_ratio": counter_offer_ratio,
            "response_delay_seconds": 3,
            "max_refund_usd": max_refund_usd,
            "escalation_outcome": escalation_outcome,
        },
    }


def build_merchants() -> list[dict[str, Any]]:
    return [
        _merchant(
            "mrc_netflix",
            "Netflix",
            "streaming",
            auto_counter_offer=True,
            counter_offer_ratio=0.60,
            max_refund_usd=50.00,
            escalation_outcome="resolved_full",
        ),
        _merchant(
            "mrc_dropbox",
            "Dropbox",
            "cloud_storage",
            auto_counter_offer=False,
            counter_offer_ratio=1.00,
            max_refund_usd=100.00,
            escalation_outcome="resolved_full",
        ),
        _merchant(
            "mrc_notion",
            "Notion",
            "saas",
            auto_counter_offer=True,
            counter_offer_ratio=0.75,
            max_refund_usd=75.00,
            escalation_outcome="resolved_full",
        ),
        _merchant(
            "mrc_fitlife",
            "FitLife Gym",
            "fitness",
            auto_counter_offer=True,
            counter_offer_ratio=0.50,
            max_refund_usd=80.00,
            escalation_outcome="denied",
        ),
        _merchant(
            "mrc_spotify",
            "Spotify",
            "music",
            auto_counter_offer=True,
            counter_offer_ratio=0.60,
            max_refund_usd=50.00,
            escalation_outcome="resolved_full",
        ),
        _merchant(
            "mrc_dailyledger",
            "The Daily Ledger",
            "news",
            auto_counter_offer=False,
            counter_offer_ratio=1.00,
            max_refund_usd=40.00,
            escalation_outcome="resolved_full",
        ),
        _merchant(
            "mrc_gamebox",
            "GameBox",
            "gaming",
            auto_counter_offer=True,
            counter_offer_ratio=0.50,
            max_refund_usd=60.00,
            escalation_outcome="denied",
        ),
        _merchant(
            "mrc_quickeats",
            "QuickEats Plus",
            "delivery",
            auto_counter_offer=True,
            counter_offer_ratio=0.70,
            max_refund_usd=40.00,
            escalation_outcome="resolved_full",
        ),
        _merchant(
            "mrc_learnsphere",
            "LearnSphere",
            "education",
            auto_counter_offer=False,
            counter_offer_ratio=1.00,
            max_refund_usd=120.00,
            escalation_outcome="resolved_full",
        ),
        _merchant(
            "mrc_safevault",
            "SafeVault",
            "security",
            auto_counter_offer=True,
            counter_offer_ratio=0.65,
            max_refund_usd=50.00,
            escalation_outcome="resolved_full",
        ),
    ]


def build_subscriptions(as_of: date) -> list[dict[str, Any]]:
    cancelled_at = (as_of - timedelta(days=25)).isoformat()
    subscriptions = [
        ("sub_001", "mrc_netflix", "Standard", 14, 15.49, "active", None),
        ("sub_002", "mrc_dropbox", "Plus", 2, 11.99, "active", None),
        ("sub_003", "mrc_spotify", "Premium", 3, 10.99, "active", None),
        ("sub_004", "mrc_notion", "Plus", 8, 12.00, "active", None),
        (
            "sub_005",
            "mrc_fitlife",
            "Monthly Access",
            20,
            39.99,
            "cancelled",
            cancelled_at,
        ),
        ("sub_006", "mrc_safevault", "Personal", 12, 2.99, "active", None),
    ]
    return [
        {
            "subscription_id": subscription_id,
            "user_id": DEMO_USER_ID,
            "merchant_id": merchant_id,
            "plan_name": plan_name,
            "billing_cycle": "monthly",
            "billing_day": billing_day,
            "base_amount_usd": base_amount_usd,
            "currency": "USD",
            "status": status,
            "started_at": _shift_month(as_of, -6, billing_day).isoformat(),
            "cancelled_at": cancelled_at,
            "terms_key": f"terms/{subscription_id}.pdf",
        }
        for (
            subscription_id,
            merchant_id,
            plan_name,
            billing_day,
            base_amount_usd,
            status,
            cancelled_at,
        ) in subscriptions
    ]


def _shift_month(value: date, months: int, day: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def _billing_dates(as_of: date, billing_day: int, count: int = 6) -> list[date]:
    latest = _shift_month(as_of, 0, billing_day)
    if latest > as_of:
        latest = _shift_month(as_of, -1, billing_day)
    return sorted(_shift_month(latest, -offset, billing_day) for offset in range(count))


def _posted_at(posted_date: date, minute: int) -> str:
    value = datetime.combine(posted_date, time(9, minute), tzinfo=timezone.utc)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _transaction_record(
    subscription: dict[str, Any],
    merchant: dict[str, Any],
    posted_date: date,
    amount_usd: float,
    *,
    minute: int,
    marker: str,
) -> dict[str, Any]:
    descriptions = {
        "mrc_netflix": "NETFLIX.COM  LOS GATOS CA",
        "mrc_dropbox": "DROPBOX PLUS  SAN FRANCISCO CA",
        "mrc_spotify": "SPOTIFY USA  NEW YORK NY",
        "mrc_notion": "NOTION LABS  SAN FRANCISCO CA",
        "mrc_fitlife": "FITLIFE GYM  AUSTIN TX",
        "mrc_safevault": "SAFEVAULT  BOSTON MA",
    }
    return {
        "_marker": marker,
        "user_id": DEMO_USER_ID,
        "subscription_id": subscription["subscription_id"],
        "merchant_id": merchant["merchant_id"],
        "merchant_name": merchant["name"],
        "amount_usd": round(amount_usd, 2),
        "currency": "USD",
        "posted_at": _posted_at(posted_date, minute),
        "description": descriptions[merchant["merchant_id"]],
        "status": "posted",
    }


def build_transactions(
    subscriptions: list[dict[str, Any]],
    merchants: list[dict[str, Any]],
    as_of: date,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    merchant_by_id = {merchant["merchant_id"]: merchant for merchant in merchants}
    records: list[dict[str, Any]] = []

    for index, subscription in enumerate(subscriptions):
        subscription_id = subscription["subscription_id"]
        merchant = merchant_by_id[subscription["merchant_id"]]
        minute = 10 + index

        if subscription_id == "sub_005":
            cancellation_date = date.fromisoformat(subscription["cancelled_at"])
            normal_dates = [
                billing_date
                for billing_date in _billing_dates(
                    cancellation_date, subscription["billing_day"], 6
                )
                if billing_date < cancellation_date
            ][-5:]
            for billing_date in normal_dates:
                records.append(
                    _transaction_record(
                        subscription,
                        merchant,
                        billing_date,
                        subscription["base_amount_usd"],
                        minute=minute,
                        marker=f"normal_{subscription_id}_{billing_date.isoformat()}",
                    )
                )
            records.append(
                _transaction_record(
                    subscription,
                    merchant,
                    cancellation_date + timedelta(days=6),
                    subscription["base_amount_usd"],
                    minute=minute,
                    marker="charge_after_cancellation",
                )
            )
            continue

        billing_dates = _billing_dates(as_of, subscription["billing_day"])
        for billing_date in billing_dates:
            is_price_hike = (
                subscription_id == "sub_001" and billing_date == billing_dates[-1]
            )
            amount = 19.99 if is_price_hike else subscription["base_amount_usd"]
            records.append(
                _transaction_record(
                    subscription,
                    merchant,
                    billing_date,
                    amount,
                    minute=minute,
                    marker=(
                        "price_hike"
                        if is_price_hike
                        else f"normal_{subscription_id}_{billing_date.isoformat()}"
                    ),
                )
            )

    spotify_latest = max(
        (
            record
            for record in records
            if record["subscription_id"] == "sub_003"
            and record["_marker"].startswith("normal_")
        ),
        key=lambda record: record["posted_at"],
    )
    duplicate = dict(spotify_latest)
    duplicate["_marker"] = "duplicate_charge"
    duplicate["posted_at"] = _posted_at(
        date.fromisoformat(spotify_latest["posted_at"][:10]), 20
    )
    records.append(duplicate)

    price_hike = next(record for record in records if record["_marker"] == "price_hike")
    other_records = sorted(
        (record for record in records if record is not price_hike),
        key=lambda record: (
            record["posted_at"],
            record["subscription_id"],
            record["_marker"],
        ),
    )

    numbered_records: list[dict[str, Any]] = []
    next_number = 1
    for record in other_records:
        if next_number == 31:
            next_number += 1
        record["transaction_id"] = f"txn_{next_number:04d}"
        record["invoice_key"] = f"invoices/inv_{next_number:04d}.pdf"
        numbered_records.append(record)
        next_number += 1

    price_hike["transaction_id"] = "txn_0031"
    price_hike["invoice_key"] = "invoices/inv_0031.pdf"
    numbered_records.append(price_hike)
    numbered_records.sort(key=lambda record: record["transaction_id"])

    marker_ids = {
        record["_marker"]: record["transaction_id"] for record in numbered_records
    }
    transactions = [
        {key: value for key, value in record.items() if key != "_marker"}
        for record in numbered_records
    ]
    return transactions, marker_ids


def build_ground_truth(marker_ids: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    return {
        "anomalies": [
            {
                "anomaly_id": "anm_001",
                "type": "price_hike",
                "transaction_id": marker_ids["price_hike"],
                "subscription_id": "sub_001",
                "expected_amount_usd": 15.49,
                "actual_amount_usd": 19.99,
                "delta_usd": 4.50,
                "notice_given": False,
                "expected_claim_amount_usd": 4.50,
            },
            {
                "anomaly_id": "anm_002",
                "type": "duplicate_charge",
                "transaction_id": marker_ids["duplicate_charge"],
                "subscription_id": "sub_003",
                "expected_amount_usd": 0.00,
                "actual_amount_usd": 10.99,
                "delta_usd": 10.99,
                "expected_claim_amount_usd": 10.99,
            },
            {
                "anomaly_id": "anm_003",
                "type": "charge_after_cancellation",
                "transaction_id": marker_ids["charge_after_cancellation"],
                "subscription_id": "sub_005",
                "expected_amount_usd": 0.00,
                "actual_amount_usd": 39.99,
                "delta_usd": 39.99,
                "expected_claim_amount_usd": 39.99,
            },
        ]
    }


def _write_json(path: Path, payload: Any) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(encoded)


def _prepare_generated_directories(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for directory_name, pattern in GENERATED_PATTERNS.items():
        directory = out_dir / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        for generated_file in directory.glob(pattern):
            if generated_file.is_file():
                generated_file.unlink()


def _configure_pdf(pdf: FPDF, title: str, creation_date: datetime) -> None:
    pdf.set_author("ChargeGuard synthetic dataset")
    pdf.set_creator("datasets/generate.py")
    pdf.set_subject("Synthetic demo document - not a real financial record")
    pdf.set_title(title)
    pdf.set_creation_date(creation_date)
    pdf.set_auto_page_break(auto=False)


def _pdf_line(pdf: FPDF, text: str, *, bold: bool = False, height: int = 8) -> None:
    pdf.set_font("Helvetica", "B" if bold else "", 11)
    pdf.cell(0, height, text=text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def write_invoices(
    out_dir: Path,
    transactions: list[dict[str, Any]],
    subscriptions: list[dict[str, Any]],
    as_of: date,
) -> None:
    subscription_by_id = {
        subscription["subscription_id"]: subscription for subscription in subscriptions
    }
    creation_date = datetime.combine(as_of, time(12), tzinfo=timezone.utc)

    for transaction in transactions:
        subscription = subscription_by_id[transaction["subscription_id"]]
        invoice_id = Path(transaction["invoice_key"]).stem
        posted_date = date.fromisoformat(transaction["posted_at"][:10])
        period_end_day = calendar.monthrange(posted_date.year, posted_date.month)[1]
        billing_period = (
            f"{posted_date.year:04d}-{posted_date.month:02d}-01 to "
            f"{posted_date.year:04d}-{posted_date.month:02d}-{period_end_day:02d}"
        )

        pdf = FPDF(format="A4")
        _configure_pdf(pdf, f"Invoice {invoice_id}", creation_date)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(0, 14, text="SYNTHETIC INVOICE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(
            0,
            7,
            text="ChargeGuard demo data - not a real charge",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(5)
        _pdf_line(pdf, f"Merchant: {transaction['merchant_name']}", bold=True)
        _pdf_line(pdf, f"Invoice ID: {invoice_id}")
        _pdf_line(pdf, f"Transaction ID: {transaction['transaction_id']}")
        _pdf_line(pdf, f"Plan: {subscription['plan_name']}")
        _pdf_line(pdf, f"Billing period: {billing_period}")
        _pdf_line(pdf, f"Date: {posted_date.isoformat()}")
        pdf.ln(6)
        _pdf_line(pdf, f"Line item: {subscription['plan_name']} monthly subscription")
        _pdf_line(
            pdf, f"Amount: USD {transaction['amount_usd']:.2f}", bold=True, height=10
        )
        pdf.output(str(out_dir / transaction["invoice_key"]))


def write_terms(
    out_dir: Path,
    subscriptions: list[dict[str, Any]],
    merchants: list[dict[str, Any]],
    as_of: date,
) -> None:
    merchant_by_id = {merchant["merchant_id"]: merchant for merchant in merchants}
    creation_date = datetime.combine(as_of, time(12), tzinfo=timezone.utc)

    for subscription in subscriptions:
        merchant = merchant_by_id[subscription["merchant_id"]]
        pdf = FPDF(format="A4")
        _configure_pdf(
            pdf,
            f"Subscription terms {subscription['subscription_id']}",
            creation_date,
        )
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.cell(
            0,
            14,
            text="SYNTHETIC SUBSCRIPTION TERMS",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        _pdf_line(pdf, "ChargeGuard demo data - not a real agreement")
        pdf.ln(4)
        _pdf_line(pdf, f"Subscription ID: {subscription['subscription_id']}", bold=True)
        _pdf_line(pdf, f"Merchant: {merchant['name']}")
        _pdf_line(pdf, f"Plan: {subscription['plan_name']}")
        _pdf_line(pdf, f"Monthly price: USD {subscription['base_amount_usd']:.2f}")
        _pdf_line(pdf, f"Billing day: {subscription['billing_day']}")
        _pdf_line(pdf, f"Effective date: {subscription['started_at']}")
        pdf.ln(5)
        _pdf_line(
            pdf,
            "Cancellation stops authorization for charges after the cancellation date.",
        )
        _pdf_line(
            pdf, "Price changes require advance notice by email before taking effect."
        )
        pdf.output(str(out_dir / subscription["terms_key"]))


def _email_bytes(
    message_id: str,
    sender: str,
    subject: str,
    sent_at: datetime,
    body: str,
    message_type: str,
) -> bytes:
    message = EmailMessage(policy=SMTP)
    message["From"] = sender
    message["To"] = "demo@chargeguard.dev"
    message["Subject"] = subject
    message["Date"] = format_datetime(sent_at)
    message["Message-ID"] = f"<{message_id}@chargeguard.dev>"
    message["X-ChargeGuard-Synthetic"] = "true"
    message["X-ChargeGuard-Message-Type"] = message_type
    message.set_content(body)
    return message.as_bytes(policy=SMTP)


def write_emails(
    out_dir: Path,
    transactions: list[dict[str, Any]],
    subscriptions: list[dict[str, Any]],
    as_of: date,
    seed: int,
) -> None:
    rng = random.Random(seed)
    receipt_candidates = [
        transaction
        for transaction in transactions
        if transaction["transaction_id"] != "txn_0031"
    ]
    receipt_transactions = sorted(
        rng.sample(receipt_candidates, 8),
        key=lambda transaction: transaction["transaction_id"],
    )

    messages: list[dict[str, Any]] = []
    for transaction in receipt_transactions:
        sent_at = datetime.fromisoformat(
            transaction["posted_at"].replace("Z", "+00:00")
        )
        messages.append(
            {
                "sender": f"receipts@{transaction['merchant_id'][4:]}.example",
                "subject": f"Receipt from {transaction['merchant_name']}",
                "sent_at": sent_at,
                "body": (
                    "This is a synthetic receipt for the ChargeGuard demo.\n\n"
                    f"Transaction: {transaction['transaction_id']}\n"
                    f"Amount: USD {transaction['amount_usd']:.2f}\n"
                    f"Posted: {transaction['posted_at']}\n"
                ),
                "message_type": "receipt",
            }
        )

    messages.extend(
        [
            {
                "sender": "support@fitlife.example",
                "subject": "Cancellation confirmed for sub_005",
                "sent_at": datetime.combine(
                    date.fromisoformat(
                        next(
                            subscription["cancelled_at"]
                            for subscription in subscriptions
                            if subscription["subscription_id"] == "sub_005"
                        )
                    ),
                    time(15),
                    tzinfo=timezone.utc,
                ),
                "body": (
                    "This is synthetic ChargeGuard demo evidence.\n\n"
                    "Your FitLife Gym Monthly Access subscription sub_005 was cancelled "
                    f"on {(as_of - timedelta(days=25)).isoformat()}. "
                    "No further charges are authorized.\n"
                ),
                "message_type": "cancellation_confirmation",
            },
            {
                "sender": "billing@dropbox.example",
                "subject": "Upcoming price change for Dropbox Plus",
                "sent_at": datetime.combine(
                    as_of - timedelta(days=17), time(13), tzinfo=timezone.utc
                ),
                "body": (
                    "This is a synthetic ChargeGuard demo notice.\n\n"
                    "Subscription sub_002 will change from USD 11.99 to USD 12.99 on "
                    f"{_shift_month(as_of, 1, 2).isoformat()}. "
                    "Charges before that date remain USD 11.99.\n"
                ),
                "message_type": "price_change_notice",
            },
            {
                "sender": "billing@notion.example",
                "subject": "Upcoming price change for Notion Plus",
                "sent_at": datetime.combine(
                    as_of - timedelta(days=13), time(14), tzinfo=timezone.utc
                ),
                "body": (
                    "This is a synthetic ChargeGuard demo notice.\n\n"
                    "Subscription sub_004 will change from USD 12.00 to USD 13.00 on "
                    f"{_shift_month(as_of, 1, 8).isoformat()}. "
                    "Charges before that date remain USD 12.00.\n"
                ),
                "message_type": "price_change_notice",
            },
        ]
    )

    marketing = [
        (
            "news@gamebox.example",
            "September games roundup",
            datetime.combine(as_of - timedelta(days=10), time(16), tzinfo=timezone.utc),
            "Explore this month's fictional GameBox releases. No account action is required.",
        ),
        (
            "offers@quickeats.example",
            "Free delivery weekend",
            datetime.combine(as_of - timedelta(days=8), time(17), tzinfo=timezone.utc),
            "A synthetic promotion for the ChargeGuard demo inbox.",
        ),
        (
            "digest@dailyledger.example",
            "Your weekly reading list",
            datetime.combine(as_of - timedelta(days=7), time(12), tzinfo=timezone.utc),
            "Five fictional stories selected for this synthetic demo mailbox.",
        ),
        (
            "hello@learnsphere.example",
            "Courses picked for you",
            datetime.combine(as_of - timedelta(days=5), time(11), tzinfo=timezone.utc),
            "Discover synthetic learning recommendations. This is marketing noise.",
        ),
    ]
    rng.shuffle(marketing)
    for sender, subject, sent_at, body in marketing:
        messages.append(
            {
                "sender": sender,
                "subject": subject,
                "sent_at": sent_at,
                "body": body,
                "message_type": "marketing",
            }
        )

    messages.sort(key=lambda message: (message["sent_at"], message["subject"]))
    for index, message in enumerate(messages, start=1):
        message_id = f"eml_{index:03d}"
        email_path = out_dir / "emails" / f"{message_id}.eml"
        email_path.write_bytes(
            _email_bytes(
                message_id,
                message["sender"],
                message["subject"],
                message["sent_at"],
                message["body"],
                message["message_type"],
            )
        )


def generate_dataset(seed: int, as_of: date, out_dir: Path) -> dict[str, int]:
    out_dir = out_dir.resolve()
    _prepare_generated_directories(out_dir)

    merchants = build_merchants()
    subscriptions = build_subscriptions(as_of)
    transactions, marker_ids = build_transactions(subscriptions, merchants, as_of)
    ground_truth = build_ground_truth(marker_ids)

    _write_json(out_dir / "merchants.json", merchants)
    _write_json(out_dir / "subscriptions.json", subscriptions)
    _write_json(out_dir / "transactions.json", transactions)
    _write_json(out_dir / "ground_truth.json", ground_truth)
    write_invoices(out_dir, transactions, subscriptions, as_of)
    write_terms(out_dir, subscriptions, merchants, as_of)
    write_emails(out_dir, transactions, subscriptions, as_of, seed)

    return {
        "merchants": len(merchants),
        "subscriptions": len(subscriptions),
        "transactions": len(transactions),
        "anomalies": len(ground_truth["anomalies"]),
        "invoices": len(list((out_dir / "invoices").glob("inv_*.pdf"))),
        "emails": len(list((out_dir / "emails").glob("eml_*.eml"))),
        "terms": len(list((out_dir / "terms").glob("sub_*.pdf"))),
    }


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "expected an ISO date in YYYY-MM-DD format"
        ) from error


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic ChargeGuard demo data"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--as-of", type=_parse_date, default=DEFAULT_AS_OF)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    counts = generate_dataset(args.seed, args.as_of, args.out)
    print(f"Generated deterministic dataset in {args.out.resolve()}")
    print(" ".join(f"{name}={count}" for name, count in counts.items()))


if __name__ == "__main__":
    main()
