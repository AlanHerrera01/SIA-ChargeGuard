import importlib.util
import json
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "chargeguard_merchant", Path(__file__).with_name("api.py")
)
merchant = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = merchant
SPEC.loader.exec_module(merchant)
DATASETS = Path(__file__).resolve().parents[2] / "datasets"
pytestmark = pytest.mark.anyio
INSTANT = {"X-Demo-Speed": "instant"}
CLAIM = {
    "case_id": "case_demo",
    "merchant_id": "mrc_netflix",
    "user_id": "usr_demo",
    "transaction_id": "txn_0031",
    "claim_type": "price_hike",
    "requested_amount_usd": 4.50,
    "currency": "USD",
    "message": "Unannounced price increase.",
    "evidence": [
        {
            "type": "invoice",
            "uri": "s3://example/invoices/inv_0031.pdf",
            "description": "Invoice shows $19.99 instead of $15.49.",
        }
    ],
}


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 14, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def dataset_dir(tmp_path):
    (tmp_path / "merchants.json").write_bytes(
        (DATASETS / "merchants.json").read_bytes()
    )
    # Startup must not attempt to parse evaluation data (or any bank datasets).
    (tmp_path / "ground_truth.json").write_text("intentionally invalid JSON")
    return tmp_path


@asynccontextmanager
async def running_app(directory):
    clock = Clock()
    app = merchant.create_app(directory, clock=clock)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://merchant.test",
            trust_env=False,
        ) as client:
            yield client, clock


async def create(client, *, headers=None, **changes):
    response = await client.post("/disputes", json=CLAIM | changes, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "submitted"
    assert result["offer"] is None and result["resolution"] is None
    return "/disputes/" + result["dispute_id"]


async def test_accept_instant(dataset_dir):
    async with running_app(dataset_dir) as (client, _):
        path = await create(client, headers=INSTANT)
        offer = (await client.get(path)).json()
        assert offer["status"] == "counter_offer"
        assert offer["offer"] == {
            "amount_usd": 2.7,
            "message": "We can offer a one-time courtesy credit of $2.70.",
            "expires_at": "2026-09-21T12:00:00Z",
        }
        result = (await client.post(path + "/accept")).json()
        assert result["status"] == "resolved_accepted" and result["offer"] is None
        assert result["resolution"] == {
            "outcome": "accepted",
            "refund_amount_usd": 2.7,
            "refund_eta_days": 5,
            "closed_at": "2026-09-14T12:00:00Z",
        }
        assert [step["status"] for step in result["history"]] == [
            "submitted",
            "under_review",
            "counter_offer",
            "resolved_accepted",
        ]
        assert (await client.get(path)).json() == result
        assert set(result) == {
            "dispute_id",
            "case_id",
            "merchant_id",
            "transaction_id",
            "status",
            "requested_amount_usd",
            "created_at",
            "updated_at",
            "offer",
            "resolution",
            "history",
        }


@pytest.mark.parametrize(
    "merchant_id,outcome,amount",
    [("mrc_netflix", "resolved_full", 4.5), ("mrc_fitlife", "denied", 0.0)],
)
async def test_reject_instant_policy(dataset_dir, merchant_id, outcome, amount):
    async with running_app(dataset_dir) as (client, _):
        path = await create(client, headers=INSTANT, merchant_id=merchant_id)
        assert (await client.get(path)).json()["status"] == "counter_offer"
        result = await client.post(
            path + "/reject", json={"reason": "Please refund the full charge."}
        )
        assert result.status_code == 200
        assert result.json()["status"] == "escalated"
        assert result.json()["offer"] is None and result.json()["resolution"] is None
        result = (await client.get(path)).json()
        assert result["status"] == outcome
        assert result["resolution"]["refund_amount_usd"] == amount
        assert [step["status"] for step in result["history"]] == [
            "submitted",
            "under_review",
            "counter_offer",
            "escalated",
            outcome,
        ]
        assert "Please refund the full charge." in result["history"][-2]["note"]
        assert result["resolution"]["outcome"] == (
            "denied" if outcome == "denied" else "full_refund"
        )


async def test_boundaries_and_late_rejection(dataset_dir):
    async with running_app(dataset_dir) as (client, clock):
        path = await create(client)
        clock.advance(0.999)
        assert (await client.get(path)).json()["status"] == "submitted"
        clock.advance(0.001)
        assert (await client.get(path)).json()["status"] == "under_review"
        clock.advance(2.999)
        assert (await client.get(path)).json()["status"] == "under_review"
        clock.advance(0.001)
        assert (await client.get(path)).json()["status"] == "counter_offer"
        clock.advance(96)
        assert (
            await client.post(path + "/reject", json={"reason": "Full refund needed."})
        ).json()["status"] == "escalated"
        clock.advance(2.999)
        assert (await client.get(path)).json()["status"] == "escalated"
        clock.advance(0.001)
        result = (await client.get(path)).json()
        assert result["status"] == "resolved_full"
        assert [step["at"] for step in result["history"]] == [
            "2026-09-14T12:00:00Z",
            "2026-09-14T12:00:01Z",
            "2026-09-14T12:00:04Z",
            "2026-09-14T12:01:40Z",
            "2026-09-14T12:01:43Z",
        ]
        clock.advance(1000)
        assert (await client.get(path)).json() == result


async def test_poll_frequency_does_not_change_history(dataset_dir):
    async with running_app(dataset_dir) as (client, clock):
        frequent = await create(client)
        late = await create(client)
        for _ in range(50):
            clock.advance(0.1)
            await client.get(frequent)
        first, second = (
            (await client.get(frequent)).json(),
            (await client.get(late)).json(),
        )
        first.pop("dispute_id")
        second.pop("dispute_id")
        assert first == second
        assert len(first["history"]) == 3


@pytest.mark.parametrize(
    "scenario,merchant_id,expected",
    [
        ("full_refund", "mrc_fitlife", "resolved_full"),
        ("counter_offer", "mrc_dropbox", "counter_offer"),
        ("denied", "mrc_dropbox", "counter_offer"),
        ("slow", "mrc_netflix", "counter_offer"),
    ],
)
async def test_every_scenario_instant(dataset_dir, scenario, merchant_id, expected):
    async with running_app(dataset_dir) as (client, _):
        path = await create(
            client,
            headers=INSTANT | {"X-Demo-Scenario": scenario},
            merchant_id=merchant_id,
        )
        result = (await client.get(path)).json()
        assert result["status"] == expected
        if expected == "counter_offer":
            await client.post(
                path + "/reject", json={"reason": "Full refund requested."}
            )
            result = (await client.get(path)).json()
            assert result["status"] == (
                "denied" if scenario == "denied" else "resolved_full"
            )
        assert {step["at"] for step in result["history"]} == {result["created_at"]}


async def test_counter_offer_override_forces_full_escalation(dataset_dir):
    async with running_app(dataset_dir) as (client, _):
        path = await create(
            client,
            headers=INSTANT | {"X-Demo-Scenario": "counter_offer"},
            merchant_id="mrc_fitlife",
        )
        # A command also checks current time, so an initial GET is not required.
        await client.post(path + "/reject", json={"reason": "Full refund."})
        assert (await client.get(path)).json()["status"] == "resolved_full"


async def test_slow_delays_and_policy_isolation(dataset_dir):
    async with running_app(dataset_dir) as (client, clock):
        path = await create(client, headers={"X-Demo-Scenario": "slow"})
        clock.advance(3.999)
        assert (await client.get(path)).json()["status"] == "submitted"
        clock.advance(0.001)
        assert (await client.get(path)).json()["status"] == "under_review"
        clock.advance(11.999)
        assert (await client.get(path)).json()["status"] == "under_review"
        clock.advance(0.001)
        assert (await client.get(path)).json()["status"] == "counter_offer"
        await client.post(path + "/reject", json={"reason": "Full amount."})
        clock.advance(11.999)
        assert (await client.get(path)).json()["status"] == "escalated"
        clock.advance(0.001)
        assert (await client.get(path)).json()["status"] == "resolved_full"
        await create(client, headers=INSTANT | {"X-Demo-Scenario": "full_refund"})
        normal = await create(client, headers=INSTANT)
        assert (await client.get(normal)).json()["status"] == "counter_offer"


async def test_delays_loaded_from_dataset(dataset_dir):
    records = json.loads((dataset_dir / "merchants.json").read_text())
    records[0]["dispute_policy"]["response_delay_seconds"] = 7
    (dataset_dir / "merchants.json").write_text(json.dumps(records))
    async with running_app(dataset_dir) as (client, clock):
        path = await create(client)
        clock.advance(7.999)
        assert (await client.get(path)).json()["status"] == "under_review"
        clock.advance(0.001)
        assert (await client.get(path)).json()["status"] == "counter_offer"
        await client.post(path + "/reject", json={"reason": "Full amount."})
        clock.advance(6.999)
        assert (await client.get(path)).json()["status"] == "escalated"
        clock.advance(0.001)
        assert (await client.get(path)).json()["status"] == "resolved_full"


@pytest.mark.parametrize("amount,expected", [(4.51, 2.71), (100.0, 50.0)])
async def test_offer_rounding_and_cap(dataset_dir, amount, expected):
    async with running_app(dataset_dir) as (client, _):
        path = await create(client, headers=INSTANT, requested_amount_usd=amount)
        assert (await client.get(path)).json()["offer"]["amount_usd"] == expected
        result = (await client.post(path + "/accept")).json()
        assert result["resolution"]["refund_amount_usd"] == expected


async def test_auto_counter_offer_false(dataset_dir):
    async with running_app(dataset_dir) as (client, clock):
        path = await create(client, merchant_id="mrc_dropbox")
        clock.advance(4)
        result = (await client.get(path)).json()
        assert result["status"] == "resolved_full" and result["offer"] is None
        assert result["resolution"]["refund_amount_usd"] == 4.5
        assert [step["status"] for step in result["history"]] == [
            "submitted",
            "under_review",
            "resolved_full",
        ]


@pytest.mark.parametrize(
    "state",
    [
        "submitted",
        "under_review",
        "escalated",
        "resolved_accepted",
        "resolved_full",
        "denied",
    ],
)
@pytest.mark.parametrize("action", ["accept", "reject"])
async def test_invalid_transitions(dataset_dir, state, action):
    async with running_app(dataset_dir) as (client, clock):
        path = await create(
            client, merchant_id="mrc_fitlife" if state == "denied" else "mrc_netflix"
        )
        if state != "submitted":
            clock.advance(1 if state == "under_review" else 4)
        if state in ("escalated", "resolved_full", "denied"):
            await client.post(path + "/reject", json={"reason": "Full amount."})
            if state != "escalated":
                clock.advance(3)
        elif state == "resolved_accepted":
            await client.post(path + "/accept")
        before = (await client.get(path)).json()
        assert before["status"] == state
        response = await client.post(
            path + "/" + action,
            json={"reason": "Retry."} if action == "reject" else None,
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "invalid_state_transition"
        assert (await client.get(path)).json() == before


@pytest.mark.parametrize("amount", [0, -0.01, -100])
async def test_invalid_amount(dataset_dir, amount):
    async with running_app(dataset_dir) as (client, _):
        response = await client.post(
            "/disputes", json=CLAIM | {"requested_amount_usd": amount}
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_claim_amount"
        assert (await client.get("/disputes")).json() == []


async def test_listing_filters_reset_health_and_missing_records(
    dataset_dir, monkeypatch
):
    monkeypatch.setenv("DATASET_DIR", str(dataset_dir))
    async with running_app(None) as (client, clock):
        assert (await client.get("/health")).json() == {"status": "ok"}
        first = await create(client)
        await create(client, case_id="case_other", merchant_id="mrc_dropbox")
        clock.advance(4)
        result = (
            await client.get(
                "/disputes", params={"status": "counter_offer", "case_id": "case_demo"}
            )
        ).json()
        assert len(result) == 1 and result[0]["dispute_id"] == first.split("/")[-1]
        assert (
            len(
                (
                    await client.get("/disputes", params={"status": "resolved_full"})
                ).json()
            )
            == 1
        )
        assert (
            await client.get("/disputes", params={"case_id": "missing"})
        ).json() == []
        response = await client.post(
            "/disputes", json=CLAIM | {"merchant_id": "missing"}
        )
        assert (
            response.status_code == 404
            and response.json()["error"]["code"] == "merchant_not_found"
        )
        assert (await client.post("/demo/reset")).json() == {"status": "ok"}
        assert (await client.get("/disputes")).json() == []
        for method, suffix, body in [
            ("GET", "", None),
            ("POST", "/accept", None),
            ("POST", "/reject", {"reason": "Full amount."}),
        ]:
            response = await client.request(method, first + suffix, json=body)
            assert (
                response.status_code == 404
                and response.json()["error"]["code"] == "dispute_not_found"
            )
        assert await create(client) == first
        for path in ("/ground_truth.json", "/datasets/ground_truth.json"):
            assert (await client.get(path)).status_code == 404


@pytest.mark.parametrize(
    "headers,changes",
    [
        ({"X-Demo-Scenario": "random"}, {}),
        ({"X-Demo-Speed": "fast"}, {}),
        ({}, {"currency": "EUR"}),
        ({}, {"claim_type": "unknown"}),
        ({}, {"evidence": [{"type": "unknown", "uri": None, "description": "Bad"}]}),
        ({}, {"requested_amount_usd": "NaN"}),
    ],
)
async def test_validation_envelope(dataset_dir, headers, changes):
    async with running_app(dataset_dir) as (client, _):
        response = await client.post("/disputes", headers=headers, json=CLAIM | changes)
        assert response.status_code == 422
        assert set(response.json()) == {"error"}
        assert response.json()["error"]["code"] == "validation_error"


async def test_same_commands_same_clock_after_reset(dataset_dir):
    async with running_app(dataset_dir) as (client, _):

        async def replay():
            path = await create(client, headers=INSTANT)
            await client.post(path + "/reject", json={"reason": "Full amount."})
            return (await client.get(path)).json()

        first = await replay()
        await client.post("/demo/reset")
        assert await replay() == first
