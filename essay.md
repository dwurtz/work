# The Language of Productivity

Most productivity tools ask the same question: what did you do today? They count tasks completed, hours logged, messages sent. They produce dashboards full of motion. But motion is not progress, and the gap between the two is where most productivity is actually lost.

Consider a Monday. You wake up, scan your inbox, respond to three emails, join two calls, review a PR, and spend forty minutes in Slack. By any standard metric you were productive. But productive toward what? One of those emails was stalling an investor who needs an answer by Wednesday. One of those calls was a status meeting that could have been a doc. The PR review was for a feature that no longer aligns with what the team decided last Thursday. And the Slack messages -- half were about a goal you set last week, and you didn't even notice.

Activity is legible. Intention is not. And until a system can reason about intention, it's just counting noise.

## Goals as the unit of work

Every action is in service of something. An email is never just "doing email." It might be closing a deal, resolving a conflict, buying time, or maintaining a relationship. A calendar event isn't "having a meeting" -- it's advancing a hiring decision, aligning on a product direction, or keeping a client from churning.

The problem is that traditional productivity systems treat all emails as email and all meetings as meetings. They see the channel, not the purpose. This is like measuring a carpenter's productivity by counting hammer swings. You need to know what they're building.

Goals are the unit of work. Not tasks -- tasks are fragments of goals, often so decomposed that they've lost their meaning. "Update spreadsheet" tells you nothing. "Ensure the fundraise model reflects the new revenue projection before the Wednesday partner meeting" tells you everything. The goal contains the deadline, the dependency, the stakes, and the audience. The task is just the leftover.

We built `work` around this idea: everything the system observes, everything it records, everything it suggests flows through the lens of goals. Not tasks. Not time blocks. Goals.

## The problem with implicit goals

Here's the hard part: most goals are never written down.

They exist in the space between your calendar and your anxiety. You know you need to close the Series A, but the sub-goals -- prepare the data room, follow up with the partner at Sequoia, make sure the revenue numbers in the deck match the model -- live in your head. They shift mid-week when new information arrives. They depend on other people's unwritten goals, like whether your co-founder has actually finished the technical diligence answers they said they'd have by Friday.

This is why "just write down your goals" doesn't work as advice. Goals are dynamic, contextual, and deeply entangled with other people. By the time you've written them down in a project management tool, they've already changed. And nobody goes back to update them, because the update itself has no value -- it's pure overhead.

What you need isn't another place to write goals. You need a system that can infer them from what you're already doing, and then hold them steady enough to reason about.

## Reading signals, not creating forms

The instinct in software is always to create a form. Want to track goals? Here's a goal-setting template. Want to know what someone's working on? Have them fill out a standup report.

Forms are where motivation goes to die. Every form is a tax on the person filling it out, and the return on that tax is almost always captured by someone else -- a manager, a dashboard, a compliance process. The person doing the work gets nothing back.

So we took the opposite approach. The `work` monitor reads signals that people already produce. It watches iMessage and WhatsApp -- not to surveil, but to notice. Coach Rob's message about moving Tuesday gymnastics to Thursday? That's a signal against your personal "kids' schedule" goal. An investor email that arrives while you're deep in a code review? That's a signal against your fundraise goal, and the system notes it without interrupting you.

The signal collector pulls from iMessage, WhatsApp, Chrome tabs, clipboard contents, active app windows, and periodic screenshots. Every two seconds, it sweeps these sources for new data. It reads the chat databases directly. It captures what's on your screen when you switch contexts. It notices when you copy a URL or a snippet of text. None of this requires a form, a standup, or a status update. You just work. The system watches.

This is ambient observation, not manual input. And it matters because the signals people naturally produce are far richer than anything they'd bother to type into a text box. The half-drafted message you deleted tells us something. The document you opened three times without editing tells us something. The Slack thread you keep returning to tells us something. These are the real signals of intention.

## The three-file system as a language

The core of `work` is three markdown files, repeated at every scope:

- **memory.md** -- who I am and what I know. Facts, decisions, context that persists.
- **actions.md** -- what I'm doing right now. Predicted next steps, ranked by priority.
- **goals.md** -- what I'm trying to accomplish. The north stars that give everything else meaning.

That's it. Three files. No database schema, no proprietary format, no API-only access. Markdown files you can open in any text editor.

If you've used Claude Code, you've already seen this pattern. `CLAUDE.md` is a context file that tells an AI agent who you are, what your project is about, and how you like to work. It's a shared language between human and machine, written in prose, version-controllable, and editable by both sides.

We took that pattern and extended it. Where `CLAUDE.md` gives a code agent context about a codebase, the three-file system gives a productivity agent context about a life. Memory is the accumulated knowledge -- like `CLAUDE.md`'s project conventions, but for everything. Actions are the working set -- like a code agent's current task list. Goals are the why -- the thing `CLAUDE.md` never quite captures because code agents don't need to know why you're building the feature, only how.

Productivity agents need the why. It's the whole point.

## From individual clarity to team alignment

Three files at one scope is personal clarity. Three files at three scopes is organizational alignment.

The scoping system in `work` operates at three levels: personal, project, and org. Your personal scope has your goals -- health, family, finances, whatever matters to you outside of work. Each project scope has that project's goals, memory, and actions. The org scope captures company-level objectives.

When one person's goals are opaque, it's a personal problem. When a team's goals are opaque to each other, it's organizational dysfunction. Most companies "solve" this with OKRs -- quarterly goal-setting exercises that produce documents nobody reads after week two. The goals are written in a vacuum, disconnected from daily work, and stale before the quarter is half over.

The scoping system makes goals legible across levels because they're continuously updated by real signals. When your project's goals change because a key hire fell through, the system captures that from the signals -- the recruiter's message, the calendar cancellation, the Slack conversation -- and updates the project memory. When the org goal shifts because a competitor launched, the signals flow through and the actions.md files across every project scope reflect the new reality.

This isn't top-down goal alignment. It's emergent alignment from shared observation.

## The compaction principle

Raw signals are noise. The monitor captures everything, but everything is too much.

This is where the compaction loop comes in. Every hour, the system takes the hot buffer -- the raw stream of timestamped signals that have been matched to goals -- and distills it. An LLM reads the buffer against existing memory and goals, and decides what matters. Decisions made, commitments given, deadlines set, status changes -- these get promoted to memory. Routine browsing, duplicate signals, ephemeral UI state -- these get discarded.

This is how human memory works. You don't remember every word of a conversation. You remember that your co-founder committed to finishing the diligence answers by Friday, that the investor seemed warm but wants to see updated metrics, and that the new hire's start date is April 15th. The facts, not the noise.

The hot buffer is perception. Memory is knowledge. The compaction loop is the process that turns one into the other. And it runs continuously, so memory stays current without anyone having to maintain it.

The architecture is explicit about this: `.hot_buffer.md` is a hidden file, a scratch pad, the system's short-term memory. `memory.md` is the durable record. The buffer fills up, gets compacted, gets cleared. Memory accumulates. Over weeks and months, memory.md becomes a rich, LLM-curated history of what actually happened -- not what was planned, not what was reported, but what the signals revealed.

## Cross-scope conflict detection

The real power of scoped goals isn't just clarity within a scope. It's the ability to detect conflicts across scopes.

You set a personal goal to be home for dinner by 6pm three nights a week. You also have a project goal to ship a feature by Friday. On Wednesday afternoon, the monitor notices: your project's hot buffer is full of signals suggesting the feature is behind -- a PR was rejected, a dependency broke, the designer is out sick. Meanwhile, your personal scope shows Coach Rob moved gymnastics to Thursday. Two scopes, two goals, one finite resource: your time on Thursday evening.

A single-scope system can't see this. Your project management tool doesn't know about gymnastics. Your family calendar doesn't know about the feature deadline. But `work` sees both, because all goals from all scopes are loaded together when the system reasons about signals. The `all_goals()` method concatenates every goal across every scope into a single context window. When a signal arrives, it's matched against everything.

This is where the system graduates from personal productivity to something more interesting: a coherent model of competing demands across every dimension of your life and work.

## The monitor as perception, the agent as judgment

There's an architectural decision in `work` that mirrors something true about human cognition: perception is cheap and constant, but judgment is expensive and intermittent.

The monitor loop uses Gemini 2.0 Flash -- fast, cheap, always running. Every fifteen seconds, it takes the accumulated signals and matches them against goals. This is peripheral awareness. It's the part of your brain that notices a name in your peripheral vision while you're reading something else. It doesn't need to be brilliant. It needs to be fast and always on.

When the monitor finds a high-confidence match -- multiple corroborating signals pointing at a concrete action -- it escalates. The prediction model kicks in, a more capable model that synthesizes goals, memory, and signals into a ranked action plan. And when you actually sit down and talk to the agent, it uses the most capable model available: Gemini 2.5 Pro. Slow, expensive, thoughtful.

This two-tier architecture (three-tier, really: Flash for matching, 2.5 Flash for prediction, 2.5 Pro for conversation) isn't just a cost optimization. It's a design principle. You don't bring your full attention to everything. You shouldn't. Most signals deserve a glance, not a stare. The system mirrors this by allocating intelligence proportionally -- cheap perception for the fire hose of daily signals, expensive judgment only when it matters.

## Why this, why now

We built this because we needed it. Not as a product thesis or a research project, but because the experience of modern knowledge work is one of drowning in signals with no way to connect them to what matters.

The pieces are finally available. LLMs can read natural language signals and match them to natural language goals -- something that was impossible two years ago. Structured output means the system can reason in JSON and write in markdown without brittle parsing. Multimodal models can read screenshots as easily as text. And the models are cheap enough to run continuously -- a monitor loop burning Flash tokens all day costs less than a cup of coffee.

The three-file system works because it's simple enough to understand and powerful enough to compose. Memory, actions, goals. At every scope. Connected by a continuous loop of observation, matching, compaction, and prediction. No forms. No dashboards. Just three files that get smarter every hour.

Productivity was never about doing more. It was about knowing what to do. The gap between activity and intention is closeable now -- not with better task managers, but with systems that can read the language of work as it actually happens and connect it back to what you're trying to accomplish.

That's what `work` does. It watches, it reasons, it remembers, and it tells you what you already knew but couldn't see: what matters, what's next, and where the conflicts are.
