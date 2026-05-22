from __future__ import annotations

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.config import settings
from app.services.member_service import MemberService
from app.utils.guards import require_member

log = structlog.get_logger()


def _detect_role(member: discord.Member) -> tuple[str, str]:
    role_names = {r.name for r in member.roles}
    if settings.DISCORD_ROLE_LEAD in role_names:
        return "lead", "T3"
    if settings.DISCORD_ROLE_PROFESSOR in role_names:
        return "professor", "T3"
    return "beginner", "T1"


class MemberCog(commands.GroupCog, name="member"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    @property
    def _service(self) -> MemberService:
        return MemberService(database.get_db())

    @app_commands.command(name="register", description="Register yourself as a LumaBot member")
    async def register(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if not isinstance(interaction.user, discord.Member):
            await interaction.followup.send(
                "This command must be used inside the server.",
                ephemeral=True
            )
            return

        role, tier_max = _detect_role(interaction.user)

        try:
            member = await self._service.register(
                discord_id=str(interaction.user.id),
                discord_name=interaction.user.display_name,
                role=role,
                tier_max=tier_max
            )
        except ValueError:
            embed = discord.Embed(
                title="Already registered",
                description="You are already registered. Use `/member info` to see your profile",
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(title="Registered!", color=discord.Color.green())
        embed.add_field(name="Name", value=member.discord_name, inline=True)
        embed.add_field(name="Role", value=member.role.capitalize(), inline=True)
        embed.add_field(name="Max Tier", value=member.tier_max, inline=True)
        embed.set_footer(text="Link your GitHub with /member github <username>")

        log.info("member.register.success", discord_id=str(interaction.user.id), role=role)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="info", description="Show a member's profile")
    @app_commands.describe(target="Member to look up (defaults to you)")
    async def info(
            self,
            interaction: discord.Interaction,
            target: discord.Member | None = None
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        lookup_id = str((target or interaction.user).id)
        member = await self._service.get_by_discord_id(lookup_id)

        if member is None:
            await interaction.followup.send("That user is not registered", ephemeral=True)
            return

        embed = discord.Embed(title=member.discord_name, color=discord.Color.blurple())
        embed.add_field(name="Role", value=member.role.capitalize(), inline=True)
        embed.add_field(name="Max Tier", value=member.tier_max, inline=True)
        embed.add_field(
            name="GitHub",
            value=member.github_username or "not linked",
            inline=True
        )
        embed.add_field(
            name="Joined",
            value=discord.utils.format_dt(member.created_at, style="D"),
            inline=True
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="github", description="Link your GitHub username to your profile")
    @app_commands.describe(username="Your GitHub username")
    async def github(self, interaction: discord.Interaction, username: str) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            await require_member(interaction)
        except RuntimeError:
            return

        member = await self._service.update_github_username(str(interaction.user.id), username)

        embed = discord.Embed(
            title="GitHub linked",
            description=f"Your GitHub username is now set to **{member.github_username}**",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemberCog(bot))