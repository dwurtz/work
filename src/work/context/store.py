"""ContextStore — read/write the three-file system for a single scope."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from work.config import ScopePaths


class ContextStore:
    """Manages memory.md, actions.md, goals.md, and .hot_buffer.md for one scope."""

    def __init__(self, scope_paths: ScopePaths) -> None:
        self.paths = scope_paths
        self.paths.ensure()

    # -- Readers --

    def read_goals(self) -> str:
        return self.paths.goals.read_text()

    def read_memory(self) -> str:
        return self.paths.memory.read_text()

    def read_actions(self) -> str:
        return self.paths.actions.read_text()

    def read_hot_buffer(self) -> str:
        if not self.paths.hot_buffer.exists():
            return ""
        return self.paths.hot_buffer.read_text()

    # -- Writers --

    def append_to_hot_buffer(self, entry: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self.paths.hot_buffer.open("a") as f:
            f.write(f"[{ts}] {entry}\n")

    def update_actions(self, content: str) -> None:
        self.paths.actions.write_text(content)

    def update_memory(self, content: str) -> None:
        self.paths.memory.write_text(content)

    def set_goal(
        self,
        name: str,
        description: str,
        key_people: list[str] | None = None,
    ) -> str:
        """Add or update a goal section in goals.md. Returns 'Created' or 'Updated'."""
        people_md = (
            "\n".join(f"- {p}" for p in key_people)
            if key_people
            else "- (none specified)"
        )
        section = (
            f"\n---\n\n## {name}\n\n{description}\n\n"
            f"**Key People:**\n{people_md}\n"
        )

        content = self.read_goals()

        # Match existing section by name (case-insensitive), up to next section or EOF
        pattern = re.compile(
            r"(\n---\n\n## " + re.escape(name) + r"\n.*?)(?=\n---\n\n## |\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(content)

        if match:
            content = content[: match.start()] + section + content[match.end() :]
            action = "Updated"
        else:
            content = content.rstrip() + section
            action = "Created"

        self.paths.goals.write_text(content)
        return action

    def clear_hot_buffer(self) -> str:
        """Return hot buffer contents and clear the file."""
        contents = self.read_hot_buffer()
        self.paths.hot_buffer.write_text("")
        return contents

    def __repr__(self) -> str:
        return f"ContextStore({self.paths.root})"
