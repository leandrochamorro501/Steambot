"""
nlu/wit_client.py
-----------------
Cliente NLU para Wit.ai (Meta).

Wit.ai es un servicio de NLU supervisado que clasifica intenciones y extrae
entidades a partir de texto. Es 100% gratuito, sin límite de peticiones, y
NO es un LLM: solo clasifica la entrada del usuario en categorías definidas
por nosotros y extrae parámetros estructurados.

Rol en la arquitectura:
  Usuario → Wit.ai (clasifica intent + extrae entidades)
           → core/pipeline.py (busca juegos, aplica score)
           → DeepSeek (genera respuesta en lenguaje natural)

API Reference: https://wit.ai/docs/http
Versión de API utilizada: 20240601
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes de API
# ---------------------------------------------------------------------------
_WIT_API_URL = "https://api.wit.ai/message"
_WIT_API_VERSION = "20240601"

# Umbral de confianza: si Wit.ai devuelve un score menor a este valor,
# el pipeline hará fallback a las reglas locales de llm_engine.
_DEFAULT_CONFIDENCE_THRESHOLD = 0.60

# ---------------------------------------------------------------------------
# Mapeo de nombres de intent Wit.ai → formato interno SteamBot
# Los nombres de intent deben coincidir exactamente con los que
# definas en la consola de Wit.ai (https://wit.ai/apps/<APP_ID>/intents).
# ---------------------------------------------------------------------------
_INTENT_MAP: dict[str, str] = {
    "search_game":      "SEARCH_GAME",
    "refine_search":    "REFINE_SEARCH",
    "check_price":      "CHECK_PRICE",
    "compare_games":    "COMPARE_GAMES",
    "find_similar":     "FIND_SIMILAR",
    "casual_chat":      "CASUAL_CHAT",
    "ask_capabilities": "ASK_CAPABILITIES",
    "random_game":      "RANDOM_GAME",
}

# ---------------------------------------------------------------------------
# Entidades del sistema de Wit.ai que usamos directamente
# Wit.ai las detecta automáticamente sin necesidad de crearlas.
# Ref: https://wit.ai/docs/built-in-entities
# ---------------------------------------------------------------------------
_WIT_MONEY_ENTITY = "wit$amount_of_money:amount_of_money"
_WIT_NUMBER_ENTITY = "wit$number:number"


class WitAIError(Exception):
    """Error al comunicarse con la API de Wit.ai."""


def detect_intent(
    message: str,
    token: Optional[str] = None,
    confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
) -> dict:
    """
    Envía un mensaje a Wit.ai y devuelve el intent estructurado en el
    formato interno de SteamBot, listo para ser consumido por pipeline.py.

    Args:
        message: Texto del usuario tal como llega (español o inglés).
        token: Server Access Token de Wit.ai. Si es None, se lee de
               la variable de entorno WIT_AI_TOKEN.
        confidence_threshold: Si la confianza del intent detectado es
               menor a este valor y no hay entidades relevantes, se
               devuelve intent_type="CASUAL_CHAT" (Wit.ai es la
               fuente de verdad — nunca se cae a reglas locales).

    Returns:
        Diccionario con la misma estructura que llm_engine.extract_intent():
        {
            "_source":        "wit",
            "_raw_intent":    str,         # nombre del intent en Wit.ai
            "_confidence":    float,
            "intent_type":    str,         # SEARCH_GAME | REFINE_SEARCH | ...
            "is_game_query":  bool,
            "status":         "complete" | "chat",
            "tags":           list[str],
            "genre":          str | None,
            "min_price_usd":  float | None,
            "max_price_usd":  float | None,
            "only_on_sale":   bool,
            "min_score_rank": int | None,
            "game_name":      str | None,
            "missing_details": None,
            "allow_nsfw":     False,
        }

    Raises:
        WitAIError: Si hay un error de red o la API responde con error.
    """
    api_token = token or os.getenv("WIT_AI_TOKEN", "")
    if not api_token:
        raise WitAIError(
            "WIT_AI_TOKEN no está configurado. "
            "Agrégalo a tu archivo .env o pásalo como parámetro."
        )

    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    params = {"v": _WIT_API_VERSION, "q": message}

    try:
        response = httpx.get(
            _WIT_API_URL,
            headers=headers,
            params=params,
            timeout=5.0,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        raise WitAIError(
            f"Wit.ai respondió con HTTP {exc.response.status_code}: "
            f"{exc.response.text}"
        ) from exc
    except httpx.RequestError as exc:
        raise WitAIError(f"Error de red al llamar a Wit.ai: {exc}") from exc

    # -- Extraer intent principal --------------------------------------------
    intents: list[dict] = data.get("intents", [])

    raw_intent_name = ""
    confidence = 0.0

    if intents:
        top_intent = intents[0]
        raw_intent_name = top_intent.get("name", "")
        confidence = top_intent.get("confidence", 0.0)

    # -- Extraer entidades --------------------------------------------------
    entities: dict = data.get("entities", {})

    tags      = _extract_tags(entities)
    genre     = _extract_genre(entities)
    game_name = _extract_game_name(entities)
    max_price = _extract_max_price(entities)
    min_price = _extract_min_price(entities)
    min_score = _extract_min_score(entities)
    only_sale = _extract_only_sale(entities, message)

    has_game_search_entities = bool(tags or genre or max_price or min_price or min_score or only_sale)
    has_game_name = bool(game_name)
    has_relevant_entities = has_game_search_entities or has_game_name

    if not intents or confidence < confidence_threshold:
        if has_relevant_entities:
            # Wit.ai detectó entidades pero no clasificó el intent.
            # Inferimos el intent más probable según el tipo de entidades:
            inferred_intent = _infer_intent_from_entities(
                message, game_name, has_game_search_entities
            )
            logger.info(
                f"[wit_client] Intent bajo o nulo (confianza {confidence:.2f}), "
                f"pero hay entidades. Infiriendo: {inferred_intent}."
            )
            raw_intent_name = inferred_intent
            confidence = 1.0
        else:
            # Wit.ai no detectó ni intent ni entidades de juego.
            # Antes de asumir CASUAL_CHAT, hacemos un análisis ligero de
            # señales de intención (palabras clave de precio, capacidades,
            # refinamiento). Wit.ai sigue siendo la fuente principal, pero
            # esta capa compensa cuando la entidad game_name no fue detectada.
            inferred = _infer_intent_from_signals(message)
            logger.info(
                f"[wit_client] Sin intent ni entidades (confianza {confidence:.2f}). "
                f"Señal inferida: {inferred}."
            )
            if inferred == "casual_chat":
                return _casual_chat_result()
            raw_intent_name = inferred
            confidence = 0.9

    else:
        logger.info(
            f"[wit_client] Intent detectado: '{raw_intent_name}' "
            f"(confianza: {confidence:.2f})"
        )

    # -- Mapear nombre de intent → formato interno --------------------------
    intent_type = _INTENT_MAP.get(raw_intent_name, "SEARCH_GAME")

    is_game_query = intent_type not in ("CASUAL_CHAT", "ASK_CAPABILITIES")
    status = "chat" if not is_game_query else "complete"

    return {
        "_source":        "wit",
        "_raw_intent":    raw_intent_name,
        "_confidence":    confidence,
        "_reasoning":     f"Wit.ai: '{raw_intent_name}' ({confidence:.2f})",
        "intent_type":    intent_type,
        "is_game_query":  is_game_query,
        "status":         status,
        "tags":           tags,
        "genre":          genre,
        "min_price_usd":  min_price,
        "max_price_usd":  max_price,
        "only_on_sale":   only_sale,
        "min_score_rank": min_score,
        "game_name":      game_name,
        "missing_details": None,
        "allow_nsfw":     False,
    }


# ---------------------------------------------------------------------------
# Helpers de extracción de entidades
# ---------------------------------------------------------------------------

# Palabras clave que sugieren una consulta de precio.
# Sin acentos para mayor cobertura (el usuario puede escribir "cuanto" o "cuanto").
# Usamos tokens completos para evitar falsos positivos.
_PRICE_KEYWORDS = {
    "cuanto cuesta", "cuánto cuesta",
    "cuanto vale",   "cuánto vale",
    "cuanto sale",   "cuánto sale",
    "cuanto esta",   "cuánto está",
    "a cuanto esta", "a cuánto está",
    "precio de",     "el precio",
    "que precio",    "qué precio",
    "costo de",
    "how much",
    "tiene descuento", "en oferta", "esta en oferta", "hay descuento",
}

# Palabras clave que indican REFINAMIENTO de una búsqueda anterior.
# Son deliberadamente específicas para no confundirse con búsquedas nuevas.
_REFINE_KEYWORDS = {
    "mas opciones",  "más opciones",
    "dame mas",      "dame más",
    "muéstrame mas", "muestrame mas",
    "mas juegos",    "más juegos",
    "lo mismo pero", "lo mismo solo",
    "igual pero",
    "ese pero",      "eso pero",
    "algo diferente",
    "no me convence",
    "no me gusto",   "no me gustó",
    "otro estilo",
    "busco algo diferente",
    "prefiero algo",
    "similar pero",  "parecido pero",
    "sigue",         "sigan",
    "continua",      "continúa",
    "otros",
    "dame otros",
    "muestrame otros", "muéstrame otros",
    "quiero otros",
}

# Palabras clave que indican preguntas sobre las capacidades del bot.
_CAPABILITIES_KEYWORDS = {
    "que puedes hacer",  "qué puedes hacer",
    "para que sirves",   "para qué sirves",
    "como funciona",     "cómo funciona",
    "que eres",          "qué eres",
    "como te uso",       "cómo te uso",
    "que haces",         "qué haces",
    "help",
    "ayuda",
    "comandos",
    "instrucciones",
    "capabilities",
    "que tipos de busqueda", "qué tipos de búsqueda",
}

# Palabras clave que indican una búsqueda aleatoria.
_RANDOM_KEYWORDS = {
    "cualquier juego",
    "juego al azar",
    "lo que sea",
    "cualquier cosa",
    "sorprendeme", "sorpréndeme",
    "no se que jugar", "no sé qué jugar",
    "algo para jugar",
}

# Palabras clave que indican novedades, lanzamientos recientes o el año actual.
_NOVELTY_KEYWORDS = {
    "últimos juegos", "ultimos juegos",
    "novedades",
    "estreno", "estrenos",
    "trending",
    "qué se juega ahora", "que se juega ahora",
    "lo mas nuevo", "lo más nuevo",
    "nuevos lanzamientos", "nuevo lanzamiento",
    "recien salidos", "recién salidos",
    "que hayan salido",
    "este año", "este ano",
    "del año", "del ano",
    "este 202", "del 202", "en 202",
    "actuales", "actual",
    "recientes", "más reciente", "mas reciente",
    "salieron hace poco",
    "último", "ultimo",
    "el nuevo", "el de ahora",
    "la nueva entrega", "la última entrega", "la ultima entrega",
}


def _infer_intent_from_entities(
    message: str,
    game_name: Optional[str],
    has_game_search_entities: bool,
) -> str:
    """
    Infiere el intent cuando Wit.ai detectó entidades pero no clasificó el intent.

    Prioridad:
    1. Señales de refinamiento ("lo mismo pero...") + entidades → refine_search
    2. game_name + palabras de precio → check_price
    3. Cualquier entidad de juego → search_game
    """
    msg_lower = message.lower()

    # ¿Es un refinamiento de búsqueda anterior?
    if any(kw in msg_lower for kw in _REFINE_KEYWORDS):
        return "refine_search"

    # ¿Tiene contexto de precio con nombre de juego?
    if game_name and any(kw in msg_lower for kw in _PRICE_KEYWORDS):
        return "check_price"

    # Resto de entidades gaming → búsqueda
    return "search_game"


def _infer_intent_from_signals(message: str) -> str:
    """
    Análisis ligero de señales de intención cuando Wit.ai no detectó
    ni intent ni entidades. Se usa solo como última capa antes de CASUAL_CHAT.

    Prioridad:
    1. Precio ("cuanto cuesta X") → check_price
    2. Capacidades ("que puedes hacer") → ask_capabilities
    3. Refinamiento ("dame mas opciones") → refine_search
    4. Todo lo demás → casual_chat

    IMPORTANTE: Este método usa frases completas (no palabras sueltas) para
    evitar falsos positivos. Ej: "mas" solo NO activa refine_search; sí lo
    hace "dame mas" o "mas opciones".
    """
    msg_lower = message.lower()

    # 1. ¿Pregunta de precio?
    if any(kw in msg_lower for kw in _PRICE_KEYWORDS):
        return "check_price"

    # 2. ¿Pregunta sobre capacidades del bot?
    if any(kw in msg_lower for kw in _CAPABILITIES_KEYWORDS):
        return "ask_capabilities"

    # 3. ¿Refinamiento de búsqueda?
    if any(kw in msg_lower for kw in _REFINE_KEYWORDS):
        return "refine_search"

    # 4. ¿Novedades o lanzamientos recientes?
    if any(kw in msg_lower for kw in _NOVELTY_KEYWORDS):
        return "search_game"

    # 5. ¿Búsqueda aleatoria?
    if any(kw in msg_lower for kw in _RANDOM_KEYWORDS):
        return "random_game"

    # 6. Por defecto: chat conversacional
    return "casual_chat"

def _extract_tags(entities: dict) -> list[str]:
    """Extrae la lista de tags de Steam de la entidad 'tags' de Wit.ai."""
    raw = entities.get("tags:tags", [])
    return [e["value"] for e in raw if e.get("value")]


def _extract_genre(entities: dict) -> Optional[str]:
    """Extrae el género de juego de la entidad 'genre' de Wit.ai."""
    raw = entities.get("genre:genre", [])
    return raw[0]["value"] if raw else None


def _extract_game_name(entities: dict) -> Optional[str]:
    """
    Extrae el nombre de un juego específico de la entidad 'game_name'.
    Se usa para búsquedas de tipo 'parecidos a X' o 'precio de X'.
    """
    raw = entities.get("game_name:game_name", [])
    return raw[0]["value"] if raw else None


def _extract_max_price(entities: dict) -> Optional[float]:
    """
    Extrae el precio máximo. Wit.ai tiene la entidad integrada
    'wit$amount_of_money' que detecta cantidades monetarias.
    Asumimos que la primera cantidad mencionada es el máximo.
    Soporta montos exactos ('value') e intervalos ('to').
    """
    raw = entities.get(_WIT_MONEY_ENTITY, [])
    if raw:
        try:
            item = raw[0]
            if "value" in item:
                return float(item["value"])
            elif item.get("type") == "interval" and "to" in item and "value" in item["to"]:
                return float(item["to"]["value"])
        except (KeyError, ValueError, TypeError):
            pass
    return None


def _extract_min_price(entities: dict) -> Optional[float]:
    """
    Si hay dos montos detectados (ej. 'entre $10 y $20'), el primero
    será el mínimo y el segundo el máximo.
    Soporta montos exactos ('value') e intervalos ('from').
    """
    raw = entities.get(_WIT_MONEY_ENTITY, [])
    if len(raw) >= 2:
        try:
            item = raw[0]
            if "value" in item:
                return float(item["value"])
            elif item.get("type") == "interval" and "from" in item and "value" in item["from"]:
                return float(item["from"]["value"])
        except (KeyError, ValueError, TypeError):
            pass
    elif len(raw) == 1:
        # Check if the single item is a 'from' interval
        item = raw[0]
        if item.get("type") == "interval" and "from" in item and "value" in item["from"]:
            return float(item["from"]["value"])
    return None


def _extract_min_score(entities: dict) -> Optional[int]:
    """
    Extrae un porcentaje de score mínimo. Wit.ai detecta números con la
    entidad integrada 'wit$number'. Ej: 'con al menos 80%'.
    """
    raw = entities.get(_WIT_NUMBER_ENTITY, [])
    if raw:
        try:
            val = int(raw[0]["value"])
            # Solo lo usamos como score si está en rango razonable (1-100)
            if 1 <= val <= 100:
                return val
        except (KeyError, ValueError, TypeError):
            pass
    return None


def _extract_only_sale(entities: dict, message: str) -> bool:
    """
    Detecta si el usuario quiere solo juegos en oferta.
    Wit.ai no tiene una entidad específica para esto, así que usamos
    un simple keyword matching como complemento.
    """
    sale_keywords = {"oferta", "descuento", "sale", "rebaja", "barato", "económico"}
    return any(kw in message.lower() for kw in sale_keywords)


# ---------------------------------------------------------------------------
# Resultado cuando Wit.ai no detecta nada gaming-related
# ---------------------------------------------------------------------------

def _casual_chat_result() -> dict:
    """
    Devuelve CASUAL_CHAT cuando Wit.ai no detecta ni intent ni entidades
    relevantes para juegos.

    Esta función reemplaza el antiguo 'fallback' que devolvía FALLBACK con
    is_game_query=True, lo que provocaba búsquedas de juegos no deseadas
    para frases como 'hola', 'chao', 'gracias', etc.

    Wit.ai es la fuente de verdad: si no ve nada gaming-related,
    el mensaje es conversacional.
    """
    return {
        "_source":         "wit",
        "_raw_intent":     "",
        "_confidence":     0.0,
        "_reasoning":      "Wit.ai: sin intent ni entidades — chat conversacional.",
        "intent_type":     "CASUAL_CHAT",
        "is_game_query":   False,
        "status":          "chat",
        "tags":            [],
        "genre":           None,
        "min_price_usd":   None,
        "max_price_usd":   None,
        "only_on_sale":    False,
        "min_score_rank":  None,
        "game_name":       None,
        "missing_details": None,
        "allow_nsfw":      False,
    }
