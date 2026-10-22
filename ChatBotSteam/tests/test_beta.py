"""
tests/test_beta.py
------------------
Tests for SteamBot Beta branch.

Covers:
  - Rule-based intent fallback
  - ConversationMemory summarization
  - Price formatting (currency.py)
  - Tag normalization (tag_registry)
  - Session management
  - No-results message builder

All tests work offline (no SteamSpy, no DB required).
"""

import sys
import os

# Ensure the ChatBotSteam package root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


# ============================================================================
# 1. Rule-based fallback intent extraction
# ============================================================================

class TestFallbackIntent:
    """Verify that fallback_intent() works locally."""

    def test_greeting(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("Hola, ¿cómo estás?")
        assert result["intent_type"] == "CASUAL_CHAT"
        assert result["is_game_query"] is False

    def test_thanks(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("Gracias por la ayuda")
        assert result["intent_type"] == "CASUAL_CHAT"

    def test_capabilities(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("¿Qué puedes hacer?")
        assert result["intent_type"] == "ASK_CAPABILITIES"

    def test_price_check(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("¿Cuánto cuesta Elden Ring?")
        assert result["intent_type"] == "CHECK_PRICE"
        assert "Elden Ring" in (result.get("game_name") or "")

    def test_compare_games(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("Compara Valheim con Minecraft")
        assert result["intent_type"] == "COMPARE_GAMES"

    def test_horror_tags(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("Quiero juegos de terror")
        assert result["intent_type"] == "SEARCH_GAME"
        assert "Horror" in result["tags"]

    def test_rpg_tags(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("Un RPG de fantasía")
        assert "RPG" in result["tags"]

    def test_free_games(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("Juegos gratis")
        assert result["intent_type"] == "SEARCH_GAME"
        assert result["max_price_usd"] == 0

    def test_only_sale(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("Juegos en oferta con descuento")
        assert result["only_on_sale"] is True

    def test_no_match_defaults(self):
        from core.llm_engine import fallback_intent
        result = fallback_intent("xyzzz blargh")
        assert result["intent_type"] == "SEARCH_GAME"
        assert result["tags"] == []


# ============================================================================
# 2. ConversationMemory summarization
# ============================================================================

class TestConversationMemory:
    """Verify memory summarization behavior."""

    def test_add_and_retrieve(self):
        from core.llm_engine import ConversationMemory
        mem = ConversationMemory(max_turns=5)
        mem.add_user("Hola")
        mem.add_assistant("¡Hola! ¿Qué juegos buscas?")
        assert len(mem._history) == 2
        assert mem._history[0]["role"] == "user"

    def test_summary_generation(self):
        from core.llm_engine import ConversationMemory
        mem = ConversationMemory(max_turns=3)
        # Fill beyond max_turns
        for i in range(8):
            mem.add_user(f"Busco juegos {i}")
            mem.add_assistant(f"Aquí tienes recomendación {i}")
        # Summary should have been populated
        assert len(mem._summary) > 0
        # History should be trimmed
        assert len(mem._history) <= 6  # 3 turns * 2

    def test_get_history_messages(self):
        from core.llm_engine import ConversationMemory
        mem = ConversationMemory()
        mem.add_user("Quiero juegos de terror")
        mem.add_assistant("Te recomiendo Amnesia")
        messages = mem.get_history_messages()
        assert messages == [
            {"role": "user", "content": "Quiero juegos de terror"},
            {"role": "assistant", "content": "Te recomiendo Amnesia"},
        ]

    def test_get_summary(self):
        from core.llm_engine import ConversationMemory
        mem = ConversationMemory(max_turns=2)
        for i in range(10):
            mem.add_user(f"msg {i}")
            mem.add_assistant(f"resp {i}")
        summary = mem.get_summary()
        assert len(summary) > 0

    def test_clear(self):
        from core.llm_engine import ConversationMemory
        mem = ConversationMemory()
        mem.add_user("test")
        mem.clear()
        assert len(mem._history) == 0
        assert mem._summary == ""


# ============================================================================
# 3. Price formatting (currency.py without network)
# ============================================================================

class TestCurrencyFormatting:
    """Verify price formatting — fallback rates only, no API call."""

    def test_usd_same(self):
        from core.currency import convert_usd
        result = convert_usd(14.99, "USD")
        assert "$14.99" in result

    def test_clp_format(self):
        from core.currency import convert_usd
        result = convert_usd(10.00, "CLP")
        assert "CLP$" in result
        # No decimals for CLP
        assert "." not in result.split("CLP$")[1].strip().replace(",", "")

    def test_ars_format(self):
        from core.currency import convert_usd
        result = convert_usd(15.00, "ARS")
        assert "ARS$" in result

    def test_eur_format(self):
        from core.currency import convert_usd
        result = convert_usd(20.00, "EUR")
        assert "€" in result

    def test_unknown_currency(self):
        from core.currency import convert_usd
        result = convert_usd(10.00, "XYZ")
        # Should default to rate 1.0
        assert "XYZ" in result
        assert "10.00" in result

    def test_format_with_regional_price(self):
        from core.currency import format_price_for_session
        game = {"name": "Test", "regional_price": "CLP$ 9.600"}
        result = format_price_for_session(game, "CLP")
        assert "CLP$ 9.600" in result

    def test_format_with_discount(self):
        from core.currency import format_price_for_session
        game = {"name": "Test", "price_usd": 20.0, "discount": 50}
        result = format_price_for_session(game, "CLP")
        assert "🔥" in result
        assert "(-50%)" in result

    def test_format_free(self):
        from core.currency import format_price_for_session
        game = {"name": "Test", "price_usd": 0.0}
        result = format_price_for_session(game, "CLP")
        assert result == "Gratis"


# ============================================================================
# 4. Tag normalization
# ============================================================================

class TestTagNormalization:
    """Verify tag_registry.normalize_tags()."""

    def test_known_tags_passthrough(self):
        from models.tag_registry import normalize_tags
        result = normalize_tags(["Action", "RPG"])
        assert "Action" in result
        assert "RPG" in result

    def test_case_insensitive(self):
        from models.tag_registry import normalize_tags
        result = normalize_tags(["action", "rpg"])
        assert "Action" in result
        assert "RPG" in result

    def test_unknown_tags_dropped(self):
        from models.tag_registry import normalize_tags
        result = normalize_tags(["FakeTagXYZ", "Action"])
        assert "Action" in result
        assert "FakeTagXYZ" not in result

    def test_empty(self):
        from models.tag_registry import normalize_tags
        result = normalize_tags([])
        assert result == []

    def test_none_input(self):
        from models.tag_registry import normalize_tags
        result = normalize_tags(None)
        assert result == []


# ============================================================================
# 5. No-results message builder
# ============================================================================

class TestNoResultsMessage:
    """Verify _build_no_results_msg gives good suggestions."""

    def test_with_tags(self):
        from core.pipeline import _build_no_results_msg
        msg = _build_no_results_msg(["Horror"], None, None)
        assert "Horror" in msg
        assert "Sugerencias" in msg

    def test_with_price_constraint(self):
        from core.pipeline import _build_no_results_msg
        msg = _build_no_results_msg([], None, 5.0)
        assert "subir el precio" in msg.lower()

    def test_with_sale_constraint(self):
        from core.pipeline import _build_no_results_msg
        msg = _build_no_results_msg([], None, None, only_sale=True)
        assert "solo ofertas" in msg.lower()

    def test_with_min_score(self):
        from core.pipeline import _build_no_results_msg
        msg = _build_no_results_msg([], None, None, min_score=85)
        assert "puntuación" in msg.lower()


# ============================================================================
# 6. Session management
# ============================================================================

class TestSession:
    """Verify Session dataclass and registry."""

    def test_default_region(self):
        from core.session import Session
        from core.llm_engine import ConversationMemory
        s = Session(memory=ConversationMemory())
        assert s.region == "CL"
        assert s.currency == "CLP"

    def test_chile_region(self):
        from core.session import Session
        from core.llm_engine import ConversationMemory
        s = Session(memory=ConversationMemory(), region="CL")
        assert s.currency == "CLP"
        assert s.currency_symbol == "CLP$"

    def test_add_to_wishlist(self):
        from core.session import Session
        from core.llm_engine import ConversationMemory
        s = Session(memory=ConversationMemory())
        game = {"appid": 730, "name": "CS2", "price_usd": 0}
        s.add_to_wishlist(game)
        assert "730" in s.recommended_appids
        assert len(s.wishlist) == 1

    def test_no_duplicate_wishlist(self):
        from core.session import Session
        from core.llm_engine import ConversationMemory
        s = Session(memory=ConversationMemory())
        game = {"appid": 730, "name": "CS2"}
        s.add_to_wishlist(game)
        s.add_to_wishlist(game)
        assert len(s.wishlist) == 1

    def test_new_games_only(self):
        from core.session import Session
        from core.llm_engine import ConversationMemory
        s = Session(memory=ConversationMemory())
        s.recommended_appids.add("730")
        games = [
            {"appid": 730, "name": "CS2"},
            {"appid": 440, "name": "TF2"},
        ]
        new = s.new_games_only(games)
        assert len(new) == 1
        assert new[0]["appid"] == 440

    def test_export_text(self):
        from core.session import Session
        from core.llm_engine import ConversationMemory
        s = Session(memory=ConversationMemory(), region="CL")
        s.add_to_wishlist({"appid": 730, "name": "CS2", "price_usd": 0})
        text = s.export_text()
        assert "CS2" in text
        assert "CL" in text

    def test_registry_get_creates(self):
        from core.session import registry
        session = registry.get(999)
        assert session.chat_id == 999

    def test_registry_set_region(self):
        from core.session import registry
        registry.set_region(1000, "CL")
        session = registry.get(1000)
        assert session.region == "CL"

    def test_registry_clear(self):
        from core.session import registry
        registry.get(1001)
        registry.clear(1001)
        # Should create a new session
        session2 = registry.get(1001)
        assert session2.region == "CL"


# ============================================================================
# Run with: pytest tests/test_beta.py -v
# ============================================================================
