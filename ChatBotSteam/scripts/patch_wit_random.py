"""
patch_wit_random.py
-------------------
Sube utterances para la intención 'random_game' (buscar cualquier juego).
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

RAW_UTTERANCES = [
    # ── RANDOM_GAME ──────────────────────────────────────────────────────────
    {"text": "recomiendame cualquier juego",    "intent": "random_game", "entities": {}},
    {"text": "dame un juego al azar",           "intent": "random_game", "entities": {}},
    {"text": "buscar cualquier juego",          "intent": "random_game", "entities": {}},
    {"text": "sugiereme algo para jugar",       "intent": "random_game", "entities": {}},
    {"text": "que me recomiendas jugar",        "intent": "random_game", "entities": {}},
    {"text": "dime un juego cualquiera",        "intent": "random_game", "entities": {}},
    {"text": "cualquier cosa",                  "intent": "random_game", "entities": {}},
    {"text": "lo que sea",                      "intent": "random_game", "entities": {}},
    {"text": "juego al azar",                   "intent": "random_game", "entities": {}},
    {"text": "sorprendeme con un juego",        "intent": "random_game", "entities": {}},
    {"text": "quiero jugar algo",               "intent": "random_game", "entities": {}},
    {"text": "no se que jugar",                 "intent": "random_game", "entities": {}},
    {"text": "recomiéndame cualquier juego",    "intent": "random_game", "entities": {}},
    {"text": "sugiéreme algo para jugar",       "intent": "random_game", "entities": {}},
    {"text": "qué me recomiendas jugar",        "intent": "random_game", "entities": {}},
    {"text": "no sé qué jugar",                 "intent": "random_game", "entities": {}},
    {"text": "sorpréndeme con un juego",        "intent": "random_game", "entities": {}},
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Primero crear el intent si no existe
        print("Creando/verificando intent 'random_game'...")
        res = await _request(client, "POST", "/intents", {"name": "random_game"})
        if res.status_code not in (200, 201) and res.status_code != 409 and res.status_code != 400:
            print(f"Error creando intent: {res.status_code} - {res.text}")

        total = len(RAW_UTTERANCES)
        print(f"Subiendo {total} utterances...")
        payload = _build_payload(RAW_UTTERANCES)
        ok_count = 0
        for start in range(0, total, BATCH_SIZE):
            batch = payload[start:start + BATCH_SIZE]
            res = await _request(client, "POST", "/utterances", batch, delay=0.4)
            if res.status_code in (200, 201):
                ok_count += len(batch)
            else:
                print(f"ERROR {res.status_code}: {res.text[:100]}")

    print(f"\nListo: {ok_count}/{total} utterances subidas.")

if __name__ == "__main__":
    asyncio.run(main())
