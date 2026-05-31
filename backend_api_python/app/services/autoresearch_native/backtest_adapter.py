"""Adapter from AutoResearch payloads into QuantDinger backtest execution."""
from __future__ import annotations

from typing import Any, Optional

from app.data_sources.factory import DataSourceFactory
from app.services.backtest import BacktestService
from app.services.backtest_execution import (
    default_slippage_if_missing,
    merge_strict_mode_into_strategy_config,
    parse_strict_mode,
)
from app.utils.safe_exec import validate_code_safety

from .contract import (
    attach_scoring_provenance,
    cost_stress_payload,
    execution_config,
    first_mapping,
    first_present,
    native_run_id,
    normalized_autoresearch_backtest_request,
    request_commission,
    request_initial_capital,
    request_leverage,
    request_slippage,
    supplied_ohlcv_rows,
    validation_scope,
    validation_window_metrics,
)


def run_autoresearch_backtest(
    payload: dict[str, Any],
    *,
    user_id: int = 1,
    backtest_service: Optional[BacktestService] = None,
    persist_default: bool = False,
) -> dict[str, Any]:
    """Run an AutoResearch-native indicator backtest inside the QD host."""
    service = backtest_service or BacktestService()
    data = dict(payload or {})
    request_fields = normalized_autoresearch_backtest_request(data)
    indicator_code = request_fields["indicator_code"]
    is_safe_code, unsafe_reason = validate_code_safety(indicator_code)
    if not is_safe_code:
        raise ValueError(f"Unsafe indicator code: {unsafe_reason}")

    symbol = request_fields["symbol"]
    market = DataSourceFactory.normalize_market(request_fields["market"])
    if not market:
        raise ValueError("market is required")
    timeframe = request_fields["timeframe"]
    start_date = request_fields["start_date"]
    start_text = request_fields["start_text"]
    end_date = request_fields["end_date"]
    end_text = request_fields["end_text"]

    strict_mode = parse_strict_mode(data.get("strictMode", data.get("strict_mode")), default=True)
    initial_capital = request_initial_capital(data)
    leverage = request_leverage(data)
    trade_direction = str(first_present(data.get("tradeDirection"), data.get("trade_direction"), "long") or "long")
    indicator_params = first_mapping(data.get("indicator_params"), data.get("params"))
    indicator_id = data.get("indicatorId", data.get("indicator_id"))
    strategy_config = first_mapping(data.get("strategyConfig"), data.get("strategy_config"))
    execution = execution_config(data, strategy_config)
    commission = request_commission(data, execution, default=0.001)
    slippage_default = default_slippage_if_missing(data.get("slippage"))
    slippage = request_slippage(data, execution, default=slippage_default)
    ohlcv_rows = supplied_ohlcv_rows(data)
    strategy_config = merge_strict_mode_into_strategy_config(strategy_config, strict_mode)

    result = service.run_aligned(
        strict_mode=strict_mode,
        indicator_code=indicator_code,
        market=market,
        symbol=symbol,
        timeframe=timeframe,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        commission=commission,
        slippage=slippage,
        leverage=leverage,
        trade_direction=trade_direction,
        strategy_config=strategy_config,
        indicator_params=indicator_params,
        user_id=int(user_id or data.get("__user_id") or 1),
        indicator_id=_int_or_none(indicator_id),
        ohlcv_rows=ohlcv_rows or None,
        ohlcv_provenance=_autoresearch_ohlcv_provenance(data) if ohlcv_rows else None,
    )

    assumptions = dict(result.get("executionAssumptions") or {})
    assumptions["commission"] = round(float(commission), 6)
    assumptions["slippage"] = round(float(slippage), 6)
    assumptions["strictMode"] = bool(strict_mode)
    result["executionAssumptions"] = assumptions

    validation_metrics = validation_window_metrics(data, result=result, initial_capital=initial_capital)
    if validation_metrics:
        result["autoresearchValidationMetrics"] = validation_metrics
        attach_scoring_provenance(data, result, validation_metrics)

    cost_stress = cost_stress_payload(
        data,
        result=validation_metrics or result,
        commission=commission,
        slippage=slippage,
        execution=execution,
    )
    if cost_stress:
        result["cost_stress"] = cost_stress

    run_id = None
    if _bool_from_payload(data.get("persist"), default=persist_default):
        run_id = service.persist_run(
            user_id=int(user_id or data.get("__user_id") or 1),
            indicator_id=_int_or_none(indicator_id),
            run_type="autoresearch_indicator",
            market=market,
            symbol=symbol,
            timeframe=timeframe,
            start_date_str=start_text,
            end_date_str=end_text,
            initial_capital=initial_capital,
            commission=commission,
            slippage=slippage,
            leverage=leverage,
            trade_direction=trade_direction,
            strategy_config=strategy_config,
            config_snapshot={
                "indicatorId": _int_or_none(indicator_id),
                "autoresearchTrace": data.get("autoresearchTrace") or {},
                "executionConfig": {
                    "strictMode": bool(strict_mode),
                    "commission": commission,
                    "slippage": slippage,
                },
            },
            status="success",
            error_message="",
            result=result,
            code=indicator_code,
        )

    qd_native_run_id = native_run_id(data, result, run_id)
    response = {
        "runId": run_id,
        "nativeRunId": qd_native_run_id,
        "persistenceStatus": "persisted" if run_id is not None else "ephemeral" if qd_native_run_id else "not_persisted",
        "result": result,
    }
    if validation_metrics:
        response["autoresearchValidationMetrics"] = validation_metrics
    if cost_stress:
        response["cost_stress"] = cost_stress
    return response


def _autoresearch_ohlcv_provenance(data: dict[str, Any]) -> dict[str, Any]:
    trace = data.get("autoresearchTrace") if isinstance(data.get("autoresearchTrace"), dict) else {}
    return {
        "source": "autoresearch_supplied_same_window_ohlcv",
        "data_source_mode": "supplied_same_window_ohlcv",
        "independent_from_autoresearch_payload": False,
        "validation_scope": validation_scope(data),
        "autoresearch_run_id": trace.get("run_id"),
        "autoresearch_candidate_id": trace.get("candidate_id"),
    }


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_from_payload(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)
