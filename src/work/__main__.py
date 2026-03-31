"""CLI entry point for the work productivity agent.

Usage:
    python -m work                  # interactive mode: monitor + chat
    python -m work monitor          # foreground monitor with Rich display
    python -m work monitor --daemon # headless background monitor
    python -m work goals            # list all goals
    python -m work goals add        # add a new goal interactively
    python -m work actions          # show actions across scopes
    python -m work memory           # show memory across scopes
    python -m work standup          # morning briefing
    python -m work status           # monitor status and signal counts
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from work.config import WORK_HOME

console = Console()

# ---------------------------------------------------------------------------
# Initialization helpers
# ---------------------------------------------------------------------------


def _init_components():
    """Create the shared ScopeManager, GeminiClient, and SignalCollector."""
    from work.context import ScopeManager
    from work.llm import GeminiClient
    from work.signals import SignalCollector

    scope_manager = ScopeManager(WORK_HOME)
    gemini = GeminiClient()
    collector = SignalCollector()
    return scope_manager, gemini, collector


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


async def cmd_interactive(args: argparse.Namespace) -> None:
    """Default command: monitor in background + interactive chat."""
    scope_manager, gemini, collector = _init_components()

    from work.agent.engine import AgentEngine
    from work.monitor.loop import MonitorLoop

    monitor = MonitorLoop(scope_manager, gemini, collector)
    agent = AgentEngine(scope_manager, gemini)

    # Start monitor as a background task
    monitor_task = asyncio.create_task(monitor.run(interactive=False))

    console.print(
        Panel(
            "[bold]work[/bold] -- productivity agent\n"
            "[dim]Monitor running in background. Type a message or 'quit' to exit.[/dim]",
            border_style="bright_blue",
        )
    )

    try:
        while True:
            try:
                user_input = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: Prompt.ask("[bold cyan]you[/bold cyan]"),
                )
            except (EOFError, KeyboardInterrupt):
                break

            if not user_input:
                continue
            if user_input.strip().lower() in ("quit", "exit", "q"):
                break

            with console.status("[dim]thinking...[/dim]"):
                response = await agent.chat(user_input)

            console.print()
            console.print(Markdown(response))
            console.print()
    finally:
        monitor.stop()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        console.print("[dim]Goodbye.[/dim]")


async def cmd_monitor(args: argparse.Namespace) -> None:
    """Run the monitor loop (foreground or daemon)."""
    scope_manager, gemini, collector = _init_components()
    from work.monitor.loop import MonitorLoop

    monitor = MonitorLoop(scope_manager, gemini, collector)
    interactive = not args.daemon

    if args.daemon:
        console.print("[dim]Starting headless monitor...[/dim]")
    else:
        console.print(
            Panel(
                "[bold]work monitor[/bold]\n[dim]Ctrl+C to stop[/dim]",
                border_style="bright_blue",
            )
        )

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, monitor.stop)
    loop.add_signal_handler(signal.SIGTERM, monitor.stop)

    await monitor.run(interactive=interactive)


def cmd_goals(args: argparse.Namespace) -> None:
    """List or add goals."""
    from work.context import ScopeManager

    scope_manager = ScopeManager(WORK_HOME)

    if args.goals_action == "add":
        _add_goal(scope_manager)
        return

    # List all goals
    scopes = scope_manager.list_scopes()
    if not scopes:
        console.print("[dim]No scopes configured. Run 'work goals add' to create one.[/dim]")
        return

    for scope_type, name in scopes:
        store = scope_manager.get_store(scope_type, name)
        label = name or scope_type
        goals = store.read_goals().strip()
        if goals:
            console.print(Panel(Markdown(goals), title=f"[bold]{label}[/bold]", border_style="cyan"))
        else:
            console.print(f"[dim]{label}: no goals[/dim]")


def _add_goal(scope_manager) -> None:
    """Interactive goal creation."""
    scopes = scope_manager.list_scopes()
    if not scopes:
        console.print("[yellow]No scopes exist yet. Creating 'personal' scope.[/yellow]")
        scope_manager.create_scope("personal")
        scopes = [("personal", None)]

    # Choose scope
    console.print("[bold]Available scopes:[/bold]")
    for i, (st, n) in enumerate(scopes):
        label = n or st
        console.print(f"  {i + 1}. {label}")

    choice = Prompt.ask("Scope number", default="1")
    try:
        idx = int(choice) - 1
        scope_type, name = scopes[idx]
    except (ValueError, IndexError):
        console.print("[red]Invalid choice[/red]")
        return

    goal_name = Prompt.ask("Goal name")
    description = Prompt.ask("Description")
    people_raw = Prompt.ask("Key people (comma-separated)", default="")
    people = [p.strip() for p in people_raw.split(",") if p.strip()] or None

    store = scope_manager.get_store(scope_type, name)
    action = store.set_goal(goal_name, description, people)
    console.print(f"[green]{action} goal '{goal_name}'[/green]")


def cmd_actions(args: argparse.Namespace) -> None:
    """Show actions across scopes."""
    from work.context import ScopeManager

    scope_manager = ScopeManager(WORK_HOME)

    for scope_type, name in scope_manager.list_scopes():
        store = scope_manager.get_store(scope_type, name)
        label = name or scope_type
        actions = store.read_actions().strip()
        if actions:
            console.print(Panel(Markdown(actions), title=f"[bold]{label}[/bold]", border_style="magenta"))
        else:
            console.print(f"[dim]{label}: no actions[/dim]")


def cmd_memory(args: argparse.Namespace) -> None:
    """Show memory across scopes."""
    from work.context import ScopeManager

    scope_manager = ScopeManager(WORK_HOME)

    for scope_type, name in scope_manager.list_scopes():
        store = scope_manager.get_store(scope_type, name)
        label = name or scope_type
        memory = store.read_memory().strip()
        if memory:
            console.print(Panel(Markdown(memory), title=f"[bold]{label}[/bold]", border_style="green"))
        else:
            console.print(f"[dim]{label}: no memory[/dim]")


async def cmd_standup(args: argparse.Namespace) -> None:
    """Morning briefing: scan signals, compare to goals, surface gaps."""
    scope_manager, gemini, _ = _init_components()

    from work.agent.engine import AgentEngine

    agent = AgentEngine(scope_manager, gemini)

    with console.status("[dim]Preparing standup briefing...[/dim]"):
        response = await agent.chat(
            "Give me a morning standup briefing. For each scope and goal: "
            "what happened recently, what's the current status, what needs attention today, "
            "and are there any commitment-action gaps (things someone said they'd do but haven't)?"
        )

    console.print(Panel(Markdown(response), title="[bold]Morning Standup[/bold]", border_style="bright_yellow"))


def cmd_status(args: argparse.Namespace) -> None:
    """Show monitor status."""
    from work.context import ScopeManager

    scope_manager = ScopeManager(WORK_HOME)
    scopes = scope_manager.list_scopes()

    console.print(Panel("[bold]work status[/bold]", border_style="bright_blue"))
    console.print(f"  Work home: {WORK_HOME}")
    console.print(f"  Scopes: {len(scopes)}")

    for scope_type, name in scopes:
        store = scope_manager.get_store(scope_type, name)
        label = name or scope_type
        hot = store.read_hot_buffer()
        hot_lines = len([l for l in hot.strip().split("\n") if l.strip()]) if hot.strip() else 0
        goals = store.read_goals()
        goal_count = goals.count("## ") - (1 if goals.startswith("# ") else 0)
        console.print(f"\n  [bold]{label}[/bold]")
        console.print(f"    Goals: {max(goal_count, 0)}")
        console.print(f"    Hot buffer entries: {hot_lines}")
        console.print(f"    Memory size: {len(store.read_memory())} chars")
        console.print(f"    Actions size: {len(store.read_actions())} chars")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="work",
        description="Productivity agent powered by Gemini",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    sub = parser.add_subparsers(dest="command")

    # work monitor
    p_monitor = sub.add_parser("monitor", help="Start the monitoring loop")
    p_monitor.add_argument("--daemon", action="store_true", help="Run headless in background")

    # work goals [add]
    p_goals = sub.add_parser("goals", help="List or manage goals")
    p_goals.add_argument("goals_action", nargs="?", default=None, choices=["add"], help="'add' to create a new goal")

    # work actions
    sub.add_parser("actions", help="Show current actions across scopes")

    # work memory
    sub.add_parser("memory", help="Show memory across scopes")

    # work standup
    sub.add_parser("standup", help="Morning standup briefing")

    # work status
    sub.add_parser("status", help="Show monitor status and signal counts")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # Ensure work home exists
    WORK_HOME.mkdir(parents=True, exist_ok=True)

    match args.command:
        case None:
            asyncio.run(cmd_interactive(args))
        case "monitor":
            asyncio.run(cmd_monitor(args))
        case "goals":
            cmd_goals(args)
        case "actions":
            cmd_actions(args)
        case "memory":
            cmd_memory(args)
        case "standup":
            asyncio.run(cmd_standup(args))
        case "status":
            cmd_status(args)
        case _:
            parser.print_help()


if __name__ == "__main__":
    main()
