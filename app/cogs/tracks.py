from __future__ import annotations

import asyncio
from uuid import UUID

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.services.track_service import TrackService
from app.services.badge_service import BadgeService
from app.services.xp_service import XPService
from app.embeds.track_embed import *
from app.models.track import TrackProgress, Track, Checkpoint, CheckpointCompletion
from app.utils.guards import require_member

import bcrypt

log = structlog.get_logger()

_LEVEL_CHOICES = [
    app_commands.Choice(name="🟢 Beginner", value="beginner"),
    app_commands.Choice(name="🟡 Intermediate", value="intermediate"),
    app_commands.Choice(name="🔴 Advanced", value="advanced"),
]


class TrackCog(commands.GroupCog, name="track"):
    checkpoint = app_commands.Group(name="checkpoint", description="Checkpoint commands")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()


    def _svc(self) -> TrackService:
        db = database.get_db()
        xp = XPService(db)
        badge = BadgeService(db, xp)
        return TrackService(db, xp_svc=xp, badge_svc=badge)


    @app_commands.command(name="list", description="Browse all available learning tracks")
    async def track_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        svc = self._svc()
        tracks = await svc.list_tracks()

        db = database.get_db()
        progress_result = (
            db.table("companion_member_track_progress")
            .select("*")
            .eq("member_id", str(member.id))
            .execute()
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
        tracks = await svc.list_tracks()
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
                await interaction.user.send("\n".join(lines))
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
        progresss_result = (
            db.table("companion_member_track_progress")
            .select("*")
            .eq("member_id", str(member.id))
            .execute()
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

            track_result = (
                db.table("companion_tracks")
                .select("*")
                .eq("id", row["track_id"])
                .maybe_single()
                .execute()
            )
            if not track_result.data:
                continue
            track = Track(**track_result.data)

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
        cp_result = (
            db.table("companion_track_checkpoints")
            .select("*")
            .ilike("id", f"{checkpoint_id}%")
            .limit(1)
            .maybe_single()
            .execute()
        )
        if not cp_result.data:
            await interaction.followup.send(
                f"No checkpoint found starting with `{checkpoint_id}`.",
                ephemeral=True
            )
            return

        full_cp_id = UUID(cp_result.data["id"])
        track_id = UUID(cp_result.data["track_id"])

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

        track_result = (
            db.table("companion_tracks")
            .select("*")
            .eq("id", str(track_id))
            .maybe_single()
            .execute()
        )
        track = Track(**track_result.data) if track_result.data else None
        track_name = track.name if track else "Unknown track"

        progress_result = (
            db.table("companion_member_track_progress")
            .select("completed_at")
            .eq("member_id", str(member.id))
            .eq("track_id", str(track_id))
            .maybe_single()
            .execute()
        )
        is_complete = bool(
            progress_result.data and progress_result.data.get("completed_at")
        )

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
                await interaction.user.send("\n".join(lines))
            except discord.Forbidden:
                pass


    @app_commands.command(name="create", description="Create a new custom learning track")
    @app_commands.describe(
        name="Track name",
        description="What will members learn?",
        level="Difficulty level"
    )
    @app_commands.choices(level=_LEVEL_CHOICES)
    @app_commands.checks.has_any_role("Lead", "Professor")
    async def track_create(
            self,
            interaction: discord.Interaction,
            name: str,
            description: str,
            level: app_commands.Choice[str]
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        db = database.get_db()
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        result = (
            db.table("companion_tracks")
            .insert({
                "name": name,
                "description": description,
                "level": level.value,
                "created_by": str(member.id),
                "is_builtin": False
            })
            .execute()
        )

        track = Track(**result.data[0])
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
    @app_commands.checks.has_any_role("Lead", "Professor")
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

        track_result = (
            db.table("companion_tracks")
            .select("*")
            .ilike("name", track_name)
            .maybe_single()
            .execute()
        )
        if not track_result.data:
            await interaction.followup.send(
                f"No track named **{track_name}** found.",
                ephemeral=True
            )
            return

        track_id = track_result.data["id"]

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

        seq_result = (
            db.table("companion_track_checkpoint")
            .select("sequence")
            .eq("track_id", track_id)
            .order("sequence", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        next_seq = (seq_result.data["sequence"] + 1) if seq_result else 1

        cp_result = (
            db.table("companion_track_checkpoint")
            .insert({
                "track_id": track_id,
                "sequence": next_seq,
                "title": title,
                "resource_url": resource_url,
                "exercise": exercise,
                "knowledge_checks": knowledge_check,
                "answer_hash": answer_hash,
                "xp_value": xp
            })
            .execute()
        )

        checkpoint = Checkpoint(**cp_result.data[0])

        embed = build_checkpoint_added_embed(
            checkpoint=checkpoint,
            track_name=track_result.data["name"],
            total_checkpoints=next_seq
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


    # Scheduled Jobs
    async def _monday_nudge_job(self) -> None:
        svc = self._svc()
        db = database.get_db()

        stale = await svc.get_stale_enrollments(inactive_days=7)
        if not stale:
            return

        nudged = 0
        for row in stale:
            member_id: str | None = row.get("member_id")
            track_id: str | None = row.get("track_id")
            if not member_id or not track_id:
                continue

            mem_res = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda mid=member_id: (
                    db.table("bot_members")
                    .select("discord_id")
                    .eq("id", mid)
                    .maybe_single()
                    .execute()
                ),
            )
            if not mem_res.data:
                continue
            discord_id: str | None = mem_res.data.get("discord_id")
            if not discord_id:
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
            track_name = track_res.data["name"] if track_res.data else "your track"

            next_cp = await svc.get_next_checkpoint(UUID(member_id), UUID(track_id))

            try:
                user = await self.bot.fetch_user(int(discord_id))
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
                await user.send("\n".join(lines))
                nudged += 1
            except (discord.Forbidden, discord.NotFound):
                pass

        log.info("track_nudge.sent", nudged=nudged)

    @checkpoint.error
    async def checkpoint_error(
            interaction: discord.Interaction,
            error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.errors.MissingAnyRole):
            msg = "Only Lead or Professor can use this command."
        else:
            log.error("track_command_error", error=str(error))
            msg = "Something went wrong. Try again or ping the Lead"

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    async def cog_group_error(
            self,
            interaction: discord.Interaction,
            error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.errors.MissingAnyRole):
            msg = "Only Lead or Professor can use this command."
        else:
            log.error("track_command_error", error=str(error))
            msg = "Something went wrong. Try again or ping the Lead"

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrackCog(bot))
