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
    python -m work log              # view signal log (last 50)
    python -m work log --today      # today's signals only
    python -m work log --source email  # filter by source
    python -m work log --search "term" # text search
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
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

    await monitor.run(interactive=interactive)


def _filter_scopes(scope_manager, scope_filter: str | None) -> list[tuple[str, str | None]]:
    """Filter scopes by name if --scope is given."""
    scopes = scope_manager.list_scopes()
    if scope_filter:
        scopes = [(st, n) for st, n in scopes if (n or st) == scope_filter]
    return scopes


def cmd_scope(args: argparse.Namespace) -> None:
    """List or create scopes."""
    from work.context import ScopeManager

    scope_manager = ScopeManager(WORK_HOME)

    if args.scope_action == "add":
        _add_scope(scope_manager)
        return

    scopes = scope_manager.list_scopes()
    if not scopes:
        console.print("[dim]No scopes configured. Run 'work scope add' to create one.[/dim]")
        return

    console.print("[bold]Scopes:[/bold]")
    for scope_type, name in scopes:
        label = name or scope_type
        store = scope_manager.get_store(scope_type, name)
        goal_count = store.read_goals().count("## ")
        console.print(f"  [cyan]{scope_type}[/cyan]/{label}  ({goal_count} goals)")


def _add_scope(scope_manager) -> None:
    """Interactive scope creation."""
    scope_type = Prompt.ask(
        "Scope type",
        choices=["personal", "projects", "org"],
        default="projects",
    )

    name = None
    if scope_type in ("projects", "org"):
        name = Prompt.ask("Name (e.g. 'kinsol', 'kinsol-research')")
        if not name:
            console.print("[red]Name required for project/org scopes[/red]")
            return

    store = scope_manager.create_scope(scope_type, name)
    label = name or scope_type
    console.print(f"[green]Created scope: {scope_type}/{label}[/green]")
    console.print(f"  Files at: {store.root}")

    # Offer to add a goal right away
    if Prompt.ask("Add a goal now?", choices=["y", "n"], default="y") == "y":
        goal_name = Prompt.ask("Goal name")
        description = Prompt.ask("Description")
        people_raw = Prompt.ask("Key people (comma-separated)", default="")
        people = [p.strip() for p in people_raw.split(",") if p.strip()] or None
        store.set_goal(goal_name, description, people)
        console.print(f"[green]Added goal '{goal_name}'[/green]")


def cmd_goals(args: argparse.Namespace) -> None:
    """List or add goals."""
    from work.context import ScopeManager

    scope_manager = ScopeManager(WORK_HOME)

    if args.goals_action == "add":
        _add_goal(scope_manager)
        return

    # List all goals
    scopes = _filter_scopes(scope_manager, getattr(args, "scope", None))
    if not scopes:
        console.print("[dim]No scopes found. Run 'work scope add' to create one.[/dim]")
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

    for scope_type, name in _filter_scopes(scope_manager, getattr(args, "scope", None)):
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

    for scope_type, name in _filter_scopes(scope_manager, getattr(args, "scope", None)):
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


async def cmd_agents(args: argparse.Namespace) -> None:
    """Run or check status of goal agents."""
    if args.agents_action == "run":
        scope_manager, gemini, _ = _init_components()
        from work.agent.goal_agent import run_all_goal_agents

        with console.status("[dim]Running goal agents...[/dim]"):
            count = await run_all_goal_agents(gemini, scope_manager)

        if count > 0:
            console.print(f"[green]Goal agents produced work for {count} goal(s).[/green]")
            console.print("[dim]Run 'work pending' to see pending actions.[/dim]")
        else:
            console.print("[dim]No agent-enabled goals found (add 'agent: enabled' to a goal section).[/dim]")

    elif args.agents_action == "status":
        pending_path = WORK_HOME / "pending_actions.json"
        if pending_path.exists():
            try:
                pending = json.loads(pending_path.read_text())
                by_status: dict[str, int] = {}
                for a in pending:
                    s = a.get("status", "unknown")
                    by_status[s] = by_status.get(s, 0) + 1
                console.print("[bold]Pending actions:[/bold]")
                for status, count in sorted(by_status.items()):
                    console.print(f"  {status}: {count}")
            except (json.JSONDecodeError, ValueError):
                console.print("[dim]No pending actions.[/dim]")
        else:
            console.print("[dim]No pending actions.[/dim]")


def cmd_pending(args: argparse.Namespace) -> None:
    """Show pending actions from goal agents."""
    pending_path = WORK_HOME / "pending_actions.json"
    if not pending_path.exists():
        console.print("[dim]No pending actions. Run 'work agents run' first.[/dim]")
        return

    try:
        pending = json.loads(pending_path.read_text())
    except (json.JSONDecodeError, ValueError):
        console.print("[dim]No pending actions.[/dim]")
        return

    # Filter to only pending status
    active = [a for a in pending if a.get("status") == "pending"]
    if not active:
        console.print("[dim]No pending actions (all approved or dismissed).[/dim]")
        return

    table = Table(title=f"Pending Actions ({len(active)})", show_lines=True)
    table.add_column("ID", style="dim", width=8)
    table.add_column("Goal", style="cyan", width=20)
    table.add_column("Type", width=14)
    table.add_column("Title", ratio=1)
    table.add_column("Priority", width=8)
    table.add_column("Created", style="dim", width=16)

    priority_colors = {"high": "red", "medium": "yellow", "low": "green"}

    for action in active:
        priority = action.get("priority", "medium")
        color = priority_colors.get(priority, "white")
        created = action.get("created_at", "")[:16]
        table.add_row(
            action.get("id", "?"),
            action.get("goal", "?"),
            action.get("type", "?"),
            action.get("title", "?"),
            f"[{color}]{priority}[/{color}]",
            created,
        )

    console.print(table)


SOURCE_COLORS = {
    "imessage": "cyan",
    "whatsapp": "green",
    "chrome": "yellow",
    "clipboard": "magenta",
    "screenshot": "blue",
    "active_app": "bright_blue",
    "email": "bright_cyan",
    "calendar": "bright_green",
    "drive": "bright_magenta",
    "tasks": "bright_white",
}


def cmd_log(args: argparse.Namespace) -> None:
    """Display signal log as a Rich table."""
    log_path = WORK_HOME / "signal_log.jsonl"
    if not log_path.exists():
        console.print("[dim]No signal log found at ~/.work/signal_log.jsonl[/dim]")
        return

    # Read all signals
    signals = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                signals.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    if not signals:
        console.print("[dim]Signal log is empty.[/dim]")
        return

    # Filter by --today
    if args.today:
        today_str = datetime.now().strftime("%Y-%m-%d")
        signals = [s for s in signals if s.get("timestamp", "").startswith(today_str)]

    # Filter by --source
    if args.source:
        signals = [s for s in signals if s.get("source") == args.source]

    # Filter by --search
    if args.search:
        query = args.search.lower()
        signals = [
            s for s in signals
            if query in s.get("text", "").lower()
            or query in s.get("sender", "").lower()
            or query in s.get("source", "").lower()
        ]

    # Take last N
    n = args.n or 50
    signals = signals[-n:]

    if not signals:
        console.print("[dim]No signals match the given filters.[/dim]")
        return

    # Build table
    table = Table(title=f"Signal Log ({len(signals)} signals)", show_lines=False)
    table.add_column("Time", style="dim", width=19)
    table.add_column("Source", width=12)
    table.add_column("Sender", width=25)
    table.add_column("Text", ratio=1)

    for s in signals:
        ts = s.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            time_str = ts[:19]

        source = s.get("source", "unknown")
        color = SOURCE_COLORS.get(source, "white")
        sender = s.get("sender", "")
        text = s.get("text", "")[:120]

        table.add_row(
            time_str,
            f"[{color}]{source}[/{color}]",
            sender[:25],
            text,
        )

    console.print(table)


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

    # work scope [add]
    p_scope = sub.add_parser("scope", help="List or create scopes")
    p_scope.add_argument("scope_action", nargs="?", default=None, choices=["add"], help="'add' to create a new scope")

    # work goals [add]
    p_goals = sub.add_parser("goals", help="List or manage goals")
    p_goals.add_argument("goals_action", nargs="?", default=None, choices=["add"], help="'add' to create a new goal")
    p_goals.add_argument("--scope", type=str, default=None, help="Filter by scope name")

    # work actions
    p_actions = sub.add_parser("actions", help="Show current actions across scopes")
    p_actions.add_argument("--scope", type=str, default=None, help="Filter by scope name")

    # work memory
    p_memory = sub.add_parser("memory", help="Show memory across scopes")
    p_memory.add_argument("--scope", type=str, default=None, help="Filter by scope name")

    # work standup
    sub.add_parser("standup", help="Morning standup briefing")

    # work log
    p_log = sub.add_parser("log", help="View signal log")
    p_log.add_argument("--today", action="store_true", help="Only show signals from today")
    p_log.add_argument("--source", type=str, default=None, help="Filter by source type (e.g. imessage, email)")
    p_log.add_argument("-n", type=int, default=None, help="Number of signals to show (default 50)")
    p_log.add_argument("--search", type=str, default=None, help="Text search across signal text/sender")

    # work status
    sub.add_parser("status", help="Show monitor status and signal counts")

    # work agents [run|status]
    p_agents = sub.add_parser("agents", help="Run goal agents")
    p_agents.add_argument(
        "agents_action",
        nargs="?",
        default="run",
        choices=["run", "status"],
    )

    # work pending
    sub.add_parser("pending", help="Show pending actions from goal agents")

    # work web
    p_web = sub.add_parser("web", help="Start the web dashboard")
    p_web.add_argument("--port", type=int, default=5050)

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

    def _run(coro):
        try:
            asyncio.run(coro)
        except KeyboardInterrupt:
            console.print("\n[dim]Goodbye.[/dim]")

    match args.command:
        case None:
            _run(cmd_interactive(args))
        case "monitor":
            _run(cmd_monitor(args))
        case "scope":
            cmd_scope(args)
        case "goals":
            cmd_goals(args)
        case "actions":
            cmd_actions(args)
        case "memory":
            cmd_memory(args)
        case "standup":
            _run(cmd_standup(args))
        case "log":
            cmd_log(args)
        case "status":
            cmd_status(args)
        case "agents":
            _run(cmd_agents(args))
        case "pending":
            cmd_pending(args)
        case "web":
            from work.web.server import start
            start(port=args.port)
        case _:
            parser.print_help()


if __name__ == "__main__":
    main()
