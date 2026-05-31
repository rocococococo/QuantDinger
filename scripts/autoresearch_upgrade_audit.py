#!/usr/bin/env python3
"""Static audit for the AutoResearch host overlay."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_FILES = [
    "backend_api_python/app/services/autoresearch_native/__init__.py",
    "backend_api_python/app/services/autoresearch_native/contract.py",
    "backend_api_python/app/services/autoresearch_native/backtest_adapter.py",
    "backend_api_python/app/routes/autoresearch.py",
    "backend_api_python/app/routes/agent_v1/autoresearch.py",
    "backend_api_python/tests/test_autoresearch_native_contract.py",
    "backend_api_python/tests/test_agent_autoresearch_backtests.py",
    "docs/agent/AUTORESEARCH_HOST_CONTRACT.md",
    "docs/agent/agent-openapi.json",
]


ALLOWED_CHANGED_FILES = {
    "backend_api_python/app/routes/__init__.py",
    "backend_api_python/app/routes/agent_v1/__init__.py",
    "backend_api_python/app/routes/agent_v1/_helpers.py",
    "backend_api_python/app/routes/agent_v1/autoresearch.py",
    "backend_api_python/app/routes/autoresearch.py",
    "backend_api_python/app/services/backtest.py",
    "backend_api_python/app/utils/auth.py",
    "backend_api_python/app/utils/agent_auth.py",
    "backend_api_python/app/utils/agent_jobs.py",
    "backend_api_python/tests/test_agent_jobs_progress.py",
    "backend_api_python/tests/test_agent_v1.py",
    "backend_api_python/tests/test_agent_autoresearch_backtests.py",
    "backend_api_python/tests/test_autoresearch_native_contract.py",
    "docs/agent/AUTORESEARCH_HOST_CONTRACT.md",
    "docs/agent/agent-openapi.json",
    "scripts/autoresearch_upgrade_audit.py",
}

ALLOWED_CHANGED_PREFIXES = (
    "backend_api_python/app/services/autoresearch_native/",
    "docs/superpowers/",
)


TEXT_CHECKS = [
    (
        "backend_api_python/app/routes/__init__.py",
        "from app.routes.autoresearch import autoresearch_bp",
        "root route imports autoresearch blueprint",
    ),
    (
        "backend_api_python/app/routes/__init__.py",
        "app.register_blueprint(autoresearch_bp, url_prefix='/api')",
        "root route mounts autoresearch at /api",
    ),
    (
        "backend_api_python/app/routes/agent_v1/__init__.py",
        "from . import autoresearch",
        "Agent Gateway imports autoresearch route module",
    ),
    (
        "backend_api_python/app/services/backtest.py",
        "ohlcv_rows: Optional[List[Dict[str, Any]]] = None",
        "BacktestService exposes ohlcv_rows seam",
    ),
    (
        "backend_api_python/app/services/backtest.py",
        "ohlcv_provenance: Optional[Dict[str, Any]] = None",
        "BacktestService exposes generic OHLCV provenance seam",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/contract.py",
        '"agent_backtest_path": AUTORESEARCH_AGENT_BACKTEST_PATH',
        "capability payload exposes Agent Gateway path",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/contract.py",
        "AUTORESEARCH_BACKTEST_PATH = AUTORESEARCH_AGENT_BACKTEST_PATH",
        "capability backtest path uses Agent Gateway as primary",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/contract.py",
        '"compatibility_backtest_path": AUTORESEARCH_COMPATIBILITY_BACKTEST_PATH',
        "capability payload exposes compatibility path separately",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/contract.py",
        '"compatibility_backtest_enabled": compatibility_enabled',
        "capability payload exposes compatibility enabled flag",
    ),
    (
        "backend_api_python/app/routes/autoresearch.py",
        "if not autoresearch_compatibility_backtest_enabled():",
        "compatibility backtest route is disabled by default",
    ),
    (
        "backend_api_python/app/routes/autoresearch.py",
        "Content-Length header is required",
        "compatibility backtest route requires Content-Length when enabled",
    ),
    (
        "backend_api_python/app/routes/autoresearch.py",
        "JSON body must be an object",
        "compatibility backtest route validates JSON object bodies",
    ),
    (
        "backend_api_python/app/routes/autoresearch.py",
        "hmac.compare_digest",
        "compatibility backtest route compares bearer token in constant time",
    ),
    (
        "backend_api_python/app/routes/autoresearch.py",
        "AUTORESEARCH_AGENT_BACKTEST_PATH",
        "compatibility route redirects clients to Agent Gateway contract",
    ),
    (
        "backend_api_python/app/routes/agent_v1/autoresearch.py",
        'kind="autoresearch_backtest"',
        "Agent Gateway queues autoresearch_backtest jobs",
    ),
    (
        "backend_api_python/app/routes/agent_v1/autoresearch.py",
        "idempotency_key=idempotency_key",
        "Agent Gateway persists AutoResearch idempotency key",
    ),
    (
        "backend_api_python/app/routes/agent_v1/autoresearch.py",
        "normalize_idempotency_key",
        "Agent Gateway bounds AutoResearch idempotency key length",
    ),
    (
        "backend_api_python/app/routes/agent_v1/autoresearch.py",
        "get_json_or_400(max_bytes=MAX_AUTORESEARCH_REQUEST_BYTES)",
        "Agent Gateway bounds AutoResearch JSON body parsing",
    ),
    (
        "backend_api_python/app/routes/agent_v1/autoresearch.py",
        "normalized_autoresearch_backtest_request(body)",
        "Agent Gateway validates required AutoResearch alias groups before enqueue",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/backtest_adapter.py",
        "normalized_autoresearch_backtest_request(data)",
        "AutoResearch adapter uses the shared request normalizer",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/backtest_adapter.py",
        "request_initial_capital(data)",
        "AutoResearch adapter validates finite positive initial capital",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/backtest_adapter.py",
        "request_leverage(data)",
        "AutoResearch adapter validates leverage bounds",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/contract.py",
        "math.isfinite",
        "AutoResearch contract rejects non-finite numeric execution inputs",
    ),
    (
        "backend_api_python/app/services/autoresearch_native/contract.py",
        "supplied OHLCV row {malformed_index} must be an object",
        "AutoResearch contract rejects malformed supplied OHLCV rows",
    ),
    (
        "backend_api_python/app/routes/agent_v1/_helpers.py",
        "Content-Length header is required",
        "Agent Gateway rejects capped JSON parsing without Content-Length",
    ),
    (
        "backend_api_python/app/routes/agent_v1/_helpers.py",
        "request_body_too_large(max_bytes)",
        "Agent Gateway checks capped JSON content length before buffering",
    ),
    (
        "backend_api_python/app/utils/agent_auth.py",
        "mark_audit_body_skipped()",
        "Agent Gateway skips audit JSON parsing for oversized bodies",
    ),
    (
        "backend_api_python/app/utils/agent_auth.py",
        "_audit_idempotency_key()",
        "Agent Gateway bounds audit idempotency key length",
    ),
    (
        "backend_api_python/app/utils/agent_jobs.py",
        "_existing_job_for_idempotency",
        "Agent jobs return existing job after idempotency insert race",
    ),
    (
        "docs/agent/agent-openapi.json",
        '"/api/agent/v1/autoresearch/backtests"',
        "Agent OpenAPI documents AutoResearch route",
    ),
    (
        "docs/agent/agent-openapi.json",
        '"autoresearch_backtest"',
        "Agent OpenAPI documents AutoResearch job kind",
    ),
]


ABSENT_TEXT_CHECKS = [
    (
        "backend_api_python/app/services/backtest.py",
        "autoresearch_supplied_same_window_ohlcv",
        "BacktestService core seam stays host-generic",
    ),
]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    failures: list[str] = []

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            failures.append(f"missing file: {rel}")

    for rel, needle, label in TEXT_CHECKS:
        path = ROOT / rel
        if not path.exists():
            failures.append(f"missing checked file: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        if needle not in text:
            failures.append(f"missing check: {label} ({rel})")

    for rel, needle, label in ABSENT_TEXT_CHECKS:
        path = ROOT / rel
        if not path.exists():
            failures.append(f"missing checked file: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        if needle in text:
            failures.append(f"unexpected text: {label} ({rel})")

    failures.extend(_audit_openapi_contract())
    failures.extend(_audit_changed_file_allowlist(args.base_ref))

    if failures:
        print("AutoResearch host overlay audit failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("AutoResearch host overlay audit OK")
    print(
        f"checked_files={len(REQUIRED_FILES)} "
        f"checked_contracts={len(TEXT_CHECKS)} "
        f"checked_absences={len(ABSENT_TEXT_CHECKS)} "
        f"checked_openapi=1 checked_diff_allowlist=1 base_ref={args.base_ref}"
    )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit the AutoResearch host overlay contract.")
    parser.add_argument(
        "--base-ref",
        default="origin/main",
        help="Git ref used as the changed-file allowlist base.",
    )
    return parser.parse_args(argv)


def _audit_openapi_contract() -> list[str]:
    failures: list[str] = []
    path = ROOT / "docs/agent/agent-openapi.json"
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"agent OpenAPI is invalid JSON: {exc}"]

    job_kind = (
        spec.get("components", {})
        .get("schemas", {})
        .get("Job", {})
        .get("properties", {})
        .get("kind", {})
        .get("enum", [])
    )
    if "autoresearch_backtest" not in job_kind:
        failures.append("agent OpenAPI Job.kind enum lacks autoresearch_backtest")

    route = spec.get("paths", {}).get("/api/agent/v1/autoresearch/backtests", {}).get("post")
    if not isinstance(route, dict):
        return failures + ["agent OpenAPI lacks /api/agent/v1/autoresearch/backtests POST"]
    if route.get("x-scope-class") != "B":
        failures.append("agent OpenAPI AutoResearch route must be scope class B")

    params = route.get("parameters") if isinstance(route.get("parameters"), list) else []
    idem = next(
        (
            param for param in params
            if param.get("in") == "header" and param.get("name") == "Idempotency-Key"
        ),
        None,
    )
    if not isinstance(idem, dict) or idem.get("required") is not True:
        failures.append("agent OpenAPI AutoResearch route must require Idempotency-Key")

    schema_ref = (
        route.get("requestBody", {})
        .get("content", {})
        .get("application/json", {})
        .get("schema", {})
        .get("$ref")
    )
    if schema_ref != "#/components/schemas/AutoResearchBacktestRequest":
        failures.append("agent OpenAPI AutoResearch route must reference AutoResearchBacktestRequest")
    schema = spec.get("components", {}).get("schemas", {}).get("AutoResearchBacktestRequest", {})
    schema_text = json.dumps(schema, sort_keys=True)
    for alias in ("indicator_code", "market_type", "instrument", "interval", "startDateTime", "endDateTime"):
        if alias not in schema_text:
            failures.append(f"agent OpenAPI AutoResearch schema lacks alias group for {alias}")
    return failures


def _audit_changed_file_allowlist(base_ref: str) -> list[str]:
    try:
        tracked = subprocess.check_output(
            ["git", "diff", "--name-only", base_ref],
            cwd=ROOT,
            text=True,
        ).splitlines()
        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=ROOT,
            text=True,
        ).splitlines()
    except Exception as exc:
        return [f"git diff allowlist check failed: {exc}"]

    failures: list[str] = []
    for rel in sorted({*tracked, *untracked}):
        if rel in ALLOWED_CHANGED_FILES:
            continue
        if any(rel.startswith(prefix) for prefix in ALLOWED_CHANGED_PREFIXES):
            continue
        failures.append(f"changed file outside AutoResearch host overlay allowlist: {rel}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
