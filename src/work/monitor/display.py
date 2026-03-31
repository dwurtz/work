"""Rich-based terminal display for the monitor loop."""

from __future__ import annotations

from collections import deque
from datetime import datetime

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from work.signals import Signal

# Deterministic colors for signal sources
SOURCE_COLORS = {
    "imessage": "cyan",
    "whatsapp": "green",
    "chrome": "yellow",
    "clipboard": "magenta",
    "screenshot": "blue",
    "calendar": "bright_green",
    "active_app": "bright_blue",
    "email": "bright_cyan",
}

CONFIDENCE_COLORS = {
    "low": "dim",
    "medium": "yellow",
    "high": "bold bright_green",
}


class MonitorDisplay:
    """Rich-based terminal display showing live signal flow using Live for in-place updates."""

    def __init__(self, max_log: int = 50) -> None:
        self.console = Console()
        self.signals_log: deque[str] = deque(maxlen=max_log)
        self.matches_log: deque[str] = deque(maxlen=max_log)
        self.proposed_goals: list[dict] = []  # pending proposed goals
        self.phase: str = "IDLE"
        self.real_match_count: int = 0
        self.skip_count: int = 0
        self._live: Live | None = None

    def start(self) -> None:
        """Start the Live display."""
        self._live = Live(
            self._build(),
            console=self.console,
            refresh_per_second=1,
            screen=True,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the Live display."""
        if self._live:
            self._live.stop()
            self._live = None

    def show_signal(self, signal: Signal) -> None:
        """Log a newly collected signal."""
        color = SOURCE_COLORS.get(signal.source, "white")
        ts = signal.timestamp.strftime("%H:%M:%S")
        self.signals_log.append(
            f"[{color}][{ts}][/{color}]  "
            f"{signal.sender}: {signal.text[:100]}"
        )

    def show_match(self, match: dict) -> None:
        """Log a signal-to-goal match (or non-match with reasoning)."""
        matched = match.get("matched", True)
        conf = match.get("confidence", "none")
        reasoning = match.get("reasoning", "")
        summary = match.get("signal_summary", "")[:60]

        if matched and conf != "none":
            self.real_match_count += 1
            color = CONFIDENCE_COLORS.get(conf, "white")
            goal = match.get("goal", "?")
            scope = match.get("scope", "?")
            self.matches_log.append(
                f"[{color}][{conf.upper()}][/{color}] "
                f"[bold]{goal}[/bold] ({scope}): {summary}\n"
                f"  [dim italic]{reasoning}[/dim italic]"
            )
        elif match.get("proposed_goal"):
            # Goal inference — show as a proposal
            pg = match["proposed_goal"]
            self.proposed_goals.append(pg)
            idx = len(self.proposed_goals)
            self.matches_log.append(
                f"[bold bright_yellow][ NEW GOAL? ] {pg.get('name', '?')}[/bold bright_yellow]\n"
                f"  [italic]{pg.get('description', '')}[/italic]\n"
                f"  [bold bright_yellow]Press {idx} to accept[/bold bright_yellow]"
            )
        else:
            self.skip_count += 1
            self.matches_log.append(
                f"[dim][ SKIP ] {summary}[/dim]\n"
                f"  [dim italic]{reasoning}[/dim italic]"
            )

    def show_status(self, phase: str) -> None:
        """Update the current phase."""
        self.phase = phase

    def render(self) -> None:
        """Update the Live display."""
        if self._live:
            self._live.update(self._build())

    def _build(self) -> Group:
        """Build the full display layout."""
        # Header
        phase_colors = {
            "IDLE": "dim",
            "OBSERVING": "bold cyan",
            "THINKING": "bold yellow",
            "PREDICTING": "bold magenta",
            "RECORDING": "bold green",
        }
        phase_style = phase_colors.get(self.phase, "white")
        header = Text()
        header.append("work monitor", style="bold white")
        header.append("  |  phase: ", style="dim")
        header.append(self.phase, style=phase_style)
        header.append(f"  |  signals: {len(self.signals_log)}", style="dim")
        header.append(f"  |  matches: {self.real_match_count}", style="dim")
        header.append(f"  |  skipped: {self.skip_count}", style="dim")

        parts = [Panel(header, border_style="bright_blue")]

        # Signals panel
        signals_text = Text()
        for line in list(self.signals_log)[-15:]:
            signals_text.append_text(Text.from_markup(line))
            signals_text.append("\n")
        parts.append(
            Panel(signals_text, title="Signals", border_style="cyan", height=18)
        )

        # Reasoning panel
        if self.matches_log:
            matches_text = Text()
            for line in list(self.matches_log)[-10:]:
                matches_text.append_text(Text.from_markup(line))
                matches_text.append("\n")
            parts.append(
                Panel(matches_text, title="Reasoning", border_style="green", height=20)
            )

        # Proposed goals panel
        if self.proposed_goals:
            pg_text = Text()
            for i, pg in enumerate(self.proposed_goals, 1):
                pg_text.append(f"  {i}. ", style="bold bright_yellow")
                pg_text.append(pg.get("name", "?"), style="bold")
                pg_text.append(f" — {pg.get('description', '')[:80]}\n", style="dim")
                people = pg.get("key_people", [])
                if people:
                    pg_text.append(f"     Key people: {', '.join(people)}\n", style="dim italic")
            pg_text.append("\n  Press number to accept, 0 to dismiss all", style="bold bright_yellow")
            parts.append(
                Panel(pg_text, title="Proposed Goals", border_style="bright_yellow", height=min(len(self.proposed_goals) * 3 + 4, 15))
            )

        return Group(*parts)
