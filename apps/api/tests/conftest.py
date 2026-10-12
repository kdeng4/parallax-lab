"""Fixtures are explicit and isolated; a hosted runtime ignores this switch."""

import pytest


@pytest.fixture(autouse=True)
def isolated_market_environment(monkeypatch):
    monkeypatch.setenv("PARALLAX_MARKET_SOURCE", "synthetic")
    monkeypatch.setenv("PARALLAX_MARKET_NETWORK", "0")
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    # These tests use synthetic transport payloads, never licensed provider data.
    monkeypatch.setenv('PARALLAX_TIINGO_STORAGE_APPROVED', '1')
    monkeypatch.delenv('PARALLAX_PUBLIC_PERFORMANCE_APPROVED', raising=False)
    for name in ('OPENAI_API_KEY', 'PARALLAX_OPENAI_MODELS', 'PARALLAX_OPENAI_NETWORK'):
        monkeypatch.delenv(name, raising=False)
    for name in ('MARKETAUX_API_KEY', 'ALPHA_VANTAGE_API_KEY', 'FRED_API_KEY', 'PARALLAX_SEC_USER_AGENT'):
        monkeypatch.delenv(name, raising=False)
