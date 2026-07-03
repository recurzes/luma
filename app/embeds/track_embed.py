from __future__ import annotations

import discord

from app.models.track import Track, Checkpoint, TrackProgress

# ── Lookup maps ───────────────────────────────────────────────────────────────

_LEVEL_EMOJI = {
    "beginner":     "🟢",
    "intermediate": "🟡",
    "advanced":     "🔴",
}

_LEVEL_COLOR = {
    "beginner":     discord.Color.green(),
    "intermediate": discord.Color.gold(),
    "advanced":     discord.Color.red(),
}

_LEVEL_LABEL = {
    "beginner":     "Beginner",
    "intermediate": "Intermediate",
    "advanced":     "Advanced",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _progress_bar(done: int, total: int, width: int = 10) -> str:
    """Renders a filled/empty 10-block progress bar."""
    pct = done / total if total else 0
    filled = round(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"`[{bar}]` {done}/{total} ({int(pct * 100)}%)"


def _truncate(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


# ── Track list embed ──────────────────────────────────────────────────────────

def build_track_list_embed(
    tracks: list[Track],
    enrolled_ids: set[str],                # UUIDs of tracks member is enrolled in
    progress_map: dict[str, TrackProgress], # track_id → progress row
) -> discord.Embed:
    """
    Main /track list embed — shows all available tracks with:
    - level badge, enrollment status, completion progress for enrolled ones.
    """
    embed = discord.Embed(
        title="📚 Learning Tracks",
        description="Enroll in a track to start earning XP and badges.",
        color=discord.Color.blurple(),
    )

    # Sort: enrolled first, then by level order
    level_order = {"beginner": 0, "intermediate": 1, "advanced": 2}
    sorted_tracks = sorted(
        tracks,
        key=lambda t: (str(t.id) not in enrolled_ids, level_order.get(t.level or "", 3), t.name),
    )

    for track in sorted_tracks:
        level_emoji = _LEVEL_EMOJI.get(track.level or "", "⚪")
        level_label = _LEVEL_LABEL.get(track.level or "", "Unknown")
        tid = str(track.id)

        if tid in enrolled_ids:
            prog = progress_map.get(tid)
            if prog and prog.completed_at:
                status = "✅ Completed"
            elif prog:
                status = f"📣 Enrolled — {prog.checkpoints_done} done"
            else:
                status = "📣 Enrolled"
        else:
            status = "➕ Not enrolled"

        builtin_tag = "⭐ " if track.is_builtin else ""
        embed.add_field(
            name=f"{level_emoji} {builtin_tag}{track.name}",
            value=(
                f"{_truncate(track.description or '_No description_', 80)}\n"
                f"Level: **{level_label}** · {status}"
            ),
            inline=False,
        )

    embed.set_footer(
        text=(
            f"{len(tracks)} track(s) available · "
            "Use /track enroll <name> to get started"
        )
    )
    return embed


# ── Track info / enroll confirmation embed ────────────────────────────────────

def build_track_enroll_embed(
    track: Track,
    first_checkpoint: Checkpoint | None,
) -> discord.Embed:
    """Shown after a member enrolls — confirms enrollment and shows checkpoint 1."""
    level_emoji = _LEVEL_EMOJI.get(track.level or "", "⚪")
    color = _LEVEL_COLOR.get(track.level or "", discord.Color.blurple())

    embed = discord.Embed(
        title=f"✅ Enrolled: {track.name}",
        description=track.description or "",
        color=color,
    )
    embed.add_field(
        name="Level",
        value=f"{level_emoji} {_LEVEL_LABEL.get(track.level or '', 'Unknown')}",
        inline=True,
    )

    if first_checkpoint:
        value_lines = [f"**{first_checkpoint.title}**"]
        if first_checkpoint.resource_url:
            value_lines.append(f"📖 [Read / Watch]({first_checkpoint.resource_url})")
        if first_checkpoint.exercise:
            value_lines.append(f"🔨 *Exercise:* {_truncate(first_checkpoint.exercise, 120)}")
        if first_checkpoint.knowledge_check:
            value_lines.append(f"🧠 *Knowledge check:* {_truncate(first_checkpoint.knowledge_check, 120)}")
        value_lines.append(f"+**{first_checkpoint.xp_value} XP** on completion")

        embed.add_field(
            name=f"📍 Checkpoint 1 of ?",
            value="\n".join(value_lines),
            inline=False,
        )
        embed.set_footer(
            text=f"Complete it with /track checkpoint done {str(first_checkpoint.id)[:8]}"
        )
    else:
        embed.set_footer(text="No checkpoints added yet — Lead can add them with /track add-checkpoint")

    return embed


# ── Progress overview embed ───────────────────────────────────────────────────

def build_progress_embed(
    enrolled: list[tuple[Track, TrackProgress, Checkpoint | None]],
    # list of (track, progress, next_checkpoint)
) -> discord.Embed:
    """
    /track progress — shows all enrolled tracks, progress bar, and next checkpoint.
    """
    embed = discord.Embed(
        title="📊 Your Learning Progress",
        color=discord.Color.blurple(),
    )

    if not enrolled:
        embed.description = "You haven't enrolled in any tracks yet.\nUse `/track list` to see what's available."
        return embed

    for track, prog, next_cp in enrolled:
        level_emoji = _LEVEL_EMOJI.get(track.level or "", "⚪")

        # We don't know the total from TrackProgress alone — use checkpoints_done
        # and whether completed_at is set as a proxy.
        if prog.completed_at:
            status_line = "✅ **Completed!**"
            bar = "`[██████████]` 100%"
        else:
            # Rough bar — we only know done count, not total here
            done = prog.checkpoints_done
            bar = f"📣 **{done}** checkpoint{'s' if done != 1 else ''} done"
            status_line = ""

        next_line = ""
        if next_cp and not prog.completed_at:
            next_line = (
                f"\n**Next:** {next_cp.title}"
                + (f" — [resource]({next_cp.resource_url})" if next_cp.resource_url else "")
                + f"\n`/track checkpoint done {str(next_cp.id)[:8]}`"
            )

        embed.add_field(
            name=f"{level_emoji} {track.name}",
            value=f"{bar}{' — ' + status_line if status_line else ''}{next_line}",
            inline=False,
        )

    embed.set_footer(text=f"{len(enrolled)} track(s) enrolled")
    return embed


# ── Checkpoint done confirmation embed ───────────────────────────────────────

def build_checkpoint_done_embed(
    checkpoint: Checkpoint,
    xp_awarded: int,
    next_checkpoint: Checkpoint | None,
    track_name: str,
    completed: bool,  # True if this was the last checkpoint
) -> discord.Embed:
    """Shown after a member completes a checkpoint."""
    color = discord.Color.gold() if completed else discord.Color.green()
    title = (
        f"🎓 Track Complete: {track_name}!"
        if completed
        else f"✅ Checkpoint {checkpoint.sequence} done!"
    )

    embed = discord.Embed(title=title, color=color)

    embed.add_field(name="Checkpoint", value=checkpoint.title, inline=True)
    embed.add_field(name="XP Earned", value=f"+**{xp_awarded} XP**", inline=True)

    if completed:
        embed.description = (
            f"🏆 You've finished **{track_name}**!\n"
            "A completion badge has been triggered. Check `/xp` for your new total."
        )
    elif next_checkpoint:
        value_lines = [f"**{next_checkpoint.title}**"]
        if next_checkpoint.resource_url:
            value_lines.append(f"📖 [Resource]({next_checkpoint.resource_url})")
        if next_checkpoint.exercise:
            value_lines.append(f"🔨 {_truncate(next_checkpoint.exercise, 100)}")
        if next_checkpoint.knowledge_check:
            value_lines.append(f"🧠 Knowledge check included")
        value_lines.append(f"+{next_checkpoint.xp_value} XP available")

        embed.add_field(
            name=f"📍 Next: Checkpoint {next_checkpoint.sequence}",
            value="\n".join(value_lines),
            inline=False,
        )
        embed.set_footer(
            text=f"Complete with /track checkpoint done {str(next_checkpoint.id)[:8]}"
        )

    return embed


# ── Lead: track created embed ─────────────────────────────────────────────────

def build_track_created_embed(track: Track) -> discord.Embed:
    level_emoji = _LEVEL_EMOJI.get(track.level or "", "⚪")
    color = _LEVEL_COLOR.get(track.level or "", discord.Color.blurple())
    embed = discord.Embed(
        title=f"📚 Track Created: {track.name}",
        description=track.description or "_No description_",
        color=color,
    )
    embed.add_field(
        name="Level",
        value=f"{level_emoji} {_LEVEL_LABEL.get(track.level or '', 'Unknown')}",
        inline=True,
    )
    embed.set_footer(text="Add checkpoints with /track add-checkpoint")
    return embed


# ── Lead: checkpoint added embed ─────────────────────────────────────────────

def build_checkpoint_added_embed(
    checkpoint: Checkpoint,
    track_name: str,
    total_checkpoints: int,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📍 Checkpoint Added — {track_name}",
        color=discord.Color.green(),
    )
    embed.add_field(name="Sequence", value=f"#{checkpoint.sequence} of {total_checkpoints}", inline=True)
    embed.add_field(name="Title", value=checkpoint.title, inline=True)
    embed.add_field(name="XP Value", value=f"+{checkpoint.xp_value}", inline=True)

    if checkpoint.resource_url:
        embed.add_field(name="Resource", value=checkpoint.resource_url, inline=False)
    if checkpoint.exercise:
        embed.add_field(name="Exercise", value=_truncate(checkpoint.exercise, 200), inline=False)
    if checkpoint.knowledge_check:
        embed.add_field(
            name="🔒 Knowledge Check",
            value=_truncate(checkpoint.knowledge_check, 200)
            + "\n_Answer hash set — members must supply the correct answer._",
            inline=False,
        )
    return embed
