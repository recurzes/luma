from __future__ import annotations

import re

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.embeds.phase_embed import build_completion_ceremony, build_phase_embed
from app.services.phase_service import PhaseService
from app.utils.guards import require_member, staff_only

log = structlog.get_logger()

_KEY_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,30}")


@app_commands.guild_only()
class PhaseCog(commands.GroupCog, name="phase"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    def _svc(self, interaction: discord.Interaction) -> PhaseService:
        return PhaseService(database.get_db(), str(interaction.guild_id))


    @app_commands.command(name="current", description="Show the active phase with criteria checklist")
    async def current(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        svc = self._svc(interaction)
        phase = await svc.get_current()
        if phase is None:
            await interaction.followup.send(
                "No active phase in this server. A Lead or Professor can add one with `/phase create`",
                ephemeral=True
            )
            return

        criteria = await svc.get_criteria(str(phase.id))
        open_count, closed_count = await svc.ticket_counts(phase.key)

        embed = build_phase_embed(
            phase,
            criteria,
            open_count=open_count,
            closed_count=closed_count
        )
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="create", description="Add a phase to this server (Lead/Professor only)")
    @app_commands.describe(
        key="Short ID used to tag tickets, e.g. phase-1",
        name="Phase name",
        description="What this phase delivers (optional)"
    )
    @staff_only()
    async def create(
            self,
            interaction: discord.Interaction,
            key: str,
            name: str,
            description: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await require_member(interaction)
        except RuntimeError:
            return

        key = key.strip().lower()
        if not _KEY_RE.fullmatch(key):
            await interaction.followup.send(
                "Key must be lowercase letters, digits or hyphens, e.g. `phase-1`", ephemeral=True
            )
            return

        try:
            phase = await self._svc(interaction).create(key, name.strip(), description)
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        state = "It is now the active phase" if phase.status == "active" else "It will start when the earlier phases complete"
        await interaction.followup.send(
            f"Phase **{phase.name}** (`{phase.key}`) created. {state}. "
            "Add exit criteria with `/phase add-criterion`",
            ephemeral=True
        )


    @app_commands.command(name="add-criterion", description="Add an exit criterion to a phase (Lead/Professor only)")
    @app_commands.describe(
        description="What must be true before the phase can complete",
        key="Phase key (defaults to the active phase)"
    )
    @staff_only()
    async def add_criterion(
            self,
            interaction: discord.Interaction,
            description: str,
            key: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await require_member(interaction)
        except RuntimeError:
            return

        svc = self._svc(interaction)
        phase = await svc.get_by_key(key.strip().lower()) if key else await svc.get_current()
        if phase is None:
            await interaction.followup.send(
                f"No phase `{key}` in this server" if key else "No active phase. Create one with `/phase create`",
                ephemeral=True
            )
            return

        await svc.add_criterion(str(phase.id), description.strip())
        count = len(await svc.get_criteria(str(phase.id)))
        await interaction.followup.send(
            f"Criterion {count} added to **{phase.name}**: _{description.strip()}_", ephemeral=True
        )


    @app_commands.command(name="criteria", description="Check off a phase exit criterion")
    @app_commands.describe(item_number="1-based criterion number from /phase current")
    async def criteria(self, interaction: discord.Interaction, item_number: int) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        svc = self._svc(interaction)
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

        tracker_channel = self.bot.get_text_channel("phase_tracker", interaction.guild)
        if isinstance(tracker_channel, discord.TextChannel):
            criteria = await svc.get_criteria(str(phase.id))
            embed = build_phase_embed(phase, criteria)
            await tracker_channel.send(embed=embed)


    @app_commands.command(name="complete", description="Complete the active phase (Lead/Professor only)")
    @staff_only()
    async def complete(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        try:
            caller = await require_member(interaction)
        except RuntimeError:
            return

        svc = self._svc(interaction)
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
