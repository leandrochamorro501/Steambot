"""
core/currency.py
----------------
Currency conversion utilities for SteamBot.

Priority chain for displaying prices:
  1. regional_price from Steam Store API  (already formatted, most accurate)
  2. Conversion from price_usd using live exchange rates  (fallback)
  3. Raw USD price                                        (last resort)

Exchange rates are fetched from:
  https://open.er-api.com/v6/latest/USD   (free, no API key required, ~1500 req/month)
  Rates are cached for 6 hours to avoid hammering the API.

Circuit breaker via tenacity: stops calling the exchange rate API after
consecutive failures, preventing cascading timeouts.
"""

from __future__ import annotations

import time
import logging
from typing import Optional

import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Exchange rate cache
# ---------------------------------------------------------------------------

_RATE_CACHE: dict[str, float] = {}
_CACHE_TS: float = 0.0
_CACHE_TTL: float = 6 * 3600

_ER_API_URL = "https://open.er-api.com/v6/latest/USD"

# Hardcoded fallback rates (used when API is unreachable)
# Last updated: May 2026 — verify periodically at open.er-api.com
_FALLBACK_RATES: dict[str, float] = {
    "USD": 1.0,
    "MXN": 17.2,
    "ARS": 1200.0,
    "CLP": 950.0,
    "COP": 4200.0,
    "BRL": 5.15,
    "EUR": 0.91,
    "GBP": 0.78,
}

_SYMBOLS: dict[str, str] = {
    "USD": "$", "MXN": "Mex$", "ARS": "ARS$", "CLP": "CLP$",
    "COP": "COP$", "BRL": "R$", "EUR": "€", "GBP": "£",
}

_DECIMALS: dict[str, int] = {
    "CLP": 0, "COP": 0, "ARS": 0,
    "USD": 2, "MXN": 2, "BRL": 2, "EUR": 2, "GBP": 2,
}

# Circuit breaker state
_consecutive_failures: int = 0
_CIRCUIT_OPEN_THRESHOLD: int = 5
_circuit_open_until: float = 0.0
_CIRCUIT_COOLDOWN: float = 300.0  # 5 minutes


def _is_circuit_open() -> bool:
    """Return True if the circuit breaker is open (stop calling the API)."""
    global _consecutive_failures, _circuit_open_until
    if _consecutive_failures >= _CIRCUIT_OPEN_THRESHOLD:
        if time.time() < _circuit_open_until:
            return True
        # Cooldown expired, half-open
        _consecutive_failures = 0
    return False


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((requests.Timeout, requests.ConnectionError)),
    reraise=True,
)
def _fetch_rates_raw() -> dict:
    """Fetch fresh rates from open.er-api.com with retry + backoff."""
    if _is_circuit_open():
        raise requests.ConnectionError("Circuit breaker open — using fallback rates")

    resp = requests.get(_ER_API_URL, timeout=5)
    resp.raise_for_status()
    data = resp.json()
    if data.get("result") != "success":
        raise ValueError(f"API returned non-success: {data.get('result')}")
    return data.get("rates", {})


def _refresh_rates() -> None:
    """Fetch fresh rates, falling back to hardcoded on failure."""
    global _RATE_CACHE, _CACHE_TS, _consecutive_failures, _circuit_open_until
    try:
        _RATE_CACHE = _fetch_rates_raw()
        _CACHE_TS = time.time()
        _consecutive_failures = 0
        logger.debug("[currency] Exchange rates refreshed from API.")
    except Exception as exc:
        _consecutive_failures += 1
        if _consecutive_failures >= _CIRCUIT_OPEN_THRESHOLD:
            _circuit_open_until = time.time() + _CIRCUIT_COOLDOWN
            logger.warning(
                f"[currency] Circuit breaker OPEN ({_consecutive_failures} failures). Using fallback for {_CIRCUIT_COOLDOWN}s."
            )
        else:
            logger.warning(
                f"[currency] Rate fetch failed ({exc}), {_consecutive_failures}/{_CIRCUIT_OPEN_THRESHOLD} failures."
            )
        _RATE_CACHE = dict(_FALLBACK_RATES)
        _CACHE_TS = time.time()


def _get_rate(currency: str) -> float:
    """Return USD → currency exchange rate, refreshing cache if stale."""
    if not _RATE_CACHE or (time.time() - _CACHE_TS) > _CACHE_TTL:
        _refresh_rates()
    rate = _RATE_CACHE.get(currency.upper())
    if rate is None:
        logger.warning(f"[currency] No rate found for {currency}, defaulting to 1.0")
        return 1.0
    return rate


def convert_usd(price_usd: float, target_currency: str) -> str:
    """
    Convert a USD price to the target currency and return a formatted string.

    Examples:
        convert_usd(14.99, "CLP")  →  "CLP$ 14.390"
        convert_usd(14.99, "ARS")  →  "ARS$ 17.238"
        convert_usd(14.99, "EUR")  →  "€ 13,79"
    """
    currency = target_currency.upper()
    if currency == "USD":
        return f"${price_usd:.2f} USD"

    rate = _get_rate(currency)
    converted = price_usd * rate
    symbol = _SYMBOLS.get(currency, currency)
    decimals = _DECIMALS.get(currency, 2)

    if decimals == 0:
        return f"{symbol} {converted:,.0f}"
    return f"{symbol} {converted:,.{decimals}f}"


def format_price_for_session(game: dict, currency: str) -> str:
    """
    Return the best available price string for a game in the user's currency.

    Priority:
      1. regional_price (from Steam Store API) — already formatted
      2. convert price_usd to currency
      3. raw USD price
    """
    if game.get("regional_price"):
        price = game["regional_price"]
        discount = game.get("regional_discount", 0)
        if discount > 0:
            price += f" 🔥 (-{discount}%)"
        return price

    price_usd = game.get("price_usd", 0.0)
    if price_usd == 0.0:
        return "Gratis"

    converted = convert_usd(price_usd, currency)
    discount = game.get("discount", 0)
    if discount > 0:
        converted += f" 🔥 (-{discount}%)"
    return converted
