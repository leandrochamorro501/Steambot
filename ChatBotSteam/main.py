"""
main.py
-------
Entry point for the Steam Recommender Chatbot (terminal interface).
Uses the UNIFIED core.pipeline.run_pipeline() — same as Telegram.

Pipeline per turn:
  1. Read user message
  2. Delegate to core.pipeline.run_pipeline() (DeepSeek + fallback + SteamSpy)
  3. Print result
"""

import sys
import asyncio
import os
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule
from rich.table import Table
from rich import print as rprint

# Core imports
from core.pipeline import run_pipeline
from core.session import Session, registry
from core.steam_api import REGIONS, region_from_language
from core import llm_engine

console = Console()

BANNER = """
  ____  _                       ____        _
 / ___|| |_ ___  __ _ _ __ ___ | __ )  ___ | |_
 \\___ \\| __/ _ \\/ _` | '_ ` _ \\|  _ \\ / _ \\| __|
  ___) | ||  __/ (_| | | | | | | |_) | (_) | |_
 |____/ \\__\\___|\\__,_|_| |_| |_|____/ \\___/ \\__|

  Tu asistente de recomendaciones de Steam
"""

HELP_TEXT = (
    "[bold cyan]Comandos especiales:[/bold cyan]\n"
    "  [yellow]salir[/yellow] / [yellow]exit[/yellow]       — Cierra el chatbot\n"
    "  [yellow]ayuda[/yellow] / [yellow]help[/yellow]       — Muestra este mensaje\n"
    "  [yellow]historial[/yellow] / [yellow]lista[/yellow]   — Ver juegos recomendados en esta sesion\n"
    "  [yellow]exportar[/yellow] / [yellow]export[/yellow]  — Exportar historial a archivo\n"
    "  [yellow]region[/yellow]             — Cambiar region de precios\n\n"
    "[bold cyan]Ejemplos de busqueda:[/bold cyan]\n"
    '  "Quiero juegos de terror psicologico ambientados en el espacio"\n'
    '  "Algo tipo Dark Souls pero con estetica anime"\n'
    '  "Juegos de estrategia baratos que esten en oferta"\n'
    '  "Co-op para jugar con amigos, menos de $15"\n'
    '  "Mejor que sea mas barato" (refina la busqueda anterior)\n'
)


def print_banner() -> None:
    console.print(f"[bold green]{BANNER}[/bold green]")
    console.print(Rule(style="green"))
    console.print()


def select_region() -> str:
    console.print("\n[bold cyan]Selecciona tu region para precios localizados:[/bold cyan]\n")

    regions = REGIONS
    table = Table(show_header=True, header_style="bold magenta", box=None)
    table.add_column("#", style="yellow", width=4)
    table.add_column("Codigo", style="cyan", width=8)
    table.add_column("Region", style="white")

    region_list = list(regions.items())
    for idx, (code, info) in enumerate(region_list, 1):
        table.add_row(str(idx), code, info["label"])

    console.print(table)
    console.print()

    while True:
        try:
            choice = console.input("[bold cyan]Elige un numero (o codigo):[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            return "US"

        try:
            num = int(choice)
            if 1 <= num <= len(region_list):
                code = region_list[num - 1][0]
                console.print(f"\n[green]✓ Region configurada:[/green] {regions[code]['label']}\n")
                return code
        except ValueError:
            pass

        code_upper = choice.upper()
        if code_upper in regions:
            console.print(f"\n[green]✓ Region configurada:[/green] {regions[code_upper]['label']}\n")
            return code_upper

        console.print("[red]Opcion no valida. Intenta de nuevo.[/red]")


def print_intent(intent: dict) -> None:
    lines = []
    if intent.get("intent_type"):
        lines.append(f"Tipo:         {intent['intent_type']}")
    if intent.get("_reasoning"):
        lines.append(f"Razonamiento: {intent['_reasoning']}\n")
    if intent.get("tags"):
        lines.append(f"Tags:         {', '.join(intent['tags'])}")
    if intent.get("genre"):
        lines.append(f"Genero:       {intent['genre']}")
    if intent.get("max_price_usd") is not None:
        lines.append(f"Precio max:   ${intent['max_price_usd']} USD")
    if intent.get("only_on_sale"):
        lines.append("Solo oferta:  Si")
    if intent.get("min_score_rank") is not None:
        lines.append(f"Score minimo: {intent['min_score_rank']}%")
    if intent.get("game_name"):
        lines.append(f"Juego ref:    {intent['game_name']}")

    if lines:
        console.print(
            Panel(
                "\n".join(lines),
                title="[dim]Intencion detectada[/dim]",
                border_style="dim",
                expand=False,
            )
        )


def show_historial(session: Session) -> None:
    if not session.historial:
        console.print("[yellow]Tu historial esta vacio. Pide una recomendacion primero![/yellow]")
        return

    table = Table(
        title="[bold magenta]🎮 Historial de esta sesion[/bold magenta]",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("#", style="yellow", width=4)
    table.add_column("Juego", style="white", min_width=25)
    table.add_column("Precio", style="green", min_width=12)
    table.add_column("Developer", style="dim", min_width=15)

    for idx, g in enumerate(session.historial, 1):
        price = g.get("regional_price", f"${g.get('price_usd', '?')} USD")
        table.add_row(str(idx), g["name"], price, g.get("developer", ""))

    console.print()
    console.print(table)
    console.print(f"\n[dim]Total: {len(session.historial)} juegos guardados[/dim]\n")


def export_historial(session: Session) -> None:
    if not session.historial:
        console.print("[yellow]Nada que exportar. El historial esta vacio.[/yellow]")
        return

    content = session.export_text()
    filename = f"steambot_historial_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)

    console.print(f"[green]✓ Historial exportado a:[/green] [bold]{filename}[/bold]")


async def handle_message(user_message: str, session: Session) -> None:
    """Process a user message through the unified pipeline."""
    with console.status("[bold yellow]Procesando tu consulta...[/bold yellow]"):
        result = await run_pipeline(user_message, session)

    print_intent(result.intent)

    if result.status in ("ok", "chat"):
        console.print()
        console.print(
            Panel(
                result.response_text,
                title="[bold green]SteamBot[/bold green]" if result.status == "ok" else "[bold blue]SteamBot[/bold blue]",
                border_style="green" if result.status == "ok" else "blue",
                padding=(1, 2),
            )
        )
        console.print()
        if result.games_found:
            console.print("[dim]Tip: Escribe 'historial' para ver todos los juegos recomendados.[/dim]")
    elif result.status == "no_results":
        console.print(f"\n[yellow]{result.response_text}[/yellow]\n")
    elif result.status == "unavailable":
        console.print(f"\n[bold red]{result.response_text}[/bold red]\n")
    else:
        console.print(f"\n[red]{result.response_text}[/red]\n")


async def main_async() -> None:
    session = Session(
        memory=llm_engine.memory,
        region="CL",
        user_id=0,
        chat_id=0,
    )

    print_banner()
    console.print("[bold]¡Bienvenido a SteamBot![/bold] (Beta)\n")

    session.region = select_region()
    console.print("Escribe [yellow]ayuda[/yellow] para ver ejemplos y comandos.\n")

    while True:
        try:
            user_input = console.input("[bold cyan]Tú:[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Hasta luego![/dim]")
            sys.exit(0)

        if not user_input:
            continue

        low = user_input.lower()

        if low in ("salir", "exit", "quit", "q"):
            if session.historial:
                console.print(
                    f"[dim]Tienes {len(session.historial)} juegos en tu historial. "
                    "Escribe 'exportar' antes de salir si quieres guardarla.[/dim]"
                )
                try:
                    confirm = console.input("[dim]¿Salir de todos modos? (s/n):[/dim] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    confirm = "s"
                if confirm not in ("s", "si", "y", "yes"):
                    continue
            console.print("[dim]Hasta luego! A jugar![/dim]")
            break

        if low in ("ayuda", "help", "h", "?"):
            console.print(Panel(HELP_TEXT, title="Ayuda", border_style="cyan"))
            continue

        if low in ("historial", "wishlist", "lista", "mis juegos"):
            show_historial(session)
            continue

        if low in ("exportar", "export", "guardar"):
            export_historial(session)
            continue

        if low == "region":
            session.region = select_region()
            continue

        try:
            await handle_message(user_input, session)
        except Exception as e:
            console.print(f"[red]Error inesperado:[/red] {e}")
            console.print("[dim]Si el error persiste, revisa tu conexion o credenciales de DeepSeek.[/dim]")


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass  # Salida limpia al usar Ctrl+C


if __name__ == "__main__":
    main()
