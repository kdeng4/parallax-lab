"""Cross-worker cache leases and rolling quotas, committed BEFORE outbound I/O."""

import json
from contextlib import contextmanager
from uuid import uuid4
from datetime import UTC, datetime


class MarketCache:
    def __init__(self, store):
        self.store = store
        self.placeholder = "%s" if store.dialect == "postgresql" else "?"

    @contextmanager
    def locked(self):
        with self.store.connection() as connection:
            if self.store.dialect == "postgresql":
                connection.execute("SELECT pg_advisory_xact_lock(719230015)")
            else:
                connection.execute("BEGIN IMMEDIATE")
            yield connection

    def read(self, connection, key):
        row = connection.execute(f"SELECT value FROM market_state WHERE key={self.placeholder}", (key,)).fetchone()
        return json.loads(row["value"]) if row else {}

    def write(self, connection, key, value):
        connection.execute(
            f"INSERT INTO market_state (key, value) VALUES ({self.placeholder}, {self.placeholder}) "
            "ON CONFLICT (key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, allow_nan=False, separators=(",", ":"))),
        )

    def discard_tiingo_content(self):
        """Invalidate obsolete content caches, retaining request-budget metadata."""
        with self.locked() as connection:
            rows = connection.execute("SELECT key FROM market_state WHERE key LIKE 'cache:tiingo:%'").fetchall()
            for row in rows:
                self.write(connection, row['key'], {})

    def reserve_tiingo_transfer(self, now, symbols, maximum_bytes):
        """Account-wide monthly symbols/bandwidth, including concurrent fetches."""
        month = datetime.fromtimestamp(now, UTC).strftime('%Y-%m')
        key = f'usage:tiingo:{month}'
        with self.locked() as connection:
            state = self.read(connection, key)
            selected = sorted(set(state.get('symbols', [])) | set(symbols))
            if len(selected) > 500:
                return None, 'monthly_symbol_limit'
            if state.get('bytes', 0) + maximum_bytes > 800_000_000:
                return None, 'monthly_bandwidth_limit'
            self.write(connection, key, {'symbols': selected, 'bytes': state.get('bytes', 0) + maximum_bytes})
        return key, None

    def finish_tiingo_transfer(self, key, reserved, actual):
        with self.locked() as connection:
            state = self.read(connection, key)
            self.write(connection, key, {**state, 'bytes': max(0, state['bytes'] - reserved + actual)})

    def claim(self, key: str, provider: str, now: int, limits: tuple[tuple[int, int], ...], *, persistent=True):
        with self.locked() as connection:
            entry = self.read(connection, f"cache:{key}")
            if not persistent:
                entry = {k: v for k, v in entry.items() if k != 'data'}
            if entry.get("expires_at", 0) > now or entry.get("lease_until", 0) > now:
                return entry, None
            state = self.read(connection, f"provider:{provider}")
            if state.get("blocked_until", 0) > now:
                return {**entry, "error": state.get("error", "rate_limited"), "retry_at": state["blocked_until"]}, None
            attempts = [t for t in state.get("attempts", []) if t > now - 86_400]
            for window, limit in limits:
                recent = [t for t in attempts if t > now - window]
                if len(recent) >= limit:
                    return {**entry, "error": "budget_exhausted", "retry_at": recent[0] + window}, None
            token = str(uuid4())
            # Failed/timeout calls consume quota too. No in-request retries.
            self.write(connection, f"provider:{provider}", {**state, "attempts": [*attempts, now]})
            self.write(connection, f"cache:{key}", {**entry, "lease": token, "lease_until": now + 120})
            return entry, token

    def finish(self, key: str, provider: str, token: str, now: int, *, data=None, ttl=21_600,
               error: str | None = None, retry_after: int = 0, persistent=True, provider_backoff=True):
        with self.locked() as connection:
            entry = self.read(connection, f"cache:{key}")
            if entry.get("lease") != token:
                return entry  # A late worker must not overwrite a newer refresh.
            state = self.read(connection, f"provider:{provider}")
            if error:
                failures = min(state.get("failures", 0) + 1, 6)
                delay = max(retry_after, min(900 * 2 ** (failures - 1), 21_600))
                if provider_backoff:
                    self.write(connection, f"provider:{provider}", {
                        **state, "failures": failures, "blocked_until": now + delay, "error": error,
                    })
                else:
                    # A missing ticker pauses only that lookup, not healthy assets.
                    entry['expires_at'] = now + delay
                entry = {**entry, "error": error, "retry_at": now + delay}
            else:
                # A different request's concurrent failure/backoff still applies.
                self.write(connection, f"provider:{provider}", {**state, "failures": 0})
                entry = {"data": data, "fetched_at": now, "expires_at": now + ttl}
            entry.pop("lease", None)
            entry.pop("lease_until", None)
            self.write(connection, f"cache:{key}", entry if persistent else {k: v for k, v in entry.items() if k != 'data'})
            return entry
