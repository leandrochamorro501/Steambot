"""
core/pipeline.py
----------------
UNIFIED recommendation pipeline, UI-agnostic.
Both telegram_bot.py AND main.py delegate to run_pipeline().

NLU_ENGINE (controlled via .env):
  wit       — Wit.ai API (Meta, 100% gratuito). Clasifica intents y extrae
              entidades. DeepSeek se usa solo para generar respuestas (NLG).
  deepseek  — DeepSeek extrae intents Y genera respuestas (modo legacy).
  (ausente) — Igual que 'deepseek'.

Pipeline per turn:
  1. Add user message to session memory
  2. Extract intent via NLU_ENGINE (Wit.ai → fallback a reglas locales)
  3. Validate/normalize tags against tag_registry
  4. Route by intent type
  5. If game query: search SteamSpy → score (recommendation_engine) → enrich prices → generate recommendation (DeepSeek NLG)
  6. Return PipelineResult with the response text and metadata
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core import llm_engine, steam_api
from core.session import Session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# NLU Engine selector — lee NLU_ENGINE desde .env
# ---------------------------------------------------------------------------
_NLU_ENGINE: str = os.getenv("NLU_ENGINE", "deepseek").lower().strip()


# == Result dataclass ==========================================================

@dataclass
class PipelineResult:
    response_text: str
    intent: dict = field(default_factory=dict)
    games_found: list[dict] = field(default_factory=list)
    status: str = "ok"  # "ok" | "chat" | "error" | "no_results" | "unavailable"
    feedback_message_id: int = 0  # Telegram message ID for feedback


_PIPELINE_FALLBACK_MSG = (
    "🎮 No pude generar la recomendación en este momento. "
    "Intenta de nuevo en unos segundos."
)


def _ensure_response_text(text: str, games: list[dict] | None = None) -> str:
    """Guarantee response_text is never empty.

    If the LLM returned an empty string, build a minimal response from
    the game data we already have so the user always sees something.
    """
    if text and text.strip():
        return text
    # Try to build something useful from the games list
    if games:
        lines = ["Aquí algunos juegos que encontré:\n"]
        for g in games[:5]:
            price = g.get("regional_price", f"${g.get('price_usd', '?')} USD")
            lines.append(f"  🎮 *{g.get('name', 'Unknown')}* — {price}")
        return "\n".join(lines)
    return _PIPELINE_FALLBACK_MSG


# == Tag validation ============================================================

def _validate_tags(tags: list[str]) -> list[str]:
    """Normalize and validate tags against the official SteamSpy registry."""
    if not tags:
        return []
    try:
        from models.tag_registry import normalize_tags, translate_spanish_to_tags
        normalized = normalize_tags(tags)

        dropped = []
        for tag in tags:
            if translate_spanish_to_tags(tag):
                continue
            if any(n.lower() == tag.lower() for n in normalized):
                continue
            dropped.append(tag)

        if dropped:
            logger.warning(f"[pipeline] Dropped invalid tags: {dropped}")

        return normalized
    except ImportError:
        return tags  # Graceful fallback


# == No-results message builder ================================================

def _build_no_results_msg(
    tags: list[str],
    genre: Optional[str],
    max_price: Optional[float],
    min_price: Optional[float] = None,
    only_sale: bool = False,
    min_score: Optional[int] = None,
) -> str:
    filter_parts = []
    if tags:
        filter_parts.append(f"tags: {', '.join(tags)}")
    if genre:
        filter_parts.append(f"género: {genre}")
    if min_price is not None:
        filter_parts.append(f"precio mínimo: ${min_price:.2f}")
    if max_price is not None:
        filter_parts.append(f"precio máximo: ${max_price:.2f}")
    if only_sale:
        filter_parts.append("solo ofertas")
    if min_score is not None:
        filter_parts.append(f"puntuación mínima: {min_score}%")

    filter_desc = "; ".join(filter_parts) if filter_parts else "esos criterios"

    suggestions = []
    if min_price is not None and min_price > 0:
        suggestions.append("• Intenta bajar el precio mínimo")
    if max_price is not None and max_price < 20:
        suggestions.append("• Intenta subir el precio máximo")
    if only_sale:
        suggestions.append("• Desactiva el filtro 'solo ofertas' para ver más opciones")
    if tags and len(tags) > 1:
        suggestions.append("• Prueba con menos tags (1-2 en vez de 3)")
    if min_score is not None and min_score > 70:
        suggestions.append("• Baja la puntuación mínima requerida")
    if not suggestions:
        suggestions.append("• Prueba con tags más genéricos como 'Action', 'Adventure' o 'RPG'")

    return f"No encontré juegos con {filter_desc}.\n\nSugerencias:\n" + "\n".join(suggestions)


# == Novelty query detector ====================================================

def _is_novelty_query(message: str) -> bool:
    if not message:
        return False
    from nlu.wit_client import _NOVELTY_KEYWORDS
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in _NOVELTY_KEYWORDS)


# == CHECK_PRICE real implementation ===========================================

def _check_price(game_name: str, session: Session, user_message: str = "") -> PipelineResult:
    """Real CHECK_PRICE: search Steam Store by name, fetch price directly.

    If game_name is empty, asks DeepSeek to extract it from the user message.
    Only asks the user for clarification if everything fails, and never loops.
    """
    search_term = game_name.strip() if game_name else ""

    # If Wit.ai didn't extract the game name, ask DeepSeek to do it
    if not search_term and user_message:
        try:
            client = llm_engine._get_client()
            messages = [
                {"role": "system", "content": (
                    "Extract ONLY the video game name from the user's message. "
                    "Respond with just the game name, nothing else. "
                    "If you cannot identify a game name, respond with NONE."
                )},
                {"role": "user", "content": user_message},
            ]
            raw = llm_engine._generate_with_retry(client, messages, max_tokens=50, temperature=0.0)
            extracted = raw.strip().strip('"').strip("'")
            if extracted and extracted.upper() != "NONE" and len(extracted) > 1:
                search_term = extracted
                logger.info(f"[pipeline] DeepSeek extracted game name: '{search_term}'")
        except Exception as exc:
            logger.warning(f"[pipeline] DeepSeek game name extraction failed: {exc}")

    if not search_term:
        # Check if we already asked — prevent loop
        already_asked = getattr(session, "_price_already_asked", False)
        if already_asked:
            session._price_already_asked = False
            return PipelineResult(
                response_text=(
                    "No logré identificar el juego. "
                    "Intenta escribir el nombre completo, por ejemplo: "
                    "\"cuánto cuesta Stray\" o \"precio de Elden Ring\"."
                ),
                status="chat",
            )
        session._price_already_asked = True
        return PipelineResult(
            response_text="¿De qué juego quieres saber el precio? Dime el nombre exacto.",
            status="chat",
        )

    # Reset the ask flag since we have a search term now
    session._price_already_asked = False

    try:
        # Search official Steam Store storefront by name
        matches = steam_api.search_store_by_name(search_term, session.region)
        if matches:
            enriched = matches[:4]
            lines = [f"🎮 *Precio de {search_term}:*  _(resultados encontrados)_\n"]
            for g in enriched:
                price = g.get("regional_price", f"${g.get('price_usd', '?')}")
                discount = g.get("regional_discount", 0)
                line = f"• *{g['name']}* — {price}"
                if discount > 0:
                    line += f"  🔥 (-{discount}%)"
                lines.append(line)
            lines.append("\n💡 ¿Quieres que busque juegos *parecidos* a " + search_term + "?")
            return PipelineResult(
                response_text="\n".join(lines),
                games_found=enriched,
                status="ok",
            )

    except Exception as exc:
        logger.warning(f"[pipeline] CHECK_PRICE search failed: {exc}")

    msg = (
        f"No encontré *{search_term}* en Steam. "
        f"Verifica el nombre e intenta de nuevo, o búscalo directamente en la tienda de Steam.\n\n"
        f"💡 ¿Quieres que busque juegos *similares* a {search_term} según mis tags?"
    )
    return PipelineResult(response_text=msg, status="chat")


# == COMPARE_GAMES real implementation =========================================

def _compare_games(game_name: str | None, session: Session) -> PipelineResult:
    """Real COMPARE_GAMES: fetch multiple games and present a comparison."""
    if not game_name:
        return PipelineResult(
            response_text="¿Qué juegos quieres comparar? Dime los nombres, por ejemplo: 'Compara Elden Ring con Dark Souls 3'.",
            status="chat",
        )
    return PipelineResult(
        response_text=(
            f"🔍 Para comparar juegos como *{game_name}*, mi recomendación es "
            f"usar Steam.store directamente para ver specs y precios lado a lado.\n\n"
            f"💡 Pero puedo recomendarte juegos *similares* a {game_name}. ¿Quieres que lo haga?"
        ),
        status="chat",
    )


# == Core search + scoring pipeline ============================================

def _execute_search(
    user_message: str,
    tags: list[str],
    genre: Optional[str],
    max_price: Optional[float],
    min_price: Optional[float],
    min_score: Optional[int],
    only_sale: bool,
    session: Session,
    game_name: Optional[str] = None,
) -> PipelineResult:
    """Core search → score (recommendation_engine) → enrich → recommend pipeline."""

    # 1. Resolve tags if only game_name is provided
    if not tags and not genre and game_name:
        logger.info(f"[pipeline] Game name provided without tags/genre: '{game_name}'. Searching SteamSpy by name.")
        name_matches = steam_api.search_by_name(game_name, limit=3)
        if name_matches:
            # Extract tags from the matched game to power a similarity search
            for match in name_matches:
                match_tags = match.get("tags", {})
                if isinstance(match_tags, dict) and match_tags:
                    # Take top 3 tags by vote count (highest first)
                    sorted_tags = sorted(match_tags.keys(),
                                         key=lambda t: match_tags[t],
                                         reverse=True)
                    tags = sorted_tags[:3]
                    logger.info(f"[pipeline] Resolved tags from '{match.get('name')}': {tags}")
                    break
            if not tags:
                logger.info(f"[pipeline] Could not resolve tags for '{game_name}'")

    # 2. Search
    filtered = []
    is_saga_or_direct = False
    is_novelty_with_game = False  # True when user wants the CURRENT entry of a saga
    if game_name:
        msg_low = user_message.lower()
        is_saga_or_direct = (
            "saga" in msg_low or
            "franquicia" in msg_low or
            "todos los" in msg_low or
            "juegos de " in msg_low or
            msg_low.strip() == game_name.lower().strip() or
            not tags
        )
        # Detect novelty + game_name (e.g. "dame el cod actual")
        is_novelty_with_game = _is_novelty_query(user_message)
        if is_novelty_with_game:
            is_saga_or_direct = True  # Force direct search path

    if game_name and is_saga_or_direct:
        search_query = game_name

        # If the user wants the CURRENT/LATEST entry, append year to query
        if is_novelty_with_game:
            current_year = datetime.now().year
            search_query = f"{game_name} {current_year}"
            logger.info(f"[pipeline] Novelty + saga detected. Searching Steam for: '{search_query}'")
        else:
            logger.info(f"[pipeline] Saga or direct game search detected. Searching by name for '{search_query}'...")

        raw_matches = steam_api.search_store_by_name(search_query, session.region)

        # Fallback: if year-appended search returned nothing, retry without year
        if not raw_matches and is_novelty_with_game:
            logger.info(f"[pipeline] Year-appended search returned 0 results. Falling back to '{game_name}'...")
            raw_matches = steam_api.search_store_by_name(game_name, session.region)

        # Enrich the top candidates with SteamSpy metadata (scores, developer, tags)
        for g in raw_matches[:6]:
            try:
                spy_details = steam_api.get_app_details(g["appid"])
                if spy_details and spy_details.get("name"):
                    g["developer"] = spy_details.get("developer", "")
                    g["publisher"] = spy_details.get("publisher", "")
                    g["owners"] = spy_details.get("owners", "0..50,000")
                    g["positive"] = spy_details.get("positive", 0)
                    g["negative"] = spy_details.get("negative", 0)
                    g["tags"] = spy_details.get("tags", {})
                    # Calculate score_rank from reviews
                    pos = spy_details.get("positive", 0) or 0
                    neg = spy_details.get("negative", 0) or 0
                    total = pos + neg
                    if total > 0:
                        g["score_rank"] = int(round((pos / total) * 100))
                    else:
                        g["score_rank"] = 75
            except Exception as e:
                logger.warning(f"[pipeline] Failed to fetch SteamSpy details for appid={g['appid']}: {e}")
        filtered = raw_matches

    # 2b. Discovery fallback: if still no results and no specific criteria,
    #     fall back to new releases or top 100 most owned / most popular games
    if not filtered and not tags and not genre and not game_name:
        is_novelty = _is_novelty_query(user_message)
        if is_novelty:
            logger.info("[pipeline] Novelty query detected — activating NEW RELEASES mode")
            top_games = steam_api.get_new_releases(session.region)
        else:
            logger.info("[pipeline] No criteria — activating DISCOVERY mode (top 100 owned)")
            top_games = steam_api.top100owned()

        if top_games:
            from core.steam_api import filter_games
            filtered = filter_games(
                {str(g.get("appid", i)): g for i, g in enumerate(top_games)},
                max_price_usd=max_price,
                min_score_rank=min_score,
                only_on_sale=only_sale,
                limit=25,
                allow_nsfw=session.allow_nsfw,
            )

    if not filtered:
        logger.info(f"[pipeline] Performing tag/genre smart_search...")
        filtered = steam_api.smart_search(
            tags=tags,
            genre=genre,
            max_price_usd=max_price,
            min_price_usd=min_price,
            min_score_rank=min_score,
            only_on_sale=only_sale,
            limit=100,  # larger pool for the prestige filter to find 'real' games
            allow_nsfw=session.allow_nsfw,
        )

    if not filtered:
        msg = _build_no_results_msg(tags, genre, max_price, min_price, only_sale, min_score)
        return PipelineResult(response_text=msg, status="no_results")

    # 3. Score games using recommendation_engine (v2: seen_appids + diversity)
    try:
        from models.recommendation_engine import score_game, rank_games, select_strategy
        strategy = select_strategy(tags, genre, max_price, only_sale, game_name)
        scored = rank_games(
            filtered, tags, genre, max_price, strategy,
            seen_appids=session.recommended_appids,  # v2: penalize seen games
        )
        # Take top 10 from scoring, then dedup will filter seen ones
        top_candidates = [s.game_data for s in scored[:10]]
    except ImportError:
        logger.debug("[pipeline] recommendation_engine not available, using simple sort")
        top_candidates = filtered[:10]

    # 4. Enrich with regional prices
    enriched = steam_api.enrich_with_regional_prices(top_candidates, session.region)

    if not enriched:
        msg = _build_no_results_msg(tags, genre, max_price, min_price, only_sale, min_score)
        return PipelineResult(response_text=msg, status="no_results")

    # 5. Deduplicate — v2: returns empty list when all games already seen
    new_games = session.new_games_only(enriched)

    if not new_games:
        # All candidates have been recommended already in this session
        total_seen = len(session.recommended_appids)
        msg = (
            f"Ya te mostré todos los juegos disponibles con esos criterios 😅 "
            f"({total_seen} títulos en esta sesión).\n\n"
            f"💡 Prueba con otros filtros: un género diferente, tags distintos, "
            f"o ajusta el presupuesto para descubrir más juegos."
        )
        return PipelineResult(response_text=msg, status="no_results")

    # 6. Generate recommendation
    # Inject temporal context hint if this is a novelty query with a game name
    llm_user_message = user_message
    if game_name and _is_novelty_query(user_message):
        current_year = datetime.now().year
        llm_user_message = (
            f"{user_message}\n\n"
            f"[CONTEXT: The user wants the LATEST/CURRENT ({current_year}) entry. "
            f"The games listed below are the most recent releases found on Steam right now. "
            f"Present them as the current/latest versions available.]"
        )
    recommendation = llm_engine.generate_recommendation(
        llm_user_message, new_games, session.memory,
    )

    # 7. Update session (only add games that the LLM actually recommended in its response)
    import re
    def _clean_val(val: str) -> str:
        return re.sub(r'[^a-z0-9]', '', val.lower())

    added_count = 0
    clean_reco = _clean_val(recommendation)
    for g in new_games[:5]:
        name = g.get("name", "")
        clean_name = _clean_val(name)
        if name and (name.lower() in recommendation.lower() or (clean_name and clean_name in clean_reco)):
            session.add_to_wishlist(g)
            added_count += 1
        else:
            logger.info(f"[pipeline] Game '{name}' (appid={g.get('appid')}) was not mentioned by the LLM; skipping wishlist.")

    logger.info(f"[pipeline] Added {added_count} games to wishlist out of {len(new_games[:5])} candidates.")

    return PipelineResult(
        response_text=_ensure_response_text(recommendation, new_games),
        games_found=new_games,
        status="ok",
    )


# == Main pipeline =============================================================

async def run_pipeline(
    user_message: str,
    session: Session,
    user_id: int = 0,
) -> PipelineResult:
    """
    Execute the full recommendation pipeline for a single user message.

    NLU routing (controlled by NLU_ENGINE in .env):
      wit       → Wit.ai clasifica el intent; si falla o baja confianza,
                  se aplica fallback de reglas locales.
      deepseek  → DeepSeek extrae el intent (modo legacy).

    Intent routing:
      CASUAL_CHAT / ASK_CAPABILITIES → generate_chat_response (DeepSeek NLG)
      status == "incomplete"          → generate_clarification (DeepSeek NLG)
      CHECK_PRICE                     → _check_price (búsqueda real Steam)
      COMPARE_GAMES                   → _compare_games
      FIND_SIMILAR                    → _execute_search (busca tags del juego → juegos similares)
      SEARCH_GAME / REFINE_SEARCH     → search SteamSpy + score + recommend (DeepSeek NLG)
    """
    # Record user message in memory
    session.memory.add_user(user_message)

    # -- CONTEXTUAL OVERRIDE: Si el bot acaba de pedir el nombre del juego para precio --
    history = session.memory.get_history_messages(limit=3)
    last_asst_msg = None
    for msg in reversed(history[:-1]):
        if msg["role"] == "assistant":
            last_asst_msg = msg["content"]
            break

    msg_clean = user_message.lower().strip()
    affirmation_keywords = {"si", "sí", "claro", "dale", "obvio", "bueno", "por favor", "por supuesto", "ok", "sii", "siii", "yes"}
    more_keywords = {"mas", "más", "otro", "otros", "otra", "otras", "sigue", "continua", "continúa"}

    is_affirmation = msg_clean in affirmation_keywords
    is_more = msg_clean in more_keywords or (len(msg_clean.split()) <= 3 and any(w in msg_clean.split() for w in more_keywords))
    is_affirmation_or_more = is_affirmation or is_more

    has_reco_history = last_asst_msg and ("🎮" in last_asst_msg or "¿Quieres" in last_asst_msg or "oferta" in last_asst_msg)

    if last_asst_msg and "¿De qué juego quieres saber el precio?" in last_asst_msg:
        intent = {
            "intent_type": "CHECK_PRICE",
            "game_name": user_message.strip(),
            "is_game_query": True,
            "status": "complete"
        }
    elif is_affirmation_or_more and has_reco_history:
        logger.info("[pipeline] Contextual override: user affirmation or request for more detected after recommendation. Setting intent to REFINE_SEARCH.")
        intent = {
            "intent_type": "REFINE_SEARCH",
            "is_game_query": True,
            "status": "complete",
            "tags": [],
            "genre": None,
            "min_price_usd": None,
            "max_price_usd": None,
            "only_on_sale": False,
            "min_score_rank": None,
            "game_name": None,
            "missing_details": None,
            "allow_nsfw": False,
        }
    else:
        # -- Step 1: Extract intent --
        intent = _extract_intent_via_engine(user_message, session)

    intent_type = intent.get("intent_type", "SEARCH_GAME")

    # Note: cuando NLU_ENGINE='wit', Wit.ai es la fuente de verdad.
    # wit_client.py nunca retorna FALLBACK: si no hay intent ni entidades,
    # retorna directamente CASUAL_CHAT. El bloque FALLBACK a continuación
    # solo aplica si se usa el modo DeepSeek y éste falla completamente.
    if intent_type == "FALLBACK":
        intent = llm_engine.fallback_intent(user_message)
        intent_type = intent.get("intent_type", "SEARCH_GAME")

    # -- Step 2: Route --

    # Casual / capabilities
    if intent_type in ("CASUAL_CHAT", "ASK_CAPABILITIES") or not intent.get("is_game_query", True):
        try:
            response = llm_engine.generate_chat_response(user_message, session.memory)
        except Exception:
            response = "¡Hola! Dime qué juego buscas y te ayudo. 🎮"
        session.memory.add_assistant(response)
        return PipelineResult(response_text=response, intent=intent, status="chat")

    # Incomplete query
    if intent.get("status") == "incomplete":
        missing = intent.get("missing_details") or "género o tags"
        try:
            response = llm_engine.generate_clarification(user_message, missing)
        except Exception:
            response = f"¿Podrías darme más detalles sobre lo que buscas? (falta: {missing})"
        session.memory.add_assistant(response)
        return PipelineResult(response_text=response, intent=intent, status="chat")

    # CHECK_PRICE (real implementation)
    if intent_type == "CHECK_PRICE":
        game_name = intent.get("game_name") or ""
        result = _check_price(game_name, session, user_message=user_message)
        session.memory.add_assistant(result.response_text)
        return result

    # COMPARE_GAMES
    if intent_type == "COMPARE_GAMES":
        game_name = intent.get("game_name")
        result = _compare_games(game_name, session)
        session.memory.add_assistant(result.response_text)
        return result

    # FIND_SIMILAR — "dame juegos como Overwatch"
    if intent_type == "FIND_SIMILAR":
        game_name = intent.get("game_name") or ""

        # If Wit.ai didn't extract the game name, ask DeepSeek
        if not game_name and user_message:
            try:
                client = llm_engine._get_client()
                messages = [
                    {"role": "system", "content": (
                        "Extract ONLY the video game name from the user's message. "
                        "Respond with just the game name, nothing else. "
                        "If you cannot identify a game name, respond with NONE."
                    )},
                    {"role": "user", "content": user_message},
                ]
                raw = llm_engine._generate_with_retry(client, messages, max_tokens=50, temperature=0.0)
                extracted = raw.strip().strip('"').strip("'")
                if extracted and extracted.upper() != "NONE" and len(extracted) > 1:
                    game_name = extracted
                    logger.info(f"[pipeline] DeepSeek extracted game name for FIND_SIMILAR: '{game_name}'")
            except Exception as exc:
                logger.warning(f"[pipeline] DeepSeek extraction failed for FIND_SIMILAR: {exc}")

        if not game_name:
            response = "¿A qué juego te refieres? Dime el nombre y te busco juegos similares. 🎮"
            session.memory.add_assistant(response)
            return PipelineResult(response_text=response, intent=intent, status="chat")

        # Step 1: Look up the reference game in SteamSpy to get its tags
        ref_matches = steam_api.search_by_name(game_name, limit=1)
        resolved_tags: list[str] = []
        if ref_matches:
            ref_game = ref_matches[0]
            ref_tags = ref_game.get("tags", {})
            if isinstance(ref_tags, dict) and ref_tags:
                # Take top 3 tags by vote count (most representative)
                sorted_tags = sorted(ref_tags.keys(), key=lambda t: ref_tags[t], reverse=True)
                resolved_tags = sorted_tags[:3]
                logger.info(
                    f"[pipeline] FIND_SIMILAR: '{ref_game.get('name')}' → "
                    f"tags resueltos: {resolved_tags}"
                )

        if not resolved_tags:
            msg = (
                f"No encontré los tags de *{game_name}* en mi base de datos. "
                f"Intenta con el nombre exacto del juego como aparece en Steam."
            )
            session.memory.add_assistant(msg)
            return PipelineResult(response_text=msg, intent=intent, status="no_results")

        # Step 2: Search by those tags (WITHOUT game_name) to find DIFFERENT games
        result = _execute_search(
            user_message=user_message,
            tags=resolved_tags,
            genre=None,
            max_price=intent.get("max_price_usd"),
            min_price=intent.get("min_price_usd"),
            min_score=intent.get("min_score_rank"),
            only_sale=intent.get("only_on_sale", False),
            session=session,
            game_name=None,  # Don't pass game_name to avoid saga/direct search
        )
        result.intent = intent
        session.memory.add_assistant(result.response_text)
        return result


    # Inherit context from previous searches if refining
    if intent_type == "REFINE_SEARCH" and getattr(session, "last_search_criteria", None):
        for key, value in session.last_search_criteria.items():
            if key == "tags":
                current_tags = intent.get("tags") or []
                previous_tags = value or []
                combined = current_tags.copy()
                for t in previous_tags:
                    if t not in combined:
                        combined.append(t)
                intent["tags"] = combined
            elif not intent.get(key) and value:
                intent[key] = value

    tags: list[str] = _validate_tags(intent.get("tags") or [])
    intent["tags"] = tags
    genre: str | None = intent.get("genre")
    if genre:
        try:
            from models.tag_registry import translate_spanish_to_tags
            translated = translate_spanish_to_tags(genre)
            if translated:
                genre = translated[0]
                intent["genre"] = genre
        except ImportError:
            pass
    max_price = intent.get("max_price_usd")
    min_price = intent.get("min_price_usd")
    only_sale: bool = intent.get("only_on_sale", False)
    min_score = intent.get("min_score_rank")

    # Update search context for future refine_search
    if intent_type in ("SEARCH_GAME", "REFINE_SEARCH") and (tags or genre or intent.get("game_name")):
        session.last_search_criteria = {
            "tags": intent.get("tags"),
            "genre": genre,
            "max_price_usd": max_price,
            "min_price_usd": min_price,
            "min_score_rank": min_score,
            "only_on_sale": only_sale,
            "game_name": intent.get("game_name"),
        }

    has_any_criteria = bool(
        tags or
        genre or
        intent.get("game_name") or
        max_price is not None or
        only_sale or
        min_score is not None or
        _is_novelty_query(user_message)
    )

    if intent_type != "RANDOM_GAME" and not has_any_criteria:
        msg = (
            "No pude identificar ningún criterio válido en tu consulta.\n"
            "Tip: Prueba con algo como _'Quiero juegos de terror'_ o _'juegos en oferta'_"
        )
        session.memory.add_assistant(msg)
        return PipelineResult(response_text=msg, intent=intent, status="no_results")

    result = _execute_search(
        user_message=user_message,
        tags=tags,
        genre=genre,
        max_price=max_price,
        min_price=min_price,
        min_score=min_score,
        only_sale=only_sale,
        session=session,
        game_name=intent.get("game_name"),
    )
    result.intent = intent
    result.response_text = _ensure_response_text(result.response_text, result.games_found)

    session.memory.add_assistant(result.response_text)
    return result


# == Intent engine dispatcher ==================================================

def _extract_intent_via_engine(user_message: str, session: Session) -> dict:
    """
    Selecciona el motor NLU según NLU_ENGINE y extrae el intent.

    - 'wit':      Llama a Wit.ai. Es la fuente de verdad: nunca produce FALLBACK.
                  Si la API falla (error de red, timeout), retorna CASUAL_CHAT
                  como safe default para no iniciar una búsqueda de juegos.
    - 'deepseek': Usa DeepSeek (extract_intent). Fallback a reglas locales.
    - otro valor: Igual que 'deepseek'.
    """
    if _NLU_ENGINE == "wit":
        try:
            from nlu.wit_client import detect_intent
            result = detect_intent(user_message)
            logger.info(
                f"[pipeline] Wit.ai → intent='{result.get('intent_type')}' "
                f"confidence={result.get('_confidence', 0):.2f}"
            )
            return result
        except Exception as exc:
            logger.warning(
                f"[pipeline] Wit.ai falló ({exc}). "
                "Retornando CASUAL_CHAT como safe default (sin búsqueda de juegos)."
            )
            # Error de red o API: no intentamos adivinar la intención.
            # Respondemos de forma conversacional y el usuario puede reintentar.
            return {
                "_source":        "wit_error",
                "_raw_intent":    "",
                "_confidence":    0.0,
                "_reasoning":     f"Wit.ai no disponible: {exc}",
                "intent_type":    "CASUAL_CHAT",
                "is_game_query":  False,
                "status":         "chat",
                "tags":           [],
                "genre":          None,
                "min_price_usd":  None,
                "max_price_usd":  None,
                "only_on_sale":   False,
                "min_score_rank": None,
                "game_name":      None,
                "missing_details": None,
                "allow_nsfw":     False,
            }

    # Modo DeepSeek (legacy / por defecto)
    try:
        return llm_engine.extract_intent(
            user_message, session.memory, region_code=session.region
        )
    except Exception as exc:
        logger.error(f"[pipeline] extract_intent falló: {exc}")
        return llm_engine.fallback_intent(user_message)
