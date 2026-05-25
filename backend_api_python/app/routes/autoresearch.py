"""AutoResearch native capability routes."""
import os

from flask import Blueprint, g, jsonify, request


autoresearch_bp = Blueprint('autoresearch', __name__)
AUTORESEARCH_BACKTEST_PATH = '/api/autoresearch/indicator-backtest'


@autoresearch_bp.route('/autoresearch/capabilities', methods=['GET'])
def autoresearch_capabilities():
    """Report QuantDinger native AutoResearch capabilities."""
    return jsonify(
        {
            'status': 'ok',
            'local_compat': False,
            'native_engine': True,
            'supports_sampled_window_cost_stress': True,
            'backtest_path': AUTORESEARCH_BACKTEST_PATH,
            'capabilities': [
                'indicator_backtest',
                'sampled_window',
                'sampled_window_cost_stress',
            ],
        }
    )


@autoresearch_bp.route('/autoresearch/indicator-backtest', methods=['POST'])
def autoresearch_indicator_backtest():
    """Run the native indicator backtest for AutoResearch loopback workers."""
    if not _autoresearch_request_authorized():
        return jsonify({'code': 401, 'msg': 'AutoResearch native token required', 'data': None}), 401
    from app.routes.backtest import run_backtest

    g.user = 'autoresearch'
    g.user_id = _autoresearch_user_id()
    g.user_role = 'admin'
    return run_backtest.__wrapped__()


def _autoresearch_request_authorized() -> bool:
    expected_token = str(os.getenv('AUTORESEARCH_NATIVE_API_TOKEN') or '').strip()
    supplied_token = _bearer_token()
    if expected_token:
        return supplied_token == expected_token
    return request.remote_addr in {'127.0.0.1', '::1', 'localhost'}


def _bearer_token() -> str:
    auth_header = request.headers.get('Authorization') or ''
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == 'bearer':
        return parts[1]
    return ''


def _autoresearch_user_id() -> int:
    raw = str(os.getenv('AUTORESEARCH_NATIVE_USER_ID') or '1').strip()
    try:
        return int(raw)
    except ValueError:
        return 1
