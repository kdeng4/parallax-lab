"""Real reference quotes and a common, timestamped news/corporate-action corpus."""

import hashlib
import json
from datetime import UTC, date, datetime
from uuid import uuid4

from .context_feeds import ContextFeeds
from .market_feeds import FeedError, finite
from .schemas import normalize_ticker

TIINGO_LIVE_LIMITS = ((60, 5), (3600, 35), (86_400, 120))


def instant(value):
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Provider timestamps require an explicit timezone")
    return result.astimezone(UTC)


def snapshot(kind, now, **data):
    content = {"kind": kind, "captured_at": now.isoformat(), **data}
    content['hash'] = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    return {"id": str(uuid4()), **content}


class LiveFeeds:
    def __init__(self, market):
        self.market = market

    def readiness(self):
        if not self.market.persistent_tiingo:
            return "A licence permitting stored live research, news processing and derived performance is required."
        if not self.market.network or not self.market.token:
            return "Connect the real quote and news feeds before starting an ongoing study."
        return None

    def quotes(self, symbols, *, allow_closed=False):
        wanted = sorted(set(symbols) | {'SPY'})
        key = "tiingo:live:" + ",".join(wanted)
        def parse(payload, _day):
            now = datetime.fromtimestamp(self.market.clock(), UTC)
            if not isinstance(payload, list) or len(payload) > 20:
                raise ValueError("Expected bounded reference quotes")
            quotes = {}
            for row in payload:
                symbol = normalize_ticker(row['ticker'])
                if symbol not in wanted or symbol in quotes:
                    raise ValueError("Unexpected or duplicated quote symbol")
                as_of = instant(row['timestamp'])
                price = finite(row['tngoLast'], positive=True)
                if as_of > now or (now - as_of).total_seconds() > (345_600 if allow_closed else 900):
                    raise ValueError("Future or stale reference quote")
                quotes[symbol] = {'price': price, 'as_of': as_of.isoformat(), 'source': 'Tiingo IEX reference price'}
            if set(quotes) != set(wanted):
                raise ValueError("All selected tickers and SPY need reference quotes")
            return quotes
        entry = self.market.load(key, 'tiingo', lambda: self.market.fetch_json(
            'https://api.tiingo.com/iex/' + ','.join(wanted), params={},
            headers={'Authorization': f'Token {self.market.token}'}), parse,
            limits=TIINGO_LIVE_LIMITS, ttl=30)
        data = entry.get('data')
        now = datetime.fromtimestamp(self.market.clock(), UTC)
        if entry.get('error') or not data:
            raise FeedError(entry.get('error', 'quotes_unavailable'))
        if any((now - instant(item['as_of'])).total_seconds() > (345_600 if allow_closed else 900) for item in data.values()):
            raise FeedError('stale_quotes')
        return data

    def common_context(self, symbols):
        corpus = ContextFeeds(self.market).overview(symbols=symbols, tiingo_limits=TIINGO_LIVE_LIMITS)
        cutoff = datetime.fromtimestamp(self.market.clock(), UTC)
        good_news = [source for source in corpus['sources'] if source['name'] in ('Tiingo News','Marketaux') and source['status'] == 'ok']
        if not good_news:
            raise FeedError('news_unavailable')
        articles, events = {}, []
        for source in corpus['sources']:
            if source['status'] != 'ok':
                continue
            for item in source['items']:
                if item['kind'] == 'news':
                    if instant(item['published_at']) <= cutoff:
                        articles[item['id']] = item
                else:
                    events.append(item)
        return {"news": sorted(articles.values(), key=lambda item: (item['published_at'],item['id']), reverse=True)[:60],
                "events": events[:60], "news_sources": [{key: source[key] for key in ('name','status','fetched_at')} for source in corpus['sources']]}

    def actions(self, symbols, since: str):
        now = datetime.fromtimestamp(self.market.clock(), UTC)
        today = now.date()
        if date.fromisoformat(since) >= today:
            return []
        actions = []
        for symbol in sorted(set(symbols) | {'SPY'}):
            for kind in ('splits', 'distributions'):
                def parse(payload, _day, symbol=symbol, kind=kind):
                    if not isinstance(payload, list) or len(payload) > 500:
                        raise ValueError("Invalid corporate-action response")
                    result = []
                    for row in payload:
                        ex_date = date.fromisoformat(row['exDate'][:10])
                        if row.get('ticker') and normalize_ticker(row['ticker']) != symbol:
                            raise ValueError("Corporate action belongs to a different ticker")
                        if not date.fromisoformat(since) < ex_date <= today:
                            continue
                        if kind == 'splits':
                            if row.get('splitStatus') == 'c':
                                continue
                            if row.get('splitStatus') != 'a':
                                raise ValueError("Unknown split status")
                            result.append({'id': f'{symbol}:split:{ex_date}', 'symbol': symbol, 'kind': 'split',
                                           'date': str(ex_date), 'factor': finite(row['splitFactor'], positive=True)})
                        else:
                            if row.get('distributionFrequency') == 'c':
                                continue
                            amount = finite(row['distribution'])
                            if amount < 0:
                                raise ValueError("Invalid distribution amount")
                            payment = row.get('paymentDate')
                            result.append({'id': f'{symbol}:dividend:{ex_date}', 'symbol': symbol, 'kind': 'dividend',
                                           'date': str(ex_date), 'amount': amount,
                                           'payment_date': str(date.fromisoformat(payment[:10])) if payment else None})
                    return result
                entry = self.market.load(f'tiingo:actions:{symbol}:{kind}:{since}:{today}', 'tiingo',
                    lambda symbol=symbol, kind=kind: self.market.fetch_json(
                        f'https://api.tiingo.com/tiingo/corporate-actions/{symbol}/{kind}',
                        params={'startExDate': since,'endExDate': str(today)},
                        headers={'Authorization': f'Token {self.market.token}'}), parse,
                    limits=TIINGO_LIVE_LIMITS, ttl=86_400)
                if entry.get('error') or 'data' not in entry:
                    raise FeedError('corporate_actions_unavailable')
                actions.extend(entry['data'])
        return sorted(actions, key=lambda item: (item['date'], item['kind'], item['id']))

    def window_snapshot(self, symbols, since):
        # Complete cached corporate-action lookups first. A quota-limited prepare
        # can resume next minute without repeatedly spending calls on quotes.
        actions = self.actions(symbols, since)
        context = self.common_context(symbols)
        quotes = self.quotes(symbols)
        now = datetime.fromtimestamp(self.market.clock(), UTC)
        return snapshot('shared_window_input', now, quotes=quotes, actions=actions, **context)
