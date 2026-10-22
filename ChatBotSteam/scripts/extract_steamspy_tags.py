"""
extract_steamspy_tags.py
-----------------------
Extrae todas las tags disponibles en SteamSpy recorriendo sus endpoints
públicos. Genera un summary completo en docs/steamspy_tags_summary.md.

Estrategia (para minimizar tiempo respetando rate-limits):
  1. top100in2weeks, top100forever, top100owned → ~300 juegos con tags
  2. Páginas 0-4 del endpoint 'all' (1 req/60s cada una) → ~5000 juegos más
  3. Búsquedas por tags "semilla" conocidos para descubrir tags raras
  4. Consolidar, ordenar por frecuencia y generar el documento

Rate limits:
  - Endpoints normales (tag, genre, top100*): 1 req/s
  - Endpoint 'all': 1 req/60s

Usage:
  python -m ChatBotSteam.extract_steamspy_tags
"""

import time
import json
import sys
import os
from datetime import datetime
from collections import Counter
from typing import Optional

# Ensure the ChatBotSteam package directory is in sys.path so `from core import steam_api` works
_chatbot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _chatbot_dir not in sys.path:
    sys.path.insert(0, _chatbot_dir)

from core import steam_api

# ── Configuration ────────────────────────────────────────────────────────────

ALL_PAGES_TO_FETCH = 5       # Pages 0-4 del endpoint 'all' (5 min total)
ALL_PAGE_DELAY = 62.0         # 60s + 2s de margen para el endpoint 'all'
OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "docs",
    "steamspy_tags_summary.md",
)

# Tags semilla para búsquedas complementarias (si no alcanzamos 300 tags)
SEED_TAGS = [
    "Indie", "Action", "Adventure", "RPG", "Strategy", "Simulation",
    "Casual", "Racing", "Sports", "Free to Play", "Early Access",
    "Horror", "Survival", "Open World", "Multiplayer", "Singleplayer",
    "FPS", "Puzzle", "Platformer", "Rogue-like", "Rogue-lite",
    "Souls-like", "Metroidvania", "Visual Novel", "Dating Sim",
    "Bullet Hell", "Tower Defense", "Card Game", "Board Game",
    "MMORPG", "MOBA", "Battle Royale", "Hero Shooter",
    "Fighting", "Beat 'em up", "Hack and Slash", "Shooter",
    "Third-Person Shooter", "First-Person", "Third Person",
    "2D", "3D", "Pixel Graphics", "Voxel", "Hand-drawn",
    "Anime", "Cute", "Dark", "Atmospheric", "Story Rich",
    "Sci-fi", "Fantasy", "Cyberpunk", "Steampunk", "Post-apocalyptic",
    "Historical", "Medieval", "Space", "Underwater", "Western",
    "Comedy", "Drama", "Mystery", "Thriller", "War",
    "Choices Matter", "Multiple Endings", "Walking Simulator",
    "Exploration", "Mining", "Crafting", "Building", "Sandbox",
    "City Builder", "Colony Sim", "Farming Sim", "Life Sim",
    "Real-Time", "Turn-Based", "Turn-Based Strategy", "Real-Time Strategy",
    "Grand Strategy", "4X", "Wargame", "Tactical", "Stealth",
    "Rhythm", "Music", "Education", "Software", "Utilities",
    "Sexual Content", "Gore", "Violent", "Nudity",
    "Zombies", "Vampire", "Werewolves", "Dragons",
    "Robots", "Aliens", "Dinosaurs", "Pirates", "Ninja",
    "Co-op", "Local Co-Op", "Online Co-Op", "PvP", "PvE",
    "Competitive", "e-sports", "Difficult", "Perma Death",
    "Resource Management", "Economy", "Trading", "Diplomacy",
]


def extract_tags_from_games(games: dict, tag_counter: Counter) -> int:
    """Extrae todas las tags de un diccionario de juegos y las acumula en tag_counter.

    Returns:
        Número de juegos procesados con tags.
    """
    processed = 0
    for appid, game in games.items():
        if game.get("appid") == 999999:
            continue
        tags = game.get("tags", {})
        if isinstance(tags, dict):
            for tag_name in tags.keys():
                tag_counter[tag_name] += 1
            processed += 1
        elif isinstance(tags, list):
            # Algunos endpoints pueden devolver tags como lista
            for tag_name in tags:
                tag_counter[str(tag_name)] += 1
            processed += 1
    return processed


def fetch_top_endpoint(request_name: str, label: str, tag_counter: Counter) -> int:
    """Obtiene juegos de un endpoint top* y extrae tags."""
    print(f"  [{_now()}] Obteniendo {label}...")
    try:
        data = steam_api._get({"request": request_name})
        count = extract_tags_from_games(data, tag_counter)
        print(f"  [{_now()}]   -> {count} juegos procesados, "
              f"{len(tag_counter)} tags unicas acumuladas")
        return count
    except Exception as e:
        print(f"  [{_now()}]   [!] Error: {e}")
        return 0


def fetch_all_page(page: int, tag_counter: Counter) -> int:
    """Obtiene una página del endpoint 'all' con delay de 60s entre llamadas."""
    print(f"  [{_now()}] Obteniendo all&page={page} (delay {ALL_PAGE_DELAY}s)...")
    try:
        # Usamos _get directamente pero forzamos el delay de 60s
        # ya que steam_api._get solo espera 1s
        data = steam_api._get({"request": "all", "page": page})
        count = extract_tags_from_games(data, tag_counter)
        print(f"  [{_now()}]   -> {count} juegos procesados, "
              f"{len(tag_counter)} tags unicas acumuladas")
        return count
    except Exception as e:
        print(f"  [{_now()}]   [!] Error: {e}")
        return 0


def fetch_seed_tags(tag_counter: Counter, target: int = 300) -> bool:
    """Busca juegos por tags semilla para descubrir más tags.

    Returns:
        True si se alcanzó el target, False en caso contrario.
    """
    processed_seeds = 0
    for tag in SEED_TAGS:
        if len(tag_counter) >= target:
            return True
        try:
            data = steam_api.search_by_tag(tag)
            if data:
                n = extract_tags_from_games(data, tag_counter)
                processed_seeds += 1
                if processed_seeds % 10 == 0:
                    print(f"  [{_now()}]   {processed_seeds} seed tags procesadas, "
                          f"{len(tag_counter)} tags únicas")
        except Exception as e:
            print(f"  [{_now()}]   [!] seed_tag='{tag}' error: {e}")
    return len(tag_counter) >= target


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def generate_summary(tag_counter: Counter, stats: dict) -> str:
    """Genera el documento Markdown con el summary de tags."""
    total_unique = len(tag_counter)
    most_common = tag_counter.most_common(50)

    lines = []
    lines.append("# SteamSpy Tags — Catálogo Completo")
    lines.append("")
    lines.append(f"> Generado el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> Total de tags únicas encontradas: **{total_unique}**")
    lines.append(f"> Total de juegos analizados: **{stats['total_games']}**")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📊 Estadísticas de Extracción")
    lines.append("")
    lines.append("| Fuente | Juegos procesados |")
    lines.append("|--------|-------------------|")
    lines.append(f"| top100in2weeks | {stats.get('top2weeks', 0)} |")
    lines.append(f"| top100forever | {stats.get('topforever', 0)} |")
    lines.append(f"| top100owned | {stats.get('topowned', 0)} |")
    for page, count in stats.get('all_pages', {}).items():
        lines.append(f"| all&page={page} | {count} |")
    lines.append(f"| Seed tags ({stats.get('seed_tags_used', 0)} búsquedas) | {stats.get('seed_games', 0)} |")
    lines.append(f"| **Total** | **{stats['total_games']}** |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"## 🏷️ Lista Completa de Tags ({total_unique})")
    lines.append("")
    lines.append("> Las tags están ordenadas alfabéticamente. El número entre paréntesis indica")
    lines.append("> en cuántos juegos apareció cada tag durante la extracción (frecuencia relativa).")
    lines.append("")
    lines.append("| # | Tag | Frecuencia |")
    lines.append("|---|-----|------------|")

    # Ordenar alfabéticamente (case-insensitive)
    sorted_tags = sorted(tag_counter.items(), key=lambda x: x[0].lower())

    for i, (tag, count) in enumerate(sorted_tags, 1):
        lines.append(f"| {i} | `{tag}` | {count} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🔥 Top 50 Tags Más Frecuentes")
    lines.append("")
    lines.append("| # | Tag | Frecuencia |")
    lines.append("|---|-----|------------|")
    for i, (tag, count) in enumerate(most_common, 1):
        lines.append(f"| {i} | `{tag}` | {count} |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📝 Notas")
    lines.append("")
    lines.append("- Los datos provienen de [SteamSpy API](https://steamspy.com/api.php).")
    lines.append("- La frecuencia es relativa al sample de juegos analizados, no representa")
    lines.append("  la cantidad total de juegos en Steam con esa tag.")
    lines.append("- SteamSpy refresca sus datos una vez al día. Este catálogo debe")
    lines.append("  regenerarse periódicamente para mantenerse actualizado.")
    lines.append("- Las tags se usan en el sistema de búsqueda del chatbot para mejorar")
    lines.append("  la precisión al mapear consultas de usuarios a tags de SteamSpy.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🔧 Uso en el ChatBot")
    lines.append("")
    lines.append("Este catálogo alimenta `intent_model.py` y `llm_engine.py` para:")
    lines.append("")
    lines.append("1. **Normalización de tags**: mapear lenguaje natural del usuario → tags exactas de SteamSpy")
    lines.append("2. **Sugerencias**: cuando el usuario escribe una tag parcial, sugerir la tag correcta")
    lines.append("3. **Búsqueda precisa**: usar los nombres exactos de tags en `steam_api.search_by_tag()`")
    lines.append("")
    lines.append("### Ejemplo de mapeo en `intent_model.py`:")
    lines.append("")
    lines.append('```python')
    lines.append('# Tag aliases — mapea lenguaje natural a tags exactas de SteamSpy')
    lines.append('TAG_ALIASES = {')
    # Incluir algunos ejemplos de aliases comunes
    lines.append('    "miedo": "Horror",')
    lines.append('    "terror": "Horror",')
    lines.append('    "mundo abierto": "Open World",')
    lines.append('    "un jugador": "Singleplayer",')
    lines.append('    "multijugador": "Multiplayer",')
    lines.append('    "cooperativo": "Co-op",')
    lines.append('    "dificil": "Difficult",')
    lines.append('    "sigilo": "Stealth",')
    lines.append('    "caricaturas": "Cartoony",')
    lines.append('    # ... (añadir más aliases según el catálogo completo)')
    lines.append('}')
    lines.append('```')
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Documento generado automáticamente por `extract_steamspy_tags.py`*")

    return "\n".join(lines)


def main():
    print("=" * 70)
    print("  SteamSpy Tag Extractor")
    print(f"  Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Target: >300 tags únicas")
    print(f"  Output: {OUTPUT_PATH}")
    print("=" * 70)

    tag_counter = Counter()
    stats = {
        "top2weeks": 0,
        "topforever": 0,
        "topowned": 0,
        "all_pages": {},
        "seed_tags_used": 0,
        "seed_games": 0,
        "total_games": 0,
    }

    # ── Fase 1: Top endpoints (rápido, ~3 segundos) ───────────────────────
    print(f"\n[{_now()}] FASE 1: Top endpoints (top100*)")
    print("-" * 50)

    # Verificar conectividad primero (no bloqueante)
    print(f"  [{_now()}] Verificando conectividad con SteamSpy...")
    available = steam_api.is_steamspy_available()
    if not available:
        print(f"  [{_now()}] [!] SteamSpy health check fallo, pero intentaremos igual...")
    else:
        print(f"  [{_now()}] SteamSpy responde OK")

    stats["top2weeks"] = fetch_top_endpoint("top100in2weeks", "top100in2weeks", tag_counter)
    stats["topforever"] = fetch_top_endpoint("top100forever", "top100forever", tag_counter)
    stats["topowned"] = fetch_top_endpoint("top100owned", "top100owned", tag_counter)

    print(f"\n  [{_now()}] Tags únicas tras Fase 1: {len(tag_counter)}")

    # ── Fase 2: Páginas del endpoint 'all' (lento, 60s por página) ───────
    print(f"\n[{_now()}] FASE 2: Endpoint 'all' ({ALL_PAGES_TO_FETCH} páginas)")
    print(f"  [!] Cada pagina requiere ~{ALL_PAGE_DELAY}s de espera (rate limit 1 req/60s)")
    print(f"  [!] Tiempo estimado: ~{ALL_PAGES_TO_FETCH * ALL_PAGE_DELAY / 60:.0f} minutos")
    print("-" * 50)

    # Delay inicial para respetar el rate limit del endpoint 'all'
    # (ya hicimos 3 requests a otros endpoints, necesitamos asegurar 60s desde
    # la última request al endpoint 'all', pero como es la primera, esperamos
    # solo si es necesario)
    print(f"  [{_now()}] Esperando {ALL_PAGE_DELAY}s antes de la primera página 'all'...")
    time.sleep(ALL_PAGE_DELAY)

    for page in range(ALL_PAGES_TO_FETCH):
        count = fetch_all_page(page, tag_counter)
        stats["all_pages"][page] = count
        if page < ALL_PAGES_TO_FETCH - 1:
            print(f"  [{_now()}] Esperando {ALL_PAGE_DELAY}s para siguiente página...")
            time.sleep(ALL_PAGE_DELAY)

    print(f"\n  [{_now()}] Tags únicas tras Fase 2: {len(tag_counter)}")

    # ── Fase 3: Seed tags complementarias (si no llegamos a 300) ──────────
    if len(tag_counter) < 300:
        print(f"\n[{_now()}] FASE 3: Búsqueda por tags semilla "
              f"(faltan {300 - len(tag_counter)} tags para llegar a 300)")
        print("-" * 50)
        reached = fetch_seed_tags(tag_counter, target=300)
        stats["seed_tags_used"] = SEED_TAGS.__len__()  # todas las que intentamos
        # La cuenta exacta de juegos de seed tags no la trackeamos individualmente
        print(f"\n  [{_now()}] Tags únicas tras Fase 3: {len(tag_counter)}")
        if reached:
            print(f"  [{_now()}] [OK] Target de 300 tags alcanzado!")
    else:
        print(f"\n[{_now()}] FASE 3: Omitida — ya tenemos {len(tag_counter)} tags (≥300)")

    # ── Calcular total de juegos ──────────────────────────────────────────
    stats["total_games"] = (
        stats["top2weeks"]
        + stats["topforever"]
        + stats["topowned"]
        + sum(stats["all_pages"].values())
    )

    # ── Generar documento ─────────────────────────────────────────────────
    print(f"\n[{_now()}] Generando documento: {OUTPUT_PATH}")
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    content = generate_summary(tag_counter, stats)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    # ── Resumen final ─────────────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  EXTRACCIÓN COMPLETADA")
    print(f"{'=' * 70}")
    print(f"  Tags únicas:        {len(tag_counter)}")
    print(f"  Juegos analizados:  {stats['total_games']}")
    print(f"  Documento:          {OUTPUT_PATH}")
    print(f"  Fin:                {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 70}")

    # Mostrar top 10 tags
    print(f"\n  Top 10 tags más frecuentes:")
    for tag, count in tag_counter.most_common(10):
        print(f"    {count:5d}  {tag}")


if __name__ == "__main__":
    main()
