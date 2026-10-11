from __future__ import annotations

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
from app.utils.db import run_query
from app.utils.guards import require_member, staff_only

log = structlog.get_logger()

# /shoutout and /share each award XP, so cap them per user: 3 uses per hour.
_XP_COMMAND_RATE = 3
_XP_COMMAND_PER_SECONDS = 3600.0


@app_commands.guild_only()
class CultureCog(commands.GroupCog, name="culture"):
    sprint = app_commands.Group(name="sprint", description="Sprint challenge commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    def _xp(self) -> XPService:
        return XPService(database.get_db())

    def _badge(self) -> BadgeService:
        return BadgeService(database.get_db(), self._xp())


    @app_commands.command(name="shoutout", description="Give a shoutout to a teammate")
    @app_commands.describe(member="Who you're shouting out", reason="Why they deserve it")
    @app_commands.checks.cooldown(_XP_COMMAND_RATE, _XP_COMMAND_PER_SECONDS, key=lambda i: i.user.id)
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
        receiver = await member_svc.get_by_discord_id(str(member.id), str(interaction.guild_id))
        xp = self._xp()

        await xp.award(str(sender.id), "shoutout_given")
        if receiver:
            await xp.award(str(receiver.id), "shoutout_recv")

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
    @app_commands.checks.cooldown(_XP_COMMAND_RATE, _XP_COMMAND_PER_SECONDS, key=lambda i: i.user.id)
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


    async def _active_sprint(self, guild_id: str) -> dict | None:
        result = await run_query(
            database.get_db().table("bot_sprints")
            .select("*")
            .eq("guild_id", guild_id)
            .eq("status", "active")
            .order("started_at", desc=True)
            .limit(1)
        )
        return result.data[0] if result.data else None

    @sprint.command(name="start", description="Start a sprint challenge (Lead/Professor only)")
    @app_commands.describe(name="Sprint name", days="Duration in days")
    @staff_only()
    async def sprint_start(
            self,
            interaction: discord.Interaction,
            name: str,
            days: int = 7
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        guild_id = str(interaction.guild_id)
        active = await self._active_sprint(guild_id)
        if active:
            await interaction.followup.send(
                f"Sprint **{active['name']}** is already active. End it first with `/culture sprint end`",
                ephemeral=True
            )
            return

        await run_query(
            database.get_db().table("bot_sprints")
            .insert({
                "guild_id": guild_id,
                "name": name,
                "days": days,
                "started_by": str(caller.id),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "active"
            })
        )

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


    @sprint.command(name="end", description="End the active sprint (Lead/Professor only)")
    @staff_only()
    async def sprint_end(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await require_member(interaction)
        except RuntimeError:
            return

        guild_id = str(interaction.guild_id)
        active = await self._active_sprint(guild_id)
        if not active:
            await interaction.followup.send("No active sprint", ephemeral=True)
            return

        now = datetime.now(timezone.utc)
        await run_query(
            database.get_db().table("bot_sprints")
            .update({"status": "ended", "ended_at": now.isoformat()})
            .eq("id", active["id"])
        )
        elapsed = (now - datetime.fromisoformat(active["started_at"])).days

        top = await self._xp().leaderboard(guild_id, limit=5)
        lines = [f"**{e.discord_name}** — {e.total_xp} XP" for e in top]
        embed = discord.Embed(
            title=f"Sprint Ended — {active['name']}",
            description=f"Duration: {elapsed} day(s)\n\nTop performers:\n" + "\n".join(lines or ["—"]),
            color=discord.Color.orange()
        )
        announcements = self.bot.get_text_channel("announcements", interaction.guild)
        if isinstance(announcements, discord.TextChannel):
            await announcements.send(embed=embed)

        await interaction.followup.send("Sprint ended. Summary posted!", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CultureCog(bot))