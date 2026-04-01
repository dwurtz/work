"""MonitorLoop -- main monitoring loop that collects signals, matches to goals, and updates context."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from work.config import (
    COMPACT_INTERVAL,
    MATCH_INTERVAL,
    SIGNAL_INTERVAL,
)
from work.context import ContextStore, ScopeManager
from work.llm import GeminiClient
from work.signals import Signal, SignalCollector

log = logging.getLogger(__name__)


class MonitorLoop:
    """Main monitoring loop that collects signals, matches to goals, and updates context files."""

    def __init__(
        self,
        scope_manager: ScopeManager,
        gemini: GeminiClient,
        collector: SignalCollector,
    ) -> None:
        self.scope_manager = scope_manager
        self.gemini = gemini
        self.collector = collector
        self.pending_signals: list[Signal] = []
        self.running = False
        self.display: MonitorDisplay | None = None

        # Stats
        self.matched_signal_ids: set[str] = set()
        self.signals_collected = 0
        self.matches_found = 0
        self.last_signal_time: datetime | None = None
        self.last_match_time: datetime | None = None
        self.last_compact_time: datetime | None = None
        self.phase: str = "IDLE"

    async def run(self, interactive: bool = False) -> None:
        """Main loop. If interactive=False, runs headless (daemon mode)."""
        if interactive:
            from work.monitor.display import MonitorDisplay

            self.display = MonitorDisplay()
            self.display.start()

        self.running = True
        log.info("Monitor loop starting (interactive=%s)", interactive)

        # Launch the three cycles as concurrent tasks
        tasks = [
            asyncio.create_task(self._signal_loop()),
            asyncio.create_task(self._match_loop()),
            asyncio.create_task(self._compact_loop()),
        ]
        if interactive and self.display:
            tasks.append(asyncio.create_task(self._display_loop()))

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("Monitor loop cancelled")
        finally:
            if self.display:
                self.display.stop()
            self.running = False

    async def _signal_loop(self) -> None:
        """Collect signals every SIGNAL_INTERVAL seconds."""
        while self.running:
            try:
                await self._collect_cycle()
            except Exception:
                log.exception("Error in signal collection cycle")
            await asyncio.sleep(SIGNAL_INTERVAL)

    async def _match_loop(self) -> None:
        """Run LLM matching every MATCH_INTERVAL seconds."""
        await asyncio.sleep(5)  # let signals accumulate first
        while self.running:
            try:
                await self._match_cycle()
            except Exception:
                log.exception("Error in match cycle")
            await asyncio.sleep(MATCH_INTERVAL)

    async def _compact_loop(self) -> None:
        """Compact hot buffers every COMPACT_INTERVAL seconds."""
        await asyncio.sleep(COMPACT_INTERVAL)
        while self.running:
            try:
                await self._compact_cycle()
            except Exception:
                log.exception("Error in compact cycle")
            await asyncio.sleep(COMPACT_INTERVAL)

    async def _display_loop(self) -> None:
        """Refresh the Rich display and handle key input."""
        while self.running and self.display:
            self.display.show_status(self.phase)
            self.display.render()

            # Check for key input (non-blocking)
            key = await self._read_key()
            if key and self.display.proposed_goals:
                if key == "0":
                    log.info("Dismissed all proposed goals")
                    self.display.proposed_goals.clear()
                elif key.isdigit():
                    idx = int(key) - 1
                    if 0 <= idx < len(self.display.proposed_goals):
                        pg = self.display.proposed_goals.pop(idx)
                        await self._accept_proposed_goal(pg)

            await asyncio.sleep(1)

    async def _accept_proposed_goal(self, pg: dict) -> None:
        """Accept a proposed goal and add it to personal scope."""
        try:
            store = self.scope_manager.get_store("personal")
            store.set_goal(
                pg.get("name", "New Goal"),
                pg.get("description", ""),
                pg.get("key_people"),
            )
            log.info("Accepted goal: %s", pg.get("name"))
        except Exception:
            log.exception("Error accepting goal")

    async def _read_key(self) -> str | None:
        """Non-blocking single key read."""
        import sys
        import select
        loop = asyncio.get_running_loop()
        try:
            ready = await loop.run_in_executor(
                None,
                lambda: select.select([sys.stdin], [], [], 0.05)[0],
            )
            if ready:
                return sys.stdin.read(1)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Cycles
    # ------------------------------------------------------------------

    async def _collect_cycle(self) -> None:
        """One collection cycle -- gather all new signals."""
        self.phase = "OBSERVING"

        # collect_all is synchronous; run in executor to avoid blocking
        loop = asyncio.get_running_loop()
        new_signals = await loop.run_in_executor(None, self.collector.collect_all)

        if new_signals:
            # Process screenshot signals through vision before adding
            processed: list[Signal] = []
            for sig in new_signals:
                if sig.source == "screenshot" and sig.text.endswith(".png"):
                    analyzed = await self._analyze_screenshot(sig)
                    if analyzed:
                        processed.append(analyzed)
                        # Notify what we're seeing on screen
                        self._notify("Screen", analyzed.text[:200])
                else:
                    processed.append(sig)

            self.pending_signals.extend(processed)
            self.signals_collected += len(processed)
            self.last_signal_time = datetime.now(timezone.utc)
            log.info("Collected %d new signals (%d pending)", len(processed), len(self.pending_signals))

            if self.display:
                for sig in processed:
                    self.display.show_signal(sig)

        self.phase = "IDLE"

    async def _analyze_screenshot(self, sig: Signal) -> Signal | None:
        """Send screenshot to Gemini Vision, delete the file, return a signal with the summary."""
        import os
        path = sig.text
        try:
            goals_text = self.scope_manager.all_goals()
            result = await self.gemini.analyze_screenshot(path, goals_text)
            summary = result.get("summary", "")
            app = result.get("app", "")
            details = result.get("key_details", "")
            text = f"{app}: {summary}"
            if details:
                text += f" | {details}"
            return Signal(
                source="screenshot",
                sender=app or "screen",
                text=text[:500],
                timestamp=sig.timestamp,
                id_key=sig.id_key,
            )
        except Exception:
            log.exception("Vision analysis failed for %s", path)
            return None
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    async def _match_cycle(self) -> None:
        """Send pending signals to Gemini for goal matching."""
        if not self.pending_signals:
            return

        self.phase = "THINKING"

        # Snapshot and clear pending
        batch = list(self.pending_signals)
        self.pending_signals.clear()

        # Build signals text
        signals_text = "\n".join(
            f"- [{s.source}] {s.sender}: {s.text}" for s in batch
        )

        # Include unmatched history for pattern detection
        unmatched_history = self.collector.get_unmatched_history_summary(self.matched_signal_ids)
        if unmatched_history:
            signals_text += (
                "\n\nRECENT UNMATCHED SIGNALS (for pattern detection — these were previously skipped):\n"
                + unmatched_history
            )

        # Get all goals across scopes
        goals_text = self.scope_manager.all_goals()
        if not goals_text.strip():
            log.info("No goals defined; skipping match cycle")
            return

        log.info("Matching %d signals against goals...", len(batch))
        matches = await self.gemini.match_signals(signals_text, goals_text)

        if not matches:
            log.info("No matches found")
            self.phase = "IDLE"
            return

        # Show ALL results in display (matches and non-matches with reasoning)
        actual_matches = [m for m in matches if m.get("matched", True) and m.get("confidence", "none") != "none"]
        self.matches_found += len(actual_matches)
        self.last_match_time = datetime.now(timezone.utc)
        log.info("Found %d matches out of %d signals", len(actual_matches), len(matches))

        # Show everything in display and notify reasoning
        skip_reasons = []
        for match in matches:
            if self.display:
                self.display.show_match(match)

            matched = match.get("matched", False)
            conf = match.get("confidence", "none")
            reasoning = match.get("reasoning", "")

            if match.get("proposed_goal"):
                pg = match["proposed_goal"]
                log.info("Goal proposed: %s", pg.get("name", "?"))
                self._notify(
                    f"New goal? {pg.get('name', '?')}",
                    pg.get("description", ""),
                )
            elif matched and conf in ("medium", "high"):
                goal = match.get("goal", "?")
                self._notify(
                    f"[{conf.upper()}] {goal}",
                    reasoning[:200],
                )
            elif not matched:
                summary = match.get("signal_summary", "")[:40]
                skip_reasons.append(summary)

        # Single notification summarizing all skips
        if skip_reasons and not actual_matches:
            self._notify(
                f"Observed {len(skip_reasons)} signals, no goal match",
                "; ".join(skip_reasons)[:200],
            )
        elif skip_reasons:
            self._notify(
                f"Matched {len(actual_matches)}, skipped {len(skip_reasons)}",
                "; ".join(r.get("signal_summary", "")[:30] for r in actual_matches)[:200],
            )

        # Route actual matches to the correct scope's hot buffer
        high_confidence_scopes: set[tuple[str, str | None]] = set()

        # Track matched signal IDs so they don't appear in unmatched history
        for s in batch:
            for m in actual_matches:
                if m.get("signal_summary", "") in s.text or s.text[:30] in m.get("signal_summary", ""):
                    self.matched_signal_ids.add(s.id_key)

        for match in actual_matches:
            scope_key = self._parse_scope(match.get("scope", "personal"))
            try:
                store = self.scope_manager.get_store(*scope_key)
            except (ValueError, FileNotFoundError):
                log.warning("Scope %s not found, skipping match", scope_key)
                continue

            # Append to hot buffer
            entry = (
                f"[{match.get('source', '?')}] "
                f"({match.get('confidence', '?')}) "
                f"goal={match.get('goal', '?')}: "
                f"{match.get('signal_summary', '')}"
            )
            if match.get("action"):
                entry += f" -> ACTION: {match['action']}"
            store.append_to_hot_buffer(entry)

            if match.get("confidence") == "high":
                high_confidence_scopes.add(scope_key)
                self._notify(
                    f"[{match.get('goal', '?')}]",
                    match.get("action") or match.get("signal_summary", ""),
                )

        # Trigger action prediction for high-confidence scopes
        self.phase = "PREDICTING"
        for scope_key in high_confidence_scopes:
            await self._predict_actions(scope_key)

        self.phase = "IDLE"

    async def _predict_actions(self, scope_key: tuple[str, str | None]) -> None:
        """Trigger action prediction for a specific scope."""
        try:
            store = self.scope_manager.get_store(*scope_key)
            goals_text = store.read_goals()
            memory_text = store.read_memory()
            hot_buffer = store.read_hot_buffer()

            # Build signals from hot buffer lines
            signals: list[dict] = []
            for line in hot_buffer.strip().split("\n"):
                if line.strip():
                    signals.append({"signal_summary": line, "source": "buffer"})

            actions_md = await self.gemini.predict_actions(
                goals_text, memory_text, signals
            )
            store.update_actions(actions_md)
            log.info("Updated actions for scope %s", scope_key)
        except Exception:
            log.exception("Error predicting actions for scope %s", scope_key)

    async def _compact_cycle(self) -> None:
        """Compact hot buffers into memory entries."""
        self.phase = "RECORDING"

        for scope_type, name in self.scope_manager.list_scopes():
            store = self.scope_manager.get_store(scope_type, name)
            hot_buffer = store.read_hot_buffer()
            if not hot_buffer.strip():
                continue

            log.info("Compacting hot buffer for scope (%s, %s)", scope_type, name)
            goals_text = store.read_goals()
            memory_text = store.read_memory()

            try:
                new_memory, updated_actions = await self.gemini.compact_buffer(
                    hot_buffer, memory_text, goals_text
                )

                # Append new memory entries
                if new_memory.strip():
                    existing = store.read_memory()
                    store.update_memory(existing.rstrip() + "\n\n" + new_memory.strip() + "\n")

                # Update actions
                if updated_actions.strip():
                    store.update_actions(updated_actions)

                # Clear the hot buffer
                store.clear_hot_buffer()
                log.info("Compacted scope (%s, %s)", scope_type, name)
            except Exception:
                log.exception("Error compacting scope (%s, %s)", scope_type, name)

        self.last_compact_time = datetime.now(timezone.utc)
        self.phase = "IDLE"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_scope(scope_str: str) -> tuple[str, str | None]:
        """Parse a scope string like 'projects/workagents' into ('projects', 'workagents')."""
        if "/" in scope_str:
            parts = scope_str.split("/", 1)
            return (parts[0], parts[1])
        return (scope_str, None)

    @staticmethod
    def _notify(title: str, body: str) -> None:
        """Send a macOS notification via osascript through Terminal."""
        import subprocess

        # Strip all quotes and special chars that break osascript
        safe_title = title[:100].replace('"', '').replace("'", "").replace("\\", "").replace("\n", " ")
        safe_body = body[:200].replace('"', '').replace("'", "").replace("\\", "").replace("\n", " ")

        try:
            subprocess.run(
                [
                    "osascript", "-e",
                    f'display notification "{safe_body}" with title "work" subtitle "{safe_title}" sound name "Glass"',
                ],
                capture_output=True, timeout=5,
            )
        except Exception:
            log.exception("Notification failed")

    @staticmethod
    def _send_imessage(phone: str, message: str) -> None:
        """Send an iMessage to a phone number."""
        import subprocess
        try:
            script = f'''
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant "{phone}" of targetService
                send "{message}" to targetBuddy
            end tell
            '''
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=10,
            )
        except Exception:
            log.exception("iMessage send failed")

    def stop(self) -> None:
        self.running = False
