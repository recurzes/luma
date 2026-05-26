from __future__ import annotations

import discord
import structlog
import asyncio
from discord import app_commands
from discord.ext import commands

from app import database
from app.config import settings
from app.embeds.phase_embed import build_completion_ceremony, build_phase_embed
from app.services.member_service import MemberService
from app.services.phase_service import PhaseService
from app.utils.guards import require_member

log = structlog.get_logger()


@app_commands.guild_only()
class PhaseCog(commands.GroupCog, name="phase"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _svc(self) -> PhaseService:
        return PhaseService(database.get_db())


    @app_commands.command(name="current", description="Show the active phase with criteria checklist")
    async def current(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        svc = self._svc()
        phase = await svc.get_current()
        if phase is None:
            await interaction.followup.send("No active phase found", ephemeral=True)
            return

        criteria = await svc.get_criteria(str(phase.id))

        db = database.get_db()
        open_res = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                db.table("bot_tickets")
                .select("id", count="exact")
                .eq("phase", phase.key)
                .neq("status", "done")
                .execute()
            )
        )
        closed_res = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: (
                db.table("bot_tickets")
                .select("id", count="exact")
                .eq("phase", phase.key)
                .eq("status", "done")
                .execute()
            )
        )

        embed = build_phase_embed(
            phase,
            criteria,
            open_count=open_res.count or 0,
            closed_count=closed_res.count or 0
        )
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="criteria", description="Check off a phase exit criterion")
    @app_commands.describe(item_number="1-based criterion number from /phase current")
    async def criteria(self, interaction: discord.Interaction, item_number: int) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        svc = self._svc()
        phase = await svc.get_current()
        if phase is None:
            await interaction.followup.send("No active phase.", ephemeral=True)
            return

        updated = await svc.check_criterion(str(phase.id), item_number, str(caller.id))
        if updated is None:
            await interaction.followup.send(
                f"Item {item_number} not found. Check `/phase current` for valid numbers",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            f"✅ Criterion {item_number} marked complete: _{updated.description}_",
            ephemeral=True
        )

        tracker_channel = self.bot.get_text_channel("phase-tracker", interaction.guild)
        if isinstance(tracker_channel, discord.TextChannel):
            criteria = await svc.get_criteria(str(phase.id))
            embed = build_phase_embed(phase, criteria)
            await tracker_channel.send(embed=embed)


    @app_commands.command(name="complete", description="Complete the active phase (Lead only)")
    async def complete(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        if caller.role not in {"lead", "professor"}:
            await interaction.followup.send("Only Lead of Professor can complete a phase", ephemeral=True)
            return

        svc = self._svc()
        phase = await svc.get_current()
        if phase is None:
            await interaction.followup.send("No active phase to complete", ephemeral=True)
            return

        completed = await svc.complete_phase(phase.key, str(caller.id))
        if completed is None:
            await interaction.followup.send("Failed to complete phase", ephemeral=True)
            return

        summary = await svc.phase_summary(phase.key)
        embed = build_completion_ceremony(phase, summary)

        announcements = self.bot.get_text_channel("announcements", interaction.guild)
        if isinstance(announcements, discord.TextChannel):
            await announcements.send(embed=embed)
        else:
            await interaction.followup.send(embed=embed)

        await interaction.followup.send(
            f"Phase **{phase.name}** marked complete. Ceremony posted to #announcements",
            ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PhaseCog(bot))
