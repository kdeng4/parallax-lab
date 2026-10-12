"""Forward-only studies: durable leases, daily shared inputs and deferred paper fills.

Every billable attempt is committed before I/O. An interrupted attempt is never
retried. Decisions are collected for the whole cohort before any portfolio trades.
"""

import asyncio
import math
import os
from datetime import UTC, datetime, timedelta, time
from uuid import uuid4
from zoneinfo import ZoneInfo

from .live_book import apply_actions, decimal, equity, new_book, rebalance, weights
from .live_feeds import LiveFeeds, instant, snapshot
from .live_provider import adapter, cloud_decision, local_decision
from .live_schemas import window_at
from .live_storage import LiveStore
from .market_feeds import FeedError
from .model_catalog import MODELS, OPENAI_LIMITS, OPENAI_TIMEOUT, available_openai_models
from .providers import ProviderConfigurationError, ProviderError
from .strategy import load_strategies
from .exchange_sessions import HOLIDAYS, NYSE, market_open, session_bounds

INSOLVENT = decimal('0.01')


def event(now, kind, message, *, account_id=None, **details):
    return {'id': str(uuid4()), 'timestamp': now.isoformat(), 'type': kind,
            'message': message, 'account_id': account_id, 'details': details}


class LiveService:
    def __init__(self, store, market, *, client=None):
        self.db = LiveStore(store)
        self.market = market
        self.feeds = LiveFeeds(market)
        self.client = client

    def now(self):
        return datetime.fromtimestamp(self.market.clock(), UTC)

    def readiness(self):
        return self.feeds.readiness() or (None if self.now().year in HOLIDAYS else 'Update the verified exchange calendar before starting or processing a study.')

    def plan(self):
        result = []
        for study in self.db.plan():
            zone = ZoneInfo(study['timezone'])
            today = self.now().astimezone(zone).date()
            windows = []
            for offset in range(2):
                day = today + timedelta(days=offset)
                if day.weekday() >= 5:
                    continue
                start = datetime.combine(day, time.fromisoformat(study['window_start']), zone).astimezone(NYSE)
                end = datetime.combine(day, time.fromisoformat(study['window_end']), zone).astimezone(NYSE)
                bounds = session_bounds(start.date())
                if bounds and max(start, bounds[0]) < min(end, bounds[1]):
                    windows.append({'start': int(max(start, bounds[0]).timestamp() * 1000),
                                    'end': int(min(end, bounds[1]).timestamp() * 1000)})
            result.append({**study, 'windows': windows})
        return result

    def create(self, request):
        reason = self.readiness()
        if reason:
            raise ProviderConfigurationError(reason)
        cloud = {key for key in request.model_ids if key.startswith('openai:')}
        if not cloud <= set(available_openai_models()):
            raise ProviderConfigurationError('A selected OpenAI model is not configured on this deployment')
        zone = ZoneInfo(request.timezone)
        today = self.now().astimezone(zone).date()
        overlaps = False
        for offset in range(14):
            day = today + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            start = datetime.combine(day, time.fromisoformat(request.window_start), zone).astimezone(NYSE)
            end = datetime.combine(day, time.fromisoformat(request.window_end), zone).astimezone(NYSE)
            bounds = session_bounds(start.date())
            overlaps |= bool(bounds and start < bounds[1] and end > bounds[0])
        if not overlaps:
            raise ValueError('The daily window must overlap US regular market hours')
        if not market_open(self.now()):
            raise ValueError('Start during US regular market hours so the benchmark begins at a current, verified price')
        quotes = self.feeds.quotes(request.symbols)
        now = self.now()
        if not market_open(now):
            raise ValueError('The regular market session closed before the study could start')
        start_date = now.astimezone(NYSE).date().isoformat()
        strategies = load_strategies()
        accounts = []
        for model_id in request.model_ids:
            for strategy_id in request.strategy_ids:
                accounts.append({'id': str(uuid4()), 'name': f"{MODELS[model_id]['name']} / {strategies[strategy_id].name}",
                                 'model_id': model_id, 'strategy_id': strategy_id, 'status': 'active',
                                 'book': new_book(request.initial_cash, start_date=start_date),
                                 'equity': request.initial_cash, 'return_pct': 0.0})
        benchmark = new_book(0, start_date=start_date)
        benchmark['holdings'] = {'SPY': '1'}
        initial = snapshot('initial_reference', now, quotes=quotes)
        study = {'id': str(uuid4()), 'name': request.name, 'status': 'active', 'created_at': now.isoformat(),
                 'started_at': now.isoformat(), 'last_tick_at': None, 'last_error': None,
                 'config': request.model_dump(), 'accounts': accounts,
                 'strategies': {key: strategies[key].model_dump() for key in request.strategy_ids},
                 'benchmark': {'book': benchmark, 'initial_value': quotes['SPY']['price'], 'return_pct': 0.0},
                 'history': [], 'round': None, 'lease': None, 'lease_until': 0,
                 'metadata': {'mode': 'ongoing_paper_study', 'data_source': 'tiingo', 'fee_bps': 1, 'slippage_bps': 2,
                              'objective': 'Maximise ending paper equity, net of trading costs, within strategy limits.',
                              'decision_frequency': 'One shared decision corpus per weekday window; no backdated execution.',
                              'benchmark_basis': 'SPY buy-and-hold including verified splits and dividend receivables, before costs.',
                              'public_performance_approved': os.getenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED') == '1'}}
        self.db.create(study, initial)
        return self.db.get(study['id'])

    def control(self, study_id, action):
        now = self.now()
        with self.db.locked() as db:
            study = self.db.read(db, study_id)
            if not study:
                raise KeyError('Study not found')
            if action == 'resume':
                if study['status'] == 'paused_bankrupt':
                    raise ValueError('Insolvent studies cannot be resumed or recapitalised; start a new study')
                active = db.execute("SELECT count(*) AS total FROM live_studies WHERE status='active'").fetchone()['total']
                if study['status'] != 'active' and active >= 2:
                    raise ValueError('At most two studies may be active')
                study['status'] = 'active'
            else:
                if study['status'] != 'paused_bankrupt':
                    study['status'] = 'paused'
                if study['round'] and study['round']['stage'] not in ('closed', 'failed'):
                    self._close(db, study, 'Owner paused the study; outstanding decisions and orders were cancelled')
            study['lease'], study['lease_until'] = None, 0
            self.db.event(db, study_id, event(now, 'control', f'Study {action} requested by owner'))
            self.db.write(db, study)
        return self.db.get(study_id)

    def _close(self, db, study, message):
        round_ = study['round']
        for value in round_.get('decisions', {}).values():
            if value.get('execution') == 'pending':
                value['execution'] = 'expired'
            if value.get('status') == 'started':
                value['status'] = 'uncertain'
        round_['stage'] = 'closed'
        self.db.event(db, study['id'], event(self.now(), 'window_closed', message,
                                           shared_snapshot_id=round_.get('snapshot_id'), day=round_['day']))

    def _claim(self, study_id):
        now = self.now()
        with self.db.locked() as db:
            study = self.db.read(db, study_id)
            if not study or study['status'] != 'active' or study['lease_until'] > self.market.clock():
                return None
            round_ = study['round']
            if round_ and round_['stage'] not in ('closed', 'failed'):
                if instant(round_['end']) <= now:
                    self._close(db, study, 'Window ended; unfilled orders expired without backdated fills')
                elif any(value['status'] == 'started' for value in round_.get('decisions', {}).values()):
                    self._close(db, study, 'Interrupted model attempt has an unknown outcome; no automatic retry or cohort trades')
            window = window_at(study['config'], now)
            if not window or not market_open(now):
                self.db.write(db, study)
                return None
            if study['round'] and study['round']['day'] == window['day'] and study['round']['stage'] in ('closed', 'failed'):
                self.db.write(db, study)
                return None
            if study['round'] is None or study['round']['day'] != window['day']:
                close = session_bounds(now.astimezone(NYSE).date())[1].astimezone(UTC)
                study['round'] = {'day': window['day'], 'start': window['start'].isoformat(),
                                  'end': min(window['end'], close).isoformat(), 'stage': 'preparing', 'decisions': {}, 'last_mark_at': 0}
            study['lease'], study['lease_until'] = str(uuid4()), self.market.clock() + 180
            self.db.write(db, study)
        return study

    def _save(self, study, *, snapshots=(), events=(), point=None):
        """Reject late workers after a pause, restart or expired lease."""
        now = self.now()
        with self.db.locked() as db:
            current = self.db.read(db, study['id'])
            if (not current or current['status'] != 'active' or current['lease'] != study['lease']
                    or current['lease_until'] <= self.market.clock()):
                return False
            if not window_at(study['config'], now) or not market_open(now):
                self._close(db, current, 'Window ended before work could commit; no late fills')
                current['lease'], current['lease_until'] = None, 0
                self.db.write(db, current)
                return False
            for item in snapshots:
                self.db.snapshot(db, study['id'], item)
            for item in events:
                self.db.event(db, study['id'], item)
            if point:
                self.db.point(db, study['id'], point)
            study['last_tick_at'] = now.isoformat()
            self.db.write(db, study)
        return True

    def tick(self, study_id=None):
        ids = [study_id] if study_id else [item['id'] for item in self.db.plan()]
        budget = [2]  # Shared across active studies and the entire HTTP invocation.
        results = []
        for identifier in ids:
            study = self._claim(identifier)
            if study is None:
                results.append({'id': identifier, 'status': 'idle'})
                continue
            try:
                reason = self.readiness()
                if reason:
                    raise ProviderConfigurationError(reason)
                self._tick(study, budget)
                results.append({'id': identifier, 'status': study['round']['stage']})
            except (FeedError, ProviderConfigurationError, ValueError) as error:
                # Never expose credential-bearing transport errors or provider bodies.
                message = ('Verified data unavailable: ' + error.code if isinstance(error, FeedError)
                           else str(error) if isinstance(error, ProviderConfigurationError)
                           else 'Verified input or accounting validation failed; no unverified trades were made')
                # Discard any uncommitted partial accounting from a failed step.
                with self.db.store.connection() as db:
                    persisted = self.db.read(db, identifier)
                changed = persisted['last_error'] != message
                persisted['last_error'] = message
                self._save(persisted, events=[event(self.now(), 'blocked', message)] if changed else [])
                results.append({'id': identifier, 'status': 'blocked'})
            finally:
                with self.db.locked() as db:
                    current = self.db.read(db, identifier)
                    if current and current['lease'] == study['lease']:
                        current['lease'], current['lease_until'] = None, 0
                        self.db.write(db, current)
        return {'studies': results, 'cloud_calls_attempted': 2 - budget[0]}

    def _tick(self, study, budget):
        round_ = study['round']
        if round_['stage'] == 'preparing':
            source = self.feeds.window_snapshot(study['config']['symbols'], study['started_at'][:10])
            shared = snapshot('shared_window_input', instant(source['captured_at']),
                              **{key: source[key] for key in ('quotes', 'news', 'events', 'news_sources', 'actions')},
                              history=study['history'][-60:])
            now, changes = self.now(), []
            # Do not mutate a held portfolio until all selected data is verified.
            for account in study['accounts']:
                applied = apply_actions(account['book'], shared['actions'], now.astimezone(NYSE).date().isoformat())
                changes.extend(event(now, 'corporate_action', 'Verified corporate action applied', account_id=account['id'], action=item)
                               for item in applied)
                value = equity(account['book'], shared['quotes'])
                if value <= INSOLVENT:
                    account['status'] = 'paused_bankrupt'
                    changes.append(event(now, 'risk', 'Account paused: total equity is exhausted', account_id=account['id']))
            apply_actions(study['benchmark']['book'], shared['actions'], now.astimezone(NYSE).date().isoformat())
            round_.update(stage='collecting', snapshot=shared, snapshot_id=shared['id'], snapshot_hash=shared['hash'],
                          decisions={account['id']: {'status': 'pending'} for account in study['accounts'] if account['status'] == 'active'})
            study['history'] = [*study['history'][-59:], {'day': round_['day'], 'quotes': shared['quotes']}]
            study['last_error'] = None
            if not self._save(study, snapshots=[shared], events=[*changes, event(now, 'shared_input',
                    'All participants receive the same verified prices, news and event corpus', shared_snapshot_id=shared['id'],
                    shared_snapshot_hash=shared['hash'], news_count=len(shared['news']), news_sources=shared['news_sources'])]):
                return
        if round_['stage'] == 'collecting':
            if not self._collect(study, budget):
                return
            round_['stage'] = 'executing'
            if not self._save(study):
                return
        if round_['stage'] == 'executing':
            self._execute(study)

    def _inputs(self, study, account):
        round_ = study['round']
        return {'objective': study['metadata']['objective'], 'symbols': study['config']['symbols'],
                'snapshot': round_['snapshot'], 'account': account['book'],
                'strategy': study['strategies'][account['strategy_id']],
                'remaining_window_minutes': max(0, math.floor((instant(round_['end']) - instant(round_['snapshot']['captured_at'])).total_seconds() / 60) - 1),
                'costs': {'fee_bps': 1, 'slippage_bps': 2}}

    def _collect(self, study, budget):
        round_ = study['round']
        for account in study['accounts']:
            record = round_['decisions'].get(account['id'])
            if record is None or record['status'] != 'pending':
                continue
            if not window_at(study['config'], self.now()):
                return False
            inputs = self._inputs(study, account)
            metadata = {}
            try:
                if account['model_id'].startswith('openai:'):
                    if budget[0] <= 0:
                        continue
                    remote = adapter(account['model_id'], self.client)
                    entry, lease = self.market.cache.claim('openai:decision', 'openai', int(self.market.clock()), OPENAI_LIMITS, persistent=False)
                    if lease is None:
                        study['last_error'] = 'OpenAI quota or cooldown reached; pending decisions wait within this window'
                        self._save(study)
                        continue
                    error, retry_after = None, 0
                    try:
                        record.update(status='started', attempted_at=self.now().isoformat())
                        if not self._save(study):
                            return False
                        budget[0] -= 1
                        decision = asyncio.run(self._remote(remote, inputs))
                        metadata = remote.last_response_metadata
                    except ProviderError as failure:
                        error = 'rate_limited' if failure.status_code == 429 else 'provider_failed'
                        retry_after = failure.retry_after
                        raise
                    finally:
                        self.market.cache.finish('openai:decision', 'openai', lease, int(self.market.clock()), ttl=0,
                                                 error=error, retry_after=retry_after, persistent=False)
                else:
                    decision = local_decision(account['model_id'], inputs)
                target = weights(decision, study['config']['symbols'], inputs['strategy']['config']['max_allocation'])
                if decision.execute_after_minutes > inputs['remaining_window_minutes']:
                    raise ValueError('Decision execution delay extends beyond this window')
            except (ProviderError, ProviderConfigurationError, ValueError):
                record['status'] = 'failed'
                round_['stage'] = 'failed'
                study['last_error'] = 'A participant decision failed; the entire window was skipped without cohort trades or automatic retries'
                self._save(study, events=[event(self.now(), 'decision_failed', study['last_error'], account_id=account['id'],
                                               shared_snapshot_id=round_['snapshot_id'])])
                return False
            completed = self.now()
            record.update(status='complete', execution='pending', decision=decision.model_dump(),
                          weights={key: str(value) for key, value in target.items()}, completed_at=completed.isoformat(),
                          not_before=max(completed, instant(round_['snapshot']['captured_at']) + timedelta(minutes=decision.execute_after_minutes)).isoformat())
            if not self._save(study, events=[event(completed, 'decision', decision.summary, account_id=account['id'],
                    shared_snapshot_id=round_['snapshot_id'], shared_snapshot_hash=round_['snapshot_hash'],
                    requested=decision.model_dump(), applied_weights=record['weights'], account_before=account['book'], **metadata)]):
                return False
        return all(value['status'] == 'complete' for value in round_['decisions'].values())

    @staticmethod
    async def _remote(remote, inputs):
        try:
            async with asyncio.timeout(OPENAI_TIMEOUT):
                return await cloud_decision(remote, inputs)
        except TimeoutError:
            raise ProviderError('OpenAI decision timed out; no automatic retry') from None

    def _execute(self, study):
        round_, now = study['round'], self.now()
        due = [value for value in round_['decisions'].values() if value['execution'] == 'pending' and instant(value['not_before']) <= now]
        if not due and self.market.clock() - round_['last_mark_at'] < 300:
            return
        # Poll at most once per five minutes after a mark, including delayed orders.
        if round_['last_mark_at'] and self.market.clock() - round_['last_mark_at'] < 300:
            return
        quotes = self.feeds.quotes(study['config']['symbols'])
        now = self.now()
        fresh = snapshot('execution_reference', now, quotes=quotes, shared_snapshot_id=round_['snapshot_id'])
        changes = []
        completed = max((instant(value['completed_at']) for value in round_['decisions'].values()), default=now)
        cohort_quote_ready = all(instant(quote['as_of']) > completed for quote in quotes.values())
        for account in study['accounts']:
            record = round_['decisions'].get(account['id'])
            if account['status'] != 'active' or not record or record['execution'] != 'pending':
                continue
            if equity(account['book'], quotes) <= INSOLVENT:
                account['status'] = 'paused_bankrupt'
                changes.append(event(now, 'risk', 'Account paused: total equity is exhausted', account_id=account['id']))
                continue
            cutoff = instant(record['not_before'])
            if not cohort_quote_ready or cutoff > now or any(instant(quote['as_of']) < cutoff or instant(quote['as_of']) <= instant(record['completed_at'])
                                   for quote in quotes.values()):
                continue
            fills = rebalance(account['book'], quotes, {key: decimal(value) for key, value in record['weights'].items()},
                              threshold=study['strategies'][account['strategy_id']]['config']['rebalance_threshold'])
            record['execution'] = 'filled' if fills else 'held'
            changes.extend(event(now, 'fill', f"{fill['side'].capitalize()} {fill['symbol']}", account_id=account['id'],
                                 execution_snapshot_id=fresh['id'], shared_snapshot_id=round_['snapshot_id'], **fill) for fill in fills)
            if not fills:
                changes.append(event(now, 'hold', 'No rebalance required at this verified quote', account_id=account['id'],
                                     execution_snapshot_id=fresh['id']))
        point = {'id': str(uuid4()), 'timestamp': now.isoformat(), 'returns': {}, 'execution_snapshot_id': fresh['id'],
                 'quote_as_of': {key: quote['as_of'] for key, quote in quotes.items()}}
        for account in study['accounts']:
            value = equity(account['book'], quotes)
            account['equity'] = float(value)
            account['return_pct'] = float((value / decimal(study['config']['initial_cash']) - 1) * 100)
            point['returns'][account['id']] = account['return_pct']
            if value <= INSOLVENT and account['status'] != 'paused_bankrupt':
                account['status'] = 'paused_bankrupt'
                changes.append(event(now, 'risk', 'Account paused: total equity is exhausted', account_id=account['id']))
        point['benchmark_pct'] = float((equity(study['benchmark']['book'], quotes) / decimal(study['benchmark']['initial_value']) - 1) * 100)
        study['benchmark']['return_pct'] = point['benchmark_pct']
        if all(account['status'] == 'paused_bankrupt' for account in study['accounts']):
            study['status'] = 'paused_bankrupt'
            round_['stage'] = 'closed'
        round_['last_mark_at'] = self.market.clock()
        study['last_error'] = None
        self._save(study, snapshots=[fresh], events=changes, point=point)
