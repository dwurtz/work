"""AgentEngine -- interactive conversation engine with full scope context."""

from __future__ import annotations

from work.context import ScopeManager
from work.llm import GeminiClient


class AgentEngine:
    """Interactive conversation engine."""

    def __init__(self, scope_manager: ScopeManager, gemini: GeminiClient) -> None:
        self.scope_manager = scope_manager
        self.gemini = gemini
        self.history: list[dict] = []

    async def chat(self, message: str) -> str:
        """Process a user message with full context."""
        context = self.build_context()

        self.history.append({"role": "user", "content": message})

        # Include recent conversation history in the message
        history_text = ""
        if len(self.history) > 1:
            recent = self.history[-10:]  # last 10 turns
            history_text = "\n\nRecent conversation:\n"
            for turn in recent[:-1]:  # exclude the current message
                role = turn["role"].upper()
                history_text += f"{role}: {turn['content']}\n"

        full_message = message
        if history_text:
            full_message = history_text + f"\nUSER: {message}"

        response = await self.gemini.chat(full_message, context)

        self.history.append({"role": "assistant", "content": response})
        return response

    def build_context(self) -> str:
        """Build context string from all scopes."""
        parts: list[str] = []

        for scope_type, name in self.scope_manager.list_scopes():
            store = self.scope_manager.get_store(scope_type, name)
            label = name or scope_type

            section = f"## Scope: {label}\n\n"

            goals = store.read_goals().strip()
            if goals:
                section += f"### Goals\n{goals}\n\n"

            memory = store.read_memory().strip()
            if memory:
                # Include last 2000 chars of memory to stay within context limits
                section += f"### Memory (recent)\n{memory[-2000:]}\n\n"

            actions = store.read_actions().strip()
            if actions:
                section += f"### Current Actions\n{actions}\n\n"

            hot_buffer = store.read_hot_buffer().strip()
            if hot_buffer:
                # Include last 1000 chars of hot buffer
                section += f"### Recent Signals (hot buffer)\n{hot_buffer[-1000:]}\n\n"

            parts.append(section)

        return "\n".join(parts) if parts else "(No scopes configured yet.)"
