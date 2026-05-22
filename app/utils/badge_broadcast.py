from __future__ import annotations

import asyncio

import discord
from supabase import Client

from app import channels
from app.embeds.badge_embed import build_badge_award_embed
from app.models.badge import Badge
from app.models.member import Member


async def get_current_streak(db: Client, member_id: str) -> int:
    def _fetch():
        return (
            db.table("bot_member_stats")
            .select("current_streak")
            .eq("member_id", member_id)
            .limit(1)
            .execute()
        )

    result = await asyncio.get_event_loop().run_in_executor(None, _fetch)
    if not result.data:
        return 0
    return int(result.data[0].get("current_streak") or 0)


async def post_badges_to_shoutouts(bot: discord.Client | None, member: Member, badges: list[Badge]) -> None:
    if bot is None or not badges:
        return
    shoutouts_name = channels.CHANNEL_MANIFEST.get("shoutouts", ("shoutouts", ""))[0]
    for guild in bot.guilds:
        channel = None
        if hasattr(bot, "get_text_channel"):
            channel = bot.get_text_channel("shoutouts", guild)
        if channel is None:
            channel = discord.utils.get(guild.text_channels, name=shoutouts_name)
        if not isinstance(channel, discord.TextChannel):
            continue
        for badge in badges:
            embed = build_badge_award_embed(member, badge)
            await channel.send(embed=embed)
