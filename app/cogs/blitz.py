from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands

from app.services.blitz_service import BlitzService
from app.models.blitz import BlitzCreate
from app.embeds.blitz_embed import *
from app.embeds.blitz_embed import _countdown_bar, _remaining_str

SHOWCASE_GRACE_HOURS = 2


class BlitzCog(commands.GroupCog, name="blitz"):
    def __init__(self, bot: commands.Bot, blitz_svc: BlitzService):
        self.bot = bot
        self.blitz_svc = blitz_svc
        super().__init__()

    @app_commands.command(name="start", description="Start a Tech Blitz for the team")
    @app_commands.describe(
        technology="What are we learning? (e.g. 'Godot 4', 'Rust', 'SvelteKit')",
        tech_category="Category of the technology",
        goal="What will we build? (e.g. 'a 2D platformer', 'a REST API')",
        deliverable_type="Type of deliverable",
        duration_hours="Timer in hours (default: 48)"
    )
    @app_commands.choices(
        tech_category=[
            app_commands.Choice(name="Language (Python, Rust, Go…)", value="language"),
            app_commands.Choice(name="Framework (SvelteKit, FastAPI…)", value="framework"),
            app_commands.Choice(name="Game Engine (Godot, Unity…)", value="engine"),
            app_commands.Choice(name="Tool (Docker, k8s, Figma…)", value="tool"),
            app_commands.Choice(name="Other", value="other"),
        ],
        deliverable_type=[
            app_commands.Choice(name="Game", value="game"),
            app_commands.Choice(name="Web App", value="web_app"),
            app_commands.Choice(name="Mobile App", value="mobile_app"),
            app_commands.Choice(name="CLI Tool", value="cli"),
            app_commands.Choice(name="API", value="api"),
            app_commands.Choice(name="Library", value="library"),
            app_commands.Choice(name="Prototype / Experiment", value="prototype"),
            app_commands.Choice(name="Anything — just ship something", value="any"),
        ]
    )
    async def blitz_start(
            self,
            interaction: discord.Interaction,
            technology: str,
            tech_category: str,
            goal: str,
            deliverable_type: str = "any",
            duration_hours: int = 48
    ):
        await interaction.response.defer()

        if duration_hours < 1 or duration_hours > 168:
            await interaction.followup.send(
                "Duration must be between 1 and 168 hours (1 week)",
                ephemeral=True
            )
            return

        try:
            session = await self.blitz_svc.create(
                BlitzCreate(
                    guild_id=str(interaction.guild_id),
                    created_by=UUID(str(interaction.user.id)),
                    technology=technology,
                    tech_category=tech_category,
                    goal=goal,
                    deliverable_type=deliverable_type,
                    duration_hours=duration_hours,
                    guild_channel_id=str(interaction.channel_id)
                )
            )
        except ValueError as e:
            await interaction.followup.send(f"{e}", ephemeral=True)
            return

        embed = blitz_announce_embed(session, participant_count=1)
        msg = await interaction.followup.send(embed=embed)

        await self.blitz_svc.set_announce_msg(session.id, str(msg.id))

        await interaction.channel.send(
            f"**A Tech Blitz just started!** React ✅ or use `/blitz join` to participate.\n"
            f"**Tech:** {technology} · 🎯 **Goal:** {goal} · ⏰ **{duration_hours}h"
        )


    @app_commands.command(name="join", description="Join the active Tech Blitz")
    async def blitz_join(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        session = await self.blitz_svc.get_active(str(interaction.guild_id))
        if not session:
            await interaction.followup.send("No active blitz right now. Start one with `/blitz start`", ephemeral=True)
            return

        try:
            await self.blitz_svc.join(session.id, UUID(str(interaction.user.id)))
        except ValueError as e:
            await interaction.followup.send(f"{e}", ephemeral=True)
            return

        participants = await self.blitz_svc.get_participants(session.id)
        await interaction.followup.send(
            f"You joined the **{session.technology}** blitz! "
            f"You're participant #{len(participants)}.\n"
            f"Post progress with `/blitz checkin` · Submit your project with `/blitz showcase`.",
            ephemeral=True,
        )


    @app_commands.command(name="checkin", description="Post a progress update during the blitz")
    @app_commands.describe(
        update="What did you build or learn? What are you working on?",
        mood="Your current energy level (1 = burnt out, 5 = in flow)",
        media_url="Optional screenshot, GIF, or Video URL"
    )
    @app_commands.choices(
        mood=[
            app_commands.Choice(name="😩 1 — Struggling hard", value=1),
            app_commands.Choice(name="😕 2 — A bit lost", value=2),
            app_commands.Choice(name="😐 3 — Making progress", value=3),
            app_commands.Choice(name="😊 4 — Feeling good", value=4),
            app_commands.Choice(name="🔥 5 — IN THE FLOW", value=5),
        ]
    )
    async def blitz_checkin(
            self,
            interaction: discord.Interaction,
            update: str,
            mood: int = None,
            media_url: str = None
    ):
        await interaction.response.defer()

        session = await self.blitz_svc.get_active(str(interaction.guild_id))
        if not session:
            await interaction.followup.send("No active blitz", ephemeral=True)
            return

        try:
            checkin = await self.blitz_svc.checkin(
                session.id,
                UUID(str(interaction.user.id)),
                content=update,
                media_url=media_url,
                mood=mood
            )
        except ValueError as e:
            await interaction.followup.send(f"{e}", ephemeral=True)
            return

        all_checkins = await self.blitz_svc.get_checkins(session.id)
        member = interaction.user
        embed = blitz_checkin_embed(checkin, member, session, len(all_checkins))
        msg = await interaction.followup.send(embed=embed)
        await msg.add_reaction("❤️")


    @app_commands.command(name="showcase", description="Submit your final project for the blitz")
    @app_commands.describe(
        title="Your project name",
        description="What did you build? What did you learn?",
        repo_url="GitHub / GitLab repo URL",
        demo_url="Playable link, hosted URL, or video demo",
        media_url="Screenshot or GIF URL"
    )
    async def blitz_showcase(
            self,
            interaction: discord.Interaction,
            title: str,
            description: str,
            repo_url: str = None,
            demo_url: str = None,
            media_url: str = None
    ):
        await interaction.response.defer()

        session = await self.blitz_svc.get_active(str(interaction.guild_id))
        if not session:
            await interaction.followup.send("No active or recent blitz to submit for", ephemeral=True)
            return

        try:
            showcase = await self.blitz_svc.submit_showcase(
                session.id,
                UUID(str(interaction.user.id)),
                title=title,
                description=description,
                repo_url=repo_url,
                demo_url=demo_url,
                media_url=media_url
            )
        except ValueError as e:
            await interaction.followup.send(f"{e}", ephemeral=True)
            return

        member = interaction.user
        embed = blitz_showcase_embed(showcase, member, session)
        msg = await interaction.followup.send(embed=embed)
        await msg.add_reaction("🏆")


    @app_commands.command(name="progress", description="See who has checked in and overall blitz status")
    async def blitz_progress(self, interaction: discord.Interaction):
        await interaction.response.defer()

        session = await self.blitz_svc.get_active(str(interaction.guild_id))
        if not session:
            await interaction.followup.send("No active blitz", ephemeral=True)
            return

        participants = await self.blitz_svc.get_participants(session.id)
        checkins = await self.blitz_svc.get_checkins(session.id)
        showcases = await self.blitz_svc.get_showcases(session.id)

        checkin_counts = Counter(str(c.member_id) for c in checkins)

        embed = discord.Embed(
            title=f"Blitz Progress - {session.technology}",
            color=discord.Color.blurple()
        )

        embed.description = f"{_countdown_bar(session)}\n{_remaining_str(session)}"

        lines = []
        for p in participants:
            count = checkin_counts.get(str(p.member_id), 0)
            has_showcase = any(str(s.member_id) == str(p.member_id) for s in showcases)
            status_icon = "🏁" if has_showcase else ("📣" if count > 0 else "⏳")
            lines.append(f"{status_icon} <@{p.member_id}> - {count} check-in{'s' if count != 1 else ''}")

        embed.add_field(
            name=f"Team ({len(participants)} participants)",
            value="\n".join(lines) if lines else "No participants yet",
            inline=False
        )
        embed.add_field(name="Total Check-ins", value=str(len(checkins)), inline=True)
        embed.add_field(name="Showcases", value=str(len(showcases)), inline=True)
        embed.set_footer(text="🏁 = Showcase submitted · 📣 = Has checked in · ⏳ = No activity")
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="extend", description="Add more time to the active blitz")
    @app_commands.describe(hours="Extra hours to add (max 24)")
    @app_commands.checks.has_any_role("Lead", "Professor")
    async def blitz_extend(self, interaction: discord.Interaction, hours: int):
        await interaction.response.defer(ephemeral=True)

        session = await self.blitz_svc.get_active(str(interaction.guild_id))
        if not session:
            await interaction.followup.send("No active blitz", ephemeral=True)
            return

        if hours < 1 or hours > 24:
            await interaction.followup.send("Extension must be 1-24 hours", ephemeral=True)
            return

        updated = await self.blitz_svc.extend(session.id, hours)
        await interaction.followup.send(
            f"Blitz extended by **{hours}h**. New end time: <t:{int(updated.ends_at.timestamp())}:F>",
            ephemeral=True
        )


    @app_commands.command(name="end", description="Close the blitz and post the showcase gallery")
    @app_commands.checks.has_any_role("Lead", "Professor")
    async def blitz_end(self, interaction: discord.Interaction):
        await interaction.response.defer()

        session = await self.blitz_svc.get_active(str(interaction.guild_id))
        if not session:
            await interaction.followup.send("No active blitz", ephemeral=True)
            return

        participants = await self.blitz_svc.get_participants(session.id)
        showcases = await self.blitz_svc.get_showcases(session.id)

        await self.blitz_svc.complete(session.id)

        embed = blitz_gallery_embed(session, showcases, len(participants))
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="cancel", description="Cancel the active blitz (no XP awarded)")
    @app_commands.checks.has_any_role("Lead", "Professor")
    async def blitz_cancel(self, interaction: discord.Interaction):
        await interaction.response.defer()

        session = await self.blitz_svc.get_active(str(interaction.guild_id))
        if not session:
            await interaction.followup.send("No active blitz", ephemeral=True)
            return

        await self.blitz_svc.cancel(session.id)
        await interaction.followup.send(
            f"**{session.technology}** blitz cancelled", ephemeral=True
        )


    @app_commands.command(name="countdown", description="Show the current blitz countdown")
    async def blitz_countdown(self, interaction: discord.Interaction):
        await interaction.response.defer()

        session = await self.blitz_svc.get_active(str(interaction.guild_id))
        if not session:
            await interaction.followup.send("No active blitz", ephemeral=True)
            return

        participants = await self.blitz_svc.get_participants(session.id)
        embed = blitz_announce_embed(session, len(participants))
        await interaction.followup.send(embed=embed)


    @app_commands.command(name="history", description="See past Tech Blitzes")
    @app_commands.describe(limit="Number of past blitzes to show (default 5)")
    async def blitz_history(self, interaction: discord.Interaction, limit: int = 5):
        await interaction.response.defer()

        past = await self.blitz_svc.get_history(str(interaction.guild_id), min(limit, 10))
        if not past:
            await interaction.followup.send("No completed blitzes yet", ephemeral=True)
            return

        embed = discord.Embed(
            title="Tech Blitz History",
            color=discord.Color.dark_grey(),
        )
        for s in past:
            showcases = await self.blitz_svc.get_showcases(s.id)
            participants = await self.blitz_svc.get_participants(s.id)
            ts = int(s.completed_at.timestamp()) if s.completed_at else 0
            embed.add_field(
                name=f"{s.technology} ({s.duration_hours}h)",
                value=(
                    f"Goal: {s.goal[:60]}\n"
                    f"👥 {len(participants)} · 🏁 {len(showcases)} shipped · "
                    f"<t:{ts}:d>"
                )
            )

        await interaction.followup.send(embed=embed)


    async def cog_group_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.errors.MissingAnyRole):
            await interaction.response.send_message(
                "Only Lead or Professor can use this command", ephemeral=True
            )
        else:
            import structlog
            structlog.get_logger().error("blitz_command_error", error=str(error))
            await interaction.response.send_message(
                "Something went wrong. Try again or ping the Lead", ephemeral=True
            )


    # Scheduled Jobs
    async def _blitz_tick(self):
        sessions = await self.blitz_svc.get_all_active()
        now = datetime.now(timezone.utc)

        for session in sessions:
            channel = self.bot.get_channel(int(session.guild_channel_id)) if session.guild_channel_id else None

            if session.status == "active" and session.ends_at and now >= session.ends_at:
                updated = await self.blitz_svc.transition_to_showcase(session.id)

                if channel:
                    announce_embed = blitz_showcase_embed(updated)
                    await channel.send(embed=announce_embed)

                    participants = await self.blitz_svc.get_participants(session.id)
                    mentions = " ".join(f"<@{p.member_id}>" for p in participants)
                    if mentions:
                        await channel.send(
                            f"{mentions}\n"
                            f"Time's up! Submit your showcase with `/blitz showcase.` "
                            f"You have **{SHOWCASE_GRACE_HOURS}**"
                        )
                continue

            if session.status == "showcase" and session.ends_at:
                grace_end = session.ends_at + timedelta(hours=SHOWCASE_GRACE_HOURS)
                if now >= grace_end:
                    participants = await self.blitz_svc.get_participants(session.id)
                    showcases = await self.blitz_svc.get_showcases(session.id)

                    await self.blitz_svc.complete(session.id)

                    if channel:
                        gallery = blitz_gallery_embed(session, showcases, len(participants))
                        await channel.send(embed=gallery)
                continue

            pending = self.blitz_svc.calculate_pending_milestones(session)
            for milestone in pending:
                fired = await self.blitz_svc.mark_milestone(session.id, milestone)
                if fired and channel:
                    embed = blitz_milestone_embed(session, milestone)
                    msg = await channel.send(embed=embed)

                    if milestone == "1h_left":
                        participants = await self.blitz_svc.get_participants(session.id)
                        mentions = " ".join(f"<@{p.member_id}>" for p in participants)
                        if mentions:
                            await channel.send(f"{mentions} - **1 hour left on the blitz!**")

            if session.announce_msg_id and channel:
                try:
                    participants = await self.blitz_svc.get_participants(session.id)
                    embed = blitz_announce_embed(session, len(participants))
                    msg = await channel.fetch_message(int(session.announce_msg_id))
                    await msg.edit(embed=embed)
                except (discord.NotFound, discord.HTTPException):
                    pass


    async def _blitz_nudge_inactive(self):
        sessions = await self.blitz_svc.get_all_active()
        now = datetime.now(timezone.utc)

        for session in sessions:
            if session.status != "active":
                continue

            participants = await self.blitz_svc.get_participants(session.id)
            checkins = await self.blitz_svc.get_checkins(session.id)
            showcases = await self.blitz_svc.get_showcases(session.id)

            showcase_member_ids = {str(s.member_id) for s in showcases}
            cutoff = now - timedelta(hours=8)

            recent_member_ids = {
                str(c.member_id) for c in checkins
                if c.posted_at and c.posted_at > cutoff
            }

            for p in participants:
                mid_str = str(p.member_id)
                if mid_str in showcase_member_ids:
                    continue
                if mid_str in recent_member_ids:
                    continue

                try:
                    user = self.bot.get_user(int(p.member_id)) or await self.bot.fetch_user(int(p.member_id))
                    embed = blitz_nudge_embed(session)
                    await user.send(embed=embed)
                except discord.Forbidden:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(BlitzCog(bot, bot.services["blitz"]))