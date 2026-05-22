from __future__ import annotations

from datetime import datetime

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.config import settings
from app.embeds.ticket_embed import build_board_embed, build_ticket_embed
from app.models.ticket import TicketCreate, TierViolationError
from app.services.member_service import MemberService
from app.services.ticket_service import TicketService
from app.utils.guards import require_member
from app.utils.badge_broadcast import post_badges_to_shoutouts

log = structlog.get_logger()

_STATUS_CHOICES = [
    app_commands.Choice(name="To Do", value="todo"),
    app_commands.Choice(name="In Progress", value="in_progress"),
    app_commands.Choice(name="In Review", value="in_review"),
    app_commands.Choice(name="Done", value="done")
]


# Modals

class TicketModal(discord.ui.Modal, title="Create Ticket"):
    ticket_title = discord.ui.TextInput(
        label="Title",
        placeholder="Short description of the task",
        max_length=100
    )
    description = discord.ui.TextInput(
        label="Description",
        style=discord.TextStyle.paragraph,
        placeholder="Details, context, reference pattern (T1 required)",
        required=False,
        max_length=500
    )
    tier = discord.ui.TextInput(
        label="Tier",
        placeholder="T1 / T2 / T3",
        max_length=2
    )
    priority = discord.ui.TextInput(
        label="Priority",
        placeholder="low / medium / high / blocker",
        default="medium",
        max_length=7
    )
    deadline = discord.ui.TextInput(
        label="Deadline (YYYY-MM-DD, optional)",
        required=False,
        max_length=10,
    )

    def __init__(self, cog: TicketCog) -> None:
        super().__init__()
        self._cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        tier_val = self.tier.value.strip().lower()
        priority_val = self.priority.value.strip().lower()

        if tier_val not in ("T1", "T2", "T3"):
            await interaction.followup.send(
                "Invalid tier. Use T1, T2, or T3",
                ephemeral=True
            )
            return

        if priority_val not in ("low", "medium", "high", "blocker"):
            await interaction.followup.send(
                "Invalid priority. Use: low, medium, high, or blocker",
                ephemeral=True
            )
            return

        deadline_dt: datetime | None = None
        if self.deadline.value.strip():
            try:
                deadline_dt = datetime.strptime(self.deadline.value.strip(), "%Y-%m-%d")
            except ValueError:
                await interaction.followup.send(
                    "Invalid deadline format. Use YYYY-MM-DD",
                    ephemeral=True
                )
                return

        service = self._cog._ticket_service()

        ticket = await service.create(
            payload=TicketCreate(
                title=self.ticket_title.value.strip(),
                description=self.description.value.strip() or None,
                tier=tier_val,
                priority=priority_val,
                deadline=deadline_dt
            ),
            created_by_discord_id=str(interaction.user.id)
        )

        embed = build_ticket_embed(ticket, assignee=None)

        channel = self._cog.bot.get_text_channel("task_feed")
        if channel and isinstance(channel, discord.TextChannel):
            feed_msg = await channel.send(embed=embed)
            await service.update_discord_msg_id(str(ticket.id), str(feed_msg.id))

        log.info("ticket.created_via_modal", ticket_id=str(ticket.id), tier=tier_val)
        await interaction.followup.send(
            f"Ticket `{str(ticket.id)[-8:]}` created and posted to {channel.mention if channel else '#task-feed'}",
            ephemeral=True
        )


# Cog

class TicketCog(commands.Cog):
    ticket = app_commands.Group(name="ticket", description="Ticket management commands")
    tickets = app_commands.Group(name="tickets", description="Ticket view commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _ticket_service(self) -> TicketService:
        db = database.get_db()
        members = MemberService(db)
        return TicketService(db, members, xp_service=None, streak_service=None)

    @ticket.command(name="create", description="Open a new ticket via form")
    async def ticket_create(self, interaction: discord.Interaction) -> None:
        try:
            await require_member(interaction)
        except RuntimeError:
            return
        await interaction.response.send_modal(TicketModal(self))

    @ticket.command(name="assign", description="Assign a ticket to a team member")
    @app_commands.describe(
        ticket_id="Ticket ID (last 8 chars or full UUID)",
        member="Team member to assign"
    )
    async def ticket_assign(
            self,
            interaction: discord.Interaction,
            ticket_id: str,
            member: discord.Member
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await require_member(interaction)
        except RuntimeError:
            return

        service = self._ticket_service()

        try:
            result = await service.assign(ticket_id, str(member.id))
        except TierViolationError as e:
            embed = discord.Embed(
                title="Tier Violation",
                description=(
                    f"**{e.assignee_name}** cannot be assigned a **{e.requested_tier}** ticket\n"
                    f"Their current max tier is **{e.max_tier}**"
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        member_svc = MemberService(database.get_db())
        assignee_record = await member_svc.get_by_discord_id(str(member.id))

        embed = build_ticket_embed(result.ticket, assignee=assignee_record)

        if result.ticket.discord_msg_id:
            channel = self.bot.get_text_channel("task_feed")
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(int(result.ticket.discord_msg_id))
                    await msg.edit(embed=embed)
                except discord.NotFound:
                    await channel.send(embed=embed)

        if result.first_t2:
            feed_channel = self.bot.get_text_channel("task_feed")
            if feed_channel and isinstance(feed_channel, discord.TextChannel):
                await feed_channel.send(
                    f"📌 **Pairing required:** {member.mention} is taking their first T2 ticket "
                    f"`{str(result.ticket.id)[-8:]}` Lead or Professor must pair with them"
                )

        await interaction.followup.send(
            f"Assigned ticket `{str(result.ticket.id)[-8:]}` to {member.mention}",
            ephemeral=True
        )

    @ticket.command(name="status", description="Update ticket status")
    @app_commands.describe(
        ticket_id="Ticket ID (last 8 chars or full UUID)",
        new_status="New status"
    )
    @app_commands.choices(new_status=_STATUS_CHOICES)
    async def ticket_status(
            self,
            interaction: discord.Interaction,
            ticket_id: str,
            new_status: app_commands.Choice[str]
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await require_member(interaction)
        except RuntimeError:
            return

        service = self._ticket_service()

        try:
            updated = await service.update_status(ticket_id, new_status.value, str(interaction.user.id))
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        member_svc = MemberService(database.get_db())
        assignee = None
        if updated.assignee_id:
            all_members = await member_svc.get_all_active()
            assignee = next((m for m in all_members if m.id == updated.assignee_id), None)

        embed = build_ticket_embed(updated, assignee=assignee)

        if updated.discord_msg_id:
            channel = self.bot.get_text_channel("task_feed")
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(int(updated.discord_msg_id))
                    await msg.edit(embed=embed)
                except discord.NotFound:
                    await channel.send(embed=embed)

        await interaction.followup.send(
            f"Ticket `{str(updated.id)[-8:]}` moved to **{new_status.name}**",
            ephemeral=True
        )

    @ticket.command(name="close", description="Close a ticket")
    @app_commands.describe(ticket_id="Ticket ID (last 8 chars or full UUID)")
    async def ticket_close(self, interaction: discord.Interaction, ticket_id: str) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await require_member(interaction)
        except RuntimeError:
            return

        service = self._ticket_service()

        try:
            close_result = await service.close(ticket_id, str(interaction.user.id))
        except ValueError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        closed = close_result.ticket
        embed = build_ticket_embed(closed, assignee=None)

        if closed.discord_msg_id:
            channel = self.bot.get_text_channel("task_feed")
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    msg = await channel.fetch_message(int(closed.discord_msg_id))
                    await msg.edit(embed=embed)
                except discord.NotFound:
                    await channel.send(embed=embed)

        if close_result.level_up:
            shoutouts = self.bot.get_text_channel("shoutouts", interaction.guild)
            if shoutouts and isinstance(shoutouts, discord.TextChannel):
                await shoutouts.send(
                    f"🎉 {interaction.user.mention} just levelled up to **Level {close_result.new_level}** "
                    f"by closing ticket `{str(closed.id)[-8:]}`! +{close_result.xp_awarded} XP"
                )

        if close_result.badges:
            closer_member = await MemberService(database.get_db()).get_by_discord_id(str(interaction.user.id))
            if closer_member:
                await post_badges_to_shoutouts(self.bot, closer_member, close_result.badges)

        await interaction.followup.send(
            f"Ticket `{str(closed.id)[-8:]}` closed. +{close_result.xp_awarded} XP awarded",
            ephemeral=True
        )

    @ticket.command(name="mine", description="Show your open tickets")
    async def tickets_mine(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await require_member(interaction)
        except RuntimeError:
            return

        service = self._ticket_service()
        open_tickets = await service.get_by_assignee(str(interaction.user.id))

        if not open_tickets:
            await interaction.followup.send("You have no open tickets", ephemeral=True)
            return

        lines = []
        for t in open_tickets:
            short_id = str(t.id)[-8:]
            status_emoji = {"todo": "⬜", "in_progress": "🟡", "in_review": "🔵"}.get(t.status, "❓")
            lines.append(f"{status_emoji} `{short_id}` **[{t.tier}]** {t.title}")

        embed = discord.Embed(
            title=f"Your Open Tickets ({len(open_tickets)})",
            description="\n".join(lines),
            color=discord.Color.blurple()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="board", description="Show the full ticket board grouped by status")
    @app_commands.checks.cooldown(1, 30.0, key=lambda i: i.guild_id)
    async def board(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        service = self._ticket_service()
        all_tickets = await service.get_all()

        embed = build_board_embed(all_tickets)
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCog(bot))
