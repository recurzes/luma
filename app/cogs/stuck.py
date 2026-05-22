from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.config import settings
from app.services.member_service import MemberService
from app.services.stuck_service import StuckService, _bumped_15
from app.services.xp_service import XPService
from app.utils.guards import require_member

log = structlog.get_logger()

_LEAD_PROFESSOR_CHECK = {"lead": "professor"}


class StuckCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _svc(self) -> StuckService:
        return StuckService(database.get_db(), XPService(database.get_db()))

    @app_commands.command(name="stuck", description="Open a help thread and start the 15-minute timer")
    @app_commands.describe(problem="Describe what you're stuck on")
    async def stuck(self, interaction: discord.Interaction, problem: str) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        help_channel = self.bot.get_text_channel("help", interaction.guild)
        if not isinstance(help_channel, discord.TextChannel):
            await interaction.followup.send("Help channel not configured", ephemeral=True)
            return

        thread = await help_channel.create_thread(
            name=f"Help: {problem[:50]}",
            type=discord.ChannelType.public_thread,
            auto_archive_duration=1440
        )

        embed = discord.Embed(
            title="🆘 Help Thread",
            description=f"**Problem:** {problem}\n\nTimer started. Tag a teammate or wait — the bot will bump at 15 min.",
            color=discord.Color.orange(),
        )
        embed.set_footer(text=f"Opened by {member.discord_name} · {discord.utils.format_dt(discord.utils.utcnow(), style='R')}")
        await thread.send(content=interaction.user.mention, embed=embed)

        svc = self._svc()
        await svc.open_thread(
            requester_id=str(member.id),
            problem=problem,
            discord_thread_id=str(thread.id)
        )

        log.info("stuck.opened", user=str(interaction.user.id), thread=str(thread.id))
        await interaction.followup.send(f"Help thread created: {thread.mention}", ephemeral=True)

    @app_commands.command(name="unstuck", description="Close a help thread and award XP to the helper")
    @app_commands.describe(helper="The person who helped you (optional)")
    async def unstuck(self, interaction: discord.Interaction, helper: discord.Member | None = None) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        if not isinstance(interaction.channel, discord.Thread):
            await interaction.followup.send("Run this command inside a help thread", ephemeral=True)
            return

        svc = self._svc()
        open_threads = await svc.get_open_threads()
        thread_record = next((t for t in open_threads if t.discord_thread_id == str(interaction.channel.id)), None)

        if thread_record is None:
            await interaction.followup.send("No open help thread found for this channel", ephemeral=True)
            return

        helper_member = None
        if helper:
            helper_member = await MemberService(database.get_db()).get_by_discord_id(str(helper.id))

        helper_id = str(helper_member.id) if helper_member else str(caller.id)
        resolved = await svc.resolve(str(thread_record.id), helper_id=helper_id)

        embed = discord.Embed(
            title="✅ Thread Resolved",
            description=f"Issue resolved! Helper: **{helper_member.discord_name if helper_member else caller.discord_name}** earned +15 XP.",
            color=discord.Color.green(),
        )
        await interaction.channel.send(embed=embed)

        try:
            await interaction.channel.edit(archived=True, locked=True)
        except discord.Forbidden:
            pass

        await interaction.followup.send("Thread closed and XP awarded", ephemeral=True)

    @app_commands.command(name="pair", description="Create a temporary pair programming session (Lead/Professor only)")
    @app_commands.describe(dev1="First developer", dev2="Second developer", topic="Topic or ticket ID")
    async def pair(self, interaction: discord.Interaction, dev1: discord.Member, dev2: discord.Member, topic: str = "pairing") -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        guild = interaction.guild
        name = f"pair-{topic[:30]}"

        text_channel = await guild.create_text_channel(
            name=name,
            topic=f"Pair session: {topic}",
            reason="Auto-created pair session"
        )
        vc = await guild.create_voice_channel(
            name=f"🎤 {name}",
            reason="Auto-created pair session"
        )

        await text_channel.send(
            f"{dev1.mention} {dev2.mention} — your pair session is ready!\n"
            f"Voice: {vc.mention}\nThis channel auto-deleted in 2 hours"
        )

        bot = self.bot
        scheduler = getattr(bot, "scheduler", None)
        if scheduler:
            delete_at = datetime.now(timezone.utc) + timedelta(hours=2)
            scheduler.add_job(
                _delete_pair_channels,
                "date",
                run_date=delete_at,
                args=[text_channel.id, vc.id, bot],
                id=f"pair_cleanup_{text_channel.id}"
            )

        await interaction.followup.send(f"Pair session created: {text_channel.mention}", ephemeral=True)

    # Stuck timer job

    async def _stuck_check_job(self) -> None:
        svc = self._svc()

        threads_15 = await svc.get_overdue_threads(15)
        threads_30 = await svc.get_overdue_threads(30)
        threads_30_ids = {str(t.id) for t in threads_30}

        for thread in threads_15:
            thread_id = str(thread.id)
            if thread_id in threads_30_ids or thread_id in _bumped_15:
                continue
            _bumped_15.add(thread_id)
            if thread.discord_thread_id:
                await self._send_thread_message(
                    int(thread.discord_thread_id),
                    "⏰ **15 minutes** — Still stuck? Tag a teammate or request a pair session with `/pair`.",
                )

        for thread in threads_30:
            try:
                await svc.escalate(str(thread.id))
            except ValueError:
                continue

            if thread.discord_thread_id:
                await self._send_thread_message(
                    int(thread.discord_thread_id),
                    "⚠️ **30 minutes stuck.** Escalating to Lead/Professor.",
                )

            await self._dm_leads(f"⚠️ **{thread.problem[:80]}** — dev has been stuck for 30+ min.\nThread: <#{thread.discord_thread_id}>")

        if threads_15 or threads_30:
            log.info("stuck_check.done", bumped=len(threads_15), escalated=len(threads_30))

    async def _send_thread_message(self, thread_id: int, content: str) -> None:
        try:
            thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                await thread.send(content)
        except (discord.NotFound, discord.Forbidden):
            pass

    async def _dm_leads(self, message: str) -> None:
        all_members = await MemberService(database.get_db()).get_all_active()
        for m in all_members:
            if m.role in _LEAD_PROFESSOR_CHECK:
                try:
                    user = await self.bot.fetch_user(int(m.discord_id))
                    await user.send(message)
                except (discord.Forbidden, discord.NotFound):
                    pass


async def _delete_pair_channels(text_id: int, vc_id: int, bot) -> None:
    for channel_id in (text_id, vc_id):
        try:
            channel = await bot.fetch_channel(channel_id)
            await channel.delete(reason="Pair session expired (2h)")
        except (discord.NotFound, discord.Forbidden):
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StuckCog(bot))