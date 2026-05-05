from __future__ import annotations

import discord

from app.models.member import Member
from app.models.standup import StandupResponse, StandupSession

def build_standup_summary(
    session: StandupSession,
    responses: list[StandupResponse],
    non_responders: list[Member],
    member_map: dict[str, str],  # member_id str -> discord_name
) -> discord.Embed:
    embed = discord.Embed(
        title=f"Standup — {session.date}",
        color=discord.Color.green(),
    )
    embed.description = f"**{len(responses)}** responded"
    if responses:
        embed.description += f" · {len(non_responders)} pending"

    for resp in responses:
        name = member_map.get(str(resp.member_id), str(resp.member_id)[:8])
        value_lines = [
            f"**Yesterday:** {resp.yesterday or '_nothing_'}",
            f"**Today:** {resp.today or '_nothing_'}",
            f"**Blockers:** {resp.blockers or '_none_'}",
        ]
        embed.add_field(name=name, value="\n".join(value_lines), inline=False)

    if non_responders:
        names = ", ".join(m.discord_name for m in non_responders)
        embed.set_footer(text=f"No response: {names}")
    else:
        embed.set_footer(text="Full team responded ✅")

    return embed
