from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta, timezone

import discord
import structlog
from discord.ext import commands

from app import database
from app.cogs.standup import has_pending_standup
from app.config import settings
from app.services.enrollment_service import EnrollmentService
from app.services.member_service import MemberService
from app.services.notification_service import NotificationService
from app.utils.db import run_query
from app.utils.dm import format_dm, send_notification_dm

log = structlog.get_logger()

_MOOD_LOOKUP: dict[str, int] = {}
for _n in range(1, 6):
    _MOOD_LOOKUP[str(_n)] = _n
    _MOOD_LOOKUP[f"{_n}\ufe0f\u20e3"] = _n
    _MOOD_LOOKUP[f"{_n}\u20e3"] = _n
_MOOD_LOOKUP.update({"1️⃣": 1, "2️⃣": 2, "3️⃣": 3, "4️⃣": 4, "5️⃣": 5})

MOOD_REACTION_EMOJIS = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣")

# Mood check-ins are per server. A user in two servers gets two prompts.
# prompt message id -> (guild id, user id), while the prompt is unanswered
_mood_prompts: dict[int, tuple[int, int]] = {}
# guild id -> {user id: score}
_mood_scores: dict[int, dict[int, int]] = {}


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
        prompt = _mood_prompts.get(payload.message_id)
        if prompt is None:
            return
        guild_id, expected_user = prompt
        if payload.user_id != expected_user:
            return
        score = _mood_score_from_emoji(payload.emoji)
        if score is None:
            return
        _mood_scores.setdefault(guild_id, {})[expected_user] = score
        del _mood_prompts[payload.message_id]

        try:
            ch = await self.bot.fetch_channel(payload.channel_id)
        except (discord.NotFound, discord.Forbidden, OSError):
            return
        if isinstance(ch, discord.DMChannel):
            await ch.send("Thanks! Your mood has been recorded anonymously")
        # No user ID here: the score is promised to be anonymous.
        log.info("mood.received", guild_id=guild_id, via="reaction")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not isinstance(message.channel, discord.DMChannel):
            return

        user_id = message.author.id
        pending = sorted(mid for mid, (_, uid) in _mood_prompts.items() if uid == user_id)
        if not pending:
            return
        # A DM sent mid-standup is a standup answer, not a mood score.
        if has_pending_standup(user_id):
            return

        content = message.content.strip()
        if content in {"1", "2", "3", "4", "5"}:
            # A typed number answers the oldest unanswered prompt.
            guild_id, _ = _mood_prompts.pop(pending[0])
            _mood_scores.setdefault(guild_id, {})[user_id] = int(content)
            await message.channel.send("Thanks! Your mood has been recorded anonymously")
            log.info("mood.received", guild_id=guild_id, via="message")
        else:
            await message.channel.send("Please react with 1️⃣–5️⃣ on the prompt, or reply with a number 1–5")


    # Scheduled Jobs
    async def _stale_ticket_check(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()

        stale = await run_query(
            self._db.table("bot_tickets")
            .select("id, guild_id, title, assignee_id, updated_at")
            .eq("status", "in_progress")
            .lt("updated_at", cutoff)
        )
        if not stale.data:
            return

        assignee_ids = list({t["assignee_id"] for t in stale.data if t.get("assignee_id")})
        members_by_id: dict[str, dict] = {}
        if assignee_ids:
            mem_res = await run_query(
                self._db.table("bot_members")
                .select("id, discord_id, discord_name")
                .in_("id", assignee_ids)
            )
            members_by_id = {r["id"]: r for r in (mem_res.data or [])}

        for ticket in stale.data:
            guild = self.bot.get_guild(int(ticket["guild_id"]))
            channel = self.bot.get_text_channel("task_feed", guild) if guild else None
            if not isinstance(channel, discord.TextChannel):
                continue

            assignee_line = ""
            m = members_by_id.get(ticket.get("assignee_id"))
            if m:
                assignee_line = f"\n**Assignee:** <@{m['discord_id']}> ({m['discord_name']})"

            embed = discord.Embed(
                title="Stale Ticket Warning",
                description=(
                    f"**{ticket['title']}** has been `in_progress` for 48+ hours "
                    f"with no activity.{assignee_line}\n`id: {str(ticket['id'])[-8:]}`"
                ),
                color=discord.Color.yellow()
            )
            await channel.send(embed=embed)
            log.info("stale_ticket.warned", ticket_id=ticket["id"], guild_id=ticket["guild_id"])

    async def _pr_stale_check(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        stale_rows = await run_query(
            self._db.table("bot_pr_reviewers")
            .select("guild_id, repo_full_name, pr_number, reviewer_member_id, pr_url")
            .lt("pr_created_at", cutoff)
        )
        rows = stale_rows.data or []
        if not rows:
            return

        reviewed: set[tuple[str, int]] = set()
        review_events = await run_query(
            self._db.table("bot_github_events")
            .select("payload")
            .eq("event_type", "pull_request_review")
        )
        for rev in (review_events.data or []):
            payload = rev.get("payload") or {}
            pr_num = payload.get("pull_request", {}).get("number")
            repo = (payload.get("repository") or {}).get("full_name", "")
            if pr_num is not None:
                reviewed.add((repo.lower(), int(pr_num)))

        member_svc = MemberService(self._db)

        for row in rows:
            pr_num = int(row["pr_number"])
            if (row["repo_full_name"].lower(), pr_num) in reviewed:
                continue

            guild = self.bot.get_guild(int(row["guild_id"]))
            channel = self.bot.get_text_channel("code_review", guild) if guild else None
            if not isinstance(channel, discord.TextChannel):
                continue

            mention = ""
            rev_uuid = row.get("reviewer_member_id")
            if rev_uuid:
                rev_member = await member_svc.get_by_id(str(rev_uuid))
                if rev_member:
                    mention = f"<@{rev_member.discord_id}> "

            await channel.send(
                f"PR **#{pr_num}** has been open 24+ hours with no review yet — {mention}\n"
                f"{row.get('pr_url') or ''}"
            )
            log.info("pr_stale.pinged", pr_number=pr_num, guild_id=row["guild_id"])

    async def _tip_of_the_day(self) -> None:
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

        posted = 0
        for guild in self.bot.guilds:
            tip_channel = self.bot.get_text_channel("tip_of_the_day", guild)
            if isinstance(tip_channel, discord.TextChannel):
                await tip_channel.send(embed=embed)
                posted += 1

        if posted:
            log.info("tip_of_day.posted", posted=posted)

    async def _mood_checkin_dm(self) -> None:
        _mood_prompts.clear()
        _mood_scores.clear()

        enrollment_svc = EnrollmentService(database.get_db())
        notification_svc = NotificationService(database.get_db())
        sent = 0

        body = (
            "**Monday Mood Check-in — How's your morale this week?**\n"
            "React with **1️⃣–5️⃣** below (rough → excellent), or reply with a number **1–5**."
        )

        for guild in self.bot.guilds:
            targets = await enrollment_svc.get_feature_targets(
                str(guild.id), "mood", notification_svc
            )
            for member in targets:
                try:
                    user = await self.bot.fetch_user(int(member.discord_id))
                    msg = await user.send(format_dm(guild.name, body))
                    for emoji in MOOD_REACTION_EMOJIS:
                        await msg.add_reaction(emoji)
                    _mood_prompts[msg.id] = (guild.id, int(member.discord_id))
                    sent += 1
                except (discord.Forbidden, discord.NotFound):
                    pass

        log.info("mood_checkin.dms_sent", count=sent)

    async def _mood_aggregate_post(self) -> None:
        emoji_map = {1: "😞", 2: "😐", 3: "🙂", 4: "😊", 5: "🔥"}
        posted = 0

        for guild in self.bot.guilds:
            scores = list(_mood_scores.get(guild.id, {}).values())
            general = self.bot.get_text_channel("general", guild)
            if not scores or not isinstance(general, discord.TextChannel):
                continue

            avg = sum(scores) / len(scores)
            distribution = {i: scores.count(i) for i in range(1, 6) if scores.count(i) > 0}
            dist_lines = "\n".join(
                f"{emoji_map.get(k, str(k))} **{k}** — {v} response(s)"
                for k, v in sorted(distribution.items())
            )

            embed = discord.Embed(
                title="Team Mood Check-in",
                description=f"**Average score:** {avg:.1f} / 5\n**Responses:** {len(scores)}\n\n{dist_lines}",
                color=discord.Color.blue()
            )
            embed.set_footer(text="Anonymous aggregate · LumaBot")
            await general.send(embed=embed)
            posted += 1

        log.info("mood_aggregate.posted", posted=posted)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MonitoringCog(bot))

