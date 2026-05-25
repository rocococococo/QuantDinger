"""AutoResearch native capability tests."""

from datetime import datetime

from app.routes.backtest import (
    _autoresearch_cost_stress_payload,
    _autoresearch_execution_config,
    _autoresearch_validation_window_metrics,
    _autoresearch_native_run_id,
    _autoresearch_ohlcv_rows,
    _request_commission,
    _request_slippage,
)
from app.routes import backtest as backtest_routes
from app.services.backtest import BacktestService
from app.utils import auth


def test_autoresearch_capabilities_endpoint_reports_native_cost_stress(client):
    resp = client.get('/api/autoresearch/capabilities')

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['status'] == 'ok'
    assert data['local_compat'] is False
    assert data['native_engine'] is True
    assert data['supports_sampled_window_cost_stress'] is True
    assert 'sampled_window_cost_stress' in data['capabilities']


def test_autoresearch_indicator_backtest_endpoint_runs_without_ui_login(client, monkeypatch):
    captured = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        return {
            'totalProfit': 12.5,
            'totalReturn': 0.125,
            'maxDrawdown': 0.0,
            'totalTrades': 1,
            'equityCurve': [{'time': '2026-05-01 13:31', 'value': 10012.5}],
            'trades': [{'time': '2026-05-01 13:31', 'type': 'close_long', 'profit': 12.5}],
            'executionAssumptions': {
                'actualDataRange': {
                    'start': '2026-05-01T13:30:00+00:00',
                    'end': '2026-05-01T13:31:00+00:00',
                }
            },
        }

    monkeypatch.setattr(backtest_routes.backtest_service, 'run', fake_run)

    resp = client.post(
        '/api/autoresearch/indicator-backtest',
        json={
            'indicatorCode': "df['buy'] = False\ndf['sell'] = False\n",
            'symbol': 'SOXL',
            'market': 'USStock',
            'timeframe': '1m',
            'startDate': '2026-05-01',
            'endDate': '2026-05-01',
            'persist': False,
            'autoresearchTrace': {
                'run_id': 'ar-run-001',
                'candidate_id': 'candidate-001',
                'strategy_ir_sha256': 'sha256:ir',
                'qd_code_sha256': 'sha256:code',
            },
            'qd_native_validation_scope': 'sampled_window',
            'autoresearchValidationWindow': {
                'start_datetime': '2026-05-01T13:30:00+00:00',
                'end_datetime': '2026-05-01T13:31:00+00:00',
            },
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['code'] == 1
    assert payload['data']['persistenceStatus'] == 'ephemeral'
    assert payload['data']['nativeRunId'].startswith('autoresearch-ephemeral-')
    assert captured['symbol'] == 'SOXL'


def test_autoresearch_cost_stress_scope_uses_stressed_execution_config():
    data = {
        'qd_native_validation_scope': 'sampled_window_cost_stress',
        'sampleWindowPlanHash': 'sha256:sample-plan',
        'scenarioGridHash': 'sha256:scenario-grid',
        'costStressScenarioId': 'next_bar_open_2x_cost',
        'strategyConfig': {'execution': {'fill_model': 'signal_bar_close', 'commission_value': 0.01}},
        'costStressScenario': {
            'stress_multiple': 2.0,
            'fill_model': 'next_bar_open',
            'execution': {
                'fill_model': 'next_bar_open',
                'commission_model': 'fixed',
                'commission_value': 0.02,
                'slippage_model': 'bps',
                'slippage_bps': 4.0,
            },
        },
    }
    execution = _autoresearch_execution_config(data, data['strategyConfig'])

    assert _request_commission(data, execution) == 0.02
    assert _request_slippage(data, execution) == 0.0004

    payload = _autoresearch_cost_stress_payload(
        data,
        result={
            'totalProfit': 5.0,
            'totalReturn': 0.05,
            'maxDrawdown': -0.01,
            'totalTrades': 2,
            'totalCommission': 0.04,
            'equityCurve': [{'time': '2026-05-08 20:00', 'value': 10005.0}],
        },
        commission=0.02,
        slippage=0.0004,
        execution=execution,
    )

    assert payload['source'] == 'qd_native_same_window_cost_replay'
    assert payload['passed'] is True
    assert payload['sample_window_plan_hash'] == 'sha256:sample-plan'
    assert payload['scenario_grid_hash'] == 'sha256:scenario-grid'
    assert payload['scenario_id'] == 'next_bar_open_2x_cost'
    assert payload['cost_model']['commission'] == 0.02
    assert payload['cost_model']['slippage'] == 0.0004
    assert payload['blocking_reasons'] == []


def test_autoresearch_validation_window_metrics_exclude_execution_warmup():
    data = {
        'qd_native_validation_scope': 'sampled_window',
        'autoresearchValidationWindow': {
            'start_datetime': '2026-02-01T14:30:00+00:00',
            'end_datetime': '2026-02-02T21:00:00+00:00',
        },
    }
    result = {
        'totalProfit': 999.0,
        'maxDrawdown': -20.0,
        'totalTrades': 99,
        'equityCurve': [
            {'time': '2026-01-31 20:00', 'value': 10000.0},
            {'time': '2026-02-01 14:30', 'value': 10001.0},
            {'time': '2026-02-02 20:00', 'value': 10004.0},
        ],
        'trades': [
            {'time': '2026-01-31 20:00', 'type': 'close_long', 'profit': 999.0},
            {'time': '2026-02-02 20:00', 'type': 'close_long', 'profit': 3.0},
        ],
    }

    metrics = _autoresearch_validation_window_metrics(data, result=result, initial_capital=10000.0)

    assert metrics['totalProfit'] == 3.0
    assert metrics['totalTrades'] == 1
    assert metrics['maxDrawdown'] == 0.0
    assert metrics['equityBasis'] == 'validation_window_relative_pnl'
    assert metrics['equityFloor'] == 0.0
    assert metrics['validationWindow'] == data['autoresearchValidationWindow']
    assert metrics['equityCurve'] == [
        {'time': '2026-02-01 14:30', 'value': 0.0},
        {'time': '2026-02-02 20:00', 'value': 3.0},
    ]
    assert metrics['trades'] == [{'time': '2026-02-02 20:00', 'type': 'close_long', 'profit': 3.0}]


def test_autoresearch_cost_stress_uses_validation_relative_equity_floor():
    data = {
        'qd_native_validation_scope': 'sampled_window_cost_stress',
        'sampleWindowPlanHash': 'sha256:sample-plan',
        'scenarioGridHash': 'sha256:scenario-grid',
        'costStressScenarioId': 'next_bar_open_2x_cost',
    }

    payload = _autoresearch_cost_stress_payload(
        data,
        result={
            'totalProfit': 3.0,
            'totalReturn': 0.03,
            'maxDrawdown': 0.0,
            'totalTrades': 1,
            'totalCommission': 0.04,
            'equityBasis': 'validation_window_relative_pnl',
            'equityFloor': 0.0,
            'equityCurve': [
                {'time': '2026-02-01 14:30', 'value': 0.0},
                {'time': '2026-02-02 20:00', 'value': 3.0},
            ],
        },
        commission=0.02,
        slippage=0.0004,
        execution={},
    )

    assert payload['passed'] is True
    assert payload['observed']['total_profit'] == 3.0
    assert payload['observed']['equity_basis'] == 'validation_window_relative_pnl'
    assert payload['observed']['equity_floor'] == 0.0
    assert payload['blocking_reasons'] == []


def test_autoresearch_cost_stress_blocks_relative_equity_floor_breach():
    data = {
        'qd_native_validation_scope': 'sampled_window_cost_stress',
        'sampleWindowPlanHash': 'sha256:sample-plan',
        'scenarioGridHash': 'sha256:scenario-grid',
        'costStressScenarioId': 'next_bar_open_2x_cost',
    }

    payload = _autoresearch_cost_stress_payload(
        data,
        result={
            'totalProfit': 2.0,
            'totalReturn': 0.02,
            'maxDrawdown': -0.05,
            'totalTrades': 1,
            'totalCommission': 0.04,
            'equityBasis': 'validation_window_relative_pnl',
            'equityFloor': 0.0,
            'equityCurve': [
                {'time': '2026-02-01 14:30', 'value': 0.0},
                {'time': '2026-02-01 15:30', 'value': -1.0},
                {'time': '2026-02-02 20:00', 'value': 2.0},
            ],
        },
        commission=0.02,
        slippage=0.0004,
        execution={},
    )

    assert payload['passed'] is False
    assert payload['observed']['min_equity'] == -1.0
    assert 'qd_native_cost_stress_equity_floor_breached' in payload['blocking_reasons']


def test_autoresearch_native_run_id_falls_back_when_persistence_is_unavailable():
    data = {
        'autoresearchTrace': {
            'run_id': 'ar-run-001',
            'candidate_id': 'candidate-002',
            'source_surface': 'autoresearch_autonomous_loop',
            'strategy_ir_sha256': 'sha256:ir',
            'qd_code_sha256': 'sha256:code',
            'benchmark_set_hash': 'sha256:bench',
        },
        'qd_native_validation_scope': 'sampled_window',
        'sampleWindowPlanHash': 'sha256:sample-plan',
    }
    result = {
        'executionAssumptions': {
            'actualDataRange': {
                'start': '2026-05-01T13:30:00+00:00',
                'end': '2026-05-03T20:00:00+00:00',
            },
        },
    }

    first = _autoresearch_native_run_id(data, result, None)
    second = _autoresearch_native_run_id(data, result, None)

    assert first.startswith('autoresearch-ephemeral-')
    assert first == second
    assert _autoresearch_native_run_id(data, result, 123) == '123'


def test_autoresearch_supplied_ohlcv_rows_require_trace_and_sample_scope():
    rows = [{'timestamp': '2026-05-01T13:30:00Z', 'open': 1, 'high': 2, 'low': 1, 'close': 2}]

    assert _autoresearch_ohlcv_rows({'autoresearchOhlcvRows': rows, 'qd_native_validation_scope': 'sampled_window'}) == []
    assert _autoresearch_ohlcv_rows({'autoresearchTrace': {}, 'autoresearchOhlcvRows': rows}) == []
    assert _autoresearch_ohlcv_rows(
        {
            'autoresearchTrace': {'run_id': 'run-001'},
            'qd_native_validation_scope': 'sampled_window',
            'autoresearchOhlcvRows': rows,
        }
    ) == rows


def test_backtest_service_uses_autoresearch_supplied_ohlcv_rows(monkeypatch):
    service = BacktestService()

    def fail_fetch(*_args, **_kwargs):
        raise AssertionError('external fetch should not run for supplied autoresearch rows')

    monkeypatch.setattr(service, '_fetch_kline_data', fail_fetch)
    rows = [
        {'timestamp': '2026-05-01T13:30:00Z', 'open': 10, 'high': 11, 'low': 9, 'close': 10, 'volume': 100},
        {'timestamp': '2026-05-01T13:31:00Z', 'open': 10, 'high': 12, 'low': 10, 'close': 12, 'volume': 100},
        {'timestamp': '2026-05-01T13:32:00Z', 'open': 12, 'high': 12, 'low': 11, 'close': 11, 'volume': 100},
    ]
    result = service.run(
        indicator_code=(
            "df['buy'] = False\n"
            "df['sell'] = False\n"
            "df.loc[0, 'buy'] = True\n"
            "df.loc[len(df) - 1, 'sell'] = True\n"
        ),
        market='USStock',
        symbol='SOXL',
        timeframe='1m',
        start_date=datetime(2026, 5, 1, 13, 30),
        end_date=datetime(2026, 5, 1, 13, 32),
        initial_capital=1000,
        commission=0.0,
        slippage=0.0,
        trade_direction='long',
        ohlcv_rows=rows,
    )

    provenance = result['executionAssumptions']['marketDataProvenance']
    assert provenance['source'] == 'autoresearch_supplied_same_window_ohlcv'
    assert provenance['data_source_mode'] == 'supplied_same_window_ohlcv'
    assert provenance['independent_from_autoresearch_payload'] is False
    assert provenance['row_count'] == 3
    assert provenance['rows_hash'].startswith('sha256:')


def test_single_user_mode_accepts_signed_token_without_db_token_version(monkeypatch):
    token = auth.generate_token(user_id=1, username='quantdinger', role='admin', token_version=7)

    monkeypatch.setenv('SINGLE_USER_MODE', 'true')
    monkeypatch.setattr(auth, '_verify_token_version', lambda *_args, **_kwargs: False)

    payload = auth.verify_token(token)

    assert payload['sub'] == 'quantdinger'
    assert payload['user_id'] == 1
    assert payload['token_version'] == 7


def test_multi_user_mode_keeps_db_token_version_check(monkeypatch):
    token = auth.generate_token(user_id=1, username='quantdinger', role='admin', token_version=7)

    monkeypatch.setenv('SINGLE_USER_MODE', 'false')
    monkeypatch.setattr(auth, '_verify_token_version', lambda *_args, **_kwargs: False)

    assert auth.verify_token(token) is None
