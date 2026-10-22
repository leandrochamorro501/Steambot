"""
recommendation_engine.py
------------------------
Recommendation Decision Matrix — Formal specification of game types,
characteristics, recommendation strategies, and user variables considered
by SteamBot when generating recommendations.

v2: Rebalanced weights (quality over price), diversity jitter, seen-game penalty.
"""

import random
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ============================================================================
# 1. GAME TYPES — Classification of games the system can recommend
# ============================================================================

class GameType(Enum):
    """
    Taxonomía de tipos de videojuegos que SteamBot puede recomendar.

    Cada tipo define:
      - genres_asociados: Géneros SteamSpy típicos para este tipo de juego
      - tags_asociados: Tags SteamSpy frecuentes
      - ejemplos: Títulos representativos usados como referencia
      - descripcion: Caracterización para el LLM
    """

    AAA = {
        "genres_asociados": ["Action", "RPG", "Adventure"],
        "tags_asociados": ["Open World", "Multiplayer", "Shooter"],
        "ejemplos": ["Elden Ring", "Cyberpunk 2077", "The Witcher 3"],
        "descripcion": (
            "Juegos de alto presupuesto con valores de producción elevados: "
            "gráficos avanzados, mundos extensos, actuación de voz profesional. "
            "Precio típico: $40-70 USD. Publicados por grandes editoras."
        ),
    }

    INDIE = {
        "genres_asociados": ["Indie", "Adventure", "Action"],
        "tags_asociados": ["Pixel Graphics", "Roguelike", "Roguelite", "Retro"],
        "ejemplos": ["Stardew Valley", "Hades", "Hollow Knight", "Celeste"],
        "descripcion": (
            "Juegos desarrollados por estudios pequeños o individuos, con "
            "presupuestos limitados pero alta creatividad. Precio típico: "
            "$5-25 USD. Enfoque en mecánicas innovadoras o narrativa única."
        ),
    }

    MULTIPLAYER = {
        "genres_asociados": ["Action", "Sports", "Strategy"],
        "tags_asociados": ["Multiplayer", "Cooperative", "FPS"],
        "ejemplos": ["Among Us", "Valheim", "Phasmophobia", "Brawlhalla"],
        "descripcion": (
            "Juegos diseñados para jugarse con otras personas, ya sea en "
            "cooperativo o competitivo. Precio variable. Factor social clave."
        ),
    }

    FREEMIUM = {
        "genres_asociados": ["Free to Play", "Action", "Strategy"],
        "tags_asociados": ["Multiplayer", "Shooter", "Sports"],
        "ejemplos": ["Dota 2", "CS2", "Apex Legends", "Warframe"],
        "descripcion": (
            "Juegos gratuitos con microtransacciones opcionales. Precio base: "
            "$0.00 USD. Monetización vía pases de batalla, cosméticos o DLC."
        ),
    }

    EARLY_ACCESS = {
        "genres_asociados": ["Early Access", "Indie", "Survival"],
        "tags_asociados": ["Survival", "Open World", "Sandbox"],
        "ejemplos": ["Valheim", "Palworld", "Hades 2", "Enshrouded"],
        "descripcion": (
            "Juegos en desarrollo activo, disponibles antes de su versión final. "
            "El contenido puede ser limitado pero el precio suele ser menor. "
            "Riesgo de bugs o cambios radicales en el diseño."
        ),
    }

    RETRO_CLASSIC = {
        "genres_asociados": ["Adventure", "Action", "RPG"],
        "tags_asociados": ["Retro", "Pixel Graphics", "Platformer"],
        "ejemplos": ["Shovel Knight", "Undertale", "Stardew Valley", "Blasphemous"],
        "descripcion": (
            "Juegos con estética o mecánicas nostálgicas, inspirados en eras "
            "anteriores del videojuego (8-bit, 16-bit). Precio típico: $5-20 USD."
        ),
    }

    @property
    def genres_asociados(self) -> list[str]:
        return self.value["genres_asociados"]

    @property
    def tags_asociados(self) -> list[str]:
        return self.value["tags_asociados"]

    @property
    def ejemplos(self) -> list[str]:
        return self.value["ejemplos"]

    @property
    def descripcion(self) -> str:
        return self.value["descripcion"]


# ============================================================================
# 2. GAME CHARACTERISTICS — Attributes considered when filtering games
# ============================================================================

@dataclass
class GameCharacteristic:
    """
    Característica de un videojuego que el sistema considera al filtrar
    y al redactar recomendaciones.
    """
    nombre: str
    fuente_dato: str  # "SteamSpy", "SteamStore", "derivado", "LLM"
    tipo: str  # "objetivo", "subjetivo", "contextual"
    descripcion: str
    peso_recomendacion: float  # 0.0 a 1.0 — influencia relativa en el ranking


# -- Registry of all game characteristics ----------------------------------
# PESOS REBALANCEADOS v2: score_rank y tags_match dominan (~47% combinado).
# price_usd reducido de 0.25 → 0.10; discount de 0.15 → 0.08.
# Pesos a 0.00 no participan en el scoring.
GAME_CHARACTERISTICS: dict[str, GameCharacteristic] = {
    "price_usd": GameCharacteristic(
        nombre="Precio (USD)",
        fuente_dato="SteamSpy",
        tipo="objetivo",
        descripcion=(
            "Precio actual del juego en dólares estadounidenses. "
            "Filtrable por rango máximo definido por el usuario."
        ),
        peso_recomendacion=0.10,  # reducido de 0.25 — el precio no debe dominar
    ),
    "discount": GameCharacteristic(
        nombre="Porcentaje de descuento",
        fuente_dato="SteamSpy",
        tipo="objetivo",
        descripcion=(
            "Descuento activo en Steam (0 = sin oferta). El usuario puede "
            "filtrar para ver solo juegos en oferta (only_on_sale=True)."
        ),
        peso_recomendacion=0.08,  # reducido de 0.15
    ),
    "score_rank": GameCharacteristic(
        nombre="Calidad (Puntuación)",
        fuente_dato="SteamSpy",
        tipo="objetivo",
        descripcion=(
            "Puntuación (0-100) basada en valoraciones de usuarios. "
            "Su peso se ha reducido al 12%."
        ),
        peso_recomendacion=0.18,  # Intercambiado con género
    ),
    "owners": GameCharacteristic(
        nombre="Popularidad / Comunidad",
        fuente_dato="SteamSpy",
        tipo="objetivo",
        descripcion=(
            "Indicador de qué tan conocido es el juego. Ahora tiene un peso "
            "dominante del 25% para priorizar juegos famosos."
        ),
        peso_recomendacion=0.25,  # Intercambiado con calidad
    ),
    "tags_match": GameCharacteristic(
        nombre="Coincidencia de tags",
        fuente_dato="derivado",
        tipo="contextual",
        descripcion=(
            "Grado en que los tags del juego coinciden con los tags "
            "solicitados por el usuario. Calculado como intersección Jaccard."
        ),
        peso_recomendacion=0.22,  # aumentado de 0.20 — relevancia temática
    ),
    "genre_match": GameCharacteristic(
        nombre="Coincidencia de género",
        fuente_dato="derivado",
        tipo="contextual",
        descripcion=(
            "Coincidencia exacta con el género solicitado (Acción, RPG, etc.)."
        ),
        peso_recomendacion=0.25,  # Intercambiado con puntuación
    ),
    "regional_price": GameCharacteristic(
        nombre="Precio regional",
        fuente_dato="SteamStore",
        tipo="contextual",
        descripcion=(
            "Precio del juego en la moneda local del usuario (CLP, ARS, MXN, "
            "EUR, etc.). Enriquece la recomendación con relevancia local."
        ),
        peso_recomendacion=0.00,  # informativo solamente
    ),
    "developer": GameCharacteristic(
        nombre="Desarrollador",
        fuente_dato="SteamSpy",
        tipo="subjetivo",
        descripcion=(
            "Estudio desarrollador del juego. Relevante cuando el usuario "
            "menciona preferencia por ciertos developers (ej: 'tipo FromSoftware')."
        ),
        peso_recomendacion=0.05,
    ),
    "game_type": GameCharacteristic(
        nombre="Tipo de juego (AAA/Indie/etc.)",
        fuente_dato="derivado",
        tipo="subjetivo",
        descripcion=(
            "Clasificación del juego según la taxonomía GameType. Permite "
            "priorizar juegos indie si el usuario busca títulos económicos, "
            "o AAA si busca experiencias de alto presupuesto."
        ),
        peso_recomendacion=0.00,  # no implementado robustamente
    ),
    "release_recency": GameCharacteristic(
        nombre="Recencia de lanzamiento",
        fuente_dato="derivado",
        tipo="contextual",
        descripcion=(
            "Qué tan reciente es el lanzamiento del juego (inferido de la "
            "popularidad y base de owners). Juegos más nuevos pueden ser "
            "más relevantes."
        ),
        peso_recomendacion=0.00,  # No implementado aún — peso 0
    ),
}


# ============================================================================
# 3. RECOMMENDATION TYPES — Strategies the bot can employ
# ============================================================================

class RecommendationStrategy(Enum):
    """
    Estrategias de recomendación que SteamBot puede aplicar según la
    intención del usuario y los datos disponibles.
    """

    TAG_MATCH = {
        "descripcion": (
            "Recomienda juegos cuyos tags coinciden exactamente con los "
            "tags solicitados. Es la estrategia por defecto para SEARCH_GAME. "
            "Usa intersección AND entre múltiples tags vía intersect_by_tags()."
        ),
        "requiere_tags": True,
        "requiere_genero": False,
        "ordenamiento": "score_rank DESC, price_usd ASC",
    }

    GENRE_MATCH = {
        "descripcion": (
            "Recomienda juegos de un género específico (RPG, Action, Strategy...). "
            "Útil cuando el usuario no especifica tags pero sí un género claro. "
            "Usa search_by_genre() con fallback GENRE_TO_TAG."
        ),
        "requiere_tags": False,
        "requiere_genero": True,
        "ordenamiento": "score_rank DESC, price_usd ASC",
    }

    PRICE_SENSITIVE = {
        "descripcion": (
            "Optimiza recomendaciones priorizando el precio más bajo que cumpla "
            "los criterios. Activado cuando el usuario menciona 'barato', "
            "'económico', 'menos de X dólares' o max_price_usd ≤ $15."
        ),
        "requiere_tags": False,
        "requiere_genero": False,
        "ordenamiento": "price_usd ASC, score_rank DESC",
    }

    SIMILARITY_BASED = {
        "descripcion": (
            "Recomienda juegos similares a un título de referencia mencionado "
            "por el usuario (ej: 'algo tipo Dark Souls'). El LLM infiere los "
            "tags implícitos del juego de referencia para buscar títulos afines."
        ),
        "requiere_tags": False,
        "requiere_genero": False,
        "ordenamiento": "tags_match DESC, score_rank DESC",
    }

    ON_SALE_FOCUS = {
        "descripcion": (
            "Muestra exclusivamente juegos con descuento activo. Activado cuando "
            "only_on_sale=True. Los juegos se ordenan por mayor descuento primero."
        ),
        "requiere_tags": False,
        "requiere_genero": False,
        "ordenamiento": "discount DESC, score_rank DESC",
    }

    DISCOVERY = {
        "descripcion": (
            "Recomendación por descubrimiento: el usuario no especifica criterios "
            "concretos pero quiere explorar. Se muestran juegos populares bien "
            "valorados sin filtros estrictos."
        ),
        "requiere_tags": False,
        "requiere_genero": False,
        "ordenamiento": "score_rank DESC, owners DESC",
    }

    @property
    def descripcion(self) -> str:
        return self.value["descripcion"]

    @property
    def requiere_tags(self) -> bool:
        return self.value["requiere_tags"]

    @property
    def requiere_genero(self) -> bool:
        return self.value["requiere_genero"]

    @property
    def ordenamiento(self) -> str:
        return self.value["ordenamiento"]


# ============================================================================
# 4. USER VARIABLES — User attributes that influence recommendations
# ============================================================================

@dataclass
class UserVariable:
    """
    Variable del usuario que el sistema considera (o podría considerar)
    para personalizar las recomendaciones.
    """
    nombre: str
    tipo: str  # "explícito", "implícito", "derivado"
    categoria: str  # "preferencia", "contexto", "historial"
    fuente: str  # "input_usuario", "sesion", "configuracion"
    descripcion: str
    implementado: bool


USER_VARIABLES: dict[str, UserVariable] = {
    "region": UserVariable(
        nombre="Región geográfica",
        tipo="explícito",
        categoria="contexto",
        fuente="configuracion",
        descripcion=(
            "Región del usuario (US, CL, AR, MX, ES, etc.) seleccionada al "
            "iniciar el bot. Determina la moneda de precios regionales y "
            "disponibilidad de juegos."
        ),
        implementado=True,
    ),
    "presupuesto": UserVariable(
        nombre="Presupuesto máximo",
        tipo="explícito",
        categoria="preferencia",
        fuente="input_usuario",
        descripcion=(
            "Precio máximo en USD que el usuario está dispuesto a pagar. "
            "Extraído por el LLM de frases como 'menos de $20' o 'hasta 15 lucas'."
        ),
        implementado=True,
    ),
    "generos_preferidos": UserVariable(
        nombre="Géneros preferidos",
        tipo="explícito",
        categoria="preferencia",
        fuente="input_usuario",
        descripcion=(
            "Géneros de videojuegos que el usuario declara preferir. "
            "Extraídos por el LLM y usados como filtro principal."
        ),
        implementado=True,
    ),
    "tags_preferidos": UserVariable(
        nombre="Tags/etiquetas preferidas",
        tipo="explícito",
        categoria="preferencia",
        fuente="input_usuario",
        descripcion=(
            "Tags de SteamSpy que describen los gustos del usuario "
            "(ej: 'Horror', 'Open World', 'Pixel Graphics')."
        ),
        implementado=True,
    ),
    "solo_ofertas": UserVariable(
        nombre="Solo juegos en oferta",
        tipo="explícito",
        categoria="preferencia",
        fuente="input_usuario",
        descripcion=(
            "Preferencia binaria: el usuario solo quiere ver juegos con "
            "descuento activo en Steam."
        ),
        implementado=True,
    ),
    "sensibilidad_precio": UserVariable(
        nombre="Sensibilidad al precio",
        tipo="derivado",
        categoria="preferencia",
        fuente="input_usuario",
        descripcion=(
            "Nivel de sensibilidad al precio inferido por el LLM según el "
            "lenguaje del usuario ('barato', 'económico', 'gratis'). "
            "Influye en la estrategia de ordenamiento."
        ),
        implementado=False,
    ),
    "nivel_hardcore": UserVariable(
        nombre="Nivel de jugador (casual/hardcore)",
        tipo="derivado",
        categoria="preferencia",
        fuente="input_usuario",
        descripcion=(
            "Perfil de jugador inferido de las preferencias: Soulslike → hardcore, "
            "Casual → accesible. Podría usarse para ajustar la dificultad de "
            "las recomendaciones."
        ),
        implementado=False,
    ),
    "plataforma": UserVariable(
        nombre="Plataforma preferida",
        tipo="explícito",
        categoria="contexto",
        fuente="input_usuario",
        descripcion=(
            "Plataforma de juego (Steam asumido por defecto, pero el usuario "
            "podría mencionar Steam Deck o requisitos de sistema)."
        ),
        implementado=False,
    ),
    "historial_sesion": UserVariable(
        nombre="Historial de recomendaciones en sesión",
        tipo="implícito",
        categoria="historial",
        fuente="sesion",
        descripcion=(
            "Juegos ya recomendados en esta sesión. Se usan para evitar "
            "duplicados (_recommended_appids) y para refinar búsquedas subsecuentes."
        ),
        implementado=True,
    ),
    "idioma": UserVariable(
        nombre="Idioma del usuario",
        tipo="implícito",
        categoria="contexto",
        fuente="input_usuario",
        descripcion=(
            "Idioma en que el usuario escribe (español/inglés). Determina el "
            "idioma de las respuestas del LLM y la interfaz."
        ),
        implementado=True,
    ),
}


# ============================================================================
# 5. RECOMMENDATION SCORING ENGINE  (v2 — diversity + seen penalty)
# ============================================================================

# Diversity jitter: ±3% random perturbation to break ties and shuffle
# identically-scored games so the user sees variety across queries.
_DIVERSITY_JITTER = 0.03

# Penalty applied to games already recommended in this session.
# A 15% reduction makes them unlikely to top the ranking but keeps them
# as fallback candidates when few new games match the criteria.
_SEEN_PENALTY = 0.15


@dataclass
class ScoredGame:
    """A game with its computed recommendation score and explanation."""
    appid: str
    name: str
    score: float  # 0.0 - 1.0
    breakdown: dict[str, float]  # per-characteristic scores
    game_data: dict


def score_game(
    game: dict,
    user_tags: list[str],
    user_genre: Optional[str],
    user_max_price: Optional[float],
    seen_appids: Optional[set[str]] = None,
) -> ScoredGame:
    """
    Computes a recommendation score (0.0-1.0) for a game based on how well
    it matches the user's criteria.

    v2 improvements:
      - Rebalanced weights: score_rank (0.25) + tags_match (0.22) now dominate.
      - Price curve softened: still gives edge to cheaper games but not as extreme.
      - Diversity jitter (±3%) applied to avoid identical rankings every query.
      - Seen penalty (−15%) for games already recommended in this session.
    """
    import hashlib

    breakdown: dict[str, float] = {}
    total_weight = 0.0
    weighted_sum = 0.0

    # 1. Price match — softened sigmoid-like curve
    char = GAME_CHARACTERISTICS["price_usd"]
    price = game.get("price_usd", 999)
    if user_max_price is not None:
        price_score = 1.0 if price <= user_max_price else 0.0
    else:
        # Smoother curve: $0 → 1.0, $15 → 0.85, $30 → 0.65, $60 → 0.35
        if price <= 0:
            price_score = 1.0
        else:
            price_score = max(0.2, 1.0 - (price / 90.0))  # softer than /60
    breakdown["price_usd"] = price_score
    weighted_sum += price_score * char.peso_recomendacion
    total_weight += char.peso_recomendacion

    # 2. Discount match
    char = GAME_CHARACTERISTICS["discount"]
    discount = game.get("discount", 0)
    discount_score = min(1.0, discount / 50.0)
    breakdown["discount"] = discount_score
    weighted_sum += discount_score * char.peso_recomendacion
    total_weight += char.peso_recomendacion

    # 3. Score rank — the primary quality signal
    char = GAME_CHARACTERISTICS["score_rank"]
    score_rank = game.get("score_rank") or 0
    score_rank_normalized = score_rank / 100.0
    breakdown["score_rank"] = score_rank_normalized
    weighted_sum += score_rank_normalized * char.peso_recomendacion
    total_weight += char.peso_recomendacion

    # 4. Popularity (Owners or Rating Count)
    char = GAME_CHARACTERISTICS["owners"]
    owners_str = game.get("owners", "")

    if owners_str:
        owners_score = _parse_owners_score(owners_str)
    else:
        owners_score = 0.2  # conservative default for unknown games

    breakdown["popularity"] = owners_score
    weighted_sum += owners_score * char.peso_recomendacion
    total_weight += char.peso_recomendacion

    # 5. Tags match (Jaccard similarity)
    char = GAME_CHARACTERISTICS["tags_match"]
    game_tags = set(game.get("tags", {}).keys()) if isinstance(game.get("tags"), dict) else set()
    user_tag_set = set(user_tags)
    if user_tag_set:
        intersection = len(game_tags & user_tag_set)
        union = len(game_tags | user_tag_set)
        tags_score = intersection / union if union > 0 else 0.0
    else:
        tags_score = 0.5  # neutral
    breakdown["tags_match"] = tags_score
    weighted_sum += tags_score * char.peso_recomendacion
    total_weight += char.peso_recomendacion

    # 6. Genre match
    char = GAME_CHARACTERISTICS["genre_match"]
    if user_genre:
        game_tags_lower = {t.lower() for t in game_tags}
        genre_score = 1.0 if user_genre.lower() in game_tags_lower else 0.0
    else:
        genre_score = 0.5
    breakdown["genre_match"] = genre_score
    weighted_sum += genre_score * char.peso_recomendacion
    total_weight += char.peso_recomendacion

    # 7. Developer (neutral placeholder)
    char = GAME_CHARACTERISTICS["developer"]
    breakdown["developer"] = 0.5
    weighted_sum += 0.5 * char.peso_recomendacion
    total_weight += char.peso_recomendacion

    final_score = weighted_sum / total_weight if total_weight > 0 else 0.5

    # -- Diversity jitter: deterministic per-game ±3% perturbation --
    # Uses a hash of appid so the same game always gets the same jitter
    # within a session, but different games get different perturbations.
    appid_str = str(game.get("appid", "0"))
    seed = int(hashlib.md5(appid_str.encode()).hexdigest()[:8], 16) % 1000
    jitter = (seed / 1000.0 - 0.5) * 2.0 * _DIVERSITY_JITTER  # [-0.03, +0.03]
    final_score = max(0.0, min(1.0, final_score + jitter))

    # -- Seen penalty: reduce score for already-recommended games --
    if seen_appids and appid_str in seen_appids:
        final_score = max(0.0, final_score - _SEEN_PENALTY)
        breakdown["_seen_penalty"] = -_SEEN_PENALTY

    return ScoredGame(
        appid=appid_str,
        name=game.get("name", "Unknown"),
        score=round(final_score, 4),
        breakdown=breakdown,
        game_data=game,
    )


def _parse_owners_score(owners_str: str) -> float:
    """Convert SteamSpy owners range string to a 0-1 score."""
    if not owners_str or not isinstance(owners_str, str):
        return 0.3
    mapping = {
        "0..20000": 0.05,
        "20000..50000": 0.10,
        "50000..100000": 0.15,
        "100000..200000": 0.20,
        "200000..500000": 0.35,
        "500000..1000000": 0.55,
        "1000000..2000000": 0.65,
        "2000000..5000000": 0.75,
        "5000000..10000000": 0.85,
        "10000000..20000000": 0.92,
        "20000000..50000000": 0.97,
        "50000000..100000000": 1.00,
    }
    for pattern, score in mapping.items():
        if owners_str == pattern:
            return score
    # Fuzzy match for slightly different format
    try:
        if ".." in owners_str:
            parts = owners_str.replace(",", "").split("..")
            low = int(parts[0])
            if low >= 20_000_000:
                return 0.95
            elif low >= 5_000_000:
                return 0.70
            elif low >= 1_000_000:
                return 0.50
            elif low >= 200_000:
                return 0.30
            else:
                return 0.15
    except (ValueError, IndexError):
        pass
    return 0.30


def _game_meets_popularity_threshold(game: dict) -> bool:
    """
    Hard filter: returns False if the game is too obscure or is a DLC.
    Restores the 'high quality' feel by requiring mass popularity.
    """
    name = game.get("name", "").lower()

    # 1. Filter out obvious DLCs, Soundtracks, and Packs
    dlc_keywords = ["dlc", "soundtrack", "artbook", "season pass", "upgrade", "pack", "chapter", "edition", "bundle"]
    if any(k in name for k in dlc_keywords):
        # Allow 'Special Edition' or 'Complete Edition' if they aren't explicitly packs
        if "edition" in name and not any(k in name for k in ["dlc", "pack", "pass"]):
            pass
        else:
            return False

    # 2. Popularity threshold: Must be a well-known game
    owners_str = game.get("owners", "0 .. 0")
    try:
        lower_bound = int(owners_str.split("..")[0].replace(",", "").strip())
    except:
        lower_bound = 0

    positive = game.get("positive", 0) or 0
    negative = game.get("negative", 0) or 0
    total_reviews = positive + negative

    # PRESTIGE FILTER: Minimum 50k owners OR 2k reviews.
    # Lowered from 100k to avoid filtering out good niche games (Racing, Building, etc.)
    return lower_bound >= 50000 or total_reviews >= 2000


def rank_games(
    games: list[dict],
    user_tags: list[str],
    user_genre: Optional[str],
    user_max_price: Optional[float],
    strategy: RecommendationStrategy = RecommendationStrategy.TAG_MATCH,
    seen_appids: Optional[set[str]] = None,
) -> list[ScoredGame]:
    """
    Scores and ranks a list of games according to the user's criteria
    and the chosen recommendation strategy.
    """
    # Hard filter: discard games that are too obscure or DLCs
    eligible = [g for g in games if _game_meets_popularity_threshold(g)]

    scored = [
        score_game(g, user_tags, user_genre, user_max_price, seen_appids=seen_appids)
        for g in eligible
    ]

    # Apply strategy-specific sorting
    if strategy == RecommendationStrategy.PRICE_SENSITIVE:
        scored.sort(key=lambda s: (s.game_data.get("price_usd", 999), -s.score))
    elif strategy == RecommendationStrategy.ON_SALE_FOCUS:
        scored.sort(key=lambda s: (-s.game_data.get("discount", 0), -s.score))
    else:
        scored.sort(key=lambda s: -s.score)

    return scored


def select_strategy(
    user_tags: list[str],
    user_genre: Optional[str],
    user_max_price: Optional[float],
    only_on_sale: bool,
    game_name: Optional[str],
) -> RecommendationStrategy:
    """
    Selects the most appropriate recommendation strategy based on
    the user's input variables.
    """
    if only_on_sale:
        return RecommendationStrategy.ON_SALE_FOCUS
    if user_max_price is not None and user_max_price <= 15.0:
        return RecommendationStrategy.PRICE_SENSITIVE
    if game_name:
        return RecommendationStrategy.SIMILARITY_BASED
    if user_tags:
        return RecommendationStrategy.TAG_MATCH
    if user_genre:
        return RecommendationStrategy.GENRE_MATCH
    return RecommendationStrategy.DISCOVERY
