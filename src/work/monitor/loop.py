"""MonitorLoop -- main monitoring loop that collects signals and periodically analyzes them."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from work.config import (
    COMPACT_INTERVAL,
    SIGNAL_INTERVAL,
    WORK_HOME,
)
from work.context import ContextStore, ScopeManager
from work.llm import GeminiClient
from work.signals import Signal, SignalCollector

log = logging.getLogger(__name__)


class MonitorLoop:
    """Main monitoring loop: perception (3s) + analysis/compaction (5min)."""

    def __init__(
        self,
        scope_manager: ScopeManager,
        gemini: GeminiClient,
        collector: SignalCollector,
    ) -> None:
        self.scope_manager = scope_manager
        self.gemini = gemini
        self.collector = collector
        self.running = False
        self.display: MonitorDisplay | None = None

        # Stats
        self.signals_collected = 0
        self.matches_found = 0
        self.last_signal_time: datetime | None = None
        self.last_analysis_time: datetime | None = None
        self.phase: str = "IDLE"

    async def run(self, interactive: bool = False) -> None:
        """Main loop. If interactive=False, runs headless (daemon mode)."""
        if interactive:
            from work.monitor.display import MonitorDisplay

            self.display = MonitorDisplay()
            self.display.start()

        self.running = True
        log.info("Monitor loop starting (interactive=%s)", interactive)

        # Launch the two cycles as concurrent tasks
        tasks = [
            asyncio.create_task(self._signal_loop()),
            asyncio.create_task(self._analysis_loop()),
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

    async def _analysis_loop(self) -> None:
        """Run combined analysis + compaction every COMPACT_INTERVAL seconds."""
        await asyncio.sleep(COMPACT_INTERVAL)
        while self.running:
            try:
                await self._analysis_cycle()
            except Exception:
                log.exception("Error in analysis cycle")
            await asyncio.sleep(COMPACT_INTERVAL)

    async def _display_loop(self) -> None:
        """Refresh the Rich display and handle key input."""
        while self.running and self.display:
            self.display.show_status(self.phase)
            self.display.render()

            # Check for key input (non-blocking)
            key = await self._read_key()
            if key:
                if key == "g":
                    # Toggle goals panel
                    self.display.show_goals_panel = not self.display.show_goals_panel
                    if self.display.show_goals_panel:
                        self.display.goals_text = self.scope_manager.all_goals()
                elif key == "0" and self.display.proposed_goals:
                    log.info("Dismissed all proposed goals")
                    self.display.proposed_goals.clear()
                elif key.isdigit() and self.display.proposed_goals:
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
                        # Persist the analyzed signal (not the raw file path)
                        self.collector._persist_signal(analyzed)
                else:
                    processed.append(sig)

            self.signals_collected += len(processed)
            self.last_signal_time = datetime.now(timezone.utc)
            log.info("Collected %d new signals", len(processed))

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

    async def _analysis_cycle(self) -> None:
        """Combined analysis + compaction: match signals, extract facts, update memory/actions."""
        self.phase = "THINKING"

        # 1. Read all unanalyzed signals (since last analysis marker)
        loop = asyncio.get_running_loop()
        signals_text, analysis_marker = await loop.run_in_executor(
            None, self.collector.get_unanalyzed_signals_from_log
        )

        if not signals_text.strip():
            log.info("No recent signals for analysis")
            self.phase = "IDLE"
            return

        # 2. Build goals text from all scopes
        goals_text = self.scope_manager.all_goals()
        if not goals_text.strip():
            log.info("No goals defined; skipping analysis cycle")
            self.phase = "IDLE"
            return

        # 3. Build existing memory text from all scopes
        existing_memories: dict[str, str] = {}
        for scope_type, name in self.scope_manager.list_scopes():
            store = self.scope_manager.get_store(scope_type, name)
            label = f"{scope_type}/{name}" if name else scope_type
            existing_memories[label] = store.read_memory()

        # 4. Call combined analysis
        log.info("Running analysis on recent signals...")
        result = await self.gemini.analyze_and_compact(
            signals_text, goals_text, existing_memories
        )

        # 5. Clear reasoning panel for fresh results
        if self.display:
            self.display.matches_log.clear()

        # 6. Process matches
        matches = result.get("matches", [])
        skips = result.get("skips", [])
        new_facts = result.get("new_facts", [])
        commitments = result.get("commitments", [])
        proposed_goals = result.get("proposed_goals", [])

        self.matches_found += len(matches)
        log.info(
            "Analysis: %d matches, %d skips, %d facts, %d commitments, %d proposed goals",
            len(matches), len(skips), len(new_facts), len(commitments), len(proposed_goals),
        )

        # Show matches in display and notify
        for match in matches:
            if self.display:
                self.display.show_match(match)
            conf = match.get("confidence", "low")
            if conf == "high":
                goal = match.get("goal", "?")
                reasoning = match.get("reasoning", "")
                self._alert(
                    f"[HIGH] {goal}",
                    reasoning[:200],
                )
            elif conf == "medium":
                goal = match.get("goal", "?")
                reasoning = match.get("reasoning", "")
                self._notify(
                    f"[MEDIUM] {goal}",
                    reasoning[:200],
                )

        # Show skips in display
        skip_summaries = []
        for skip in skips:
            if self.display:
                self.display.show_match({
                    "matched": False,
                    "signal_summary": skip.get("signal_summary", ""),
                    "reasoning": skip.get("reasoning", ""),
                    "confidence": "none",
                })
            skip_summaries.append(skip.get("signal_summary", "")[:40])

        # Batch skip notification
        if skip_summaries and not matches:
            self._notify(
                f"Observed {len(skip_summaries)} signals, no goal match",
                "; ".join(skip_summaries)[:200],
            )
        elif skip_summaries and matches:
            self._notify(
                f"Matched {len(matches)}, skipped {len(skip_summaries)}",
                "; ".join(m.get("signal_summary", "")[:30] for m in matches)[:200],
            )

        # 7. Write new facts to memory.md per scope
        self.phase = "RECORDING"
        today = datetime.now().strftime("%Y-%m-%d")
        for fact_entry in new_facts:
            scope_key = self._parse_scope(fact_entry.get("scope", "personal"))
            fact = fact_entry.get("fact", "")
            if not fact:
                continue
            try:
                store = self.scope_manager.get_store(*scope_key)
                existing = store.read_memory()
                new_entry = f"\n### {today}\n- {fact}\n"
                store.update_memory(existing.rstrip() + "\n" + new_entry)
                log.info("Added fact to %s: %s", scope_key, fact[:80])
            except (ValueError, FileNotFoundError):
                log.warning("Scope %s not found for fact, skipping", scope_key)

        # 8. Write commitments to actions.md per scope
        for commitment_entry in commitments:
            scope_key = self._parse_scope(commitment_entry.get("scope", "personal"))
            commitment = commitment_entry.get("commitment", "")
            deadline = commitment_entry.get("deadline")
            if not commitment:
                continue
            try:
                store = self.scope_manager.get_store(*scope_key)
                existing = store.read_actions()
                deadline_str = f" (by {deadline})" if deadline else ""
                new_entry = f"\n- [ ] {commitment}{deadline_str}\n"
                store.update_actions(existing.rstrip() + "\n" + new_entry)
                log.info("Added commitment to %s: %s", scope_key, commitment[:80])
            except (ValueError, FileNotFoundError):
                log.warning("Scope %s not found for commitment, skipping", scope_key)

        # 9. Handle proposed goals
        for pg in proposed_goals:
            log.info("Goal proposed: %s", pg.get("name", "?"))
            if self.display:
                self.display.proposed_goals.append(pg)
                idx = len(self.display.proposed_goals)
                self.display.matches_log.append(
                    f"[bold bright_yellow][ NEW GOAL? ] {pg.get('name', '?')}[/bold bright_yellow]\n"
                    f"  [italic]{pg.get('description', '')}[/italic]\n"
                    f"  [bold bright_yellow]Press {idx} to accept[/bold bright_yellow]"
                )
            self._alert(
                f"New goal? {pg.get('name', '?')}",
                pg.get("description", ""),
            )

        # Build proactive conversation message if anything important happened
        proactive_parts = []
        for match in matches:
            if match.get("confidence") in ("medium", "high"):
                proactive_parts.append(
                    f"**[{match.get('confidence', '?').upper()}] {match.get('goal', '?')}:** "
                    f"{match.get('signal_summary', '')} — {match.get('reasoning', '')}"
                )
                if match.get("action"):
                    proactive_parts.append(f"  → Suggested: {match['action']}")

        for fact in new_facts:
            proactive_parts.append(f"📝 New fact: {fact.get('fact', '')}")

        for commitment in commitments:
            proactive_parts.append(
                f"🤝 Commitment: {commitment.get('commitment', '')}"
                + (f" (due: {commitment['deadline']})" if commitment.get('deadline') else "")
            )

        for pg in proposed_goals:
            proactive_parts.append(
                f"🆕 **New goal detected: {pg.get('name', '?')}** — {pg.get('description', '')}\n"
                f"Say 'yes' to add this goal, or 'no' to dismiss."
            )

        if proactive_parts:
            message = "\n\n".join(proactive_parts)
            self._post_to_conversation(message)

        # Log analysis results
        analysis_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "matches": matches,
            "skips": skips[:10],  # truncate skips to save space
            "new_facts": new_facts,
            "commitments": commitments,
            "proposed_goals": proposed_goals,
        }
        try:
            with open(WORK_HOME / "analysis_log.jsonl", "a") as f:
                f.write(json.dumps(analysis_entry) + "\n")
        except Exception:
            log.exception("Failed to write analysis log")

        # Run goal agents after analysis
        try:
            from work.agent.goal_agent import run_all_goal_agents

            actions_count = await run_all_goal_agents(self.gemini, self.scope_manager)
            if actions_count > 0:
                log.info("Goal agents produced work for %d goals", actions_count)
        except Exception:
            log.exception("Goal agents failed")

        # Save analysis marker so these signals aren't re-analyzed next cycle
        if analysis_marker:
            self.collector.save_analysis_marker(analysis_marker)

        self.last_analysis_time = datetime.now(timezone.utc)
        self.phase = "IDLE"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _post_to_conversation(content: str) -> None:
        """Post a proactive message to the conversation log."""
        import json as _json
        from work.config import WORK_HOME as _wh
        conv_path = _wh / "conversation.json"
        try:
            messages = _json.loads(conv_path.read_text()) if conv_path.exists() else []
            messages.append({
                "role": "agent",
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "proactive": True,
            })
            conv_path.write_text(_json.dumps(messages, indent=2))
        except Exception:
            log.exception("Failed to post to conversation")

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
        safe_msg = message[:300].replace('"', '').replace("'", "").replace("\\", "")
        try:
            script = f'''
            tell application "Messages"
                set targetService to 1st account whose service type = iMessage
                set targetBuddy to participant "{phone}" of targetService
                send "{safe_msg}" to targetBuddy
            end tell
            '''
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, timeout=10,
            )
        except Exception:
            log.exception("iMessage send failed")

    @staticmethod
    def _send_email(subject: str, body: str) -> None:
        """Send an email to yourself via gws gmail."""
        import subprocess
        import json
        import base64

        raw_msg = f"From: david@davidwurtz.com\nTo: david@davidwurtz.com\nSubject: [work] {subject}\n\n{body}"
        encoded = base64.urlsafe_b64encode(raw_msg.encode()).decode()

        try:
            subprocess.run(
                [
                    "gws", "gmail", "users", "messages", "send",
                    "--params", json.dumps({"userId": "me"}),
                    "--json", json.dumps({"raw": encoded}),
                ],
                capture_output=True, timeout=15,
            )
        except Exception:
            log.exception("Email send failed")

    def _alert(self, title: str, body: str) -> None:
        """Send notification via all channels: macOS, iMessage, and email."""
        self._notify(title, body)
        self._send_imessage("david@davidwurtz.com", f"[work] {title}: {body[:200]}")
        self._send_email(title, body)

    def stop(self) -> None:
        self.running = False
