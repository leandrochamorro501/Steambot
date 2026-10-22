"""
intent_model.py
--------------
Formal Intent Model for SteamBot NLU pipeline.

Defines the structured schema of intents, slots, entities and training
utterances that the LLM-based extractor maps user queries to — addressing
the "modelado de intenciones y frases de entrenamiento" requirement.

Architecture:
  - IntentSchema: Enumeration of all possible user intents with metadata.
  - SlotRegistry: Formal definition of every slot (entity) the system extracts.
  - TrainingUtterances: Labeled Spanish utterances per intent for NLU validation.
  - IntentClassifier: Programmatic wrapper that provides the contract between
    the LLM extractor and the business logic in main.py.

Tag source: tag_registry.py (339 tags from SteamSpy official CSV).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from models import tag_registry


# ============================================================================
# 1. INTENT SCHEMA — Formal definition of all intents the system recognizes
# ============================================================================

class IntentType(Enum):
    """
    Enumerated intent types that SteamBot can classify a user message into.

    Each intent carries:
      - priority: Execution precedence (lower = higher priority)
      - description: Human-readable explanation of the intent
      - requires_search: Whether this intent triggers SteamSpy lookups
    """

    SEARCH_GAME = {
        "priority": 1,
        "description": (
            "El usuario solicita una recomendación de videojuegos con criterios "
            "específicos (género, tags, precio, ofertas, puntuación). Es el flujo "
            "principal del bot."
        ),
        "requires_search": True,
    }

    REFINE_SEARCH = {
        "priority": 2,
        "description": (
            "El usuario quiere ajustar una búsqueda anterior — p.ej. 'más barato', "
            "'igual pero multijugador', 'otro parecido'. Depende del contexto de "
            "la conversación previa."
        ),
        "requires_search": True,
    }

    CHECK_PRICE = {
        "priority": 3,
        "description": (
            "El usuario pregunta por el precio de un juego específico o si está "
            "en oferta. Puede resolverse con SteamSpy + Steam Store API."
        ),
        "requires_search": True,
    }

    COMPARE_GAMES = {
        "priority": 4,
        "description": (
            "El usuario quiere comparar dos o más juegos conocidos. Implica "
            "recuperar datos de ambos y presentar una comparación estructurada."
        ),
        "requires_search": True,
    }

    CASUAL_CHAT = {
        "priority": 5,
        "description": (
            "Interacción social sin intención de búsqueda: saludos, preguntas "
            "sobre el bot, agradecimientos, despedidas."
        ),
        "requires_search": False,
    }

    ASK_CAPABILITIES = {
        "priority": 6,
        "description": (
            "El usuario pregunta qué puede hacer el bot, qué comandos existen, "
            "o cómo usarlo."
        ),
        "requires_search": False,
    }

    @property
    def priority(self) -> int:
        return self.value["priority"]

    @property
    def description(self) -> str:
        return self.value["description"]

    @property
    def requires_search(self) -> bool:
        return self.value["requires_search"]


# ============================================================================
# 2. SLOT / ENTITY REGISTRY — Formal definition of every extractable parameter
# ============================================================================

@dataclass
class SlotDefinition:
    """Formal specification of a slot (entity) that the NLU extractor must fill."""

    name: str
    type: str  # "string", "string[]", "float", "int", "boolean"
    required: bool
    description: str
    allowed_values: Optional[list[str]] = None
    default: object = None
    examples: list[str] = field(default_factory=list)


# -- Complete Slot Registry --------------------------------------------------
SLOT_REGISTRY: dict[str, SlotDefinition] = {
    "genre": SlotDefinition(
        name="genre",
        type="string",
        required=False,
        description=(
            "Género principal del videojuego deseado. Debe ser uno de los géneros "
            "reconocidos por SteamSpy: Action, RPG, Strategy, Indie, Adventure, "
            "Simulation, Racing, Sports, Casual, Free to Play, Early Access."
        ),
        allowed_values=[
            "Action", "RPG", "Strategy", "Indie", "Adventure",
            "Simulation", "Racing", "Sports", "Casual",
            "Free to Play", "Early Access",
        ],
        default=None,
        examples=["RPG", "acción", "aventura", "estrategia", "juego de rol"],
    ),
    "tags": SlotDefinition(
        name="tags",
        type="string[]",
        required=False,
        description=(
            "Etiquetas de SteamSpy que describen la temática, mecánica o estilo "
            "visual del juego. Máximo 3 tags por consulta. Deben ser tags exactos "
            "reconocidos por SteamSpy (ver tag_registry.ALL_TAGS)."
        ),
        allowed_values=tag_registry.ALL_TAGS,
        default=[],
        examples=[
            "terror", "mundo abierto", "almas", "cooperativo", "anime",
            "pixel art", "multijugador", "ciencia ficción", "fantasía",
        ],
    ),
    "max_price_usd": SlotDefinition(
        name="max_price_usd",
        type="float",
        required=False,
        description=(
            "Precio máximo en dólares estadounidenses que el usuario está "
            "dispuesto a pagar. Se extrae de frases como 'menos de 20 dólares', "
            "'hasta 15 lucas', 'barato', 'económico'."
        ),
        allowed_values=None,
        default=None,
        examples=["20", "menos de 10 dólares", "hasta 5000 pesos", "barato", "gratis"],
    ),
    "only_on_sale": SlotDefinition(
        name="only_on_sale",
        type="boolean",
        required=False,
        description=(
            "Indica si el usuario solo quiere ver juegos que estén actualmente "
            "en oferta/descuento en Steam."
        ),
        allowed_values=None,
        default=False,
        examples=["en oferta", "con descuento", "rebajado", "solo ofertas"],
    ),
    "min_score_rank": SlotDefinition(
        name="min_score_rank",
        type="int",
        required=False,
        description=(
            "Puntuación mínima (0-100) según SteamSpy score_rank. El usuario "
            "puede expresarlo como 'bien valorado', 'más de 80%', 'con buenas críticas'."
        ),
        allowed_values=None,
        default=None,
        examples=["80", "bien puntuado", "con buenas reseñas", "recomendado"],
    ),
    "game_name": SlotDefinition(
        name="game_name",
        type="string",
        required=False,
        description=(
            "Nombre de un videojuego específico mencionado por el usuario. "
            "Usado para búsquedas por similitud ('algo como Dark Souls'), "
            "consulta de precio, o comparaciones."
        ),
        allowed_values=None,
        default=None,
        examples=["Dark Souls", "Stardew Valley", "Elden Ring", "The Witcher 3"],
    ),
    "target_game_count": SlotDefinition(
        name="target_game_count",
        type="int",
        required=False,
        description=(
            "Cantidad de juegos que el usuario espera recibir en la recomendación. "
            "Por defecto el sistema muestra 3-5."
        ),
        allowed_values=None,
        default=5,
        examples=["5", "dame 10", "un par", "los mejores 3"],
    ),
}


# ============================================================================
# 3. TRAINING UTTERANCES — Labeled phrases per intent for NLU validation
# ============================================================================

@dataclass
class TrainingUtterance:
    """A single labeled training example for the NLU classifier."""

    text: str
    intent: IntentType
    slots: dict  # e.g. {"genre": "RPG", "tags": ["Fantasy"], "max_price_usd": 20.0}


TRAINING_DATA: list[TrainingUtterance] = [
    # ── SEARCH_GAME ──────────────────────────────────────────────────────
    TrainingUtterance(
        text="Recomiéndame juegos de terror psicológico",
        intent=IntentType.SEARCH_GAME,
        slots={"tags": ["Psychological Horror", "Horror"], "genre": None, "max_price_usd": None, "only_on_sale": False, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Busco un RPG de fantasía de menos de 20 dólares",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": "RPG", "tags": ["Fantasy"], "max_price_usd": 20.0, "only_on_sale": False, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Quiero juegos de estrategia baratos que estén en oferta",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": "Strategy", "tags": [], "max_price_usd": 10.0, "only_on_sale": True, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Algo tipo Dark Souls pero con estética anime",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": None, "tags": ["Soulslike", "Anime"], "max_price_usd": None, "only_on_sale": False, "min_score_rank": None, "game_name": "Dark Souls"},
    ),
    TrainingUtterance(
        text="Co-op para jugar con amigos, menos de $15",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": None, "tags": ["Cooperative", "Multiplayer"], "max_price_usd": 15.0, "only_on_sale": False, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Juegos de mundo abierto con buenas críticas",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": None, "tags": ["Open World"], "max_price_usd": None, "only_on_sale": False, "min_score_rank": 80},
    ),
    TrainingUtterance(
        text="Dame los mejores juegos de supervivencia con zombies",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": None, "tags": ["Survival", "Zombies"], "max_price_usd": None, "only_on_sale": False, "min_score_rank": 70},
    ),
    TrainingUtterance(
        text="Quiero un juego de disparos en primera persona, online",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": None, "tags": ["FPS", "Multiplayer"], "max_price_usd": None, "only_on_sale": False, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Juegos indie con gráficos pixel art, baratos",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": "Indie", "tags": ["Pixel Graphics"], "max_price_usd": 15.0, "only_on_sale": False, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="RPG de ciencia ficción con combate por turnos",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": "RPG", "tags": ["Sci-fi", "Turn-Based"], "max_price_usd": None, "only_on_sale": False, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Juegos como Stardew Valley para jugar con mi pareja",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": None, "tags": ["Cooperative", "Pixel Graphics"], "max_price_usd": None, "only_on_sale": False, "min_score_rank": None, "game_name": "Stardew Valley"},
    ),
    TrainingUtterance(
        text="Busco algo de deportes, pero que no sea FIFA",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": "Sports", "tags": [], "max_price_usd": None, "only_on_sale": False, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Me gustan los rogue-like, ¿qué me recomiendas?",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": None, "tags": ["Roguelike"], "max_price_usd": None, "only_on_sale": False, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Juegos de carreras que estén en descuento ahora mismo",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": "Racing", "tags": [], "max_price_usd": None, "only_on_sale": True, "min_score_rank": None},
    ),
    TrainingUtterance(
        text="Aventuras gráficas con buena historia, menos de 30 USD",
        intent=IntentType.SEARCH_GAME,
        slots={"genre": "Adventure", "tags": [], "max_price_usd": 30.0, "only_on_sale": False, "min_score_rank": None},
    ),

    # ── REFINE_SEARCH ─────────────────────────────────────────────────────
    TrainingUtterance(
        text="Mejor que sea más barato",
        intent=IntentType.REFINE_SEARCH,
        slots={"max_price_usd": None},
    ),
    TrainingUtterance(
        text="¿Tienes algo parecido pero multijugador?",
        intent=IntentType.REFINE_SEARCH,
        slots={"tags": ["Multiplayer"]},
    ),
    TrainingUtterance(
        text="Lo mismo pero que sea de mundo abierto",
        intent=IntentType.REFINE_SEARCH,
        slots={"tags": ["Open World"]},
    ),
    TrainingUtterance(
        text="Muéstrame solo los que están en oferta de esos",
        intent=IntentType.REFINE_SEARCH,
        slots={"only_on_sale": True},
    ),
    TrainingUtterance(
        text="Quiero algo con mejor puntuación",
        intent=IntentType.REFINE_SEARCH,
        slots={"min_score_rank": 80},
    ),
    TrainingUtterance(
        text="Mejor dame opciones de menos de 10 dólares",
        intent=IntentType.REFINE_SEARCH,
        slots={"max_price_usd": 10.0},
    ),
    TrainingUtterance(
        text="No me gustó ninguno, dame otras opciones",
        intent=IntentType.REFINE_SEARCH,
        slots={},
    ),
    TrainingUtterance(
        text="Ese mismo género pero sin restricción de precio",
        intent=IntentType.REFINE_SEARCH,
        slots={"max_price_usd": None},
    ),

    # ── CHECK_PRICE ───────────────────────────────────────────────────────
    TrainingUtterance(
        text="¿Cuánto cuesta Elden Ring?",
        intent=IntentType.CHECK_PRICE,
        slots={"game_name": "Elden Ring"},
    ),
    TrainingUtterance(
        text="¿Está en oferta el Baldur's Gate 3?",
        intent=IntentType.CHECK_PRICE,
        slots={"game_name": "Baldur's Gate 3", "only_on_sale": True},
    ),
    TrainingUtterance(
        text="Precio del Cyberpunk 2077 en Steam",
        intent=IntentType.CHECK_PRICE,
        slots={"game_name": "Cyberpunk 2077"},
    ),
    TrainingUtterance(
        text="¿A cuánto está el FIFA?",
        intent=IntentType.CHECK_PRICE,
        slots={"game_name": "FIFA"},
    ),
    TrainingUtterance(
        text="Dime el precio del Hades 2",
        intent=IntentType.CHECK_PRICE,
        slots={"game_name": "Hades 2"},
    ),

    # ── COMPARE_GAMES ─────────────────────────────────────────────────────
    TrainingUtterance(
        text="Compara Elden Ring con Dark Souls 3",
        intent=IntentType.COMPARE_GAMES,
        slots={"game_name": "Elden Ring"},
    ),
    TrainingUtterance(
        text="¿Cuál es mejor, Baldur's Gate 3 o Divinity Original Sin 2?",
        intent=IntentType.COMPARE_GAMES,
        slots={"game_name": "Baldur's Gate 3"},
    ),
    TrainingUtterance(
        text="Diferencias entre Cyberpunk y The Witcher 3",
        intent=IntentType.COMPARE_GAMES,
        slots={"game_name": "Cyberpunk 2077"},
    ),

    # ── CASUAL_CHAT ───────────────────────────────────────────────────────
    TrainingUtterance(
        text="Hola, ¿cómo estás?",
        intent=IntentType.CASUAL_CHAT,
        slots={},
    ),
    TrainingUtterance(
        text="Buenos días",
        intent=IntentType.CASUAL_CHAT,
        slots={},
    ),
    TrainingUtterance(
        text="Gracias por la ayuda",
        intent=IntentType.CASUAL_CHAT,
        slots={},
    ),
    TrainingUtterance(
        text="Eres muy útil",
        intent=IntentType.CASUAL_CHAT,
        slots={},
    ),
    TrainingUtterance(
        text="Adiós, hasta luego",
        intent=IntentType.CASUAL_CHAT,
        slots={},
    ),
    TrainingUtterance(
        text="¿Cuál es tu juego favorito?",
        intent=IntentType.CASUAL_CHAT,
        slots={},
    ),
    TrainingUtterance(
        text="Jajaja qué buen bot",
        intent=IntentType.CASUAL_CHAT,
        slots={},
    ),

    # ── ASK_CAPABILITIES ──────────────────────────────────────────────────
    TrainingUtterance(
        text="¿Qué puedes hacer?",
        intent=IntentType.ASK_CAPABILITIES,
        slots={},
    ),
    TrainingUtterance(
        text="¿Cómo funcionas?",
        intent=IntentType.ASK_CAPABILITIES,
        slots={},
    ),
    TrainingUtterance(
        text="¿Qué comandos tienes?",
        intent=IntentType.ASK_CAPABILITIES,
        slots={},
    ),
    TrainingUtterance(
        text="Ayuda",
        intent=IntentType.ASK_CAPABILITIES,
        slots={},
    ),
    TrainingUtterance(
        text="Explícame cómo usarte",
        intent=IntentType.ASK_CAPABILITIES,
        slots={},
    ),
]


# ============================================================================
# 4. INTENT CLASSIFIER — Contract between LLM extractor and business logic
# ============================================================================

@dataclass
class ClassifiedIntent:
    """
    Structured output contract that every extraction must conform to.
    This is the single source of truth for the shape of data flowing from
    llm_engine.extract_intent() to main.run_pipeline().
    """

    # Core identification
    intent_type: IntentType

    # Reasoning trace (required by the EXTRACTOR prompt)
    reasoning: str

    # Slots extracted from the user message
    genre: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    max_price_usd: Optional[float] = None
    only_on_sale: bool = False
    min_score_rank: Optional[int] = None
    game_name: Optional[str] = None
    target_game_count: int = 5

    # Status flags
    is_game_query: bool = True
    is_complete: bool = False
    missing_details: Optional[str] = None

    def to_legacy_dict(self) -> dict:
        """
        Converts to the legacy dict format expected by main.py, ensuring
        backward compatibility while adding the formal intent_type.
        """
        return {
            "_reasoning": self.reasoning,
            "intent_type": self.intent_type.name,
            "is_game_query": self.is_game_query,
            "status": (
                "complete"
                if self.is_complete
                else ("chat" if not self.is_game_query else "incomplete")
            ),
            "tags": self.tags,
            "genre": self.genre,
            "max_price_usd": self.max_price_usd,
            "only_on_sale": self.only_on_sale,
            "min_score_rank": self.min_score_rank,
            "game_name": self.game_name,
            "missing_details": self.missing_details,
        }


# ============================================================================
# 5. NLU EVALUATION UTILITIES
# ============================================================================

def get_training_summary() -> dict:
    """Returns aggregate statistics about the training dataset."""
    intent_counts: dict[str, int] = {}
    total_slots_filled = 0
    total_utterances = len(TRAINING_DATA)

    for utt in TRAINING_DATA:
        name = utt.intent.name
        intent_counts[name] = intent_counts.get(name, 0) + 1
        total_slots_filled += len(utt.slots)

    return {
        "total_utterances": total_utterances,
        "intents_covered": len(intent_counts),
        "utterances_per_intent": intent_counts,
        "avg_slots_per_utterance": round(total_slots_filled / total_utterances, 2),
    }


def validate_slots(slots: dict) -> list[str]:
    """
    Validates extracted slots against the SLOT_REGISTRY.
    Returns a list of validation errors (empty = valid).
    """
    errors = []
    for slot_name, value in slots.items():
        if slot_name not in SLOT_REGISTRY:
            errors.append(f"Unknown slot: {slot_name}")
            continue

        definition = SLOT_REGISTRY[slot_name]
        if definition.allowed_values and value is not None:
            if isinstance(value, list):
                for v in value:
                    if v not in definition.allowed_values:
                        errors.append(
                            f"Slot '{slot_name}': '{v}' not in allowed values"
                        )
            elif value not in definition.allowed_values:
                errors.append(
                    f"Slot '{slot_name}': '{value}' not in allowed values"
                )

    return errors
