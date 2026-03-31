# The Language of Productivity

You spend an hour reviewing a pull request on a service that, in a meeting you weren't invited to, was decided to be deprecated. You draft an investor update using metrics your co-founder quietly revised last night. You prepare for a customer call that got rescheduled, but the notification went to a Slack channel you muted.

None of this is laziness. The work was real. The effort was genuine. It just wasn't connected to what actually needed to happen.

We don't have a productivity problem. We have a goal alignment problem. And it doesn't live at the level of the individual — it lives in the space between people, projects, and the organizations that contain them.

## A new category

This isn't about building a better task manager. Task managers assume you already know what to work on. The hard problem isn't organization — it's knowing whether the thing you're doing right now is the thing that matters most.

No existing tool answers that question. Project management tools track what was planned. Time trackers measure what was done. Communication tools surface what's urgent. None of them connect activity to intention. None of them can tell you that the PR you're reviewing is for a system the team decided to kill, because the decision happened in a thread you didn't see and the project board hasn't been updated.

We're inventing something that doesn't exist yet: a system that understands what you're trying to accomplish — and what your team and organization are trying to accomplish — and can tell you, in real time, whether it all lines up.

## Goals as the underbelly

Goals are the invisible infrastructure beneath all useful work.

When goals are clear and shared, teams move fast. A developer reviews a PR knowing the feature ships Thursday because sales has a demo Friday, which she knows because the project goal is explicit. She catches a bug not because she's thorough but because she understands what the code needs to do in the demo and this edge case would break it. The goal shaped her judgment.

When goals are absent or misaligned, you get a room full of smart people pulling in different directions — each one productive by their own measure, collectively going nowhere. The developer approves a well-written PR on a service that's about to be deprecated. She spent an hour not because she was careless, but because nobody connected her work to the team's current direction.

The difference isn't talent or effort. It's whether goals were legible to the person doing the work.

## Inferring goals from behavior

Here's the uncomfortable truth: people don't write their goals down. OKRs get written once a quarter and forgotten by week three. Goal-tracking apps collect dust. This isn't a discipline problem — it's a design problem. Writing goals is overhead, maintaining them is more overhead, and the return flows mostly to managers and dashboards, not to the person doing the work.

But goals still exist. They live in behavior.

You opened the same Linear ticket four times this week without making progress — that's a blocked goal. You have three calendar events with "fundraise" in the title — that's an active goal. You drafted an email to five investors and didn't send it — that's a goal with friction. Past conversations carry signal too: "I'll have the pitch deck done by Wednesday" is a commitment with a deadline and an audience.

The system should infer goals from these signals, not ask you to type them into a form. The things you do, the messages you send, the tabs you keep open, the documents you revisit — these are all evidence of what you're trying to accomplish.

## Every entity is an agent. Every agent is the same shape.

This is the core idea. Not just individuals — projects and organizations are agents too, and they all have the same structure:

- **goals.md** — what this entity is trying to accomplish
- **memory.md** — what this entity has observed, filtered through its goals
- **actions.md** — what this entity should do next, derived from memory

Three files. One loop. Every scope.

An individual agent observes your desktop — iMessage, WhatsApp, Chrome tabs, clipboard, screenshots. It matches signals against your goals, records what matters, and derives next actions.

A project agent does the same thing, but its signals come from the individual agents on the project. When Sarah says "I'll send the vendor proposal by Friday" in a meeting, her individual agent records it. That memory pushes up to the project agent, which now knows there's a commitment with a deadline. When Friday passes with no proposal, the project agent notices the gap and generates an action: flag the delay.

An organization agent sits above projects. Its signals come from project agents. It sees cross-project patterns — two projects competing for the same engineer's time, a strategic shift that invalidates a project's assumptions, a dependency that's creating systemic risk. It doesn't see individual-level detail. It sees what matters at the organizational level.

The same three files. The same observe-match-remember-decide loop. Applied recursively at every level of scope.

## Memories flow up. Goals flow down.

The hierarchy isn't just structural — it's a communication protocol. Information flows in two directions:

**Memories flow up.** An individual observes something goal-relevant and records it. If it matters to the project, it gets pushed up to the project's memory. If it matters to the organization, it gets pushed further. Each push is filtered — only facts propagate. "Sarah seems stressed" doesn't flow up. "Vendor proposal delayed 3 days" does.

**Goals flow down.** The organization sets strategic direction. Projects translate that into milestones. Individuals receive actions derived from project goals. When the org goal shifts because a competitor launched, the shift propagates down through project goals into individual actions. The developer who was about to review that PR on the deprecated service gets a signal: this goal has changed, this work is no longer aligned.

There are five operations in this protocol:

1. **Push Memory** — individual to project, project to org. "Sarah committed to X by Friday."
2. **Push Action** — org to project, project to individual. "You need to review the Acme terms."
3. **Peer Query** — same level. "Status on vendor proposal?"
4. **Escalate** — any agent to its parent. "Project A is at risk — 3 blockers and a missed milestone."
5. **Confirm** — any agent to any agent. "Vendor proposal received. Commitment resolved."

This is how a commitment travels through the system: Sarah's agent hears her make a promise in a meeting. It records the commitment. It pushes the memory up to the project agent. The project agent creates an action to monitor the deadline. When the deadline passes without delivery, the project agent escalates to the org agent. At every step, the same three files, the same loop.

## Privacy is structural

When memories flow between agents, sensitive content must never propagate. This isn't a policy — it's built into the architecture. The filter runs on every write to every memory.md.

What never gets recorded or propagated: performance assessments, interpersonal conflicts, personal circumstances, tone and sentiment. "Sarah is underperforming" is never written. "Sarah seems frustrated" is never pushed up.

What does propagate: commitments, status updates, blockers, deadlines, decisions. Facts, not feelings. The project agent knows the proposal is late. It doesn't know — and shouldn't know — why.

This is what makes the system safe to deploy. The org agent can detect that a project is at risk without ever seeing an individual's personal messages. The project agent can track commitments without surveilling the people making them. Privacy isn't an afterthought bolted onto the system. It's a structural property of how memory flows between scopes.

## The compaction principle

Raw signals are noise. The monitor captures thousands of data points per hour — app switches, tab changes, clipboard contents, messages. Most of it is meaningless.

The compaction loop turns perception into knowledge. Every hour, the system reads the hot buffer of raw signals against goals and memory, and makes a judgment: what here is worth remembering? A commitment was made — that goes into memory. A deadline was mentioned — that updates actions. You browsed the same page four times without acting — that's a pattern worth noting. Everything else gets dropped.

This is how human memory works. You don't remember every word of a conversation. You remember that your co-founder committed to finishing the diligence answers by Friday, that the investor seemed warm but wants updated metrics, that the new hire starts April 15th. Facts, not noise.

Over weeks, memory.md becomes a curated history of what actually happened — not what was planned, not what was reported, but what the signals revealed.

## Perception is cheap. Judgment is expensive.

The architecture splits intelligence into tiers, mirroring how human attention works.

The monitor loop runs a fast, inexpensive model every fifteen seconds, scanning signals against goals. This is peripheral awareness — the part of your brain that notices a name in your peripheral vision while reading something else. It doesn't need to be brilliant. It needs to be fast and always on.

When signals match with high confidence, a more capable model synthesizes goals, memory, and signals into a ranked action plan. And when you sit down and talk to the agent directly, the most capable model available engages — slow, expensive, thoughtful.

Most signals deserve a glance, not a stare. The system allocates intelligence proportionally. You shouldn't bring your full attention to everything. Neither should your tools.

## What this makes possible

Imagine an organization where every person, every project, and the organization itself each have a living, continuously-updated model of what they're trying to accomplish, what they know, and what they should do next. Where a strategic decision at the top propagates through project goals into individual actions within hours, not quarters. Where a blocker discovered by one person surfaces as a risk at the project level before anyone has to escalate it manually. Where two projects competing for the same person's Thursday afternoon get flagged before Thursday.

This isn't a fantasy about AI replacing managers. It's a system for making the invisible visible. The goals exist. The commitments exist. The conflicts exist. They're just locked in people's heads, scattered across Slack threads and calendar events and half-read emails. The three-file system, applied recursively at every scope, with memories flowing up and goals flowing down, is a way to surface what everyone already knows but nobody can see.

We didn't set out to build a better productivity tool. We set out to give people — and the teams and organizations they belong to — a shared language for what matters, what's happening, and what to do about it.

That's the language of productivity.
