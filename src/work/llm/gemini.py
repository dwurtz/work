"""Core Gemini wrapper for the work agent.

Uses the google-genai SDK for all LLM calls. All methods are async.
Requires GEMINI_API_KEY or GOOGLE_API_KEY in the environment.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from work.config import AGENT_MODEL, MONITOR_MODEL, PREDICT_MODEL, VISION_MODEL

log = logging.getLogger(__name__)


def _parse_json(raw: str) -> Any:
    """Best-effort JSON extraction from LLM output."""
    text = raw.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    # Find outermost JSON structure
    for open_ch, close_ch in [("[", "]"), ("{", "}")]:
        if open_ch in text and close_ch in text:
            start = text.index(open_ch)
            end = text.rindex(close_ch) + 1
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
    return json.loads(text)


class GeminiClient:
    """Async wrapper around the google-genai SDK for all agent LLM operations."""

    def __init__(self) -> None:
        self.client = genai.Client()

    # ------------------------------------------------------------------
    # Signal matching
    # ------------------------------------------------------------------

    async def match_signals(
        self, signals_text: str, goals_text: str
    ) -> list[dict]:
        """Match raw signals against goals.

        Returns a list of matches, each:
            {signal_summary, source, scope, goal, confidence, action}

        confidence: low / medium / high
        scope: "personal" | "projects/<name>" | "org/<name>"
        """
        prompt = f"""\
You are a goal-matching assistant for a productivity agent.

GOALS (organized by scope -- personal, projects/<name>, org/<name>):
{goals_text}

NEW SIGNALS:
{signals_text}

For EVERY signal, output a JSON object explaining your reasoning. Include both matches and non-matches so the user can see what the system is thinking.

Output a JSON array — one entry per signal:
[
  {{
    "signal_summary": "brief description of the signal",
    "source": "imessage|whatsapp|chrome|clipboard|screen|calendar|email|observation",
    "matched": true,
    "reasoning": "1-2 sentence explanation of WHY this matches or doesn't match any goal",
    "scope": "personal|projects/<project_name>|org/<org_name> (or null if no match)",
    "goal": "exact goal name from the list above (or null if no match)",
    "confidence": "low|medium|high|none",
    "action": "suggested next action if confidence is medium or high, else null"
  }}
]

Confidence guide:
- "low": tangentially related, or a single weak signal (e.g. keyword overlap only)
- "medium": clearly relevant -- the signal directly references the goal's subject or people, but more information is needed before acting
- "high": ONLY when multiple corroborating signals exist AND a concrete action is ready

Scope guide:
- Determine scope from the goal it matches. If a signal matches a goal under "projects/workagents", scope is "projects/workagents".
- If a signal matches a personal goal, scope is "personal".

IMPORTANT RULES:
- Use the EXACT goal name from the GOALS list. Do not rephrase.
- Match based on the goal's full description and key people, not just keyword overlap.
- A person listed under a specific goal almost certainly produces signals for THAT goal.
- Look for commitment-action gaps: someone said they'd do X but no evidence of follow-through.
- Look for behavioral patterns: repeated viewing without editing may indicate being blocked.
- If no signals match any goal, still return an entry for each with matched=false and your reasoning.
- ALWAYS include reasoning — this is shown to the user so they can see what the system is thinking.

GOAL INFERENCE:
- If you see a CLUSTER of unmatched signals that suggest a coherent activity (e.g. multiple real estate signals, or several signals about travel planning), add a special entry at the end:
  {{
    "signal_summary": "description of the pattern you noticed",
    "source": "inference",
    "matched": false,
    "reasoning": "why you think this is a goal",
    "scope": null,
    "goal": null,
    "confidence": "none",
    "action": null,
    "proposed_goal": {{
      "name": "short goal name",
      "description": "what this goal is about based on the signals",
      "key_people": ["names if detectable"]
    }}
  }}
- Only propose a goal when 2+ signals form a clear pattern. Don't propose for single isolated signals.

Return ONLY the JSON array."""

        resp = await self.client.aio.models.generate_content(
            model=MONITOR_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=2048,
                temperature=0.2,
            ),
        )
        try:
            matches = json.loads(resp.text)
        except (json.JSONDecodeError, ValueError):
            try:
                matches = _parse_json(resp.text)
            except (json.JSONDecodeError, ValueError):
                log.warning("match_signals: could not parse response: %s", resp.text[:200])
                return []

        if not isinstance(matches, list):
            log.warning("match_signals: expected list, got %s", type(matches))
            return []
        return matches

    # ------------------------------------------------------------------
    # Screenshot analysis
    # ------------------------------------------------------------------

    async def analyze_screenshot(
        self, image_path: str, goals_text: str
    ) -> dict:
        """Analyze a screenshot with vision.

        Returns {summary, app, key_details}.
        """
        # Resize image to reduce payload (max 1280px wide)
        try:
            from PIL import Image
            import io
            img = Image.open(image_path)
            if img.width > 1280:
                ratio = 1280 / img.width
                img = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            image_bytes = buf.getvalue()
            mime = "image/jpeg"
        except Exception:
            image_bytes = Path(image_path).read_bytes()
            mime = "image/png"

        prompt = (
            "Describe this screenshot in one sentence. "
            "Name the app, what content is visible, and any specific names, dates, numbers, or URLs you can see. "
            "Be concise — max 2 sentences."
        )

        resp = await self.client.aio.models.generate_content(
            model=VISION_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                prompt,
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=500,
                temperature=0.2,
            ),
        )

        if not resp.text:
            log.warning("Vision returned empty response")
            return {"summary": "Screenshot analysis failed", "app": "", "key_details": ""}

        return {"summary": resp.text.strip()[:500], "app": "", "key_details": ""}

    # ------------------------------------------------------------------
    # Action prediction
    # ------------------------------------------------------------------

    async def predict_actions(
        self,
        goals_text: str,
        memory_text: str,
        signals: list[dict],
    ) -> str:
        """Generate predicted next-actions markdown.

        Takes recent signals grouped by goal and produces a prioritized
        action plan. Returns the full markdown string for actions.md.
        """
        signals_summary = ""
        # Group signals by goal
        by_goal: dict[str, list[dict]] = {}
        for s in signals:
            goal = s.get("goal", "ungrouped")
            by_goal.setdefault(goal, []).append(s)

        for goal, sigs in by_goal.items():
            signals_summary += f"\n{goal} ({len(sigs)} signals):\n"
            for s in sigs[-10:]:
                source = s.get("source", "?")
                summary = s.get("summary", s.get("signal_summary", ""))
                signals_summary += f"  - [{source}] {summary}\n"

        prompt = f"""\
You maintain a "predicted next actions" file for a proactive productivity assistant.

GOALS:
{goals_text}

RECENT MEMORY:
{memory_text[-3000:] if memory_text else "(empty)"}

ACCUMULATED SIGNALS:
{signals_summary if signals_summary else "(none)"}

Based on the goals and signals, write an updated actions.md file.

For each goal with signals, include:
- Scope (personal / project name / org name)
- Priority level (HIGH / NORMAL / LOW)
- What happened (summarize the signals concisely)
- What needs to happen next (concrete, specific action steps)
- Any commitment-action gaps detected (things promised but not yet done)

For goals with no signals, write "No new signals" with a brief current status.

Write clean markdown. Start with "# Predicted Next Actions" and today's date.
Be specific -- include names, dates, amounts, URLs from the signals.
Keep it scannable: use headers, bullets, and bold for key items."""

        resp = await self.client.aio.models.generate_content(
            model=PREDICT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=2048,
                temperature=0.3,
            ),
        )
        return resp.text.strip()

    # ------------------------------------------------------------------
    # Buffer compaction
    # ------------------------------------------------------------------

    async def compact_buffer(
        self,
        hot_buffer: str,
        existing_memory: str,
        goals_text: str,
    ) -> tuple[str, str]:
        """Compact the hot buffer into durable memory entries.

        Separates signal noise from facts worth persisting.
        Returns (new_memory_entries, updated_actions_markdown).
        """
        prompt = f"""\
You are compacting a rolling signal buffer into durable memory for a productivity agent.

GOALS:
{goals_text}

EXISTING MEMORY (already persisted):
{existing_memory[-3000:] if existing_memory else "(empty)"}

HOT BUFFER (recent signals to process):
{hot_buffer}

Do two things:

1. MEMORY ENTRIES: Extract facts worth remembering long-term from the hot buffer.
   Keep: decisions made, commitments given, key dates/deadlines, status changes,
   contact info, meeting outcomes, prices, quantities, relationship context.
   Discard: routine browsing, duplicate signals, ephemeral UI state, noise.

   Format each memory entry as:
   ### <date> -- <source>
   <fact or facts as bullet points>

2. UPDATED ACTIONS: Based on everything (goals + existing memory + new facts),
   write a fresh actions.md with prioritized next steps per goal.

Return JSON with two keys:
{{
  "memory_entries": "markdown string of new memory entries to append",
  "actions": "full markdown string for actions.md"
}}"""

        resp = await self.client.aio.models.generate_content(
            model=PREDICT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=3000,
                temperature=0.3,
            ),
        )
        try:
            result = json.loads(resp.text)
        except (json.JSONDecodeError, ValueError):
            result = _parse_json(resp.text)

        memory = result.get("memory_entries", "")
        actions = result.get("actions", "")
        return memory, actions

    # ------------------------------------------------------------------
    # Interactive chat
    # ------------------------------------------------------------------

    async def chat(self, message: str, context: str) -> str:
        """Interactive conversation with the agent.

        context should be the concatenated memory/actions/goals from
        relevant scopes.
        """
        prompt = f"""\
You are a proactive productivity assistant. You have access to the user's goals,
memory, and predicted actions across their personal life, projects, and organization.

CONTEXT (goals, memory, recent actions):
{context}

Respond helpfully, concisely, and with specific references to the context above.
If the user asks about status, quote specifics from memory and signals.
If they ask what to do next, reference the predicted actions.
If they want to update goals or memory, confirm what you'll change.

USER: {message}"""

        resp = await self.client.aio.models.generate_content(
            model=AGENT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=2048,
                temperature=0.5,
            ),
        )
        return resp.text.strip()
