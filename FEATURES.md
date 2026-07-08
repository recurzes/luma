# LumaBot Features

This document summarizes bot features, how to use them, and the required arguments for commands.

## Core Features

- Member registration and profiles, including GitHub username linking.
- Per-server sign-out and per-feature opt-in (standup, mood, journal, etc.).
- Personal messages labeled with the server they apply to (multi-server safe).
- Ticket board with assignments, status updates, and XP rewards.
- Daily standup collection via DM, with automated summaries and reminders.
- XP, levels, streak tracking, and leaderboard posts.
- Culture tools: shoutouts, resource sharing, sprint challenges.
- Help workflow: /stuck threads, escalations, and pair sessions.
- Phase tracking with criteria checklists and completion ceremony.
- GitHub webhook ingestion and event-driven updates in Discord.
- Automated monitoring: stale ticket pings, stale PR pings, mood check-ins, tip-of-the-day posts.
- Auto-provisioned channels under the "LumaBot" category.
- In-Discord help via `/help` with sample command usage per group.

## Commands (Slash Commands)

Notes:
- Most commands require the user to be registered with `/member register` in the current server.
- Sign out with `/member signout` to stop DMs and command access in that server; rejoin with `/member register`.
- Join optional features with `/member feature join <feature>` (standup, mood, journal, streak, track, blitz, stuck).
- `/member notifications on|off|list` are aliases for feature join/leave/list.
- Some commands are restricted to Lead/Professor (enforced in code).
- Commands with cooldowns include: `/ticket board`, `/xp leaderboard`.

### Help

- `/help`
  - Purpose: list all command groups and passive DM features.
  - Args: none.

- `/help group:<name>`
  - Purpose: show commands, descriptions, and sample usage for one group.
  - Args:
    - `group` (optional): e.g. `member`, `ticket`, `standup` (autocomplete available).

### General

- `/bot ping`
  - Purpose: check latency, database reachability, and uptime.
  - Args: none.

### Members

- `/member register`
  - Purpose: register or rejoin Luma in this server using your Discord role.
  - Args: none.

- `/member signout`
  - Purpose: sign out of Luma in this server (stops DMs and slash commands here).
  - Args: none.

- `/member feature list`
  - Purpose: show which features you have joined on this server.
  - Args: none.

- `/member feature join <feature>`
  - Purpose: opt in to a feature (required before receiving standup DMs, mood check-ins, etc.).
  - Args:
    - `feature` (required): `standup`, `mood`, `journal`, `streak`, `track`, `blitz`, or `stuck`.

- `/member feature leave <feature>`
  - Purpose: opt out of a feature on this server.
  - Args:
    - `feature` (required): same choices as above.

- `/member notifications list`
  - Purpose: show personal message preferences for this server.
  - Args: none.

- `/member notifications off <feature>`
  - Purpose: opt out of a DM type.
  - Args:
    - `feature` (required): `standup`, `mood`, `journal`, `streak`, `track`, `blitz`, or `stuck`.

- `/member notifications on <feature>`
  - Purpose: re-enable a DM type.
  - Args:
    - `feature` (required): same choices as above.

- `/member info [target]`
  - Purpose: show a member profile (defaults to you).
  - Args:
    - `target` (optional): Discord member to look up.

- `/member github <username>`
  - Purpose: link your GitHub username to your profile.
  - Args:
    - `username` (required): your GitHub username.

### Tickets

- `/ticket create`
  - Purpose: create a new ticket via modal form.
  - Modal fields:
    - `Title` (required, max 100 chars)
    - `Description` (optional, max 500 chars)
    - `Tier` (required: T1/T2/T3)
    - `Priority` (required: low/medium/high/blocker)
    - `Deadline` (optional: YYYY-MM-DD)

- `/ticket assign <ticket_id> <member>`
  - Purpose: assign a ticket to a team member.
  - Args:
    - `ticket_id` (required): last 8 chars or full UUID.
    - `member` (required): Discord member to assign.
  - Notes: enforces tier eligibility for assignees.

- `/ticket status <ticket_id> <new_status>`
  - Purpose: update ticket status.
  - Args:
    - `ticket_id` (required): last 8 chars or full UUID.
    - `new_status` (required): one of `todo`, `in_progress`, `in_review`, `done`.

- `/ticket close <ticket_id>`
  - Purpose: close a ticket and award XP.
  - Args:
    - `ticket_id` (required): last 8 chars or full UUID.

- `/ticket mine`
  - Purpose: list your open tickets.
  - Args: none.

- `/ticket board`
  - Purpose: show the full ticket board grouped by status.
  - Args: none.
  - Cooldown: 30s per guild.

### Standups (Automated)

- Daily standup DM prompts are sent automatically (weekday mornings).
- Each DM is labeled with the server name (`📍 **Server Name**`).
- Replies are collected in a 3-step flow (yesterday, today, blockers).
- A compiled summary is posted to `#standup-log`.
- Non-responders are pinged in `#standup-log` before the window closes.
- Opt out: `/member notifications off feature:standup`.

### Phases

- `/phase current`
  - Purpose: show the active phase and exit criteria checklist.
  - Args: none.

- `/phase criteria <item_number>`
  - Purpose: check off a phase exit criterion.
  - Args:
    - `item_number` (required): 1-based index from `/phase current`.

- `/phase complete`
  - Purpose: complete the active phase and post a ceremony.
  - Args: none.
  - Restricted: Lead/Professor only.

### XP and Leaderboards

- `/xp show [target]`
  - Purpose: show XP, level, streak, and recent activity.
  - Args:
    - `target` (optional): Discord member to look up.

- `/xp leaderboard`
  - Purpose: show the XP leaderboard.
  - Args: none.
  - Cooldown: 30s per guild.

### Culture

- `/culture shoutout <member> <reason>`
  - Purpose: give a teammate a shoutout and post to `#shoutouts`.
  - Args:
    - `member` (required): Discord member to shout out.
    - `reason` (required): why they deserve it.

- `/culture share <tip> [link]`
  - Purpose: share a tip/resource in `#resources`.
  - Args:
    - `tip` (required): the tip or resource text.
    - `link` (optional): a URL.

- `/culture sprint start <name> [days]`
  - Purpose: start a sprint challenge and announce in `#announcements`.
  - Args:
    - `name` (required): sprint name.
    - `days` (optional): duration in days (default 7).
  - Restricted: Lead/Professor only.

- `/culture sprint end`
  - Purpose: end the active sprint and post top performers.
  - Args: none.
  - Restricted: Lead/Professor only.

### Help and Pairing

- `/stuck open <problem>`
  - Purpose: open a help thread and start the 15-minute timer.
  - Args:
    - `problem` (required): brief description of what you are stuck on.

- `/stuck unstuck [helper]`
  - Purpose: close a help thread and award XP to a helper.
  - Args:
    - `helper` (optional): Discord member who helped (defaults to caller).
  - Notes: must be run inside the help thread.

- `/stuck pair <dev1> <dev2> [topic]`
  - Purpose: create a temporary pair programming text + voice channel.
  - Args:
    - `dev1` (required): first developer.
    - `dev2` (required): second developer.
    - `topic` (optional): topic or ticket ID (default "pairing").
  - Notes: channels auto-delete after 2 hours.

### Reviews

- `/review assign <dev> <pr_number>`
  - Purpose: manually assign a PR reviewer.
  - Args:
    - `dev` (required): member to assign as reviewer.
    - `pr_number` (required): GitHub PR number or ticket ID suffix.
  - Restricted: Lead/Professor only.

- `/review stats`
  - Purpose: show PR review counts per developer.
  - Args: none.

## Personal Messages

All scheduled DMs include the server name so you know which community they refer to.

| Feature | Schedule | Opt-out feature key |
|---------|----------|---------------------|
| Standup | Weekdays 9:00 | `standup` |
| Mood check-in | Monday 9:00 | `mood` |
| Journal EOD prompt | Weekdays 17:00 | `journal` |
| Streak risk / broken | Daily 20:00 / 23:50 | `streak` |
| Track nudge | Monday 9:00 | `track` |
| Blitz inactive | Every 8h | `blitz` |
| Stuck escalation | On 30min stuck | `stuck` (leads only) |

## GitHub Integration (Webhooks + Automation)

- Webhook endpoint: `POST /webhooks/github`
  - Events handled: `push`, `pull_request`, `pull_request_review`, `check_run`.
  - Signature validation: `X-Hub-Signature-256` using `GITHUB_WEBHOOK_SECRET`.

- Event processing highlights:
  - Posts commit/PR/review/CI updates to `#github-feed`.
  - Auto-assigns reviewers for PRs, rotating eligible members.
  - Tracks and awards XP for commits, merged PRs, and reviews.
  - Closes linked tickets when PR bodies reference a ticket ID.
  - Flags TypeScript `any` usage and protected-path changes in `#code-review` (beginner PRs).
  - Pings for stale PRs without review.

## Scheduled Automation

- Standup DM prompt, compile summary, and reminder ping jobs.
- Weekly leaderboard post to `#rankings`.
- Daily streak checks and at-risk streak DMs.
- Stale ticket warnings (in-progress > 48h) to `#task-feed`.
- PR review stale pings (open > 24h) to `#code-review`.
- Tip of the day posts to `#tip-of-the-day` (if configured).
- Monday mood check-in DM + aggregate posting to `#general`.

## Auto-Created Channels

The bot auto-creates a `LumaBot` category and the following text channels (if missing):

- `#task-feed`, `#standup-log`, `#github-feed`, `#code-review`, `#phase-tracker`
- `#help`, `#shoutouts`, `#announcements`, `#tip-of-the-day`
- `#resources`, `#retro`, `#rankings`, `#general`

## Database Migration

Apply `app/migrations/010_enrollments_and_notifications.sql` before deploying. Existing members are backfilled into enrollments on bot startup.
