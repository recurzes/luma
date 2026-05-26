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
from app.utils.guards import require_member

log = structlog.get_logger()


@app_commands.guild_only()
class ReviewCog(commands.GroupCog, name="review"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot


    @app_commands.command(name="assign", description="Manually assign a PR reviewer (Lead/Professor only)")
    @app_commands.describe(dev="Member to assign as reviewer", pr_number="GitHub PR number or ticket ID suffix")
    async def assign(
            self,
            interaction: discord.Interaction,
            dev: discord.Member,
            pr_number: str
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        if caller.role not in {"lead", "professor"}:
            await interaction.followup.send("Only Lead or Professor can assign reviewers", ephemeral=True)
            return

        db = database.get_db()
        reviewer = await MemberService(db).get_by_discord_id(str(dev.id))
        if reviewer is None:
            await interaction.followup.send(f"{dev.display_name} is not a registered member", ephemeral=True)
            return

        ticket_svc = TicketService(db)
        ticket = await ticket_svc.get(pr_number)
        if ticket is None:
            await interaction.followup.send(f"No ticket found for `{pr_number}`", ephemeral=True)
            return

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
                f"📋 PR `{pr_number}` reviewer manually set to {dev.mention} "
                f"(by {interaction.user.mention})"
            )

        await interaction.followup.send(
            f"Reviewer for `{pr_number}` set to **{reviewer.discord_name}**",
            ephemeral=True
        )
        log.info("review.assigned", ticket=pr_number, reviewer=str(reviewer.id), by=str(caller.id))


    @app_commands.command(name="stats", description="Show PR review counts per dev this sprint")
    async def stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        db = database.get_db()

        ledger = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                db.table("bot_xp_ledger")
                .select("member_id")
                .eq("action", "pr_reviewed")
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

        member_ids = list(counts.keys())
        names_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                db.table("bot_members")
                .select("id, discord_name")
                .in_("id", member_ids)
                .execute()
            )
        )
        names = {r["id"]: r["discord_name"] for r in names_result.data}

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