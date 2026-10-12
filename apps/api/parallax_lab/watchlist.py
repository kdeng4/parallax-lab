"""Owner preferences only: ticker strings, without any provider market data."""

from .market_cache import MarketCache
from .schemas import MAX_WATCHLIST, SYMBOLS, WatchlistInput


class Watchlist:
    def __init__(self, store):
        self.cache = MarketCache(store)

    def get(self):
        with self.cache.store.connection() as connection:
            saved = self.cache.read(connection, "settings:watchlist")
        return {"symbols": saved.get("symbols", list(SYMBOLS)), "max_symbols": MAX_WATCHLIST}

    def replace(self, request: WatchlistInput):
        with self.cache.locked() as connection:
            self.cache.write(connection, "settings:watchlist", {"symbols": request.symbols})
        return {"symbols": request.symbols, "max_symbols": MAX_WATCHLIST}
