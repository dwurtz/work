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

from work.config import AGENT_MODEL, PREDICT_MODEL, VISION_MODEL

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
    # Combined analysis + compaction (5-minute cycle)
    # ------------------------------------------------------------------

    async def analyze_and_compact(
        self,
        signals_text: str,
        goals_text: str,
        existing_memories: dict[str, str],
    ) -> dict:
        """Analyze signals against goals and extract memory/actions in one call.

        Args:
            signals_text: All unanalyzed signals since last analysis cycle, one per line.
            goals_text: All goals across all scopes.
            existing_memories: Dict of scope label -> existing memory.md content.

        Returns a dict with keys: matches, skips, new_facts, commitments, proposed_goals.
        """
        memory_context = ""
        for scope_label, mem in existing_memories.items():
            snippet = mem[-2000:] if mem else "(empty)"
            memory_context += f"\n--- {scope_label} ---\n{snippet}\n"

        prompt = f"""\
You are a combined goal-matching + memory-extraction assistant for a productivity agent.

GOALS (organized by scope -- personal, projects/<name>, org/<name>):
{goals_text}

EXISTING MEMORY (already persisted -- do NOT repeat these facts):
{memory_context}

SIGNALS (timestamped — use timestamps to understand conversation flow and related events):
{signals_text}

Analyze every signal and return a JSON object with these keys:

1. "matches" — signals that match existing goals:
[
  {{
    "signal_summary": "brief description",
    "goal": "exact goal name from GOALS list",
    "scope": "personal|projects/<name>|org/<name>",
    "confidence": "low|medium|high",
    "reasoning": "1 short sentence",
    "action": "suggested next action if medium/high, else null"
  }}
]

2. "skips" — signals that don't match any goal:
[
  {{
    "signal_summary": "brief description",
    "reasoning": "1 short sentence why no match"
  }}
]

3. "new_facts" — NEW facts to add to memory.md (NOT already in existing memory):
[
  {{
    "scope": "personal|projects/<name>|org/<name>",
    "fact": "the fact to remember, with names/dates/amounts"
  }}
]

4. "commitments" — commitments to track in actions.md:
[
  {{
    "scope": "personal|projects/<name>|org/<name>",
    "commitment": "who committed to what",
    "deadline": "deadline if mentioned, else null"
  }}
]

5. "proposed_goals" — new goals inferred from signal patterns:
[
  {{
    "name": "short specific goal name",
    "description": "what this goal is about",
    "key_people": ["names if detectable"]
  }}
]

RULES:
- Use EXACT goal names from the GOALS list. Do not rephrase.
- Match based on full description and key people, not just keyword overlap.
- A person listed under a specific goal almost certainly produces signals for THAT goal.
- Confidence: low=tangential, medium=clearly relevant, high=multiple corroborating signals + concrete action ready.
- Only extract facts NOT already in existing memory. Check carefully.
- Identify commitments: "I'll...", "by Friday", deadline language, task assignments.
- Only propose goals when 2+ signals form a clear pattern. Be specific in naming.
- TIMESTAMPS MATTER: Messages within minutes of each other from the same person or thread are likely part of one conversation. A reply at 12:41 relates to a message at 12:38.
- GROUP RELATED SIGNALS: Multiple signals about the same topic (e.g. several real estate signals over an hour) should be analyzed together, not individually.
- CONVERSATION CONTEXT: When you see a reply from someone, look for the original message in earlier signals. "I'm not going to" only makes sense if you see what was asked.

COMPOUND PATTERNS to watch for:
- New Google Doc/Sheet + shared with people + calendar event = New project starting
- 5+ emails from same sender + calendar event = Active deal or negotiation
- Real estate tabs + address searches + partner messages = House hunting
- Flight/hotel booking + calendar blocks + partner messages = Trip planning
- Repeated visits to same tutorial/course site = Learning a new skill
- School/activity emails + calendar events + partner messages = Child activity coordination
- Same doc opened 3+ times without edits = Blocked or under review
- Same person messaged 3+ days running = Active collaboration
- Calendar event rescheduled 2+ times = Struggling to schedule
- "I'll..." or deadline language in any message = Commitment with timeline

Return ONLY the JSON object with all 5 keys."""

        resp = await self.client.aio.models.generate_content(
            model=PREDICT_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                max_output_tokens=8192,
                temperature=0.2,
            ),
        )
        try:
            result = json.loads(resp.text)
        except (json.JSONDecodeError, ValueError):
            try:
                result = _parse_json(resp.text)
            except (json.JSONDecodeError, ValueError):
                log.warning("analyze_and_compact: could not parse response: %s", resp.text[:200])
                return {"matches": [], "skips": [], "new_facts": [], "commitments": [], "proposed_goals": []}

        if not isinstance(result, dict):
            log.warning("analyze_and_compact: expected dict, got %s", type(result))
            return {"matches": [], "skips": [], "new_facts": [], "commitments": [], "proposed_goals": []}

        # Ensure all keys exist
        for key in ("matches", "skips", "new_facts", "commitments", "proposed_goals"):
            if key not in result:
                result[key] = []

        return result

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
            img = Image.open(image_path).convert("RGB")
            if img.width > 800:
                ratio = 800 / img.width
                img = img.resize((800, int(img.height * ratio)), Image.LANCZOS)
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
