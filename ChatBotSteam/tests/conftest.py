"""Keep the automated suite independent from network access and live rates."""

import socket

import pytest


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError("Network access is disabled in offline tests")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)

    from core import currency
    from core.session import registry

    monkeypatch.setattr(currency, "_RATE_CACHE", dict(currency._FALLBACK_RATES))
    monkeypatch.setattr(currency, "_CACHE_TS", currency.time.time())
    monkeypatch.setattr(currency, "_fetch_rates_raw", lambda: dict(currency._FALLBACK_RATES))
    monkeypatch.setattr(registry, "_sessions", {})
