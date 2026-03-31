# work

A productivity agent CLI that monitors your desktop activity, matches signals to your goals, and helps you stay focused. Powered by Gemini. Think "Claude Code, but for productivity instead of coding."

`work` runs a background monitor that watches your messages, browser tabs, clipboard, and screen. It matches what it sees to goals you define, records what matters, predicts next actions, and compacts everything into durable memory. You can also chat with it interactively -- it knows your goals, your recent activity, and what needs attention.

## How it works

### The three-file system

Every scope has three markdown files:

| File | Purpose |
|---|---|
| `goals.md` | What you're trying to accomplish. Defined by you, referenced by the agent. |
| `actions.md` | Predicted next actions. Auto-generated from signals and goals. Regenerated on each match cycle. |
| `memory.md` | Durable facts. Compacted from the hot buffer hourly. Decisions, commitments, deadlines, status changes. |

There's also a hidden `.hot_buffer.md` that accumulates raw signal matches between compaction cycles.

### Three scopes

Scopes organize your context:

- **personal** -- single scope, no sub-name needed. `~/.work/personal/`
- **projects** -- one directory per project. `~/.work/projects/<name>/`
- **org** -- one directory per organization. `~/.work/org/<name>/`

Each scope gets its own independent set of three files. The monitor matches signals across all scopes simultaneously and routes matches to the correct scope.

### The monitor loop

The monitor runs three concurrent cycles:

```
Observe (every 2s)     Match (every 15s)         Compact (every 1h)
  |                      |                          |
  | collect signals      | send pending signals     | read hot buffer
  | from all sources     | + all goals to Gemini    | + existing memory
  | deduplicate          | get match array back     | + goals
  | add to pending       | route to scope buffers   | ask Gemini to extract
  |                      | if high-confidence:      |   durable facts
  |                      |   predict actions         | append to memory.md
  |                      |                           | update actions.md
  |                      |                           | clear hot buffer
```

## Quick start

### Prerequisites

- macOS (required -- uses macOS-specific APIs for screenshots, AppleScript, iMessage/WhatsApp databases)
- Python 3.10+
- A Gemini API key (`GEMINI_API_KEY` or `GOOGLE_API_KEY` environment variable)

### Installation

```bash
cd /path/to/work
pip install -e .
```

### Setup

```bash
# Set your API key
export GEMINI_API_KEY="your-key-here"

# Create your first goal
work goals add
# Follow the interactive prompts:
#   Scope: personal (auto-created if missing)
#   Goal name: e.g. "Ship v2 launch"
#   Description: e.g. "Get version 2.0 out the door by April 15"
#   Key people: e.g. "Alice, Bob"

# Start the monitor with Rich display
work monitor

# Or run interactive mode (monitor + chat)
work
```

## CLI reference

### `work` (interactive mode)

Starts the monitor in the background and opens an interactive chat session. The agent has full context from all scopes -- goals, memory, recent signals, and predicted actions.

```bash
work
# you> what should I focus on today?
# you> what happened with the product launch yesterday?
# you> quit
```

### `work monitor [--daemon]`

Runs the monitor loop in the foreground with a Rich terminal display showing live signal flow and goal matches.

```bash
work monitor          # foreground with Rich display
work monitor --daemon # headless, logging only
```

The display shows two panels: recent signals (color-coded by source) and goal matches (color-coded by confidence: dim=low, yellow=medium, green=high).

### `work goals` / `work goals add`

```bash
work goals      # list all goals across all scopes
work goals add  # interactive goal creation
```

Goals are stored as markdown sections in `goals.md` with a name, description, and key people list.

### `work actions`

```bash
work actions    # show predicted next actions across all scopes
```

Displays the auto-generated actions.md files. These are regenerated whenever high-confidence matches occur and during compaction.

### `work memory`

```bash
work memory     # show durable memory across all scopes
```

Displays compacted memory entries -- facts the agent decided were worth remembering long-term.

### `work standup`

```bash
work standup    # morning briefing
```

Generates a standup report using Gemini 2.5 Pro. Covers each scope and goal: recent activity, current status, what needs attention, and commitment-action gaps.

### `work status`

```bash
work status     # monitor status and signal counts
```

Shows work home path, number of scopes, and per-scope stats (goal count, hot buffer entries, memory/actions sizes).

### Flags

```bash
work -v <command>   # enable debug logging (all commands)
```

## Architecture

### Directory structure

```
~/.work/
  personal/
    goals.md
    actions.md
    memory.md
    .hot_buffer.md
  projects/
    myproject/
      goals.md
      actions.md
      memory.md
      .hot_buffer.md
  org/
    mycompany/
      goals.md
      actions.md
      memory.md
      .hot_buffer.md
```

### Source layout

```
src/work/
  __main__.py          CLI entry point, argument parser, all subcommands
  config.py            Constants, paths, model names, timing intervals
  context/
    store.py           ContextStore -- read/write the three files + hot buffer
    scopes.py          ScopeManager -- discover and manage all scopes
  signals/
    types.py           Signal dataclass (source, sender, text, timestamp, id_key)
    collector.py       SignalCollector -- orchestrates all sources, deduplication
    imessage.py        iMessage collector (reads chat.db via SQLite)
    whatsapp.py        WhatsApp collector (reads ChatStorage.sqlite via SQLite)
    chrome.py          Chrome tab collector (AppleScript via osascript)
    clipboard.py       Clipboard collector (pbpaste)
    screenshot.py      Screenshot capture with perceptual hash diffing
    active_app.py      Active app/window title (AppleScript via osascript)
  monitor/
    loop.py            MonitorLoop -- three concurrent cycles (signal/match/compact)
    display.py         Rich terminal display for live monitoring
  agent/
    engine.py          AgentEngine -- interactive chat with full scope context
    router.py          Scope detection from user messages (keyword matching)
  llm/
    gemini.py          GeminiClient -- all Gemini API calls (match, vision, predict, compact, chat)
```

### Data flow

```
 Signal Sources                    MonitorLoop                      Storage
 +-----------+                                                    +----------+
 | iMessage  |--+                                                 |          |
 | WhatsApp  |--+   collect    +----------+   match    +-------+  | goals.md |
 | Chrome    |--+------------->| pending  |----------->| Gemini|  |          |
 | Clipboard |--+   (2s)      | signals  |   (15s)    | Flash |  +----------+
 | Screenshot|--+              +----------+            +---+---+
 | ActiveApp |--+                                          |
 +-----------+                                             |
                                                    match results
                                                    (scope, goal,
                                                     confidence)
                                                           |
                              +----------------------------+
                              |
                    +---------v----------+
                    | .hot_buffer.md     |  (per scope)
                    +----+----------+----+
                         |          |
            high-conf    |          |  compact (1h)
            triggers     |          |
                    +----v----+ +---v-------+
                    | predict | | compact   |
                    | actions | | to memory |
                    | (Flash) | | (Flash)   |
                    +----+----+ +-----+-----+
                         |            |
                    +----v----+ +-----v-----+
                    |actions.md| |memory.md  |
                    +----------+ +-----------+
```

## The three-file system

### goals.md

Defined by the user. The agent reads goals but never modifies them autonomously.

Structure:

```markdown
# Goals

---

## Ship v2 launch

Get version 2.0 out the door by April 15. Focus on payment integration and onboarding flow.

**Key People:**
- Alice
- Bob

---

## Hire senior engineer

Fill the senior backend role. Target start date May 1.

**Key People:**
- Carol (recruiter)
```

Key people matter -- the agent uses them to match signals. A message from "Alice" automatically gets higher relevance to goals where Alice is listed.

### actions.md

Auto-generated. Overwritten by the agent after high-confidence matches and during compaction. Structure varies but typically:

```markdown
# Predicted Next Actions

## Ship v2 launch (HIGH)
- Alice sent updated designs -- review and approve by EOD
- Payment integration PR still open -- Bob needs to merge
- **Gap detected**: Bob committed to finishing tests on Monday, no follow-up seen

## Hire senior engineer (NORMAL)
- No new signals
```

### memory.md

Append-only (via compaction). Contains durable facts extracted from signals:

```markdown
# Memory

### 2026-03-28 -- imessage
- Alice confirmed final designs are done
- Payment flow requires Stripe webhook setup

### 2026-03-29 -- chrome
- Bob's PR #142 adds payment tests, currently 3 failing
```

### Hot buffer and compaction

The `.hot_buffer.md` file accumulates timestamped signal matches between compaction cycles:

```
[2026-03-29T14:30:00Z] [imessage] (high) goal=Ship v2 launch: Alice sent updated wireframes -> ACTION: Review designs
[2026-03-29T14:32:00Z] [chrome] (medium) goal=Ship v2 launch: Viewing PR #142 on GitHub
```

Every hour, Gemini compacts the hot buffer: extracts durable facts into memory.md, updates actions.md, and clears the buffer. This prevents unbounded growth while preserving important information.

## Signal sources

| Source | Method | What it captures | Permission needed |
|---|---|---|---|
| **iMessage** | SQLite read of `~/Library/Messages/chat.db` | Messages from the last 5 minutes (sender, text, timestamp) | Full Disk Access |
| **WhatsApp** | SQLite read of WhatsApp's `ChatStorage.sqlite` | Messages from the last 5 minutes (sender, text, timestamp) | Full Disk Access |
| **Chrome tabs** | AppleScript via `osascript` | All open tab titles and URLs | Automation (Chrome) |
| **Clipboard** | `pbpaste` subprocess | Current clipboard text content | None |
| **Screenshot** | `screencapture -x -C` + perceptual hash | Screen capture when context changes (app/window switch) | Screen Recording |
| **Active app** | AppleScript via `osascript` (System Events) | Frontmost app name and window title | Accessibility |

All signals are truncated to 500 characters. Deduplication uses per-signal `id_key` values (hash-based for messages/clipboard, URL-based for Chrome, timestamp-based for screenshots).

Screenshots use perceptual hashing (imagehash/Pillow) to avoid capturing duplicate frames. A screenshot is only taken when the active app or window title changes AND the new app is in the `SCREENSHOT_APPS` allowlist. Apps in `IGNORED_APPS` (Terminal, Python, Activity Monitor) are never captured.

## Gemini models

| Model | Config constant | Used for | Why |
|---|---|---|---|
| `gemini-2.0-flash` | `MONITOR_MODEL` | Signal-to-goal matching | Cheapest and fastest. Runs every 15 seconds. JSON output mode, temp 0.2. |
| `gemini-2.5-flash` | `VISION_MODEL` | Screenshot analysis | Multimodal input (image + text). Extracts app, content summary, key details. |
| `gemini-2.5-flash` | `PREDICT_MODEL` | Action prediction, buffer compaction | Mid-tier. Generates markdown (actions) and JSON (compaction). Temp 0.3. |
| `gemini-2.5-pro` | `AGENT_MODEL` | Interactive chat | Highest quality for user-facing conversation. Temp 0.5. |

## macOS permissions

`work` requires the following macOS permissions for the process running it (typically Terminal.app or your terminal emulator):

| Permission | Why | How to grant |
|---|---|---|
| **Full Disk Access** | Read iMessage (`chat.db`) and WhatsApp (`ChatStorage.sqlite`) databases | System Settings > Privacy & Security > Full Disk Access > add your terminal |
| **Accessibility** | Read frontmost app name and window title via System Events | System Settings > Privacy & Security > Accessibility > add your terminal |
| **Screen Recording** | Capture screenshots via `screencapture` | System Settings > Privacy & Security > Screen Recording > add your terminal |
| **Automation (Chrome)** | Read Chrome tab titles and URLs via AppleScript | Prompted automatically on first use; or System Settings > Privacy & Security > Automation |

If a permission is missing, the corresponding collector will fail silently (logged at exception level with `-v`). The monitor continues running with whatever sources are available.

## Configuration

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` or `GOOGLE_API_KEY` | Yes | -- | Gemini API authentication. The `google-genai` SDK checks both. |
| `WORK_HOME` | No | `~/.work` | Root directory for all scope data. |

### Timing constants (config.py)

| Constant | Default | Description |
|---|---|---|
| `SIGNAL_INTERVAL` | 2s | How often signals are collected |
| `MATCH_INTERVAL` | 15s | How often pending signals are sent to Gemini for matching |
| `SCREENSHOT_INTERVAL` | 3s | Screenshot context-change check interval |
| `COMPACT_INTERVAL` | 3600s (1h) | How often hot buffers are compacted into memory |

### App lists (config.py)

- `SCREENSHOT_APPS` -- Apps that trigger screenshot capture on focus. Browsers, messaging apps, email, calendar, etc.
- `IGNORED_APPS` -- Apps that are never screenshotted or tracked as active. Terminal, Python, Activity Monitor.

To customize, edit `src/work/config.py` directly.

## Privacy

- **Screenshots are ephemeral.** Captured to a temp file, analyzed by Gemini's vision model, then immediately deleted. Only the text summary persists in the hot buffer.
- **All data stays local.** Goals, memory, actions, and hot buffers live in `~/.work/` as plain markdown files. Nothing is uploaded to any server except Gemini API calls for LLM processing.
- **Messages are read, not stored verbatim.** iMessage and WhatsApp text is truncated to 500 characters, hashed for deduplication, and only the LLM's summary (not the raw text) makes it into memory.
- **No message sending.** The agent reads signals. It never sends messages, modifies files outside `~/.work/`, or takes actions on your behalf.
- **Gemini API calls.** Signal text, goals, and memory content are sent to Google's Gemini API for processing. Review Google's [Gemini API data usage policies](https://ai.google.dev/terms) if this matters for your use case.
