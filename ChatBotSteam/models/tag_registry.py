"""
tag_registry.py
---------------
Catálogo CENTRALIZADO de todas las tags de SteamSpy.

Fuente: docs/Tags overview - SteamSpy - All the data and stats about Steam games.csv
Total: 340 tags (lista completa, ordenada alfabéticamente).

Este módulo es la fuente única de verdad para:
  1. Validar tags extraídas por el LLM
  2. Mapear español → tags exactas de SteamSpy
  3. Generar prompts del EXTRACTOR con la lista completa
  4. Sugerir tags parciales (autocompletado)
"""

import csv
import os
from typing import Optional

# ============================================================================
# 1. LISTA COMPLETA DE 340 TAGS (extraída del CSV oficial de SteamSpy)
# ============================================================================

ALL_TAGS: list[str] = [
    "2.5D",
    "2D",
    "2D Fighter",
    "3D Platformer",
    "3D Vision",
    "4 Player Local",
    "4X",
    "6DOF",
    "1980s",
    "1990's",
    "360 Video",
    "Abstract",
    "Action",
    "Action RPG",
    "Action-Adventure",
    "Adventure",
    "Agriculture",
    "Aliens",
    "Alternate History",
    "America",
    "Animation & Modeling",
    "Anime",
    "Arcade",
    "Arena Shooter",
    "Artificial Intelligence",
    "Assassin",
    "Asynchronous Multiplayer",
    "Atmospheric",
    "Audio Production",
    "Base-Building",
    "Based On A Novel",
    "Basketball",
    "Battle Royale",
    "Batman",
    "Beat 'em up",
    "Benchmark",
    "Bikes",
    "Blood",
    "Board Game",
    "Bowling",
    "Building",
    "Bullet Hell",
    "Bullet Time",
    "CRPG",
    "Capitalism",
    "Card Game",
    "Cartoon",
    "Cartoony",
    "Casual",
    "Character Action Game",
    "Character Customization",
    "Chess",
    "Choices Matter",
    "Choose Your Own Adventure",
    "Cinematic",
    "City Builder",
    "Class-Based",
    "Classic",
    "Clicker",
    "Co-op",
    "Co-op Campaign",
    "Cold War",
    "Colorful",
    "Comedy",
    "Comic Book",
    "Competitive",
    "Conspiracy",
    "Controller",
    "Conversation",
    "Crafting",
    "Crime",
    "Crowdfunded",
    "Cult Classic",
    "Cute",
    "Cyberpunk",
    "Cycling",
    "Dark",
    "Dark Comedy",
    "Dark Fantasy",
    "Dark Humor",
    "Dating Sim",
    "Demons",
    "Design & Illustration",
    "Destruction",
    "Detective",
    "Difficult",
    "Dinosaurs",
    "Diplomacy",
    "Documentary",
    "Dragons",
    "Drama",
    "Driving",
    "Dungeon Crawler",
    "Dynamic Narration",
    "Dystopian",
    "Early Access",
    "Economy",
    "Education",
    "Episodic",
    "e-sports",
    "Experience",
    "Experimental",
    "Exploration",
    "FMV",
    "FPS",
    "Faith",
    "Family Friendly",
    "Fantasy",
    "Fast-Paced",
    "Female Protagonist",
    "Fighting",
    "First-Person",
    "Fishing",
    "Flight",
    "Football",
    "Free to Play",
    "Funny",
    "Futuristic",
    "Gambling",
    "Game Development",
    "GameMaker",
    "Games Workshop",
    "Gaming",
    "God Game",
    "Golf",
    "Gore",
    "Gothic",
    "Grand Strategy",
    "Great Soundtrack",
    "Grid-Based Movement",
    "Gun Customization",
    "Hack and Slash",
    "Hacking",
    "Hand-drawn",
    "Hardware",
    "Heist",
    "Hex Grid",
    "Hidden Object",
    "Historical",
    "Horror",
    "Horses",
    "Hunting",
    "Illuminati",
    "Indie",
    "Intentionally Awkward Controls",
    "Interactive Fiction",
    "Inventory Management",
    "Investigation",
    "Isometric",
    "JRPG",
    "Kickstarter",
    "LEGO",
    "Lara Croft",
    "Lemmings",
    "Level Editor",
    "Linear",
    "Local Co-Op",
    "Local Multiplayer",
    "Logic",
    "Loot",
    "Lore-Rich",
    "Lovecraftian",
    "MMORPG",
    "MOBA",
    "Magic",
    "Management",
    "Mars",
    "Martial Arts",
    "Massively Multiplayer",
    "Match 3",
    "Mature",
    "Mechs",
    "Medieval",
    "Memes",
    "Metroidvania",
    "Military",
    "Mini Golf",
    "Minimalist",
    "Mining",
    "Mod",
    "Moddable",
    "Modern",
    "Mouse only",
    "Movie",
    "Multiple Endings",
    "Multiplayer",
    "Music",
    "Music-Based Procedural Generation",
    "Mystery",
    "Mystery Dungeon",
    "Mythology",
    "NSFW",
    "Narration",
    "Naval",
    "Ninja",
    "Noir",
    "Nonlinear",
    "Nudity",
    "Offroad",
    "On-Rails Shooter",
    "Online Co-Op",
    "Open World",
    "Otome",
    "Parkour",
    "Parody",
    "Party-Based RPG",
    "Perma Death",
    "Philisophical",
    "Photo Editing",
    "Physics",
    "Pinball",
    "Pirates",
    "Pixel Graphics",
    "Platformer",
    "Point & Click",
    "Political",
    "Politics",
    "Pool",
    "Post-apocalyptic",
    "Procedural Generation",
    "Programming",
    "Psychedelic",
    "Psychological",
    "Psychological Horror",
    "Puzzle",
    "Puzzle-Platformer",
    "PvE",
    "PvP",
    "Quick-Time Events",
    "RPG",
    "RPGMaker",
    "RTS",
    "Racing",
    "Real-Time",
    "Real-Time with Pause",
    "Real Time Tactics",
    "Realistic",
    "Relaxing",
    "Remake",
    "Replay Value",
    "Resource Management",
    "Retro",
    "Rhythm",
    "Robots",
    "Rogue-like",
    "Rogue-lite",
    "Romance",
    "Rome",
    "Runner",
    "Sailing",
    "Sandbox",
    "Satire",
    "Science",
    "Sci-fi",
    "Score Attack",
    "Sexual Content",
    "Shoot 'Em Up",
    "Shooter",
    "Short",
    "Side Scroller",
    "Silent Protagonist",
    "Simulation",
    "Singleplayer",
    "Sniper",
    "Soccer",
    "Software",
    "Software Training",
    "Sokoban",
    "Soundtrack",
    "Space",
    "Space Sim",
    "Spectacle fighter",
    "Spelling",
    "Split Screen",
    "Sports",
    "Star Wars",
    "Stealth",
    "Steam Machine",
    "Steampunk",
    "Story Rich",
    "Strategy",
    "Strategy RPG",
    "Stylized",
    "Superhero",
    "Supernatural",
    "Surreal",
    "Survival",
    "Survival Horror",
    "Swordplay",
    "Tactical",
    "Tactical RPG",
    "Tanks",
    "Team-Based",
    "Text-Based",
    "Third Person",
    "Third-Person Shooter",
    "Thriller",
    "Time Attack",
    "Time Manipulation",
    "Time Travel",
    "Top-Down",
    "Top-Down Shooter",
    "Touch-Friendly",
    "Tower Defense",
    "TrackIR",
    "Trading",
    "Trading Card Game",
    "Trains",
    "Transhumanism",
    "Turn-Based",
    "Turn-Based Combat",
    "Turn-Based Strategy",
    "Turn-Based Tactics",
    "Tutorial",
    "Twin Stick Shooter",
    "Typing",
    "Underground",
    "Underwater",
    "Utilities",
    "VR",
    "VR Only",
    "Vampire",
    "Video Production",
    "Villain Protagonist",
    "Violent",
    "Visual Novel",
    "Voice Control",
    "Voxel",
    "Walking Simulator",
    "War",
    "Wargame",
    "Warhammer 40K",
    "Web Publishing",
    "Werewolves",
    "Western",
    "Word Game",
    "World War I",
    "World War II",
    "Wrestling",
    "Zombies",
]

# Conjunto para búsquedas O(1)
ALL_TAGS_SET: set[str] = set(ALL_TAGS)


# ============================================================================
# 2. FILTRO DE CONTENIDO SEXUAL
# ============================================================================

# Tags que se EXCLUYEN SIEMPRE de las recomendaciones por defecto.
# Un juego con CUALQUIERA de estas tags es bloqueado si allow_nsfw=False.
# Incluye tags que existen en SteamSpy pero no están en ALL_TAGS (e.g. Hentai).
BLOCKED_TAGS: set[str] = {
    "Sexual Content",
    "Nudity",
    "NSFW",
}

# Tags que INDIVIDUALMENTE son legítimas (muchos juegos buenos las tienen),
# pero cuando 2+ de estas aparecen JUNTAS en un juego, es probable que sea
# contenido adulto/sexual disfrazado. Se bloquean en combinación.
NSFW_COMBO_TAGS: set[str] = {
    "Mature",
    "Dating Sim",
    "Anime",
    "Visual Novel",
    "Romance",
    "Otome",
}

# Umbral: si un juego tiene >= NSFW_COMBO_THRESHOLD de las NSFW_COMBO_TAGS,
# se considera potencialmente NSFW y se bloquea.
# Threshold 2 = más agresivo (bloquea Anime+Mature, Dating Sim+Romance, etc.)
NSFW_COMBO_THRESHOLD: int = 2

# Tags que se permiten solo si el usuario las solicita de forma explícita
# (no se bloquean automáticamente pero requieren opt-in consciente).
ADULT_TAGS: set[str] = {
    "Mature",
    "Dating Sim",
    "Gore",
    "Violent",
}

# Patterns in game NAMES that indicate adult content
# (catches games that pass tag filters but have obviously adult names)
import re as _re

_NSFW_NAME_PATTERNS = _re.compile(
    r"\b(hentai|sex|sexy|porn|eroge|ecchi|waifu|lewd|uncensor|nude|naked|strip|"
    r"nsfw|adult\s*only|18\+|\+18|xxx)\b",
    _re.IGNORECASE,
)


def is_nsfw_game(game_tags: set[str], game_name: str = "") -> bool:
    """
    Determines if a game should be blocked by the NSFW filter.
    Returns True if:
      1. The game has ANY tag from BLOCKED_TAGS, OR
      2. The game has >= NSFW_COMBO_THRESHOLD tags from NSFW_COMBO_TAGS, OR
      3. The game's name matches known adult content patterns
    """
    # Check 1: Direct block by tag
    if game_tags & BLOCKED_TAGS:
        return True
    # Check 2: Combo block (e.g., Anime + Dating Sim, Mature + Romance)
    combo_count = len(game_tags & NSFW_COMBO_TAGS)
    if combo_count >= NSFW_COMBO_THRESHOLD:
        return True
    # Check 3: Name-based block
    if game_name and _NSFW_NAME_PATTERNS.search(game_name):
        return True
    return False


# ============================================================================
# 3. MAPEO ESPAÑOL / LENGUAJE NATURAL → TAGS EXACTAS DE STEAMSPY
# ============================================================================

# Formato: término en español o lenguaje natural → [lista de tags exactas candidatas]
# El LLM elige la(s) más apropiada(s) según contexto.
# Orden: la primera es la más probable.

SPANISH_TO_TAGS: dict[str, list[str]] = {
    # ── Géneros principales ──
    "acción": ["Action"],
    "aventura": ["Adventure"],
    "rpg": ["RPG"],
    "rol": ["RPG"],
    "juego de rol": ["RPG"],
    "estrategia": ["Strategy"],
    "táctico": ["Tactical", "Turn-Based Tactics"],
    "táctica": ["Tactical", "Turn-Based Tactics"],
    "simulación": ["Simulation"],
    "simulador": ["Simulation"],
    "carreras": ["Racing"],
    "autos": ["Racing"],
    "velocidad": ["Racing", "Fast-Paced"],
    "deportes": ["Sports"],
    "fútbol": ["Soccer", "Football", "Sports"],
    "futbol": ["Soccer", "Football", "Sports"],
    "basquet": ["Sports"],
    "básquet": ["Sports"],
    "basket": ["Sports"],
    "basquetbol": ["Sports"],
    "básquetbol": ["Sports"],
    "basketball": ["Sports"],
    "casual": ["Casual"],
    "gratis": ["Free to Play"],
    "free to play": ["Free to Play"],
    "f2p": ["Free to Play"],
    "acceso anticipado": ["Early Access"],
    "early access": ["Early Access"],
    "indie": ["Indie"],
    "independiente": ["Indie"],

    # ── Horror / Terror ──
    "terror": ["Horror", "Psychological Horror", "Survival Horror"],
    "miedo": ["Horror", "Psychological Horror"],
    "horror": ["Horror"],
    "terror psicológico": ["Psychological Horror"],
    "horror psicológico": ["Psychological Horror"],
    "survival horror": ["Survival Horror"],
    "terror de supervivencia": ["Survival Horror"],
    "lovecraft": ["Lovecraftian"],
    "lovecraftiano": ["Lovecraftian"],

    # ── Multijugador ──
    "battle royale": ["Battle Royale"],
    "battle royal": ["Battle Royale"],
    "multijugador": ["Multiplayer"],
    "multiplayer": ["Multiplayer"],
    "online": ["Multiplayer", "Online Co-Op"],
    "cooperativo": ["Co-op"],
    "co-op": ["Co-op"],
    "coop": ["Co-op"],
    "con amigos": ["Multiplayer", "Co-op"],
    "juego en equipo": ["Team-Based", "Co-op"],
    "equipo": ["Team-Based"],
    "local": ["Local Multiplayer", "Local Co-Op"],
    "pantalla dividida": ["Split Screen"],
    "splitscreen": ["Split Screen"],
    "pvp": ["PvP"],
    "pve": ["PvE"],
    "competitivo": ["Competitive", "PvP"],
    "esports": ["e-sports"],
    "mmo": ["Massively Multiplayer", "MMORPG"],
    "mmorpg": ["MMORPG"],
    "moba": ["MOBA"],

    # ── Mundo / Exploración ──
    "mundo abierto": ["Open World"],
    "open world": ["Open World"],
    "sandbox": ["Sandbox"],
    "exploración": ["Exploration"],
    "explorar": ["Exploration"],

    # ── Disparos ──
    "disparos": ["Shooter", "FPS"],
    "shooter": ["Shooter"],
    "fps": ["FPS"],
    "primera persona": ["First-Person", "FPS"],
    "first person": ["First-Person"],
    "tercera persona": ["Third Person", "Third-Person Shooter"],
    "third person": ["Third Person"],
    "shooter táctico": ["Tactical", "FPS"],
    "balas": ["Bullet Hell", "Shooter"],
    "bullet hell": ["Bullet Hell"],

    # ── Fantasía / Ciencia Ficción ──
    "fantasía": ["Fantasy"],
    "fantasia": ["Fantasy"],
    "fantasy": ["Fantasy"],
    "fantasía oscura": ["Dark Fantasy"],
    "fantasia oscura": ["Dark Fantasy"],
    "ciencia ficción": ["Sci-fi"],
    "scifi": ["Sci-fi"],
    "sci-fi": ["Sci-fi"],
    "futurista": ["Futuristic", "Sci-fi"],
    "cyberpunk": ["Cyberpunk"],
    "ciberpunk": ["Cyberpunk"],
    "steampunk": ["Steampunk"],
    "ciencia": ["Science"],
    "space": ["Space"],
    "espacio": ["Space"],
    "espacial": ["Space", "Space Sim"],
    "medieval": ["Medieval"],
    "edad media": ["Medieval"],
    "mitología": ["Mythology"],
    "mitologia": ["Mythology"],
    "post-apocalíptico": ["Post-apocalyptic"],
    "apocalipsis": ["Post-apocalyptic"],
    "apocalíptico": ["Post-apocalyptic"],

    # ── Criaturas / Temáticas ──
    "zombies": ["Zombies"],
    "zombi": ["Zombies"],
    "vampiros": ["Vampire"],
    "vampiro": ["Vampire"],
    "dragones": ["Dragons"],
    "dragón": ["Dragons"],
    "dragon": ["Dragons"],
    "hombres lobo": ["Werewolves"],
    "licántropos": ["Werewolves"],
    "licantropo": ["Werewolves"],
    "robots": ["Robots"],
    "mechas": ["Mechs"],
    "mecha": ["Mechs"],
    "alienígenas": ["Aliens"],
    "aliens": ["Aliens"],
    "extraterrestres": ["Aliens"],
    "dinosaurios": ["Dinosaurs"],
    "dinos": ["Dinosaurs"],
    "piratas": ["Pirates"],
    "ninja": ["Ninja"],
    "samurai": ["Swordplay", "Ninja"],
    "demonios": ["Demons"],
    "infierno": ["Demons", "Dark", "Gothic"],

    # ── Estética Visual ──
    "pixel art": ["Pixel Graphics"],
    "pixel": ["Pixel Graphics"],
    "píxeles": ["Pixel Graphics"],
    "retro": ["Retro", "Pixel Graphics"],
    "16 bits": ["Retro", "Pixel Graphics"],
    "8 bits": ["Retro", "Pixel Graphics"],
    "voxel": ["Voxel"],
    "anime": ["Anime"],
    "animé": ["Anime"],
    "japonés": ["Anime", "JRPG", "Visual Novel"],
    "cartoon": ["Cartoony", "Cartoon"],
    "caricaturas": ["Cartoony"],
    "dibujado a mano": ["Hand-drawn"],
    "hand drawn": ["Hand-drawn"],
    "minimalista": ["Minimalist"],
    "colorido": ["Colorful"],
    "colorful": ["Colorful"],
    "stylized": ["Stylized"],
    "estilizado": ["Stylized"],
    "realista": ["Realistic"],
    "abstracto": ["Abstract"],
    "oscuro": ["Dark"],
    "dark": ["Dark"],
    "gótico": ["Gothic"],
    "gotico": ["Gothic"],
    "noir": ["Noir"],
    "surrealista": ["Surreal"],
    "psicodélico": ["Psychedelic"],
    "comic": ["Comic Book"],

    # ── Mecánicas / Jugabilidad ──
    "sigilo": ["Stealth"],
    "stealth": ["Stealth"],
    "infiltración": ["Stealth"],
    "plataformas": ["Platformer"],
    "plataformero": ["Platformer"],
    "platformer": ["Platformer"],
    "metroidvania": ["Metroidvania", "Platformer", "Exploration"],
    "roguelike": ["Rogue-like", "Rogue-lite"],
    "rogue like": ["Rogue-like", "Rogue-lite"],
    "roguelite": ["Rogue-lite", "Rogue-like"],
    "rogue lite": ["Rogue-lite", "Rogue-like"],
    "mazmorras": ["Dungeon Crawler", "Rogue-like"],
    "dungeon crawler": ["Dungeon Crawler"],
    "almas": ["Difficult", "Dark Fantasy"],
    "soulslike": ["Difficult", "Dark Fantasy"],
    "souls-like": ["Difficult", "Dark Fantasy"],
    "dark souls": ["Difficult", "Dark Fantasy"],
    "difícil": ["Difficult"],
    "dificil": ["Difficult"],
    "difficult": ["Difficult"],
    "por turnos": ["Turn-Based", "Turn-Based Combat", "Turn-Based Strategy"],
    "turn based": ["Turn-Based", "Turn-Based Combat", "Turn-Based Strategy"],
    "combate por turnos": ["Turn-Based Combat"],
    "rts": ["RTS"],
    "estrategia en tiempo real": ["RTS", "Real-Time"],
    "tiempo real": ["Real-Time", "RTS"],
    "pausa táctica": ["Real-Time with Pause"],
    "gestión": ["Management", "Resource Management"],
    "administración": ["Management"],
    "manejo de recursos": ["Resource Management"],
    "economía": ["Economy"],
    "economia": ["Economy"],
    "construcción": ["Building", "Base-Building"],
    "construir": ["Building", "Base-Building", "Sandbox"],
    "construccion": ["Building", "Base-Building"],
    "crafting": ["Crafting"],
    "crafteo": ["Crafting"],
    "fabricación": ["Crafting"],
    "tower defense": ["Tower Defense"],
    "defensa de torres": ["Tower Defense"],
    "cartas": ["Card Game", "Trading Card Game"],
    "card game": ["Card Game"],
    "tcg": ["Trading Card Game"],
    "supervivencia": ["Survival"],
    "survival": ["Survival"],
    "lucha": ["Fighting", "Beat 'em up"],
    "peleas": ["Fighting", "Beat 'em up"],
    "fighting": ["Fighting"],
    "hack and slash": ["Hack and Slash"],
    "rompecabezas": ["Puzzle"],
    "puzzle": ["Puzzle"],
    "puzle": ["Puzzle"],
    "point and click": ["Point & Click"],
    "apuntar y clickear": ["Point & Click"],
    "novela visual": ["Visual Novel"],
    "visual novel": ["Visual Novel"],
    "citas": ["Dating Sim"],
    "dating sim": ["Dating Sim"],
    "simulador de citas": ["Dating Sim"],
    "novela interactiva": ["Interactive Fiction", "Visual Novel"],
    "elige tu propia aventura": ["Choose Your Own Adventure", "Choices Matter"],
    "múltiples finales": ["Multiple Endings"],
    "finales múltiples": ["Multiple Endings"],
    "decisiones importan": ["Choices Matter"],
    "choices matter": ["Choices Matter"],
    "ritmo": ["Rhythm", "Music"],
    "música": ["Music", "Great Soundtrack"],
    "musica": ["Music", "Great Soundtrack"],
    "soundtrack": ["Great Soundtrack", "Music"],
    "banda sonora": ["Great Soundtrack", "Music"],

    # ── Narrativa / Historia ──
    "historia": ["Story Rich"],
    "narrativa": ["Story Rich", "Narration"],
    "story rich": ["Story Rich"],
    "buena historia": ["Story Rich"],
    "narrativa profunda": ["Story Rich", "Narration"],
    "narración": ["Narration"],
    "misterio": ["Mystery", "Detective"],
    "detective": ["Detective", "Mystery"],
    "investigación": ["Investigation", "Detective", "Mystery"],
    "drama": ["Drama"],
    "comedia": ["Comedy", "Funny"],
    "gracioso": ["Funny", "Comedy"],
    "humor": ["Comedy", "Funny"],
    "humor negro": ["Dark Humor", "Dark Comedy"],
    "comedia oscura": ["Dark Comedy"],
    "sátira": ["Satire"],
    "satira": ["Satire"],
    "thriller": ["Thriller"],
    "suspenso": ["Thriller", "Mystery"],
    "conspiración": ["Conspiracy"],
    "conspiracion": ["Conspiracy"],
    "política": ["Political", "Politics"],
    "politica": ["Political", "Politics"],
    "filosófico": ["Philisophical"],
    "filosofico": ["Philisophical"],
    "psicológico": ["Psychological", "Psychological Horror"],
    "psicologico": ["Psychological", "Psychological Horror"],

    # ── Ambientación / Setting ──
    "atmosférico": ["Atmospheric"],
    "atmosferico": ["Atmospheric"],
    "atmósfera": ["Atmospheric"],
    "atmosfera": ["Atmospheric"],
    "inmersivo": ["Atmospheric"],
    "guerra": ["War", "Military"],
    "militar": ["Military", "War"],
    "histórico": ["Historical"],
    "historico": ["Historical"],
    "bélico": ["War", "Military"],
    "belico": ["War", "Military"],
    "segunda guerra mundial": ["World War II"],
    "ww2": ["World War II"],
    "primera guerra mundial": ["World War I"],
    "ww1": ["World War I"],
    "guerra fría": ["Cold War"],
    "guerra fria": ["Cold War"],
    "roma": ["Rome", "Historical"],
    "imperio romano": ["Rome", "Historical"],
    "western": ["Western"],
    "vaqueros": ["Western"],
    "lejano oeste": ["Western"],
    "oriental": ["Anime", "JRPG"],
    "guerra de las galaxias": ["Star Wars"],
    "star wars": ["Star Wars"],
    "batman": ["Batman", "Superhero"],
    "superhéroes": ["Superhero"],
    "superheroes": ["Superhero"],
    "lego": ["LEGO"],
    "bajo el agua": ["Underwater"],
    "submarino": ["Underwater", "Naval"],
    "oceánico": ["Underwater"],
    "marte": ["Mars", "Space"],
    "transhumanismo": ["Transhumanism", "Cyberpunk", "Sci-fi"],
    "distópico": ["Dystopian"],
    "distopia": ["Dystopian"],
    "utópico": ["Dystopian"],

    # ── Estilo de juego ──
    "corto": ["Short"],
    "juego corto": ["Short"],
    "rápido": ["Fast-Paced"],
    "rapido": ["Fast-Paced"],
    "relajante": ["Relaxing"],
    "tranquilo": ["Relaxing"],
    "relajado": ["Relaxing"],
    "familiar": ["Family Friendly"],
    "para niños": ["Family Friendly", "Cartoony"],
    "infantil": ["Family Friendly", "Cartoony"],
    "niños": ["Family Friendly"],
    "tierno": ["Cute"],
    "cute": ["Cute"],
    "lindo": ["Cute"],
    "mono": ["Cute"],
    "maduro": ["Mature"],
    "adulto": ["Mature"],
    "+18": ["Mature"],
    "gore": ["Gore", "Violent"],
    "violento": ["Violent", "Gore"],
    "sangriento": ["Gore", "Blood"],
    "sangre": ["Blood", "Gore"],
    "desnudos": ["Nudity", "Sexual Content"],
    "nudity": ["Nudity"],
    "contenido sexual": ["Sexual Content", "Nudity"],
    "nsfw": ["NSFW", "Sexual Content", "Nudity"],

    # ── Otras mecánicas ──
    "rejugable": ["Replay Value"],
    "replay": ["Replay Value"],
    "muerte permanente": ["Perma Death"],
    "perma death": ["Perma Death"],
    "procedural": ["Procedural Generation"],
    "generación procedural": ["Procedural Generation"],
    "mundo generado": ["Procedural Generation"],
    "personalización": ["Character Customization"],
    "personalizacion": ["Character Customization"],
    "crear personaje": ["Character Customization"],
    "mascotas": ["Cute"],
    "agricultura": ["Agriculture"],
    "granja": ["Agriculture"],
    "farmear": ["Agriculture"],
    "pesca": ["Fishing"],
    "pescar": ["Fishing"],
    "caza": ["Hunting"],
    "minería": ["Mining"],
    "mineria": ["Mining"],
    "minar": ["Mining"],
    "trenes": ["Trains"],
    "naval": ["Naval", "Sailing"],
    "barcos": ["Naval", "Sailing", "Pirates"],
    "navegación": ["Sailing", "Naval"],
    "vuelo": ["Flight"],
    "volar": ["Flight", "Space Sim"],
    "aviación": ["Flight"],
    "aviacion": ["Flight"],
    "conducción": ["Driving", "Racing"],
    "conduccion": ["Driving", "Racing"],
    "parkour": ["Parkour"],
    "sigilo asesino": ["Stealth", "Assassin"],
    "asesino": ["Assassin"],
    "hackeo": ["Hacking"],
    "hacking": ["Hacking"],
    "programación": ["Programming"],
    "programacion": ["Programming"],
    "juego de mesa": ["Board Game", "Card Game"],
    "ajedrez": ["Chess", "Board Game", "Turn-Based Strategy"],
    "pinball": ["Pinball"],
    "golf": ["Golf", "Mini Golf"],
    "mini golf": ["Mini Golf"],
    "billar": ["Pool"],
    "bowling": ["Bowling"],
    "bolos": ["Bowling"],
    "wrestling": ["Wrestling"],
    "lucha libre": ["Wrestling"],
    "artes marciales": ["Martial Arts"],
    "bicicleta": ["Bikes", "Cycling"],
    "ciclismo": ["Cycling", "Bikes"],
    "motos": ["Bikes", "Racing"],
    "offroad": ["Offroad", "Driving"],
    "baloncesto": ["Sports"],

    # ── Cámara / Perspectiva ──
    "2d": ["2D", "Side Scroller", "Platformer"],
    "3d": ["3D Platformer"],
    "plataformas 3d": ["3D Platformer"],
    "isométrico": ["Isometric"],
    "isometrico": ["Isometric"],
    "vista superior": ["Top-Down"],
    "top down": ["Top-Down"],
    "side scroller": ["Side Scroller"],
    "scroll lateral": ["Side Scroller"],
    "primera persona": ["First-Person", "FPS"],
    "tercera persona": ["Third Person", "Third-Person Shooter"],

    # ── VR ──
    "vr": ["VR"],
    "realidad virtual": ["VR"],
    "vr only": ["VR Only"],

    # ── Misc. ──
    "mujer protagonista": ["Female Protagonist"],
    "protagonista femenina": ["Female Protagonist"],
    "female protagonist": ["Female Protagonist"],
    "protagonista silencioso": ["Silent Protagonist"],
    "villano": ["Villain Protagonist"],
    "mods": ["Moddable", "Mod"],
    "moddable": ["Moddable"],
    "editor de niveles": ["Level Editor"],
    "física": ["Physics"],
    "fisicas": ["Physics"],
    "destrucción": ["Destruction"],
    "destruccion": ["Destruction"],
    "educativo": ["Education"],
    "educación": ["Education"],
    "educacion": ["Education"],
    "aprender": ["Education", "Software Training"],
    "clicker": ["Clicker"],
    "idle": ["Clicker"],
    "incremental": ["Clicker"],
    "conversación": ["Conversation"],
    "conversacion": ["Conversation"],
    "experimental": ["Experimental"],
    "experiencia": ["Experience"],
    "documental": ["Documentary"],
    "película interactiva": ["FMV", "Interactive Fiction"],
    "fotos": ["Photo Editing"],
    "diseño": ["Design & Illustration"],
    "video": ["Video Production"],
    "audio": ["Audio Production"],
    "utilidades": ["Utilities", "Software"],
    "software": ["Software"],
    "clásico": ["Classic", "Retro"],
    "clasico": ["Classic", "Retro"],
    "culto": ["Cult Classic"],
    "de culto": ["Cult Classic"],
    "remake": ["Remake"],
    "remaster": ["Remake"],
    "kickstarter": ["Kickstarter", "Crowdfunded"],
    "memes": ["Memes", "Funny", "Comedy"],
    "meme": ["Memes", "Funny"],
    "logros": ["Replay Value"],
    "speedrun": ["Fast-Paced", "Time Attack"],
    "tiempo": ["Time Manipulation", "Time Travel", "Time Attack"],
    "viaje en el tiempo": ["Time Travel"],
    "time travel": ["Time Travel"],
    "manipulación del tiempo": ["Time Manipulation"],
    "episódico": ["Episodic"],
    "episodico": ["Episodic"],
    "fe": ["Faith"],
    "religión": ["Faith"],
    "religion": ["Faith"],
    "biblia": ["Faith"],
    "escritura": ["Word Game", "Spelling"],
    "palabras": ["Word Game", "Typing"],
    "mecanografía": ["Typing"],
    "mecanografia": ["Typing"],
    "campeones": ["Warhammer 40K", "Games Workshop"],
    "warhammer": ["Warhammer 40K"],
}


# ============================================================================
# 4. FUNCIONES DE UTILIDAD
# ============================================================================

def is_valid_tag(tag: str) -> bool:
    """Verifica si una tag es válida en SteamSpy (case-insensitive)."""
    return tag in ALL_TAGS_SET


def normalize_tags(tags: list[str]) -> list[str]:
    """
    Toma una lista de tags (posiblemente con mal casing o en español) y devuelve
    solo las que existen en SteamSpy con su casing correcto.
    """
    if tags is None:
        return []
    result = []
    seen = set()
    for tag in tags:
        # 1. Intentar traducir de español a tags exactas
        translated_tags = translate_spanish_to_tags(tag)
        if translated_tags:
            for t in translated_tags:
                if t not in seen:
                    result.append(t)
                    seen.add(t)
            continue

        # 2. Buscar case-insensitive en ALL_TAGS_SET
        for valid_tag in ALL_TAGS_SET:
            if valid_tag.lower() == tag.lower() and valid_tag not in seen:
                result.append(valid_tag)
                seen.add(valid_tag)
                break
    return result


def suggest_tags(partial: str, limit: int = 10) -> list[str]:
    """
    Sugiere tags de SteamSpy que contengan el texto parcial (case-insensitive).
    Útil para autocompletado en la UI.
    """
    partial_lower = partial.lower().strip()
    if not partial_lower:
        return []

    matches = [t for t in ALL_TAGS if partial_lower in t.lower()]
    # Priorizar matches exactos y que empiecen con el término
    matches.sort(key=lambda t: (
        0 if t.lower() == partial_lower else
        1 if t.lower().startswith(partial_lower) else 2,
        len(t),
    ))
    return matches[:limit]


def translate_spanish_to_tags(spanish_term: str) -> list[str]:
    """
    Traduce un término en español a su(s) tag(s) exacta(s) de SteamSpy.
    Retorna lista vacía si no hay mapeo.
    """
    term_lower = spanish_term.lower().strip()
    return SPANISH_TO_TAGS.get(term_lower, [])


def get_all_tags_for_prompt(indent: str = "   ") -> str:
    """
    Genera una lista formateada de todas las tags para incluir en prompts del LLM.
    Agrupadas alfabéticamente para facilitar la lectura.
    """
    lines = [f"{indent}ALLOWED TAGS (use EXACTLY as written):"]
    current_letter = ""
    for tag in ALL_TAGS:
        first = tag[0].upper()
        if first != current_letter:
            current_letter = first
            lines.append(f"{indent}  --- {current_letter} ---")
        lines.append(f'{indent}  "{tag}",')
    return "\n".join(lines)


def load_tags_from_csv(csv_path: Optional[str] = None) -> list[str]:
    """
    Carga las tags directamente desde el CSV de SteamSpy.
    Útil para verificar que ALL_TAGS está actualizado.

    Args:
        csv_path: Ruta al CSV. Si es None, busca en docs/.

    Returns:
        Lista de tags extraídas del CSV.
    """
    if csv_path is None:
        import os as _os
        _base = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        csv_path = _os.path.join(_base, "docs", "Tags overview - SteamSpy - All the data and stats about Steam games.csv")

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV de tags no encontrado: {csv_path}")

    tags = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)  # skip header
        for row in reader:
            if len(row) >= 2:
                tag_name = row[1].strip().strip('"')
                if tag_name:
                    tags.append(tag_name)
    return tags


def validate_against_csv(csv_path: Optional[str] = None) -> dict:
    """
    Compara ALL_TAGS con el CSV fuente para detectar discrepancias.

    Returns:
        {"match": bool, "missing_in_code": [...], "missing_in_csv": [...], "csv_count": int, "code_count": int}
    """
    csv_tags = load_tags_from_csv(csv_path)
    csv_set = set(csv_tags)

    missing_in_code = csv_set - ALL_TAGS_SET
    missing_in_csv = ALL_TAGS_SET - csv_set

    return {
        "match": len(missing_in_code) == 0 and len(missing_in_csv) == 0,
        "missing_in_code": sorted(missing_in_code),
        "missing_in_csv": sorted(missing_in_csv),
        "csv_count": len(csv_tags),
        "code_count": len(ALL_TAGS),
    }
