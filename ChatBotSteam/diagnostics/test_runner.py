"""
Script de prueba rapida para main.py (sin interfaz interactiva).
Prueba el pipeline completo con el fallback rule-based.
"""
# -*- coding: utf-8 -*-
import asyncio
import sys
import os
import io

# Fix encoding on Windows terminal
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm_engine import ConversationMemory, memory, fallback_intent
from core.pipeline import run_pipeline
from core.session import Session
from core.steam_api import REGIONS, region_from_language, LANGUAGE_TO_REGION

PASS = 0
FAIL = 0

def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}: {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}: {detail}")

# ===================================================================
# Test 1: Fallback intent classifier
# ===================================================================
print("=" * 60)
print("TEST 1: Clasificador de intencion (fallback rule-based)")
print("=" * 60)

tests = [
    ("Hola", "CASUAL_CHAT"),
    ("Gracias", "CASUAL_CHAT"),
    ("Que puedes hacer?", "ASK_CAPABILITIES"),
    ("Quiero juegos de terror", "SEARCH_GAME"),
    ("RPG con mundo abierto", "SEARCH_GAME"),
    ("Cuanto cuesta Elden Ring", "CHECK_PRICE"),
    ("Juegos baratos en oferta", "SEARCH_GAME"),
    ("Algo multijugador con amigos", "SEARCH_GAME"),
    ("Compara Dark Souls con Elden Ring", "COMPARE_GAMES"),
    ("juegos gratis", "SEARCH_GAME"),
]

for msg, expected in tests:
    intent = fallback_intent(msg)
    ok = intent["intent_type"] == expected
    check(f"'{msg}' -> {intent['intent_type']}", ok, f"esperado={expected}" if not ok else "")

# ===================================================================
# Test 2: Pipeline async (Chat / no-search paths)
# ===================================================================
print("\n" + "=" * 60)
print("TEST 2: Pipeline asincrono - respuestas de chat")
print("=" * 60)

async def test_pipeline():
    session = Session(
        memory=ConversationMemory(),
        region="CL",
        user_id=999,
        chat_id=999,
    )

    # Test chat message (should fall back to chat response)
    try:
        result = await run_pipeline("Hola, como estas?", session, user_id=999)
        check(
            "Pipeline 'Hola' status",
            result.status in ("ok", "chat"),
            f"status={result.status}, response={result.response_text[:80] if result.response_text else 'empty'}"
        )
        check(
            "Pipeline 'Hola' tiene texto",
            bool(result.response_text),
            f"response_text vacio"
        )
    except Exception as e:
        check("Pipeline 'Hola' exception", False, str(e)[:120])

    # Test help message
    try:
        result2 = await run_pipeline("ayuda", session, user_id=999)
        check(
            "Pipeline 'ayuda' no crashea",
            True,
            f"status={result2.status}"
        )
    except Exception as e:
        check("Pipeline 'ayuda' exception", False, str(e)[:120])

    # Test game search (requires SteamSpy API)
    try:
        result3 = await run_pipeline("Quiero juegos de terror", session, user_id=999)
        check(
            "Pipeline 'juegos de terror' ejecuto",
            True,
            f"status={result3.status}"
        )
        if result3.status == "ok":
            check(
                "Pipeline 'juegos de terror' encontro juegos",
                len(result3.games_found) > 0,
                f"encontrados={len(result3.games_found)}"
            )
        elif result3.status == "unavailable":
            print("  [WARN] SteamSpy no disponible (esperado si no hay internet)")
    except Exception as e:
        check("Pipeline 'juegos de terror' exception", False, str(e)[:120])

asyncio.run(test_pipeline())

# ===================================================================
# Test 3: Session methods
# ===================================================================
print("\n" + "=" * 60)
print("TEST 3: Session y wishlist")
print("=" * 60)

def test_session():
    mem = ConversationMemory()
    s = Session(memory=mem, region="CL")

    check("Session region=CL", s.region == "CL")
    check("Session currency=CLP", s.currency == "CLP")
    check("Session symbol=CLP$", s.currency_symbol == "CLP$")
    check("Wishlist vacia", len(s.wishlist) == 0)

    s.add_to_wishlist({"appid": 730, "name": "CS:GO", "price_usd": 0.0, "developer": "Valve"})
    check("Wishlist +1", len(s.wishlist) == 1)
    check("appid en recommended", "730" in s.recommended_appids)

    s.add_to_wishlist({"appid": 730, "name": "CS:GO dupe", "price_usd": 0.0})
    check("No duplicados", len(s.wishlist) == 1, f"size={len(s.wishlist)}")

    new = s.new_games_only([{"appid": 730, "name": "CS:GO"}])
    check("new_games_only filtra duplicado", len(new) == 0,
          "debe retornar lista vacía cuando todos son duplicados (comportamiento v2)")

    new2 = s.new_games_only([{"appid": 570, "name": "Dota 2"}])
    check("new_games_only permite nuevo", len(new2) == 1)

    exported = s.export_text()
    check("export_text contiene CS:GO", "CS:GO" in exported)
    check("export_text contiene CLP", "CLP" in exported or "CL" in exported)

test_session()

# ===================================================================
# Test 4: Steam API regions
# ===================================================================
print("\n" + "=" * 60)
print("TEST 4: Steam API - regiones")
print("=" * 60)

check("REGIONS tiene 9 entradas", len(REGIONS) == 9, str(len(REGIONS)))
check("region_from_language('es')", region_from_language("es") == "CL")
check("region_from_language('es-cl')", region_from_language("es-cl") == "CL")
check("region_from_language('en')", region_from_language("en") == "US")
check("region_from_language('pt-br')", region_from_language("pt-br") == "BR")
check("region_from_language('fr') -> CL default", region_from_language("fr") == "CL")
check("region_from_language('') -> CL default", region_from_language("") == "CL")
check("REGIONS['CL'] label", REGIONS["CL"]["label"] == "Chile (CLP)")

# ===================================================================
# Resultado final
# ===================================================================
print("\n" + "=" * 60)
total = PASS + FAIL
pct = (PASS / total * 100) if total > 0 else 0
print(f"RESULTADO: {PASS} [PASS] / {FAIL} [FAIL]  ({pct:.0f}% pass)")
print("=" * 60)

if FAIL > 0:
    sys.exit(1)
else:
    sys.exit(0)
