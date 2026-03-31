# The Language of Productivity

Most of what you do at work doesn't matter.

That's not a judgment — it's a structural problem. You spend an hour reviewing a pull request on a service that, in a meeting you weren't invited to, was just decided to be deprecated. You draft a detailed investor update using metrics from a model your co-founder quietly revised last night. You prepare for a customer call that got rescheduled, but nobody told you because the notification went to a Slack channel you muted.

None of this is laziness. It's misalignment. The work was real. The effort was genuine. It just wasn't connected to what actually needed to happen.

We don't have a productivity problem. We have a goal alignment problem.

## A new category

This isn't about building a better task manager or a smarter calendar. Those tools assume you already know what to work on and just need help organizing it. But the hard problem isn't organization — it's knowing whether the thing you're doing right now is the thing that matters most.

No existing tool answers that question. Project management tools track what was planned. Time trackers measure what was done. Communication tools surface what's urgent. None of them connect activity to intention. None of them can tell you that the PR you're reviewing is for a system the team decided to kill, because the decision happened in a thread you didn't see and the project board hasn't been updated yet.

We're not competing with productivity tools. We're building something that doesn't exist yet: a system that understands what you're trying to accomplish and can tell you, in real time, whether what you're doing right now is getting you there.

## Goals are the underbelly

Goals are the invisible infrastructure beneath all useful work. When goals are clear and shared, teams move fast. When they're ambiguous or misaligned, you get a room full of smart people pulling in different directions — each one productive by their own measure, collectively going nowhere.

Think about what happens when goals are working:

A developer opens a PR. She knows the feature ships Thursday because the sales team has a demo Friday, which she knows because the project goal is explicit: close the Acme deal by end of month. She reviews the diff with that context. She catches a bug not because she's thorough but because she understands what the code needs to do in the demo and this edge case would break it. The goal shaped her judgment.

Now think about what happens when goals are absent:

The same developer reviews a different PR. It's well-written code on a well-architected service. She approves it. Two days later she learns in standup that the team decided to deprecate that service and migrate to a new one. The PR was dead on arrival. She spent an hour — not because she was careless, but because nobody connected her work to the team's current direction. The goal existed, but it was locked in someone else's head.

The difference between these two scenarios isn't talent or effort. It's whether goals were legible to the person doing the work.

## Inferring goals from behavior

Here's the uncomfortable truth about goal-setting: people don't do it. OKRs get written once a quarter and forgotten by week three. Goal-tracking apps collect dust. The annual planning doc lives in a Google Drive folder nobody opens.

This isn't a discipline problem. It's a design problem. Writing goals down is overhead. Maintaining them is more overhead. And the return on that overhead flows mostly to managers and dashboards, not to the person doing the work. So people rationally skip it.

But goals still exist. They just live in behavior, not documents.

You opened the same Linear ticket four times this week without making progress — that's a signal of a blocked goal. You have three calendar events with "fundraise" in the title — that's a signal of an active goal. You drafted an email to five investors and didn't send it — that's a signal of a goal with friction. You keep switching between a spreadsheet and a slide deck — that's a signal of two goals competing for your attention.

The system should infer goals from these signals, not ask you to type them into a form. The things you do, the messages you send, the tabs you keep open, the documents you revisit — these are all evidence of what you're trying to accomplish. A system that can read this evidence can maintain a living model of your goals without you lifting a finger.

Past conversations carry goal signal too. When you told your co-founder "I'll have the pitch deck done by Wednesday," that's a commitment — a goal with a deadline and an audience. When your manager said "let's deprioritize the dashboard rewrite," that's a goal being retired. These utterances, scattered across Slack, iMessage, email, and meetings, are the raw material of goal inference. The system should be listening.

## The three-file system

We landed on three files as the core primitive. Not a database, not an API — three markdown files per scope:

- **goals.md** — what I'm trying to accomplish. The north stars.
- **actions.md** — what I'm doing right now. Current commitments, predicted next steps.
- **memory.md** — what I know. Facts, decisions, context that persists.

Goals give meaning. Actions give direction. Memory gives context. Together, they form a complete picture of a person's relationship to their work.

These repeat at three scopes: personal, project, and org. Your personal scope knows about your kids' schedules and your health goals. Your project scope knows about the fundraise and the product roadmap. Your org scope knows about the hiring plan and the company strategy.

The power is in the repetition. The same three files, the same structure, at every level. A signal comes in — an iMessage from Coach Rob about Tuesday gymnastics — and the system routes it to `personal/goals.md` because Coach Rob is listed as a key person under the kids' schedule goal. A Slack message from Jamil about the Gemini API routes to `projects/kinsol/actions.md`. An email from an investor routes to both the project fundraise goal and the org-level funding goal.

If you've used Claude Code, you've seen a version of this. `CLAUDE.md` is a context file that tells an AI agent about a codebase — conventions, architecture, preferences. We took that pattern and extended it from code to life. Where `CLAUDE.md` answers "how does this codebase work?", the three-file system answers "what is this person trying to do, what do they know, and what should they do next?"

## Why alignment breaks

Misalignment isn't malice. It's information asymmetry.

The developer reviewing the dead PR didn't lack skill or motivation. She lacked a single piece of context: the deprecation decision. That context existed — it was in a Slack thread, probably in someone's head, maybe in meeting notes nobody reads. But it wasn't connected to her work.

This happens constantly. A designer spends a week on a flow that product already decided to cut. An engineer optimizes a query that's about to be replaced by a new data pipeline. A salesperson pitches a feature that was removed in the last release. In every case, someone knew. The information was in the system. It just wasn't in the right place at the right time.

Goals, when they're legible and current, are the connective tissue. If the deprecation decision had updated the project's `goals.md` — even a single line: "Migrating off legacy auth service, no new work" — anyone looking at that scope would know. Not because they were told in a meeting. Not because they happened to be in the right Slack channel. Because the goal was written down and the system kept it current.

## The compaction loop

Raw signals are noise. You can't just log everything and hope someone reads it.

The system captures signals every two seconds — messages, tabs, clipboard, screenshots, app switches. That's thousands of data points per hour. Most of them are meaningless: you switched to Chrome, you scrolled, you copied a URL, you switched back.

The compaction loop turns perception into knowledge. Every hour, an LLM reads the hot buffer of raw signals against your goals and memory, and makes a judgment call: what here is actually worth remembering? A commitment was made — that goes into memory. A deadline was mentioned — that updates actions. You browsed the same page four times without acting — that's a pattern worth noting. Everything else gets dropped.

This mirrors how human memory works. You don't remember every word of every conversation. You remember that your co-founder said the diligence answers would be done by Friday. You remember that the investor seemed warm but wants to see updated metrics. You remember that the new hire starts April 15th. Facts, not noise.

Over weeks, `memory.md` becomes a curated history of what actually happened — not what was planned, not what was reported, but what the signals revealed.

## Cross-scope conflict detection

The real leverage is seeing across scopes.

You set a personal goal: be home by 6pm on school nights. You also have a project goal: ship the feature by Friday. On Wednesday, the monitor notices signals piling up in the project scope — a PR was rejected, a dependency broke, the designer is out. Meanwhile, your personal scope shows a schedule change for Thursday evening.

A single-scope system can't see this tension. Your project management tool doesn't know about your kids. Your family calendar doesn't know about the feature deadline. But when all goals across all scopes are loaded into the same context window, the system can surface the conflict before it becomes a crisis.

This extends to teams. If two project scopes are both demanding the same person's time this week, the system can flag it. If an org-level goal shifted but a project scope is still operating on the old assumption, the system can catch the drift. The conflicts that kill productivity aren't within a project — they're between projects, between work and life, between what was decided and what's actually happening.

## Perception and judgment

The architecture splits intelligence into two tiers, mirroring how human attention works.

Peripheral awareness is cheap and constant. The monitor loop runs a fast, inexpensive model every fifteen seconds, scanning signals against goals. This is the part of your brain that notices a name in your peripheral vision while you're reading something else. It doesn't need to be brilliant. It needs to be fast and always on.

Focused attention is expensive and intermittent. When you sit down and ask "what should I focus on today?", the system brings its most capable model to bear — synthesizing goals, memory, actions, and recent signals into a considered answer. This is deliberate thought, not reflexive pattern matching.

Most signals deserve a glance, not a stare. The system allocates intelligence proportionally: cheap perception for the fire hose of daily signals, expensive judgment only when you ask for it.

## What this enables

Imagine starting your day and typing `work standup`. The system has been watching while you slept — emails arrived, Slack messages accumulated, a calendar event was moved. It reads all of this against your goals across every scope and tells you:

Your fundraise goal has a gap: you told an investor you'd send updated metrics by today, but the spreadsheet hasn't been touched since Monday. Your project goal is on track, but Jamil flagged a blocker in Slack at 11pm that needs your input. Your personal goal has a conflict: Ruby's recital is Thursday at 5pm and your project scope is showing signs of a crunch that week.

You didn't fill out a form. You didn't update a dashboard. You just worked, and the system built understanding from the exhaust of that work.

This is the language of productivity: not the language of tasks and time blocks, but the language of goals, signals, and alignment. It's the language that connects what you're doing to why you're doing it, and surfaces the gaps before they become failures.

We didn't set out to build a better productivity tool. We set out to make the invisible visible — to give people a way to see whether their time, the only non-renewable resource they have, is actually going where it matters.
