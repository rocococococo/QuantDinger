"""AutoResearch native host contract tests."""

from datetime import datetime

import pandas as pd
import pytest

from app.routes import autoresearch as autoresearch_routes
from app.services.autoresearch_native.backtest_adapter import run_autoresearch_backtest
from app.services.autoresearch_native.contract import (
    MAX_SUPPLIED_OHLCV_ROWS,
    capabilities_payload,
    cost_stress_payload,
    execution_config,
    native_run_id,
    request_commission,
    request_slippage,
    supplied_ohlcv_rows,
    validation_window_metrics,
)
from app.services.backtest import BacktestService
from app.utils import auth


def test_capabilities_payload_reports_hosted_native_cost_stress():
    payload = capabilities_payload()

    assert payload["status"] == "ok"
    assert payload["local_compat"] is False
    assert payload["native_engine"] is True
    assert payload["supports_sampled_window_cost_stress"] is True
    assert payload["backtest_path"] == "/api/agent/v1/autoresearch/backtests"
    assert payload["agent_backtest_path"] == "/api/agent/v1/autoresearch/backtests"
    assert payload["compatibility_backtest_path"] == "/api/autoresearch/indicator-backtest"
    assert payload["compatibility_backtest_enabled"] is False
    assert "sampled_window_cost_stress" in payload["capabilities"]


def test_autoresearch_capabilities_endpoint(client):
    resp = client.get("/api/autoresearch/capabilities")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["native_engine"] is True
    assert data["backtest_path"] == "/api/agent/v1/autoresearch/backtests"
    assert data["agent_backtest_path"] == "/api/agent/v1/autoresearch/backtests"


def test_autoresearch_indicator_backtest_endpoint_uses_native_adapter(client, monkeypatch):
    captured = {}

    def fake_run(payload, *, user_id, persist_default):
        captured["payload"] = payload
        captured["user_id"] = user_id
        captured["persist_default"] = persist_default
        return {
            "runId": None,
            "nativeRunId": "autoresearch-ephemeral-test",
            "persistenceStatus": "ephemeral",
            "result": {"totalProfit": 1.0},
        }

    monkeypatch.setattr(autoresearch_routes, "run_autoresearch_backtest", fake_run)
    monkeypatch.setenv("AUTORESEARCH_NATIVE_COMPAT_ENABLED", "true")
    monkeypatch.setenv("AUTORESEARCH_NATIVE_API_TOKEN", "test-native-token")

    resp = client.post(
        "/api/autoresearch/indicator-backtest",
        headers={"Authorization": "Bearer test-native-token"},
        json={
            "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
            "symbol": "SOXL",
            "market": "USStock",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["code"] == 1
    assert payload["data"]["nativeRunId"] == "autoresearch-ephemeral-test"
    assert captured["user_id"] == 1
    assert captured["persist_default"] is False


def test_autoresearch_indicator_backtest_disabled_by_default(client, monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("native adapter called")

    monkeypatch.setattr(autoresearch_routes, "run_autoresearch_backtest", fail_run)
    monkeypatch.delenv("AUTORESEARCH_NATIVE_COMPAT_ENABLED", raising=False)
    monkeypatch.delenv("AUTORESEARCH_NATIVE_API_TOKEN", raising=False)
    monkeypatch.delenv("AUTORESEARCH_NATIVE_ALLOW_LOOPBACK", raising=False)

    resp = client.post("/api/autoresearch/indicator-backtest", json={})

    assert resp.status_code == 410
    assert resp.get_json()["data"]["backtest_path"] == "/api/agent/v1/autoresearch/backtests"


def test_autoresearch_indicator_backtest_requires_token_when_compat_enabled(client, monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("native adapter called")

    monkeypatch.setattr(autoresearch_routes, "run_autoresearch_backtest", fail_run)
    monkeypatch.setenv("AUTORESEARCH_NATIVE_COMPAT_ENABLED", "true")
    monkeypatch.delenv("AUTORESEARCH_NATIVE_API_TOKEN", raising=False)
    monkeypatch.delenv("AUTORESEARCH_NATIVE_ALLOW_LOOPBACK", raising=False)

    resp = client.post("/api/autoresearch/indicator-backtest", json={})

    assert resp.status_code == 401


def test_autoresearch_indicator_backtest_requires_content_length_when_compat_enabled(client, monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("native adapter called")

    monkeypatch.setattr(autoresearch_routes, "run_autoresearch_backtest", fail_run)
    monkeypatch.setenv("AUTORESEARCH_NATIVE_COMPAT_ENABLED", "true")
    monkeypatch.setenv("AUTORESEARCH_NATIVE_API_TOKEN", "test-native-token")

    resp = client.post(
        "/api/autoresearch/indicator-backtest",
        headers={"Authorization": "Bearer test-native-token", "Content-Type": "application/json"},
        environ_overrides={"CONTENT_LENGTH": None},
    )

    assert resp.status_code == 411


def test_autoresearch_indicator_backtest_requires_json_object_when_compat_enabled(client, monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("native adapter called")

    monkeypatch.setattr(autoresearch_routes, "run_autoresearch_backtest", fail_run)
    monkeypatch.setenv("AUTORESEARCH_NATIVE_COMPAT_ENABLED", "true")
    monkeypatch.setenv("AUTORESEARCH_NATIVE_API_TOKEN", "test-native-token")

    resp = client.post(
        "/api/autoresearch/indicator-backtest",
        headers={"Authorization": "Bearer test-native-token"},
        json=["invalid"],
    )

    assert resp.status_code == 400
    assert resp.get_json()["msg"] == "JSON body must be an object"


def test_autoresearch_indicator_backtest_rejects_invalid_json_when_compat_enabled(client, monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("native adapter called")

    monkeypatch.setattr(autoresearch_routes, "run_autoresearch_backtest", fail_run)
    monkeypatch.setenv("AUTORESEARCH_NATIVE_COMPAT_ENABLED", "true")
    monkeypatch.setenv("AUTORESEARCH_NATIVE_API_TOKEN", "test-native-token")

    resp = client.post(
        "/api/autoresearch/indicator-backtest",
        headers={"Authorization": "Bearer test-native-token", "Content-Type": "application/json"},
        data="{",
    )

    assert resp.status_code == 400
    assert resp.get_json()["msg"] == "Invalid JSON body"


def test_autoresearch_indicator_backtest_rejects_loopback_when_token_configured(client, monkeypatch):
    def fail_run(*_args, **_kwargs):
        raise AssertionError("native adapter called")

    monkeypatch.setattr(autoresearch_routes, "run_autoresearch_backtest", fail_run)
    monkeypatch.setenv("AUTORESEARCH_NATIVE_COMPAT_ENABLED", "true")
    monkeypatch.setenv("AUTORESEARCH_NATIVE_API_TOKEN", "required-token")
    monkeypatch.setenv("AUTORESEARCH_NATIVE_ALLOW_LOOPBACK", "true")

    resp = client.post("/api/autoresearch/indicator-backtest", json={})

    assert resp.status_code == 401


def test_cost_stress_scope_uses_stressed_execution_config():
    data = {
        "qd_native_validation_scope": "sampled_window_cost_stress",
        "sampleWindowPlanHash": "sha256:sample-plan",
        "scenarioGridHash": "sha256:scenario-grid",
        "costStressScenarioId": "next_bar_open_2x_cost",
        "commission": 0.001,
        "slippage": 0.0001,
        "strategyConfig": {"execution": {"fill_model": "signal_bar_close", "commission_value": 0.01}},
        "costStressScenario": {
            "stress_multiple": 2.0,
            "fill_model": "next_bar_open",
            "execution": {
                "fill_model": "next_bar_open",
                "commission_model": "fixed",
                "commission_value": 0.02,
                "slippage_model": "bps",
                "slippage_bps": 4.0,
            },
        },
    }
    execution = execution_config(data, data["strategyConfig"])

    assert request_commission(data, execution) == 0.02
    assert request_slippage(data, execution) == 0.0004

    payload = cost_stress_payload(
        data,
        result={
            "totalProfit": 5.0,
            "totalReturn": 0.05,
            "maxDrawdown": -0.01,
            "totalTrades": 2,
            "totalCommission": 0.04,
            "equityCurve": [{"time": "2026-05-08 20:00", "value": 10005.0}],
        },
        commission=0.02,
        slippage=0.0004,
        execution=execution,
    )

    assert payload["source"] == "qd_native_same_window_cost_replay"
    assert payload["passed"] is True
    assert payload["sample_window_plan_hash"] == "sha256:sample-plan"
    assert payload["scenario_grid_hash"] == "sha256:scenario-grid"
    assert payload["scenario_id"] == "next_bar_open_2x_cost"
    assert payload["cost_model"]["commission"] == 0.02
    assert payload["cost_model"]["slippage"] == 0.0004
    assert payload["blocking_reasons"] == []


def test_validation_window_metrics_exclude_execution_warmup():
    data = {
        "qd_native_validation_scope": "sampled_window",
        "autoresearchValidationWindow": {
            "start_datetime": "2026-02-01T14:30:00+00:00",
            "end_datetime": "2026-02-02T21:00:00+00:00",
        },
    }
    result = {
        "totalProfit": 999.0,
        "maxDrawdown": -20.0,
        "totalTrades": 99,
        "equityCurve": [
            {"time": "2026-01-31 20:00", "value": 10000.0},
            {"time": "2026-02-01 14:30", "value": 10001.0},
            {"time": "2026-02-02 20:00", "value": 10004.0},
        ],
        "trades": [
            {"time": "2026-01-31 20:00", "type": "close_long", "profit": 999.0},
            {"time": "2026-02-02 20:00", "type": "close_long", "profit": 3.0},
        ],
    }

    metrics = validation_window_metrics(data, result=result, initial_capital=10000.0)

    assert metrics["totalProfit"] == 3.0
    assert metrics["totalTrades"] == 1
    assert metrics["maxDrawdown"] == 0.0
    assert metrics["equityBasis"] == "validation_window_relative_pnl"
    assert metrics["equityFloor"] == 0.0
    assert metrics["validationWindow"] == data["autoresearchValidationWindow"]
    assert metrics["equityCurve"] == [
        {"time": "2026-02-01 14:30", "value": 0.0},
        {"time": "2026-02-02 20:00", "value": 3.0},
    ]


def test_cost_stress_blocks_relative_equity_floor_breach():
    data = {
        "qd_native_validation_scope": "sampled_window_cost_stress",
        "sampleWindowPlanHash": "sha256:sample-plan",
        "scenarioGridHash": "sha256:scenario-grid",
        "costStressScenarioId": "next_bar_open_2x_cost",
    }

    payload = cost_stress_payload(
        data,
        result={
            "totalProfit": 2.0,
            "totalReturn": 0.02,
            "maxDrawdown": -0.05,
            "totalTrades": 1,
            "totalCommission": 0.04,
            "equityBasis": "validation_window_relative_pnl",
            "equityFloor": 0.0,
            "equityCurve": [
                {"time": "2026-02-01 14:30", "value": 0.0},
                {"time": "2026-02-01 15:30", "value": -1.0},
                {"time": "2026-02-02 20:00", "value": 2.0},
            ],
        },
        commission=0.02,
        slippage=0.0004,
        execution={},
    )

    assert payload["passed"] is False
    assert payload["observed"]["min_equity"] == -1.0
    assert "qd_native_cost_stress_equity_floor_breached" in payload["blocking_reasons"]


def test_native_run_id_is_stable_for_ephemeral_runs():
    data = {
        "autoresearchTrace": {
            "run_id": "ar-run-001",
            "candidate_id": "candidate-002",
            "source_surface": "autoresearch_autonomous_loop",
            "strategy_ir_sha256": "sha256:ir",
            "qd_code_sha256": "sha256:code",
            "benchmark_set_hash": "sha256:bench",
        },
        "qd_native_validation_scope": "sampled_window",
        "sampleWindowPlanHash": "sha256:sample-plan",
    }
    result = {
        "executionAssumptions": {
            "actualDataRange": {
                "start": "2026-05-01T13:30:00+00:00",
                "end": "2026-05-03T20:00:00+00:00",
            },
        },
    }

    first = native_run_id(data, result, None)
    second = native_run_id(data, result, None)

    assert first.startswith("autoresearch-ephemeral-")
    assert first == second
    assert native_run_id(data, result, 123) == "123"


def test_supplied_ohlcv_rows_require_trace_and_sample_scope():
    rows = [{"timestamp": "2026-05-01T13:30:00Z", "open": 1, "high": 2, "low": 1, "close": 2}]

    assert supplied_ohlcv_rows({"autoresearchOhlcvRows": rows, "qd_native_validation_scope": "sampled_window"}) == []
    assert supplied_ohlcv_rows({"autoresearchTrace": {}, "autoresearchOhlcvRows": rows}) == []
    assert supplied_ohlcv_rows(
        {
            "autoresearchTrace": {"run_id": "run-001"},
            "qd_native_validation_scope": "sampled_window",
            "autoresearchOhlcvRows": rows,
        }
    ) == rows


def test_supplied_ohlcv_rows_enforce_row_cap():
    rows = [
        {"timestamp": "2026-05-01T13:30:00Z", "open": 1, "high": 2, "low": 1, "close": 2}
        for _ in range(MAX_SUPPLIED_OHLCV_ROWS + 1)
    ]

    with pytest.raises(ValueError, match="row count exceeds"):
        supplied_ohlcv_rows(
            {
                "autoresearchTrace": {"run_id": "run-001"},
                "qd_native_validation_scope": "sampled_window",
                "autoresearchOhlcvRows": rows,
            }
        )


def test_supplied_ohlcv_rows_reject_malformed_rows():
    with pytest.raises(ValueError, match="row 0 must be an object"):
        supplied_ohlcv_rows(
            {
                "autoresearchTrace": {"run_id": "run-001"},
                "qd_native_validation_scope": "sampled_window",
                "autoresearchOhlcvRows": ["bad"],
            }
        )


def test_supplied_ohlcv_rows_reject_present_null_alias():
    with pytest.raises(ValueError, match="must be a list"):
        supplied_ohlcv_rows(
            {
                "autoresearchTrace": {"run_id": "run-001"},
                "qd_native_validation_scope": "sampled_window",
                "autoresearchOhlcvRows": None,
            }
        )


def test_autoresearch_adapter_rejects_malformed_supplied_ohlcv_rows():
    class FailBacktestService:
        def run_aligned(self, **_kwargs):
            raise AssertionError("backtest called with malformed supplied OHLCV rows")

    with pytest.raises(ValueError, match="row 0 must be an object"):
        run_autoresearch_backtest(
            {
                "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
                "symbol": "SOXL",
                "market": "USStock",
                "timeframe": "1m",
                "startDate": "2026-05-01",
                "endDate": "2026-05-01",
                "autoresearchTrace": {"run_id": "ar-run-001"},
                "qd_native_validation_scope": "sampled_window",
                "autoresearchOhlcvRows": ["bad"],
            },
            backtest_service=FailBacktestService(),
        )


def test_backtest_service_rejects_invalid_supplied_ohlcv_rows():
    service = BacktestService()

    with pytest.raises(ValueError, match="high must be greater"):
        service._dataframe_from_supplied_ohlcv_rows(
            [{"timestamp": "2026-05-01T13:30:00Z", "open": 10, "high": 9, "low": 10, "close": 10}],
            market="USStock",
            symbol="SOXL",
            timeframe="1m",
            start_date=datetime(2026, 5, 1, 13, 30),
            end_date=datetime(2026, 5, 1, 13, 32),
        )


def test_backtest_service_uses_generic_supplied_ohlcv_rows(monkeypatch):
    service = BacktestService()

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("external fetch called")

    monkeypatch.setattr(service, "_fetch_kline_data", fail_fetch)
    rows = [
        {"timestamp": "2026-05-01T13:30:00Z", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        {"timestamp": "2026-05-01T13:31:00Z", "open": 10, "high": 12, "low": 10, "close": 12, "volume": 100},
        {"timestamp": "2026-05-01T13:32:00Z", "open": 12, "high": 12, "low": 11, "close": 11, "volume": 100},
    ]
    result = service.run(
        indicator_code=(
            "df['buy'] = False\n"
            "df['sell'] = False\n"
            "df.loc[0, 'buy'] = True\n"
            "df.loc[len(df) - 1, 'sell'] = True\n"
        ),
        market="USStock",
        symbol="SOXL",
        timeframe="1m",
        start_date=datetime(2026, 5, 1, 13, 30),
        end_date=datetime(2026, 5, 1, 13, 32),
        initial_capital=1000,
        commission=0.0,
        slippage=0.0,
        trade_direction="long",
        ohlcv_rows=rows,
    )

    provenance = result["executionAssumptions"]["marketDataProvenance"]
    assert provenance["source"] == "supplied_ohlcv"
    assert provenance["data_source_mode"] == "supplied_ohlcv"
    assert provenance["row_count"] == 3
    assert provenance["rows_hash"].startswith("sha256:")


def test_backtest_service_supplied_rows_force_standard_mtf_path(monkeypatch):
    service = BacktestService()

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError("external fetch called")

    monkeypatch.setattr(service, "_fetch_kline_data", fail_fetch)
    rows = [
        {"timestamp": "2026-05-01T13:30:00Z", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        {"timestamp": "2026-05-01T13:31:00Z", "open": 10, "high": 12, "low": 10, "close": 12, "volume": 100},
        {"timestamp": "2026-05-01T13:32:00Z", "open": 12, "high": 12, "low": 11, "close": 11, "volume": 100},
    ]

    result = service.run_multi_timeframe(
        indicator_code="df['buy'] = False\ndf['sell'] = False\n",
        market="Crypto",
        symbol="BTC/USDT",
        timeframe="1D",
        start_date=datetime(2026, 5, 1, 13, 30),
        end_date=datetime(2026, 5, 1, 13, 32),
        ohlcv_rows=rows,
    )

    assert result["executionAssumptions"]["mtfActive"] is False
    assert result["executionAssumptions"]["mtfFallbackReason"] == "supplied_ohlcv"
    assert result["precision_info"]["enabled"] is False
    assert result["precision_info"]["fallback_reason"] == "supplied_ohlcv"


def test_autoresearch_adapter_passes_provenance_to_host_seam():
    captured = {}

    class FakeBacktestService:
        def run_aligned(self, **kwargs):
            captured.update(kwargs)
            return {
                "executionAssumptions": {},
                "totalProfit": 0.0,
                "totalReturn": 0.0,
                "maxDrawdown": 0.0,
                "totalTrades": 0,
                "equityCurve": [],
                "trades": [],
            }

    run_autoresearch_backtest(
        {
            "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
            "symbol": "SOXL",
            "market": "USStock",
            "timeframe": "1m",
            "startDate": "2026-05-01",
            "endDate": "2026-05-01",
            "autoresearchTrace": {"run_id": "ar-run-001", "candidate_id": "candidate-001"},
            "qd_native_validation_scope": "sampled_window",
            "autoresearchOhlcvRows": [
                {"timestamp": "2026-05-01T13:30:00Z", "open": 10, "high": 11, "low": 9, "close": 10}
            ],
        },
        backtest_service=FakeBacktestService(),
    )

    assert captured["ohlcv_provenance"]["source"] == "autoresearch_supplied_same_window_ohlcv"
    assert captured["ohlcv_provenance"]["data_source_mode"] == "supplied_same_window_ohlcv"
    assert captured["ohlcv_provenance"]["independent_from_autoresearch_payload"] is False


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"initialCapital": "NaN"}, "initialCapital must be finite"),
        ({"initialCapital": 0}, "initialCapital must be positive"),
        ({"leverage": 0}, "leverage must be between 1 and 100"),
        ({"leverage": 101}, "leverage must be between 1 and 100"),
        ({"commission": -0.1}, "commission must be non-negative"),
        ({"commission": "Infinity"}, "commission must be finite"),
        ({"slippage": -0.01}, "slippage must be non-negative"),
        ({"slippage": "NaN"}, "slippage must be finite"),
        ({"costStressScenario": {"execution": {"slippage_bps": -1}}}, "slippage_bps must be non-negative"),
    ],
)
def test_autoresearch_adapter_rejects_invalid_execution_numbers(override, message):
    class FailBacktestService:
        def run_aligned(self, **_kwargs):
            raise AssertionError("backtest called with invalid execution numbers")

    payload = {
        "indicatorCode": "df['buy'] = False\ndf['sell'] = False\n",
        "symbol": "SOXL",
        "market": "USStock",
        "timeframe": "1m",
        "startDate": "2026-05-01",
        "endDate": "2026-05-01",
    }
    payload.update(override)

    with pytest.raises(ValueError, match=message):
        run_autoresearch_backtest(payload, backtest_service=FailBacktestService())


def test_fixed_share_position_sizing_uses_configured_share_count():
    index = pd.date_range("2026-01-01 09:30", periods=3, freq="min")
    df = pd.DataFrame(
        {
            "open": [100.0, 110.0, 110.0],
            "high": [100.0, 110.0, 110.0],
            "low": [100.0, 110.0, 110.0],
            "close": [100.0, 110.0, 110.0],
        },
        index=index,
    )
    signals = {
        "buy": pd.Series([True, False, False], index=index),
        "sell": pd.Series([False, True, False], index=index),
    }

    _, trades, _ = BacktestService()._simulate_trading(
        df=df,
        signals=signals,
        initial_capital=10000.0,
        commission=0.0,
        slippage=0.0,
        leverage=1,
        trade_direction="long",
        strategy_config={"position": {"sizingMode": "shares", "sizingValue": 10}},
    )

    assert trades[0]["type"] == "open_long"
    assert trades[0]["amount"] == 10.0
    assert trades[1]["type"] == "close_long"
    assert trades[1]["amount"] == 10.0


def test_single_user_mode_accepts_signed_token_without_db_token_version(monkeypatch):
    token = auth.generate_token(user_id=1, username="quantdinger", role="admin", token_version=7)

    monkeypatch.setenv("SINGLE_USER_MODE", "true")
    monkeypatch.setattr(auth, "_verify_token_version", lambda *_args, **_kwargs: False)

    payload = auth.verify_token(token)

    assert payload["sub"] == "quantdinger"
    assert payload["user_id"] == 1
    assert payload["token_version"] == 7


def test_multi_user_mode_keeps_db_token_version_check(monkeypatch):
    token = auth.generate_token(user_id=1, username="quantdinger", role="admin", token_version=7)

    monkeypatch.setenv("SINGLE_USER_MODE", "false")
    monkeypatch.setattr(auth, "_verify_token_version", lambda *_args, **_kwargs: False)

    assert auth.verify_token(token) is None
