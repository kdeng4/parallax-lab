"""Fixtures are explicit and isolated; a hosted runtime ignores this switch."""

import pytest


@pytest.fixture(autouse=True)
def isolated_market_environment(monkeypatch):
    monkeypatch.setenv("PARALLAX_MARKET_SOURCE", "synthetic")
    monkeypatch.setenv("PARALLAX_MARKET_NETWORK", "0")
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
