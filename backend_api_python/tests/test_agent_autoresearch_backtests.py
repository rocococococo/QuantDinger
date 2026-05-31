"""Agent Gateway AutoResearch backtest route tests."""
from __future__ import annotations

import pytest

from app.routes.agent_v1 import autoresearch as autoresearch_agent_routes
from app.utils import agent_auth
from app.services.autoresearch_native.contract import MAX_AUTORESEARCH_REQUEST_BYTES


@pytest.fixture(autouse=True)
def _reset_rate_limit_state():
    agent_auth._rate_state.clear()
    yield
    agent_auth._rate_state.clear()


def _fake_token_row(scopes: str = "R,B", *, markets: str = "*", instruments: str = "*") -> dict:
    return {
        "id": 999,
        "user_id": 1,
        "name": "test-agent",
        "scopes": scopes,
        "markets": markets,
        "instruments": instruments,
        "paper_only": True,
        "rate_limit_per_min": 60,
        "status": "active",
        "expires_at": None,
    }


def _bearer(headers: dict | None = None, token: str = "qd_agent_TESTTOKEN12345") -> dict:
    out = {"Authorization": f"Bearer {token}"}
    out.update(headers or {})
    return out


def test_agent_autoresearch_backtest_requires_b_scope(client, monkeypatch):
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json"}),
        json={
            "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
            "market": "USStock",
            "symbol": "SOXL",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
        },
    )

    assert resp.status_code == 403


def test_agent_autoresearch_backtest_queues_host_job(client, monkeypatch):
    captured = {}

    def fake_submit_job(**kwargs):
        captured.update(kwargs)
        return {"job_id": "job-autoresearch-1", "status": "queued"}

    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R,B"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)
    monkeypatch.setattr(autoresearch_agent_routes, "submit_job", fake_submit_job)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json", "Idempotency-Key": "ar-test-key-001"}),
        json={
            "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
            "market": "USStock",
            "symbol": "SOXL",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
            "autoresearchTrace": {"run_id": "ar-run-001"},
            "qd_native_validation_scope": "sampled_window",
        },
    )

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["data"]["job_id"] == "job-autoresearch-1"
    assert captured["user_id"] == 1
    assert captured["agent_token_id"] == 999
    assert captured["kind"] == "autoresearch_backtest"
    assert captured["request_payload"]["__user_id"] == 1
    assert captured["runner"] is autoresearch_agent_routes._run_autoresearch_backtest
    assert captured["idempotency_key"] == "ar-test-key-001"


def test_agent_autoresearch_backtest_requires_idempotency_key(client, monkeypatch):
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R,B"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json"}),
        json={
            "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
            "market": "USStock",
            "symbol": "SOXL",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
        },
    )

    assert resp.status_code == 400
    assert resp.get_json()["message"] == "Idempotency-Key header is required"


@pytest.mark.parametrize(
    ("removed_key", "message"),
    [
        ("indicatorCode", "indicatorCode is required"),
        ("market", "market is required"),
        ("symbol", "symbol is required"),
        ("timeframe", "timeframe is required"),
        ("startDate", "startDate is required"),
        ("endDate", "endDate is required"),
    ],
)
def test_agent_autoresearch_backtest_validates_required_fields_before_enqueue(
    client,
    monkeypatch,
    removed_key,
    message,
):
    def fail_submit_job(**_kwargs):
        raise AssertionError("job submitted with invalid AutoResearch payload")

    payload = {
        "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
        "market": "USStock",
        "symbol": "SOXL",
        "timeframe": "1m",
        "startDate": "2026-05-01",
        "endDate": "2026-05-01",
    }
    payload.pop(removed_key)

    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R,B"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)
    monkeypatch.setattr(autoresearch_agent_routes, "submit_job", fail_submit_job)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json", "Idempotency-Key": f"ar-missing-{removed_key}"}),
        json=payload,
    )

    assert resp.status_code == 400
    assert resp.get_json()["message"] == message


def test_agent_autoresearch_backtest_rejects_long_idempotency_key(client, monkeypatch):
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R,B"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json", "Idempotency-Key": "x" * 121}),
        json={
            "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
            "market": "USStock",
            "symbol": "SOXL",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
        },
    )

    assert resp.status_code == 400
    assert resp.get_json()["message"] == "Idempotency-Key exceeds 120 characters"


def test_agent_autoresearch_backtest_validates_indicator_code_alias_used_by_adapter(client, monkeypatch):
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R,B"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json", "Idempotency-Key": "ar-code-alias"}),
        json={
            "code": "df['buy'] = False\ndf['sell'] = False\n",
            "indicatorCode": "x" * (512 * 1024 + 1),
            "market": "USStock",
            "symbol": "SOXL",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
        },
    )

    assert resp.status_code == 400
    assert "Indicator code exceeds" in resp.get_json()["message"]


def test_agent_autoresearch_backtest_rejects_oversized_body_before_route_parse(client, monkeypatch):
    def fail_parse():
        raise AssertionError("route JSON parser called")

    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R,B"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)
    monkeypatch.setattr(autoresearch_agent_routes, "get_json_or_400", fail_parse)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json", "Idempotency-Key": "ar-large-body"}),
        data=b'{"payload":"' + (b"x" * MAX_AUTORESEARCH_REQUEST_BYTES) + b'"}',
    )

    assert resp.status_code == 413


def test_agent_autoresearch_backtest_checks_market_type_alias(client, monkeypatch):
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R,B", markets="Crypto"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json", "Idempotency-Key": "ar-market-alias"}),
        json={
            "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
            "market_type": "USStock",
            "symbol": "SOXL",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
        },
    )

    assert resp.status_code == 403


def test_agent_autoresearch_backtest_checks_instrument_alias(client, monkeypatch):
    agent_auth._schema_ready = True
    monkeypatch.setattr(agent_auth, "_lookup_token", lambda _raw: _fake_token_row(scopes="R,B", instruments="SOXL"))
    monkeypatch.setattr(agent_auth, "_touch_token_last_used", lambda *_: None)
    monkeypatch.setattr(agent_auth, "_audit", lambda *a, **kw: None)

    resp = client.post(
        "/api/agent/v1/autoresearch/backtests",
        headers=_bearer({"Content-Type": "application/json", "Idempotency-Key": "ar-instrument-alias"}),
        json={
            "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
            "market": "Crypto",
            "instrument": "BTC/USDT",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
        },
    )

    assert resp.status_code == 403
