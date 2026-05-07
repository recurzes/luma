from __future__ import annotations

import discord

from app.models.member import Member


def build_commit_embed(branch: str, commits: list[dict], author_member: Member | None) -> discord.Embed:
    author_name = author_member.discord_name if author_member else (commits[0].get("author", {}).get("name", "unknown") if commits else "unknown")
    n = len(commits)

    embed = discord.Embed(
        title=f"[{branch}] {n} commit{'s' if n != 1 else ''} pushed",
        color=discord.Color.green(),
    )
    embed.set_author(name=author_name)

    lines: list[str] = []
    for c in commits[:5]:
        sha = c.get("id", "")[:7]
        msg = c.get("message", "").splitlines()[0][:72]
        url = c.get("url", "")
        lines.append(f"[`{sha}`]({url}) {msg}")
    if n > 5:
        lines.append(f"_… and {n - 5} more_")

    embed.description = "\n".join(lines) if lines else "_No commit messages_"
    return embed


def build_pr_embed(
    pr_number: int | None,
    pr_title: str,
    pr_url: str,
    author_member: Member | None,
    reviewer_member: Member | None,
    merged: bool = False,
) -> discord.Embed:
    if merged:
        color = discord.Color.purple()
        status = "Merged"
    else:
        color = discord.Color.blurple()
        status = "Opened"

    embed = discord.Embed(
        title=f"PR #{pr_number} {status}: {pr_title}",
        url=pr_url,
        color=color,
    )

    embed.add_field(name="Author", value=author_member.discord_name if author_member else "Unknown", inline=True)
    embed.add_field(name="Reviewer", value=reviewer_member.discord_name if reviewer_member else "TBD", inline=True)

    if merged:
        embed.set_footer(text="Merged ✅")

    return embed


def build_ci_failure_embed(check_name: str, conclusion: str, url: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"❌ CI {conclusion.capitalize()}: {check_name}",
        url=url,
        description=f"The **{check_name}** check failed with conclusion **{conclusion}**.\n[View run]({url})",
        color=discord.Color.red(),
    )
    return embed
