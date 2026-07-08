from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandHelp:
    name: str
    description: str
    usage: str
    notes: str | None = None


@dataclass(frozen=True)
class GroupHelp:
    key: str
    title: str
    summary: str
    commands: tuple[CommandHelp, ...]
    requires_registration: bool = True


COMMAND_GROUPS: dict[str, GroupHelp] = {
    "bot": GroupHelp(
        key="bot",
        title="Bot",
        summary="Health checks and bot status.",
        requires_registration=False,
        commands=(
            CommandHelp(
                name="ping",
                description="Check bot latency, database reachability, and uptime.",
                usage="/bot ping",
            ),
        ),
    ),
    "help": GroupHelp(
        key="help",
        title="Help",
        summary="In-Discord command reference with sample usage.",
        requires_registration=False,
        commands=(
            CommandHelp(
                name="(index)",
                description="List all command groups and passive features.",
                usage="/help",
            ),
            CommandHelp(
                name="group",
                description="Show detailed help for one command group.",
                usage="/help group:member",
                notes="Use autocomplete to pick a group.",
            ),
        ),
    ),
    "member": GroupHelp(
        key="member",
        title="Members",
        summary="Registration, profiles, sign-out, and per-feature opt-in.",
        commands=(
            CommandHelp(
                name="register",
                description="Register or rejoin Luma in this server.",
                usage="/member register",
                notes="Does not auto-join features — use /member feature join after registering.",
            ),
            CommandHelp(
                name="signout",
                description="Stop receiving DMs and using Luma in this server.",
                usage="/member signout",
            ),
            CommandHelp(
                name="feature list",
                description="Show which features you have joined on this server.",
                usage="/member feature list",
            ),
            CommandHelp(
                name="feature join",
                description="Join a feature (standup, mood, journal, streak, track, blitz, stuck).",
                usage="/member feature join feature:standup",
            ),
            CommandHelp(
                name="feature leave",
                description="Leave a feature on this server.",
                usage="/member feature leave feature:standup",
            ),
            CommandHelp(
                name="notifications list",
                description="Show feature/message preferences (alias for feature list).",
                usage="/member notifications list",
            ),
            CommandHelp(
                name="notifications off",
                description="Disable a feature (alias for feature leave).",
                usage="/member notifications off feature:standup",
            ),
            CommandHelp(
                name="notifications on",
                description="Enable a feature (alias for feature join).",
                usage="/member notifications on feature:journal",
            ),
            CommandHelp(
                name="info",
                description="Show a member profile.",
                usage="/member info",
                notes="Optional: `target:@Dev`",
            ),
            CommandHelp(
                name="github",
                description="Link your GitHub username.",
                usage="/member github username:octocat",
            ),
        ),
    ),
    "ticket": GroupHelp(
        key="ticket",
        title="Tickets",
        summary="Create, assign, and close work tickets with XP rewards.",
        commands=(
            CommandHelp("create", "Open a new ticket via modal form.", "/ticket create"),
            CommandHelp(
                "assign",
                "Assign a ticket to a teammate.",
                "/ticket assign ticket_id:abc12345 member:@Dev",
            ),
            CommandHelp(
                "status",
                "Update ticket status.",
                "/ticket status ticket_id:abc12345 new_status:in_progress",
            ),
            CommandHelp("close", "Close a ticket and award XP.", "/ticket close ticket_id:abc12345"),
            CommandHelp("mine", "List your open tickets.", "/ticket mine"),
            CommandHelp(
                "board",
                "Show the full ticket board.",
                "/ticket board",
                notes="30s cooldown per guild.",
            ),
        ),
    ),
    "phase": GroupHelp(
        key="phase",
        title="Phases",
        summary="Track roadmap phases and exit criteria.",
        commands=(
            CommandHelp("current", "Show active phase and checklist.", "/phase current"),
            CommandHelp(
                "criteria",
                "Check off an exit criterion.",
                "/phase criteria item_number:1",
            ),
            CommandHelp(
                "complete",
                "Complete the active phase.",
                "/phase complete",
                notes="Lead/Professor only.",
            ),
        ),
    ),
    "xp": GroupHelp(
        key="xp",
        title="XP",
        summary="XP profiles, streaks, and leaderboards.",
        commands=(
            CommandHelp("show", "Show XP, level, and streak.", "/xp show"),
            CommandHelp(
                "leaderboard",
                "Show the XP leaderboard.",
                "/xp leaderboard",
                notes="30s cooldown per guild.",
            ),
        ),
    ),
    "culture": GroupHelp(
        key="culture",
        title="Culture",
        summary="Shoutouts, resources, and sprint challenges.",
        commands=(
            CommandHelp(
                "shoutout",
                "Give a teammate a shoutout.",
                "/culture shoutout member:@Dev reason:Shipped the auth fix!",
            ),
            CommandHelp(
                "share",
                "Share a tip or resource.",
                "/culture share tip:Use structlog link:https://example.com",
            ),
            CommandHelp(
                "sprint start",
                "Start a sprint challenge.",
                "/culture sprint start name:Week 3 days:7",
                notes="Lead/Professor only.",
            ),
            CommandHelp(
                "sprint end",
                "End the active sprint.",
                "/culture sprint end",
                notes="Lead/Professor only.",
            ),
        ),
    ),
    "stuck": GroupHelp(
        key="stuck",
        title="Stuck / Help",
        summary="Help threads, escalations, and pair sessions.",
        commands=(
            CommandHelp(
                "open",
                "Open a help thread and start the 15-minute timer.",
                "/stuck open problem:Can't get pytest fixtures working",
            ),
            CommandHelp(
                "unstuck",
                "Close a help thread and award XP.",
                "/stuck unstuck helper:@Mentor",
                notes="Run inside the help thread.",
            ),
            CommandHelp(
                "pair",
                "Create a temporary pair programming session.",
                "/stuck pair dev1:@Alice dev2:@Bob topic:auth-bug",
                notes="Lead/Professor only.",
            ),
        ),
    ),
    "review": GroupHelp(
        key="review",
        title="Reviews",
        summary="PR reviewer assignment and stats.",
        commands=(
            CommandHelp(
                "assign",
                "Manually assign a PR reviewer.",
                "/review assign dev:@Dev pr_number:42",
                notes="Lead/Professor only.",
            ),
            CommandHelp("stats", "Show PR review counts.", "/review stats"),
        ),
    ),
    "project": GroupHelp(
        key="project",
        title="Projects",
        summary="Project context for journals, ADRs, and tickets.",
        commands=(
            CommandHelp(
                "create",
                "Create a new project.",
                "/project create name:Capstone type:web",
            ),
            CommandHelp("list", "List active projects.", "/project list"),
            CommandHelp(
                "switch",
                "Set your active project.",
                "/project switch name:Capstone",
            ),
            CommandHelp("archive", "Archive a project.", "/project archive name:Capstone"),
            CommandHelp("info", "Show project details.", "/project info"),
            CommandHelp(
                "link-repo",
                "Link a GitHub repo.",
                "/project link-repo url:https://github.com/org/repo",
            ),
        ),
    ),
    "journal": GroupHelp(
        key="journal",
        title="Journal",
        summary="Daily entries, ADRs, and sprint summaries.",
        commands=(
            CommandHelp(
                "entry",
                "Log what you built or learned today.",
                "/journal entry content:Implemented OAuth flow mood:4",
            ),
            CommandHelp(
                "decision",
                "Record an architectural decision (ADR).",
                "/journal decision title:Use JWT context:Auth needs stateless tokens decision:Use JWT",
            ),
            CommandHelp("today", "See today's entries.", "/journal today"),
            CommandHelp("week", "See this week's entries.", "/journal week"),
            CommandHelp("search", "Search your journal.", "/journal search query:OAuth"),
            CommandHelp("summary", "Generate a sprint summary.", "/journal summary"),
            CommandHelp("adr list", "List ADRs for active project.", "/journal adr list"),
            CommandHelp("adr view", "View one ADR.", "/journal adr view sequence:1"),
        ),
    ),
    "track": GroupHelp(
        key="track",
        title="Tracks",
        summary="Structured learning tracks with checkpoints.",
        commands=(
            CommandHelp("list", "Browse learning tracks.", "/track list"),
            CommandHelp("enroll", "Enroll in a track.", "/track enroll name:Python Basics"),
            CommandHelp("progress", "See your track progress.", "/track progress"),
            CommandHelp(
                "checkpoint done",
                "Complete a checkpoint.",
                "/track checkpoint done checkpoint_id:abc12345 answer:42",
            ),
            CommandHelp(
                "create",
                "Create a custom track.",
                "/track create name:API Design description:REST patterns level:beginner",
                notes="Lead/Professor only.",
            ),
        ),
    ),
    "blitz": GroupHelp(
        key="blitz",
        title="Tech Blitz",
        summary="Timed team learning sprints.",
        commands=(
            CommandHelp(
                "start",
                "Start a Tech Blitz.",
                "/blitz start technology:Rust tech_category:language duration_hours:4",
                notes="Lead/Professor only.",
            ),
            CommandHelp("join", "Join the active blitz.", "/blitz join"),
            CommandHelp(
                "checkin",
                "Post progress during the blitz.",
                "/blitz checkin update:Built the CLI parser mood:4",
            ),
            CommandHelp(
                "showcase",
                "Submit your final project.",
                "/blitz showcase url:https://github.com/... description:CLI tool",
            ),
            CommandHelp("progress", "See blitz status.", "/blitz progress"),
            CommandHelp("countdown", "Show time remaining.", "/blitz countdown"),
            CommandHelp("history", "See past blitzes.", "/blitz history limit:5"),
        ),
    ),
    "standup": GroupHelp(
        key="standup",
        title="Standup (DM)",
        summary="Automated daily standup collection via personal message.",
        requires_registration=True,
        commands=(
            CommandHelp(
                "(automated)",
                "Bot DMs you on weekday mornings with standup questions.",
                "Reply in DM: yesterday → today → blockers",
                notes="Labeled with server name. Opt out: /member notifications off feature:standup",
            ),
        ),
    ),
    "monitoring": GroupHelp(
        key="monitoring",
        title="Monitoring (DM)",
        summary="Automated mood check-ins and channel monitoring.",
        requires_registration=True,
        commands=(
            CommandHelp(
                "mood check-in",
                "Monday DM mood prompt.",
                "React 1️⃣–5️⃣ or reply 1–5 in DM",
                notes="Opt out: /member notifications off feature:mood",
            ),
        ),
    ),
}

GROUP_ORDER: tuple[str, ...] = (
    "help",
    "bot",
    "member",
    "ticket",
    "standup",
    "phase",
    "xp",
    "culture",
    "stuck",
    "review",
    "project",
    "journal",
    "track",
    "blitz",
    "monitoring",
)
