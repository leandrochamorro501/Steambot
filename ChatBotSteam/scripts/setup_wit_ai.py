import os
import csv
import asyncio
import httpx
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(env_path)

WIT_AI_TOKEN = os.getenv("WIT_AI_TOKEN")
WIT_API_VERSION = "20240601"
BASE_URL = "https://api.wit.ai"

headers = {
    "Authorization": f"Bearer {WIT_AI_TOKEN}",
    "Content-Type": "application/json",
    "Accept": "application/json"
}

# --- DATOS DE CONFIGURACIÓN ---

INTENTS = [
    "search_game", "refine_search", "check_price",
    "compare_games", "casual_chat", "ask_capabilities"
]

GENRES = {
    "Action": ["Action", "acción", "accion", "juego de acción", "tiros", "disparos"],
    "Adventure": ["Adventure", "aventura", "aventuras", "juego de aventura"],
    "RPG": ["RPG", "rol", "juego de rol", "juego rpg", "juegos de rol"],
    "Strategy": ["Strategy", "estrategia", "juego de estrategia", "tactico", "táctico", "táctica"],
    "Simulation": ["Simulation", "simulación", "simulacion", "simulador"],
    "Racing": ["Racing", "carreras", "carrera", "autos", "coches", "conducción"],
    "Sports": ["Sports", "deportes", "deporte", "futbol", "fútbol", "basket"],
    "Indie": ["Indie", "independiente", "juegos indie", "indies"],
    "Casual": ["Casual", "casual", "juego casual", "relajante", "tranquilo"],
    "Massively Multiplayer": ["Massively Multiplayer", "mmo", "mmorpg", "multijugador masivo"],
    "Free to Play": ["Free to Play", "gratis", "gratuito", "f2p", "free to play"],
    "Early Access": ["Early Access", "acceso anticipado", "early access", "beta"]
}

# Sinónimos para los Tags más comunes
TAG_SYNONYMS = {
    "Horror": ["terror", "miedo", "horror", "aterrador"],
    "Psychological Horror": ["terror psicológico", "horror psicológico"],
    "Survival": ["supervivencia", "survival", "sobrevivir"],
    "Co-op": ["cooperativo", "coop", "co-op", "con amigos", "dos jugadores"],
    "Multiplayer": ["multijugador", "online", "en línea", "con otros"],
    "Open World": ["mundo abierto", "open world", "exploración"],
    "Puzzle": ["puzzle", "rompecabezas", "puzle"],
    "Shooter": ["shooter", "disparos", "tiros", "fps"],
    "Sci-fi": ["ciencia ficción", "sci-fi", "futurista", "espacio"],
    "Anime": ["anime", "japonés", "otaku"],
    "Pixel Graphics": ["pixel art", "retro", "8-bit", "pixelados"],
    "Fantasy": ["fantasía", "fantasy", "magia", "dragones"],
    "Sandbox": ["sandbox", "arenero", "libertad"],
    "Building": ["construcción", "construir", "building"],
    "Crafting": ["crafting", "crafteo", "fabricar"],
    "Zombies": ["zombies", "zombis", "muertos vivientes"],
    "Stealth": ["sigilo", "stealth", "espionaje"],
    "Difficult": ["difícil", "hard", "souls-like", "retador"],
    "Rogue-like": ["roguelike", "roguelite", "permadeath"],
    "Platformer": ["plataformas", "platformer", "saltos"],
    "Story Rich": ["historia", "narrativa", "story rich", "buena historia"],
    "Battle Royale": ["battle royale", "br"],
    "Farming Sim": ["granja", "farming sim", "cosecha", "agricultura"],
    "Space": ["espacio", "galaxia", "naves espaciales"],
    "Medieval": ["medieval", "castillos", "espadas"]
}

UTTERANCES = [
    {"text": "Recomiéndame juegos de terror", "intent": "search_game", "entities": {"terror": "tags:Horror"}},
    {"text": "Busco un RPG de fantasía", "intent": "search_game", "entities": {"RPG": "genre:RPG", "fantasía": "tags:Fantasy"}},
    {"text": "Juegos de supervivencia co-op", "intent": "search_game", "entities": {"supervivencia": "tags:Survival", "co-op": "tags:Co-op"}},
    {"text": "Quiero algo de mundo abierto", "intent": "search_game", "entities": {"mundo abierto": "tags:Open World"}},
    {"text": "Juegos indie con pixel art", "intent": "search_game", "entities": {"indie": "genre:Indie", "pixel art": "tags:Pixel Graphics"}},
    {"text": "Un shooter multijugador", "intent": "search_game", "entities": {"shooter": "tags:Shooter", "multijugador": "tags:Multiplayer"}},
    {"text": "Algo de granjas para jugar con amigos", "intent": "search_game", "entities": {"granjas": "tags:Farming Sim", "con amigos": "tags:Co-op"}},
    {"text": "Juegos difíciles tipo rogue-like", "intent": "search_game", "entities": {"difíciles": "tags:Difficult", "rogue-like": "tags:Rogue-like"}},
    {"text": "Mejor que sea más barato", "intent": "refine_search"},
    {"text": "Lo mismo pero cooperativo", "intent": "refine_search", "entities": {"cooperativo": "tags:Co-op"}},
    {"text": "Dame más opciones", "intent": "refine_search"},
    {"text": "¿Cuánto cuesta Elden Ring?", "intent": "check_price", "entities": {"Elden Ring": "game_name"}},
    {"text": "Precio de Stardew Valley", "intent": "check_price", "entities": {"Stardew Valley": "game_name"}},
    {"text": "Compara Elden Ring con Dark Souls", "intent": "compare_games", "entities": {"Elden Ring": "game_name", "Dark Souls": "game_name"}},
    {"text": "Hola", "intent": "casual_chat"},
    {"text": "Gracias", "intent": "casual_chat"},
    {"text": "¿Qué puedes hacer?", "intent": "ask_capabilities"},
    {"text": "Ayuda", "intent": "ask_capabilities"}
]

# --- FUNCIONES DE LA API ---

async def request_api(client: httpx.AsyncClient, method: str, endpoint: str, json_data=None):
    url = f"{BASE_URL}{endpoint}"
    params = {"v": WIT_API_VERSION}
    res = await client.request(method, url, params=params, headers=headers, json=json_data)
    # Esperamos un poco para no saturar
    await asyncio.sleep(0.2)
    return res

async def create_intent(client, name):
    res = await request_api(client, "POST", "/intents", {"name": name})
    if res.status_code in (200, 201):
        print(f"+ Intent creado: {name}")
    elif res.status_code == 409:
        print(f"= Intent ya existe: {name}")
    else:
        print(f"- Error intent {name}: {res.status_code} - {res.text}")

async def create_entity(client, name, lookups):
    res = await request_api(client, "POST", "/entities", {
        "name": name, "roles": [], "lookups": lookups
    })
    if res.status_code in (200, 201):
        print(f"+ Entidad creada: {name}")
    elif res.status_code == 409:
        print(f"= Entidad ya existe: {name}")
    else:
        print(f"- Error entidad {name}: {res.status_code} - {res.text}")

async def add_keyword_synonym(client, entity_name, keyword, synonym):
    # En Wit.ai, para agregar un sinónimo a un keyword, se hace un POST
    res = await request_api(client, "POST", f"/entities/{entity_name}/keywords/{keyword}/synonyms", {"synonym": synonym})
    if res.status_code in (200, 201):
        pass
    elif res.status_code == 409:
        pass
    else:
        print(f"   - Error con sinónimo '{synonym}' en {keyword}: {res.status_code}")

async def train_utterances(client):
    print("\nEntrenando frases de ejemplo...")

    formatted_utterances = []
    for u in UTTERANCES:
        text = u["text"]
        intent = u["intent"]
        entities = []

        if "entities" in u:
            for substring, mapping in u["entities"].items():
                start = text.lower().find(substring.lower())
                if start != -1:
                    end = start + len(substring)

                    if ":" in mapping:
                        entity_name, entity_value = mapping.split(":")
                        entity_type = f"{entity_name}:{entity_name}"
                        entities.append({
                            "entity": entity_type,
                            "start": start,
                            "end": end,
                            "body": text[start:end],
                            "entities": []
                        })
                    else:
                        # Para game_name (free-text)
                        entity_type = f"{mapping}:{mapping}"
                        entities.append({
                            "entity": entity_type,
                            "start": start,
                            "end": end,
                            "body": text[start:end],
                            "entities": []
                        })

        formatted_utterances.append({
            "text": text,
            "intent": intent,
            "entities": entities,
            "traits": []
        })

    res = await request_api(client, "POST", "/utterances", formatted_utterances)
    if res.status_code in (200, 201):
        print("+ Se enviaron las frases de entrenamiento con éxito.")
    else:
        print(f"- Error al enviar frases: {res.status_code} - {res.text}")

# --- FLUJO PRINCIPAL ---

async def main():
    if not WIT_AI_TOKEN:
        print("Error: WIT_AI_TOKEN no configurado en .env")
        return

    async with httpx.AsyncClient() as client:
        print("=== CONFIGURACIÓN AUTOMÁTICA DE WIT.AI ===\n")

        # 1. Crear Intents
        print("1. Creando Intents...")
        for intent in INTENTS:
            await create_intent(client, intent)

        # 2. Crear Entities
        print("\n2. Creando Entities (tags, genre, game_name)...")
        await create_entity(client, "tags", ["free-text", "keywords"])
        await create_entity(client, "genre", ["free-text", "keywords"])
        await create_entity(client, "game_name", ["free-text"])

        # 3. Subir/Actualizar tags con sinónimos
        print("\n3. Agregando sinónimos en español a los Tags más comunes...")
        for tag, synonyms in TAG_SYNONYMS.items():
            print(f"   -> Actualizando sinónimos para {tag}...")
            # Primero nos aseguramos que el keyword exista
            await request_api(client, "POST", "/entities/tags/keywords", {"keyword": tag, "synonyms": [tag]})
            for syn in synonyms:
                await add_keyword_synonym(client, "tags", tag, syn)

        # 4. Entrenar Utterances
        await train_utterances(client)

        print("\n=== CONFIGURACIÓN FINALIZADA ===")
        print("Tu aplicación en Wit.ai está lista para ser usada.")

if __name__ == "__main__":
    asyncio.run(main())
