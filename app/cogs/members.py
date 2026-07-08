from __future__ import annotations

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from app import database
from app.config import settings
from app.models.notification_preference import NOTIFICATION_FEATURES
from app.services.enrollment_service import EnrollmentService
from app.services.member_service import MemberService
from app.services.notification_service import NotificationService
from app.utils.guards import require_member

log = structlog.get_logger()

_FEATURE_CHOICES = [
    app_commands.Choice(name=label, value=key)
    for key, label in NOTIFICATION_FEATURES.items()
]


def _detect_role(member: discord.Member) -> tuple[str, str]:
    role_names = {r.name for r in member.roles}
    if settings.DISCORD_ROLE_LEAD in role_names:
        return "lead", "T3"
    if settings.DISCORD_ROLE_PROFESSOR in role_names:
        return "professor", "T3"
    return "beginner", "T1"


class MemberCog(commands.GroupCog, name="member"):
    notifications = app_commands.Group(
        name="notifications",
        description="Manage personal message preferences for this server",
    )
    feature = app_commands.Group(
        name="feature",
        description="Join or leave optional bot features for this server",
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    @property
    def _service(self) -> MemberService:
        return MemberService(database.get_db())

    def _enrollment(self) -> EnrollmentService:
        return EnrollmentService(database.get_db())

    def _notifications(self) -> NotificationService:
        return NotificationService(database.get_db())

    @app_commands.command(name="register", description="Register yourself as a LumaBot member")
    async def register(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            await interaction.followup.send(
                "This command must be used inside the server.",
                ephemeral=True
            )
            return

        role, tier_max = _detect_role(interaction.user)
        guild_id = str(interaction.guild_id)
        guild_name = interaction.guild.name

        existing = await self._service.get_by_discord_id(str(interaction.user.id))

        try:
            if existing is None:
                member = await self._service.register(
                    discord_id=str(interaction.user.id),
                    discord_name=interaction.user.display_name,
                    role=role,
                    tier_max=tier_max,
                )
            else:
                member = await self._service.update_role_and_tier(
                    discord_id=str(interaction.user.id),
                    role=role,
                    tier_max=tier_max,
                    discord_name=interaction.user.display_name,
                )

            await self._enrollment().enroll(member.id, guild_id, guild_name)
        except ValueError as exc:
            embed = discord.Embed(
                title="Registration failed",
                description=str(exc),
                color=discord.Color.red(),
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        embed = discord.Embed(title="Registered!", color=discord.Color.green())
        embed.add_field(name="Server", value=guild_name, inline=True)
        embed.add_field(name="Name", value=member.discord_name, inline=True)
        embed.add_field(name="Role", value=member.role.capitalize(), inline=True)
        embed.add_field(name="Max Tier", value=member.tier_max, inline=True)
        embed.set_footer(text="Link GitHub with /member github · Join features with /member feature join <feature>")

        log.info("member.register.success", discord_id=str(interaction.user.id), role=role, guild_id=guild_id)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="signout", description="Sign out of Luma in this server")
    async def signout(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("This command must be used inside the server.", ephemeral=True)
            return

        member = await self._service.get_by_discord_id(str(interaction.user.id))
        if member is None:
            await interaction.followup.send("You are not registered with Luma.", ephemeral=True)
            return

        try:
            await self._enrollment().sign_out(member.id, str(interaction.guild_id))
        except ValueError:
            await interaction.followup.send("You are not enrolled in this server.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Signed out",
            description=(
                f"You will no longer receive personal messages from Luma in **{interaction.guild.name}** "
                "and cannot use bot commands here until you `/member register` again."
            ),
            color=discord.Color.orange(),
        )
        log.info("member.signout", discord_id=str(interaction.user.id), guild_id=str(interaction.guild_id))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @notifications.command(name="list", description="Show personal message preferences for this server")
    async def notifications_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("This command must be used inside the server.", ephemeral=True)
            return

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        prefs = await self._notifications().list_preferences(member.id, str(interaction.guild_id))

        lines = [
            f"{'✅' if enabled else '❌'} **{NOTIFICATION_FEATURES[key]}** (`{key}`)"
            for key, enabled in prefs.items()
        ]
        embed = discord.Embed(
            title=f"Notifications — {interaction.guild.name}",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Use /member feature join <feature> or /member notifications off <feature>")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @notifications.command(name="off", description="Opt out of a personal message type")
    @app_commands.describe(feature="Which notification to disable")
    @app_commands.choices(feature=_FEATURE_CHOICES)
    async def notifications_off(
            self,
            interaction: discord.Interaction,
            feature: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("This command must be used inside the server.", ephemeral=True)
            return

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        await self._notifications().set_enabled(
            member.id, str(interaction.guild_id), feature.value, False
        )
        await interaction.followup.send(
            f"Disabled **{NOTIFICATION_FEATURES[feature.value]}** for **{interaction.guild.name}**.",
            ephemeral=True,
        )

    @notifications.command(name="on", description="Re-enable a personal message type")
    @app_commands.describe(feature="Which notification to enable")
    @app_commands.choices(feature=_FEATURE_CHOICES)
    async def notifications_on(
            self,
            interaction: discord.Interaction,
            feature: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("This command must be used inside the server.", ephemeral=True)
            return

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        await self._notifications().set_enabled(
            member.id, str(interaction.guild_id), feature.value, True
        )
        await interaction.followup.send(
            f"Enabled **{NOTIFICATION_FEATURES[feature.value]}** for **{interaction.guild.name}**.",
            ephemeral=True,
        )

    @feature.command(name="list", description="Show which features you have joined on this server")
    async def feature_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("This command must be used inside the server.", ephemeral=True)
            return

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        prefs = await self._notifications().list_preferences(member.id, str(interaction.guild_id))

        lines = [
            f"{'✅' if enabled else '⬜'} **{NOTIFICATION_FEATURES[key]}** (`{key}`)"
            for key, enabled in prefs.items()
        ]
        embed = discord.Embed(
            title=f"Features — {interaction.guild.name}",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Use /member feature join <feature> or /member feature leave <feature>")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @feature.command(name="join", description="Join a feature on this server")
    @app_commands.describe(feature="Which feature to join")
    @app_commands.choices(feature=_FEATURE_CHOICES)
    async def feature_join(
            self,
            interaction: discord.Interaction,
            feature: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("This command must be used inside the server.", ephemeral=True)
            return

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        await self._notifications().set_enabled(
            member.id, str(interaction.guild_id), feature.value, True
        )
        await interaction.followup.send(
            f"Joined **{NOTIFICATION_FEATURES[feature.value]}** on **{interaction.guild.name}**.",
            ephemeral=True,
        )

    @feature.command(name="leave", description="Leave a feature on this server")
    @app_commands.describe(feature="Which feature to leave")
    @app_commands.choices(feature=_FEATURE_CHOICES)
    async def feature_leave(
            self,
            interaction: discord.Interaction,
            feature: app_commands.Choice[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("This command must be used inside the server.", ephemeral=True)
            return

        try:
            member = await require_member(interaction)
        except RuntimeError:
            return

        await self._notifications().set_enabled(
            member.id, str(interaction.guild_id), feature.value, False
        )
        await interaction.followup.send(
            f"Left **{NOTIFICATION_FEATURES[feature.value]}** on **{interaction.guild.name}**.",
            ephemeral=True,
        )

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
