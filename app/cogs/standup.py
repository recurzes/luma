from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog
from discord.ext import commands

from app import database
from app.embeds.standup_embed import build_standup_summary
from app.services.enrollment_service import EnrollmentService
from app.services.member_service import MemberService
from app.services.notification_service import NotificationService
from app.services.standup_service import StandupService
from app.services.xp_service import XPService
from app.utils.badge_broadcast import post_badges_to_shoutouts
from app.utils.dm import send_notification_dm

if TYPE_CHECKING:
    pass

log = structlog.get_logger()

_PENDING: dict[int, dict] = {}

_QUESTIONS = [
    "**1. What did you complete yesterday?**",
    "**2. What are you working on today?**",
    "**3. Any blockers?** (reply 'none' if not)",
]


class StandupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _svc(self) -> StandupService:
        db = database.get_db()
        return StandupService(db, MemberService(db), XPService(db))

    # State Machine

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is not None:
            return
        if message.author.bot:
            return

        user_id = message.author.id
        state = _PENDING.get(user_id)
        if state is None:
            return

        stage = state["stage"]
        content = message.content.strip()

        if stage == 0:
            stage["yesterday"] = content
            state["stage"] = 1
            await message.channel.send(_QUESTIONS[1])

        elif stage == 1:
            state["today"] = content
            state["stage"] = 2
            await message.channel.send(_QUESTIONS[2])

        elif stage == 2:
            state["blockers"] = content

            svc = self._svc()

            try:
                _, badges = await svc.save_response(
                    session_id=state["session_id"],
                    member_id=state["member_id"],
                    yesterday=state["yesterday"],
                    today=state["today"],
                    blockers=state["blockers"]
                )
                await message.channel.send(
                    "Got it — your standup has been recorded. ✅"
                )
                if badges:
                    m = await MemberService(database.get_db()).get_by_id(state["member_id"])
                    if m:
                        await post_badges_to_shoutouts(self.bot, m, badges)
                log.info("standup.response_collected", discord_id=user_id)

            except Exception as e:
                log.error("standup.save_error", error=str(e))
                await message.channel.send(
                    "Something went wrong saving your standup. Please try again or let the Lead know"
                )
            finally:
                _PENDING.pop(user_id, None)

    # Scheduled Jobs

    async def _standup_dm_job(self) -> None:
        log.info("job.standup_dm.start")
        svc = self._svc()
        session = await svc.get_or_create_today()
        enrollment_svc = EnrollmentService(database.get_db())
        notification_svc = NotificationService(database.get_db())
        sent = 0

        for guild in self.bot.guilds:
            targets = await enrollment_svc.get_feature_targets(
                str(guild.id), "standup", notification_svc
            )
            for member in targets:
                discord_id = int(member.discord_id)
                if discord_id in _PENDING:
                    continue

                body = "☀️ **Good morning! Time for your daily standup.**\n\n" + _QUESTIONS[0]
                if await send_notification_dm(
                        self.bot,
                        discord_id=member.discord_id,
                        member_id=member.id,
                        guild=guild,
                        feature="standup",
                        body=body,
                        notification_svc=notification_svc,
                ):
                    _PENDING[discord_id] = {
                        "session_id": str(session.id),
                        "member_id": str(member.id),
                        "guild_id": str(guild.id),
                        "guild_name": guild.name,
                        "stage": 0,
                        "yesterday": None,
                        "today": None,
                        "blockers": None,
                    }
                    sent += 1
                    log.info("standup.dm_sent", discord_id=discord_id, guild_id=guild.id)

        log.info("job.standup_dm.done", sent=sent)

    async def _standup_compile_job(self) -> None:
        log.info("job.standup_compile.start")
        svc = self._svc()
        session = await svc.get_or_create_today()
        responses = await svc.get_responses(str(session.id))
        enrollment_svc = EnrollmentService(database.get_db())
        notification_svc = NotificationService(database.get_db())

        responded_ids = {str(r.member_id) for r in responses}
        posted = 0

        for guild in self.bot.guilds:
            targets = await enrollment_svc.get_feature_targets(
                str(guild.id), "standup", notification_svc
            )
            if not targets:
                continue

            target_ids = {str(m.id) for m in targets}
            guild_responses = [r for r in responses if str(r.member_id) in target_ids]
            guild_non_resp = [m for m in targets if str(m.id) not in responded_ids]
            member_map = {str(m.id): m.discord_name for m in targets}

            embed = build_standup_summary(session, guild_responses, guild_non_resp, member_map)

            channel = self.bot.get_text_channel("standup_log", guild)
            if isinstance(channel, discord.TextChannel):
                await channel.send(embed=embed)
                posted += 1

        if posted:
            await svc.mark_posted(str(session.id))

        log.info("job.standup_compile.done", responses=len(responses), posted=posted)

    async def _standup_nag_job(self) -> None:
        log.info("job.standup_nag.start")
        svc = self._svc()
        session = await svc.get_or_create_today()
        responses = await svc.get_responses(str(session.id))
        responded_ids = {str(r.member_id) for r in responses}

        enrollment_svc = EnrollmentService(database.get_db())
        notification_svc = NotificationService(database.get_db())
        pinged = 0

        for guild in self.bot.guilds:
            channel = self.bot.get_text_channel("standup_log", guild)
            if not isinstance(channel, discord.TextChannel):
                continue

            targets = await enrollment_svc.get_feature_targets(
                str(guild.id), "standup", notification_svc
            )
            guild_non_resp = [m for m in targets if str(m.id) not in responded_ids]

            if not guild_non_resp:
                continue

            mentions = " ".join(f"<@{m.discord_id}>" for m in guild_non_resp)
            await channel.send(
                f"⏰ Standup reminder! Still waiting on: {mentions}\n"
                "Reply to your standup DM or the window closes at 9:30 AM."
            )
            pinged += 1

        log.info("job.standup_nag.done", pinged=pinged)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StandupCog(bot))