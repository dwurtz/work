"""FastAPI backend for the work productivity agent web dashboard."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from work.config import WORK_HOME
from work.context.scopes import ScopeManager
from work.context.store import ContextStore

app = FastAPI(title="work dashboard", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

scope_manager = ScopeManager(WORK_HOME)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIGNAL_LOG = WORK_HOME / "signal_log.jsonl"
ANALYSIS_LOG = WORK_HOME / "analysis_log.jsonl"
PROPOSED_GOALS = WORK_HOME / "proposed_goals.json"


def _read_jsonl(path: Path, limit: int | None = None) -> list[dict]:
    """Read a JSONL file, return list of dicts (most recent last)."""
    if not path.exists():
        return []
    entries: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit is not None:
        entries = entries[-limit:]
    return entries


def _read_proposed() -> list[dict]:
    """Read proposed_goals.json (create if missing)."""
    if not PROPOSED_GOALS.exists():
        PROPOSED_GOALS.write_text("[]")
        return []
    try:
        return json.loads(PROPOSED_GOALS.read_text())
    except (json.JSONDecodeError, ValueError):
        return []


def _write_proposed(goals: list[dict]) -> None:
    PROPOSED_GOALS.write_text(json.dumps(goals, indent=2))


def _parse_goals_md(content: str, scope: str, scope_name: str | None) -> list[dict]:
    """Parse a goals.md file into structured goal objects."""
    goals: list[dict] = []
    # Split by --- separators, then find ## sections
    sections = re.split(r"\n---\n", content)
    for section in sections:
        section = section.strip()
        if not section:
            continue
        # Find ## header
        match = re.search(r"^##\s+(.+)$", section, re.MULTILINE)
        if not match:
            continue
        name = match.group(1).strip()

        # Everything after the ## line
        after_header = section[match.end():].strip()
        lines = after_header.split("\n")

        # First non-empty line may have icon | status
        icon = ""
        status = ""
        description_lines: list[str] = []
        key_people: list[str] = []
        in_people = False
        started_desc = False

        for line in lines:
            stripped = line.strip()
            if not started_desc and not stripped:
                continue
            # Check for icon | status line (e.g. "🤸 | Active")
            if not started_desc and re.match(r"^.{1,4}\s*\|\s*\w+", stripped):
                parts = stripped.split("|", 1)
                icon = parts[0].strip()
                status = parts[1].strip() if len(parts) > 1 else ""
                started_desc = True
                continue
            started_desc = True

            if stripped.startswith("**Key People:**"):
                in_people = True
                continue
            if in_people:
                if stripped.startswith("- "):
                    key_people.append(stripped[2:].strip())
                elif stripped and not stripped.startswith("-"):
                    in_people = False
                    description_lines.append(stripped)
                continue

            description_lines.append(stripped)

        description = "\n".join(description_lines).strip()

        goals.append({
            "scope": scope,
            "scope_name": scope_name,
            "name": name,
            "description": description,
            "status": status or "Active",
            "key_people": key_people,
            "icon": icon,
        })

    return goals


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class GoalCreate(BaseModel):
    scope: str
    scope_name: str | None = None
    name: str
    description: str
    key_people: list[str] = []
    icon: str = ""


class GoalDelete(BaseModel):
    scope: str
    scope_name: str | None = None
    name: str


class ScopeCreate(BaseModel):
    type: str
    name: str | None = None


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------


@app.get("/api/signals")
def get_signals(
    since: str | None = Query(None, description="ISO timestamp filter"),
    source: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(200),
) -> list[dict]:
    signals = _read_jsonl(SIGNAL_LOG)

    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            signals = [
                s for s in signals
                if datetime.fromisoformat(s.get("timestamp", "")) >= since_dt
            ]
        except ValueError:
            pass

    if source:
        signals = [s for s in signals if s.get("source") == source]

    if search:
        q = search.lower()
        signals = [
            s for s in signals
            if q in s.get("text", "").lower()
            or q in s.get("sender", "").lower()
        ]

    return signals[-limit:]


@app.get("/api/signals/sources")
def get_signal_sources() -> list[str]:
    signals = _read_jsonl(SIGNAL_LOG)
    sources = sorted({s.get("source", "") for s in signals if s.get("source")})
    return sources


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------


@app.get("/api/goals")
def get_goals() -> list[dict]:
    all_goals: list[dict] = []
    for scope_type, name in scope_manager.list_scopes():
        store = scope_manager.get_store(scope_type, name)
        content = store.read_goals()
        all_goals.extend(_parse_goals_md(content, scope_type, name))
    return all_goals


@app.post("/api/goals")
def create_goal(body: GoalCreate) -> dict:
    store = scope_manager.get_store(body.scope, body.scope_name)
    # Prepend icon to description if provided
    desc = body.description
    if body.icon:
        desc = f"{body.icon} | Active\n\n{desc}"
    action = store.set_goal(body.name, desc, body.key_people or None)
    return {"status": action, "name": body.name}


@app.delete("/api/goals")
def delete_goal(body: GoalDelete) -> dict:
    store = scope_manager.get_store(body.scope, body.scope_name)
    content = store.read_goals()

    # Remove the ## section for this goal (from --- before it to next --- or EOF)
    pattern = re.compile(
        r"\n---\n\n## " + re.escape(body.name) + r"\n.*?(?=\n---\n\n## |\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    new_content, count = pattern.subn("", content)
    if count == 0:
        return {"status": "not_found", "name": body.name}

    store.paths.goals.write_text(new_content)
    return {"status": "deleted", "name": body.name}


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


@app.get("/api/memory")
def get_memory(scope: str | None = Query(None)) -> list[dict]:
    results: list[dict] = []
    for scope_type, name in scope_manager.list_scopes():
        if scope and (name or scope_type) != scope:
            continue
        store = scope_manager.get_store(scope_type, name)
        results.append({
            "scope": scope_type,
            "scope_name": name,
            "content": store.read_memory(),
        })
    return results


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@app.get("/api/actions")
def get_actions(scope: str | None = Query(None)) -> list[dict]:
    results: list[dict] = []
    for scope_type, name in scope_manager.list_scopes():
        if scope and (name or scope_type) != scope:
            continue
        store = scope_manager.get_store(scope_type, name)
        results.append({
            "scope": scope_type,
            "scope_name": name,
            "content": store.read_actions(),
        })
    return results


# ---------------------------------------------------------------------------
# Proposed Goals
# ---------------------------------------------------------------------------


@app.get("/api/proposed")
def get_proposed() -> list[dict]:
    return _read_proposed()


@app.post("/api/proposed/{goal_id}/accept")
def accept_proposed(goal_id: str) -> dict:
    proposed = _read_proposed()
    target = None
    remaining = []
    for pg in proposed:
        if pg.get("id") == goal_id:
            target = pg
        else:
            remaining.append(pg)

    if target is None:
        return {"status": "not_found", "id": goal_id}

    # Add to personal scope goals
    store = scope_manager.get_store("personal")
    store.set_goal(
        target.get("name", "New Goal"),
        target.get("description", ""),
        target.get("key_people"),
    )
    _write_proposed(remaining)
    return {"status": "accepted", "name": target.get("name")}


@app.post("/api/proposed/{goal_id}/reject")
def reject_proposed(goal_id: str) -> dict:
    proposed = _read_proposed()
    remaining = [pg for pg in proposed if pg.get("id") != goal_id]
    if len(remaining) == len(proposed):
        return {"status": "not_found", "id": goal_id}
    _write_proposed(remaining)
    return {"status": "rejected", "id": goal_id}


# ---------------------------------------------------------------------------
# Analysis History
# ---------------------------------------------------------------------------


@app.get("/api/analysis")
def get_analysis(limit: int = Query(50)) -> list[dict]:
    return _read_jsonl(ANALYSIS_LOG, limit=limit)


# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------


@app.get("/api/scopes")
def get_scopes() -> list[dict]:
    return [
        {"type": scope_type, "name": name}
        for scope_type, name in scope_manager.list_scopes()
    ]


@app.post("/api/scopes")
def create_scope(body: ScopeCreate) -> dict:
    scope_manager.create_scope(body.type, body.name)
    label = body.name or body.type
    return {"status": "created", "label": label}


# ---------------------------------------------------------------------------
# WebSocket: live signal stream
# ---------------------------------------------------------------------------


class SignalWatcher:
    """Watches signal_log.jsonl for new lines and broadcasts to connected clients."""

    def __init__(self) -> None:
        self.clients: list[WebSocket] = []
        self._task: asyncio.Task | None = None
        self._last_size: int = 0

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.append(ws)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._poll())

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.remove(ws)

    async def _poll(self) -> None:
        """Poll signal_log.jsonl for growth every 1s."""
        while self.clients:
            try:
                if SIGNAL_LOG.exists():
                    current_size = SIGNAL_LOG.stat().st_size
                    if current_size > self._last_size:
                        new_lines = self._read_new(current_size)
                        self._last_size = current_size
                        for line in new_lines:
                            await self._broadcast(line)
                    elif current_size < self._last_size:
                        # File was truncated/rotated
                        self._last_size = current_size
            except Exception:
                pass
            await asyncio.sleep(1)

    def _read_new(self, current_size: int) -> list[dict]:
        """Read new lines from the signal log."""
        results: list[dict] = []
        try:
            with open(SIGNAL_LOG, "rb") as f:
                f.seek(self._last_size)
                data = f.read(current_size - self._last_size)
            for line in data.decode("utf-8", errors="replace").split("\n"):
                line = line.strip()
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass
        return results

    async def _broadcast(self, data: dict) -> None:
        dead: list[WebSocket] = []
        for ws in self.clients:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


watcher = SignalWatcher()


@app.websocket("/ws/signals")
async def ws_signals(ws: WebSocket) -> None:
    await watcher.connect(ws)
    try:
        while True:
            # Keep connection alive; client can send pings
            await ws.receive_text()
    except WebSocketDisconnect:
        watcher.disconnect(ws)
