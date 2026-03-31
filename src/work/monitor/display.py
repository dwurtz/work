"""Rich-based terminal display for the monitor loop."""

from __future__ import annotations

from collections import deque
from datetime import datetime

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
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
    """Rich-based terminal display showing live signal flow."""

    def __init__(self, max_log: int = 50) -> None:
        self.console = Console()
        self.signals_log: deque[str] = deque(maxlen=max_log)
        self.matches_log: deque[str] = deque(maxlen=max_log)
        self.phase: str = "IDLE"
        self._last_render: datetime | None = None

    def show_signal(self, signal: Signal) -> None:
        """Log a newly collected signal."""
        color = SOURCE_COLORS.get(signal.source, "white")
        ts = signal.timestamp.strftime("%H:%M:%S")
        self.signals_log.append(
            f"[{color}][{ts}] [{signal.source}][/{color}] "
            f"{signal.sender}: {signal.text[:100]}"
        )

    def show_match(self, match: dict) -> None:
        """Log a signal-to-goal match (or non-match with reasoning)."""
        matched = match.get("matched", True)
        conf = match.get("confidence", "none")
        reasoning = match.get("reasoning", "")
        summary = match.get("signal_summary", "")[:60]

        if matched and conf != "none":
            color = CONFIDENCE_COLORS.get(conf, "white")
            goal = match.get("goal", "?")
            scope = match.get("scope", "?")
            self.matches_log.append(
                f"[{color}][{conf.upper()}][/{color}] "
                f"[bold]{goal}[/bold] ({scope}): {summary}\n"
                f"  [dim italic]{reasoning}[/dim italic]"
            )
        else:
            self.matches_log.append(
                f"[dim][ SKIP ] {summary}[/dim]\n"
                f"  [dim italic]{reasoning}[/dim italic]"
            )

    def show_status(self, phase: str) -> None:
        """Update the current phase."""
        self.phase = phase

    def render(self) -> None:
        """Render the full display to the terminal."""
        self.console.clear()

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
        header.append(f"  |  matches: {len(self.matches_log)}", style="dim")
        self.console.print(Panel(header, border_style="bright_blue"))

        # Signals panel
        if self.signals_log:
            signals_text = Text()
            for line in list(self.signals_log)[-15:]:
                signals_text.append_text(Text.from_markup(line))
                signals_text.append("\n")
            self.console.print(
                Panel(signals_text, title="Signals", border_style="cyan", height=18)
            )

        # Matches panel
        if self.matches_log:
            matches_text = Text()
            for line in list(self.matches_log)[-10:]:
                matches_text.append_text(Text.from_markup(line))
                matches_text.append("\n")
            self.console.print(
                Panel(matches_text, title="Reasoning", border_style="green", height=20)
            )

        self._last_render = datetime.now()
