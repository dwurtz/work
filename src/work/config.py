"""Configuration and paths for the work agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

WORK_HOME = Path(os.environ.get("WORK_HOME", Path.home() / ".work"))

# Scopes
SCOPES = ("personal", "projects", "org")

# Monitor timing
SIGNAL_INTERVAL = 2        # collect signals every N seconds
MATCH_INTERVAL = 15         # run Gemini matching every N seconds
SCREENSHOT_INTERVAL = 3     # screenshot on context change check
COMPACT_INTERVAL = 3600     # compact hot buffer every hour

# Gemini models
MONITOR_MODEL = "gemini-2.0-flash"          # cheap, fast signal matching
VISION_MODEL = "gemini-2.5-flash"           # screenshot analysis
PREDICT_MODEL = "gemini-2.5-flash"          # action prediction
AGENT_MODEL = "gemini-2.5-pro"              # interactive conversation

# Apps to ignore for screenshots
IGNORED_APPS = {"cmux", "Activity Monitor", "Python", "Terminal"}

# Apps to capture screenshots of
SCREENSHOT_APPS = {
    "Google Chrome", "Safari", "Arc", "Brave Browser", "Firefox",
    "Messages", "WhatsApp", "Mail", "Superhuman", "Calendar",
    "Preview", "Finder", "Slack", "Notes", "Maps", "Discord",
    "Signal", "Telegram",
}

# Signal sources
IMESSAGE_DB = Path.home() / "Library" / "Messages" / "chat.db"
WHATSAPP_DB = (
    Path.home()
    / "Library"
    / "Group Containers"
    / "group.net.whatsapp.WhatsApp.shared"
    / "ChatStorage.sqlite"
)


@dataclass
class ScopePaths:
    """Paths to the three files for a given scope."""
    root: Path
    memory: Path = field(init=False)
    actions: Path = field(init=False)
    goals: Path = field(init=False)
    hot_buffer: Path = field(init=False)

    def __post_init__(self) -> None:
        self.memory = self.root / "memory.md"
        self.actions = self.root / "actions.md"
        self.goals = self.root / "goals.md"
        self.hot_buffer = self.root / ".hot_buffer.md"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for p in (self.memory, self.actions, self.goals):
            if not p.exists():
                p.write_text(f"# {p.stem.title()}\n\n")


def scope_paths(scope: str, name: str | None = None) -> ScopePaths:
    """Get paths for a scope. For projects/org, name is required."""
    if scope == "personal":
        return ScopePaths(root=WORK_HOME / "personal")
    if name is None:
        raise ValueError(f"Scope '{scope}' requires a name")
    return ScopePaths(root=WORK_HOME / scope / name)
