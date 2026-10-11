from __future__ import annotations

import asyncio
from datetime import timedelta

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.services.enrollment_service import EnrollmentService
from app.services.member_service import MemberService
from app.services.notification_service import NotificationService
from app.services.stuck_service import StuckService, _bumped_15
from app.services.xp_service import XPService
from app.utils.dm import send_notification_dm
from app.utils.guards import is_staff, require_member, staff_only

log = structlog.get_logger()

_LEAD_PROFESSOR_ROLES = {"lead", "professor"}

_PAIR_PREFIX = "pair-"
_PAIR_VOICE_PREFIX = "🎤 "
_PAIR_TOPIC_PREFIX = "Pair session: "
_PAIR_LIFETIME = timedelta(hours=2)


class StuckCog(commands.GroupCog, name="stuck"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    def _svc(self) -> StuckService:
        return StuckService(database.get_db(), XPService(database.get_db()))

    @app_commands.command(name="open", description="Open a help thread and start the 15-minute timer")
    @app_commands.describe(problem="Describe what you're stuck on")
    async def open(self, interaction: discord.Interaction, problem: str) -> None:
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
        thread_record = await svc.get_unresolved_by_discord_thread(str(interaction.channel.id))

        if thread_record is None:
            await interaction.followup.send("No open help thread found for this channel", ephemeral=True)
            return

        if caller.id != thread_record.requester_id and not is_staff(interaction.user):
            await interaction.followup.send(
                "Only the person who opened this thread (or a Lead/Professor) can close it",
                ephemeral=True
            )
            return

        helper_member = None
        if helper:
            helper_member = await MemberService(database.get_db()).get_by_discord_id(str(helper.id))
            if helper_member is None:
                await interaction.followup.send(
                    f"{helper.display_name} is not a registered member, so they can't be credited",
                    ephemeral=True
                )
                return

        credited = helper_member is not None and helper_member.id != thread_record.requester_id
        await svc.resolve(
            str(thread_record.id),
            helper_id=str(helper_member.id) if helper_member else None
        )

        description = "Issue resolved!"
        if credited:
            description += f" Helper: **{helper_member.discord_name}** earned +15 XP."
        embed = discord.Embed(
            title="✅ Thread Resolved",
            description=description,
            color=discord.Color.green(),
        )
        await interaction.channel.send(embed=embed)

        try:
            await interaction.channel.edit(archived=True, locked=True)
        except discord.Forbidden:
            pass

        await interaction.followup.send(
            "Thread closed and XP awarded" if credited else "Thread closed",
            ephemeral=True
        )

    @app_commands.command(name="pair", description="Create a temporary pair programming session (Lead/Professor only)")
    @app_commands.describe(dev1="First developer", dev2="Second developer", topic="Topic or ticket ID")
    @app_commands.guild_only()
    @staff_only()
    async def pair(self, interaction: discord.Interaction, dev1: discord.Member, dev2: discord.Member, topic: str = "pairing") -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        guild = interaction.guild
        name = f"{_PAIR_PREFIX}{topic[:30]}"

        text_channel = await guild.create_text_channel(
            name=name,
            topic=f"{_PAIR_TOPIC_PREFIX}{topic}",
            reason="Auto-created pair session"
        )
        vc = await guild.create_voice_channel(
            name=f"{_PAIR_VOICE_PREFIX}{name}",
            reason="Auto-created pair session"
        )

        await text_channel.send(
            f"{dev1.mention} {dev2.mention} — your pair session is ready!\n"
            f"Voice: {vc.mention}\nThis channel auto-deleted in 2 hours"
        )

        for channel in (text_channel, vc):
            self._schedule_pair_cleanup(channel)

        await interaction.followup.send(f"Pair session created: {text_channel.mention}", ephemeral=True)

    # Pair session cleanup

    def _schedule_pair_cleanup(self, channel: discord.abc.GuildChannel) -> None:
        scheduler = getattr(self.bot, "scheduler", None)
        if scheduler is None:
            return
        # A run_date already in the past fires immediately.
        scheduler.add_job(
            _delete_pair_channel,
            "date",
            run_date=channel.created_at + _PAIR_LIFETIME,
            args=[channel.id, self.bot],
            id=f"pair_cleanup_{channel.id}",
            replace_existing=True,
            misfire_grace_time=None
        )

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Cleanup jobs live in memory, so re-create them for sessions that outlived a restart.
        restored = 0
        for guild in self.bot.guilds:
            for channel in [*guild.text_channels, *guild.voice_channels]:
                if _is_pair_channel(channel):
                    self._schedule_pair_cleanup(channel)
                    restored += 1
        if restored:
            log.info("stuck.pair_cleanup.restored", channels=restored)

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
                    "⏰ **15 minutes** — Still stuck? Tag a teammate or request a pair session with `/stuck pair`.",
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

            await self._dm_leads(
                f"⚠️ **{thread.problem[:80]}** — dev has been stuck for 30+ min.\n"
                f"Thread: <#{thread.discord_thread_id}>",
                int(thread.discord_thread_id) if thread.discord_thread_id else None,
            )

        if threads_15 or threads_30:
            log.info("stuck_check.done", bumped=len(threads_15), escalated=len(threads_30))

    async def _send_thread_message(self, thread_id: int, content: str) -> None:
        try:
            thread = await self.bot.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                await thread.send(content)
        except (discord.NotFound, discord.Forbidden):
            pass

    async def _dm_leads(self, message: str, thread_id: int | None) -> None:
        if thread_id is None:
            return

        try:
            channel = await self.bot.fetch_channel(thread_id)
        except (discord.NotFound, discord.Forbidden):
            return

        if not isinstance(channel, discord.Thread) or channel.guild is None:
            return

        guild = channel.guild
        enrollment_svc = EnrollmentService(database.get_db())
        notification_svc = NotificationService(database.get_db())
        targets = await enrollment_svc.get_feature_targets(
            str(guild.id), "stuck", notification_svc
        )

        for member in targets:
            if member.role not in _LEAD_PROFESSOR_ROLES:
                continue
            await send_notification_dm(
                self.bot,
                discord_id=member.discord_id,
                member_id=member.id,
                guild=guild,
                feature="stuck",
                body=message,
                notification_svc=notification_svc,
            )


def _is_pair_channel(channel: discord.abc.GuildChannel) -> bool:
    """Recognise channels made by /stuck pair from the markers it stamps on them."""
    if isinstance(channel, discord.TextChannel):
        return channel.name.startswith(_PAIR_PREFIX) and (channel.topic or "").startswith(_PAIR_TOPIC_PREFIX)
    if isinstance(channel, discord.VoiceChannel):
        return channel.name.startswith(f"{_PAIR_VOICE_PREFIX}{_PAIR_PREFIX}")
    return False


async def _delete_pair_channel(channel_id: int, bot) -> None:
    try:
        channel = await bot.fetch_channel(channel_id)
        await channel.delete(reason="Pair session expired (2h)")
    except (discord.NotFound, discord.Forbidden):
        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StuckCog(bot))