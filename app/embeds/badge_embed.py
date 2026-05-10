from __future__ import annotations

import discord

from app.models.badge import Badge
from app.models.member import Member

_BADGE_FLAVORS: dict[str, str] = {
    "rubber_duck":     "Five devs freed from the bog. The duck reigns supreme.",
    "helpful_human":   "Generosity is the highest form of engineering.",
    "ship_it":         "Same day open, same day merged. Zero procrastination.",
    "standup_champion": "Seven days in a row. Consistency is a superpower.",
    "streak_starter":  "Three days and counting. The streak begins.",
    "on_fire":         "Seven straight days of activity. Respect.",
    "unstoppable":     "Two weeks without missing a beat.",
    "legendary":       "Thirty days. A legend in the making.",
    "no_any_club":     "Ten PRs, zero `any`. TypeScript approves.",
    "clutch_coder":    "Cut it close. Shipped under pressure.",
    "knowledge_dealer": "Five resources. The community learned from you.",
}

_BADGE_COLORS: dict[str, discord.Color] = {
    "rubber_duck":      discord.Color.yellow(),
    "helpful_human":    discord.Color.teal(),
    "standup_champion": discord.Color.gold(),
    "ship_it":          discord.Color.green(),
    "on_fire":          discord.Color.orange(),
    "unstoppable":      discord.Color.red(),
    "legendary":        discord.Color.purple(),
    "clutch_coder":     discord.Color.blue(),
}


def build_badge_award_embed(member: Member, badge: Badge) -> discord.Embed:
    flavor = _BADGE_FLAVORS.get(badge.key, badge.description)
    color = _BADGE_COLORS.get(badge.key, discord.Color.gold())

    embed = discord.Embed(
        title=f"{badge.emoji}  {badge.name}",
        description=f"**{member.discord_name}** just unlocked a badge!\n\n_{flavor}_",
        color=color,
    )
    embed.set_footer(text="Badge earned · DevBot")
    return embed
