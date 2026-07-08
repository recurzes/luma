from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from app.data.command_help import COMMAND_GROUPS, GROUP_ORDER
from app.embeds.help_embed import build_group_help, build_help_index


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="help", description="List command groups or show detailed help")
    @app_commands.describe(group="Command group to look up (optional)")
    @app_commands.autocomplete(group=_group_autocomplete)
    async def help(
            self,
            interaction: discord.Interaction,
            group: str | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if group is None:
            await interaction.followup.send(embed=build_help_index(), ephemeral=True)
            return

        key = group.lower().strip()
        info = COMMAND_GROUPS.get(key)
        if info is None:
            await interaction.followup.send(
                f"Unknown group **{group}**. Run `/help` to see available groups.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(embed=build_group_help(info), ephemeral=True)


async def _group_autocomplete(
        interaction: discord.Interaction,
        current: str,
) -> list[app_commands.Choice[str]]:
    current_lower = current.lower()
    choices = []
    for key in GROUP_ORDER:
        info = COMMAND_GROUPS[key]
        if current_lower in key or current_lower in info.title.lower():
            choices.append(app_commands.Choice(name=info.title, value=key))
    return choices[:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
