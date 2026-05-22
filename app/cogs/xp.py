from __future__ import annotations

import discord
import structlog
from discord import app_commands
from discord.ext import commands
import asyncio

from sqlalchemy.ext.asyncio import result

from app import database
from app.config import settings
from app.embeds.leaderboard_embed import build_leaderboard_embed
from app.services.member_service import MemberService
from app.services.steak_service import StreakService
from app.services.xp_service import XPService, compute_level, level_title
from app.utils.guards import require_member

log = structlog.get_logger()


class XPCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _xp_service(self) -> XPService:
        return XPService(database.get_db())

    def _streak_service(self) -> StreakService:
        db = database.get_db()
        return StreakService(db, MemberService(db))

    @app_commands.command(name="xp", description="Show XP, level and recent activity")
    @app_commands.describe(target="Member to look up (defaults to you)")
    async def xp(
            self,
            interaction: discord.Interaction,
            target: discord.Member | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        lookup = target or interaction.user
        svc = MemberService(database.get_db())
        member = await svc.get_by_discord_id(str(lookup.id))

        if member is None:
            await interaction.followup.send("That user is not registered", ephemeral=True)
            return

        xp_svc = self._xp_service()
        stats = await xp_svc.get_stats(str(member.id))
        recent = await xp_svc.get_recent_ledger(str(member.id), limit=5)

        total = stats.total_xp if stats else 0
        lvl = stats.level if stats else 1
        streak = stats.current_streak if stats else 0

        embed = discord.Embed(
            title=f"{member.discord_name} — XP Profile",
            color=discord.Color.gold()
        )
        embed.add_field(name="Total XP", value=str(total), inline=True)
        embed.add_field(name="Level", value=f"{lvl} — {level_title(lvl)}", inline=True)
        embed.add_field(name="Streak", value=f"🔥 {streak} days", inline=True)

        board = await xp_svc.leaderboard(limit=50)
        rank = next((e.rank for e in board if str(e.member_id) == str(member.id)), None)
        if rank:
            embed.add_field(name="Rank", value=f"#{rank}", inline=True)

        if recent:
            lines = [f"`{e.action}` +{e.xp} XP" for e in recent]
            embed.add_field(name="Recent Activity", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Show the XP leaderboard")
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.guild_id)
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        entries = await self._xp_service().leaderboard(limit=10)
        embed = build_leaderboard_embed(entries, period="All-time")
        await interaction.followup.send(embed=embed)

    # Scheduled Jobs

    async def _leaderboard_post_job(self) -> None:
        log.info("job.leaderboard_post.start")
        guild = self.bot.get_guild(settings.DISCORD_GUILD_ID)
        if guild is None:
            return
        channel = self.bot.get_text_channel("rankings", guild)
        if not isinstance(channel, discord.TextChannel):
            return

        entries = await self._xp_service().leaderboard(limit=10)
        embed = build_leaderboard_embed(entries, period="Weekly")
        await channel.send(embed=embed)
        log.info("job.leaderboard_post.done", entries=len(entries))

    async def _streak_check_job(self) -> None:
        log.info("job.streak_check.start")
        broken_ids = await self._streak_service().check_all_streaks()
        if not broken_ids:
            return

        guild = self.bot.get_guild(settings.DISCORD_GUILD_ID)
        if guild is None:
            return

        svc = MemberService(database.get_db())
        for member_id in broken_ids:
            def _fetch(mid=member_id):
                return (
                    database.get_db()
                    .table("bot_members")
                    .select("discord_id")
                    .eq("id", mid)
                    .limit(1)
                    .execute()
                )

            result = await asyncio.get_event_loop().run_in_executor(None, _fetch())
            if not result.data:
                continue
            discord_id = int(result.data[0]["discord_id"])
            try:
                user = await self.bot.fetch_user(discord_id)
                await user.send(
                    "💔 Your streak was reset — no qualifying activity was recorded today. "
                    "Start fresh tomorrow!"
                )
            except (discord.Forbidden, discord.NotFound):
                pass

        log.info("job.streak_check.done", broken=len(broken_ids))

    async def _streak_risk_dm_job(self) -> None:
        log.info("job.streak_risk_dm.start")
        at_risk = await self._streak_service().at_risk_members()
        for member in at_risk:
            try:
                user = await self.bot.fetch_user(int(member.discord_id))
                await user.send(
                    "🔥 Your streak is at risk — no activity recorded yet today. "
                    "Close a ticket, push a commit, or respond to standup to keep it alive!"
                )
            except (discord.Forbidden, discord.NotFound):
                pass
        log.info("job.streak_risk_dm.done", at_risk=len(at_risk))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(XPCog(bot))


