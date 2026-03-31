"""ScopeManager — discover and manage all context scopes."""

from __future__ import annotations

from pathlib import Path

from work.config import SCOPES, ScopePaths, scope_paths
from work.context.store import ContextStore


class ScopeManager:
    """Discovers and provides access to all scope ContextStores."""

    def __init__(self, work_home: Path) -> None:
        self.work_home = work_home

    def list_scopes(self) -> list[tuple[str, str | None]]:
        """Return all (scope_type, name) pairs that exist on disk."""
        result: list[tuple[str, str | None]] = []

        # Personal scope — single directory
        personal_dir = self.work_home / "personal"
        if personal_dir.is_dir():
            result.append(("personal", None))

        # Named scopes (projects, org, etc.)
        for scope in SCOPES:
            if scope == "personal":
                continue
            scope_dir = self.work_home / scope
            if not scope_dir.is_dir():
                continue
            for child in sorted(scope_dir.iterdir()):
                if child.is_dir():
                    result.append((scope, child.name))

        return result

    def get_store(self, scope: str, name: str | None = None) -> ContextStore:
        """Get a ContextStore for an existing or new scope."""
        return ContextStore(scope_paths(scope, name))

    def get_all_stores(self) -> list[ContextStore]:
        """Return a ContextStore for every discovered scope."""
        return [self.get_store(s, n) for s, n in self.list_scopes()]

    def create_scope(self, scope: str, name: str | None = None) -> ContextStore:
        """Create a new scope directory with empty files and return its store."""
        store = ContextStore(scope_paths(scope, name))
        # ensure() is called in ContextStore.__init__, so files already exist
        return store

    def all_goals(self) -> str:
        """Concatenate goals from all scopes (useful for signal matching)."""
        parts: list[str] = []
        for scope_type, name in self.list_scopes():
            store = self.get_store(scope_type, name)
            goals = store.read_goals().strip()
            if goals:
                label = name or scope_type
                parts.append(f"### {label}\n\n{goals}")
        return "\n\n".join(parts)
