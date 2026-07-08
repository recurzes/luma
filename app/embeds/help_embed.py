from __future__ import annotations

import discord

from app.data.command_help import COMMAND_GROUPS, GROUP_ORDER, GroupHelp


def build_help_index() -> discord.Embed:
    lines: list[str] = []
    for key in GROUP_ORDER:
        group = COMMAND_GROUPS[key]
        reg = "" if group.requires_registration else " · public"
        lines.append(f"**{group.title}** (`{key}`){reg} — {group.summary}")

    embed = discord.Embed(
        title="LumaBot Command Groups",
        description="\n".join(lines),
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="Detailed help",
        value="Use `/help group:<name>` for commands and sample usage.",
        inline=False,
    )
    embed.set_footer(text="Most commands require /member register in this server")
    return embed


def build_group_help(group: GroupHelp) -> discord.Embed:
    embed = discord.Embed(
        title=f"{group.title} Commands",
        description=group.summary,
        color=discord.Color.blurple(),
    )

    for cmd in group.commands:
        value = f"{cmd.description}\n**Sample:** `{cmd.usage}`"
        if cmd.notes:
            value += f"\n_{cmd.notes}_"
        embed.add_field(name=cmd.name, value=value, inline=False)

    if group.requires_registration:
        embed.set_footer(text="Requires registration: /member register")
    else:
        embed.set_footer(text="No registration required")

    return embed
