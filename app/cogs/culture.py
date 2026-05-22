from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.config import settings
from app.services.badge_service import BadgeService
from app.services.member_service import MemberService
from app.services.xp_service import XPService
from app.utils.badge_broadcast import post_badges_to_shoutouts
from app.utils.guards import require_member

log = structlog.get_logger()

_active_sprint: dict | None = None


class CultureCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _xp(self) -> XPService:
        return XPService(database.get_db())

    def _badge(self) -> BadgeService:
        return BadgeService(database.get_db(), self._xp())


    @app_commands.command(name="shoutout", description="Give a shoutout to a teammate")
    @app_commands.describe(member="Who you're shouting out", reason="Why they deserve it")
    async def shoutout(
            self,
            interaction: discord.Interaction,
            member: discord.Member,
            reason: str
    ) -> None:
        await interaction.response.defer()

        try:
            sender = await require_member(interaction)
        except RuntimeError:
            return

        if member.id == interaction.user.id:
            await interaction.followup.send("You can't shoutout yourself", ephemeral=True)
            return

        db = database.get_db()
        member_svc = MemberService(db)
        receiver = await member_svc.get_by_discord_id(str(member.id))
        xp = self._xp()

        await xp.award(str(sender.id), "shoutout_giver")
        if receiver:
            await xp.award(str(sender.id), "shoutout_recv")

        shoutouts_channel = self.bot.get_text_channel("shoutouts", interaction.guild)

        embed = discord.Embed(
            title="Shoutout",
            description=(
                f"{interaction.user.mention} gives a shoutout to {member.mention}!\n\n"
                f"_{reason}_"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="LumaBot Shoutouts")

        if isinstance(shoutouts_channel, discord.TextChannel):
            await shoutouts_channel.send(embed=embed)
        else:
            await interaction.followup.send(embed=embed)

        badge_svc = self._badge()
        sender_badges = await badge_svc.check_and_award(str(sender.id), "shoutout_given")
        await post_badges_to_shoutouts(self.bot, sender, sender_badges)

        await interaction.followup.send("Shoutout posted!", ephemeral=True)


    @app_commands.command(name="share", description="Share a tip or resource with the team")
    @app_commands.describe(tip="Your tip or resource", link="Optional URL")
    async def share(
            self,
            interaction: discord.Interaction,
            tip: str,
            link: str | None = None
    ) -> None:
        await interaction.response.defer()

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        resources_channel = self.bot.get_text_channel("resources", interaction.guild)

        description = tip
        if link:
            description += f"\n\n[{link}]({link})"

        embed = discord.Embed(
            title="Resource Drop",
            description=description,
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"Shared by {member.discord_name} · React 👍 to upvote")

        if isinstance(resources_channel, discord.TextChannel):
            msg = await resources_channel.send(embed=embed)
            await msg.add_reaction("👍")
            await msg.add_reaction("👎")
        else:
            await interaction.followup.send(embed=embed)

        await self._xp().award(str(member.id), "knowledge_drop")

        badge_svc = self._badge()
        badges = await badge_svc.check_and_award(str(member.id), "knowledge_drop")
        await post_badges_to_shoutouts(self.bot, member, badges)

        await interaction.followup.send("Resource shared!", ephemeral=True)


    @app_commands.command(name="sprint_start", description="Start a sprint challenge (Lead only)")
    @app_commands.describe(name="Sprint name", days="Duration in days")
    async def sprint_start(
            self,
            interaction: discord.Interaction,
            name: str,
            days: int = 7
    ) -> None:
        global _active_sprint
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        if caller.role not in {"lead", "professor"}:
            await interaction.followup.send("Only Lead or Professor can start sprints", ephemeral=True)
            return

        if _active_sprint:
            await interaction.followup.send(
                f"Sprint **{_active_sprint['name']}** is already active. End it first with `/sprint_end`",
                ephemeral=True
            )
            return

        now = datetime.now(timezone.utc)
        _active_sprint = {"name": name, "days": days, "started_at": now, "started_by": str(caller.id)}

        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: (
                    database.get_db().table("bot_sprints")
                    .insert({
                        "name": name,
                        "days": days,
                        "started_by": str(caller.id),
                        "started_at": now.isoformat(),
                        "status": "active"
                    })
                    .execute()
                )
            )
        except Exception as exc:
            log.warning("sprint.db_persist_failed", error=str(exc))

        embed = discord.Embed(
            title=f"Sprint Started — {name}",
            description=(
                f"Duration: **{days} days**\n"
                f"Started by: {interaction.user.mention}\n\n"
                "Close tickets, push commits, help teammates — every action earns XP!"
            ),
            color=discord.Color.green()
        )
        announcements = self.bot.get_text_channel("announcements", interaction.guild)
        if isinstance(announcements, discord.TextChannel):
            await announcements.send(embed=embed)

        await interaction.followup.send(f"Sprint **{name}** started!", ephemeral=True)


    @app_commands.command(name="sprint_end", description="End the active sprint (Lead only)")
    async def sprint_end(self, interaction: discord.Interaction) -> None:
        global _active_sprint
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        if caller.role not in {"lead", "professor"}:
            await interaction.followup.send("Only Lead or Professor can end sprints", ephemeral=True)
            return

        if not _active_sprint:
            await interaction.followup.send("No active sprint", ephemeral=True)
            return

        sprint_name = _active_sprint["name"]
        started_at = _active_sprint["started_at"]
        elapsed = (datetime.now(timezone.utc) - started_at).days

        stats = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                database.get_db().table("bot_member_stats")
                .select("member_id, total_xp")
                .order("total_xp", desc=True)
                .limit(5)
                .execute()
            )
        )

        _active_sprint = None

        lines = [f"**{r['member_id'][:8]}…** — {r['total_xp']} XP" for r in (stats.data or [])]
        embed = discord.Embed(
            title=f"Sprint Ended — {sprint_name}",
            description=f"Duration: {elapsed} day(s)\n\nTop performers:\n" + "\n".join(lines or ["—"]),
            color=discord.Color.orange()
        )
        announcements = self.bot.get_text_channel("announcements", interaction.guild)
        if isinstance(announcements, discord.TextChannel):
            await announcements.send(embed=embed)

        await interaction.followup.send("Sprint ended. Summary posted!", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CultureCog(bot))