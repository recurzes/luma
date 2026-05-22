from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog
from discord.ext import commands

from app import database
from app.config import settings
from app.embeds.standup_embed import build_standup_summary
from app.services.member_service import MemberService
from app.services.standup_service import StandupService
from app.services.xp_service import XPService
from app.utils.badge_broadcast import post_badges_to_shoutouts

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
        all_members = await MemberService(database.get_db()).get_all_active()

        for member in all_members:
            discord_id = int(member.discord_id)
            if discord_id in _PENDING:
                continue

            try:
                user = await self.bot.fetch_user(discord_id)
                await user.send(
                    "☀️ **Good morning! Time for your daily standup.**\n\n" + _QUESTIONS[0]
                )
                _PENDING[discord_id] = {
                    "session_id": str(session.id),
                    "member_id": str(member.id),
                    "stage": 0,
                    "yesterday": None,
                    "today": None,
                    "blockers": None
                }
                log.info("standup.dm_sent", discord_id=discord_id)
            except (discord.Forbidden, discord.NotFound):
                log.warning("standup.dm_failed", discord_id=discord_id)

        log.info("job.standup_dm.done", members=len(all_members))

    async def _standup_compile_job(self) -> None:
        log.info("job.standup_compile.start")
        svc = self._svc()
        session = await svc.get_or_create_today()
        responses = await svc.get_responses(str(session.id))
        non_resp = await svc.non_responders(str(session.id))

        all_members = await MemberService(database.get_db()).get_all_active()
        member_map = {str(m.id): m.discord_name for m in all_members}

        embed = build_standup_summary(session, responses, non_resp, member_map)

        guild = self.bot.get_guild(settings.DISCORD_GUILD_ID)
        if guild is None:
            return
        channel = guild.get_channel(settings.CHANNEL_STANDUP_LOG)
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=embed)
            await svc.mark_posted(str(session.id))

        log.info("job.standup_compile.done", responses=len(responses))

    async def _standup_nag_job(self) -> None:
        log.info("job.standup_nag.start")
        svc = self._svc()
        session = await svc.get_or_create_today()
        non_resp = await svc.non_responders(str(session.id))

        if not non_resp:
            return

        guild = self.bot.get_guild(settings.DISCORD_GUILD_ID)
        if guild is None:
            return
        channel = guild.get_channel(settings.CHANNEL_STANDUP_LOG)
        if not isinstance(channel, discord.TextChannel):
            return

        mentions = " ".join(
            f"<@{m.discord_id}>" for m in non_resp
        )
        await channel.send(
            f"⏰ Standup reminder! Still waiting on: {mentions}\n"
            "Reply to your standup DM or the window closes at 9:30 AM."
        )
        log.info("job.standup_nag.done", pinged=len(non_resp))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StandupCog(bot))