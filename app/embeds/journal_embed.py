from __future__ import annotations

from datetime import datetime, timezone, timedelta

import discord

from devbot.models.companion.journal import JournalEntry, ADR


# ── Lookup maps ───────────────────────────────────────────────────────────────

_TYPE_EMOJI = {
    "freeform":   "📝",
    "adr":        "📋",
    "reflection": "🪞",
    "blocker":    "🚧",
}

_TYPE_LABEL = {
    "freeform":   "Entry",
    "adr":        "Decision",
    "reflection": "Reflection",
    "blocker":    "Blocker",
}

_TYPE_COLOR = {
    "freeform":   discord.Color.blurple(),
    "adr":        discord.Color.from_rgb(88, 101, 242),
    "reflection": discord.Color.from_rgb(87, 180, 180),
    "blocker":    discord.Color.red(),
}

_MOOD_EMOJI = {1: "😩", 2: "😕", 3: "😐", 4: "😊", 5: "🔥"}
_MOOD_LABEL = {1: "Struggling", 2: "A bit lost", 3: "Getting there", 4: "Feeling good", 5: "In flow!"}

_ADR_STATUS_EMOJI = {
    "proposed":   "🟡",
    "accepted":   "✅",
    "deprecated": "⚫",
    "superseded": "🔄",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mood_bar(entries: list[JournalEntry]) -> str:
    """Sparkline-style mood trend for the past 7 entries that have mood."""
    moods = [(e.created_at, e.mood) for e in entries if e.mood][-7:]
    if not moods:
        return "_No mood data_"
    bar = " ".join(_MOOD_EMOJI.get(m, "❔") for _, m in moods)
    avg = sum(m for _, m in moods) / len(moods)
    return f"{bar}  avg **{avg:.1f}/5**"


def _truncate(text: str, limit: int = 300) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _relative_ts(dt: datetime) -> str:
    return discord.utils.format_dt(dt, style="R")


# ── Single-entry embed ────────────────────────────────────────────────────────

def build_entry_embed(entry: JournalEntry, project_name: str | None = None) -> discord.Embed:
    emoji = _TYPE_EMOJI.get(entry.entry_type, "📝")
    color = _TYPE_COLOR.get(entry.entry_type, discord.Color.blurple())
    label = _TYPE_LABEL.get(entry.entry_type, "Entry")

    embed = discord.Embed(
        title=f"{emoji} Journal {label}",
        description=_truncate(entry.content, 1800),
        color=color,
    )

    if project_name:
        embed.add_field(name="Project", value=project_name, inline=True)

    if entry.mood:
        mood_str = f"{_MOOD_EMOJI[entry.mood]} {_MOOD_LABEL[entry.mood]}"
        embed.add_field(name="Mood", value=mood_str, inline=True)

    if entry.tags:
        embed.add_field(name="Tags", value="  ".join(entry.tags), inline=True)

    embed.set_footer(text=f"Logged {_relative_ts(entry.created_at)}")
    return embed


# ── Today's entries embed ────────────────────────────────────────────────────

def build_today_embed(
    entries: list[JournalEntry],
    project_name: str | None,
) -> discord.Embed:
    embed = discord.Embed(
        title="📅 Today's Journal",
        color=discord.Color.blurple(),
    )
    if project_name:
        embed.description = f"Project: **{project_name}**"

    if not entries:
        embed.add_field(
            name="No entries yet",
            value="Use `/journal entry` to log what you built today.",
            inline=False,
        )
        return embed

    for e in entries:
        emoji = _TYPE_EMOJI.get(e.entry_type, "📝")
        mood = f" {_MOOD_EMOJI[e.mood]}" if e.mood else ""
        ts = discord.utils.format_dt(e.created_at, style="t")
        embed.add_field(
            name=f"{emoji} {ts}{mood}",
            value=_truncate(e.content, 200),
            inline=False,
        )

    embed.set_footer(text=f"{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} today")
    return embed


# ── Weekly entries embed ─────────────────────────────────────────────────────

def build_week_embed(
    entries: list[JournalEntry],
    project_name: str | None,
) -> discord.Embed:
    embed = discord.Embed(
        title="📆 This Week's Journal",
        color=discord.Color.from_rgb(88, 101, 242),
    )
    if project_name:
        embed.description = f"Project: **{project_name}**\n\n"

    if not entries:
        embed.description = (embed.description or "") + "_No entries this week._"
        return embed

    # Group by day
    from collections import defaultdict
    by_day: dict[str, list[JournalEntry]] = defaultdict(list)
    for e in entries:
        day_key = e.created_at.strftime("%a %b %d")
        by_day[day_key].append(e)

    for day, day_entries in by_day.items():
        lines = []
        for e in day_entries:
            emoji = _TYPE_EMOJI.get(e.entry_type, "📝")
            mood = f" {_MOOD_EMOJI[e.mood]}" if e.mood else ""
            lines.append(f"{emoji}{mood} {_truncate(e.content, 80)}")
        embed.add_field(name=day, value="\n".join(lines), inline=False)

    embed.add_field(
        name="Mood trend",
        value=_mood_bar(entries),
        inline=False,
    )
    embed.set_footer(text=f"{len(entries)} entries this week")
    return embed


# ── Search results embed ─────────────────────────────────────────────────────

def build_search_embed(entries: list[JournalEntry], query: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔍 Search: \"{query}\"",
        color=discord.Color.dark_grey(),
    )

    if not entries:
        embed.description = f"No journal entries matching **{query}**."
        return embed

    for e in entries[:8]:  # Discord embed field limit
        emoji = _TYPE_EMOJI.get(e.entry_type, "📝")
        ts = discord.utils.format_dt(e.created_at, style="d")
        embed.add_field(
            name=f"{emoji} {ts}",
            value=_truncate(e.content, 150),
            inline=False,
        )

    embed.set_footer(text=f"{len(entries)} result(s) found")
    return embed


# ── ADR single embed ──────────────────────────────────────────────────────────

def build_adr_embed(adr: ADR, project_name: str | None = None) -> discord.Embed:
    status_emoji = _ADR_STATUS_EMOJI.get(adr.status, "🟡")
    embed = discord.Embed(
        title=f"📋 ADR #{adr.sequence} — {adr.title}",
        color=discord.Color.from_rgb(88, 101, 242),
    )

    if project_name:
        embed.add_field(name="Project", value=project_name, inline=True)
    embed.add_field(name="Status", value=f"{status_emoji} {adr.status.capitalize()}", inline=True)

    embed.add_field(name="Context", value=_truncate(adr.context, 400), inline=False)
    embed.add_field(name="Decision", value=_truncate(adr.decision, 400), inline=False)

    if adr.alternatives:
        embed.add_field(name="Alternatives Considered", value=_truncate(adr.alternatives, 300), inline=False)

    return embed


# ── ADR list embed ────────────────────────────────────────────────────────────

def build_adr_list_embed(adrs: list[ADR], project_name: str | None) -> discord.Embed:
    embed = discord.Embed(
        title="📋 Architectural Decision Records",
        color=discord.Color.from_rgb(88, 101, 242),
    )
    if project_name:
        embed.description = f"Project: **{project_name}**"

    if not adrs:
        embed.add_field(
            name="No ADRs yet",
            value="Record your first decision with `/journal decision`.",
            inline=False,
        )
        return embed

    for adr in adrs:
        status_emoji = _ADR_STATUS_EMOJI.get(adr.status, "🟡")
        embed.add_field(
            name=f"{status_emoji} ADR #{adr.sequence} — {adr.title}",
            value=_truncate(adr.decision, 120),
            inline=False,
        )

    embed.set_footer(text=f"{len(adrs)} decision(s) recorded · Use /journal adr [id] for full detail")
    return embed


# ── Sprint summary embed ──────────────────────────────────────────────────────

def build_summary_embed(summary_text: str, project_name: str | None) -> discord.Embed:
    embed = discord.Embed(
        title="📖 Sprint Journal Summary",
        description=summary_text,
        color=discord.Color.from_rgb(87, 180, 180),
    )
    if project_name:
        embed.set_footer(text=f"Project: {project_name}")
    return embed
