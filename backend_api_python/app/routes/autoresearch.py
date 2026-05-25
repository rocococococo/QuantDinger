"""AutoResearch native capability routes."""
from flask import Blueprint, jsonify


autoresearch_bp = Blueprint('autoresearch', __name__)


@autoresearch_bp.route('/autoresearch/capabilities', methods=['GET'])
def autoresearch_capabilities():
    """Report QuantDinger native AutoResearch capabilities."""
    return jsonify(
        {
            'status': 'ok',
            'local_compat': False,
            'native_engine': True,
            'supports_sampled_window_cost_stress': True,
            'capabilities': [
                'indicator_backtest',
                'sampled_window',
                'sampled_window_cost_stress',
            ],
        }
    )
