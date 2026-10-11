from __future__ import annotations

import asyncio
from uuid import UUID

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.services.enrollment_service import EnrollmentService
from app.services.member_service import MemberService
from app.services.notification_service import NotificationService
from app.services.track_service import TrackService
from app.utils.dm import format_dm
from app.services.badge_service import BadgeService
from app.services.xp_service import XPService
from app.embeds.track_embed import *
from app.models.track import TrackProgress, Track, Checkpoint, CheckpointCompletion
from app.utils.badge_broadcast import make_badge_announcer
from app.utils.guards import require_member, staff_only
from app.utils.db import row_or_none, run_query

import bcrypt

log = structlog.get_logger()

_LEVEL_CHOICES = [
    app_commands.Choice(name="🟢 Beginner", value="beginner"),
    app_commands.Choice(name="🟡 Intermediate", value="intermediate"),
    app_commands.Choice(name="🔴 Advanced", value="advanced"),
]


@app_commands.guild_only()
class TrackCog(commands.GroupCog, name="track"):
    checkpoint = app_commands.Group(name="checkpoint", description="Checkpoint commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()


    def _svc(self) -> TrackService:
        db = database.get_db()
        xp = XPService(db)
        badge = BadgeService(db, xp, announce=make_badge_announcer(self.bot, db))
        return TrackService(db, xp_svc=xp, badge_svc=badge)


    @app_commands.command(name="list", description="Browse all available learning tracks")
    async def track_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        svc = self._svc()
        tracks = await svc.list_tracks(str(interaction.guild_id))

        db = database.get_db()
        progress_result = await run_query(
            db.table("companion_member_track_progress")
            .select("*")
            .eq("member_id", str(member.id))
        )

        progress_rows = {r["track_id"]: TrackProgress(**r) for r in progress_result.data}
        enrolled_ids = set(progress_rows.keys())

        embed = build_track_list_embed(tracks, enrolled_ids, progress_rows)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @app_commands.command(name="enroll", description="Enroll in a learning track")
    @app_commands.describe(name="Track name to enroll in")
    async def track_enroll(self, interaction: discord.Interaction, name: str) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        svc = self._svc()
        tracks = await svc.list_tracks(str(interaction.guild_id))
        track = next((t for t in tracks if t.name.lower() == name.lower()), None)

        if not track:
            await interaction.followup.send(
                f"No track named **{name}** found. Use `/track list` to see available tracks.",
                ephemeral=True
            )
            return

        try:
            await svc.enroll(member.id, track.id)
        except ValueError as e:
            await interaction.followup.send(f"{e}", ephemeral=True)
            return

        next_cp = await svc.get_next_checkpoint(member.id, track.id)
        embed = build_track_enroll_embed(track, first_checkpoint=next_cp)
        await interaction.followup.send(embed=embed, ephemeral=True)

        if next_cp:
            try:
                lines = [f"📚 **{track.name}** — Checkpoint 1: **{next_cp.title}**"]
                if next_cp.resource_url:
                    lines.append(f"📖 Resource: {next_cp.resource_url}")
                if next_cp.exercise:
                    lines.append(f"🔨 Exercise: {next_cp.exercise}")
                if next_cp.knowledge_check:
                    lines.append(f"🧠 Knowledge check: {next_cp.knowledge_check}")
                lines.append(
                    f"\nWhen ready: `/track checkpoint done {str(next_cp.id)[:8]}`"
                    + (" `answer: your answer`" if next_cp.answer_hash else "")
                )
                guild_name = interaction.guild.name if interaction.guild else "Luma"
                await interaction.user.send(format_dm(guild_name, "\n".join(lines)))
            except discord.Forbidden:
                pass


    @app_commands.command(name="progress", description="See your progress across all enrolled tracks")
    async def track_progress(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        db = database.get_db()
        progresss_result = await run_query(
            db.table("companion_member_track_progress")
            .select("*")
            .eq("member_id", str(member.id))
        )

        if not progresss_result.data:
            await interaction.followup.send(
                "You haven't enrolled in any tracks yet. Use `/track list` to get started",
                ephemeral=True
            )
            return

        svc = self._svc()
        enrolled: list[tuple[Track, TrackProgress, any]] = []

        for row in progresss_result.data:
            prog = TrackProgress(**row)

            track_result = await run_query(
                db.table("companion_tracks")
                .select("*")
                .eq("id", row["track_id"])
                .maybe_single()
            )
            track_row = row_or_none(track_result)
            if not track_row:
                continue
            track = Track(**track_row)

            next_cp = None if prog.completed_at else await svc.get_next_checkpoint(member.id, track.id)
            enrolled.append((track, prog, next_cp))

        embed = build_progress_embed(enrolled)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @checkpoint.command(name="done", description="Mark a checkpoint as complete")
    @app_commands.describe(
        checkpoint_id="Checkpoint ID (first 8 characters shown in the DM or /track progress)",
        answer="Answer to the knowledge check (if required)"
    )
    async def checkpoint_done(
            self,
            interaction: discord.Interaction,
            checkpoint_id: str,
            answer: str | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        svc = self._svc()

        db = database.get_db()
        try:
            found = await svc.find_checkpoint_by_short_id(member.id, checkpoint_id)
        except ValueError as e:
            await interaction.followup.send(f"{e}", ephemeral=True)
            return
        if found is None:
            await interaction.followup.send(
                f"No checkpoint `{checkpoint_id}` found in your enrolled tracks. "
                "Use the 8-character ID from your DM or `/track progress`.",
                ephemeral=True
            )
            return

        full_cp_id = found.id
        track_id = found.track_id

        try:
            checkpoint, xp = await svc.complete_checkpoint(
                member_id=member.id,
                checkpoint_id=full_cp_id,
                answer=answer
            )
        except ValueError as e:
            await interaction.followup.send(f"{e}", ephemeral=True)
            return
        except Exception as e:
            log.error("track_checkpoint_done_error", error=str(e))
            await interaction.followup.send("Something went wrong. Try again", ephemeral=True)
            return

        track_result = await run_query(
            db.table("companion_tracks")
            .select("*")
            .eq("id", str(track_id))
            .maybe_single()
        )
        track_row = row_or_none(track_result)
        track = Track(**track_row) if track_row else None
        track_name = track.name if track else "Unknown track"

        progress_result = await run_query(
            db.table("companion_member_track_progress")
            .select("completed_at")
            .eq("member_id", str(member.id))
            .eq("track_id", str(track_id))
            .maybe_single()
        )
        progress_row = row_or_none(progress_result)
        is_complete = bool(progress_row and progress_row.get("completed_at"))

        next_cp = None if is_complete else await svc.get_next_checkpoint(member.id, track_id)

        embed = build_checkpoint_done_embed(
            checkpoint=checkpoint,
            xp_awarded=xp,
            next_checkpoint=next_cp,
            track_name=track_name,
            completed=is_complete
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        if next_cp and not is_complete:
            try:
                lines = [
                    f"📚 **{track_name}** — Checkpoint {next_cp.sequence}: **{next_cp.title}**"
                ]
                if next_cp.resource_url:
                    lines.append(f"📖 Resource: {next_cp.resource_url}")
                if next_cp.exercise:
                    lines.append(f"🔨 Exercise: {next_cp.exercise}")
                if next_cp.knowledge_check:
                    lines.append(f"🧠 Knowledge check: {next_cp.knowledge_check}")
                lines.append(
                    f"\nWhen ready: `/track checkpoint done {str(next_cp.id)[:8]}`"
                    + (" `answer: your answer`" if next_cp.answer_hash else "")
                )
                guild_name = interaction.guild.name if interaction.guild else "Luma"
                await interaction.user.send(format_dm(guild_name, "\n".join(lines)))
            except discord.Forbidden:
                pass


    @app_commands.command(name="create", description="Create a new custom learning track")
    @app_commands.describe(
        name="Track name",
        description="What will members learn?",
        level="Difficulty level"
    )
    @app_commands.choices(level=_LEVEL_CHOICES)
    @staff_only()
    async def track_create(
            self,
            interaction: discord.Interaction,
            name: str,
            description: str,
            level: app_commands.Choice[str]
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        try:
            track = await self._svc().create_track(
                guild_id=str(interaction.guild_id),
                name=name.strip(),
                description=description,
                level=level.value,
                created_by=member.id
            )
        except ValueError as e:
            await interaction.followup.send(f"{e}", ephemeral=True)
            return

        embed = build_track_created_embed(track)
        await interaction.followup.send(embed=embed, ephemeral=True)


    @app_commands.command(name="add-checkpoint", description="Append a checkpoint to a track")
    @app_commands.describe(
        track_name="Track name to add to",
        title="Checkpoint title",
        resource_url="Link to reading, video, or docs (optional)",
        exercise="Hands-on exercise description (optional)",
        knowledge_check="Question the member must answer to complete (optional)",
        answer="Correct answer - will be bcrypt-hashed before storing (required if knowledge_check set)",
        xp="XP awarded on completion (default 10)"
    )
    @staff_only()
    async def track_add_checkpoint(
            self,
            interaction: discord.Interaction,
            track_name: str,
            title: str,
            resource_url: str | None = None,
            exercise: str | None = None,
            knowledge_check: str | None = None,
            answer: str | None = None,
            xp: int = 10
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        db = database.get_db()

        # Only this server's own tracks: built-in tracks are shared with every server.
        tracks = await self._svc().list_tracks(str(interaction.guild_id))
        track = next((t for t in tracks if t.name.lower() == track_name.strip().lower()), None)
        if track is None:
            await interaction.followup.send(
                f"No track named **{track_name}** found.",
                ephemeral=True
            )
            return
        if track.guild_id is None:
            await interaction.followup.send(
                f"**{track.name}** is a built-in track shared by every server and can't be edited here. "
                "Create your own with `/track create`",
                ephemeral=True
            )
            return

        track_id = str(track.id)

        if knowledge_check and not answer:
            await interaction.followup.send(
                "A knowledge check requires an `answer` so I can hash it",
                ephemeral=True
            )
            return

        answer_hash: str | None = None
        if answer:
            answer_hash = bcrypt.hashpw(
                answer.lower().strip().encode(),
                bcrypt.gensalt()
            ).decode()

        seq_result = await run_query(
            db.table("companion_track_checkpoints")
            .select("sequence")
            .eq("track_id", track_id)
            .order("sequence", desc=True)
            .limit(1)
        )
        next_seq = (seq_result.data[0]["sequence"] + 1) if seq_result.data else 1

        cp_result = await run_query(
            db.table("companion_track_checkpoints")
            .insert({
                "track_id": track_id,
                "sequence": next_seq,
                "title": title,
                "resource_url": resource_url,
                "exercise": exercise,
                "knowledge_check": knowledge_check,
                "answer_hash": answer_hash,
                "xp_value": xp
            })
        )

        checkpoint = Checkpoint(**cp_result.data[0])

        embed = build_checkpoint_added_embed(
            checkpoint=checkpoint,
            track_name=track.name,
            total_checkpoints=next_seq
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


    # Scheduled Jobs
    async def _monday_nudge_job(self) -> None:
        svc = self._svc()
        db = database.get_db()
        enrollment_svc = EnrollmentService(database.get_db())
        notification_svc = NotificationService(database.get_db())
        member_svc = MemberService(db)

        stale = await svc.get_stale_enrollments(inactive_days=7)
        if not stale:
            return

        nudged = 0
        for row in stale:
            member_id: str | None = row.get("member_id")
            track_id: str | None = row.get("track_id")
            if not member_id or not track_id:
                continue

            member = await member_svc.get_by_id(member_id)
            if member is None:
                continue

            track_res = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda tid=track_id: (
                    db.table("companion_tracks")
                    .select("name")
                    .eq("id", tid)
                    .maybe_single()
                    .execute()
                ),
            )
            track_row = row_or_none(track_res)
            track_name = track_row["name"] if track_row else "your track"
            next_cp = await svc.get_next_checkpoint(UUID(member_id), UUID(track_id))

            lines = [
                f"Hey! You haven't made progress on **{track_name}** in a while.",
                "Ready to pick it back up?",
            ]
            if next_cp:
                lines.append(f"\nNext checkpoint: **{next_cp.title}**")
                if next_cp.resource_url:
                    lines.append(f"📖 {next_cp.resource_url}")
                if next_cp.exercise:
                    lines.append(f"🔨 {next_cp.exercise}")
                lines.append(
                    f"\nRun `/track checkpoint done {str(next_cp.id)[:8]}`"
                    + (" `answer: your answer`" if next_cp.answer_hash else "")
                    + " when ready."
                )
            else:
                lines.append("\nRun `/track progress` to see where you left off.")

            body = "\n".join(lines)
            enrollments = await enrollment_svc.get_active_enrollments_for_member(member.id)
            for enrollment in enrollments:
                guild = self.bot.get_guild(int(enrollment.guild_id))
                if guild is None:
                    continue
                if not await notification_svc.is_enabled(member.id, str(guild.id), "track"):
                    continue
                try:
                    user = await self.bot.fetch_user(int(member.discord_id))
                    await user.send(format_dm(guild.name, body))
                    nudged += 1
                except (discord.Forbidden, discord.NotFound):
                    pass

        log.info("track_nudge.sent", nudged=nudged)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrackCog(bot))
