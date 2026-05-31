# AutoResearch Host Contract

QuantDinger is the host framework for AutoResearch native backtests. The host owns identity, Agent Gateway scopes, async jobs, SSE streams, persistence, backtest execution, deployment, and operator-visible routes.

AutoResearch owns the research payload semantics:

- candidate trace fields under `autoresearchTrace`
- sampled-window scopes: `sampled_window`, `sampled_window_cost_stress`
- supplied same-window OHLCV rows for QD-native replay
- validation-window scoring metadata
- cost-stress scenario metadata
- native ephemeral run ids when persistence is disabled

## Host Surfaces

### Compatibility Probe

`GET /api/autoresearch/capabilities`

The response advertises the QD-native Agent Gateway backtest path, optional compatibility path, job stream path, and supported AutoResearch scopes. `backtest_path` points to the Agent Gateway route.

### Compatibility Backtest

`POST /api/autoresearch/indicator-backtest`

This transitional route is disabled by default and returns HTTP 410 with the Agent Gateway `backtest_path`. Enabling it requires `AUTORESEARCH_NATIVE_COMPAT_ENABLED=true`; bearer-token workers then use `AUTORESEARCH_NATIVE_API_TOKEN`. Local loopback development additionally requires the explicit `AUTORESEARCH_NATIVE_ALLOW_LOOPBACK=true` opt-in. Enabled requests must include `Content-Length` and a JSON object body. When enabled, it returns the historical AutoResearch response shape:

```json
{
  "code": 1,
  "msg": "Backtest succeeded",
  "data": {
    "runId": null,
    "nativeRunId": "autoresearch-ephemeral-...",
    "persistenceStatus": "ephemeral",
    "result": {}
  }
}
```

### Agent Gateway Backtest

`POST /api/agent/v1/autoresearch/backtests`

This route is the preferred host-native lane. It requires Agent scope `B`, queues a `kind=autoresearch_backtest` job, and uses the existing Agent Gateway job endpoints:

- `GET /api/agent/v1/jobs/{job_id}`
- `GET /api/agent/v1/jobs/{job_id}/stream`

Requests must include `Idempotency-Key`; QD stores the key on the queued Agent job.

## Backtest Seam

`BacktestService.run_aligned(...)`, `BacktestService.run_multi_timeframe(...)`, and `BacktestService.run(...)` accept `ohlcv_rows` plus optional `ohlcv_provenance`.

Supplied rows are converted into a pandas frame with:

- sorted UTC-naive timestamp index
- numeric `open`, `high`, `low`, `close`, `volume`
- `executionAssumptions.marketDataProvenance`
- row hash as `sha256:<digest>`

The core backtest seam records generic supplied-OHLCV provenance by default. The AutoResearch adapter injects AutoResearch provenance fields at the hosted capability layer:

- `source=autoresearch_supplied_same_window_ohlcv`
- `data_source_mode=supplied_same_window_ohlcv`
- `independent_from_autoresearch_payload=false`

Supplied rows are capped at 25,000 rows and must pass OHLCV sanity checks: list-of-object payload shape, finite numeric values, positive prices, non-negative volume, `high >= low`, and open/close inside the high-low range.

Agent Gateway requests with capped JSON bodies require `Content-Length`; oversized bodies are rejected before route JSON parsing and are redacted from audit body capture.

Agent Gateway and the AutoResearch adapter share one required-field alias normalizer. `indicatorCode`/`indicator_code`/`code`, `market`/`market_type`, `symbol`/`instrument`, `timeframe`/`interval`, and start/end date aliases are validated before jobs are queued.

Execution numeric inputs must be finite and bounded before QD runs the backtest: `initialCapital > 0`, `1 <= leverage <= 100`, `commission >= 0`, `slippage >= 0`, and cost-stress `slippage_bps >= 0`.

Compatibility route removal trigger: once AutoResearch workers submit through `/api/agent/v1/autoresearch/backtests` and consume Agent job/SSE responses directly, remove `AUTORESEARCH_NATIVE_COMPAT_ENABLED` and `/api/autoresearch/indicator-backtest` from the overlay.

Fixed-share sizing is supported through:

```json
{
  "strategyConfig": {
    "position": {
      "sizingMode": "shares",
      "sizingValue": 10
    }
  }
}
```

## Upgrade Workflow

1. Fetch upstream QD tags and identify the target tag.
2. Create an integration branch from the target upstream tag.
3. Reapply the AutoResearch overlay files and seam edits.
4. Run `python scripts/autoresearch_upgrade_audit.py --base-ref <target-upstream-ref>`.
5. Validate `docs/agent/agent-openapi.json` includes `/api/agent/v1/autoresearch/backtests`, `kind=autoresearch_backtest`, and required `Idempotency-Key`.
6. Run focused backend tests:

```bash
cd backend_api_python
python -m pytest \
  tests/test_autoresearch_native_contract.py \
  tests/test_agent_autoresearch_backtests.py \
  tests/test_agent_v1.py \
  tests/test_agent_jobs_progress.py \
  -v
```

7. Review `git diff --stat` and ensure changed files match the overlay list.

## Overlay File List

- `backend_api_python/app/services/autoresearch_native/__init__.py`
- `backend_api_python/app/services/autoresearch_native/contract.py`
- `backend_api_python/app/services/autoresearch_native/backtest_adapter.py`
- `backend_api_python/app/routes/autoresearch.py`
- `backend_api_python/app/routes/agent_v1/autoresearch.py`
- `backend_api_python/tests/test_autoresearch_native_contract.py`
- `backend_api_python/tests/test_agent_autoresearch_backtests.py`
- `docs/agent/AUTORESEARCH_HOST_CONTRACT.md`
- `docs/agent/agent-openapi.json`
- `scripts/autoresearch_upgrade_audit.py`

Expected host seam edits:

- `backend_api_python/app/routes/__init__.py`
- `backend_api_python/app/routes/agent_v1/__init__.py`
- `backend_api_python/app/routes/agent_v1/_helpers.py`
- `backend_api_python/app/services/backtest.py`
- `backend_api_python/app/utils/agent_auth.py`
- `backend_api_python/app/utils/agent_jobs.py`
- `backend_api_python/app/utils/auth.py`

## Upgrade Risk Checks

- Agent Gateway registration must import `autoresearch`.
- Root route registration must mount `autoresearch_bp` at `/api`.
- `BacktestService.run_aligned` must accept `ohlcv_rows`.
- `BacktestService.run` must accept `ohlcv_rows`.
- `BacktestService` must keep the core supplied-OHLCV seam generic and accept adapter-provided `ohlcv_provenance`.
- Capability payload must include `agent_backtest_path`.
- Agent Gateway AutoResearch route must pass `idempotency_key` to queued jobs.
- Agent Gateway must enforce the request-size cap before route JSON parsing, require `Content-Length` for capped JSON routes, and skip audit JSON parsing for oversized bodies.
- Agent Gateway must validate required AutoResearch alias groups before enqueue, using the same normalizer as the adapter.
- AutoResearch execution numeric inputs must reject `NaN`, `Infinity`, negative costs, and leverage outside `1..100`.
- Sampled-window supplied OHLCV aliases must reject malformed rows instead of falling back to host-fetched data.
- Agent Gateway audit must bound stored `Idempotency-Key` values to the database column length.
- Agent jobs must return the existing job after a concurrent idempotency insert race.
- Agent OpenAPI must document the AutoResearch route, `autoresearch_backtest` job kind, required `Idempotency-Key`, and accepted alias groups.
- Tests must cover capability, native route authorization, Agent route authorization/idempotency, supplied OHLCV, cost stress, validation metrics, fixed shares, and single-user token behavior.
