"""Agent Gateway routes for AutoResearch-hosted backtests."""
from __future__ import annotations

from typing import Any

from flask import request

from app.data_sources.factory import DataSourceFactory
from app.services.autoresearch_native.backtest_adapter import run_autoresearch_backtest
from app.services.autoresearch_native.contract import (
    MAX_AUTORESEARCH_REQUEST_BYTES,
    normalized_autoresearch_backtest_request,
)
from app.utils.agent_auth import (
    SCOPE_B,
    agent_required,
    current_token,
    current_user_id,
    instrument_allowed,
    market_allowed,
    normalize_idempotency_key,
    with_idempotency,
)
from app.utils.agent_jobs import submit_job
from app.utils.logger import get_logger

from . import agent_v1_bp
from ._helpers import envelope, error, get_json_or_400
from ._security import assert_indicator_code_size


logger = get_logger(__name__)


def _run_autoresearch_backtest(payload: dict[str, Any]) -> Any:
    return run_autoresearch_backtest(
        payload,
        user_id=int(payload.get("__user_id") or 1),
        persist_default=False,
    )


@agent_v1_bp.route("/autoresearch/backtests", methods=["POST"])
@agent_required(SCOPE_B)
def create_autoresearch_backtest():
    """Submit an AutoResearch-native backtest job through the QD host."""
    body, err = get_json_or_400(max_bytes=MAX_AUTORESEARCH_REQUEST_BYTES)
    if err:
        return err

    try:
        idempotency_key = normalize_idempotency_key(request.headers.get("Idempotency-Key"), required=True)
    except ValueError as exc:
        return error(400, str(exc), http=400)

    try:
        request_fields = normalized_autoresearch_backtest_request(body)
    except ValueError as exc:
        return error(400, str(exc), http=400)

    market = DataSourceFactory.normalize_market(request_fields["market"])
    symbol = request_fields["symbol"]
    code = request_fields["indicator_code"]
    if code:
        try:
            assert_indicator_code_size(code)
        except ValueError as exc:
            return error(400, str(exc))
    if not market_allowed(market):
        return error(403, f"Market not allowed: {market}", http=403)
    if symbol and not instrument_allowed(symbol):
        return error(403, f"Instrument not allowed: {symbol}", http=403)

    with with_idempotency("autoresearch_backtest") as existing:
        if existing:
            return envelope(
                {
                    "job_id": existing["job_id"],
                    "status": existing["status"],
                    "duplicate": True,
                },
                message="idempotent replay",
            )

    payload = dict(body)
    payload["__user_id"] = current_user_id()
    job = submit_job(
        user_id=current_user_id(),
        agent_token_id=int(current_token().get("id")),
        kind="autoresearch_backtest",
        request_payload=payload,
        runner=_run_autoresearch_backtest,
        idempotency_key=idempotency_key,
    )
    return envelope(job, message="queued", status=202)
