from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog
from discord.ext import commands

from app import database
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

        posted = 0
        for guild in self.bot.guilds:
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
        non_resp = await svc.non_responders(str(session.id))

        if not non_resp:
            return

        mentions = " ".join(
            f"<@{m.discord_id}>" for m in non_resp
        )

        pinged = 0
        for guild in self.bot.guilds:
            channel = self.bot.get_text_channel("standup_log", guild)
            if not isinstance(channel, discord.TextChannel):
                continue
            await channel.send(
                f"⏰ Standup reminder! Still waiting on: {mentions}\n"
                "Reply to your standup DM or the window closes at 9:30 AM."
            )
            pinged += 1

        log.info("job.standup_nag.done", pinged=pinged)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StandupCog(bot))