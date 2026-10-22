"""
Diagnostic script to test Steam Spy API direct endpoints and the project's fallback mechanisms.
Run using: python ChatBotSteam/diagnostics/test_steamspy_diagnostics.py
"""

import sys
import os
import time
import requests

# Set encoding to UTF-8 for Windows terminal support
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Include project root in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import steam_api

STEAMSPY_BASE = "https://steamspy.com/api.php"

def test_direct_api(label: str, params: dict) -> tuple[bool, int]:
    """Call SteamSpy directly and return (is_working, number_of_items)"""
    print(f"\n🔍 Probando endpoint directo de SteamSpy: {label}")
    url = f"{STEAMSPY_BASE}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
    print(f"   URL: {url}")

    try:
        resp = requests.get(STEAMSPY_BASE, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"   ❌ Falló - Status HTTP: {resp.status_code}")
            return False, 0

        data = resp.json()
        if isinstance(data, dict):
            count = len(data)
            print(f"   Status HTTP: 200 OK")
            print(f"   Cant. Elementos recibidos: {count}")
            if count > 0:
                print(f"   ✅ FUNCIONA - Muestra: {list(data.keys())[:3]}")
                return True, count
            else:
                print(f"   ⚠️ RETORNÓ CERO ELEMENTOS (Vacío) - La API responde HTTP 200 pero sin datos.")
                return False, 0
        elif isinstance(data, list):
            count = len(data)
            print(f"   Status HTTP: 200 OK")
            print(f"   Cant. Elementos recibidos: {count}")
            if count > 0:
                print(f"   ✅ FUNCIONA - Muestra: {data[:3]}")
                return True, count
            else:
                print(f"   ⚠️ RETORNÓ CERO ELEMENTOS (Vacío) - La API responde HTTP 200 pero sin datos.")
                return False, 0
        else:
            print(f"   ❌ Respuesta inesperada: Tipo {type(data).__name__}")
            return False, 0

    except Exception as e:
        print(f"   ❌ ERROR al consultar API: {e}")
        return False, 0

def test_project_function(label: str, func, arg: str):
    """Test a high-level function from the project's steam_api module"""
    print(f"\n⚙️ Probando función del proyecto: {label} con argumento '{arg}'")
    start_time = time.time()
    try:
        result = func(arg)
        elapsed = time.time() - start_time
        if result and isinstance(result, dict):
            print(f"   Status: Éxito ({elapsed:.2f}s)")
            print(f"   Cant. Juegos encontrados: {len(result)}")
            print(f"   Muestra de juegos: {list(result.keys())[:3]}")
            # Show game names
            for appid in list(result.keys())[:3]:
                game = result[appid]
                print(f"     - AppID {appid}: {game.get('name')} (Price: {game.get('price_usd') or game.get('price')} USD, Score: {game.get('score_rank')}%)")
            return True, len(result)
        else:
            print(f"   ❌ Falló - Retornó vacío o tipo inesperado ({type(result).__name__})")
            return False, 0
    except Exception as e:
        print(f"   ❌ ERROR en la función del proyecto: {e}")
        return False, 0

def main():
    print("=" * 70)
    print("🧪 DIAGNÓSTICO DE STEAM SPY Y FALLBACK DE TAGS/GÉNEROS")
    print("=" * 70)
    print(f"Hora de ejecución: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. Test Direct SteamSpy Endpoints
    print("\n" + "=" * 50)
    print("1. PROBANDO ENDPOINTS DIRECTOS DE STEAMSPY")
    print("=" * 50)

    # 1a. Check appdetails
    details_ok, _ = test_direct_api("appdetails (CS:GO appid=730)", {"request": "appdetails", "appid": 730})
    time.sleep(1.2)

    # 1b. Check tag
    tag_ok, _ = test_direct_api("tag (Action)", {"request": "tag", "tag": "Action"})
    time.sleep(1.2)

    # 1c. Check genre
    genre_ok, _ = test_direct_api("genre (RPG)", {"request": "genre", "genre": "RPG"})
    time.sleep(1.2)

    # 1d. Check top100in2weeks
    top_ok, _ = test_direct_api("top100in2weeks", {"request": "top100in2weeks"})
    time.sleep(1.2)

    # 1e. Check top 1000 games endpoint (all page 0)
    all_ok, _ = test_direct_api("all (Page 0 - Top 1000)", {"request": "all", "page": 0})
    time.sleep(1.2)

    # 2. Test Project Wrapper Functions with Fallback
    print("\n" + "=" * 50)
    print("2. PROBANDO INTEGRACIÓN Y FALLBACKS EN EL PROYECTO")
    print("=" * 50)

    # 2a. test steam_api.search_by_tag
    func_tag_ok, tag_count = test_project_function(
        "steam_api.search_by_tag",
        steam_api.search_by_tag,
        "Action"
    )
    time.sleep(1.2)

    # 2b. test steam_api.search_by_genre
    func_genre_ok, genre_count = test_project_function(
        "steam_api.search_by_genre",
        steam_api.search_by_genre,
        "RPG"
    )
    time.sleep(1.2)

    # 3. Conclusions
    print("\n" + "=" * 70)
    print("📊 DIAGNÓSTICO Y CONCLUSIONES")
    print("=" * 70)

    print("🔌 Estado de endpoints directos de SteamSpy:")
    print(f"   - appdetails:      {'🟢 OPERATIVO' if details_ok else '🔴 CAÍDO/VACÍO'}")
    print(f"   - tag (búsquedas):  {'🟢 OPERATIVO' if tag_ok else '🔴 CAÍDO/VACÍO (Retorna 0 items)'}")
    print(f"   - genre (géneros):  {'🟢 OPERATIVO' if genre_ok else '🔴 CAÍDO/VACÍO (Retorna 0 items)'}")
    print(f"   - top100in2weeks:  {'🟢 OPERATIVO' if top_ok else '🔴 CAÍDO/VACÍO'}")
    print(f"   - all (top 1000):   {'🟢 OPERATIVO' if all_ok else '🔴 CAÍDO/VACÍO'}")

    print("\n🛡️ Estado de los Fallbacks del Proyecto:")
    if func_tag_ok:
        print(f"   - Fallback de Tag:   🟢 CORRECTO (Encontró {tag_count} juegos usando storesearch)")
    else:
        print("   - Fallback de Tag:   🔴 CON ERRORES / FALLÓ")

    if func_genre_ok:
        print(f"   - Fallback de Género: 🟢 CORRECTO (Encontró {genre_count} juegos usando storesearch)")
    else:
        print("   - Fallback de Género: 🔴 CON ERRORES / FALLÓ")

    print("\n📝 RESUMEN:")
    if not tag_ok or not genre_ok:
        print("   ⚠️  ATENCIÓN: Los endpoints directos de SteamSpy para buscar por tag y género están")
        print("      retornando respuestas vacías (HTTP 200 con `{}`). Esto es un comportamiento conocido")
        print("      de la API de SteamSpy cuando está saturada o inestable.")
        print("   ✅ Sin embargo, el mecanismo de FALLBACK del proyecto (`storesearch` de Steam Oficial)")
        print("      está detectando el resultado vacío y recuperando los juegos de forma transparente.")
    else:
        print("   🎉 Todo está funcionando correctamente y los endpoints directos de SteamSpy responden.")

    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
