from __future__ import annotations

import asyncio

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.config import settings
from app.services.member_service import MemberService
from app.services.ticket_service import TicketService
from app.utils.guards import require_member, staff_only

log = structlog.get_logger()


@app_commands.guild_only()
class ReviewCog(commands.GroupCog, name="review"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()


    @app_commands.command(name="assign", description="Manually assign a ticket's reviewer (Lead/Professor only)")
    @app_commands.describe(dev="Member to assign as reviewer", ticket_id="Ticket ID (last 8 chars or full UUID)")
    @staff_only()
    async def assign(
            self,
            interaction: discord.Interaction,
            dev: discord.Member,
            ticket_id: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        db = database.get_db()
        members = MemberService(db)
        reviewer = await members.get_by_discord_id(str(dev.id), str(interaction.guild_id))
        if reviewer is None:
            await interaction.followup.send(f"{dev.display_name} is not a registered member", ephemeral=True)
            return

        try:
            ticket = await TicketService(db, members, str(interaction.guild_id)).get(ticket_id)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        if ticket is None:
            await interaction.followup.send(f"No ticket found for `{ticket_id}`", ephemeral=True)
            return
        short_id = str(ticket.id)[-8:]

        updated = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                db.table("bot_tickets")
                .update({"reviewer_id": str(reviewer.id)})
                .eq("id", str(ticket.id))
                .execute()
            )
        )
        if not updated.data:
            await interaction.followup.send("Failed to update reviewer", ephemeral=True)
            return

        code_review = self.bot.get_text_channel("code_review", interaction.guild)
        if isinstance(code_review, discord.TextChannel):
            await code_review.send(
                f"📋 Ticket `{short_id}` reviewer manually set to {dev.mention} "
                f"(by {interaction.user.mention})"
            )

        await interaction.followup.send(
            f"Reviewer for ticket `{short_id}` set to **{reviewer.discord_name}**",
            ephemeral=True
        )
        log.info("review.assigned", ticket=str(ticket.id), reviewer=str(reviewer.id), by=str(caller.id))


    @app_commands.command(name="stats", description="Show PR review counts per dev this sprint")
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        db = database.get_db()

        # Members are per server, so limiting to this server's members limits the stats to it.
        guild_members = await MemberService(db).get_all_active(str(interaction.guild_id))
        guild_member_ids = [str(m.id) for m in guild_members]
        if not guild_member_ids:
            await interaction.followup.send("No reviews recorded yet")
            return

        ledger = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                db.table("bot_xp_ledger")
                .select("member_id")
                .eq("action", "pr_reviewed")
                .in_("member_id", guild_member_ids)
                .execute()
            )
        )

        counts: dict[str, int] = {}
        for row in ledger.data:
            mid = row["member_id"]
            counts[mid] = counts.get(mid, 0) + 1

        if not counts:
            await interaction.followup.send("No reviews recorded yet")
            return

        names = {str(m.id): m.discord_name for m in guild_members}

        sorted_devs = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        lines = [
            f"{i + 1}. **{names.get(mid, mid[:8])}** — {cnt} reviews(s)"
            for i, (mid, cnt) in enumerate(sorted_devs)
        ]

        embed = discord.Embed(
            title="Review Stats",
            description="\n".join(lines),
            color=discord.Color.blue()
        )
        embed.set_footer(text="All-time review counts · /review stats")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReviewCog(bot))