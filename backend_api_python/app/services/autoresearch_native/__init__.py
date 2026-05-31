"""AutoResearch native host contract helpers."""

from .contract import (
    AUTORESEARCH_AGENT_BACKTEST_PATH,
    AUTORESEARCH_BACKTEST_PATH,
    attach_scoring_provenance,
    capabilities_payload,
    cost_stress_payload,
    execution_config,
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

__all__ = [
    "AUTORESEARCH_AGENT_BACKTEST_PATH",
    "AUTORESEARCH_BACKTEST_PATH",
    "attach_scoring_provenance",
    "capabilities_payload",
    "cost_stress_payload",
    "execution_config",
    "native_run_id",
    "normalized_autoresearch_backtest_request",
    "request_commission",
    "request_initial_capital",
    "request_leverage",
    "request_slippage",
    "supplied_ohlcv_rows",
    "validation_scope",
    "validation_window_metrics",
]
