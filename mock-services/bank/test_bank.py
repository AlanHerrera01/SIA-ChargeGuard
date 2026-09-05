import asyncio
import base64
import importlib.util
import json
import shutil
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, Request

SPEC = importlib.util.spec_from_file_location(
    "chargeguard_bank", Path(__file__).with_name("api.py")
)
bank = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bank
SPEC.loader.exec_module(bank)
DATASETS = Path(__file__).resolve().parents[2] / "datasets"
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def dataset_dir(tmp_path):
    for name in ("transactions.json", "subscriptions.json"):
        shutil.copyfile(DATASETS / name, tmp_path / name)
    # An invalid evaluation file must have no effect on startup or reset.
    (tmp_path / "ground_truth.json").write_text("DO NOT READ: secret evaluation labels")
    return tmp_path


@asynccontextmanager
async def running_app(directory, transport=None):
    app = bank.create_app(directory, webhook_transport=transport)
    # ASGITransport deliberately does not run lifespan; exercise it explicitly.
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://bank.test"
        ) as client:
            yield app, client


def read_transactions(directory):
    return json.loads((directory / "transactions.json").read_text())


async def test_health_and_subscriptions(dataset_dir):
    async with running_app(dataset_dir) as (_, client):
        assert (await client.get("/health")).json() == {
            "status": "ok",
            "dataset_version": "1",
        }
        assert (await client.get("/users/usr_demo/subscriptions")).json() == json.loads(
            (dataset_dir / "subscriptions.json").read_text()
        )
        assert (await client.get("/users/unknown/subscriptions")).json() == []
        assert (await client.get("/users/unknown/transactions")).json() == {
            "items": [],
            "next_cursor": None,
        }


async def test_pages_are_descending_complete_and_stable_on_timestamp_ties(dataset_dir):
    records = read_transactions(dataset_dir)
    records[0]["posted_at"] = records[1]["posted_at"]
    (dataset_dir / "transactions.json").write_text(json.dumps(records))
    expected = sorted(
        records, key=lambda t: f"{t['posted_at']}#{t['transaction_id']}", reverse=True
    )
    async with running_app(dataset_dir) as (_, client):
        seen = []
        params = {"limit": 5}
        for _ in range(20):
            response = await client.get("/users/usr_demo/transactions", params=params)
            assert response.status_code == 200
            page = response.json()
            assert 1 <= len(page["items"]) <= 5
            seen.extend(page["items"])
            if page["next_cursor"] is None:
                break
            last = page["items"][-1]
            assert (
                base64.urlsafe_b64decode(page["next_cursor"]).decode()
                == f"{last['posted_at']}#{last['transaction_id']}"
            )
            params["cursor"] = page["next_cursor"]
        else:
            pytest.fail("Pagination did not terminate")
        assert seen == expected
        assert len({t["transaction_id"] for t in seen}) == len(records)
        assert (await client.get("/transactions/txn_0031")).json() == next(
            t for t in records if t["transaction_id"] == "txn_0031"
        )


async def test_default_and_maximum_limits(dataset_dir):
    template = read_transactions(dataset_dir)[0]
    records = [dict(template, transaction_id=f"txn_{i:04d}") for i in range(501)]
    (dataset_dir / "transactions.json").write_text(json.dumps(records))
    async with running_app(dataset_dir) as (_, client):
        assert (
            len((await client.get("/users/usr_demo/transactions")).json()["items"])
            == 100
        )
        page = (await client.get("/users/usr_demo/transactions?limit=500")).json()
        assert len(page["items"]) == 500
        tail = (
            await client.get(
                "/users/usr_demo/transactions", params={"cursor": page["next_cursor"]}
            )
        ).json()
        assert len(tail["items"]) == 1
        assert tail["next_cursor"] is None


@pytest.mark.parametrize(
    "filters",
    [
        {"merchant_id": "mrc_spotify"},
        {"subscription_id": "sub_001"},
        {"since": "2026-09-03", "until": "2026-09-03"},
        {"since": "2026-09-03"},
        {"until": "2026-04-03"},
        {
            "merchant_id": "mrc_spotify",
            "subscription_id": "sub_003",
            "since": "2026-08-01",
            "until": "2026-09-03",
        },
        {"merchant_id": "unknown"},
    ],
)
async def test_filters_before_pagination(dataset_dir, filters):
    expected = [
        t
        for t in read_transactions(dataset_dir)
        if all(
            t[key] == value
            for key, value in filters.items()
            if key in {"merchant_id", "subscription_id"}
        )
        and t["posted_at"][:10] >= filters.get("since", "0001-01-01")
        and t["posted_at"][:10] <= filters.get("until", "9999-12-31")
    ]
    expected.sort(key=lambda t: f"{t['posted_at']}#{t['transaction_id']}", reverse=True)
    async with running_app(dataset_dir) as (_, client):
        seen, cursor = [], None
        while True:
            params = dict(filters, limit=1)
            if cursor:
                params["cursor"] = cursor
            page = (
                await client.get("/users/usr_demo/transactions", params=params)
            ).json()
            seen.extend(page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert seen == expected


async def test_user_isolation(dataset_dir):
    records = read_transactions(dataset_dir)
    records[0]["user_id"] = "usr_other"
    (dataset_dir / "transactions.json").write_text(json.dumps(records))
    async with running_app(dataset_dir) as (_, client):
        assert (await client.get("/users/usr_other/transactions")).json()["items"] == [
            records[0]
        ]
        assert (
            len((await client.get("/users/usr_demo/transactions")).json()["items"])
            == len(records) - 1
        )


@pytest.mark.parametrize(
    "query,status,code",
    [
        ("limit=0", 422, "validation_error"),
        ("limit=501", 422, "validation_error"),
        ("limit=bad", 422, "validation_error"),
        ("since=2026-02-30", 422, "validation_error"),
        ("since=2026-09-14&until=2026-01-01", 400, "invalid_date_range"),
        ("cursor=", 400, "invalid_cursor"),
        ("cursor=!!!", 400, "invalid_cursor"),
        ("cursor=YmFk", 400, "invalid_cursor"),
    ],
)
async def test_invalid_query_errors(dataset_dir, query, status, code):
    async with running_app(dataset_dir) as (_, client):
        response = await client.get(f"/users/usr_demo/transactions?{query}")
        assert response.status_code == status
        assert set(response.json()) == {"error"}
        assert response.json()["error"]["code"] == code


async def test_missing_transaction_and_invalid_request(dataset_dir):
    async with running_app(dataset_dir) as (_, client):
        for response in [
            await client.get("/transactions/txn_missing"),
            await client.post(
                "/transactions/notify", json={"transaction_id": "txn_missing"}
            ),
        ]:
            assert response.status_code == 404
            assert response.json() == {
                "error": {
                    "code": "transaction_not_found",
                    "message": "Transaction not found",
                }
            }
        for body in [
            {},
            {"transaction_id": "txn_0031", "webhook_url": "file:///etc/passwd"},
        ]:
            response = await client.post("/transactions/notify", json=body)
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "validation_error"
        assert (await client.post("/health")).json()["error"][
            "code"
        ] == "method_not_allowed"


async def test_successful_webhook_to_asgi_receiver_and_reset_replay(
    dataset_dir, monkeypatch
):
    receiver = FastAPI()
    events = []

    @receiver.post("/transactions/webhook")
    async def receive(request: Request):
        events.append((request.url.hostname, await request.json()))
        return {"status": "ok"}

    monkeypatch.setenv(
        "BACKEND_WEBHOOK_URL", "http://default.test/transactions/webhook"
    )
    async with running_app(dataset_dir, httpx.ASGITransport(app=receiver)) as (
        app,
        client,
    ):
        body = {"transaction_id": "txn_0031"}
        result = await client.post("/transactions/notify", json=body)
        assert result.status_code == 200
        assert result.json() == {"delivered": True, "status_code": 200}
        event = events[0][1]
        assert set(event) == {"event_id", "event_type", "occurred_at", "data"}
        assert event["event_id"].startswith("evt_")
        assert event["event_type"] == "transaction.posted"
        assert event["data"] == (await client.get("/transactions/txn_0031")).json()
        assert event["occurred_at"] == event["data"]["posted_at"]
        assert events[0][0] == "default.test"
        await client.post(
            "/transactions/notify",
            json=dict(body, webhook_url="http://override.test/transactions/webhook"),
        )
        assert events[1][0] == "override.test"
        assert events[1][1]["event_id"] != event["event_id"]
        await client.post("/demo/reset")
        assert app.state.bank.notification_sequence == 0
        await client.post("/transactions/notify", json=body)
        assert events[2] == events[0]


@pytest.mark.parametrize(
    "failure", ["connect", "timeout", "http500", "redirect", "deadline"]
)
async def test_failed_webhooks_always_return_http_200(
    dataset_dir, monkeypatch, failure
):
    calls = []

    async def deliver(request):
        calls.append(request)
        assert request.extensions["timeout"]["connect"] == 5.0
        if failure == "connect":
            raise httpx.ConnectError("Backend down", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("Backend hung", request=request)
        if failure == "deadline":
            await asyncio.sleep(1)
        return httpx.Response(302 if failure == "redirect" else 500)

    async with running_app(dataset_dir, httpx.MockTransport(deliver)) as (_, client):
        if failure == "deadline":
            monkeypatch.setattr(bank, "WEBHOOK_TIMEOUT_SECONDS", 0.01)
        response = await client.post(
            "/transactions/notify",
            json={
                "transaction_id": "txn_0031",
                "webhook_url": "http://receiver.test/hook",
            },
        )
        assert response.status_code == 200
        assert response.json()["delivered"] is False
        assert response.json()["status_code"] is None
        assert response.json()["error"]
        assert len(calls) == 1


@pytest.mark.parametrize("url", [None, "invalid://destination"])
async def test_missing_or_invalid_webhook_configuration(dataset_dir, monkeypatch, url):
    monkeypatch.delenv("BACKEND_WEBHOOK_URL", raising=False)
    if url:
        monkeypatch.setenv("BACKEND_WEBHOOK_URL", url)
    async with running_app(dataset_dir) as (_, client):
        response = await client.post(
            "/transactions/notify", json={"transaction_id": "txn_0031"}
        )
        assert response.status_code == 200
        assert response.json()["delivered"] is False


async def test_reset_reloads_both_files_and_keeps_old_snapshot_on_failure(dataset_dir):
    async with running_app(dataset_dir) as (app, client):
        records = read_transactions(dataset_dir)
        removed = records.pop()
        subscriptions = json.loads((dataset_dir / "subscriptions.json").read_text())
        subscriptions[0]["plan_name"] = "Reloaded plan"
        (dataset_dir / "transactions.json").write_text(json.dumps(records))
        (dataset_dir / "subscriptions.json").write_text(json.dumps(subscriptions))
        assert (
            await client.get(f"/transactions/{removed['transaction_id']}")
        ).status_code == 200
        assert (await client.post("/demo/reset")).json() == {"status": "ok"}
        assert (
            await client.get(f"/transactions/{removed['transaction_id']}")
        ).status_code == 404
        assert (await client.get("/users/usr_demo/subscriptions")).json()[0][
            "plan_name"
        ] == "Reloaded plan"
        snapshot = app.state.bank
        (dataset_dir / "subscriptions.json").write_text("[]")
        (dataset_dir / "transactions.json").write_text("corrupt JSON")
        failed = await client.post("/demo/reset")
        assert failed.status_code == 503
        assert failed.json()["error"]["code"] == "dataset_reload_failed"
        assert app.state.bank is snapshot


async def test_only_feed_files_are_read_and_no_evaluation_is_exposed(
    dataset_dir, monkeypatch
):
    reads = []
    read_bytes = Path.read_bytes

    def guarded_read(path):
        reads.append(path.name)
        assert path.name in {"transactions.json", "subscriptions.json"}
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    monkeypatch.setenv("DATASET_DIR", str(dataset_dir))
    async with running_app(None) as (_, client):
        await client.post("/demo/reset")
        assert reads == ["subscriptions.json", "transactions.json"] * 2
        for url in [
            "/ground_truth.json",
            "/datasets/ground_truth.json",
            "/invoices/inv_0031.pdf",
        ]:
            response = await client.get(url)
            assert response.status_code == 404
            assert response.json()["error"]["code"] == "not_found"
        for item in (await client.get("/users/usr_demo/transactions")).json()["items"]:
            assert set(item) == set(read_transactions(DATASETS)[0])


async def test_bad_dataset_fails_startup(dataset_dir):
    (dataset_dir / "transactions.json").write_text("not JSON")
    with pytest.raises(ValueError):
        async with running_app(dataset_dir):
            pytest.fail("A malformed dataset must prevent startup")
