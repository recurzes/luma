from __future__ import annotations

import discord

from app.models.xp import LeaderboardEntry
from app.services.xp_service import level_title

_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def build_leaderboard_embed(entries: list[LeaderboardEntry], period: str = "All-time") -> discord.Embed:
    embed = discord.Embed(
        title=f"XP Leaderboard — {period}",
        color=discord.Color.gold(),
    )

    if not entries:
        embed.description = "_No data yet._"
        return embed

    lines: list[str] = []
    for entry in entries:
        medal = _MEDALS.get(entry.rank, f"**#{entry.rank}**")
        streak_str = f"🔥{entry.current_streak}" if entry.current_streak > 0 else ""
        title = level_title(entry.level)
        lines.append(
            f"{medal} **{entry.discord_name}** — {entry.total_xp} XP "
            f"· Lv.{entry.level} {title} {streak_str}"
        )

    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Top {len(entries)} members by total XP")
    return embed