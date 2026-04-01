"""GoalAgent — autonomous agent that works toward goals and produces pending actions."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from work.config import AGENT_MODEL, WORK_HOME
from work.context.scopes import ScopeManager
from work.llm.gemini import GeminiClient

log = logging.getLogger(__name__)

PENDING_PATH = WORK_HOME / "pending_actions.json"
ARTIFACTS_DIR = WORK_HOME / "artifacts"


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


class GoalAgent:
    """Autonomous agent that works toward a specific goal."""

    def __init__(self, gemini: GeminiClient, scope_manager: ScopeManager) -> None:
        self.gemini = gemini
        self.scope_manager = scope_manager

    async def run_for_goal(
        self, scope_type: str, scope_name: str | None, goal: dict
    ) -> None:
        """Run the agent for a single goal. Produces pending actions."""
        goal_name = goal.get("name", "")
        description = goal.get("description", "")
        key_people = goal.get("key_people", [])

        # Get context
        store = self.scope_manager.get_store(scope_type, scope_name)
        memory = store.read_memory()
        actions = store.read_actions()

        # Get recent signals related to this goal from signal log
        recent_signals = self._get_recent_goal_signals(goal_name, limit=20)

        prompt = f"""You are an autonomous agent working toward a user's goal. You can research, create documents, and draft messages — but you CANNOT contact anyone or take external action. Everything you produce goes into a review queue for the user to approve.

GOAL: {goal_name}
DESCRIPTION: {description}
KEY PEOPLE: {', '.join(key_people) if key_people else 'none specified'}

EXISTING MEMORY (what we know):
{memory[-2000:] if memory else '(empty)'}

CURRENT ACTIONS (what we're tracking):
{actions[-1000:] if actions else '(empty)'}

RECENT SIGNALS RELATED TO THIS GOAL:
{recent_signals if recent_signals else '(none)'}

Based on the goal, memory, and recent signals, what concrete work can you do RIGHT NOW to advance this goal?

Return a JSON array of actions you want to take. Each action:
{{
  "type": "research|draft_email|draft_message|create_document|create_note|suggestion",
  "title": "short title of the action",
  "description": "what this action does and why",
  "content": "the actual content (search query, email draft text, document content, etc)",
  "recipient": "who this is for (null if not a message)",
  "requires_approval": true,
  "priority": "high|medium|low"
}}

RULES:
- Only suggest actions that are CONCRETELY useful right now, not vague "research more"
- For research: specify exact search queries or URLs to check
- For draft_email/draft_message: write the FULL draft text ready to send
- For create_document: write the full document content
- For suggestion: suggest an action the user should take manually
- NEVER suggest contacting someone without requires_approval: true
- If there's nothing useful to do right now, return an empty array []
- Max 3 actions per run

Return ONLY the JSON array."""

        try:
            from google.genai import types

            resp = await self.gemini.client.aio.models.generate_content(
                model=AGENT_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    max_output_tokens=4096,
                    temperature=0.3,
                ),
            )

            if not resp.text:
                return

            new_actions = json.loads(resp.text)
            if not isinstance(new_actions, list):
                return

            # Add metadata and save to pending queue
            pending = _load_pending()
            for action in new_actions:
                action["id"] = str(uuid.uuid4())[:8]
                action["goal"] = goal_name
                action["scope"] = (
                    f"{scope_type}/{scope_name}" if scope_name else scope_type
                )
                action["created_at"] = datetime.now(timezone.utc).isoformat()
                action["status"] = "pending"
                pending.append(action)

                # If action creates a document, save it as an artifact
                if action.get("type") in (
                    "create_document",
                    "create_note",
                ) and action.get("content"):
                    self._save_artifact(action)

            _save_pending(pending)
            log.info(
                "Goal agent produced %d actions for '%s'",
                len(new_actions),
                goal_name,
            )

        except Exception:
            log.exception("Goal agent failed for '%s'", goal_name)

    def _save_artifact(self, action: dict) -> None:
        """Save document/note content to artifacts directory."""
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        title_slug = action.get("title", "untitled").replace(" ", "_")[:40]
        filename = f"{action['id']}_{title_slug}.md"
        path = ARTIFACTS_DIR / filename
        path.write_text(action.get("content", ""))
        action["artifact_path"] = str(path)

    def _get_recent_goal_signals(self, goal_name: str, limit: int = 20) -> str:
        """Get recent signals that were matched to this goal from analysis log."""
        analysis_path = WORK_HOME / "analysis_log.jsonl"
        if not analysis_path.exists():
            return ""

        relevant: list[str] = []
        try:
            with open(analysis_path) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        for match in entry.get("matches", []):
                            if match.get("goal") == goal_name:
                                relevant.append(
                                    f"[{entry.get('timestamp', '?')[:16]}] "
                                    f"{match.get('signal_summary', '')} "
                                    f"(confidence: {match.get('confidence', '?')})"
                                )
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

        return "\n".join(relevant[-limit:])


async def run_all_goal_agents(
    gemini: GeminiClient, scope_manager: ScopeManager
) -> int:
    """Run agents for all goals that have agent: enabled. Returns count of actions produced."""
    agent = GoalAgent(gemini, scope_manager)
    total_actions = 0

    for scope_type, scope_name in scope_manager.list_scopes():
        store = scope_manager.get_store(scope_type, scope_name)
        goals_text = store.read_goals()
        goals = _parse_goals_for_agents(goals_text)

        for goal in goals:
            if goal.get("agent_enabled"):
                await agent.run_for_goal(scope_type, scope_name, goal)
                total_actions += 1

    return total_actions


def _parse_goals_for_agents(goals_text: str) -> list[dict]:
    """Parse goals.md and check for agent: enabled flag."""
    goals: list[dict] = []
    sections = goals_text.split("---")
    for section in sections:
        section = section.strip()
        if not section or not section.startswith("##"):
            continue
        lines = section.split("\n")
        name_line = lines[0].replace("##", "").strip()

        # Check for agent: enabled in the section
        agent_enabled = any(
            "agent:" in line.lower() and "enabled" in line.lower()
            for line in lines
        )

        # Extract description and key people
        description = ""
        key_people: list[str] = []
        in_people = False
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("**Key People"):
                in_people = True
                continue
            if in_people and stripped.startswith("- "):
                people_text = stripped[2:].split("\u2014")[0].split("(")[0].strip()
                key_people.append(people_text)
            elif in_people and stripped and not stripped.startswith("-"):
                in_people = False
            elif not in_people and stripped and not stripped.startswith(("agent:", "Agent:")):
                if description:
                    description += " "
                description += stripped

        goals.append(
            {
                "name": name_line,
                "description": description,
                "key_people": key_people,
                "agent_enabled": agent_enabled,
            }
        )

    return goals
