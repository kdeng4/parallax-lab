"""Private news and event adapters. No feeds run from public page requests."""

import csv
import hashlib
import io
import os
import re
from datetime import date, timedelta
from urllib.parse import urlsplit, urlunsplit

from .market_feeds import FeedError, stamp

COMPANIES = {'AAPL': '0000320193', 'MSFT': '0000789019', 'NVDA': '0001045810'}


def text(value, limit=280):
    return re.sub(r'<[^>]*>', '', str(value or '')).strip()[:limit]


def link(value):
    parsed = urlsplit(str(value or ''))
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Unsafe source link')
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ''))


def news(payload, provider, today):
    rows = payload.get('data') if provider == 'Marketaux' and isinstance(payload, dict) else payload
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('Expected bounded news')
    items = []
    for row in rows:
        url = link(row['url'])
        published = row.get('published_at', row.get('publishedDate', ''))
        day = date.fromisoformat(published[:10])
        if day > today:
            continue
        symbols = row.get('tickers', []) if provider == 'Tiingo' else [e.get('symbol') for e in row.get('entities', [])]
        items.append({'id': hashlib.sha256(url.encode()).hexdigest()[:24], 'kind': 'news',
                      'title': text(row['title'], 220), 'summary': text(row.get('description', row.get('snippet'))),
                      'url': url, 'published_at': text(published, 35), 'date': day.isoformat(), 'provider': provider,
                      'symbols': [str(s).upper()[:20] for s in symbols if isinstance(s, str)][:12]})
    return items[:30]


def earnings(payload, today):
    if not isinstance(payload, str):
        raise ValueError('Expected calendar CSV')
    # Alpha Vantage sometimes returns a JSON quota/entitlement message with HTTP 200.
    if payload.lstrip().startswith('{'):
        raise FeedError('provider_unavailable', 3600)
    reader = csv.DictReader(io.StringIO(payload))
    if not {'symbol', 'reportDate', 'name'} <= set(reader.fieldnames or []):
        raise ValueError('Invalid calendar columns')
    items = []
    for row in reader:
        day = date.fromisoformat(row['reportDate'])
        if today <= day <= today + timedelta(days=90) and row['symbol'] in COMPANIES:
            items.append({'id': f"earnings:{row['symbol']}:{day}", 'kind': 'earnings', 'date': str(day),
                          'title': f"{row['symbol']} expected earnings", 'summary': 'Expected date; may change.',
                          'symbols': [row['symbol']], 'provider': 'Alpha Vantage',
                          'url': 'https://www.alphavantage.co/documentation/#earnings-calendar'})
    return items[:30]


def releases(payload, today):
    rows = payload['release_dates']
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('Invalid release calendar')
    items = []
    for row in rows:
        day, release_id = date.fromisoformat(row['date']), int(row['release_id'])
        if today <= day <= today + timedelta(days=30):
            items.append({'id': f'fred:{release_id}:{day}', 'kind': 'economic_release', 'date': str(day),
                          'title': text(row['release_name'], 220), 'summary': 'Source release date; FRED availability can be later.',
                          'symbols': [], 'provider': 'FRED', 'url': f'https://fred.stlouisfed.org/release?rid={release_id}'})
    return items


def filings(payload, symbol, cik, today):
    recent = payload['filings']['recent']
    items = []
    for i, form in enumerate(recent['form'][:1000]):
        if form not in ('8-K', '10-K', '10-Q', '6-K', '20-F'):
            continue
        day = date.fromisoformat(recent['filingDate'][i])
        if not today - timedelta(days=90) <= day <= today:
            continue
        accession, document = recent['accessionNumber'][i], recent['primaryDocument'][i]
        if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession) or not re.fullmatch(r'[\w.-]+', document):
            raise ValueError('Invalid filing path')
        items.append({'id': f'sec:{accession}', 'kind': 'filing', 'date': str(day),
                      'title': f'{symbol} · {form}', 'summary': 'Official SEC filing. Filing date, not a future event forecast.',
                      'symbols': [symbol], 'provider': 'SEC EDGAR',
                      'url': f'https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace("-", "")}/{document}'})
        if len(items) == 10:
            break
    return items


class ContextFeeds:
    def __init__(self, market):
        self.market = market

    def overview(self):
        from datetime import UTC, datetime
        today = datetime.fromtimestamp(self.market.clock(), UTC).date()
        sources = []

        def add(key, provider, label, fetch, parse, *, credential=True, limits=((3600, 2), (86400, 8)), ttl=21600):
            if not credential:
                entry = {'error': 'key_missing'}
            else:
                entry = self.market.load(key, provider, fetch, parse, limits=limits, ttl=ttl)
            data = entry.get('data')
            stale = data is not None and (entry.get('expires_at', 0) <= self.market.clock() or bool(entry.get('error')))
            sources.append({'id': key, 'name': label, 'status': 'stale' if stale else 'ok' if data is not None else entry.get('error', 'refreshing'),
                            'fetched_at': stamp(entry.get('fetched_at', 0)),
                            'next_refresh_at': stamp(max(entry.get('expires_at', 0), entry.get('retry_at', 0))), 'items': data or []})

        add('tiingo:news', 'tiingo', 'Tiingo News', lambda: self.market.fetch_json(
            'https://api.tiingo.com/tiingo/news', params={'limit': 20}, headers={'Authorization': f'Token {self.market.token}'}),
            lambda payload, day: news(payload, 'Tiingo', day), credential=bool(self.market.token),
            limits=((60, 5), (3600, 10), (86400, 30)))
        marketaux_key = os.getenv('MARKETAUX_API_KEY', '').strip()
        add('marketaux:news', 'marketaux', 'Marketaux', lambda: self.market.fetch_json(
            'https://api.marketaux.com/v1/news/all', params={'api_token': marketaux_key, 'limit': 3, 'language': 'en', 'group_similar': 'true'}),
            lambda payload, day: news(payload, 'Marketaux', day), credential=bool(marketaux_key), limits=((3600, 4), (86400, 24)), ttl=3600)
        alpha_key = os.getenv('ALPHA_VANTAGE_API_KEY', '').strip()
        for symbol in COMPANIES:
            add(f'alphavantage:{symbol}', 'alphavantage', f'Earnings · {symbol}', lambda symbol=symbol: self.market.fetch_json(
                'https://www.alphavantage.co/query', params={'function': 'EARNINGS_CALENDAR', 'symbol': symbol,
                    'horizon': '3month', 'apikey': alpha_key}, csv_response=True),
                earnings, credential=bool(alpha_key), limits=((3600, 3), (86400, 6)), ttl=86400)
        fred_key = os.getenv('FRED_API_KEY', '').strip()
        add('fred:releases', 'fred', 'Economic calendar', lambda: self.market.fetch_json(
            'https://api.stlouisfed.org/fred/releases/dates', params={'api_key': fred_key, 'file_type': 'json', 'limit': 100,
                'realtime_start': str(today), 'realtime_end': str(today + timedelta(days=30)), 'include_release_dates_with_no_data': 'true',
                'order_by': 'release_date', 'sort_order': 'asc'}), releases, credential=bool(fred_key))
        user_agent = os.getenv('PARALLAX_SEC_USER_AGENT', '').strip()
        for symbol, cik in COMPANIES.items():
            add(f'sec:{symbol}', 'sec', f'SEC · {symbol}', lambda cik=cik: self.market.fetch_json(
                f'https://data.sec.gov/submissions/CIK{cik}.json', params={}, headers={'User-Agent': user_agent}),
                lambda payload, day, symbol=symbol, cik=cik: filings(payload, symbol, cik, day),
                credential=bool(user_agent), limits=((60, 3), (3600, 6), (86400, 12)), ttl=86400)
        return {'as_of': stamp(int(self.market.clock())), 'sources': sources,
                'usage': 'Private research context. Current baseline replays do not consume these feeds.'}
