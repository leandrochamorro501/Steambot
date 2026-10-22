"""
core/steam_api.py
-----------------
Handles all communication with the SteamSpy API and applies
business logic filters (price, reviews, discounts).

Also provides regional pricing via the official Steam Store API,
with automatic USD-conversion fallback via core.currency.

SteamSpy API Docs: https://steamspy.com/api.php
Rate limit: 1 req/s for most endpoints.
"""

import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

STEAMSPY_BASE = "https://steamspy.com/api.php"
STEAM_STORE_API = "https://store.steampowered.com/api/appdetails"
REQUEST_DELAY = 1.0  # seconds — SteamSpy rate limit is 1 req/s

# -- In-memory cache with TTL ------------------------------------------------
_cache: dict[str, dict] = {}
CACHE_TTL = 21600  # 6 hours — balance between freshness and rate limits

# -- Regional price cache (Steam Store API) ----------------------------------
_regional_price_cache: dict[str, tuple[float, dict]] = {}  # key → (timestamp, data)
_REGIONAL_CACHE_TTL = 3600  # 1 hour — prices rarely change intra-day

# -- New releases cache (Steam Store API) ------------------------------------
_new_releases_cache: dict[str, tuple[float, list[dict]]] = {}  # cc -> (timestamp, data)
_NEW_RELEASES_CACHE_TTL = 3600  # 1 hour

_request_timestamps: list[float] = []

# -- "all" endpoint rate limiting (1 req per 60 s) ---------------------------
_last_all_request: float = 0.0
_ALL_MIN_INTERVAL = 60.0

# -- Global name-search cache (all endpoint page 0) --------------------------
_all_cache: dict = {}
_all_cache_ts: float = 0.0
_ALL_CACHE_TTL = 86400  # 24 h — SteamSpy refreshes daily


# -- Supported regions -------------------------------------------------------
REGIONS = {
    "US": {"cc": "us", "label": "Estados Unidos (USD)",   "symbol": "$",    "currency": "USD"},
    "MX": {"cc": "mx", "label": "México (MXN)",           "symbol": "Mex$", "currency": "MXN"},
    "AR": {"cc": "ar", "label": "Argentina (ARS)",         "symbol": "ARS$", "currency": "ARS"},
    "CL": {"cc": "cl", "label": "Chile (CLP)",             "symbol": "CLP$", "currency": "CLP"},
    "CO": {"cc": "co", "label": "Colombia (COP)",          "symbol": "COP$", "currency": "COP"},
    "BR": {"cc": "br", "label": "Brasil (BRL)",            "symbol": "R$",   "currency": "BRL"},
    "ES": {"cc": "es", "label": "España (EUR)",            "symbol": "€",    "currency": "EUR"},
    "GB": {"cc": "gb", "label": "Reino Unido (GBP)",       "symbol": "£",    "currency": "GBP"},
    "VE": {"cc": "ve", "label": "Venezuela (USD - Steam)", "symbol": "$",    "currency": "USD"},
}

# Language code → best-fit region code (for auto-detection)
LANGUAGE_TO_REGION: dict[str, str] = {
    "es": "CL",   # generic Spanish → Chile as safe default for this user
    "es-419": "MX",
    "es-mx": "MX",
    "es-ar": "AR",
    "es-cl": "CL",
    "es-co": "CO",
    "es-ve": "VE",
    "pt": "BR",
    "pt-br": "BR",
    "en": "US",
    "en-gb": "GB",
    "en-us": "US",
}


def region_from_language(lang_code: str) -> str:
    """Map a Telegram language_code to a REGIONS key, defaulting to 'CL'."""
    if not lang_code:
        return "CL"
    lc = lang_code.lower()
    # Try exact match first, then prefix
    if lc in LANGUAGE_TO_REGION:
        return LANGUAGE_TO_REGION[lc]
    prefix = lc.split("-")[0]
    return LANGUAGE_TO_REGION.get(prefix, "CL")


# -- Cache helpers -----------------------------------------------------------

def _cache_key(params: dict) -> str:
    return "|".join(f"{k}={v}" for k, v in sorted(params.items()))


def _cache_get(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        return entry["data"]
    if entry:
        del _cache[key]
    return None


def _cache_set(key: str, data: dict) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


# -- Rate limiter ------------------------------------------------------------

def _respect_rate_limit() -> None:
    global _request_timestamps
    now = time.time()
    _request_timestamps = [t for t in _request_timestamps if now - t < 1.0]
    if len(_request_timestamps) >= 1:
        sleep_time = 1.0 - (now - _request_timestamps[0]) + 0.05
        if sleep_time > 0:
            time.sleep(sleep_time)
    _request_timestamps.append(time.time())


# -- Low-level GET -----------------------------------------------------------

def _get(params: dict, max_retries: int = 3) -> dict:
    """
    Low-level GET to SteamSpy with retry/backoff and caching.

    Returns JSON dict on success, empty dict on failure.
    """
    key = _cache_key(params)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    last_error = None
    for attempt in range(1, max_retries + 1):
        _respect_rate_limit()
        timeout = 15 * attempt
        try:
            resp = requests.get(STEAMSPY_BASE, params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            _cache_set(key, data)
            return data
        except requests.exceptions.Timeout as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(2.0 * attempt)
        except requests.exceptions.ConnectionError as e:
            last_error = e
            if attempt < max_retries:
                time.sleep(3.0 * attempt)
        except requests.exceptions.RequestException as e:
            last_error = e
            if hasattr(e, "response") and e.response and 400 <= e.response.status_code < 500:
                return {}
            if attempt < max_retries:
                time.sleep(1.0 * attempt)

    logger.warning(f"[steam_api] All {max_retries} attempts failed. Last error: {last_error}")
    return {}


# -- Health check ------------------------------------------------------------

def is_steamspy_available() -> bool:
    """Quick health check — True if SteamSpy responds within 8 s."""
    key = _cache_key({"request": "healthcheck"})
    cached = _cache_get(key)
    if cached is not None:
        return cached.get("_available", True)
    try:
        _respect_rate_limit()
        resp = requests.get(
            STEAMSPY_BASE,
            params={"request": "tag", "tag": "Action"},
            timeout=8,
        )
        resp.raise_for_status()
        ok = bool(resp.json())
        _cache_set(key, {"_available": ok})
        return ok
    except Exception:
        _cache_set(key, {"_available": False})
        return False


# -- Public search endpoints -------------------------------------------------

def search_by_tag(tag: str) -> dict:
    # 1. Try to filter top 1000 games locally from cache
    all_games = search_all(page=0)
    if all_games and isinstance(all_games, dict):
        tag_lower = tag.lower()
        matching = {}
        for appid, game in all_games.items():
            game_tags = game.get("tags")
            # If tags is present in the cache entry, filter by it
            if isinstance(game_tags, dict):
                if tag_lower in {t.lower() for t in game_tags.keys()}:
                    matching[appid] = game
            elif isinstance(game_tags, list):
                if tag_lower in {t.lower() for t in game_tags}:
                    matching[appid] = game

        # If we found matches in the Top 1000 cache, return them
        if matching:
            logger.info(f"[steam_api] search_by_tag '{tag}' matched {len(matching)} games from local Top 1000.")
            return matching

    # 2. Fallback to direct SteamSpy API call (useful if API works or for niche tags)
    res = _get({"request": "tag", "tag": tag.lower()})
    if res and isinstance(res, dict) and len(res) > 0:
        return res

    return {}


def search_by_genre(genre: str) -> dict:
    # 1. Try to filter top 1000 games locally from cache
    all_games = search_all(page=0)
    if all_games and isinstance(all_games, dict):
        genre_lower = genre.lower()
        matching = {}
        for appid, game in all_games.items():
            # Check genres list/string
            game_genres = game.get("genre")
            if isinstance(game_genres, list):
                if genre_lower in {g.lower() for g in game_genres}:
                    matching[appid] = game
                    continue
            elif isinstance(game_genres, str):
                if genre_lower == game_genres.lower():
                    matching[appid] = game
                    continue

            # Fallback to check tags for the genre name (genres are usually tags too)
            game_tags = game.get("tags")
            if isinstance(game_tags, dict):
                if genre_lower in {t.lower() for t in game_tags.keys()}:
                    matching[appid] = game
            elif isinstance(game_tags, list):
                if genre_lower in {t.lower() for t in game_tags}:
                    matching[appid] = game

        # If we found matches in the Top 1000 cache, return them
        if matching:
            logger.info(f"[steam_api] search_by_genre '{genre}' matched {len(matching)} games from local Top 1000.")
            return matching

    # 2. Fallback to direct SteamSpy API call
    res = _get({"request": "genre", "genre": genre.lower()})
    if res and isinstance(res, dict) and len(res) > 0:
        return res

    return {}



def get_app_details(appid: int) -> dict:
    return _get({"request": "appdetails", "appid": appid})


# -- Top / discovery endpoints -----------------------------------------------

def get_new_releases(region_code: str = "US") -> list[dict]:
    """
    Returns real new releases from Steam Store's /api/featuredcategories/ endpoint.
    Returns standard game dicts to be enriched with prices by the pipeline.
    """
    region = REGIONS.get(region_code.upper(), REGIONS["US"])
    cc = region["cc"]
    now = time.time()

    if cc in _new_releases_cache:
        cached_ts, cached_data = _new_releases_cache[cc]
        if now - cached_ts < _NEW_RELEASES_CACHE_TTL:
            return cached_data

    url = "https://store.steampowered.com/api/featuredcategories/"
    params = {"cc": cc, "l": "spanish"}

    try:
        _respect_rate_limit()
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("new_releases", {}).get("items", [])
        if not items:
            items = data.get("top_sellers", {}).get("items", [])

        results = []
        for item in items:
            appid = item.get("id")
            if not appid:
                continue

            results.append({
                "appid": int(appid),
                "name": item.get("name", "Unknown"),
                "developer": "Novedad de Steam",
                "publisher": "",
                "price_usd": 0.0,
                "original_price_usd": 0.0,
                "discount": item.get("discount_percent", 0),
                "score_rank": 80,
                "owners": "100,000..200,000",
                "positive": 1000,
                "negative": 100,
                "tags": {},
            })

        if results:
            _new_releases_cache[cc] = (now, results)
        return results

    except Exception as e:
        logger.warning(f"[steam_api] get_new_releases failed: {e}")
        return []


def top100in2weeks() -> list[dict]:
    """Returns Top 100 games by players in the last two weeks."""
    data = _get({"request": "top100in2weeks"})
    if not data:
        return []
    # SteamSpy returns a dict keyed by appid for most endpoints
    return list(data.values()) if isinstance(data, dict) else []


def top100forever() -> list[dict]:
    """Returns Top 100 games by players since March 2009."""
    data = _get({"request": "top100forever"})
    if not data:
        return []
    return list(data.values()) if isinstance(data, dict) else []


def top100owned() -> list[dict]:
    """Returns Top 100 games by owners."""
    data = _get({"request": "top100owned"})
    if not data:
        return []
    return list(data.values()) if isinstance(data, dict) else []


def search_all(page: int = 0) -> dict:
    """
    Returns up to 1,000 games sorted by owners, from the given page.

    Rate limit: 1 req per 60 s (enforced globally).
    Page 0 is cached for 24 h to serve name searches efficiently.
    Uses disk caching to persist the data and provide graceful offline fallbacks.
    """
    global _all_cache, _all_cache_ts

    # 1. Check in-memory cache
    if page == 0 and _all_cache and (time.time() - _all_cache_ts) < _ALL_CACHE_TTL:
        return _all_cache

    # 2. Check disk cache if page == 0
    if page == 0:
        import os
        import json
        cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "top_1000_cache.json")
        if os.path.exists(cache_path):
            try:
                mtime = os.path.getmtime(cache_path)
                # If disk cache is fresh (less than 24h old), load it
                if (time.time() - mtime) < _ALL_CACHE_TTL:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data and isinstance(data, dict) and len(data) > 0:
                        _all_cache = data
                        _all_cache_ts = mtime
                        logger.info("[steam_api] Loaded top 1000 games from valid disk cache.")
                        return data
            except Exception as e:
                logger.warning(f"[steam_api] Error loading disk cache: {e}")

    # 3. Call API (complying with rate limits)
    global _last_all_request
    now = time.time()
    elapsed = now - _last_all_request
    if elapsed < _ALL_MIN_INTERVAL:
        wait = _ALL_MIN_INTERVAL - elapsed + 0.5
        logger.debug("[steam_api] search_all rate limit — sleeping %.1f s", wait)
        time.sleep(wait)

    _last_all_request = time.time()
    data = _get({"request": "all", "page": str(page)})

    if page == 0:
        import os
        import json
        cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "top_1000_cache.json")
        if data and isinstance(data, dict) and len(data) > 0:
            _all_cache = data
            _all_cache_ts = time.time()
            try:
                with open(cache_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info("[steam_api] Saved top 1000 games to disk cache.")
            except Exception as e:
                logger.warning(f"[steam_api] Error saving disk cache: {e}")
        else:
            # API call failed (rate limited, offline, etc.). Use existing disk cache even if expired
            if os.path.exists(cache_path):
                try:
                    with open(cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data and isinstance(data, dict) and len(data) > 0:
                        _all_cache = data
                        _all_cache_ts = os.path.getmtime(cache_path)
                        logger.warning("[steam_api] search_all API call failed. Using expired disk cache as fallback.")
                        return data
                except Exception as e:
                    logger.warning(f"[steam_api] Error loading expired disk cache: {e}")

    return data or {}


def search_by_name(name: str, limit: int = 5) -> list[dict]:
    """
    Search for games by name using the cached 'all' endpoint (page 0).

    Performs a case-insensitive substring match against the ~1,000 most-owned
    games on Steam.  Returns up to *limit* results sorted by owners DESC.

    This is the primary look-up mechanism for CHECK_PRICE and game-name
    resolution when the user mentions a specific title.
    """
    if not name or not name.strip():
        return []

    needle = name.strip().lower()
    all_games = search_all(page=0)
    if not all_games:
        return []

    matches: list[dict] = []

    for appid, game in all_games.items():
        game_name = (game.get("name") or "").lower()
        if not game_name:
            continue
        # Exact match scores highest
        if game_name == needle:
            matches.append((0, appid, game))
        elif needle in game_name:
            matches.append((1, appid, game))
        elif any(word in game_name for word in needle.split() if len(word) >= 3):
            matches.append((2, appid, game))

    # Sort by match quality, then by owners (more owners = more relevant)
    matches.sort(key=lambda x: (x[0], -_parse_owners_for_sort(x[2].get("owners", ""))))

    result = []
    for _, appid, game in matches[:limit]:
        result.append({
            "appid": int(appid) if appid.isdigit() else 0,
            "name": game.get("name", "Unknown"),
            "developer": game.get("developer", ""),
            "publisher": game.get("publisher", ""),
            "price_cents": int(game.get("price", 0) or 0),
            "initialprice": int(game.get("initialprice", 0) or 0),
            "discount": int(game.get("discount", 0) or 0),
            "score_rank": game.get("score_rank", ""),
            "owners": game.get("owners", ""),
            "tags": game.get("tags", {}),
            "genre": game.get("genre", []),
        })
    return result


def _parse_owners_for_sort(owners_str: str) -> int:
    """Rough numeric extraction from owners range for sorting purposes."""
    if not owners_str:
        return 0
    try:
        parts = owners_str.replace(",", "").split("..")
        if len(parts) == 2:
            return int(parts[1])
        return 0
    except (ValueError, IndexError):
        return 0


# -- Price helpers -----------------------------------------------------------

def cents_to_usd(cents) -> float:
    try:
        return round(int(cents) / 100, 2)
    except (TypeError, ValueError):
        return 0.0


def _parse_game_fields(game: dict) -> dict:
    """
    Extract and normalise numeric fields from a raw SteamSpy game entry.
    Centralises the parsing logic that was previously duplicated in
    filter_games() and union_by_tags().
    """
    try:
        price_cents = int(game.get("price", 0) or 0)
    except (TypeError, ValueError):
        price_cents = 0
    try:
        initial_cents = int(game.get("initialprice", 0) or 0)
    except (TypeError, ValueError):
        initial_cents = 0
    try:
        discount = int(game.get("discount", 0) or 0)
    except (TypeError, ValueError):
        discount = 0

    score_raw = game.get("score_rank", "")
    try:
        score = int(score_raw) if score_raw != "" else None
    except (ValueError, TypeError):
        score = None

    return {
        "price_cents": price_cents,
        "price_usd": cents_to_usd(price_cents),
        "original_price_usd": cents_to_usd(initial_cents),
        "discount": discount,
        "score_rank": score,
    }


# -- Filtering ---------------------------------------------------------------

def filter_games(
    games: dict,
    max_price_usd: Optional[float] = None,
    min_price_usd: Optional[float] = None,
    min_score_rank: Optional[int] = None,
    only_on_sale: bool = False,
    limit: int = 10,
    allow_nsfw: bool = False,
) -> list[dict]:
    from models.tag_registry import is_nsfw_game

    filtered = []

    for appid, game in games.items():
        if game.get("appid") == 999999:
            continue
        if not game.get("name", "").strip():
            continue

        # Bloquear contenido sexual explícito (opt-in requerido)
        if not allow_nsfw:
            raw_tags = game.get("tags") or {}
            if isinstance(raw_tags, dict):
                game_tags = set(raw_tags.keys())
            elif isinstance(raw_tags, (list, set)):
                game_tags = set(raw_tags)
            else:
                game_tags = set()
            game_name = game.get("name", "")
            if is_nsfw_game(game_tags, game_name):
                continue

        fields = _parse_game_fields(game)

        if max_price_usd is not None and fields["price_cents"] > 0 and fields["price_usd"] > max_price_usd:
            continue
        if min_price_usd is not None and fields["price_usd"] < min_price_usd:
            continue
        if only_on_sale and fields["discount"] <= 0:
            continue
        if min_score_rank is not None:
            # If score is None, only keep it if it's very popular (prestige)
            if fields["score_rank"] is None:
                try:
                    owners_low = int(game.get("owners", "0").split("..")[0].replace(",", "").strip())
                    if owners_low < 50000: # If not popular and no score, filter out
                        continue
                except:
                    continue
            elif fields["score_rank"] < min_score_rank:
                continue

        filtered.append({
            "appid": appid,
            "name": game.get("name", "Unknown"),
            "developer": game.get("developer", ""),
            "publisher": game.get("publisher", ""),
            "price_usd": fields["price_usd"],
            "original_price_usd": fields["original_price_usd"],
            "discount": fields["discount"],
            "score_rank": fields["score_rank"],
            "owners": game.get("owners", ""),
            "positive": game.get("positive", 0),
            "negative": game.get("negative", 0),
            "tags": game.get("tags", {}),
        })

    # Sort by popularity: positive reviews + owners lower bound
    def _popularity_key(g):
        try:
            owners_lower = int(g["owners"].split("..")[0].replace(",", "").strip())
        except:
            owners_lower = 0
        # Combine owners lower bound and positive reviews for a strong popularity signal
        return (owners_lower + g.get("positive", 0))

    filtered.sort(key=_popularity_key, reverse=True)
    return filtered[:limit]


def intersect_by_tags(
    tags: list[str],
    max_price_usd: Optional[float] = None,
    min_price_usd: Optional[float] = None,
    min_score_rank: Optional[int] = None,
    only_on_sale: bool = False,
    limit: int = 10,
    allow_nsfw: bool = False,
) -> list[dict]:
    """AND intersection — games that appear in ALL tag results."""
    if not tags:
        return []
    all_results = []
    sets = []

    for tag in tags:
        result = search_by_tag(tag)
        if not result:
            logger.info(f"[steam_api] SteamSpy returned no results for tag '{tag}'")
        all_results.append(result)
        sets.append(set(result.keys()))

    common_ids = sets[0].intersection(*sets[1:])
    games = {appid: all_results[0][appid] for appid in common_ids if appid in all_results[0]}

    return filter_games(games, max_price_usd=max_price_usd, min_price_usd=min_price_usd, min_score_rank=min_score_rank,
                        only_on_sale=only_on_sale, limit=limit, allow_nsfw=allow_nsfw)


def union_by_tags(
    tags: list[str],
    max_price_usd: Optional[float] = None,
    min_price_usd: Optional[float] = None,
    min_score_rank: Optional[int] = None,
    only_on_sale: bool = False,
    limit: int = 10,
    allow_nsfw: bool = False,
) -> list[dict]:
    """Union — games from ANY tag, scored by number of matching tags."""
    if not tags:
        return []

    from models.tag_registry import is_nsfw_game

    tag_match_counts: dict[str, int] = {}
    all_games: dict = {}

    for tag in tags:
        result = search_by_tag(tag)
        if not result:
            logger.info(f"[steam_api] SteamSpy returned no results for tag '{tag}'")
        for appid, game in result.items():
            if appid not in all_games:
                all_games[appid] = game
                tag_match_counts[appid] = 0
            tag_match_counts[appid] += 1

    if not all_games:
        return []

    filtered: list[dict] = []
    for appid, game in all_games.items():
        if game.get("appid") == 999999 or not game.get("name", "").strip():
            continue

        # Bloquear contenido sexual explícito (opt-in requerido)
        if not allow_nsfw:
            raw_tags = game.get("tags") or {}
            if isinstance(raw_tags, dict):
                game_tags = set(raw_tags.keys())
            elif isinstance(raw_tags, (list, set)):
                game_tags = set(raw_tags)
            else:
                game_tags = set()
            game_name = game.get("name", "")
            if is_nsfw_game(game_tags, game_name):
                continue

        fields = _parse_game_fields(game)

        if max_price_usd is not None and fields["price_cents"] > 0 and fields["price_usd"] > max_price_usd:
            continue
        if min_price_usd is not None and fields["price_usd"] < min_price_usd:
            continue
        if only_on_sale and fields["discount"] <= 0:
            continue
        if min_score_rank is not None and (fields["score_rank"] is None or fields["score_rank"] < min_score_rank):
            continue

        filtered.append({
            "appid": appid,
            "name": game.get("name", "Unknown"),
            "developer": game.get("developer", ""),
            "publisher": game.get("publisher", ""),
            "price_usd": fields["price_usd"],
            "original_price_usd": fields["original_price_usd"],
            "discount": fields["discount"],
            "score_rank": fields["score_rank"],
            "owners": game.get("owners", ""),
            "tags": game.get("tags", {}),
            "_tag_matches": tag_match_counts[appid],
        })

    filtered.sort(
        key=lambda g: (g.get("_tag_matches", 0), g.get("score_rank") or 0, g.get("discount", 0)),
        reverse=True,
    )
    return filtered[:limit]


GENRE_TO_TAG = {
    "Action": "Action",
    "RPG": "RPG",
    "Strategy": "Strategy",
    "Indie": "Indie",
    "Adventure": "Adventure",
    "Simulation": "Simulation",
    "Racing": "Racing",
    "Sports": "Sports",
    "Casual": "Casual",
    "Free to Play": "Free to Play",
    "Early Access": "Early Access",
}


def smart_search(
    tags: list[str],
    genre: Optional[str] = None,
    max_price_usd: Optional[float] = None,
    min_price_usd: Optional[float] = None,
    min_score_rank: Optional[int] = None,
    only_on_sale: bool = False,
    limit: int = 10,
    allow_nsfw: bool = False,
) -> list[dict]:
    """
    Intelligent search: AND intersection → union fallback → genre search.
    """
    results: list[dict] = []

    if tags and len(tags) > 1:
        results = intersect_by_tags(tags, max_price_usd=max_price_usd, min_price_usd=min_price_usd,
                                    min_score_rank=min_score_rank, only_on_sale=only_on_sale,
                                    limit=limit, allow_nsfw=allow_nsfw)
        if not results:
            results = union_by_tags(tags, max_price_usd=max_price_usd, min_price_usd=min_price_usd,
                                    min_score_rank=min_score_rank, only_on_sale=only_on_sale,
                                    limit=limit, allow_nsfw=allow_nsfw)
    elif tags:
        tag_to_try = tags[0]
        raw = search_by_tag(tag_to_try)

        # SUPER-ROBUSTNESS: If primary tag fails, try common SteamSpy variations
        if not raw:
            variations = []
            if tag_to_try == "Action": variations = ["Action-Adventure", "Shooter"]
            elif tag_to_try == "Racing": variations = ["Driving", "Automobile Sim", "Sports", "Simulation"]
            elif tag_to_try == "Building": variations = ["Base-Building", "City Builder", "Simulation", "Strategy"]
            elif tag_to_try == "Open World": variations = ["Exploration", "Sandbox", "Adventure"]

            for v in variations:
                raw = search_by_tag(v)
                if raw:
                    logger.info(f"[steam_api] Primary tag '{tag_to_try}' failed, using variation '{v}'")
                    break

        results = filter_games(raw, max_price_usd=max_price_usd, min_price_usd=min_price_usd, allow_nsfw=allow_nsfw,
                               min_score_rank=min_score_rank, only_on_sale=only_on_sale,
                               limit=limit)
    elif genre:
        raw = search_by_genre(genre)
        # Always fallback to tag if genre search is empty or unreliable
        if not raw and genre in GENRE_TO_TAG:
            raw = search_by_tag(GENRE_TO_TAG[genre])

        results = filter_games(raw, max_price_usd=max_price_usd, min_price_usd=min_price_usd, allow_nsfw=allow_nsfw,
                               min_score_rank=min_score_rank, only_on_sale=only_on_sale,
                               limit=limit)

    # Merge genre results if both tags + genre provided
    if genre and tags and results:
        raw_genre = search_by_genre(genre)
        if not raw_genre and genre in GENRE_TO_TAG:
            raw_genre = search_by_tag(GENRE_TO_TAG[genre])
        if raw_genre:
            existing_ids = {str(g["appid"]) for g in results}
            extra = filter_games(raw_genre, max_price_usd=max_price_usd, min_price_usd=min_price_usd,
                                 min_score_rank=min_score_rank, only_on_sale=only_on_sale,
                                 limit=limit, allow_nsfw=allow_nsfw)
            for g in extra:
                if str(g["appid"]) not in existing_ids:
                    results.append(g)
            results.sort(
                key=lambda g: (g.get("_tag_matches", 1), g.get("score_rank") or 0),
                reverse=True,
            )
            results = results[:limit]

    return results


# -- Regional pricing --------------------------------------------------------

def fetch_regional_prices(appids: list[str], region_code: str = "US") -> dict:
    """
    Fetch prices from the official Steam Store API for a list of appids.

    Prices are cached per (appid, region) with a 1-hour TTL to reduce
    redundant API calls across consecutive searches.

    Queries each appid individually (without filters) to get complete metadata,
    allowing us to strictly verify active status (differentiating Free-to-Play
    from delisted games).

    Returns dict: appid -> {final_formatted, discount_percent, currency}
    """
    region = REGIONS.get(region_code.upper())
    if not region:
        return {}

    prices = {}
    now = time.time()

    for appid in appids:
        appid_str = str(appid)
        cache_key = f"{appid_str}:{region['cc']}"
        cached_entry = _regional_price_cache.get(cache_key)

        if cached_entry and (now - cached_entry[0]) < _REGIONAL_CACHE_TTL:
            if cached_entry[1] is not None:  # None means delisted/invalid
                prices[appid_str] = cached_entry[1]
            continue

        # Fetch from Steam API
        success = False
        price_data = None

        for attempt in range(2):  # retry once on failure
            try:
                _respect_rate_limit()
                resp = requests.get(
                    STEAM_STORE_API,
                    params={"appids": appid_str, "cc": region["cc"]},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()

                app_data = data.get(appid_str, {})
                if isinstance(app_data, dict) and app_data.get("success") and "data" in app_data:
                    inner_data = app_data["data"]
                    if isinstance(inner_data, list):
                        inner_data = inner_data[0] if inner_data else {}

                    po = inner_data.get("price_overview", {}) if isinstance(inner_data, dict) else {}
                    is_free = inner_data.get("is_free", False) if isinstance(inner_data, dict) else False

                    if po:
                        price_data = {
                            "final_formatted": po.get("final_formatted", "?"),
                            "discount_percent": po.get("discount_percent", 0),
                            "currency": po.get("currency", region["currency"]),
                        }
                        success = True
                    elif is_free:
                        price_data = {
                            "final_formatted": "Gratis",
                            "discount_percent": 0,
                            "currency": region["currency"],
                        }
                        success = True
                break  # succeeded, break retry loop
            except Exception as e:
                if attempt == 0:
                    logger.debug(f"[pricing] Steam Store individual retry for {appid_str}: {e}")
                    time.sleep(0.3)
                else:
                    logger.warning(f"[pricing] Steam Store individual failed for {appid_str}: {e}")

        # Cache the result (even if None, to avoid re-querying delisted games!)
        _regional_price_cache[cache_key] = (now, price_data)
        if success and price_data:
            prices[appid_str] = price_data

        # Add a very small sleep to respect rate limits
        time.sleep(0.15)

    return prices


def enrich_with_regional_prices(
    games: list[dict],
    region_code: str = "US",
) -> list[dict]:
    """
    Enriches game dicts with regional prices.
    - Discards games that are delisted or not found in the official Steam Store API.
    - Games always end up with a populated regional_price field.
    """
    from core.currency import convert_usd

    region = REGIONS.get(region_code.upper())
    currency = region["currency"] if region else "USD"

    if not games:
        return games

    # Fetch Steam Store regional prices (always validate all games against the store API)
    appids = [str(g["appid"]) for g in games]
    regional = fetch_regional_prices(appids, region_code)

    enriched_games = []
    from_steam = 0

    for game in games:
        appid_str = str(game["appid"])
        if appid_str in regional:
            rp = regional[appid_str]
            game["regional_price"] = rp["final_formatted"]
            game["regional_currency"] = rp["currency"]
            game["regional_discount"] = rp["discount_percent"]
            game["price_source"] = "steam_store"
            enriched_games.append(game)
            from_steam += 1
        else:
            logger.info(
                f"[pricing] Skipping game '{game.get('name')}' (appid={appid_str}) because "
                f"it was not found or is delisted/inactive in the official Steam Store."
            )

    logger.info(
        f"[pricing] Regional prices: {from_steam}/{len(games)} games successfully validated and enriched from Steam Store."
    )

    return enriched_games


def search_store_by_name(query: str, region_code: str = "US") -> list[dict]:
    """
    Search the official Steam Storefront API by name.
    Very fast, returns list of games with appid, name, and regional price.
    """
    region = REGIONS.get(region_code.upper(), REGIONS["US"])
    cc = region["cc"]

    url = "https://store.steampowered.com/api/storesearch/"
    params = {"term": query, "l": "spanish", "cc": cc}

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])

        results = []
        for item in items:
            appid = item.get("id")
            name = item.get("name", "")

            # Format price
            price_info = item.get("price", {})
            price_cents = price_info.get("final", 0)
            initial_cents = price_info.get("initial", 0)
            currency = price_info.get("currency", "USD")

            price_usd = price_cents / 100
            original_price_usd = initial_cents / 100

            discount = 0
            if initial_cents > price_cents:
                discount = int(round((1 - (price_cents / initial_cents)) * 100))

            symbol = region.get("symbol", "$")
            if price_cents == 0:
                regional_price = "Gratis"
            else:
                if currency == "CLP":
                    # Format as CLP$ 22.990
                    regional_price = f"CLP$ {int(price_usd):,}".replace(",", ".")
                else:
                    regional_price = f"{symbol} {price_usd:.2f}"

            results.append({
                "appid": int(appid),
                "name": name,
                "price_usd": price_usd,
                "original_price_usd": original_price_usd,
                "discount": discount,
                "regional_price": regional_price,
                "regional_currency": currency,
                "regional_discount": discount,
                "price_source": "steam_store",
                "developer": "",
                "publisher": "",
                "owners": "Unknown",
                "score_rank": 0,
                "tags": {},
            })
        return results
    except Exception as e:
        logger.error(f"[steam_api] search_store_by_name failed for '{query}': {e}")
        return []
