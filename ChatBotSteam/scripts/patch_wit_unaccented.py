"""
patch_wit_unaccented.py
-----------------------
Sube utterances SIN tildes para cubrir usuarios que escriben en español
sin acentos (muy común en móviles y teclados sin configuración regional).

También agrega más ejemplos de:
- check_price (sin tildes)
- ask_capabilities (sin tildes)
- refine_search contextual (frases de refinamiento)
- casual_chat variado (despedidas, reacciones)

Uso:
    python scripts/patch_wit_unaccented.py
"""

import asyncio
import os
import sys
import io

import httpx
from dotenv import load_dotenv

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

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

BATCH_SIZE = 50

# ---------------------------------------------------------------------------
# Utterances adicionales sin acentos + variantes importantes
# ---------------------------------------------------------------------------
RAW_UTTERANCES = [
    # ── CHECK_PRICE — sin tildes / variantes ──────────────────────────────────
    {"text": "cuanto cuesta Elden Ring",       "intent": "check_price", "entities": {"Elden Ring": "game_name"}},
    {"text": "cuanto cuesta Dark Souls",        "intent": "check_price", "entities": {"Dark Souls": "game_name"}},
    {"text": "cuanto vale Minecraft",           "intent": "check_price", "entities": {"Minecraft": "game_name"}},
    {"text": "cuanto sale Hades",               "intent": "check_price", "entities": {"Hades": "game_name"}},
    {"text": "precio de Hollow Knight",         "intent": "check_price", "entities": {"Hollow Knight": "game_name"}},
    {"text": "precio de Cyberpunk 2077",        "intent": "check_price", "entities": {"Cyberpunk 2077": "game_name"}},
    {"text": "que precio tiene Stardew Valley", "intent": "check_price", "entities": {"Stardew Valley": "game_name"}},
    {"text": "a cuanto esta GTA V",             "intent": "check_price", "entities": {"GTA V": "game_name"}},
    {"text": "dime el precio de Terraria",      "intent": "check_price", "entities": {"Terraria": "game_name"}},
    {"text": "esta en oferta RimWorld",         "intent": "check_price", "entities": {"RimWorld": "game_name"}},
    {"text": "tiene descuento The Witcher 3",   "intent": "check_price", "entities": {"The Witcher 3": "game_name"}},
    {"text": "cuanto cuesta Baldur's Gate 3",   "intent": "check_price", "entities": {"Baldur's Gate 3": "game_name"}},
    {"text": "cuanto sale Sekiro",              "intent": "check_price", "entities": {"Sekiro": "game_name"}},
    {"text": "precio actual de Monster Hunter", "intent": "check_price", "entities": {"Monster Hunter": "game_name"}},
    {"text": "cuanto cuesta Dead by Daylight",  "intent": "check_price", "entities": {"Dead by Daylight": "game_name"}},
    {"text": "cuanto esta Valheim",             "intent": "check_price", "entities": {"Valheim": "game_name"}},

    # ── ASK_CAPABILITIES — sin tildes / variantes ────────────────────────────
    {"text": "que puedes hacer",               "intent": "ask_capabilities", "entities": {}},
    {"text": "para que sirves",                "intent": "ask_capabilities", "entities": {}},
    {"text": "como funciona esto",             "intent": "ask_capabilities", "entities": {}},
    {"text": "que eres",                       "intent": "ask_capabilities", "entities": {}},
    {"text": "como te uso",                    "intent": "ask_capabilities", "entities": {}},
    {"text": "que haces",                      "intent": "ask_capabilities", "entities": {}},
    {"text": "puedes recomendar juegos",       "intent": "ask_capabilities", "entities": {}},
    {"text": "que juegos puedes recomendar",   "intent": "ask_capabilities", "entities": {}},
    {"text": "explicame como usarte",          "intent": "ask_capabilities", "entities": {}},
    {"text": "como funciona el bot",           "intent": "ask_capabilities", "entities": {}},
    {"text": "que tipos de busqueda soportas", "intent": "ask_capabilities", "entities": {}},
    {"text": "que informacion me puedes dar",  "intent": "ask_capabilities", "entities": {}},

    # ── REFINE_SEARCH — frases de contexto de refinamiento ───────────────────
    {"text": "dame mas opciones",                     "intent": "refine_search", "entities": {}},
    {"text": "muéstrame mas",                         "intent": "refine_search", "entities": {}},
    {"text": "muestrame mas",                         "intent": "refine_search", "entities": {}},
    {"text": "busco algo diferente",                  "intent": "refine_search", "entities": {}},
    {"text": "no me convence ninguno",                "intent": "refine_search", "entities": {}},
    {"text": "otro estilo",                           "intent": "refine_search", "entities": {}},
    {"text": "algo mas barato",                       "intent": "refine_search", "entities": {}},
    {"text": "que no sea tan caro",                   "intent": "refine_search", "entities": {}},
    {"text": "lo mismo pero para un jugador",         "intent": "refine_search", "entities": {}},
    {"text": "lo mismo pero solo",                    "intent": "refine_search", "entities": {}},
    {"text": "lo mismo pero en cooperativo",          "intent": "refine_search", "entities": {"cooperativo": "tags:Co-op"}},
    {"text": "lo mismo pero cooperativo",             "intent": "refine_search", "entities": {"cooperativo": "tags:Co-op"}},
    {"text": "igual pero cooperativo",                "intent": "refine_search", "entities": {"cooperativo": "tags:Co-op"}},
    {"text": "lo mismo pero con coop",                "intent": "refine_search", "entities": {"coop": "tags:Co-op"}},
    {"text": "algo similar pero gratis",              "intent": "refine_search", "entities": {}},
    {"text": "ese pero free to play",                 "intent": "refine_search", "entities": {}},
    {"text": "prefiero algo con mas accion",          "intent": "refine_search", "entities": {}},
    {"text": "que tenga multijugador",                "intent": "refine_search", "entities": {"multijugador": "tags:Multiplayer"}},
    {"text": "prefiero single player",               "intent": "refine_search", "entities": {}},
    {"text": "algo menos dificil",                   "intent": "refine_search", "entities": {}},
    {"text": "que no sea tan dificil",               "intent": "refine_search", "entities": {}},
    {"text": "con mejor puntaje",                    "intent": "refine_search", "entities": {}},
    {"text": "mejor valorado",                       "intent": "refine_search", "entities": {}},
    {"text": "algo mas reciente",                    "intent": "refine_search", "entities": {}},

    # ── CASUAL_CHAT — variantes adicionales ──────────────────────────────────
    {"text": "chao",                "intent": "casual_chat", "entities": {}},
    {"text": "ciao",                "intent": "casual_chat", "entities": {}},
    {"text": "bye",                 "intent": "casual_chat", "entities": {}},
    {"text": "hasta",               "intent": "casual_chat", "entities": {}},
    {"text": "adios",               "intent": "casual_chat", "entities": {}},
    {"text": "hasta pronto",        "intent": "casual_chat", "entities": {}},
    {"text": "nos vemos",           "intent": "casual_chat", "entities": {}},
    {"text": "oki",                 "intent": "casual_chat", "entities": {}},
    {"text": "oki doki",            "intent": "casual_chat", "entities": {}},
    {"text": "genial",              "intent": "casual_chat", "entities": {}},
    {"text": "perfecto",            "intent": "casual_chat", "entities": {}},
    {"text": "super",               "intent": "casual_chat", "entities": {}},
    {"text": "jaja",                "intent": "casual_chat", "entities": {}},
    {"text": "jajaja",              "intent": "casual_chat", "entities": {}},
    {"text": "lol",                 "intent": "casual_chat", "entities": {}},
    {"text": "xd",                  "intent": "casual_chat", "entities": {}},
    {"text": "que cool",            "intent": "casual_chat", "entities": {}},
    {"text": "que bueno",           "intent": "casual_chat", "entities": {}},
    {"text": "buenisimo",           "intent": "casual_chat", "entities": {}},
    {"text": "ya lo tengo",         "intent": "casual_chat", "entities": {}},
    {"text": "ya lo vi",            "intent": "casual_chat", "entities": {}},
    {"text": "no me gusto",         "intent": "casual_chat", "entities": {}},
    {"text": "no me interesa",      "intent": "casual_chat", "entities": {}},
    {"text": "esta muy caro",       "intent": "casual_chat", "entities": {}},
    {"text": "muy caro",            "intent": "casual_chat", "entities": {}},
    {"text": "esta barato",         "intent": "casual_chat", "entities": {}},
    {"text": "interesante",         "intent": "casual_chat", "entities": {}},
    {"text": "no sabia",            "intent": "casual_chat", "entities": {}},
    {"text": "gracias igual",       "intent": "casual_chat", "entities": {}},
    {"text": "muchas gracias",      "intent": "casual_chat", "entities": {}},
    {"text": "gracias amigo",       "intent": "casual_chat", "entities": {}},
    {"text": "dale",                "intent": "casual_chat", "entities": {}},
    {"text": "veamos",              "intent": "casual_chat", "entities": {}},
    {"text": "a ver",               "intent": "casual_chat", "entities": {}},
    {"text": "esta bien",           "intent": "casual_chat", "entities": {}},

    # ── COMPARE_GAMES — sin tildes ────────────────────────────────────────────
    {"text": "cual es mejor Hollow Knight o Celeste", "intent": "compare_games",
     "entities": {"Hollow Knight": "game_name", "Celeste": "game_name"}},
    {"text": "diferencias entre Hades y Dead Cells",  "intent": "compare_games",
     "entities": {"Hades": "game_name", "Dead Cells": "game_name"}},
    {"text": "compara Minecraft y Terraria",           "intent": "compare_games",
     "entities": {"Minecraft": "game_name", "Terraria": "game_name"}},

    # ── SEARCH_GAME — sin tildes ──────────────────────────────────────────────
    {"text": "juegos de terror baratos",          "intent": "search_game", "entities": {"terror": "tags:Horror"}},
    {"text": "algo de rol con historia",          "intent": "search_game", "entities": {"historia": "tags:Story Rich"}},
    {"text": "juego de estrategia por turnos",    "intent": "search_game", "entities": {"por turnos": "tags:Turn-Based"}},
    {"text": "quiero algo de mundos abiertos",    "intent": "search_game", "entities": {}},
    {"text": "survival con amigos",               "intent": "search_game", "entities": {"survival": "tags:Survival", "amigos": "tags:Co-op"}},
    {"text": "algo de zombies cooperativo",       "intent": "search_game", "entities": {"zombies": "tags:Zombies", "cooperativo": "tags:Co-op"}},
    {"text": "fps multijugador bueno",            "intent": "search_game", "entities": {"fps": "tags:FPS", "multijugador": "tags:Multiplayer"}},
    {"text": "juego de pixel art indie",          "intent": "search_game", "entities": {"pixel art": "tags:Pixel Graphics"}},
    {"text": "algo de souls-like facil",          "intent": "search_game", "entities": {}},
    {"text": "quiero un juego de granja",         "intent": "search_game", "entities": {"granja": "tags:Farming Sim"}},
]


async def _request(client, method, endpoint, json_data=None, delay=0.2):
    url = f"{BASE_URL}{endpoint}"
    params = {"v": WIT_API_VERSION}
    res = await client.request(method, url, params=params, headers=HEADERS, json=json_data)
    await asyncio.sleep(delay)
    return res


def _build_payload(raw):
    out = []
    for u in raw:
        text = u["text"]
        ents = []
        for substring, mapping in u.get("entities", {}).items():
            start = text.lower().find(substring.lower())
            if start == -1:
                continue
            end = start + len(substring)
            if ":" in mapping:
                entity_type = f"{mapping.split(':')[0]}:{mapping.split(':')[0]}"
            else:
                entity_type = f"{mapping}:{mapping}"
            ents.append({
                "entity": entity_type,
                "start": start,
                "end": end,
                "body": text[start:end],
                "entities": [],
            })
        out.append({"text": text, "intent": u["intent"], "entities": ents, "traits": []})
    return out


async def main():
    if not WIT_AI_TOKEN:
        print("ERROR: WIT_AI_TOKEN no configurado")
        return

    total = len(RAW_UTTERANCES)
    print(f"Subiendo {total} utterances adicionales (sin tildes + variantes)...")

    async with httpx.AsyncClient(timeout=30.0) as client:
        payload = _build_payload(RAW_UTTERANCES)
        ok_count = 0
        for start in range(0, total, BATCH_SIZE):
            batch = payload[start:start + BATCH_SIZE]
            end_idx = min(start + BATCH_SIZE, total)
            print(f"  Lote {start + 1}-{end_idx} / {total}...", end=" ", flush=True)
            res = await _request(client, "POST", "/utterances", batch, delay=0.4)
            if res.status_code in (200, 201):
                ok_count += len(batch)
                print("OK")
            else:
                print(f"ERROR {res.status_code}: {res.text[:100]}")

    print(f"\nListo: {ok_count}/{total} utterances subidas.")
    print("Wit.ai puede tardar 1-2 min en reentrenar. Luego prueba con: python _quick_test.py")


if __name__ == "__main__":
    asyncio.run(main())
