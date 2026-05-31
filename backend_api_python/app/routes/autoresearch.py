"""AutoResearch native compatibility routes."""
from __future__ import annotations

import hmac
import os
import traceback

from flask import Blueprint, jsonify, request

from app.services.autoresearch_native import capabilities_payload
from app.services.autoresearch_native.backtest_adapter import run_autoresearch_backtest
from app.services.autoresearch_native.contract import (
    AUTORESEARCH_AGENT_BACKTEST_PATH,
    MAX_AUTORESEARCH_REQUEST_BYTES,
    autoresearch_compatibility_backtest_enabled,
)
from app.utils.logger import get_logger


logger = get_logger(__name__)
autoresearch_bp = Blueprint("autoresearch", __name__)


@autoresearch_bp.route("/autoresearch/capabilities", methods=["GET"])
def autoresearch_capabilities():
    """Report QD-hosted AutoResearch capabilities."""
    return jsonify(capabilities_payload())


@autoresearch_bp.route("/autoresearch/indicator-backtest", methods=["POST"])
def autoresearch_indicator_backtest():
    """Run a native indicator backtest for AutoResearch loopback workers."""
    if not autoresearch_compatibility_backtest_enabled():
        return jsonify(
            {
                "code": 0,
                "msg": "AutoResearch compatibility backtest disabled; use Agent Gateway",
                "data": {"backtest_path": AUTORESEARCH_AGENT_BACKTEST_PATH},
            }
        ), 410
    if not _autoresearch_request_authorized():
        return jsonify({"code": 401, "msg": "AutoResearch native token required", "data": None}), 401
    if _request_too_large():
        return jsonify({"code": 0, "msg": "AutoResearch request body too large", "data": None}), 413
    if request.content_length is None:
        return jsonify({"code": 0, "msg": "Content-Length header is required", "data": None}), 411

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"code": 0, "msg": "Invalid JSON body", "data": None}), 400
    if not isinstance(data, dict):
        return jsonify({"code": 0, "msg": "JSON body must be an object", "data": None}), 400
    try:
        result = run_autoresearch_backtest(
            data,
            user_id=_autoresearch_user_id(),
            persist_default=False,
        )
        return jsonify({"code": 1, "msg": "Backtest succeeded", "data": result})
    except ValueError as exc:
        return jsonify({"code": 0, "msg": str(exc), "data": None}), 400
    except Exception as exc:
        logger.error(f"AutoResearch native backtest failed: {exc}")
        logger.error(traceback.format_exc())
        return jsonify({"code": 0, "msg": "AutoResearch native backtest failed", "data": None}), 500


def _autoresearch_request_authorized() -> bool:
    expected_token = str(os.getenv("AUTORESEARCH_NATIVE_API_TOKEN") or "").strip()
    supplied_token = _bearer_token()
    if expected_token:
        return hmac.compare_digest(supplied_token, expected_token)
    allow_loopback = str(os.getenv("AUTORESEARCH_NATIVE_ALLOW_LOOPBACK") or "").strip().lower()
    return allow_loopback in {"1", "true", "yes", "on"} and request.remote_addr in {
        "127.0.0.1",
        "::1",
        "localhost",
    }


def _request_too_large() -> bool:
    content_length = request.content_length
    return content_length is not None and int(content_length) > MAX_AUTORESEARCH_REQUEST_BYTES


def _bearer_token() -> str:
    auth_header = request.headers.get("Authorization") or ""
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return ""


def _autoresearch_user_id() -> int:
    raw = str(os.getenv("AUTORESEARCH_NATIVE_USER_ID") or "1").strip()
    try:
        return int(raw)
    except ValueError:
        return 1
