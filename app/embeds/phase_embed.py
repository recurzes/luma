from __future__ import annotations

import discord

from app.models.phase import Phase, PhaseCriteria

_STATUS_COLORS = {
    "active":   discord.Color.blue(),
    "complete": discord.Color.green(),
    "pending":  discord.Color.greyple(),
}


def build_phase_embed(
    phase: Phase,
    criteria: list[PhaseCriteria],
    open_count: int = 0,
    closed_count: int = 0,
) -> discord.Embed:
    color = _STATUS_COLORS.get(phase.status, discord.Color.blurple())
    embed = discord.Embed(
        title=f"Phase Tracker — {phase.name}",
        description=phase.description or "",
        color=color,
    )

    if criteria:
        checklist = "\n".join(
            f"{'✅' if c.checked else '⬜'} {c.description}"
            for c in criteria
        )
        embed.add_field(name="Exit Criteria", value=checklist, inline=False)
    else:
        embed.add_field(name="Exit Criteria", value="_(none defined)_", inline=False)

    embed.add_field(name="Open Tickets", value=str(open_count), inline=True)
    embed.add_field(name="Closed Tickets", value=str(closed_count), inline=True)
    embed.set_footer(text=f"Status: {phase.status.upper()} · key: {phase.key}")
    return embed


def build_completion_ceremony(phase: Phase, summary: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Phase Complete — {phase.name}",
        description=f"**{summary.get('motivational', '')}**",
        color=discord.Color.gold(),
    )

    per_dev = summary.get("per_dev", [])
    if per_dev:
        lines = []
        for dev in per_dev[:10]:
            lines.append(
                f"**{dev['name']}** — {dev['tickets_closed']} tickets · "
                f"{dev['total_xp']} XP · streak {dev['current_streak']}d"
            )
        embed.add_field(name="Dev Stats", value="\n".join(lines) or "_—_", inline=False)

    # Streak leaders
    streakers = sorted(per_dev, key=lambda d: d["current_streak"], reverse=True)[:3]
    if streakers:
        streak_lines = [
            f"{i + 1}. **{d['name']}** — {d['current_streak']}-day streak"
            for i, d in enumerate(streakers)
        ]
        embed.add_field(name="Streak Leaders", value="\n".join(streak_lines), inline=False)

    embed.set_footer(text=f"Phase {phase.key} completed · LumaBot")
    return embed
