"""
Script to build and update the local top games database (with tags).
Run using: python -m scripts.build_top_games_db [limit]
"""

import sys
import os
import time
import json
import requests

# Set encoding to UTF-8 for Windows terminal support
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Include project root in sys.path
_chatbot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _chatbot_dir not in sys.path:
    sys.path.insert(0, _chatbot_dir)

from core import steam_api

CACHE_FILE = os.path.join(_chatbot_dir, "core", "top_1000_cache.json")
STEAMSPY_BASE = "https://steamspy.com/api.php"

def load_existing_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"⚠️ Error al leer caché existente: {e}")
    return {}

def save_cache(data: dict):
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"❌ Error al guardar caché: {e}")

def fetch_top_games_list() -> dict:
    """Gets the list of top games from SteamSpy page 0. Falls back to top list endpoints if rate limited."""
    print("📋 Obteniendo listado de juegos más populares...")

    # Try request=all&page=0
    try:
        resp = requests.get(STEAMSPY_BASE, params={"request": "all", "page": 0}, timeout=15)
        if resp.status_code == 200 and "Connection failed" not in resp.text:
            data = resp.json()
            if isinstance(data, dict) and len(data) > 0:
                print(f"   Listo: Encontrados {len(data)} juegos en el Top 1000 (Pág 0).")
                return data
    except Exception as e:
        print(f"   ⚠️ Falló request=all&page=0: {e}")

    # Try request=all&page=1
    try:
        print("   ⚠️ Intentando request=all&page=1 como fallback principal...")
        resp = requests.get(STEAMSPY_BASE, params={"request": "all", "page": 1}, timeout=15)
        if resp.status_code == 200 and "Connection failed" not in resp.text:
            data = resp.json()
            if isinstance(data, dict) and len(data) > 0:
                print(f"   Listo: Encontrados {len(data)} juegos en el Top 1000 (Pág 1).")
                return data
    except Exception as e:
        print(f"   ⚠️ Falló request=all&page=1: {e}")

    print("   ⚠️ Intentando fallbacks (top100owned, top100forever, top100in2weeks)...")
    time.sleep(1.5)

    combined = {}
    for req in ["top100owned", "top100forever", "top100in2weeks"]:
        try:
            resp = requests.get(STEAMSPY_BASE, params={"request": req}, timeout=15)
            if resp.status_code == 200 and "Connection failed" not in resp.text:
                data = resp.json()
                if isinstance(data, dict):
                    combined.update(data)
            time.sleep(1.2)
        except Exception as e:
            print(f"   ⚠️ Falló {req}: {e}")

    # Fetch additional games for specific important tags to ensure we have variety
    extra_tags = ["Racing", "Sports", "Simulation", "Horror", "RPG", "Strategy", "Action", "Adventure"]
    print("   📥 Obteniendo juegos adicionales de tags clave para asegurar variedad...")
    for tag in extra_tags:
        try:
            print(f"     Consultando tag: '{tag}'...")
            resp = requests.get(STEAMSPY_BASE, params={"request": "tag", "tag": tag.lower()}, timeout=15)
            if resp.status_code == 200 and "Connection failed" not in resp.text:
                data = resp.json()
                if isinstance(data, dict):
                    # Sort them by owners to get the top games for this tag
                    games_list = list(data.values())
                    def parse_owners(g):
                        try:
                            return int(g.get('owners', '0').split('..')[0].replace(',', '').strip())
                        except:
                            return 0
                    games_list.sort(key=parse_owners, reverse=True)
                    # Take top 30 games for this tag and add them to combined
                    for g in games_list[:30]:
                        appid_str = str(g.get("appid"))
                        if appid_str:
                            combined[appid_str] = g
            time.sleep(1.2)
        except Exception as e:
            print(f"     ⚠️ Falló tag '{tag}': {e}")

    print(f"   Listo: Encontrados {len(combined)} juegos únicos vía fallbacks y tags clave.")
    return combined

def main():
    # Allow passing limit as parameter (e.g. limit to 100 or 250 for quick run)
    limit = 1000
    if len(sys.argv) > 1:
        try:
            limit = int(sys.argv[1])
        except ValueError:
            pass

    print("=" * 70)
    print(f"🚀 INICIANDO CONSTRUCCIÓN DE BASE DE DATOS LOCAL DE JUEGOS (Límite: {limit})")
    print(f"   Archivo destino: {CACHE_FILE}")
    print("=" * 70)

    cache = load_existing_cache()
    print(f"ℹ️ Caché existente contiene {len(cache)} juegos.")

    # Fetch target list of games
    target_games = fetch_top_games_list()
    if not target_games:
        print("💀 ERROR: No se pudo obtener ningún listado de juegos de SteamSpy. Abortando.")
        return

    # Sort target games by owners/popularity (from target_games metadata)
    def parse_owners(owners_str: str) -> int:
        if not owners_str: return 0
        try:
            parts = owners_str.replace(",", "").split("..")
            if len(parts) == 2: return int(parts[1])
        except: pass
        return 0

    sorted_appids = sorted(
        target_games.keys(),
        key=lambda k: parse_owners(target_games[k].get("owners", "")),
        reverse=True
    )

    # Restrict to limit
    sorted_appids = sorted_appids[:limit]

    to_fetch = []
    for appid in sorted_appids:
        if appid not in cache or not cache[appid].get("tags") or not isinstance(cache[appid].get("tags"), dict):
            to_fetch.append(appid)

    print(f"ℹ️ Total juegos a procesar: {len(sorted_appids)}")
    print(f"ℹ️ Juegos ya en caché con tags: {len(sorted_appids) - len(to_fetch)}")
    print(f"ℹ️ Juegos pendientes por descargar tags: {len(to_fetch)}")

    if not to_fetch:
        print("🎉 ¡La caché local está completamente actualizada! No hay nada que descargar.")
        return

    print("\n📥 Descargando detalles (tags, reviews, genres) desde SteamSpy...")
    print("   (Respetando rate-limit de 1.2 segundos por llamada)")
    print("-" * 70)

    success_count = 0
    start_time = time.time()

    try:
        for idx, appid in enumerate(to_fetch, 1):
            game_base = target_games[appid]
            name = game_base.get("name", "Unknown")
            print(f"[{idx}/{len(to_fetch)}] Descargando: {name} (AppID: {appid})...")

            success = False
            # Try up to 3 times with exponential backoff if we hit "Connection failed" or JSON decode issues
            for attempt in range(1, 4):
                try:
                    resp = requests.get(STEAMSPY_BASE, params={"request": "appdetails", "appid": appid}, timeout=10)
                    if resp.status_code == 200:
                        text = resp.text
                        if "Connection failed" in text:
                            print(f"   ⚠️ [Intento {attempt}/3] Servidor sobrecargado ('Connection failed') para AppID {appid}.")
                            if attempt < 3:
                                time.sleep(3 * attempt)
                                continue
                            else:
                                break

                        details = resp.json()
                        if details and isinstance(details, dict) and details.get("name"):
                            # Save it in cache
                            cache[appid] = details
                            success_count += 1
                            success = True

                            # Save cache every 10 successful fetches to prevent data loss
                            if success_count % 10 == 0:
                                save_cache(cache)
                                print(f"   💾 Guardado parcial: {len(cache)} juegos totales en disco.")
                            break
                        else:
                            print(f"   ⚠️ Respuesta vacía o inválida para AppID {appid}")
                            break
                    else:
                        print(f"   ❌ Error HTTP {resp.status_code} para AppID {appid}")
                        break
                except json.JSONDecodeError:
                    print(f"   ⚠️ [Intento {attempt}/3] Error al decodificar JSON (posible HTML/texto de error) para AppID {appid}.")
                    if attempt < 3:
                        time.sleep(3 * attempt)
                        continue
                    else:
                        break
                except Exception as e:
                    print(f"   ❌ Error al descargar AppID {appid}: {e}")
                    break

            # Rate limit delay
            time.sleep(1.2)

    except KeyboardInterrupt:
        print("\n🛑 Ejecución interrumpida por el usuario. Guardando avance...")

    save_cache(cache)
    elapsed = time.time() - start_time
    print("=" * 70)
    print("📊 RESUMEN DE CONSTRUCCIÓN")
    print("=" * 70)
    print(f"   Total juegos en caché local: {len(cache)}")
    print(f"   Juegos descargados en esta ejecución: {success_count}")
    print(f"   Tiempo transcurrido: {elapsed/60:.2f} minutos")
    print(f"   Ubicación: {CACHE_FILE}")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    main()
