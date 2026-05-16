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

        task_feed = self.bot.get_channel(settings.CHANNEL_TASK_FEED)
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