"""AutoResearch native contract utilities.

This module keeps AutoResearch request semantics out of human-facing route
modules. QuantDinger owns the host surfaces; AutoResearch contributes payload
normalization, provenance, and scoring metadata.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from typing import Any, Optional


AUTORESEARCH_COMPATIBILITY_BACKTEST_PATH = "/api/autoresearch/indicator-backtest"
AUTORESEARCH_AGENT_BACKTEST_PATH = "/api/agent/v1/autoresearch/backtests"
AUTORESEARCH_BACKTEST_PATH = AUTORESEARCH_AGENT_BACKTEST_PATH
AUTORESEARCH_COST_STRESS_CONTRACT = "autoresearch_qd_native_cost_stress_sample.v1"
MAX_AUTORESEARCH_REQUEST_BYTES = 8 * 1024 * 1024
MAX_SUPPLIED_OHLCV_ROWS = 25_000
MAX_AUTORESEARCH_LEVERAGE = 100


def autoresearch_compatibility_backtest_enabled() -> bool:
    value = str(os.getenv("AUTORESEARCH_NATIVE_COMPAT_ENABLED") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def capabilities_payload() -> dict[str, Any]:
    """Return the QD-hosted AutoResearch capability contract."""
    compatibility_enabled = autoresearch_compatibility_backtest_enabled()
    backtest_path = AUTORESEARCH_COMPATIBILITY_BACKTEST_PATH if compatibility_enabled else AUTORESEARCH_AGENT_BACKTEST_PATH
    return {
        "status": "ok",
        "local_compat": False,
        "native_engine": True,
        "supports_sampled_window_cost_stress": True,
        "backtest_path": backtest_path,
        "agent_backtest_path": AUTORESEARCH_AGENT_BACKTEST_PATH,
        "compatibility_backtest_path": AUTORESEARCH_COMPATIBILITY_BACKTEST_PATH,
        "compatibility_backtest_enabled": compatibility_enabled,
        "compatibility_backtest_mode": "legacy_sync_enabled" if compatibility_enabled else "disabled_by_default",
        "job_stream_path": "/api/agent/v1/jobs/{job_id}/stream",
        "max_request_bytes": MAX_AUTORESEARCH_REQUEST_BYTES,
        "max_supplied_ohlcv_rows": MAX_SUPPLIED_OHLCV_ROWS,
        "capabilities": [
            "indicator_backtest",
            "sampled_window",
            "sampled_window_cost_stress",
            "agent_gateway_job",
        ],
    }


def parse_backtest_datetime(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("empty datetime")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return {}


def first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def float_or_none(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def request_initial_capital(data: dict[str, Any], default: float = 10000.0) -> float:
    value = first_present(data.get("initialCapital"), data.get("initial_capital"), default)
    parsed = _required_number(value, "initialCapital")
    if parsed <= 0:
        raise ValueError("initialCapital must be positive")
    return parsed


def request_leverage(data: dict[str, Any], default: int = 1) -> int:
    value = first_present(data.get("leverage"), default)
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("leverage must be an integer") from exc
    if parsed < 1 or parsed > MAX_AUTORESEARCH_LEVERAGE:
        raise ValueError(f"leverage must be between 1 and {MAX_AUTORESEARCH_LEVERAGE}")
    return parsed


def _optional_number(value: Any, label: str) -> Optional[float]:
    if value is None or value == "":
        return None
    return _required_number(value, label)


def _required_number(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be finite")
    return parsed


def _non_negative_number(value: float, label: str) -> float:
    if value < 0:
        raise ValueError(f"{label} must be non-negative")
    return value


def normalized_autoresearch_backtest_request(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the required AutoResearch backtest alias groups."""
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")

    indicator_code = _required_text(data, "indicatorCode", "indicatorCode", "indicator_code", "code")
    market = _required_text(data, "market", "market", "market_type")
    symbol = _required_text(data, "symbol", "symbol", "instrument")
    timeframe = _required_text(data, "timeframe", "timeframe", "interval")
    start_value = _required_value(
        data,
        "startDate",
        "startDateTime",
        "startDatetime",
        "start_date_time",
        "start_date",
        "startDate",
    )
    end_value = _required_value(
        data,
        "endDate",
        "endDateTime",
        "endDatetime",
        "end_date_time",
        "end_date",
        "endDate",
    )

    try:
        start_date = parse_backtest_datetime(start_value)
    except ValueError as exc:
        raise ValueError("startDate is invalid") from exc
    try:
        end_date = parse_backtest_datetime(end_value)
    except ValueError as exc:
        raise ValueError("endDate is invalid") from exc
    end_text = str(end_value)
    if len(end_text.strip()) == 10:
        end_date = end_date.replace(hour=23, minute=59, second=59)

    return {
        "indicator_code": indicator_code,
        "market": market,
        "symbol": symbol,
        "timeframe": timeframe,
        "start_date": start_date,
        "start_text": str(start_value),
        "end_date": end_date,
        "end_text": end_text,
    }


def _required_text(data: dict[str, Any], label: str, *aliases: str) -> str:
    value = _required_value(data, label, *aliases)
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


def _required_value(data: dict[str, Any], label: str, *aliases: str) -> Any:
    for alias in aliases:
        value = data.get(alias)
        if value is not None and value != "":
            return value
    raise ValueError(f"{label} is required")


def execution_config(data: dict[str, Any], strategy_config: dict[str, Any]) -> dict[str, Any]:
    """Merge strategy, request, and cost-stress execution config."""
    scenario = first_mapping(data.get("costStressScenario"), data.get("cost_stress_scenario"))
    scenario_execution = first_mapping(scenario.get("execution"))
    execution = first_mapping(data.get("execution"))
    strategy_execution = first_mapping(strategy_config.get("execution"))
    merged = {**strategy_execution, **execution, **scenario_execution}
    return dict(merged) if merged else {}


def request_commission(data: dict[str, Any], execution: dict[str, Any], default: float = 0.001) -> float:
    scenario = first_mapping(data.get("costStressScenario"), data.get("cost_stress_scenario"))
    scenario_execution = first_mapping(scenario.get("execution"))
    scenario_value = _optional_number(
        first_present(
            scenario_execution.get("commission_value"),
            scenario_execution.get("commissionValue"),
            scenario_execution.get("commission"),
        ),
        "commission",
    )
    if scenario_value is not None:
        return _non_negative_number(scenario_value, "commission")
    direct = _optional_number(data.get("commission"), "commission")
    if direct is not None:
        return _non_negative_number(direct, "commission")
    value = _optional_number(
        first_present(
            execution.get("commission_value"),
            execution.get("commissionValue"),
            execution.get("commission"),
        ),
        "commission",
    )
    if value is not None:
        return _non_negative_number(value, "commission")
    return default if direct is None else direct


def request_slippage(data: dict[str, Any], execution: dict[str, Any], default: float = 0.0) -> float:
    scenario = first_mapping(data.get("costStressScenario"), data.get("cost_stress_scenario"))
    scenario_execution = first_mapping(scenario.get("execution"))
    scenario_bps = _optional_number(
        first_present(scenario_execution.get("slippage_bps"), scenario_execution.get("slippageBps")),
        "slippage_bps",
    )
    if scenario_bps is not None:
        return _non_negative_number(scenario_bps, "slippage_bps") / 10000.0
    scenario_value = _optional_number(scenario_execution.get("slippage"), "slippage")
    if scenario_value is not None:
        return _non_negative_number(scenario_value, "slippage")
    direct = _optional_number(data.get("slippage"), "slippage")
    if direct is not None:
        return _non_negative_number(direct, "slippage")
    bps = _optional_number(first_present(execution.get("slippage_bps"), execution.get("slippageBps")), "slippage_bps")
    if bps is not None:
        return _non_negative_number(bps, "slippage_bps") / 10000.0
    value = _optional_number(execution.get("slippage"), "slippage")
    if value is not None:
        return _non_negative_number(value, "slippage")
    return default if direct is None else direct


def validation_scope(data: dict[str, Any]) -> str:
    trace = data.get("autoresearchTrace") if isinstance(data.get("autoresearchTrace"), dict) else {}
    return str(
        data.get("qd_native_validation_scope")
        or data.get("qdNativeValidationScope")
        or trace.get("qd_native_validation_scope")
        or ""
    ).strip()


def supplied_ohlcv_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    trace = data.get("autoresearchTrace") if isinstance(data.get("autoresearchTrace"), dict) else {}
    if not trace:
        return []
    if validation_scope(data) not in ("sampled_window", "sampled_window_cost_stress"):
        return []
    missing = object()
    rows = missing
    for alias in ("autoresearchOhlcvRows", "autoresearch_ohlcv_rows", "marketDataRows"):
        if alias in data:
            rows = data.get(alias)
            break
    if rows is missing:
        return []
    if not isinstance(rows, list):
        raise ValueError("supplied OHLCV rows must be a list")
    if len(rows) > MAX_SUPPLIED_OHLCV_ROWS:
        raise ValueError(f"supplied OHLCV row count exceeds {MAX_SUPPLIED_OHLCV_ROWS}")
    malformed_index = next((index for index, row in enumerate(rows) if not isinstance(row, dict)), None)
    if malformed_index is not None:
        raise ValueError(f"supplied OHLCV row {malformed_index} must be an object")
    return [dict(row) for row in rows]


def native_run_id(data: dict[str, Any], result: dict[str, Any], run_id: Any) -> str:
    if run_id is not None:
        return str(run_id)
    trace = data.get("autoresearchTrace") if isinstance(data.get("autoresearchTrace"), dict) else {}
    if not trace:
        return ""
    assumptions = result.get("executionAssumptions") if isinstance(result.get("executionAssumptions"), dict) else {}
    seed = {
        "run_id": trace.get("run_id"),
        "candidate_id": trace.get("candidate_id"),
        "source_surface": trace.get("source_surface"),
        "strategy_ir_sha256": trace.get("strategy_ir_sha256"),
        "qd_code_sha256": trace.get("qd_code_sha256"),
        "benchmark_set_hash": trace.get("benchmark_set_hash"),
        "validation_scope": validation_scope(data),
        "sample_window_plan_hash": data.get("sampleWindowPlanHash") or data.get("sample_window_plan_hash"),
        "scenario_grid_hash": data.get("scenarioGridHash") or data.get("scenario_grid_hash"),
        "cost_stress_scenario_id": data.get("costStressScenarioId") or data.get("cost_stress_scenario_id"),
        "actual_range": assumptions.get("actualDataRange", {}),
    }
    digest = hashlib.sha256(
        json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"autoresearch-ephemeral-{digest[:16]}"


def cost_stress_payload(
    data: dict[str, Any],
    *,
    result: dict[str, Any],
    commission: float,
    slippage: float,
    execution: dict[str, Any],
) -> dict[str, Any]:
    if validation_scope(data) != "sampled_window_cost_stress":
        return {}
    scenario = first_mapping(data.get("costStressScenario"), data.get("cost_stress_scenario"))
    scenario_id = str(
        data.get("costStressScenarioId")
        or data.get("cost_stress_scenario_id")
        or scenario.get("scenario_id")
        or scenario.get("scenarioId")
        or ""
    ).strip()
    sample_window_plan_hash = str(data.get("sampleWindowPlanHash") or data.get("sample_window_plan_hash") or "").strip()
    scenario_grid_hash = str(data.get("scenarioGridHash") or data.get("scenario_grid_hash") or "").strip()
    stress_multiple = float_or_none(first_present(scenario.get("stress_multiple"), scenario.get("stressMultiple")))
    fill_model = str(first_present(scenario.get("fill_model"), scenario.get("fillModel"), execution.get("fill_model")) or "").strip()
    observed = cost_stress_observed(result)
    reasons: list[str] = []
    if observed.get("total_trades", 0) <= 0:
        reasons.append("qd_native_cost_stress_trades_missing")
    if observed.get("total_profit", 0.0) <= 0.0:
        reasons.append("qd_native_cost_stress_total_return_not_positive")
    min_equity = observed.get("min_equity")
    equity_floor = observed.get("equity_floor")
    equity_basis = str(observed.get("equity_basis") or "").strip()
    if equity_basis != "validation_window_relative_pnl":
        if min_equity is not None and equity_floor is not None and min_equity < equity_floor:
            reasons.append("qd_native_cost_stress_equity_floor_breached")
        if min_equity is not None and equity_floor is None and min_equity <= 0.0:
            reasons.append("qd_native_cost_stress_equity_floor_breached")
    return {
        "contract_version": AUTORESEARCH_COST_STRESS_CONTRACT,
        "authority": "qd-native",
        "scope": "sampled_window_cost_stress",
        "status": "observed",
        "passed": len(reasons) == 0,
        "basis": "qd_native_same_window_cost_replay",
        "source": "qd_native_same_window_cost_replay",
        "spread_model": "explicit_or_estimated_spread.v1",
        "sample_window_plan_hash": sample_window_plan_hash,
        "scenario_grid_hash": scenario_grid_hash,
        "scenario_id": scenario_id,
        "stress_multiple": stress_multiple,
        "fill_model": fill_model,
        "execution": dict(execution),
        "cost_model": {
            "commission": commission,
            "slippage": slippage,
            "commission_model": execution.get("commission_model") or execution.get("commissionModel") or "",
            "slippage_model": execution.get("slippage_model") or execution.get("slippageModel") or "",
            "slippage_bps": execution.get("slippage_bps") or execution.get("slippageBps"),
        },
        "observed": observed,
        "blocking_reasons": reasons,
    }


def cost_stress_observed(result: dict[str, Any]) -> dict[str, Any]:
    equity_curve = result.get("equityCurve") if isinstance(result.get("equityCurve"), list) else []
    equity_values = []
    for point in equity_curve:
        if not isinstance(point, dict):
            continue
        value = float_or_none(point.get("value") if point.get("value") is not None else point.get("equity"))
        if value is not None:
            equity_values.append(value)
    return {
        "total_profit": float_or_none(result.get("totalProfit")) or 0.0,
        "total_return": float_or_none(result.get("totalReturn")) or 0.0,
        "max_drawdown": float_or_none(result.get("maxDrawdown")) or 0.0,
        "total_trades": int(float_or_none(result.get("totalTrades")) or 0),
        "total_commission": float_or_none(result.get("totalCommission")) or 0.0,
        "equity_basis": str(result.get("equityBasis") or "").strip(),
        "equity_floor": float_or_none(result.get("equityFloor")),
        "min_equity": min(equity_values) if equity_values else None,
        "max_equity": max(equity_values) if equity_values else None,
        "equity_point_count": len(equity_values),
    }


def validation_window(data: dict[str, Any]) -> dict[str, Any]:
    trace = data.get("autoresearchTrace") if isinstance(data.get("autoresearchTrace"), dict) else {}
    return first_mapping(
        data.get("autoresearchValidationWindow"),
        data.get("autoresearch_validation_window"),
        data.get("validationWindow"),
        data.get("validation_window"),
        trace.get("validation_window"),
    )


def window_datetime_bounds(window: dict[str, Any]) -> tuple[Optional[datetime], Optional[datetime]]:
    start = first_present(
        window.get("start_datetime"),
        window.get("startDateTime"),
        window.get("startDatetime"),
        window.get("start"),
    )
    end = first_present(
        window.get("end_datetime"),
        window.get("endDateTime"),
        window.get("endDatetime"),
        window.get("end"),
    )
    if not start or not end:
        return None, None
    try:
        return parse_backtest_datetime(start), parse_backtest_datetime(end)
    except ValueError:
        return None, None


def result_timestamp(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return parse_backtest_datetime(text)
    except ValueError:
        return None


def validation_window_metrics(data: dict[str, Any], *, result: dict[str, Any], initial_capital: float) -> dict[str, Any]:
    if validation_scope(data) not in ("sampled_window", "sampled_window_cost_stress"):
        return {}
    window = validation_window(data)
    if not window:
        return {}
    start_dt, end_dt = window_datetime_bounds(window)
    if start_dt is None or end_dt is None or end_dt < start_dt:
        return {}
    equity_curve = result.get("equityCurve") if isinstance(result.get("equityCurve"), list) else []
    points: list[tuple[datetime, str, float]] = []
    for point in equity_curve:
        if not isinstance(point, dict):
            continue
        timestamp_text = str(point.get("time") or point.get("timestamp") or "").strip()
        timestamp = result_timestamp(timestamp_text)
        value = float_or_none(point.get("value") if point.get("value") is not None else point.get("equity"))
        if timestamp is not None and value is not None:
            points.append((timestamp, timestamp_text, value))
    points.sort(key=lambda item: item[0])
    in_window = [(timestamp_text, value) for timestamp, timestamp_text, value in points if start_dt <= timestamp <= end_dt]
    if not in_window:
        return {}
    baseline_candidates = [value for timestamp, _timestamp_text, value in points if timestamp <= start_dt]
    baseline = baseline_candidates[-1] if baseline_candidates else in_window[0][1]
    relative_equity = [{"time": timestamp_text, "value": round(value - baseline, 10)} for timestamp_text, value in in_window]
    relative_values = [point["value"] for point in relative_equity]
    max_drawdown_amount = max_drawdown_amount_from_values(relative_values)
    max_drawdown_pct = round((max_drawdown_amount / initial_capital) * 100.0, 10) if initial_capital > 0 else max_drawdown_amount
    trades = window_trades(result.get("trades") if isinstance(result.get("trades"), list) else [], start_dt, end_dt)
    total_profit = relative_values[-1] if relative_values else 0.0
    return {
        "totalProfit": round(total_profit, 10),
        "totalReturn": round((total_profit / initial_capital) * 100.0, 10) if initial_capital > 0 else 0.0,
        "maxDrawdown": max_drawdown_pct,
        "totalTrades": len([trade for trade in trades if float_or_none(trade.get("profit")) not in (None, 0.0)]),
        "totalCommission": round(sum(float_or_none(trade.get("commission")) or 0.0 for trade in trades), 10),
        "equityCurve": relative_equity,
        "trades": trades,
        "validationWindow": dict(window),
        "equityBasis": "validation_window_relative_pnl",
        "equityFloor": 0.0,
    }


def window_trades(trades: list[Any], start_dt: datetime, end_dt: datetime) -> list[dict[str, Any]]:
    windowed = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        timestamp = result_timestamp(
            first_present(
                trade.get("exit_timestamp"),
                trade.get("exitTimestamp"),
                trade.get("exit_time"),
                trade.get("exitTime"),
                trade.get("time"),
                trade.get("timestamp"),
            )
        )
        if timestamp is not None and start_dt <= timestamp <= end_dt:
            windowed.append(dict(trade))
    return windowed


def max_drawdown_amount_from_values(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        if value > peak:
            peak = value
        drawdown = value - peak
        if drawdown < max_drawdown:
            max_drawdown = drawdown
    return round(max_drawdown, 10)


def attach_scoring_provenance(data: dict[str, Any], result: dict[str, Any], validation_metrics: dict[str, Any]) -> None:
    if not validation_metrics:
        return
    assumptions = result.get("executionAssumptions") if isinstance(result.get("executionAssumptions"), dict) else {}
    provenance = assumptions.get("marketDataProvenance") if isinstance(assumptions.get("marketDataProvenance"), dict) else {}
    provenance = dict(provenance)
    provenance["scoringValidationWindow"] = dict(validation_metrics.get("validationWindow") or {})
    trace = data.get("autoresearchTrace") if isinstance(data.get("autoresearchTrace"), dict) else {}
    execution_window = first_mapping(data.get("executionWindow"), data.get("execution_window"), trace.get("execution_window"))
    if execution_window:
        provenance["executionWindow"] = dict(execution_window)
    assumptions = dict(assumptions)
    assumptions["marketDataProvenance"] = provenance
    result["executionAssumptions"] = assumptions
