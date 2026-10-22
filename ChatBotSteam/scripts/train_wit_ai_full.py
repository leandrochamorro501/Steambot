"""
train_wit_ai_full.py
--------------------
Entrenamiento COMPLETO y refinado de Wit.ai para SteamBot.

import sys; sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

Estrategia:
  1. Crear/verificar los 6 intents del sistema
  2. Crear entidades: tags (keywords+free-text), genre (keywords+free-text),
     game_name (free-text). Wit.ai usa sus entidades built-in para dinero/números.
  3. Cargar keywords con sinónimos exhaustivos en español (ambos hemisferios)
     para: tags y géneros.
  4. Subir ~300 utterances etiquetadas con intents + entidades.

Cómo usar:
  Desde ChatBotSteam/:
    python scripts/train_wit_ai_full.py

Notas:
  - La API de Wit.ai acepta hasta 100 utterances por request (lote).
  - Limitar el delay a 0.15s entre requests; el endpoint /utterances
    es más permisivo que /entities.
  - Si ya existen los intents/entidades, la API retorna 409 (se ignora).
"""

import asyncio
import io
import os
import sys

import httpx

# Force UTF-8 output on Windows so special chars don't crash
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(env_path)

WIT_AI_TOKEN = os.getenv("WIT_AI_TOKEN", "")
WIT_API_VERSION = "20240601"
BASE_URL = "https://api.wit.ai"

HEADERS = {
    "Authorization": f"Bearer {WIT_AI_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

BATCH_SIZE = 50   # utterances por request

# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------
INTENTS = [
    "search_game",
    "refine_search",
    "check_price",
    "compare_games",
    "casual_chat",
    "ask_capabilities",
]

# ---------------------------------------------------------------------------
# Géneros con sinónimos (español completo: España + Latam)
# ---------------------------------------------------------------------------
GENRE_SYNONYMS: dict[str, list[str]] = {
    "Action": [
        "Action", "acción", "accion", "juego de acción", "juego de accion",
        "tiros", "disparos", "combate", "lucha", "peleas", "bélico",
        "beat em up", "hack and slash",
    ],
    "Adventure": [
        "Adventure", "aventura", "aventuras", "juego de aventura",
        "exploración", "exploracion", "explorar", "adventure game",
    ],
    "RPG": [
        "RPG", "rol", "juego de rol", "rpg", "juego rpg", "juegos de rol",
        "juego de roles", "juego de personajes", "role playing",
        "role playing game", "rpgs",
    ],
    "Strategy": [
        "Strategy", "estrategia", "juego de estrategia", "tactico", "táctico",
        "táctica", "táctica militar", "estratégico", "estrategico",
        "grand strategy", "wargame",
    ],
    "Simulation": [
        "Simulation", "simulación", "simulacion", "simulador",
        "juego de simulación", "sim", "sims",
    ],
    "Racing": [
        "Racing", "carreras", "carrera", "autos", "coches", "conducción",
        "conduccion", "racing game", "juego de carreras", "juego de autos",
        "juego de coches", "manejar", "conducir",
    ],
    "Sports": [
        "Sports", "deportes", "deporte", "juego de deportes",
        "futbol", "fútbol", "basket", "baloncesto", "tenis", "golf",
        "deportivo", "atlético",
    ],
    "Indie": [
        "Indie", "independiente", "juegos indie", "indies",
        "indie game", "juego indie",
    ],
    "Casual": [
        "Casual", "casual", "juego casual", "relajante", "tranquilo",
        "facil", "fácil", "sin complicaciones", "pick and play",
    ],
    "Massively Multiplayer": [
        "Massively Multiplayer", "mmo", "mmorpg", "multijugador masivo",
        "masivo multijugador", "online masivo", "mundo online",
    ],
    "Free to Play": [
        "Free to Play", "gratis", "gratuito", "f2p", "free to play",
        "juegos gratis", "sin costo", "precio cero", "free", "free2play",
    ],
    "Early Access": [
        "Early Access", "acceso anticipado", "early access", "beta",
        "en desarrollo", "acceso temprano",
    ],
}

# ---------------------------------------------------------------------------
# Tags con sinónimos EXHAUSTIVOS (español de ambos hemisferios)
# ---------------------------------------------------------------------------
TAG_SYNONYMS: dict[str, list[str]] = {
    # ── Terror / Horror ──────────────────────────────────────────────────────
    "Horror": [
        "Horror", "terror", "miedo", "horror", "aterrador", "aterradoras",
        "perturbador", "espantoso", "susto", "sustos", "tenebroso",
        "macabro", "juego de terror", "juego de miedo",
    ],
    "Psychological Horror": [
        "Psychological Horror", "terror psicológico", "terror psicologico",
        "horror psicológico", "horror psicologico", "psicológico",
        "psicologico", "paranoia", "perturbador psicológico",
        "mente", "miedo psicológico",
    ],
    "Survival Horror": [
        "Survival Horror", "terror de supervivencia", "horror survival",
        "sobrevivir con miedo", "survival horror", "resident evil like",
        "juego tipo resident evil",
    ],
    # ── Supervivencia ────────────────────────────────────────────────────────
    "Survival": [
        "Survival", "supervivencia", "survival", "sobrevivir", "sobrevivencia",
        "resistir", "juego de supervivencia", "sobrevivir en la naturaleza",
        "craftear para vivir", "crafting survival",
    ],
    "Zombies": [
        "Zombies", "zombies", "zombis", "muertos vivientes", "no muertos",
        "apocalipsis zombie", "apocalipsis zombi", "walking dead",
        "muertos", "horda de zombies",
    ],
    "Post-apocalyptic": [
        "Post-apocalyptic", "postapocalíptico", "postapocaliptico",
        "post-apocalíptico", "post apocalipsis", "fin del mundo",
        "mundo destruido", "wasteland", "tierra baldía",
    ],
    # ── Acción / Combate ─────────────────────────────────────────────────────
    "Shooter": [
        "Shooter", "shooter", "disparos", "tiros", "fps", "pistola",
        "rifle", "armas de fuego", "shooting", "juego de disparos",
        "primera persona disparos",
    ],
    "FPS": [
        "FPS", "fps", "primera persona", "primera persona disparos",
        "first person shooter", "first person", "primera persona",
    ],
    "Third-Person Shooter": [
        "Third-Person Shooter", "tercera persona disparos",
        "shooter tercera persona", "tps", "disparos tercera persona",
    ],
    "Hack and Slash": [
        "Hack and Slash", "hack and slash", "espadas", "matar hordas",
        "golpear enemigos", "acción con espada", "action rpg combate",
    ],
    "Fighting": [
        "Fighting", "pelea", "peleas", "lucha", "artes marciales",
        "combate cuerpo a cuerpo", "fighting game", "juego de pelea",
        "uno contra uno", "1v1",
    ],
    "Stealth": [
        "Stealth", "sigilo", "stealth", "espionaje", "invisible",
        "sin ser visto", "sigiloso", "esconderse", "assassin",
        "ocultarse", "infiltración", "infiltracion",
    ],
    # ── Multijugador / Social ─────────────────────────────────────────────────
    "Multiplayer": [
        "Multiplayer", "multijugador", "online", "en línea", "en linea",
        "con otros jugadores", "con más gente", "varios jugadores",
        "jugar online", "jugar en línea",
    ],
    "Co-op": [
        "Co-op", "cooperativo", "coop", "co-op", "con amigos",
        "con mi amigo", "dos jugadores", "con otra persona",
        "jugar juntos", "modo cooperativo", "colaborativo",
        "co operativo", "compañero", "duo",
    ],
    "Online Co-Op": [
        "Online Co-Op", "cooperativo online", "coop online",
        "jugar con amigos online", "cooperativo en línea",
        "con amigos por internet",
    ],
    "Local Co-Op": [
        "Local Co-Op", "cooperativo local", "coop local", "pantalla dividida",
        "split screen", "misma tele", "mismo sofá", "couch co-op",
        "local multiplayer", "multiplayer local",
    ],
    "Battle Royale": [
        "Battle Royale", "battle royale", "br", "royal", "fortnite like",
        "pubg like", "último en pie", "ultimo en pie",
        "battle royal", "royale",
    ],
    "PvP": [
        "PvP", "pvp", "jugador contra jugador", "competitivo online",
        "vs otros jugadores", "versus", "enfrentamiento online",
    ],
    "Competitive": [
        "Competitive", "competitivo", "competencia", "ranked",
        "torneos", "esports", "e-sports", "liga",
    ],
    # ── RPG / Historia ────────────────────────────────────────────────────────
    "RPG": [
        "RPG", "rol", "juego de rol", "rpg", "role playing",
    ],
    "Action RPG": [
        "Action RPG", "action rpg", "rpg de acción", "rpg acción",
        "arpg", "souls like rpg", "rpg con combate",
    ],
    "JRPG": [
        "JRPG", "jrpg", "rpg japones", "rpg japonés", "rpg de japón",
        "final fantasy like", "dragon quest like",
    ],
    "Story Rich": [
        "Story Rich", "historia", "narrativa", "story rich", "buena historia",
        "con historia", "argumento", "trama", "relato",
        "historia épica", "historia profunda", "narrativo", "cinemático",
    ],
    "Choices Matter": [
        "Choices Matter", "decisiones", "elecciones", "importan las decisiones",
        "mis elecciones importan", "finales alternativos", "distintos finales",
        "múltiples finales", "multiples finales", "tus decisiones cambian",
    ],
    "Multiple Endings": [
        "Multiple Endings", "múltiples finales", "multiples finales",
        "varios finales", "distintos finales", "varios endings",
    ],
    # ── Mundo abierto / Exploración ───────────────────────────────────────────
    "Open World": [
        "Open World", "mundo abierto", "open world", "exploración libre",
        "exploracion libre", "mapa abierto", "sin límites de mapa",
        "libertad de movimiento", "mundo enorme",
    ],
    "Exploration": [
        "Exploration", "exploración", "exploracion", "explorar",
        "descubrir", "descubrimiento", "aventura exploración",
    ],
    "Sandbox": [
        "Sandbox", "sandbox", "arenero", "libertad", "sin objetivos fijos",
        "haz lo que quieras", "creative mode",
    ],
    # ── Construcción / Crafting ───────────────────────────────────────────────
    "Building": [
        "Building", "construcción", "construir", "building", "edificar",
        "crear estructuras", "base building",
    ],
    "Base-Building": [
        "Base-Building", "base building", "construir base",
        "base de operaciones", "construir campamento",
    ],
    "Crafting": [
        "Crafting", "crafting", "crafteo", "fabricar", "crear objetos",
        "fabricación", "elaborar", "hacer items", "craftear",
    ],
    "Farming Sim": [
        "Farming Sim", "granja", "farming sim", "cosecha", "agricultura",
        "cultivar", "cultivos", "stardew valley like", "juego de granja",
        "agricola", "agrícola", "sembrar", "cosechar",
    ],
    "City Builder": [
        "City Builder", "ciudad", "construir ciudad", "city builder",
        "alcalde", "urbanismo", "planificación urbana", "simcity like",
    ],
    # ── Ciencia Ficción / Fantasía ────────────────────────────────────────────
    "Sci-fi": [
        "Sci-fi", "ciencia ficción", "ciencia ficcion", "sci-fi", "scifi",
        "futurista", "naves espaciales", "tecnología avanzada",
        "robots", "inteligencia artificial", "cyberpunk lite",
    ],
    "Cyberpunk": [
        "Cyberpunk", "cyberpunk", "ciberpunk", "neo noir", "futuro oscuro",
        "megaciudad", "implantes", "hacking", "hackers", "dystopian future",
    ],
    "Fantasy": [
        "Fantasy", "fantasía", "fantasia", "fantasy", "magia", "magos",
        "dragones", "elfos", "enanos", "orcos", "medieval mágico",
        "medieval magico", "reino mágico", "hechizos",
    ],
    "Dark Fantasy": [
        "Dark Fantasy", "dark fantasy", "fantasía oscura", "fantasia oscura",
        "souls like ambientación", "fantasía sombría", "lore oscuro",
        "oscuro y brutal",
    ],
    "Medieval": [
        "Medieval", "medieval", "castillos", "espadas", "caballeros",
        "rey", "reinos", "épica medieval", "epica medieval",
        "edad media", "señores feudales",
    ],
    "Space": [
        "Space", "espacio", "galaxia", "naves espaciales", "space",
        "cosmos", "exploración espacial", "astronauta", "alienígenas",
        "interstellar", "sci fi espacial",
    ],
    "Steampunk": [
        "Steampunk", "steampunk", "vapor punk", "victoriano", "máquinas de vapor",
        "retrofuturista", "estética steampunk",
    ],
    # ── Puzzle / Estrategia ───────────────────────────────────────────────────
    "Puzzle": [
        "Puzzle", "puzzle", "rompecabezas", "puzle", "acertijo",
        "pensar", "lógica", "desafío mental", "brain game",
        "enigma", "laberinto",
    ],
    "Strategy": [
        "Strategy", "estrategia", "tactico", "táctico",
        "planificar", "gestión", "gestion",
    ],
    "Turn-Based": [
        "Turn-Based", "por turnos", "turnos", "turn based",
        "por turno", "estrategia por turnos",
    ],
    "Tower Defense": [
        "Tower Defense", "tower defense", "defensa de torres",
        "proteger base", "defender oleadas",
    ],
    "4X": [
        "4X", "4x", "conquistar", "colonizar", "expandir",
        "civilización like", "civ like",
    ],
    "Grand Strategy": [
        "Grand Strategy", "gran estrategia", "grand strategy",
        "hearts of iron like", "europa universalis like",
    ],
    # ── Roguelike / Dungeon ───────────────────────────────────────────────────
    "Rogue-like": [
        "Rogue-like", "roguelike", "roguelite", "rogue like", "rogue-like",
        "permadeath", "muerte permanente", "generacion procedural",
        "generación procedural", "aleatatorio", "hades like",
    ],
    "Rogue-lite": [
        "Rogue-lite", "roguelite", "rogue lite", "semi roguelike",
        "con progresión", "roguelike suave",
    ],
    "Dungeon Crawler": [
        "Dungeon Crawler", "dungeon crawler", "mazmorras", "mazmorra",
        "explorar mazmorras", "dungeon", "rpg mazmorras",
    ],
    "Metroidvania": [
        "Metroidvania", "metroidvania", "metroid like", "castlevania like",
        "exploración no lineal", "backtracking", "habilidades nuevas",
        "mapa interconectado",
    ],
    # ── Plataformas / 2D ─────────────────────────────────────────────────────
    "Platformer": [
        "Platformer", "plataformas", "platformer", "saltos", "plataformero",
        "juego de plataformas", "correr y saltar", "mario like",
    ],
    "Pixel Graphics": [
        "Pixel Graphics", "pixel art", "retro", "8-bit", "16-bit",
        "pixelados", "pixelado", "gráficos retro", "pixel",
        "estética retro", "old school gráficos",
    ],
    "2D": [
        "2D", "2d", "dos dimensiones", "vista lateral", "lado a lado",
        "juego 2d", "plano",
    ],
    # ── Anime / Cultura pop ───────────────────────────────────────────────────
    "Anime": [
        "Anime", "anime", "japonés", "japones", "otaku", "manga",
        "anime style", "estilo anime", "dibujos animados japoneses",
        "waifus", "visual novel anime",
    ],
    # ── Dificultad ────────────────────────────────────────────────────────────
    "Difficult": [
        "Difficult", "difícil", "dificil", "hard", "souls-like", "souls like",
        "soulslike", "retador", "desafiante", "muy complicado",
        "extremadamente difícil", "frustrantemente difícil",
        "elden ring like", "dark souls like",
    ],
    "Perma Death": [
        "Perma Death", "muerte permanente", "permadeath", "perma death",
        "una vida", "sin saves", "sin guardar",
    ],
    # ── Miscelánea importante ──────────────────────────────────────────────────
    "Atmospheric": [
        "Atmospheric", "atmosférico", "atmosferico", "inmersivo",
        "inmersiva", "ambiente", "sensación de inmersión",
        "con atmósfera", "mood", "estético",
    ],
    "Funny": [
        "Funny", "gracioso", "divertido", "humor", "cómico", "comico",
        "risas", "absurdo", "chistoso", "hilarante",
    ],
    "Relaxing": [
        "Relaxing", "relajante", "tranquilo", "calmado", "sin estrés",
        "sin estres", "para desestresarse", "casual relajado",
        "jugar y relajarse",
    ],
    "Visual Novel": [
        "Visual Novel", "novela visual", "visual novel", "novela interactiva",
        "libro interactivo", "leer y decidir",
    ],
    "Dating Sim": [
        "Dating Sim", "dating sim", "simulador de citas",
        "romance", "relaciones", "enamorarse en el juego",
    ],
    "Singleplayer": [
        "Singleplayer", "un jugador", "solo", "juego solo",
        "single player", "singleplayer", "para un solo jugador",
        "modo historia", "un solo jugador",
    ],
    "VR": [
        "VR", "vr", "realidad virtual", "virtual reality", "oculus",
        "meta quest", "gafas vr",
    ],
    "Parkour": [
        "Parkour", "parkour", "escalar", "moverse libre",
        "dying light like", "mirrors edge like",
    ],
    "Rhythm": [
        "Rhythm", "ritmo", "música", "musica", "beat", "ritmos",
        "juego musical", "juego de ritmo",
    ],
    "Clicker": [
        "Clicker", "clicker", "idle", "clicker game", "idle game",
        "juego incremental", "sin hacer nada",
    ],
    "Walking Simulator": [
        "Walking Simulator", "walking simulator", "caminar y explorar",
        "simulator caminar", "narrativo sin acción", "experiencia narrativa",
    ],
    "War": [
        "War", "guerra", "militar", "bélico", "belico", "combate bélico",
        "segunda guerra mundial", "world war", "ejercito",
    ],
    "Historical": [
        "Historical", "histórico", "historico", "historia real",
        "basado en hechos", "antiguedad", "antigüedad",
    ],
    "Noir": [
        "Noir", "noir", "policial", "investigación", "investigacion",
        "detective", "crimen", "criminal", "misterio policial",
    ],
    "Mystery": [
        "Mystery", "misterio", "mystery", "enigma", "resolver",
        "investigar", "caso criminal",
    ],
    "Demons": [
        "Demons", "demonios", "demonio", "infernal", "infierno",
        "diablo like", "doom like", "bestias infernales",
    ],
    "Great Soundtrack": [
        "Great Soundtrack", "buena música", "buena musica",
        "banda sonora", "ost", "soundtrack", "excelente música",
    ],
    "Local Multiplayer": [
        "Local Multiplayer", "multijugador local", "local",
        "en el mismo pc", "en la misma pantalla",
    ],
}

# ---------------------------------------------------------------------------
# Utterances — ~300 frases de ejemplo etiquetadas
# ---------------------------------------------------------------------------
# Formato: {
#   "text": str,
#   "intent": str,
#   "entities": {substring_in_text: "entity_name:role"}
# }
# Nota: el entity_name se usa para buscar el rol en Wit.ai. Si la entidad
# tiene role igual a su nombre (ej: tags:tags), en Wit.ai se registra como
# "entityname:rolename" → para tags es "tags:tags", para genre "genre:genre".
# ---------------------------------------------------------------------------
RAW_UTTERANCES = [
    # ── SEARCH_GAME: Terror / Horror ──────────────────────────────────────────
    {"text": "Recomiéndame juegos de terror", "intent": "search_game", "entities": {"terror": "tags:Horror"}},
    {"text": "Quiero juegos de miedo", "intent": "search_game", "entities": {"miedo": "tags:Horror"}},
    {"text": "Busco algo aterrador para jugar", "intent": "search_game", "entities": {"aterrador": "tags:Horror"}},
    {"text": "Dame juegos de horror psicológico", "intent": "search_game", "entities": {"horror psicológico": "tags:Psychological Horror"}},
    {"text": "Juegos de terror psicológico ambientados en el espacio", "intent": "search_game", "entities": {"terror psicológico": "tags:Psychological Horror", "espacio": "tags:Space"}},
    {"text": "Quiero algo de terror y supervivencia tipo Resident Evil", "intent": "search_game", "entities": {"terror": "tags:Horror", "supervivencia": "tags:Survival"}},
    {"text": "Juegos de survival horror", "intent": "search_game", "entities": {"survival horror": "tags:Survival Horror"}},
    {"text": "Algo perturbador y oscuro para jugar solo", "intent": "search_game", "entities": {"perturbador": "tags:Psychological Horror"}},
    {"text": "Juegos de zombies que den miedo", "intent": "search_game", "entities": {"zombies": "tags:Zombies", "miedo": "tags:Horror"}},
    {"text": "Quiero algo de apocalipsis zombie", "intent": "search_game", "entities": {"apocalipsis zombie": "tags:Zombies"}},
    {"text": "Dame juegos de muertos vivientes", "intent": "search_game", "entities": {"muertos vivientes": "tags:Zombies"}},
    {"text": "Quiero juegos postapocalípticos", "intent": "search_game", "entities": {"postapocalípticos": "tags:Post-apocalyptic"}},
    {"text": "Algo de wasteland y fin del mundo", "intent": "search_game", "entities": {"fin del mundo": "tags:Post-apocalyptic"}},

    # ── SEARCH_GAME: Supervivencia ────────────────────────────────────────────
    {"text": "Juegos de supervivencia", "intent": "search_game", "entities": {"supervivencia": "tags:Survival"}},
    {"text": "Quiero un juego de sobrevivencia", "intent": "search_game", "entities": {"sobrevivencia": "tags:Survival"}},
    {"text": "Algo de survival con crafting", "intent": "search_game", "entities": {"survival": "tags:Survival", "crafting": "tags:Crafting"}},
    {"text": "Juegos de supervivencia co-op", "intent": "search_game", "entities": {"supervivencia": "tags:Survival", "co-op": "tags:Co-op"}},
    {"text": "Quiero sobrevivir en un mundo abierto", "intent": "search_game", "entities": {"sobrevivir": "tags:Survival", "mundo abierto": "tags:Open World"}},
    {"text": "Juego de survival crafting en mundo abierto", "intent": "search_game", "entities": {"survival": "tags:Survival", "crafting": "tags:Crafting", "mundo abierto": "tags:Open World"}},

    # ── SEARCH_GAME: Mundo abierto / Exploración ──────────────────────────────
    {"text": "Quiero algo de mundo abierto", "intent": "search_game", "entities": {"mundo abierto": "tags:Open World"}},
    {"text": "Juegos para explorar el mapa", "intent": "search_game", "entities": {"explorar": "tags:Exploration"}},
    {"text": "Algo con exploración libre", "intent": "search_game", "entities": {"exploración libre": "tags:Open World"}},
    {"text": "Un sandbox de mundo abierto", "intent": "search_game", "entities": {"sandbox": "tags:Sandbox", "mundo abierto": "tags:Open World"}},
    {"text": "Quiero un juego de exploración espacial", "intent": "search_game", "entities": {"exploración": "tags:Exploration", "espacial": "tags:Space"}},
    {"text": "Algo para explorar mazmorras", "intent": "search_game", "entities": {"explorar mazmorras": "tags:Dungeon Crawler"}},

    # ── SEARCH_GAME: Acción / Shooters ────────────────────────────────────────
    {"text": "Un shooter multijugador", "intent": "search_game", "entities": {"shooter": "tags:Shooter", "multijugador": "tags:Multiplayer"}},
    {"text": "Quiero un FPS bueno", "intent": "search_game", "entities": {"FPS": "tags:FPS"}},
    {"text": "Dame juegos de disparos en primera persona", "intent": "search_game", "entities": {"primera persona": "tags:FPS"}},
    {"text": "Juegos de tiros online", "intent": "search_game", "entities": {"tiros": "tags:Shooter", "online": "tags:Multiplayer"}},
    {"text": "Algo de acción con muchos disparos", "intent": "search_game", "entities": {"disparos": "tags:Shooter"}},
    {"text": "Quiero un hack and slash", "intent": "search_game", "entities": {"hack and slash": "tags:Hack and Slash"}},
    {"text": "Juegos de peleas uno contra uno", "intent": "search_game", "entities": {"peleas": "tags:Fighting"}},
    {"text": "Un juego de lucha competitivo", "intent": "search_game", "entities": {"lucha": "tags:Fighting", "competitivo": "tags:Competitive"}},
    {"text": "Juegos de acción tipo God of War", "intent": "search_game", "entities": {}},
    {"text": "Quiero algo con acción rápida y combate", "intent": "search_game", "entities": {}},

    # ── SEARCH_GAME: RPG ──────────────────────────────────────────────────────
    {"text": "Busco un RPG de fantasía", "intent": "search_game", "entities": {"fantasía": "tags:Fantasy"}},
    {"text": "Quiero un buen RPG de acción", "intent": "search_game", "entities": {"RPG": "tags:Action RPG"}},
    {"text": "Juegos JRPG como Final Fantasy", "intent": "search_game", "entities": {"JRPG": "tags:JRPG"}},
    {"text": "Algo tipo Skyrim con mundo abierto", "intent": "search_game", "entities": {"mundo abierto": "tags:Open World"}},
    {"text": "Un RPG con buena historia y muchas decisiones", "intent": "search_game", "entities": {"historia": "tags:Story Rich", "decisiones": "tags:Choices Matter"}},
    {"text": "Quiero un RPG por turnos", "intent": "search_game", "entities": {"por turnos": "tags:Turn-Based"}},
    {"text": "Dame un role playing game con dragones", "intent": "search_game", "entities": {"dragones": "tags:Fantasy"}},
    {"text": "Juegos de rol con magia y elfos", "intent": "search_game", "entities": {"magia": "tags:Fantasy"}},
    {"text": "Un JRPG japonés con anime", "intent": "search_game", "entities": {"JRPG": "tags:JRPG", "anime": "tags:Anime"}},

    # ── SEARCH_GAME: Estrategia ────────────────────────────────────────────────
    {"text": "Busco juegos de estrategia", "intent": "search_game", "entities": {"estrategia": "genre:Strategy"}},
    {"text": "Un juego de estrategia por turnos", "intent": "search_game", "entities": {"estrategia": "genre:Strategy", "por turnos": "tags:Turn-Based"}},
    {"text": "Algo táctico para pensar bien las decisiones", "intent": "search_game", "entities": {"táctico": "genre:Strategy"}},
    {"text": "Juego de gran estrategia tipo Civilization", "intent": "search_game", "entities": {"gran estrategia": "tags:Grand Strategy"}},
    {"text": "Quiero un 4X para conquista", "intent": "search_game", "entities": {"4X": "tags:4X"}},
    {"text": "Dame algo de tower defense", "intent": "search_game", "entities": {"tower defense": "tags:Tower Defense"}},
    {"text": "Un juego de defensa de torres", "intent": "search_game", "entities": {"defensa de torres": "tags:Tower Defense"}},
    {"text": "Juegos de estrategia en tiempo real", "intent": "search_game", "entities": {"estrategia": "genre:Strategy"}},

    # ── SEARCH_GAME: Cooperativo / Multijugador ───────────────────────────────
    {"text": "Algo para jugar con amigos", "intent": "search_game", "entities": {"amigos": "tags:Co-op"}},
    {"text": "Quiero un juego cooperativo online", "intent": "search_game", "entities": {"cooperativo": "tags:Co-op", "online": "tags:Online Co-Op"}},
    {"text": "Un coop para jugar con mi pareja", "intent": "search_game", "entities": {"coop": "tags:Co-op"}},
    {"text": "Juego en pantalla dividida para dos jugadores", "intent": "search_game", "entities": {"pantalla dividida": "tags:Local Co-Op"}},
    {"text": "Quiero algo en co-op local en el sofá", "intent": "search_game", "entities": {"co-op local": "tags:Local Co-Op"}},
    {"text": "Un multijugador competitivo online", "intent": "search_game", "entities": {"multijugador": "tags:Multiplayer", "competitivo": "tags:Competitive"}},
    {"text": "Algo de battle royale tipo Fortnite", "intent": "search_game", "entities": {"battle royale": "tags:Battle Royale"}},
    {"text": "Juego de battle royal para jugar con mis panas", "intent": "search_game", "entities": {"battle royal": "tags:Battle Royale"}},
    {"text": "Quiero algo de PvP intenso", "intent": "search_game", "entities": {"PvP": "tags:PvP"}},

    # ── SEARCH_GAME: Construcción / Crafting / Granja ─────────────────────────
    {"text": "Juegos de construcción tipo Minecraft", "intent": "search_game", "entities": {"construcción": "tags:Building"}},
    {"text": "Algo de crafting y construir bases", "intent": "search_game", "entities": {"crafting": "tags:Crafting", "construir bases": "tags:Base-Building"}},
    {"text": "Un juego de granja relajante", "intent": "search_game", "entities": {"granja": "tags:Farming Sim", "relajante": "tags:Relaxing"}},
    {"text": "Quiero algo tipo Stardew Valley", "intent": "search_game", "entities": {"granja": "tags:Farming Sim"}},
    {"text": "Juego de cultivar y construir", "intent": "search_game", "entities": {"cultivar": "tags:Farming Sim", "construir": "tags:Building"}},
    {"text": "Algo de city builder para construir ciudades", "intent": "search_game", "entities": {"city builder": "tags:City Builder"}},
    {"text": "Un simulador de granja cooperativo", "intent": "search_game", "entities": {"granja": "tags:Farming Sim", "cooperativo": "tags:Co-op"}},
    {"text": "Quiero algo de granjas para jugar con amigos", "intent": "search_game", "entities": {"granjas": "tags:Farming Sim", "amigos": "tags:Co-op"}},

    # ── SEARCH_GAME: Plataformas / 2D / Pixel Art ────────────────────────────
    {"text": "Un juego de plataformas difícil", "intent": "search_game", "entities": {"plataformas": "tags:Platformer", "difícil": "tags:Difficult"}},
    {"text": "Juegos indie con pixel art", "intent": "search_game", "entities": {"pixel art": "tags:Pixel Graphics"}},
    {"text": "Algo retro con gráficos de 8 bits", "intent": "search_game", "entities": {"retro": "tags:Pixel Graphics", "8 bits": "tags:Pixel Graphics"}},
    {"text": "Un platformer tipo Celeste", "intent": "search_game", "entities": {"platformer": "tags:Platformer"}},
    {"text": "Juegos 2D de plataformas con buen pixel art", "intent": "search_game", "entities": {"plataformas": "tags:Platformer", "pixel art": "tags:Pixel Graphics"}},
    {"text": "Quiero algo retro de plataformas", "intent": "search_game", "entities": {"retro": "tags:Pixel Graphics", "plataformas": "tags:Platformer"}},

    # ── SEARCH_GAME: Sci-Fi / Cyberpunk / Espacio ─────────────────────────────
    {"text": "Algo de ciencia ficción futurista", "intent": "search_game", "entities": {"ciencia ficción": "tags:Sci-fi", "futurista": "tags:Sci-fi"}},
    {"text": "Juegos de naves espaciales", "intent": "search_game", "entities": {"naves espaciales": "tags:Space"}},
    {"text": "Quiero algo cyberpunk como Cyberpunk 2077", "intent": "search_game", "entities": {"cyberpunk": "tags:Cyberpunk"}},
    {"text": "Un RPG de ciencia ficción con robots", "intent": "search_game", "entities": {"ciencia ficción": "tags:Sci-fi"}},
    {"text": "Algo ambientado en el espacio exterior", "intent": "search_game", "entities": {"espacio": "tags:Space"}},
    {"text": "Juegos de galaxias y exploración espacial", "intent": "search_game", "entities": {"exploración": "tags:Exploration", "espacial": "tags:Space"}},
    {"text": "Quiero algo de hacking y dystopía", "intent": "search_game", "entities": {"hacking": "tags:Cyberpunk"}},

    # ── SEARCH_GAME: Fantasía / Medieval ─────────────────────────────────────
    {"text": "Algo de fantasía con dragones y magia", "intent": "search_game", "entities": {"fantasía": "tags:Fantasy", "dragones": "tags:Fantasy", "magia": "tags:Fantasy"}},
    {"text": "Juegos medievales de espadas", "intent": "search_game", "entities": {"medievales": "tags:Medieval", "espadas": "tags:Medieval"}},
    {"text": "Quiero algo de caballeros y castillos", "intent": "search_game", "entities": {"castillos": "tags:Medieval"}},
    {"text": "Un juego de dark fantasy tipo Dark Souls", "intent": "search_game", "entities": {"dark fantasy": "tags:Dark Fantasy"}},
    {"text": "Algo con elfos, enanos y orcos", "intent": "search_game", "entities": {"elfos": "tags:Fantasy"}},

    # ── SEARCH_GAME: Souls-like / Difícil / Rogue ────────────────────────────
    {"text": "Juegos difíciles tipo Dark Souls", "intent": "search_game", "entities": {"difíciles": "tags:Difficult"}},
    {"text": "Algo souls-like muy retador", "intent": "search_game", "entities": {"souls-like": "tags:Difficult"}},
    {"text": "Quiero un roguelike para morir mucho", "intent": "search_game", "entities": {"roguelike": "tags:Rogue-like"}},
    {"text": "Un juego de permadeath y generación aleatoria", "intent": "search_game", "entities": {"permadeath": "tags:Rogue-like"}},
    {"text": "Juegos difíciles tipo rogue-like", "intent": "search_game", "entities": {"difíciles": "tags:Difficult", "rogue-like": "tags:Rogue-like"}},
    {"text": "Un roguelite tipo Hades", "intent": "search_game", "entities": {"roguelite": "tags:Rogue-lite"}},
    {"text": "Metroidvania de plataformas", "intent": "search_game", "entities": {"Metroidvania": "tags:Metroidvania", "plataformas": "tags:Platformer"}},

    # ── SEARCH_GAME: Puzzle / Historia ────────────────────────────────────────
    {"text": "Juegos de puzzle para pensar", "intent": "search_game", "entities": {"puzzle": "tags:Puzzle"}},
    {"text": "Algo de rompecabezas lógicos", "intent": "search_game", "entities": {"rompecabezas": "tags:Puzzle"}},
    {"text": "Un juego con muy buena historia", "intent": "search_game", "entities": {"historia": "tags:Story Rich"}},
    {"text": "Quiero algo con narrativa profunda", "intent": "search_game", "entities": {"narrativa": "tags:Story Rich"}},
    {"text": "Una novela visual romántica", "intent": "search_game", "entities": {"novela visual": "tags:Visual Novel", "romántica": "tags:Dating Sim"}},
    {"text": "Juego con muchos finales alternativos", "intent": "search_game", "entities": {"finales alternativos": "tags:Multiple Endings"}},
    {"text": "Algo donde mis decisiones importen", "intent": "search_game", "entities": {"decisiones importen": "tags:Choices Matter"}},

    # ── SEARCH_GAME: Anime / Cultura ──────────────────────────────────────────
    {"text": "Juegos de anime estilo JRPG", "intent": "search_game", "entities": {"anime": "tags:Anime", "JRPG": "tags:JRPG"}},
    {"text": "Algo con estética anime", "intent": "search_game", "entities": {"anime": "tags:Anime"}},
    {"text": "Un RPG japonés con mucho anime", "intent": "search_game", "entities": {"japonés": "tags:Anime", "anime": "tags:Anime"}},
    {"text": "Juego de waifus", "intent": "search_game", "entities": {}},
    {"text": "Algo tipo Dark Souls pero con estetica anime", "intent": "search_game", "entities": {"anime": "tags:Anime", "Souls": "tags:Difficult"}},

    # ── SEARCH_GAME: Simulación / Casual ──────────────────────────────────────
    {"text": "Un juego de simulación de vida", "intent": "search_game", "entities": {"simulación": "genre:Simulation"}},
    {"text": "Algo relajante y sin estrés", "intent": "search_game", "entities": {"relajante": "tags:Relaxing"}},
    {"text": "Juegos casuales para descansar", "intent": "search_game", "entities": {"casuales": "genre:Casual"}},
    {"text": "Quiero un simulador de autos de carreras", "intent": "search_game", "entities": {"autos": "genre:Racing"}},
    {"text": "Un juego de manejar autos", "intent": "search_game", "entities": {"manejar autos": "genre:Racing"}},
    {"text": "Simulador de vuelo", "intent": "search_game", "entities": {"Simulador": "genre:Simulation"}},
    {"text": "Un juego de deportes de futbol", "intent": "search_game", "entities": {"deportes": "genre:Sports", "futbol": "genre:Sports"}},

    # ── SEARCH_GAME: Con precio / Oferta ──────────────────────────────────────
    {"text": "Juegos baratos de menos de 10 dolares", "intent": "search_game", "entities": {}},
    {"text": "Algo económico de terror", "intent": "search_game", "entities": {"terror": "tags:Horror"}},
    {"text": "Juegos de RPG en oferta", "intent": "search_game", "entities": {}},
    {"text": "Quiero algo con descuento ahora mismo", "intent": "search_game", "entities": {}},
    {"text": "Co-op para jugar con amigos, menos de 15 dólares", "intent": "search_game", "entities": {"amigos": "tags:Co-op"}},
    {"text": "Juegos de terror baratos", "intent": "search_game", "entities": {"terror": "tags:Horror"}},
    {"text": "Algo de estrategia que no sea muy caro", "intent": "search_game", "entities": {"estrategia": "genre:Strategy"}},
    {"text": "Juegos gratis multijugador", "intent": "search_game", "entities": {"multijugador": "tags:Multiplayer"}},
    {"text": "Algo free to play de battle royale", "intent": "search_game", "entities": {"battle royale": "tags:Battle Royale"}},

    # ── SEARCH_GAME: Con puntuación / Calidad ─────────────────────────────────
    {"text": "Juegos muy bien valorados de RPG", "intent": "search_game", "entities": {}},
    {"text": "Algo con buenas reviews de terror", "intent": "search_game", "entities": {"terror": "tags:Horror"}},
    {"text": "Quiero el mejor juego de estrategia", "intent": "search_game", "entities": {"estrategia": "genre:Strategy"}},
    {"text": "Un roguelike con buenas puntuaciones", "intent": "search_game", "entities": {"roguelike": "tags:Rogue-like"}},

    # ── SEARCH_GAME: Combinaciones mixtas ────────────────────────────────────
    {"text": "RPG de acción con mundo abierto y buena historia", "intent": "search_game", "entities": {"mundo abierto": "tags:Open World", "historia": "tags:Story Rich"}},
    {"text": "Survival de terror cooperativo online", "intent": "search_game", "entities": {"terror": "tags:Horror", "cooperativo": "tags:Co-op", "online": "tags:Online Co-Op"}},
    {"text": "Puzzle aventura con buena narrativa", "intent": "search_game", "entities": {"Puzzle": "tags:Puzzle", "narrativa": "tags:Story Rich"}},
    {"text": "Shooter con historia y modo historia", "intent": "search_game", "entities": {"Shooter": "tags:Shooter", "historia": "tags:Story Rich"}},
    {"text": "Roguelike de fantasía medieval difícil", "intent": "search_game", "entities": {"Roguelike": "tags:Rogue-like", "fantasía": "tags:Fantasy", "difícil": "tags:Difficult"}},
    {"text": "Un FPS cooperativo de ciencia ficción", "intent": "search_game", "entities": {"FPS": "tags:FPS", "cooperativo": "tags:Co-op", "ciencia ficción": "tags:Sci-fi"}},
    {"text": "Indie de pixel art relajante con granja", "intent": "search_game", "entities": {"pixel art": "tags:Pixel Graphics", "relajante": "tags:Relaxing", "granja": "tags:Farming Sim"}},
    {"text": "Un souls-like con ambientación de fantasía oscura", "intent": "search_game", "entities": {"souls-like": "tags:Difficult", "fantasía oscura": "tags:Dark Fantasy"}},

    # ── REFINE_SEARCH ─────────────────────────────────────────────────────────
    {"text": "Mejor que sea más barato", "intent": "refine_search", "entities": {}},
    {"text": "Lo mismo pero más económico", "intent": "refine_search", "entities": {}},
    {"text": "Que sea cooperativo", "intent": "refine_search", "entities": {"cooperativo": "tags:Co-op"}},
    {"text": "Lo mismo pero cooperativo", "intent": "refine_search", "entities": {"cooperativo": "tags:Co-op"}},
    {"text": "Dame más opciones", "intent": "refine_search", "entities": {}},
    {"text": "Busco algo diferente", "intent": "refine_search", "entities": {}},
    {"text": "Muéstrame más juegos", "intent": "refine_search", "entities": {}},
    {"text": "Que no sea tan difícil", "intent": "refine_search", "entities": {}},
    {"text": "Algo similar pero para un jugador", "intent": "refine_search", "entities": {"un jugador": "tags:Singleplayer"}},
    {"text": "Eso pero con pixel art", "intent": "refine_search", "entities": {"pixel art": "tags:Pixel Graphics"}},
    {"text": "Más opciones por favor", "intent": "refine_search", "entities": {}},
    {"text": "Otro estilo", "intent": "refine_search", "entities": {}},
    {"text": "Que sea gratis", "intent": "refine_search", "entities": {}},
    {"text": "Algo de ese estilo pero más corto", "intent": "refine_search", "entities": {}},
    {"text": "Lo mismo pero con mejor puntaje", "intent": "refine_search", "entities": {}},
    {"text": "Que tenga más de 80 por ciento de reviews positivas", "intent": "refine_search", "entities": {}},
    {"text": "Prefiero algo de terror", "intent": "refine_search", "entities": {"terror": "tags:Horror"}},
    {"text": "Que tenga modo online", "intent": "refine_search", "entities": {"online": "tags:Multiplayer"}},
    {"text": "Que sea indie", "intent": "refine_search", "entities": {"indie": "genre:Indie"}},
    {"text": "Algo con co-op que no cueste mucho", "intent": "refine_search", "entities": {"co-op": "tags:Co-op"}},
    {"text": "Con descuento si es posible", "intent": "refine_search", "entities": {}},

    # ── CHECK_PRICE ───────────────────────────────────────────────────────────
    {"text": "¿Cuánto cuesta Elden Ring?", "intent": "check_price", "entities": {"Elden Ring": "game_name"}},
    {"text": "Precio de Stardew Valley", "intent": "check_price", "entities": {"Stardew Valley": "game_name"}},
    {"text": "¿Cuánto vale Minecraft en Chile?", "intent": "check_price", "entities": {"Minecraft": "game_name"}},
    {"text": "¿Qué precio tiene Cyberpunk 2077?", "intent": "check_price", "entities": {"Cyberpunk 2077": "game_name"}},
    {"text": "Cuánto sale Hollow Knight", "intent": "check_price", "entities": {"Hollow Knight": "game_name"}},
    {"text": "Precio de The Witcher 3", "intent": "check_price", "entities": {"The Witcher 3": "game_name"}},
    {"text": "¿Está en oferta Red Dead Redemption 2?", "intent": "check_price", "entities": {"Red Dead Redemption 2": "game_name"}},
    {"text": "Cuánto cuesta GTA V", "intent": "check_price", "entities": {"GTA V": "game_name"}},
    {"text": "Precio de Hades", "intent": "check_price", "entities": {"Hades": "game_name"}},
    {"text": "¿A cuánto está Dead by Daylight?", "intent": "check_price", "entities": {"Dead by Daylight": "game_name"}},
    {"text": "Quiero saber el precio de Baldur's Gate 3", "intent": "check_price", "entities": {"Baldur's Gate 3": "game_name"}},
    {"text": "¿Cuánto sale Dark Souls?", "intent": "check_price", "entities": {"Dark Souls": "game_name"}},
    {"text": "Dime el precio de Terraria", "intent": "check_price", "entities": {"Terraria": "game_name"}},
    {"text": "¿Tiene descuento RimWorld?", "intent": "check_price", "entities": {"RimWorld": "game_name"}},
    {"text": "Precio actual de Monster Hunter World", "intent": "check_price", "entities": {"Monster Hunter World": "game_name"}},

    # ── COMPARE_GAMES ─────────────────────────────────────────────────────────
    {"text": "Compara Elden Ring con Dark Souls", "intent": "compare_games", "entities": {"Elden Ring": "game_name", "Dark Souls": "game_name"}},
    {"text": "¿Qué es mejor, Hollow Knight o Ori and the Blind Forest?", "intent": "compare_games", "entities": {"Hollow Knight": "game_name", "Ori and the Blind Forest": "game_name"}},
    {"text": "Diferencias entre The Witcher 3 y Skyrim", "intent": "compare_games", "entities": {"The Witcher 3": "game_name", "Skyrim": "game_name"}},
    {"text": "Compara Hades con Dead Cells", "intent": "compare_games", "entities": {"Hades": "game_name", "Dead Cells": "game_name"}},
    {"text": "¿Cuál es mejor, Minecraft o Terraria?", "intent": "compare_games", "entities": {"Minecraft": "game_name", "Terraria": "game_name"}},
    {"text": "Compara Stardew Valley con Farming Simulator", "intent": "compare_games", "entities": {"Stardew Valley": "game_name", "Farming Simulator": "game_name"}},
    {"text": "¿Dark Souls o Sekiro, cuál recomiendas?", "intent": "compare_games", "entities": {"Dark Souls": "game_name", "Sekiro": "game_name"}},
    {"text": "Diferencias entre RimWorld y Dwarf Fortress", "intent": "compare_games", "entities": {"RimWorld": "game_name", "Dwarf Fortress": "game_name"}},

    # ── CASUAL_CHAT ───────────────────────────────────────────────────────────
    {"text": "Hola", "intent": "casual_chat", "entities": {}},
    {"text": "Buenas", "intent": "casual_chat", "entities": {}},
    {"text": "Buenos días", "intent": "casual_chat", "entities": {}},
    {"text": "Qué tal", "intent": "casual_chat", "entities": {}},
    {"text": "Gracias", "intent": "casual_chat", "entities": {}},
    {"text": "Muchas gracias", "intent": "casual_chat", "entities": {}},
    {"text": "Perfecto, gracias", "intent": "casual_chat", "entities": {}},
    {"text": "Chao", "intent": "casual_chat", "entities": {}},
    {"text": "Hasta luego", "intent": "casual_chat", "entities": {}},
    {"text": "Adiós", "intent": "casual_chat", "entities": {}},
    {"text": "Nos vemos", "intent": "casual_chat", "entities": {}},
    {"text": "Ok", "intent": "casual_chat", "entities": {}},
    {"text": "Entendido", "intent": "casual_chat", "entities": {}},
    {"text": "Me gusta esa recomendación", "intent": "casual_chat", "entities": {}},
    {"text": "Excelente", "intent": "casual_chat", "entities": {}},
    {"text": "No me gustó ese juego", "intent": "casual_chat", "entities": {}},
    {"text": "Qué aburrido", "intent": "casual_chat", "entities": {}},
    {"text": "Ya lo tengo ese", "intent": "casual_chat", "entities": {}},
    {"text": "Está muy caro", "intent": "casual_chat", "entities": {}},
    {"text": "Estoy aburrido", "intent": "casual_chat", "entities": {}},

    # ── ASK_CAPABILITIES ─────────────────────────────────────────────────────
    {"text": "¿Qué puedes hacer?", "intent": "ask_capabilities", "entities": {}},
    {"text": "Ayuda", "intent": "ask_capabilities", "entities": {}},
    {"text": "Help", "intent": "ask_capabilities", "entities": {}},
    {"text": "¿Para qué sirves?", "intent": "ask_capabilities", "entities": {}},
    {"text": "¿Qué eres?", "intent": "ask_capabilities", "entities": {}},
    {"text": "Comandos", "intent": "ask_capabilities", "entities": {}},
    {"text": "¿Cómo funciona esto?", "intent": "ask_capabilities", "entities": {}},
    {"text": "¿Puedes recomendarme juegos?", "intent": "ask_capabilities", "entities": {}},
    {"text": "¿Qué juegos puedes recomendar?", "intent": "ask_capabilities", "entities": {}},
    {"text": "Instrucciones", "intent": "ask_capabilities", "entities": {}},
    {"text": "¿Cómo te uso?", "intent": "ask_capabilities", "entities": {}},
    {"text": "¿Qué tipos de búsqueda soportas?", "intent": "ask_capabilities", "entities": {}},

    # ── FIND_SIMILAR ─────────────────────────────────────────────────────
    {"text": "Dame juegos similares a Metal Gear Solid", "intent": "find_similar", "entities": {"Metal Gear Solid": "game_name"}},
    {"text": "Busco algo parecido a The Last of Us", "intent": "find_similar", "entities": {"The Last of Us": "game_name"}},
    {"text": "Recomiéndame juegos tipo God of War", "intent": "find_similar", "entities": {"God of War": "game_name"}},
    {"text": "Juegos que se parezcan a Minecraft", "intent": "find_similar", "entities": {"Minecraft": "game_name"}},
    {"text": "Quiero jugar algo como Stardew Valley", "intent": "find_similar", "entities": {"Stardew Valley": "game_name"}},
    {"text": "¿Qué juegos hay similares a Red Dead Redemption 2?", "intent": "find_similar", "entities": {"Red Dead Redemption 2": "game_name"}},
    {"text": "Juegos del mismo estilo que Hollow Knight", "intent": "find_similar", "entities": {"Hollow Knight": "game_name"}},
    {"text": "Algo igual a Elden Ring", "intent": "find_similar", "entities": {"Elden Ring": "game_name"}},
    {"text": "Dame opciones parecidas a GTA V", "intent": "find_similar", "entities": {"GTA V": "game_name"}},
    {"text": "Juegos parecidos al FIFA", "intent": "find_similar", "entities": {"FIFA": "game_name"}},
    {"text": "Busco una alternativa a Los Sims", "intent": "find_similar", "entities": {"Los Sims": "game_name"}},
    {"text": "Algo en la onda de Cyberpunk 2077", "intent": "find_similar", "entities": {"Cyberpunk 2077": "game_name"}},
    {"text": "Juegos parecidos a Resident Evil 4", "intent": "find_similar", "entities": {"Resident Evil 4": "game_name"}},
    {"text": "Quiero un juego estilo Doom", "intent": "find_similar", "entities": {"Doom": "game_name"}},
    {"text": "Recomienda juegos como Zelda Breath of the Wild", "intent": "find_similar", "entities": {"Zelda Breath of the Wild": "game_name"}},
    {"text": "Algo que sea como el Age of Empires", "intent": "find_similar", "entities": {"Age of Empires": "game_name"}},
    {"text": "Juegos parecidos a Skyrim", "intent": "find_similar", "entities": {"Skyrim": "game_name"}},
    {"text": "Busca juegos del estilo de Persona 5", "intent": "find_similar", "entities": {"Persona 5": "game_name"}},
    {"text": "Títulos similares a Bloodborne", "intent": "find_similar", "entities": {"Bloodborne": "game_name"}},
    {"text": "Quiero algo como el Fortnite", "intent": "find_similar", "entities": {"Fortnite": "game_name"}},
    {"text": "Juegos parecidos a Animal Crossing", "intent": "find_similar", "entities": {"Animal Crossing": "game_name"}},
    {"text": "Algo tipo Terraria", "intent": "find_similar", "entities": {"Terraria": "game_name"}},
    {"text": "¿Qué otro juego es como Portal?", "intent": "find_similar", "entities": {"Portal": "game_name"}},
    {"text": "Dame algo parecido a Left 4 Dead", "intent": "find_similar", "entities": {"Left 4 Dead": "game_name"}},
    {"text": "Juegos parecidos a Silent Hill", "intent": "find_similar", "entities": {"Silent Hill": "game_name"}},
    {"text": "Busca alternativas a Diablo 4", "intent": "find_similar", "entities": {"Diablo 4": "game_name"}},
    {"text": "Quiero jugar algo similar a Mass Effect", "intent": "find_similar", "entities": {"Mass Effect": "game_name"}},
    {"text": "Algo que me recuerde a Bioshock", "intent": "find_similar", "entities": {"Bioshock": "game_name"}},
    {"text": "Juegos tipo League of Legends", "intent": "find_similar", "entities": {"League of Legends": "game_name"}},
    {"text": "Un juego parecido a Undertale", "intent": "find_similar", "entities": {"Undertale": "game_name"}}
]


# ---------------------------------------------------------------------------
# Funciones de la API de Wit.ai
# ---------------------------------------------------------------------------

async def _request(
    client: httpx.AsyncClient,
    method: str,
    endpoint: str,
    json_data=None,
    delay: float = 0.15,
) -> httpx.Response:
    url = f"{BASE_URL}{endpoint}"
    params = {"v": WIT_API_VERSION}
    res = await client.request(
        method, url, params=params, headers=HEADERS, json=json_data
    )
    await asyncio.sleep(delay)
    return res


async def ensure_intent(client: httpx.AsyncClient, name: str) -> None:
    res = await _request(client, "POST", "/intents", {"name": name})
    if res.status_code in (200, 201):
        print(f"  [+] Intent creado: {name}")
    elif res.status_code in (400, 409) and "already" in res.text.lower():
        print(f"  [=] Intent ya existe: {name}")
    else:
        print(f"  [!] Error intent '{name}': {res.status_code} - {res.text[:120]}")


async def ensure_entity(
    client: httpx.AsyncClient, name: str, lookups: list[str]
) -> None:
    res = await _request(client, "POST", "/entities", {"name": name, "roles": [], "lookups": lookups})
    if res.status_code in (200, 201):
        print(f"  [+] Entidad creada: {name}")
    elif res.status_code == 409:
        print(f"  [=] Entidad ya existe: {name}")
    else:
        print(f"  [!] Error entidad '{name}': {res.status_code} - {res.text[:120]}")


async def upsert_keyword(
    client: httpx.AsyncClient, entity: str, keyword: str, synonyms: list[str]
) -> None:
    """Crea el keyword con sus sinónimos; si ya existe, agrega sinónimos faltantes."""
    payload = {"keyword": keyword, "synonyms": synonyms}
    res = await _request(
        client, "POST", f"/entities/{entity}/keywords", payload, delay=0.12
    )
    if res.status_code in (200, 201):
        pass  # OK silencioso
    elif res.status_code == 409:
        # Ya existe — intentar agregar sinónimos uno a uno
        for syn in synonyms:
            r = await _request(
                client,
                "POST",
                f"/entities/{entity}/keywords/{keyword}/synonyms",
                {"synonym": syn},
                delay=0.1,
            )
            # 200/201: agregado, 409: ya existe → ignorar ambos
    else:
        print(f"    [!] Error keyword '{keyword}' en '{entity}': {res.status_code} — {res.text[:100]}")


def _build_utterance_payload(raw: list[dict]) -> list[dict]:
    """Convierte nuestro formato de utterances al formato que acepta la API."""
    out = []
    for u in raw:
        text = u["text"]
        intent = u["intent"]
        ents = []
        for substring, mapping in u.get("entities", {}).items():
            start = text.lower().find(substring.lower())
            if start == -1:
                continue
            end = start + len(substring)
            if ":" in mapping:
                entity_role, _ = mapping.split(":", 1)
                entity_type = f"{entity_role}:{entity_role}"
            else:
                entity_type = f"{mapping}:{mapping}"
            ents.append({
                "entity": entity_type,
                "start": start,
                "end": end,
                "body": text[start:end],
                "entities": [],
            })
        out.append({
            "text": text,
            "intent": intent,
            "entities": ents,
            "traits": [],
        })
    return out


async def upload_utterances_batch(
    client: httpx.AsyncClient, batch: list[dict]
) -> bool:
    res = await _request(client, "POST", "/utterances", batch, delay=0.3)
    if res.status_code in (200, 201):
        return True
    else:
        print(f"  [!] Error utterances: {res.status_code} — {res.text[:200]}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    if not WIT_AI_TOKEN:
        print("ERROR: WIT_AI_TOKEN no configurado en .env")
        sys.exit(1)

    print("=" * 65)
    print("  SteamBot — Entrenamiento completo de Wit.ai")
    print(f"  Utterances: {len(RAW_UTTERANCES)}")
    print(f"  Tags con sinónimos: {len(TAG_SYNONYMS)}")
    print(f"  Géneros con sinónimos: {len(GENRE_SYNONYMS)}")
    print("=" * 65)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # ── 1. Intents ──────────────────────────────────────────────────────
        print("\n[1/4] Creando Intents...")
        for intent in INTENTS:
            await ensure_intent(client, intent)

        # ── 2. Entidades ────────────────────────────────────────────────────
        print("\n[2/4] Creando Entidades...")
        await ensure_entity(client, "tags", ["free-text", "keywords"])
        await ensure_entity(client, "genre", ["free-text", "keywords"])
        await ensure_entity(client, "game_name", ["free-text"])

        # ── 3. Keywords + sinónimos ─────────────────────────────────────────
        print(f"\n[3/4] Cargando sinónimos de Tags ({len(TAG_SYNONYMS)} tags)...")
        for i, (tag, syns) in enumerate(TAG_SYNONYMS.items(), 1):
            print(f"  [{i:3d}/{len(TAG_SYNONYMS)}] tags → {tag}")
            await upsert_keyword(client, "tags", tag, syns)

        print(f"\n[3b/4] Cargando sinónimos de Géneros ({len(GENRE_SYNONYMS)} géneros)...")
        for i, (genre, syns) in enumerate(GENRE_SYNONYMS.items(), 1):
            print(f"  [{i:2d}/{len(GENRE_SYNONYMS)}] genre → {genre}")
            await upsert_keyword(client, "genre", genre, syns)

        # ── 4. Utterances ───────────────────────────────────────────────────
        print(f"\n[4/4] Subiendo utterances en lotes de {BATCH_SIZE}...")
        payload = _build_utterance_payload(RAW_UTTERANCES)
        total = len(payload)
        ok_count = 0

        for start in range(0, total, BATCH_SIZE):
            batch = payload[start : start + BATCH_SIZE]
            end_idx = min(start + BATCH_SIZE, total)
            print(f"  Lote {start + 1}–{end_idx} / {total}...", end=" ", flush=True)
            ok = await upload_utterances_batch(client, batch)
            if ok:
                ok_count += len(batch)
                print("OK")
            else:
                print("FALLO")

        print("\n" + "=" * 65)
        print("  ENTRENAMIENTO COMPLETADO")
        print(f"  Utterances subidas: {ok_count}/{total}")
        print("=" * 65)
        print("\nWit.ai puede tardar unos minutos en entrenar el modelo.")
        print("Prueba con: python test_wit_integration.py")


if __name__ == "__main__":
    asyncio.run(main())
