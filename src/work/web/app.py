"""FastAPI backend for the work productivity agent web dashboard."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import subprocess
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
from work.llm import GeminiClient
from work.signals import SignalCollector

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
PENDING_PATH = WORK_HOME / "pending_actions.json"
CONTACTS_PATH = WORK_HOME / "contacts.json"


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


class PendingEdit(BaseModel):
    content: str


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
# Pending Actions (from goal agents)
# ---------------------------------------------------------------------------


def _load_pending() -> list[dict]:
    if PENDING_PATH.exists():
        try:
            return json.loads(PENDING_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _save_pending(actions: list[dict]) -> None:
    WORK_HOME.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(actions, indent=2))


@app.get("/api/pending")
def get_pending() -> list[dict]:
    return _load_pending()


@app.post("/api/pending/{action_id}/approve")
def approve_pending(action_id: str) -> dict:
    pending = _load_pending()
    target = None
    for action in pending:
        if action.get("id") == action_id:
            target = action
            break

    if target is None:
        return {"status": "not_found", "id": action_id}

    target["status"] = "approved"
    target["approved_at"] = datetime.now(timezone.utc).isoformat()

    # Execute the action if applicable
    action_type = target.get("type", "")
    if action_type == "draft_email" and target.get("recipient"):
        try:
            title = target.get("title", "(no subject)")
            content = target.get("content", "")
            recipient = target.get("recipient", "")
            raw = f"From: david@davidwurtz.com\nTo: {recipient}\nSubject: {title}\n\n{content}"
            encoded = base64.urlsafe_b64encode(raw.encode()).decode()
            subprocess.run(
                [
                    "gws", "gmail", "users", "messages", "send",
                    "--params", json.dumps({"userId": "me"}),
                    "--json", json.dumps({"raw": encoded}),
                ],
                capture_output=True,
                timeout=15,
            )
            target["executed"] = True
        except Exception as e:
            target["execute_error"] = str(e)
    elif action_type == "draft_message" and target.get("recipient"):
        try:
            phone = target.get("recipient", "")
            content = target.get("content", "")
            safe_msg = content[:300].replace('"', '').replace("'", "").replace("\\", "")
            script = f'''
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant "{phone}" of targetService
                send "{safe_msg}" to targetBuddy
            end tell
            '''
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=10,
            )
            target["executed"] = True
        except Exception as e:
            target["execute_error"] = str(e)

    _save_pending(pending)
    return {"status": "approved", "id": action_id, "type": action_type}


@app.post("/api/pending/{action_id}/dismiss")
def dismiss_pending(action_id: str) -> dict:
    pending = _load_pending()
    remaining = [a for a in pending if a.get("id") != action_id]
    if len(remaining) == len(pending):
        return {"status": "not_found", "id": action_id}
    _save_pending(remaining)
    return {"status": "dismissed", "id": action_id}


@app.post("/api/pending/{action_id}/edit")
def edit_pending(action_id: str, body: PendingEdit) -> dict:
    pending = _load_pending()
    for action in pending:
        if action.get("id") == action_id:
            action["content"] = body.content
            action["edited_at"] = datetime.now(timezone.utc).isoformat()
            _save_pending(pending)
            return {"status": "updated", "id": action_id}
    return {"status": "not_found", "id": action_id}


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


@app.get("/api/contacts")
async def get_contacts():
    if CONTACTS_PATH.exists():
        try:
            return json.loads(CONTACTS_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            return []
    return []


@app.post("/api/contacts")
async def upsert_contact(body: dict):
    contacts = []
    if CONTACTS_PATH.exists():
        try:
            contacts = json.loads(CONTACTS_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            contacts = []
    existing = next((c for c in contacts if c.get("id") == body.get("id")), None)
    if existing:
        existing.update(body)
    else:
        if "id" not in body:
            body["id"] = body.get("name", "").lower().replace(" ", "_")[:20]
        contacts.append(body)
    WORK_HOME.mkdir(parents=True, exist_ok=True)
    CONTACTS_PATH.write_text(json.dumps(contacts, indent=2))
    return {"ok": True}


@app.delete("/api/contacts/{contact_id}")
async def delete_contact(contact_id: str):
    contacts = []
    if CONTACTS_PATH.exists():
        try:
            contacts = json.loads(CONTACTS_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            contacts = []
    contacts = [c for c in contacts if c.get("id") != contact_id]
    WORK_HOME.mkdir(parents=True, exist_ok=True)
    CONTACTS_PATH.write_text(json.dumps(contacts, indent=2))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Agent trigger
# ---------------------------------------------------------------------------


@app.post("/api/agents/run")
async def run_agents() -> dict:
    from work.agent.goal_agent import run_all_goal_agents
    from work.llm import GeminiClient

    gemini = GeminiClient()
    actions_count = await run_all_goal_agents(gemini, scope_manager)
    return {"actions_produced": actions_count}


# ---------------------------------------------------------------------------
# Conversation (chat)
# ---------------------------------------------------------------------------

CONVERSATION_PATH = WORK_HOME / "conversation.json"


def _load_conversation() -> list[dict]:
    if CONVERSATION_PATH.exists():
        try:
            return json.loads(CONVERSATION_PATH.read_text())
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def _save_conversation(messages: list[dict]):
    WORK_HOME.mkdir(parents=True, exist_ok=True)
    CONVERSATION_PATH.write_text(json.dumps(messages, indent=2))


@app.get("/api/chat")
async def get_chat(limit: int = 50):
    """Get conversation history."""
    messages = _load_conversation()
    return messages[-limit:]


@app.post("/api/chat")
async def post_chat(body: dict):
    """Send a message to the agent, get a response."""
    user_message = body.get("message", "")

    messages = _load_conversation()
    messages.append({
        "role": "user",
        "content": user_message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    # Build full context for the agent
    sm = ScopeManager(WORK_HOME)
    gemini = GeminiClient()

    # Get all context
    goals = sm.all_goals()

    memories = ""
    actions_text = ""
    for st, n in sm.list_scopes():
        store = sm.get_store(st, n)
        label = f"{st}/{n}" if n else st
        mem = store.read_memory()
        act = store.read_actions()
        if mem.strip():
            memories += f"\n--- {label} ---\n{mem[-1500:]}\n"
        if act.strip():
            actions_text += f"\n--- {label} ---\n{act[-500:]}\n"

    # Get recent signals
    collector = SignalCollector()
    recent = collector.get_recent_signals_from_log(minutes=30)

    # Get pending actions
    pending = []
    pending_path = WORK_HOME / "pending_actions.json"
    if pending_path.exists():
        try:
            pending = json.loads(pending_path.read_text())
            pending = [p for p in pending if p.get("status") == "pending"]
        except (json.JSONDecodeError, ValueError):
            pending = []

    # Build conversation history for Gemini
    history_for_model = []
    for msg in messages[-20:]:  # last 20 messages for context
        if msg["role"] == "user":
            history_for_model.append(f"User: {msg['content']}")
        elif msg["role"] == "agent":
            history_for_model.append(f"Agent: {msg['content']}")

    context = f"""You are a personal productivity agent for David. You have been monitoring his desktop, messages, email, and calendar. You know his goals, his memory, and his recent activity. You are having a conversation with him.

GOALS:
{goals}

MEMORY:
{memories if memories.strip() else "(no memory entries yet)"}

CURRENT ACTIONS:
{actions_text if actions_text.strip() else "(no actions tracked yet)"}

RECENT SIGNALS (last 30 min):
{recent[-3000:] if recent else "(no recent signals)"}

PENDING ACTIONS FROM SUB-AGENTS ({len(pending)} pending):
{json.dumps(pending[:5], indent=2) if pending else "(none)"}

CONVERSATION HISTORY:
{chr(10).join(history_for_model[-10:])}

INSTRUCTIONS:
- Be concise and direct. You know David personally from monitoring his life.
- Reference specific signals, people, and events you've observed.
- When suggesting actions that contact people (email, text), present them as drafts with [Send] [Edit] [Skip] options. Format these as markdown.
- When reporting sub-agent work, include the results inline.
- Never fabricate information. Only reference signals and facts you actually have.
- You can suggest creating goals, updating memory, or triggering sub-agents.
- Use markdown formatting for readability.

Respond to David's latest message."""

    # Call Gemini
    from google.genai import types

    resp = await gemini.client.aio.models.generate_content(
        model="gemini-2.5-pro",
        contents=context,
        config=types.GenerateContentConfig(
            max_output_tokens=2048,
            temperature=0.4,
        ),
    )

    agent_response = resp.text if resp.text else "I couldn't generate a response. Try again."

    messages.append({
        "role": "agent",
        "content": agent_response,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    _save_conversation(messages)

    return {"response": agent_response}


@app.post("/api/chat/proactive")
async def post_proactive(body: dict):
    """Add a proactive message from the system (called by monitor/agents)."""
    messages = _load_conversation()
    messages.append({
        "role": "agent",
        "content": body.get("content", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proactive": True,
    })
    _save_conversation(messages)
    return {"ok": True}


@app.delete("/api/chat")
async def clear_chat():
    """Clear conversation history."""
    _save_conversation([])
    return {"ok": True}


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
