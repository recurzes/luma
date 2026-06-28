import discord
from discord import app_commands
from discord.ext import commands

from app.services.project_service import ProjectService
from app.embeds.project_embed import *
from app.models.project import ProjectCreate


class ProjectsCog(commands.Cog):
    def __init__(self, bot: commands.Bot, project_svc: ProjectService):
        self.bot = bot
        self.project_svc = project_svc

    project_group = app_commands.Group(name="project", description="Manage your projects")

    @project_group.command(name="create", description="Create a new project")
    @app_commands.describe(
        name="Project name",
        type="Project type",
        description="Short description"
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Web", value="web"),
        app_commands.Choice(name="Mobile", value="mobile"),
        app_commands.Choice(name="Game", value="game"),
        app_commands.Choice(name="Research", value="research"),
        app_commands.Choice(name="Capstone", value="capstone"),
        app_commands.Choice(name="Hackathon", value="hackathon"),
        app_commands.Choice(name="Other", value="other")
    ])
    async def project_create(
            self,
            interaction: discord.Interaction,
            name: str,
            type: str,
            description: str = ""
    ):
        await interaction.response.defer()
        project = await self.project_svc.create(
            ProjectCreate(
                name=name,
                type=type,
                description=description,
                guild_id=str(interaction.guild_id)
            ),
            creator_id=interaction.user.id
        )
        embed = project_info_embed(project)
        embed.set_footer(text="Active project set automatically")
        await interaction.followup.send(embed=embed)


    @project_group.command(name="list", description="List all active projects")
    async def project_list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        projects = await self.project_svc.list_active(str(interaction.guild_id))
        if not projects:
            await interaction.followup.send("No active projects yet. Create one with `/project create`")
            return
        embed = project_list_embed(projects)
        await interaction.followup.send(embed=embed)


    @project_group.command(name="switch", description="Switch your active project context")
    @app_commands.describe(name="Project name to switch to")
    async def project_switch(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        projects = await self.project_svc.list_active(str(interaction.guild.id))
        match = next((p for p in projects if p.name.lower() == name.lower()), None)
        if not match:
            await interaction.followup.send(f"No active project named **{name}**.", ephemeral=True)
            return
        await self.project_svc.set_active_project(interaction.user.id, match.id)
        await interaction.followup.send(
            f"Active project set to **{match.name}**. All `/ticket` and `/phase` commands now target this project",
            ephemeral=True
        )


    @project_group.command(name="archive", description="Archive a completed project")
    @app_commands.checks.has_any_role("Lead", "Professor")
    async def project_archive(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        projects = await self.project_svc.list_active(str(interaction.guild_id))
        match = next((p for p in projects if p.name.lower() == name.lower()), None)
        if not match:
            await interaction.followup.send(f"No active project named **{name}**", ephemeral=True)
            return
        await self.project_svc.archive(match.id)
        await interaction.followup.send(f"Project **{match.name}** archived", ephemeral=True)


    @project_group.command(name="info", description="Show details of the active or named project")
    @app_commands.describe(name="Project name (omit to use active project)")
    async def project_info(self, interaction: discord.Interaction, name: str = ""):
        await interaction.response.defer()
        if name:
            projects = await self.project_svc.list_active(str(interaction.guild_id))
            project = next((p for p in projects if p.name.lower() == name.lower()), None)
        else:
            project = await self.project_svc.resolve_active_or_abort(
                interaction.user.id,
                interaction
            )
        if not project:
            return
        embed = project_info_embed(project)
        await interaction.followup.send(embed=embed)


    @project_group.command(name="link-repo", description="Link a GitHub repo to this project")
    @app_commands.checks.has_any_role("Lead", "Professor")
    @app_commands.describe(url="GitHub repository URL")
    async def project_link_repo(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)
        project = await self.project_svc.resolve_active_or_abort(interaction.user.id, interaction)
        if not project:
            return
        await self.project_svc.link_repo(project.id, url)
        await interaction.followup.send(f"Linked **{url}** to **{project.name}**", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ProjectsCog(bot, bot.services["project"]))