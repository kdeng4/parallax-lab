"""Small, explicitly licensed public projection. Never return research objects."""

import math
import os

from .model_catalog import MODELS, available_models


def attach_benchmark(detail, benchmark):
    """Match SPY sessions exactly; do not interpolate or splice experiments."""
    by_date = {c.timestamp[:10]: c for c in benchmark.candles}
    days = [c['timestamp'][:10] for c in detail['candles']]
    if not days or any(day not in by_date for day in days):
        return
    anchor = by_date[days[0]].open
    detail['benchmark'] = {
        'name': 'S&P 500 · SPY', 'source': benchmark.source,
        'basis': 'Adjusted SPY buy-and-hold, before costs; agents are net of costs.',
        'curve': [{'timestamp': detail['runs'][0]['equity_curve'][0]['timestamp'], 'value': 100.0}]
                 + [{'timestamp': point['timestamp'], 'value': round(by_date[point['timestamp'][:10]].close / anchor * 100, 4)}
                    for point in detail['runs'][0]['equity_curve'][1:]],
    }


def public_dashboard(store):
    result = {'agents': [{'id': value['id'], 'name': value['name']} for value in available_models()],
              'study': None, 'series': [], 'activities': []}
    # Approval is an operator assertion of a suitable data licence, not a toggle
    # that creates rights. Both the immutable run and the current deployment must approve.
    if os.getenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED') != '1':
        return result
    for summary in store.list_experiments(limit=20):
        if summary.get('data_source') == 'synthetic':
            continue
        detail = store.get(summary['id'], include_events=False)
        if not detail or detail.get('metadata', {}).get('public_performance_approved') is not True:
            continue
        initial = detail.get('initial_cash', 0)
        if not isinstance(initial, (int, float)) or not math.isfinite(initial) or initial <= 0:
            continue
        result['study'] = {'id': detail['id'], 'recorded_at': detail['created_at'], 'mode': 'historical_paper_replay'}
        names = {}
        for index, run in enumerate(detail.get('runs', [])[:6]):
            base_name = MODELS.get(run.get('model_id'), {}).get('name', 'Research agent')
            name = base_name if detail.get('comparison') == 'models' else f'{base_name} {index + 1}'
            names[run['id']] = name
            points = [{'date': point['timestamp'], 'value': round(point['equity'] / initial * 100, 4)}
                      for point in run['equity_curve'][:253] if math.isfinite(point['equity'])]
            result['series'].append({'id': run['id'], 'name': name, 'benchmark': False, 'points': points})
            for trade in run.get('trades', []):
                if trade.get('side') in ('buy', 'sell'):
                    result['activities'].append({'id': trade['id'], 'agent': name, 'action': trade['side'],
                                                 'symbol': detail['symbol'], 'session_date': trade['timestamp'][:10]})
        benchmark = detail.get('benchmark')
        if benchmark:
            result['series'].append({'id': 'benchmark', 'name': 'S&P 500 · SPY', 'benchmark': True,
                                     'points': [{'date': p['timestamp'], 'value': p['value']} for p in benchmark['curve'][:253]]})
        result['activities'] = sorted(result['activities'], key=lambda e: (e['session_date'], e['id']), reverse=True)[:100]
        result['agents'] = [{'id': key, 'name': name} for key, name in names.items()]
        break
    return result
