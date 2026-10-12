"""Isolated transport and clock simulations; never seed the deployed workspace."""

import asyncio
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from parallax_lab.live_book import apply_actions, decimal, equity, new_book, rebalance, weights
from parallax_lab.live_feeds import LiveFeeds, instant, snapshot
from parallax_lab.live_provider import cloud_decision, local_decision
from parallax_lab.live_schemas import PortfolioDecision, StudyInput, window_at
from parallax_lab.live_service import LiveService, event, market_open
from parallax_lab.main import create_app
from parallax_lab.market_feeds import FeedError, MarketService
from parallax_lab.providers import ProviderConfigurationError, ProviderError
from parallax_lab.public_dashboard import public_dashboard
from parallax_lab.storage import Store


class Clock:
    value = datetime(2026, 10, 12, 14, tzinfo=UTC).timestamp()
    def __call__(self):
        return self.value
    def advance(self, seconds):
        self.value += seconds


def request(**kwargs):
    return StudyInput(name='Forward contract', model_ids=['buy-and-hold'], strategy_ids=['balanced'],
                      symbols=['AAPL', 'MSFT'], **kwargs)


def decision(**kwargs):
    return PortfolioDecision(targets=[{'symbol': 'AAPL', 'weight': .5}, {'symbol': 'MSFT', 'weight': .3}],
                             execute_after_minutes=0, summary='Observed opportunity', confidence=.8, **kwargs)


@pytest.fixture
def live(tmp_path, monkeypatch):
    store = Store(f"sqlite:///{tmp_path / 'live.db'}")
    store.initialize()
    clock = Clock()
    market = MarketService(store, network=True, token='test-only-token', clock=clock, persistent_tiingo=True)
    service = LiveService(store, market)
    service.test_clock = clock
    def quotes(symbols, **kwargs):
        return {symbol: {'price': 100 if symbol != 'SPY' else 500, 'as_of': service.now().isoformat(),
                         'source': 'Test transport'} for symbol in set(symbols) | {'SPY'}}
    monkeypatch.setattr(service.feeds, 'quotes', quotes)
    monkeypatch.setattr(service.feeds, 'window_snapshot', lambda symbols, since: snapshot(
        'shared_window_input', service.now(), quotes=quotes(symbols), actions=[], events=[],
        news=[{'id': 'one', 'title': 'Test observation', 'published_at': service.now().isoformat(),
               'summary': 'Unit-test transport only', 'url': 'https://example.com/article', 'provider': 'Test'}],
        news_sources=[{'name': 'Tiingo News', 'status': 'ok', 'fetched_at': service.now().isoformat()}]))
    return service


@pytest.mark.parametrize('changes', [
    {'name': ' '}, {'model_ids': ['unknown']}, {'symbols': ['AAPL', 'aapl']},
    {'model_ids': ['momentum', 'momentum']}, {'strategy_ids': ['balanced', 'balanced']},
    {'timezone': 'Not/AZone'}, {'timezone': '/tmp/private'}, {'window_start': '25:00'},
    {'window_start': '9:45'}, {'window_end': '09:00'}, {'window_end': '13:00'},
    {'initial_cash': float('nan')}, {'initial_cash': True}, {'start_date': '2020-01-01'},
])
def test_study_rejects_ambiguous_or_backdated_inputs(changes):
    payload = request().model_dump()
    with pytest.raises(ValidationError):
        StudyInput.model_validate({**payload, **changes})


def test_window_timezone_weekends_and_dst():
    config = request().model_dump()
    assert window_at(config, datetime(2026, 10, 12, 14, tzinfo=UTC))['start'].hour == 13
    assert window_at(config, datetime(2026, 11, 2, 15, tzinfo=UTC))['start'].hour == 14
    assert window_at(config, datetime(2026, 10, 10, 14, tzinfo=UTC)) is None
    assert window_at(config, datetime(2026, 10, 12, 12, tzinfo=UTC)) is None
    assert not market_open(datetime(2026, 10, 12, 21, tzinfo=UTC))
    with pytest.raises(ValueError):
        instant('2026-10-12T14:00:00')


def test_exchange_holidays_early_closes_and_unknown_years(live):
    from parallax_lab.exchange_sessions import session_bounds
    from datetime import date
    assert session_bounds(date(2026, 11, 26)) is None
    assert not market_open(datetime(2026, 11, 27, 18, tzinfo=UTC))
    assert market_open(datetime(2026, 11, 27, 17, 59, tzinfo=UTC))
    assert session_bounds(date(2028, 7, 3))[1].hour == 13
    assert session_bounds(date(2029, 1, 2)) is None
    study = live.create(request(window_start='12:00', window_end='14:00'))
    live.test_clock.value = datetime(2026, 11, 27, 17, tzinfo=UTC).timestamp()
    plan = live.plan()[0]
    assert datetime.fromtimestamp(plan['windows'][0]['end'] / 1000, UTC).hour == 18
    assert live._claim(study['id'])['round']['end'] == '2026-11-27T18:00:00+00:00'
    live.test_clock.value = datetime(2029, 1, 2, 15, tzinfo=UTC).timestamp()
    assert 'calendar' in live.readiness()
    assert live.plan()[0]['windows'] == []


@pytest.mark.parametrize('value', [
    {'targets': [{'symbol': 'AAPL', 'weight': .8}, {'symbol': 'MSFT', 'weight': .8}]},
    {'targets': [{'symbol': 'AAPL', 'weight': .5}, {'symbol': 'AAPL', 'weight': .2}]},
    {'execute_after_minutes': True}, {'confidence': float('inf')},
])
def test_portfolio_contract_rejects_leverage_duplicates_and_nonfinite_values(value):
    with pytest.raises(ValidationError):
        PortfolioDecision.model_validate({**decision().model_dump(), **value})


def test_decimal_multiticker_accounting_sell_first_costs_and_cash_limit():
    quotes = {key: {'price': 100, 'as_of': '2026-10-12T14:01:00Z'} for key in ['AAPL', 'MSFT']}
    book = new_book(1000, start_date='2026-10-12')
    target = weights(decision(), ['AAPL', 'MSFT'], .5)
    assert sum(target.values()) == decimal('.5')
    fills = rebalance(book, quotes, target, threshold=.01)
    assert len(fills) == 2 and all(fill['fee'] > 0 for fill in fills)
    assert 999 < equity(book, quotes) < 1000
    assert decimal(book['cash']) >= 0
    full = rebalance(book, quotes, {'AAPL': decimal(0), 'MSFT': decimal(1)}, threshold=.001)
    assert full[0]['side'] == 'sell' and full[-1]['side'] == 'buy'
    assert decimal(book['cash']) >= 0
    assert 'AAPL' not in book['holdings']
    assert rebalance(book, quotes, {'AAPL': decimal(0), 'MSFT': decimal(1)}, threshold=.1) == []
    with pytest.raises(ValueError, match='outside'):
        weights(decision(), ['AAPL'], .5)
    empty = new_book(0, start_date='2026-10-12')
    assert rebalance(empty, quotes, target, threshold=.01) == []


def test_corporate_actions_no_double_credit_or_same_day_entitlement():
    book = new_book(0, start_date='2026-10-12')
    book['holdings'] = {'AAPL': '10'}
    split = {'id': 's', 'date': '2026-10-13', 'symbol': 'AAPL', 'kind': 'split', 'factor': 2}
    dividend = {'id': 'd', 'date': '2026-10-13', 'symbol': 'AAPL', 'kind': 'dividend', 'amount': 1, 'payment_date': None}
    assert len(apply_actions(book, [split, dividend], '2026-10-13')) == 2
    assert book['holdings']['AAPL'] == '20'
    assert decimal(book['cash']) == 0
    assert equity(book, {'AAPL': {'price': 50}}) == 1020
    assert apply_actions(book, [split, dividend], '2026-10-14') == []
    dividend['payment_date'] = '2026-10-16'
    apply_actions(book, [split, dividend], '2026-10-16')
    assert decimal(book['cash']) == 20 and not book['receivables']
    apply_actions(book, [split, dividend], '2026-10-17')
    assert decimal(book['cash']) == 20
    with pytest.raises(ValueError, match='revised'):
        apply_actions(book, [{**split, 'factor': 3}], '2026-10-17')
    same_day = {**split, 'id': 'same', 'date': '2026-10-12'}
    assert apply_actions(book, [same_day], '2026-10-13') == []
    no_holding = {**split, 'id': 'other', 'symbol': 'MSFT'}
    assert apply_actions(book, [no_holding], '2026-10-13') == []


def test_forward_create_real_start_independent_pairs_fixed_config(live):
    payload = request().model_dump()
    payload.update(model_ids=['buy-and-hold', 'momentum'], strategy_ids=['balanced', 'conservative'])
    study = live.create(StudyInput(**payload))
    assert study['started_at'] == live.now().isoformat()
    assert len(study['accounts']) == 4
    assert len(set(account['id'] for account in study['accounts'])) == 4
    assert all(account['book']['holdings'] == {} for account in study['accounts'])
    assert set(study['points'][0]['returns'].values()) == {0}
    assert study['points'][0]['benchmark_pct'] == 0
    assert live.db.list()[0]['id'] == study['id']
    assert len(live.db.plan()) == 1
    with pytest.raises(ProviderConfigurationError):
        payload['model_ids'] = ['openai:gpt-6-luna']
        live.create(StudyInput(**payload))


def test_create_requires_rights_credentials_open_market_and_overlapping_window(live):
    live.market.persistent_tiingo = False
    with pytest.raises(ProviderConfigurationError, match='licence'):
        live.create(request())
    live.market.persistent_tiingo = True
    live.market.network = False
    with pytest.raises(ProviderConfigurationError, match='feeds'):
        live.create(request())
    live.market.network = True
    with pytest.raises(ValueError, match='overlap'):
        live.create(request(timezone='UTC', window_start='00:00', window_end='01:00'))
    live.test_clock.advance(10 * 3600)
    with pytest.raises(ValueError, match='market hours'):
        live.create(request())
    assert live.db.list() == []


def test_one_decision_per_window_fresh_next_quote_no_duplicate_fills_and_restart(live):
    study = live.create(request())
    assert live.tick()['studies'][0]['status'] == 'executing'
    before = live.db.get(study['id'])
    assert not any(item['type'] == 'fill' for item in before['events'])
    assert before['round']['decisions'][before['accounts'][0]['id']]['status'] == 'complete'
    live.test_clock.advance(301)
    live.tick()
    after = live.db.get(study['id'])
    assert len([item for item in after['events'] if item['type'] == 'fill']) == 2
    assert -1 < after['accounts'][0]['return_pct'] < 0
    assert after['points'][-1]['benchmark_pct'] == 0
    assert all(item['quantity'] > 0 for item in [e['details'] for e in after['events'] if e['type'] == 'fill'])
    live.tick()
    live.test_clock.advance(301)
    live.tick()
    assert len([item for item in live.db.get(study['id'])['events'] if item['type'] == 'fill']) == 2
    restarted = LiveService(live.db.store, live.market)
    assert restarted.db.get(study['id']) == live.db.get(study['id'])
    common = live.db.snapshot_detail(study['id'], after['round']['snapshot_id'])
    assert len(common['news']) == 1 and common['hash'] == after['round']['snapshot_hash']
    assert live.db.snapshot_detail(str(uuid4()), common['id']) is None


def test_pausing_revokes_worker_cancels_orders_and_daily_resume_does_not_retry(live):
    study = live.create(request())
    working = live._claim(study['id'])
    live._tick(working, [2])
    live.control(study['id'], 'pause')
    assert live._save(working, events=[event(live.now(), 'unsafe', 'Late')]) is False
    paused = live.db.get(study['id'])
    assert paused['status'] == 'paused' and paused['round']['stage'] == 'closed'
    live.control(study['id'], 'resume')
    assert live.tick(study['id'])['studies'][0]['status'] == 'idle'
    assert not any(item['type'] == 'unsafe' for item in live.db.get(study['id'])['events'])
    with pytest.raises(KeyError):
        live.control(str(uuid4()), 'pause')


def test_max_active_studies_and_resume_constraint(live):
    one = live.create(request())
    two = live.create(request())
    with pytest.raises(ValueError, match='two'):
        live.create(request())
    live.control(one['id'], 'pause')
    live.create(request())
    with pytest.raises(ValueError, match='two'):
        live.control(one['id'], 'resume')
    assert live.db.get(two['id'])['status'] == 'active'


def test_concurrent_ticks_have_one_lease_and_interrupted_attempt_is_not_retried(live):
    study = live.create(request())
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda _: live._claim(study['id']), range(6)))
    winners = [item for item in claims if item]
    assert len(winners) == 1
    working = winners[0]
    account_id = working['accounts'][0]['id']
    working['round']['stage'] = 'collecting'
    working['round']['decisions'] = {account_id: {'status': 'started'}}
    assert live._save(working)
    live.test_clock.advance(181)
    assert live.tick(study['id'])['studies'][0]['status'] == 'idle'
    final = live.db.get(study['id'])
    assert final['round']['stage'] == 'closed'
    assert final['round']['decisions'][account_id]['status'] == 'uncertain'
    assert any('no automatic retry' in item['message'] for item in final['events'])


def test_daily_expiration_and_next_window_have_new_snapshot(live):
    study = live.create(request())
    live.tick()
    first = live.db.get(study['id'])['round']['snapshot_id']
    live.test_clock.advance(3600)
    assert live.tick(study['id'])['studies'][0]['status'] == 'idle'
    assert live.db.get(study['id'])['round']['stage'] == 'closed'
    live.test_clock.advance(23 * 3600)
    live.tick()
    next_day = live.db.get(study['id'])
    assert next_day['round']['snapshot_id'] != first
    assert len(next_day['history']) == 2


def test_missing_feed_blocks_without_synthetic_fallback_and_uncommitted_actions_rollback(live, monkeypatch):
    study = live.create(request())
    def unavailable(*args):
        raise FeedError('news_unavailable')
    monkeypatch.setattr(live.feeds, 'window_snapshot', unavailable)
    assert live.tick()['studies'][0]['status'] == 'blocked'
    assert live.tick()['studies'][0]['status'] == 'blocked'
    final = live.db.get(study['id'])
    assert len(final['events']) == 1 and final['accounts'][0]['book']['holdings'] == {}
    assert len(final['points']) == 1
    live.market.persistent_tiingo = False
    live.tick()
    assert 'licence' in live.db.get(study['id'])['last_error']


def test_total_equity_bankruptcy_not_cash_only(live):
    study = live.create(request())
    with live.db.locked() as db:
        state = live.db.read(db, study['id'])
        state['accounts'][0]['book']['cash'] = '0'
        state['accounts'][0]['book']['holdings'] = {'AAPL': '10'}
        live.db.write(db, state)
    live.tick()
    assert live.db.get(study['id'])['accounts'][0]['status'] == 'active'
    with live.db.locked() as db:
        state = live.db.read(db, study['id'])
        state['accounts'][0]['book']['cash'] = '0'
        state['accounts'][0]['book']['holdings'] = {}
        state['round'] = None
        live.db.write(db, state)
    live.tick()
    final = live.db.get(study['id'])
    assert final['status'] == 'paused_bankrupt'
    assert final['accounts'][0]['return_pct'] == -100
    assert any(item['type'] == 'risk' for item in final['events'])
    with pytest.raises(ValueError, match='Insolvent'):
        live.control(study['id'], 'resume')
    live.control(study['id'], 'pause')
    assert live.db.get(study['id'])['status'] == 'paused_bankrupt'


def enable_cloud(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'unit-test-key')
    monkeypatch.setenv('PARALLAX_OPENAI_MODELS', 'gpt-6-luna,gpt-6.1-sol,gpt-6-astra')


def cloud_request(strategies=None):
    return StudyInput(name='Cloud cohort', symbols=['AAPL', 'MSFT'], initial_cash=1000,
                      model_ids=['openai:gpt-6-luna', 'openai:gpt-6.1-sol', 'openai:gpt-6-astra'],
                      strategy_ids=strategies or ['balanced'])


def test_bounded_cloud_calls_same_news_no_trade_before_whole_cohort_and_delayed_execution(live, monkeypatch):
    enable_cloud(monkeypatch)
    inputs = []
    async def decide(remote, value):
        inputs.append(value)
        live.test_clock.advance(1)
        payload = decision().model_dump()
        payload['execute_after_minutes'] = 15 if len(inputs) == 3 else 0
        return PortfolioDecision(**payload)
    monkeypatch.setattr('parallax_lab.live_service.cloud_decision', decide)
    study = live.create(cloud_request())
    assert live.tick()['cloud_calls_attempted'] == 2
    first = live.db.get(study['id'])
    assert first['round']['stage'] == 'collecting'
    assert not any(item['type'] == 'fill' for item in first['events'])
    live.test_clock.advance(61)
    assert live.tick()['cloud_calls_attempted'] == 1
    live.test_clock.advance(301)
    live.tick()
    middle = live.db.get(study['id'])
    assert len([item for item in middle['events'] if item['type'] == 'fill']) == 4
    live.test_clock.advance(600)
    live.tick()
    final = live.db.get(study['id'])
    assert len([item for item in final['events'] if item['type'] == 'fill']) == 6
    assert len(inputs) == 3
    assert len({value['snapshot']['hash'] for value in inputs}) == 1
    assert all(value['snapshot']['news'] == inputs[0]['snapshot']['news'] for value in inputs)
    records = [item for item in final['events'] if item['type'] == 'decision']
    assert len({item['details']['shared_snapshot_hash'] for item in records}) == 1


def test_global_call_budget_quota_wait_and_single_failure_skips_cohort(live, monkeypatch):
    enable_cloud(monkeypatch)
    live.create(cloud_request())
    live.create(cloud_request())
    seen = []
    async def decide(remote, value):
        seen.append(value)
        return decision()
    monkeypatch.setattr('parallax_lab.live_service.cloud_decision', decide)
    assert live.tick()['cloud_calls_attempted'] == 2 and len(seen) == 2
    with live.market.cache.locked() as db:
        live.market.cache.write(db, 'provider:openai', {'attempts': [int(live.market.clock())] * 24})
    assert live.tick()['cloud_calls_attempted'] == 0
    assert any('quota' in item['last_error'] for item in live.db.list())
    with live.market.cache.locked() as db:
        live.market.cache.write(db, 'provider:openai', {})
    async def fail(*args):
        raise ProviderError('Sanitized failure', status_code=429, retry_after=60)
    monkeypatch.setattr('parallax_lab.live_service.cloud_decision', fail)
    live.tick()
    failed = live.db.get(live.db.list()[0]['id'])
    other = live.db.get(live.db.list()[1]['id'])
    assert any(item['round']['stage'] == 'failed' for item in [failed, other])
    assert not any(event['type'] == 'fill' for item in [failed, other] for event in item['events'])


@pytest.mark.parametrize('failure', ['outside', 'late', 'configuration'])
def test_invalid_model_choice_or_delay_skips_without_trades(live, monkeypatch, failure):
    enable_cloud(monkeypatch)
    async def decide(*args):
        payload = decision().model_dump()
        if failure == 'outside':
            payload['targets'] = [{'symbol': 'TSLA', 'weight': .5}]
        else:
            payload['execute_after_minutes'] = 180
        return PortfolioDecision(**payload)
    monkeypatch.setattr('parallax_lab.live_service.cloud_decision', decide)
    study = live.create(cloud_request())
    if failure == 'configuration':
        monkeypatch.delenv('OPENAI_API_KEY')
    live.tick()
    final = live.db.get(study['id'])
    assert final['round']['stage'] == 'failed'
    assert not any(item['type'] == 'fill' for item in final['events'])


def test_timeout_is_sanitized_and_never_retried(monkeypatch):
    monkeypatch.setattr('parallax_lab.live_service.OPENAI_TIMEOUT', .001)
    async def slow(*args):
        await asyncio.sleep(.1)
    monkeypatch.setattr('parallax_lab.live_service.cloud_decision', slow)
    with pytest.raises(ProviderError, match='timed out'):
        asyncio.run(LiveService._remote(None, {}))


def test_append_only_snapshots_points_events(live):
    study = live.create(request())
    live.tick()
    for table in ['live_snapshots', 'live_points', 'live_events']:
        for verb in ['UPDATE', 'DELETE']:
            sql = f"UPDATE {table} SET payload='{{}}' WHERE study_id=?" if verb == 'UPDATE' else f'DELETE FROM {table} WHERE study_id=?'
            with pytest.raises(sqlite3.IntegrityError):
                with live.db.store.connection() as db:
                    db.execute(sql, (study['id'],))


def test_public_projection_only_percent_names_and_fills_never_settings(live, monkeypatch):
    monkeypatch.setenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED', '1')
    study = live.create(request())
    live.tick()
    live.test_clock.advance(301)
    live.tick()
    public = public_dashboard(live.db.store)
    assert public['study']['mode'] == 'ongoing_paper_study'
    assert len(public['series']) == 2 and len(public['activities']) == 2
    assert public['series'][0]['points'][0]['value'] == 0
    assert public['series'][-1]['points'][0]['value'] == 0
    encoded = json.dumps(public)
    for private in ['initial_cash', 'strategy_id', 'strategy_version', 'targets', 'cash', 'news', 'quantity', 'reference_price', 'snapshot_hash']:
        assert private not in encoded
    monkeypatch.setenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED', '0')
    assert public_dashboard(live.db.store)['series'] == []
    monkeypatch.setenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED', '1')
    with live.db.locked() as db:
        value = live.db.read(db, study['id'])
        value['metadata']['public_performance_approved'] = False
        live.db.write(db, value)
    assert public_dashboard(live.db.store)['series'] == []


def test_price_only_controls_have_observed_history_warmup(live):
    study = live.create(request())
    live.tick()
    value = live.db.get(study['id'])
    inputs = live._inputs(value, value['accounts'][0])
    assert not local_decision('momentum', inputs).targets
    assert not local_decision('mean-reversion', inputs).targets
    lookback = inputs['strategy']['config']['lookback']
    inputs['snapshot']['history'] = [{'quotes': {symbol: {'price': 50} for symbol in inputs['symbols']}} for _ in range(lookback)]
    assert local_decision('momentum', inputs).targets
    assert not local_decision('mean-reversion', inputs).targets
    inputs['snapshot']['history'] = [{'quotes': {symbol: {'price': 200} for symbol in inputs['symbols']}} for _ in range(lookback)]
    assert local_decision('mean-reversion', inputs).targets


def test_structured_cloud_adapter_rejects_invalid_output():
    class Remote:
        async def respond(self, input_json, schema, name, system):
            assert 'news' in input_json and name == 'paper_portfolio_decision'
            assert 'untrusted' in system and schema['additionalProperties'] is False
            return {'unexpected': 'sensitive value'}
    with pytest.raises(ProviderError, match='invalid portfolio'):
        asyncio.run(cloud_decision(Remote(), {'news': []}))


def test_api_study_contract_read_control_and_machine_plan(tmp_path, monkeypatch, live):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'api.db'}")) as client:
        assert client.get('/api/v1/studies').json() == {'studies': []}
        monkeypatch.setattr('parallax_lab.main.LiveService', lambda *args, **kwargs: live)
        started = client.post('/api/v1/studies', json=request().model_dump())
        assert started.status_code == 201
        study_id = started.json()['id']
        endpoint = f'/api/v1/studies/{study_id}'
        assert client.get(endpoint).status_code == 200
        checked = client.post(endpoint + '/check', json={})
        assert checked.status_code == 200
        snapshot_id = checked.json()['round']['snapshot_id']
        assert client.get(endpoint + '/snapshots/' + snapshot_id).status_code == 200
        assert client.get(endpoint + '/snapshots/' + str(uuid4())).status_code == 404
        assert client.get('/api/v1/studies/' + str(uuid4())).status_code == 404
        assert client.post('/api/v1/studies/' + str(uuid4()) + '/check').status_code == 404
        assert client.get('/api/v1/scheduler/plan').json()['studies'][0]['id'] == study_id
        assert client.post('/api/v1/scheduler/tick', json={}).status_code == 200
        assert client.post(endpoint + '/pause').json()['status'] == 'paused'
        assert client.post(endpoint + '/resume').json()['status'] == 'active'
        assert client.post(endpoint + '/whatever').status_code == 422
        live.market.persistent_tiingo = False
        assert client.post('/api/v1/studies', json=request().model_dump()).status_code == 503
        assert 'licence' in client.get('/api/v1/catalog').json()['live']['requirement']
