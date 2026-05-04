from __future__ import annotations

import discord

from app.models.member import Member
from app.models.ticket import Ticket

_TIER_COLORS = {
    "T1": discord.Color.blue(),
    "T2": discord.Color.orange(),
    "T3": discord.Color.red()
}

_STATUS_EMOJI = {
    "todo": "⬜",
    "in_progress": "🟡",
    "in_review": "🔵",
    "done": "✅",
}

_PRIORITY_EMOJI = {
    "low": "⬇️",
    "medium": "➡️",
    "high": "⬆️",
    "blocker": "🚨",
}

_STATUS_LABELS = {
    "todo": "To Do",
    "in_progress": "In Progress",
    "in_review": "In Review",
    "done": "Done"
}


def build_ticket_embed(ticket: Ticket, assignee: Member | None) -> discord.Embed:
    color = _TIER_COLORS.get(ticket.tier, discord.Color.default())
    status_emoji = _STATUS_EMOJI.get(ticket.status, "❓")
    priority_emoji = _PRIORITY_EMOJI.get(ticket.priority, "➡️")
    status_label = _STATUS_LABELS.get(ticket.status, ticket.status)

    embed = discord.Embed(
        title=f"[{ticket.tier}] {ticket.title}",
        description=ticket.description or "",
        color=color
    )

    embed.add_field(
        name="Status",
        value=f"{status_emoji} {status_label}",
        inline=True
    )
    embed.add_field(
        name="Priority",
        value=f"{priority_emoji} {ticket.priority.capitalize()}",
        inline=True
    )
    embed.add_field(
        name="Assignee",
        value=assignee.discord_name if assignee else "Unassigned",
        inline=True
    )

    if ticket.deadline:
        embed.add_field(
            name="Deadline",
            value=discord.utils.format_dt(ticket.deadline, style="D"),
            inline=True
        )

    if ticket.phase:
        embed.add_field(name="Phase", value=ticket.phase, inline=True)

    short_id = str(ticket.id)[-8:]
    embed.add_field(name="ID", value=f"`{short_id}`", inline=True)

    if ticket.tier == "T1" and not ticket.description:
        embed.add_field(
            name="⚠️ Reference Pattern",
            value="T1 tickets should include a reference pattern in the description.",
            inline=False,
        )

    embed.set_footer(text=f"Created {discord.utils.format_dt(ticket.created_at, style='R')}")
    return embed


def build_board_embed(tickets: list[Ticket]) -> discord.Embed:
    embed = discord.Embed(title="Ticket Board", color=discord.Color.blurple())

    by_status: dict[str, list[Ticket]] = {
        "todo": [],
        "in_progress": [],
        "in_review": [],
        "done": []
    }
    for t in tickets:
        by_status.setdefault(t.status, []).append(t)

    for status in ("todo", "in_progress", "in_review", "done"):
        group = by_status[status]
        emoji = _STATUS_EMOJI[status]
        label = _STATUS_LABELS[status]

        if not group:
            embed.add_field(
                name=f"{emoji} {label} (0)",
                value="_None_",
                inline=False
            )
            continue

        lines = []
        for t in group:
            short_id = str(t.id)[-8:]
            lines.append(f"`{short_id}` **[{t.tier}]** {t.title}")
            if len(lines) >= 10:
                lines.append(f"_… and {len(group) - 10} more_")
                break

        embed.add_field(
            name=f"{emoji} {label} ({len(group)})",
            value="\n".join(lines),
            inline=False
        )

    total_open = sum(
        len(by_status[s]) for s in ("todo", "in_progress", "in_review")
    )
    embed.set_footer(text=f"{total_open} open tickets")
    return embed