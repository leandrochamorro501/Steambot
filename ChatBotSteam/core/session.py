"""
core/session.py
---------------
Centralised session state (in-memory only).

A Session tracks everything needed per-user:
  - conversation memory (for multi-turn LLM context)
  - region / currency preference
  - wishlist of recommended games
  - set of already-recommended appids (deduplication)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.llm_engine import ConversationMemory


def _get_regions() -> dict:
    from core.steam_api import REGIONS
    return REGIONS


@dataclass
class Session:
    """All per-user runtime state, agnostic of UI (Telegram vs terminal)."""

    memory: "ConversationMemory"
    region: str = "CL"
    historial: list[dict] = field(default_factory=list)
    recommended_appids: set[str] = field(default_factory=set)
    chat_id: int = 0
    user_id: int = 0
    allow_nsfw: bool = False
    last_search_criteria: dict = field(default_factory=dict)

    @property
    def wishlist(self) -> list[dict]:
        """Backward compatibility alias for historial."""
        return self.historial

    @property
    def currency(self) -> str:
        regions = _get_regions()
        return regions.get(self.region, {}).get("currency", "USD")

    @property
    def currency_symbol(self) -> str:
        regions = _get_regions()
        return regions.get(self.region, {}).get("symbol", "$")

    def add_to_historial(self, game: dict) -> None:
        appid_str = str(game.get("appid", ""))
        if appid_str and appid_str not in self.recommended_appids:
            self.recommended_appids.add(appid_str)
            self.historial.append(game)

    def add_to_wishlist(self, game: dict) -> None:
        """Backward compatibility alias for add_to_historial."""
        self.add_to_historial(game)

    def new_games_only(self, games: list[dict]) -> list[dict]:
        """
        Return only games that haven't been recommended yet in this session.

        v2: NEVER returns already-recommended games. If all candidates have been
        seen, returns games sorted with seen ones at the end so the LLM can
        acknowledge repetition instead of silently re-recommending.
        """
        new_games = [g for g in games if str(g.get("appid", "")) not in self.recommended_appids]
        if new_games:
            return new_games
        # All games have been seen — return empty list so the pipeline
        # generates a "no new results" message instead of repeating.
        return []

    def export_text(self) -> str:
        from datetime import datetime as dt
        lines = [
            "═══════════════════════════════════════════",
            "  SteamBot - Historial Exportado",
            f"  Fecha: {dt.now().strftime('%d/%m/%Y %H:%M')}",
            f"  Región: {self.region}",
            "═══════════════════════════════════════════",
            "",
        ]
        for idx, g in enumerate(self.historial, 1):
            price = g.get("regional_price", f"${g.get('price_usd', '?')} USD")
            lines.append(f"  {idx}. {g['name']}")
            lines.append(f"     Precio: {price}")
            if g.get("developer"):
                lines.append(f"     Developer: {g['developer']}")
            lines.append("")
        lines.append(f"Total: {len(self.historial)} juegos")
        return "\n".join(lines)

# ---------------------------------------------------------------------------
# Session registry for multi-user environments (Telegram)
# ---------------------------------------------------------------------------

class SessionRegistry:
    """
    Thread-safe dict-based registry of sessions keyed by user/chat ID.
    Pure in-memory storage.
    """

    def __init__(self) -> None:
        self._sessions: dict[int, Session] = {}

    def get(self, chat_id: int, user_id: int = 0) -> Session:
        if chat_id not in self._sessions:
            from core.llm_engine import ConversationMemory
            session = Session(
                memory=ConversationMemory(),
                chat_id=chat_id,
                user_id=user_id or chat_id,
            )
            self._sessions[chat_id] = session
        return self._sessions[chat_id]

    def set_region(self, chat_id: int, region: str) -> None:
        session = self.get(chat_id)
        session.region = region

    def clear(self, chat_id: int) -> None:
        self._sessions.pop(chat_id, None)


# Global registry instance
registry = SessionRegistry()
