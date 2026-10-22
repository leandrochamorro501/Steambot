"""
telegram_bot.py
---------------
Telegram interface for SteamBot.

Features:
  - Auto-detects user region from Telegram language_code on /start
  - Per-user session state (memory, historial, region)
  - All business logic delegated to core.pipeline (UNIFIED)
  - Commands: /start, /help, /region, /historial, /export, /reset
"""

import asyncio
import os
import sys
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from core.pipeline import run_pipeline
from core.session import registry
from core.steam_api import REGIONS, region_from_language

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")


# == Command handlers ==========================================================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    user = update.message.from_user
    user_id = user.id if user else chat_id

    # Forzamos región por defecto a Chile (CL), el usuario puede cambiarla libremente con /region si lo desea
    registry.set_region(chat_id, "CL")
    session = registry.get(chat_id, user_id)
    session.user_id = user_id

    region_info = REGIONS["CL"]

    welcome = (
        f"🤖 *¡Bienvenido a SteamBot, {user.first_name if user else 'Gamer'}!*\n\n"
        f"Soy tu asistente de recomendaciones de Steam impulsado por IA.\n\n"
        f"🌎 Tu región inicial: *{region_info['label']}*\n"
        f"Los precios se mostrarán en *{region_info['currency']}*.\n\n"
        f"Usa /region para cambiarla o simplemente dime qué juegos te gustan. 🎮\n\n"
        f"Escribe /help para ver todos los comandos."
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "🎮 *Comandos disponibles:*\n"
        "/start — Inicia el bot y detecta tu región\n"
        "/help — Muestra este mensaje\n"
        "/region — Cambia tu región de precios\n"
        "/historial — Muestra los juegos recomendados en esta sesión\n"
        "/export — Descarga tu historial como archivo\n"
        "/reset — Reinicia la conversación\n\n"
        "*Ejemplos de búsqueda:*\n"
        "— _Quiero juegos de terror psicológico en el espacio_\n"
        "— _Algo tipo Dark Souls pero con estética anime_\n"
        "— _Juegos de supervivencia co-op, menos de $20_\n"
        "— _Mejor que sea más barato_ _(refina la búsqueda anterior)_"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def region_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    buttons = []
    row = []
    for code, info in REGIONS.items():
        row.append(InlineKeyboardButton(f"{code} — {info['currency']}", callback_data=f"region:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(
        "🌎 *Selecciona tu región:*",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def region_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    code = query.data.split(":", 1)[1]
    chat_id = query.message.chat_id

    if code not in REGIONS:
        await query.edit_message_text("❌ Región no válida.")
        return

    registry.set_region(chat_id, code)
    info = REGIONS[code]
    await query.edit_message_text(
        f"✅ Región configurada: *{info['label']}*\n"
        f"Los precios aparecerán en *{info['currency']}*.",
        parse_mode="Markdown",
    )


async def historial_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    session = registry.get(chat_id)

    if not session.historial:
        await update.message.reply_text("Tu historial está vacío. ¡Pídeme una recomendación primero! 🎮")
        return

    currency = session.currency
    lines = [f"📝 *Tu Historial ({currency}):*\n"]
    for idx, g in enumerate(session.historial, 1):
        price = g.get("regional_price", f"${g.get('price_usd', '?')} USD")
        lines.append(f"{idx}. *{g['name']}* — {price}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    session = registry.get(chat_id)

    if not session.historial:
        await update.message.reply_text("Nada que exportar. El historial está vacío.")
        return

    content = session.export_text()
    filename = f"historial_{chat_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    with open(filename, "rb") as f:
        await update.message.reply_document(document=f, filename=filename)

    os.remove(filename)


async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    registry.clear(chat_id)
    await update.message.reply_text(
        "🔄 Sesión reiniciada. ¡Empecemos de nuevo! Dime qué tipo de juego estás buscando."
    )


# == Message handler ===========================================================


_FALLBACK_MSG = "🎮 No pude procesar tu consulta. Intenta de nuevo o escribe /help para ver los comandos."


def _safe_text(text: str) -> str:
    """Ensure text is never empty — Telegram rejects empty messages."""
    if text and text.strip():
        return text
    return _FALLBACK_MSG


_TELEGRAM_MAX_LEN = 4096  # Telegram's hard limit per message
_CHUNK_DELAY = 0.3  # seconds between chunk sends to avoid rate limits


def _sanitize_markdown(text: str) -> str:
    """Fix unbalanced Markdown formatting that Telegram would reject.

    Telegram's legacy Markdown mode requires matched pairs of *, _, `, [].
    When splitting long messages, formatting tokens can become unbalanced.
    This function ensures every chunk is valid Markdown on its own.
    """
    # Count unescaped formatting characters
    # We only care about *, _, ` as they are the most common in our bot output

    def _count_unescaped(s: str, char: str) -> int:
        count = 0
        i = 0
        while i < len(s):
            if s[i] == '\\' and i + 1 < len(s):
                i += 2  # skip escaped char
                continue
            if s[i] == char:
                count += 1
            i += 1
        return count

    result = text

    # Fix unbalanced bold markers (**) — count pairs
    # For **, we count occurrences of the double-char pattern
    double_star_count = result.count('**')
    if double_star_count % 2 != 0:
        # Find the last ** and remove it (or add a closing one)
        last_pos = result.rfind('**')
        if last_pos >= 0:
            result = result[:last_pos] + result[last_pos + 2:]

    # Fix unbalanced single * (italic in Telegram Markdown)
    # After handling **, replace ** temporarily to count single *
    temp = result.replace('**', '\x00\x00')
    single_star = temp.count('*')
    if single_star % 2 != 0:
        # Remove the last unmatched single *
        # Work on the original string, find the last single * (not part of **)
        pos = len(result) - 1
        while pos >= 0:
            if result[pos] == '*':
                # Check it's not part of **
                before = result[pos - 1] if pos > 0 else ''
                after = result[pos + 1] if pos + 1 < len(result) else ''
                if before != '*' and after != '*':
                    result = result[:pos] + result[pos + 1:]
                    break
            pos -= 1

    # Fix unbalanced _ (italic)
    underscore_count = _count_unescaped(result, '_')
    if underscore_count % 2 != 0:
        # Remove the last unmatched _
        last_pos = result.rfind('_')
        if last_pos >= 0:
            result = result[:last_pos] + result[last_pos + 1:]

    # Fix unbalanced ` (code)
    backtick_count = _count_unescaped(result, '`')
    if backtick_count % 2 != 0:
        result += '`'

    # Fix unbalanced [] (links) — just count [ vs ]
    open_brackets = _count_unescaped(result, '[')
    close_brackets = _count_unescaped(result, ']')
    if open_brackets > close_brackets:
        result += ']' * (open_brackets - close_brackets)

    return result


def _split_message(text: str, max_len: int = _TELEGRAM_MAX_LEN) -> list[str]:
    """Split a long message into chunks that fit within Telegram's limit.

    Tries to split at paragraph boundaries (\\n\\n), then at line boundaries (\\n),
    then at word boundaries as a last resort.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Try to find a good split point
        split_at = max_len

        # 1. Try splitting at paragraph boundary
        para_break = remaining.rfind("\n\n", 0, max_len)
        if para_break > max_len // 3:  # Don't split too early
            split_at = para_break + 2  # Include the \n\n in the first chunk
        else:
            # 2. Try splitting at line boundary
            line_break = remaining.rfind("\n", 0, max_len)
            if line_break > max_len // 3:
                split_at = line_break + 1
            else:
                # 3. Try splitting at word boundary
                space = remaining.rfind(" ", 0, max_len)
                if space > max_len // 3:
                    split_at = space + 1
                # else: hard split at max_len

        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]

    return chunks


def _strip_markdown(text: str) -> str:
    """Remove all Markdown formatting as a last-resort fallback."""
    result = text
    result = result.replace('**', '')
    result = result.replace('__', '')
    result = result.replace('`', '')
    result = result.replace('*', '')
    result = result.replace('_', '')
    return result


async def _send_response(
    status_msg,
    update: Update,
    response: str,
    parse_mode: str | None = "Markdown",
) -> None:
    """Send a response, splitting into multiple messages if needed for Telegram's 4096 char limit.

    Triple fallback per chunk:
      1. Send with Markdown (after sanitizing unbalanced markers)
      2. Send as plain text (no parse_mode)
      3. Send with all Markdown stripped (nuclear option)
    """
    chunks = _split_message(response)
    total = len(chunks)

    print(f"[telegram_debug] Sending {total} chunk(s), total response length: {len(response)} chars")

    # Intenta borrar el mensaje de estado inicial para mantener el chat limpio
    try:
        await status_msg.delete()
    except Exception as e:
        print(f"[telegram_debug] Failed to delete status_msg: {e}")
        try:
            await status_msg.edit_text("✨ ¡Aquí tienes!")
        except Exception:
            pass

    for i, chunk in enumerate(chunks):
        chunk_text = chunk.strip()
        if not chunk_text:
            print(f"[telegram_debug] Skipping empty chunk {i+1}/{total}")
            continue

        sent = False

        # === Attempt 1: Markdown with sanitized formatting ===
        if parse_mode == "Markdown":
            try:
                sanitized = _sanitize_markdown(chunk_text)
                await update.message.reply_text(sanitized, parse_mode="Markdown")
                sent = True
                print(f"[telegram_debug] ✅ Chunk {i+1}/{total} sent (Markdown, {len(sanitized)} chars)")
            except Exception as e1:
                print(f"[telegram_debug] ⚠️ Chunk {i+1}/{total} Markdown failed: {type(e1).__name__}: {e1}")

        # === Attempt 2: Plain text (no formatting) ===
        if not sent:
            try:
                await update.message.reply_text(chunk_text)
                sent = True
                print(f"[telegram_debug] ✅ Chunk {i+1}/{total} sent (plain text, {len(chunk_text)} chars)")
            except Exception as e2:
                print(f"[telegram_debug] ⚠️ Chunk {i+1}/{total} plain text failed: {type(e2).__name__}: {e2}")

        # === Attempt 3: Strip all Markdown and send plain ===
        if not sent:
            try:
                stripped = _strip_markdown(chunk_text)
                if not stripped.strip():
                    stripped = "(contenido no disponible)"
                await update.message.reply_text(stripped)
                sent = True
                print(f"[telegram_debug] ✅ Chunk {i+1}/{total} sent (stripped, {len(stripped)} chars)")
            except Exception as e3:
                print(f"[telegram_debug] ❌ Chunk {i+1}/{total} ALL ATTEMPTS FAILED: {type(e3).__name__}: {e3}")

        # Delay between chunks to avoid Telegram rate limiting
        if i < total - 1 and sent:
            await asyncio.sleep(_CHUNK_DELAY)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    user = update.message.from_user
    user_id = user.id if user else chat_id
    user_message = update.message.text or ""
    session = registry.get(chat_id, user_id)
    session.user_id = user_id

    status_msg = await update.message.reply_text("⏳ Analizando tu consulta...")

    try:
        result = await asyncio.wait_for(
            run_pipeline(user_message, session),
            timeout=60.0,
        )

        if result.status in ("ok",):
            await status_msg.edit_text("⏳ Redactando recomendación...")
        elif result.status == "unavailable":
            await status_msg.edit_text("⚠️ Verificando SteamSpy...")

        response = _safe_text(result.response_text)

        # Log response length for debugging
        print(f"[telegram_debug] response_length={len(response)} chars, chunks_needed={len(_split_message(response))}")

        await _send_response(status_msg, update, response)

        if result.status == "ok" and result.games_found:
            currency = session.currency
            await update.message.reply_text(
                f"💡 Tip: usa /historial para ver tus juegos guardados (precios en {currency})."
            )

    except asyncio.TimeoutError:
        await status_msg.edit_text(
            "⏰ La consulta tardó demasiado. "
            "SteamSpy puede estar lento o caído. Intenta de nuevo más tarde."
        )
    except Exception as exc:
        print(f"[telegram_debug] handle_message exception: {type(exc).__name__}: {exc}")
        error_msg = f"❌ Error inesperado: {exc}" if str(exc).strip() else "❌ Ocurrió un error inesperado. Intenta de nuevo."
        try:
            await status_msg.edit_text(error_msg)
        except Exception:
            await status_msg.edit_text("❌ Ocurrió un error inesperado. Intenta de nuevo.")


# == Entry point ===============================================================

def main() -> None:
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN no está configurado en .env")
        sys.exit(1)

    print(f"🤖 SteamBot Beta iniciando... (modelo: {os.getenv('DEEPSEEK_MODEL_ID', 'deepseek-chat')})")

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("region", region_cmd))
    app.add_handler(CommandHandler("historial", historial_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CallbackQueryHandler(region_callback, pattern="^region:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot en ejecución (presiona Ctrl+C para detener)")
    try:
        app.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Bot detenido de forma segura. ¡Hasta luego! 🎮")


if __name__ == "__main__":
    main()
