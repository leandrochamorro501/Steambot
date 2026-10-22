"""
core/llm_engine.py
------------------
All communication with DeepSeek AI (OpenAI-compatible API).

Roles:
  1. EXTRACTOR -- Parses user intent → structured JSON dict.
  2. REFINER   -- Filtered game list → natural-language recommendation.
  3. CLARIFIER -- Asks for missing info when query is incomplete.
  4. CHAT      -- Casual conversational responses.
  5. MEMORY    -- Per-session conversation context (ConversationMemory).
  6. FALLBACK  -- Rule-based intent classifier when DeepSeek is unavailable.

Model: deepseek-chat (DeepSeek-V3)
API:  https://api.deepseek.com (OpenAI-compatible)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time


import openai
from dotenv import load_dotenv

from models import tag_registry

load_dotenv()

logger = logging.getLogger(__name__)

# -- Credentials ---------------------------------------------------------------
_API_KEY   = os.getenv("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_APIKEY", ""))
_BASE_URL  = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_MODEL_ID  = os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat")

_RETRY_DELAY = 2.0
_RETRY_MAX   = 3

# Summarization: use shorter model call to compress history
_SUMMARIZE_MODEL_TEMPERATURE = 0.3
_SUMMARIZE_MAX_TOKENS = 200


# == Conversation Memory (with summarization) ====================================

class ConversationMemory:
    """
    Stores the last N conversation turns + a running summary for context.
    Uses LLM summarization for long history instead of aggressive truncation.
    Provides get_summary() that returns full summarized context.
    """

    def __init__(self, max_turns: int = 10) -> None:
        self.max_turns = max_turns
        self._history: list[dict[str, str]] = []
        self._summary: str = ""  # Running summary of older turns

    def add_user(self, message: str) -> None:
        self._history.append({"role": "user", "content": message})
        self._trim()

    def add_assistant(self, message: str) -> None:
        self._history.append({"role": "assistant", "content": message})
        self._trim()

    def _trim(self) -> None:
        max_entries = self.max_turns * 2
        if len(self._history) > max_entries:
            # Summarize the oldest turn before dropping it
            self._summarize_oldest()
            self._history = self._history[-max_entries:]

    def _summarize_oldest(self) -> None:
        """Uses a lightweight summarization of the oldest turns."""
        if len(self._history) < 4:
            return
        old_pair = self._history[:2]
        user_msg = old_pair[0]["content"][:200]
        asst_msg = old_pair[1]["content"][:200]
        self._summary += (
            f"Earlier: usuario preguntó '{user_msg}' y el bot respondió '{asst_msg}'\n"
        )

    def get_history_messages(self, limit: int = 6) -> list[dict[str, str]]:
        """
        Return conversation history as OpenAI-compatible message dicts.
        Includes summary as a system message if available.
        """
        messages: list[dict[str, str]] = []
        if self._summary:
            messages.append({
                "role": "system",
                "content": f"[Conversation summary]\n{self._summary.strip()}",
            })
        for msg in self._history[-limit:]:
            messages.append(dict(msg))
        return messages

    def get_summary(self) -> str:
        """Return full context: summary + last 3 turns with generous limit."""
        lines = []
        if self._summary:
            lines.append(f"Resumen: {self._summary.strip()}")
        for msg in self._history[-6:]:
            prefix = "Usuario" if msg["role"] == "user" else "Bot"
            lines.append(f"{prefix}: {msg['content'][:400]}")
        return "\n".join(lines)

    def clear(self) -> None:
        self._history.clear()
        self._summary = ""


# Global memory instance (used by main.py terminal interface)
memory = ConversationMemory()


# == Rule-based intent fallback =================================================

# Spanish keywords to intent mapping
_FALLBACK_PATTERNS = [
    # (regex, intent_type, extra mapping)
    (r"\bhola\b|\bbuenos\s*d[ií]as\b|\bbuenas\b", "CASUAL_CHAT", {}),
    (r"\bgracias\b|\bad[ií]os\b|hasta\s*luego", "CASUAL_CHAT", {}),
    (r"\bqu[ée]\s*puedes\s*hacer\b|\bayuda\b|\bcomandos\b", "ASK_CAPABILITIES", {}),
    (r"\bprecio\b.*\bde\b|\bcu[aá]nto\s*cuesta\b", "CHECK_PRICE", {}),
    (r"\bcompar[ae]\b.*\bcon\b|\bdiferencias?\b.*\by\b", "COMPARE_GAMES", {}),
    (r"\bbarato\b|\becon[oó]mico\b|\bofertas?\b|\bdescuento\b", "SEARCH_GAME", {"only_on_sale": True}),
    (r"\bterror\b|\bmiedo\b|\bhorror\b", "SEARCH_GAME", {"tags": ["Horror"]}),
    (r"\bsupervivencia\b|\bsurvival\b", "SEARCH_GAME", {"tags": ["Survival"]}),
    (r"\baventura\b|\bexplora", "SEARCH_GAME", {"tags": ["Adventure"]}),
    (r"\bsimula", "SEARCH_GAME", {"tags": ["Simulation"]}),
    (r"\bpuzzle\b|\brompecabezas\b", "SEARCH_GAME", {"tags": ["Puzzle"]}),
    (r"\brpg\b|\brol\b", "SEARCH_GAME", {"tags": ["RPG"]}),
    (r"\bacci[oó]n\b|\bdisparo|\bshooter\b", "SEARCH_GAME", {"tags": ["Action"]}),
    (r"\bestrategia\b|\bturnos\b", "SEARCH_GAME", {"tags": ["Strategy"]}),
    (r"\bmultijugador\b|\bcoop\b|\bco-op\b|\bamigos\b", "SEARCH_GAME", {"tags": ["Multiplayer"]}),
    (r"\bmundo\s*abierto\b", "SEARCH_GAME", {"tags": ["Open World"]}),
    (r"\bpixel\s*art\b|\bretro\b", "SEARCH_GAME", {"tags": ["Pixel Graphics"]}),
    (r"\banim[ée]\b", "SEARCH_GAME", {"tags": ["Anime"]}),
    (r"\bdeportes\b|\bsports\b", "SEARCH_GAME", {"tags": ["Sports"]}),
    (r"\bcarreras\b|\bracing\b", "SEARCH_GAME", {"tags": ["Racing"]}),
    (r"\bgratis\b|\bfree\b", "SEARCH_GAME", {"max_price_usd": 0}),
]


def fallback_intent(user_message: str) -> dict:
    """
    Rule-based intent extraction when DeepSeek is unavailable.
    Uses keyword matching against common Spanish gaming phrases.
    """
    base = {
        "_reasoning": "Fallback rule-based classifier (DeepSeek unavailable).",
        "intent_type": "SEARCH_GAME",
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
    }

    msg_lower = user_message.lower().strip()

    # Extract game name for CHECK_PRICE or SIMILARITY
    price_match = re.search(
        r"(?:precio\s+(?:de\s+)?|cu[aá]nto\s+cuesta\s+)([A-Za-z0-9\s:.'\-]+)",
        user_message, re.IGNORECASE,
    )
    if price_match:
        base["intent_type"] = "CHECK_PRICE"
        base["game_name"] = price_match.group(1).strip()
        base["_reasoning"] = "Fallback: price query detected"
        return base

    similarity_match = re.search(
        r"(?:parecidos?\s+a|similares?\s+a|iguales?\s+a|como)\s+([A-Za-z0-9\s:.'\-]+)",
        user_message, re.IGNORECASE,
    )
    if similarity_match:
        base["intent_type"] = "SEARCH_GAME"
        base["game_name"] = similarity_match.group(1).strip()
        base["_reasoning"] = "Fallback: similarity query detected"
        return base

    for pattern, intent_type, extras in _FALLBACK_PATTERNS:
        if re.search(pattern, msg_lower, re.IGNORECASE):
            base["intent_type"] = intent_type
            base.update(extras)
            base["is_game_query"] = intent_type not in ("CASUAL_CHAT", "ASK_CAPABILITIES")
            base["_reasoning"] = f"Fallback: matched pattern '{pattern}'"
            return base

    # Default: treat as SEARCH_GAME with whatever we could extract
    base["_reasoning"] = "Fallback: no specific pattern, defaulting to SEARCH_GAME"
    return base


# == DeepSeek client factory ====================================================

def _get_client() -> openai.OpenAI:
    """Create an OpenAI client pointing to DeepSeek's API."""
    return openai.OpenAI(
        api_key=_API_KEY,
        base_url=_BASE_URL,
    )


def _generate_with_retry(
    client: openai.OpenAI,
    messages: list[dict[str, str]],
    max_tokens: int = 512,
    temperature: float = 0.1,
    disable_thinking: bool = False,
) -> str:
    """
    Send a chat completion request to DeepSeek with retry logic.
    Raises if all retries are exhausted.
    """
    last_error: Exception | None = None

    for attempt in range(1, _RETRY_MAX + 1):
        try:
            extra_body = None
            if disable_thinking:
                extra_body = {"thinking": {"type": "disabled"}}

            response = client.chat.completions.create(
                model=_MODEL_ID,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=temperature,
                extra_body=extra_body,
            )
            choice = response.choices[0]
            content = choice.message.content

            # === DEBUG: Log finish_reason and token usage ===
            finish_reason = choice.finish_reason
            usage = response.usage
            reasoning_tokens = 0
            if usage and hasattr(usage, 'completion_tokens_details') and usage.completion_tokens_details:
                reasoning_tokens = getattr(usage.completion_tokens_details, 'reasoning_tokens', 0) or 0

            prompt_tk = usage.prompt_tokens if usage else "?"
            comp_tk = usage.completion_tokens if usage else "?"
            total_tk = usage.total_tokens if usage else "?"

            print(f"[llm_debug] finish_reason={finish_reason} | prompt={prompt_tk} comp={comp_tk} total={total_tk} reasoning={reasoning_tokens} | max_tokens={max_tokens}")

            if finish_reason == "length":
                logger.warning(
                    f"[llm_engine] TRUNCATED! finish_reason='length'. "
                    f"completion_tokens={comp_tk}, reasoning_tokens={reasoning_tokens}, max_tokens={max_tokens}. "
                    f"Response may be incomplete."
                )
                print(f"[llm_debug] *** TRUNCATED! The model hit max_tokens={max_tokens} ***")
            # === END DEBUG ===

            if not content or not content.strip():
                raise ValueError("DeepSeek returned empty content")
            return content
        except openai.RateLimitError as exc:
            last_error = exc
            if attempt < _RETRY_MAX:
                wait = _RETRY_DELAY * attempt
                logger.warning(
                    f"[llm_engine] Rate limit hit (attempt {attempt}). "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                raise
        except openai.AuthenticationError as exc:
            logger.error(f"[llm_engine] Authentication failed: {exc}")
            raise
        except openai.APIError as exc:
            last_error = exc
            err_str = str(exc).lower()
            is_retryable = any(
                kw in err_str
                for kw in ("rate limit", "too many requests", "busy", "429", "503", "server error", "overloaded")
            )
            if is_retryable and attempt < _RETRY_MAX:
                wait = _RETRY_DELAY * attempt
                logger.warning(
                    f"[llm_engine] Transient API error (attempt {attempt}): {exc}. "
                    f"Retrying in {wait}s..."
                )
                time.sleep(wait)
            else:
                raise

    # Should only reach here if all retries exhausted without raising
    raise last_error or RuntimeError("Unexpected: all retries exhausted")


# == DeepSeek prompt templates ==================================================

def _build_extractor_system() -> str:
    allowed = ", ".join(f'"{t}"' for t in tag_registry.ALL_TAGS)
    return f"""You are the Brain of SteamBot. Your ONLY job is to parse user intent into JSON.

SteamBot recognizes 6 intent types:
  - SEARCH_GAME: User wants game recommendations with criteria
  - REFINE_SEARCH: User wants to adjust a previous search
  - CHECK_PRICE: User asks for the price of a specific game
  - COMPARE_GAMES: User wants to compare two or more games
  - CASUAL_CHAT: Greetings, thanks, small-talk
  - ASK_CAPABILITIES: User asks what the bot can do

CRITICAL RULES:
1. Return ONLY a valid JSON object. No prose, no markdown fences.
2. If the user query is too vague (e.g., "Quiero un juego"), set "status": "incomplete".
3. Use EXACT canonical tags (SteamSpy compatible) only from: {allowed}
4. Map Spanish terms to English tags:
   terror/miedo → "Horror" or "Psychological Horror"
   mundo abierto → "Open World"
   carreras/autos/conducir → "Racing"
   construcción/construir → "Building" or "Base-Building"
   multijugador/online/con amigos → "Multiplayer" or "Co-op"
   disparos/shooter → "Shooter" or "FPS"
   acción → "Action"
   pixel art/retro → "Pixel Graphics" or "Retro"
   ciencia ficción/futurista → "Sci-fi"
   fantasía/dragones → "Fantasy" or "Medieval"
   zombies/supervivencia → "Zombies" or "Survival"
   plataformas → "Platformer"
   sigilo → "Stealth"
   dificil/dark souls/souls-like → "Difficult" or "Dark Fantasy"
   aventura/explorar → "Adventure" or "Exploration"
   rol/rpg → "RPG"
   estrategia → "Strategy" or "Turn-Based"
   construir/crafting → "Crafting" or "Building" or "Sandbox"
   anime/japonés → "Anime" or "JRPG"
   historia/narrativa → "Story Rich"
   gratis → set max_price_usd=0
   carreras/autos → "Racing"
   roguelike → "Rogue-like" or "Rogue-lite"
   puzle → "Puzzle"
   simulación → "Simulation"
   battle royale/battle royal → "Battle Royale"
   If the user requests a minimum price or a price range (e.g., "entre 5 mil y 15 mil", "mínimo 5000", "más de 8 lucas"), convert both limits to USD and set BOTH "min_price_usd" and "max_price_usd".
5. Genres must be exactly one of: "Action","RPG","Strategy","Indie","Adventure","Simulation","Racing","Sports","Casual","Free to Play","Early Access".
6. Start JSON with "_reasoning" field explaining your mapping.
7. REFINE_SEARCH: copy tags/genre from history, only update what changed.
8. Max 3 tags. Prefer the most specific match.
9. NEVER set tags "NSFW", "Sexual Content", or "Nudity" unless the user EXPLICITLY asks for adult/sexual content with words like "+18", "NSFW", "contenido sexual", "desnudos". If they do, set "allow_nsfw": true.
10. DIVERSITY & FUZZY MATCHING: If a user misspells a tag or uses a synonym (e.g., "shoter", "estrtegia"), map it to the closest valid tag silently without correcting them.
11. CATEGORY/STYLE REQUESTS: If the user asks for a specific genre, category, or style (e.g., "quiero un juego de carreras", "juego estilo metroidvania", "juego de tiros"), DO NOT mark as incomplete. Set "intent_type": "SEARCH_GAME" and map the style to the closest exact tags or genre.
12. SIMILARITY ("Like Game X"): If the user asks for games similar to a popular game (e.g., "juegos parecidos a X") where X is a specific game (e.g. Skyrim, Minecraft, etc), set "intent_type": "SEARCH_GAME", set "game_name" to the extracted name of X, AND infer 2-3 canonical tags that best describe that game (e.g., ["Open World", "RPG", "Fantasy"]). The system uses SteamSpy for all game searches.

JSON STRUCTURE:
{{"_reasoning":"...","intent_type":"SEARCH_GAME|REFINE_SEARCH|CHECK_PRICE|COMPARE_GAMES|CASUAL_CHAT|ASK_CAPABILITIES","is_game_query":bool,"status":"complete|incomplete|chat","tags":[],"genre":null,"min_price_usd":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null}}

EXAMPLES:
User: "Recomiendame juegos de terror" -> {{"_reasoning":"terror->Horror","intent_type":"SEARCH_GAME","is_game_query":true,"status":"complete","tags":["Horror"],"genre":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null,"allow_nsfw":false}}
User: "juegos parecidos a Minecraft" -> {{"_reasoning":"like Minecraft->Sandbox/Building/Survival","intent_type":"SEARCH_GAME","is_game_query":true,"status":"complete","tags":["Sandbox","Building","Survival"],"genre":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":"Minecraft","missing_details":null,"allow_nsfw":false}}
User: "quiero un juego de supervivencia" -> {{"_reasoning":"supervivencia->Survival","intent_type":"SEARCH_GAME","is_game_query":true,"status":"complete","tags":["Survival"],"genre":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null,"allow_nsfw":false}}
User: "Busco juegos de miedo en el espacio" -> {{"_reasoning":"miedo->Horror, espacio->Space","intent_type":"SEARCH_GAME","is_game_query":true,"status":"complete","tags":["Horror","Space"],"genre":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null,"allow_nsfw":false}}
User: "quiero un juego de carreras" -> {{"_reasoning":"carreras->Racing category","intent_type":"SEARCH_GAME","is_game_query":true,"status":"complete","tags":[],"genre":"Racing","max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null,"allow_nsfw":false}}
User: "quiero un juego de accion y estrategia" -> {{"_reasoning":"accion->Action, estrategia->Strategy","intent_type":"SEARCH_GAME","is_game_query":true,"status":"complete","tags":["Action", "Strategy"],"genre":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null,"allow_nsfw":false}}
User: "Mejor que sea mas barato" -> {{"_reasoning":"refine previous, lower price","intent_type":"REFINE_SEARCH","is_game_query":true,"status":"complete","tags":["Horror"],"genre":null,"max_price_usd":15.0,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null,"allow_nsfw":false}}
User: "Hola" -> {{"_reasoning":"greeting","intent_type":"CASUAL_CHAT","is_game_query":false,"status":"chat","tags":[],"genre":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null,"allow_nsfw":false}}
User: "Quiero juegos para adultos +18" -> {{"_reasoning":"explicit adult request","intent_type":"SEARCH_GAME","is_game_query":true,"status":"complete","tags":["Mature"],"genre":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":null,"missing_details":null,"allow_nsfw":true}}
User: "algo como Stardew Valley pero con shoters" -> {{"_reasoning":"like Stardew Valley->Farming Sim/Pixel Graphics, shoters->Shooter (fuzzy match)","intent_type":"SEARCH_GAME","is_game_query":true,"status":"complete","tags":["Farming Sim","Pixel Graphics","Shooter"],"genre":null,"max_price_usd":null,"only_on_sale":false,"min_score_rank":null,"game_name":"Stardew Valley","missing_details":null,"allow_nsfw":false}}
"""


EXTRACTOR_SYSTEM = _build_extractor_system()

CLARIFIER_SYSTEM = """You are SteamBot's Assistant. The user wants a recommendation but hasn't given enough details.
Ask for the missing information (genre, budget, or vibes/tags) in a friendly, gamer-focused way.

RULES:
- Be brief (max 2 sentences).
- Use gaming slang (level up, quest, loot, etc.).
- Suggest 3 example genres or tags to help them decide.
- Match the user's language (English or Spanish).
"""

REFINER_SYSTEM = """You are SteamBot, a passionate game curator who recommends games like a trusted gamer friend.
Your mission: make the user excited about the games you found for them.

RULES:
- Language: Respond in the SAME language the user used.
- STRICT RECOMMENDATION RULE: You MUST ONLY recommend games that are explicitly listed in the "Games found" list. NEVER make up, invent, or recommend any games that are not present in the "Games found" list under any circumstances, even if they belong to the same saga or genre!
- Mention 3-5 games maximum. Choose the best ones — quality over quantity.
- For EACH game use this format:
    🎮 **Game Name** (Price)
    > One sentence explaining why it matches what the user asked for.
    > If on sale: 🔥 **¡EN OFERTA! (-X%)**
- DO NOT show, print, or mention any score, rating percentage, or stars (e.g. do NOT include "⭐ X%" or "Score") under any circumstances.
- PRICE ACCURACY: Use the EXACT price string provided in the "Games found" list. Do NOT round, modify, or assume a different price even if it looks unusual. If the price is "CLP$ 5.075", write "CLP$ 5.075".
- ALWAYS use regional_price if available in the data — never show USD if a local price exists.
- If a price shows '~' or '(est.)' it means the price is an ESTIMATE and may not be accurate. In that case, add a note saying "precio estimado, verifica en Steam" next to that game's price.
- CRITICAL: NEVER mention, recommend, or include games that are adult/sexual content.
- IMMERSION RULE: NEVER mention "la lista", "los juegos que encontré", or refer to the search process or internal data. Present the recommendations naturally as if you personally thought of them in the moment.
- CURRENT/LATEST GAMES: If the user asks for "current", "latest", "new", or "this year's" version of a game or saga, the games in the "Games found" list ARE the most recent entries available on Steam right now. Present them confidently as the latest releases. NEVER say you don't have up-to-date information — the data you received IS current.
- Total response < 300 words.
- End with a fun gamer sign-off line.
"""

CHAT_SYSTEM = """You are SteamBot, a Steam game assistant with the personality of a veteran gamer.
You speak with gamer slang but don't overdo it. Warm, helpful, occasionally sarcastic.
Respond in the SAME language the user used (Spanish or English). Keep it short (1-3 sentences).

WHAT YOU CAN DO:
- Recommend games by genre, tags, price, discounts
- Find games similar to ones the user mentions
- Show regional prices in the user's local currency

Every 3-4 messages, remind the user they can ask for game recommendations.
Never break character or reveal you are an AI language model."""


# == JSON extraction ===========================================================

def _extract_first_json(text: str) -> dict:
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON found in model response: {text!r}")

    depth = 0
    in_string = False
    escape_next = False

    for i in range(start, len(text)):
        ch = text[i]
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])

    raise ValueError(f"Unbalanced braces in model response: {text!r}")


# == Public API ================================================================

_INTENT_FALLBACK = {
    "_reasoning": "Fallback used due to parsing error.",
    "intent_type": "SEARCH_GAME",
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
}


def extract_intent(user_message: str, user_memory: ConversationMemory, region_code: str = "US") -> dict:
    """
    Extract structured intent from a user message using DeepSeek.
    Includes regional context to help the LLM with currency conversion.
    """
    from core.steam_api import REGIONS
    client = _get_client()

    # Get regional context for better price conversion (e.g. CLP vs COP)
    reg_info = REGIONS.get(region_code, REGIONS["US"])
    currency = reg_info["currency"]

    # Rough exchange rates to help the LLM convert to USD
    rates = {
        "CLP": 950, "COP": 4000, "ARS": 900, "MXN": 18,
        "BRL": 5, "EUR": 0.9, "GBP": 0.8
    }
    rate_hint = f" (Roughly 1 USD = {rates[currency]} {currency})" if currency in rates else ""

    regional_context = (
        f"IMPORTANT: User is in {reg_info['label']}. "
        f"If they mention a price in {currency}, convert it to USD{rate_hint} "
        f"before setting 'max_price_usd' and/or 'min_price_usd'."
    )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": EXTRACTOR_SYSTEM},
        {"role": "system", "content": regional_context},
    ]

    # Include conversation history for context (REFINE_SEARCH, etc.)
    # v2: Filter history to avoid confusing the LLM with previous long recommendations.
    # We truncate assistant prose so the model doesn't try to imitate it during extraction.
    history_msgs = user_memory.get_history_messages(limit=4)
    for msg in history_msgs:
        if msg["role"] == "assistant" and len(msg["content"]) > 100:
            msg["content"] = msg["content"][:100] + " (truncated recommendations)..."
    messages.extend(history_msgs)

    messages.append({"role": "user", "content": user_message})
    messages.append({"role": "system", "content": "IMPORTANT: Respond ONLY with a JSON object starting with '{'. No prose."})

    try:
        raw = _generate_with_retry(client, messages, max_tokens=512, temperature=0.1, disable_thinking=True)
        intent = _extract_first_json(raw)
        return {**_INTENT_FALLBACK, **intent}
    except openai.AuthenticationError:
        logger.error("[llm_engine] DeepSeek authentication failed. Check DEEPSEEK_APIKEY in .env")
        return fallback_intent(user_message)
    except openai.APIError as exc:
        logger.warning(f"[llm_engine] DeepSeek API error: {exc}. Falling back to rule-based.")
        return fallback_intent(user_message)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning(f"[llm_engine] JSON parse failed: {exc}. Falling back to rule-based.")
        return fallback_intent(user_message)
    except Exception as exc:
        logger.warning(f"[llm_engine] Unexpected error: {exc}. Falling back to rule-based.")
        return fallback_intent(user_message)


def generate_chat_response(user_message: str, user_memory: ConversationMemory) -> str:
    """Generate a casual chat response using DeepSeek."""
    try:
        client = _get_client()

        messages: list[dict[str, str]] = [
            {"role": "system", "content": CHAT_SYSTEM},
        ]
        history_msgs = user_memory.get_history_messages(limit=8)
        messages.extend(history_msgs)
        messages.append({"role": "user", "content": user_message})

        content = _generate_with_retry(client, messages, max_tokens=256, temperature=0.5, disable_thinking=True).strip()
        if not content:
            raise ValueError("Empty response from DeepSeek API")
        return content
    except Exception as exc:
        logger.warning(f"[llm_engine] generate_chat_response error: {exc}")
        return (
            "¡Hola! Soy SteamBot, tu asistente de juegos de Steam. "
            "Dime qué tipo de juego buscas y te ayudo a encontrarlo. 🎮"
        )


def generate_clarification(user_message: str, missing_details: str) -> str:
    """Ask the user for missing info when their query is incomplete."""
    try:
        client = _get_client()

        messages: list[dict[str, str]] = [
            {"role": "system", "content": CLARIFIER_SYSTEM},
            {"role": "user", "content": (
                f"User message: {user_message}\n"
                f"Missing details needed: {missing_details}"
            )},
        ]

        content = _generate_with_retry(client, messages, max_tokens=150, temperature=0.4, disable_thinking=True).strip()
        if not content:
            raise ValueError("Empty response from DeepSeek API")
        return content
    except Exception as exc:
        logger.warning(f"[llm_engine] generate_clarification error: {exc}")
        return (
            f"Para darte una mejor recomendación, ¿podrías darme un poco más de detalle "
            f"sobre lo que buscas? (falta: {missing_details})"
        )


def _is_response_complete(text: str) -> bool:
    """Check if a response appears to be complete (not truncated mid-sentence).

    A complete response typically ends with punctuation, an emoji, or a newline.
    A truncated response ends mid-word or mid-sentence.
    """
    if not text or not text.strip():
        return False
    stripped = text.strip()
    # Check for common ending characters
    ending_chars = {'.', '!', '?', ')', ']', '\n', '"', "'"}
    last_char = stripped[-1]
    # Emoji detection: most emoji are in ranges above U+2000
    is_emoji = ord(last_char) > 0x2000
    return last_char in ending_chars or is_emoji


def _append_graceful_closing(text: str) -> str:
    """If the response was truncated mid-sentence, append a graceful closing."""
    if _is_response_complete(text):
        return text
    # The response was cut mid-sentence — close it gracefully
    logger.warning("[llm_engine] Response appears truncated. Appending graceful closing.")
    return text.rstrip() + "...\n\n¡Pregúntame si quieres más detalles sobre alguno! 🎮"


def generate_recommendation(
    user_message: str,
    games: list[dict],
    user_memory: ConversationMemory,
) -> str:
    """Generate a natural-language recommendation from a list of games."""
    if not games:
        return (
            "No encontré juegos que coincidan con tus criterios. "
            "Intenta con una búsqueda más amplia o sin filtro de precio."
        )

    def _price_str(g: dict) -> str:
        if g.get("regional_price"):
            return g["regional_price"]
        return f"${g.get('price_usd', 0.0)} USD"

    games_summary = "\n".join(
        f"- {g['name']} | EXACT_PRICE: {_price_str(g)}"
        + (f" | Discount: {g.get('regional_discount', 0)}%" if g.get("regional_discount", 0) > 0 else "")
        + (f" | Score: {g.get('score_rank')}%" if g.get("score_rank") else "")
        + (f" | Tags: {', '.join(list(g.get('tags', {}).keys())[:4])}" if g.get("tags") else "")
        + (f" | ⚠️ PRICE IS ESTIMATE" if g.get("price_source") == "estimate" else "")
        for g in games[:5]
    )

    # Add warning if any prices are estimates
    has_estimates = any(g.get("price_source") == "estimate" for g in games[:5])
    price_note = ""
    if has_estimates:
        price_note = (
            "\n\nIMPORTANT: Some prices marked with ⚠️ are ESTIMATES converted from USD. "
            "Tell the user to verify on Steam for accurate regional pricing. "
            "Show estimated prices with '~' prefix."
        )

    user_content = f"{user_message}\n\nGames found:\n{games_summary}{price_note}"

    try:
        client = _get_client()

        # --- Attempt 1: full history, generous token budget ---
        messages: list[dict[str, str]] = [
            {"role": "system", "content": REFINER_SYSTEM},
        ]
        # Limit history to 4 messages to leave more token budget for the response
        history_msgs = user_memory.get_history_messages(limit=4)
        messages.extend(history_msgs)
        messages.append({"role": "user", "content": user_content})

        content = _generate_with_retry(
            client, messages, max_tokens=8192, temperature=0.4, disable_thinking=True
        ).strip()

        if content and _is_response_complete(content):
            return content

        # --- Attempt 2: if truncated, retry with minimal history + brevity instruction ---
        if content and not _is_response_complete(content):
            print(f"[llm_debug] Response truncated ({len(content)} chars). Retrying with minimal prompt...")
            messages_retry: list[dict[str, str]] = [
                {"role": "system", "content": REFINER_SYSTEM + "\n\nIMPORTANT: Keep your response CONCISE. Max 200 words. Finish every sentence you start."},
            ]
            messages_retry.append({"role": "user", "content": user_content})

            content_retry = _generate_with_retry(
                client, messages_retry, max_tokens=8192, temperature=0.4, disable_thinking=True
            ).strip()

            if content_retry and _is_response_complete(content_retry):
                return content_retry
            # If still truncated, use whichever is longer and close gracefully
            best = content_retry if len(content_retry or "") > len(content or "") else content
            return _append_graceful_closing(best or content)

        if not content:
            raise ValueError("Empty response from DeepSeek API")
        return _append_graceful_closing(content)
    except Exception as exc:
        logger.warning(f"[llm_engine] generate_recommendation error: {exc}")
        lines = ["Aquí algunos juegos que encontré:\n"]
        for g in games[:5]:
            price = g.get("regional_price", f"${g['price_usd']} USD")
            if not g.get("regional_price") and g.get("discount", 0) > 0:
                price += f" (-{g['discount']}%)"
            lines.append(f"  * {g['name']} — {price}")
        return "\n".join(lines)
