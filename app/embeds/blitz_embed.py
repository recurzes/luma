"""
embeds/companion/blitz_embed.py
Discord embed builders for all Tech Blitz states.
Branch: feature/tech-blitz
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from app.models.blitz import BlitzSession, BlitzCheckin, BlitzShowcase

# Tech category emojis
TECH_EMOJI = {
    "language":  "🔤",
    "framework": "🧱",
    "engine":    "🎮",
    "tool":      "🔧",
    "other":     "⚙️",
}

DELIVERABLE_EMOJI = {
    "game":       "🕹️",
    "web_app":    "🌐",
    "mobile_app": "📱",
    "cli":        "💻",
    "api":        "🔌",
    "library":    "📦",
    "prototype":  "🔬",
    "any":        "🚀",
}

MOOD_EMOJI = {1: "😩", 2: "😕", 3: "😐", 4: "😊", 5: "🔥"}


def _countdown_bar(session: "BlitzSession") -> str:
    """Renders a 10-block progress bar showing time elapsed."""
    now = datetime.now(timezone.utc)
    total = (session.ends_at - session.started_at).total_seconds()
    elapsed = (now - session.started_at).total_seconds()
    pct = max(0, min(1, elapsed / total)) if total > 0 else 0
    filled = round(pct * 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"`[{bar}]` {int(pct * 100)}% elapsed"


def _remaining_str(session: "BlitzSession") -> str:
    now = datetime.now(timezone.utc)
    remaining = session.ends_at - now
    total_s = int(remaining.total_seconds())
    if total_s <= 0:
        return "⏰ **Time's up!**"
    h, rem = divmod(total_s, 3600)
    m = rem // 60
    if h > 0:
        return f"⏱️ **{h}h {m}m remaining**"
    return f"⏱️ **{m} minutes remaining**"


def blitz_announce_embed(session: "BlitzSession", participant_count: int = 1) -> discord.Embed:
    """Main pinned countdown embed — updated in-place by the job."""
    tech_emoji = TECH_EMOJI.get(session.tech_category, "⚙️")
    del_emoji = DELIVERABLE_EMOJI.get(session.deliverable_type, "🚀")

    embed = discord.Embed(
        title=f"⚡ TECH BLITZ — {session.technology.upper()}",
        description=(
            f"{tech_emoji} **Learning:** {session.technology}\n"
            f"{del_emoji} **Goal:** {session.goal}\n\n"
            f"{_countdown_bar(session)}\n"
            f"{_remaining_str(session)}"
        ),
        color=discord.Color.from_rgb(255, 200, 0),  # gold
    )
    embed.add_field(
        name="⏰ Ends",
        value=f"<t:{int(session.ends_at.timestamp())}:F>",
        inline=True,
    )
    embed.add_field(
        name="👥 Participants",
        value=str(participant_count),
        inline=True,
    )
    embed.add_field(
        name="⌛ Duration",
        value=f"{session.duration_hours}h" + (f" (+{session.extended_hours}h extended)" if session.extended_hours else ""),
        inline=True,
    )
    embed.set_footer(
        text="Use /blitz join to enter · /blitz checkin to post progress · /blitz showcase to submit your project"
    )
    return embed


def blitz_milestone_embed(session: "BlitzSession", milestone: str) -> discord.Embed:
    messages = {
        "50pct_done": (
            "🏃 **Halfway there!**",
            "You've used half your time. How's the project coming along?\nPost a `/blitz checkin` and keep the momentum.",
            discord.Color.blue(),
        ),
        "75pct_done": (
            "🔥 **Final stretch — 25% left!**",
            "Time to lock in. Focus on what you can ship.\nPost your progress with `/blitz checkin`.",
            discord.Color.orange(),
        ),
        "1h_left": (
            "🚨 **ONE HOUR LEFT!**",
            "Wrap up, clean up, and prepare your showcase.\nUse `/blitz showcase` to submit when ready.",
            discord.Color.red(),
        ),
    }
    title, desc, color = messages.get(milestone, ("⚡ Blitz Update", "Keep going!", discord.Color.greyple()))
    embed = discord.Embed(
        title=f"{title} · {session.technology}",
        description=desc,
        color=color,
    )
    embed.add_field(name="⏱️ Time Remaining", value=_remaining_str(session), inline=False)
    return embed


def blitz_checkin_embed(
    checkin: "BlitzCheckin",
    member: discord.Member,
    session: "BlitzSession",
    checkin_number: int,
) -> discord.Embed:
    mood_label = MOOD_EMOJI.get(checkin.mood, "") if checkin.mood else ""
    embed = discord.Embed(
        title=f"📣 Check-in #{checkin_number} · {member.display_name}",
        description=checkin.content,
        color=discord.Color.green(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if mood_label:
        embed.add_field(name="Vibe", value=f"{mood_label} {checkin.mood}/5", inline=True)
    embed.add_field(name="Blitz", value=session.technology, inline=True)
    embed.add_field(name="Time Left", value=_remaining_str(session), inline=True)
    if checkin.media_url:
        embed.set_image(url=checkin.media_url)
    embed.set_footer(text="React ❤️ to cheer them on!")
    return embed


def blitz_showcase_embed(
    showcase: "BlitzShowcase",
    member: discord.Member,
    session: "BlitzSession",
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏁 {showcase.title}",
        description=showcase.description,
        color=discord.Color.purple(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.add_field(name="🔤 Technology", value=session.technology, inline=True)
    embed.add_field(name="⏱️ Built in", value=f"{session.duration_hours}h Blitz", inline=True)
    if showcase.repo_url:
        embed.add_field(name="📂 Repo", value=f"[GitHub]({showcase.repo_url})", inline=True)
    if showcase.demo_url:
        embed.add_field(name="🔗 Demo / Play", value=f"[Link]({showcase.demo_url})", inline=False)
    if showcase.media_url:
        embed.set_image(url=showcase.media_url)
    embed.set_footer(text="React 🏆 to vote for this showcase!")
    return embed


def blitz_gallery_embed(
    session: "BlitzSession",
    showcases: "list[BlitzShowcase]",
    participants: int,
) -> discord.Embed:
    """End-of-blitz gallery summary embed."""
    tech_emoji = TECH_EMOJI.get(session.tech_category, "⚙️")
    embed = discord.Embed(
        title=f"🎉 Blitz Complete — {session.technology}",
        description=(
            f"{tech_emoji} {session.technology} · {session.duration_hours}h\n"
            f"**Goal:** {session.goal}\n\n"
            f"**{len(showcases)}/{participants}** participants shipped a project."
        ),
        color=discord.Color.gold(),
    )
    for i, s in enumerate(sorted(showcases, key=lambda x: -x.vote_count), 1):
        medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"#{i}"
        links = []
        if s.repo_url:
            links.append(f"[Repo]({s.repo_url})")
        if s.demo_url:
            links.append(f"[Demo]({s.demo_url})")
        link_str = " · ".join(links) if links else "—"
        embed.add_field(
            name=f"{medal} {s.title}  🏆 {s.vote_count}",
            value=f"{s.description[:80]}{'…' if len(s.description) > 80 else ''}\n{link_str}",
            inline=False,
        )
    return embed


def blitz_nudge_embed(session: "BlitzSession") -> discord.Embed:
    """DM embed sent to participants who haven't checked in recently."""
    embed = discord.Embed(
        title=f"⚡ Blitz check-in reminder!",
        description=(
            f"The **{session.technology}** blitz is still running!\n"
            f"Post your progress with `/blitz checkin` — your team wants to see what you've built.\n\n"
            f"{_remaining_str(session)}"
        ),
        color=discord.Color.from_rgb(255, 165, 0),
    )
    embed.set_footer(text="Use /blitz showcase when you're ready to submit.")
    return embed


def blitz_showcase_open_embed(session: "BlitzSession") -> discord.Embed:
    """Announcement that the timer ended and showcases are now open."""
    embed = discord.Embed(
        title=f"⏰ Time's Up! — {session.technology} Blitz",
        description=(
            "The blitz timer has ended. You now have **2 hours** to submit your showcase.\n\n"
            "Use `/blitz showcase` to post your project.\n"
            "Include a repo link, demo link, or screenshot."
        ),
        color=discord.Color.red(),
    )
    embed.set_footer(text="Voting opens after all showcases are submitted.")
    return embed
