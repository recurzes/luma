from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

import discord
import structlog
from discord.ext import commands

from app import database
from app.config import settings
from app.services.member_service import MemberService

log = structlog.get_logger()

_MOOD_LOOKUP: dict[str, int] = {}
for _n in range(1, 6):
    _MOOD_LOOKUP[str(_n)] = _n
    _MOOD_LOOKUP[f"{_n}\ufe0f\u20e3"] = _n
    _MOOD_LOOKUP[f"{_n}\u20e3"] = _n
_MOOD_LOOKUP.update({"1️⃣": 1, "2️⃣": 2, "3️⃣": 3, "4️⃣": 4, "5️⃣": 5})

MOOD_REACTION_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")

_mood_state: dict[int, str | int] = {}
_mood_prompt_by_msg: dict[int, int] = {}


def _mood_score_from_emoji(emoji: discord.PartialEmoji) -> int | None:
    if emoji.id is not None:
        return None
    name = emoji.name
    if name in _MOOD_LOOKUP:
        return _MOOD_LOOKUP[name]
    if len(name) == 1 and name.isdigit():
        n = int(name)
        if 1 <= n <= 5:
            return n
    return None


class MonitoringCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._db = database.get_db()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if self.bot.user and payload.user_id == self.bot.user.id:
            return
        expected_user = _mood_prompt_by_msg.get(payload.message_id)
        if expected_user is None:
            return
        if payload.user_id != expected_user:
            return
        if _mood_state.get(expected_user) != "pending":
            return
        score = _mood_score_from_emoji(payload.emoji)
        if score is None:
            return
        _mood_state[expected_user] = score
        del _mood_prompt_by_msg[payload.message_id]

        try:
            ch = await self.bot.fetch_channel(payload.channel_id)
        except (discord.NotFound, discord.Forbidden, OSError):
            return
        if isinstance(ch, discord.DMChannel):
            await ch.send("Thanks! Your mood has been recorded anonymously")
        log.info("mood.received", user_id=expected_user, score=score, via="reaction")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return

        user_id = message.author.id
        if user_id not in _mood_state or _mood_state[user_id] != "pending":
            return

        content = message.content.strip()
        if content in {"1", "2", "3", "4", "5"}:
            _mood_state[user_id] = int(content)
            for mid, uid in list(_mood_prompt_by_msg.items()):
                if uid == user_id:
                    del _mood_prompt_by_msg[mid]
                    break
            await message.channel.send("Thanks! Your mood has been recorded anonymously")
            log.info("mood.received", user_id=user_id, score=content, via="message")
        else:
            await message.channel.send("Please react with 1️⃣–5️⃣ on the prompt, or reply with a number 1–5")


    # Scheduled Jobs
    async def _stale_ticket_check(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        db = database.get_db()

        stale = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                db.table("bot_tickets")
                .select("id, title, assignee_id, updated_at")
                .eq("status", "in_progress")
                .lt("updated_at", cutoff)
                .execute()
            )
        )

        if not stale.data:
            return

        task_feed = self.bot.get_text_channel("task_feed")
        if not isinstance(task_feed, discord.TextChannel):
            return

        guild = self.bot.get_guild(settings.DISCORD_GUILD_ID)
        assignee_ids = ({t["assignee_id"] for t in stale.data if t.get("assignee_id")})
        members_by_id: dict[str, dict] = {}
        if assignee_ids:
            mem_res = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: (
                    db.table("bot_members")
                    .select("id, discord_id, discord_name")
                    .in_("id", assignee_ids)
                    .execute()
                )
            )
            members_by_id = {r["id"]: r for r in (mem_res.data or [])}

        for ticket in stale.data:
            assignee_line = ""
            aid = ticket.get("assignee_id")
            if aid and aid in members_by_id:
                m = members_by_id[aid]
                if guild:
                    gm = guild.get_member(int(m["discord_id"]))
                    mention = gm.mention if gm else f"<@{m['discord_id']}>"
                else:
                    mention = f"<@{m['discord_id']}>"
                assignee_line = f"\n**Assignee:** {mention} ({m['discord_name']})"

            embed = discord.Embed(
                title="Stale Ticket Warning",
                description=(
                    f"**{ticket['title']}** has been `in_progress` for 48+ hours"
                    f"with no activity.{assignee_line}\n`id: {str(ticket['id'])[:8]}...`"
                ),
                color=discord.Color.yellow()
            )
            await task_feed.send(embed=embed)
            log.info("stale_ticket.warned", ticket_id=ticket["id"])

    async def _pr_stale_check(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        reviewed_prs: set[int] = set()
        review_events = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                self._db.table("bot_github_events")
                .select("payload")
                .eq("event_type", "pull_request_review")
                .execute()
            )
        )
        for rev in review_events or []:
            pr_num = (rev.get("payload") or {}).get("pull_request", {}).get("number")
            if pr_num is not None:
                reviewed_prs.add(int(pr_num))

        stale_rows = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                self._db.table("bot_pr_reviews")
                .select("pr_number, reviewer_member_id, pr_url")
                .lt("pr_created_at", cutoff)
                .execute()
            )
        )

        rows = stale_rows.data or []
        if not rows:
            return

        code_review = self.bot.get_text_channel("code_review")
        if not isinstance(code_review, discord.TextChannel):
            return

        guild = self.bot.get_guild(settings.DISCORD_GUILD_ID)
        member_svc = MemberService(self._db)

        seen_pr: set[int] = set()
        for row in rows:
            pr_num = int(row["pr_number"])
            if pr_num in seen_pr:
                continue
            seen_pr.add(pr_num)
            if pr_num in reviewed_prs:
                continue

            mention = ""
            rev_uuid = row.get("reviewer_member_id")
            if rev_uuid:
                rev_member = await member_svc.get_by_id(str(rev_uuid))
                if rev_member and guild:
                    gm = guild.get_member(int(rev_member.discord_id))
                    mention = (gm.mention if gm else f"<@{rev_member.discord_id}>") + " "
                elif rev_member:
                    mention = f"<@{rev_member.discord_id}>"

            pr_url = row.get("pr_url") or ""
            msg = (
                f"PR **#{pr_num}** has been open 24+ hours with no review yet — {mention}\n"
                f"{pr_url}"
            )
            await code_review.send(msg)
            log.info("pr_stale.pinged", pr_number=pr_num)

    async def _tip_of_the_day(self) -> None:
        tip_channel = self.bot.get_text_channel("tip_of_the_day")
        if not isinstance(tip_channel, discord.TextChannel):
            return

        tips = settings.DEV_TIPS
        if not tips:
            return
        tip = random.choice(tips)
        embed = discord.Embed(
            title="Tip of the Day",
            description=tip,
            color=discord.Color.teal()
        )
        embed.set_footer(text=f"LumaBot · {datetime.now(timezone.utc).strftime('%A, %B %-d')}")
        await tip_channel.send(embed=embed)
        log.info("tip_of_day.posted")

    async def _mood_checkin_dm(self) -> None:
        global _mood_state, _mood_prompt_by_msg
        _mood_state = {}
        _mood_prompt_by_msg = {}

        members = await MemberService(database.get_db()).get_all_active()
        for m in members:
            try:
                user = await self.bot.fetch_user(int(m.discord_id))
                msg = await user.send(
                    "**Monday Mood Check-in — How's your morale this week?\n**"
                    "React with **1️⃣–5️⃣** below (rough → excellent), or reply with a number **1–5**."
                )
                for emoji in MOOD_REACTION_EMOJIS:
                    await msg.add_reaction(emoji)
                _mood_prompt_by_msg[msg.id] = int(m.discord_id)
                _mood_state[int(m.discord_id)] = "pending"
            except (discord.Forbidden, discord.NotFound):
                pass

        log.info("mood_checkin.dms_sent", count=len(members))

    async def _mood_aggregate_post(self) -> None:
        scores = [v for v in _mood_state.values() if isinstance(v, int)]
        if not scores:
            return

        avg = sum(scores) / len(scores)
        emoji_map = {1: "😞", 2: "😐", 3: "🙂", 4: "😊", 5: "🔥"}
        distribution = {i: scores.count(i) for i in range(1, 6) if scores.count(i) > 0}
        dist_lines = "\n".join(
            f"{emoji_map.get(k, str(k))} **{k}** — {v} response(s)"
            for k, v in sorted(distribution.items())
        )

        general = self.bot.get_text_channel("general")
        if not isinstance(general, discord.TextChannel):
            return

        embed = discord.Embed(
            title="Team Mood Check-in",
            description=f"**Average score:** {avg:.1f} / 5\n**Responses:** {len(scores)}\n\n{dist_lines}",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Anonymous aggregate · LumaBot")
        await general.send(embed=embed)
        log.info("mood_aggregate.posted", avg=round(avg, 2), responses=len(scores))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MonitoringCog(bot))

