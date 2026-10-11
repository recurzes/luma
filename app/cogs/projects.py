import discord
from discord import app_commands
from discord.ext import commands

from app import database
from app.services.project_service import ProjectService
from app.embeds.project_embed import *
from app.models.project import ProjectCreate
from app.utils.github_repo import normalize_repo
from app.utils.guards import require_member, staff_only


@app_commands.guild_only()
class ProjectsCog(commands.GroupCog, name="project"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.project_svc = ProjectService(database.get_db())
        super().__init__()

    @app_commands.command(name="create", description="Create a new project")
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
    async def create(
            self,
            interaction: discord.Interaction,
            name: str,
            type: str,
            description: str = ""
    ):
        await interaction.response.defer()
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return
        project = await self.project_svc.create(
            ProjectCreate(
                name=name,
                type=type,
                description=description,
                guild_id=str(interaction.guild_id)
            ),
            creator_id=member.id
        )
        embed = project_info_embed(project)
        embed.set_footer(text="Active project set automatically")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="list", description="List all active projects")
    async def list(self, interaction: discord.Interaction):
        await interaction.response.defer()
        projects = await self.project_svc.list_active(str(interaction.guild_id))
        if not projects:
            await interaction.followup.send("No active projects yet. Create one with `/project create`")
            return
        embed = project_list_embed(projects)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="switch", description="Switch your active project context")
    @app_commands.describe(name="Project name to switch to")
    async def switch(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return
        projects = await self.project_svc.list_active(str(interaction.guild_id))
        match = next((p for p in projects if p.name.lower() == name.lower()), None)
        if not match:
            await interaction.followup.send(f"No active project named **{name}**.", ephemeral=True)
            return
        await self.project_svc.set_active_project(member.id, match.id)
        await interaction.followup.send(
            f"Active project set to **{match.name}**. All `/ticket` and `/phase` commands now target this project",
            ephemeral=True
        )

    @app_commands.command(name="archive", description="Archive a completed project")
    @staff_only()
    async def archive(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        projects = await self.project_svc.list_active(str(interaction.guild_id))
        match = next((p for p in projects if p.name.lower() == name.lower()), None)
        if not match:
            await interaction.followup.send(f"No active project named **{name}**", ephemeral=True)
            return
        await self.project_svc.archive(match.id)
        await interaction.followup.send(f"Project **{match.name}** archived", ephemeral=True)

    @app_commands.command(name="info", description="Show details of the active or named project")
    @app_commands.describe(name="Project name (omit to use active project)")
    async def info(self, interaction: discord.Interaction, name: str = ""):
        await interaction.response.defer()
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return
        if name:
            projects = await self.project_svc.list_active(str(interaction.guild_id))
            project = next((p for p in projects if p.name.lower() == name.lower()), None)
        else:
            project = await self.project_svc.resolve_active_or_abort(member.id, interaction)
            if not project:
                return
        if not project:
            await interaction.followup.send(f"No active project named **{name}**", ephemeral=True)
            return
        embed = project_info_embed(project)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="link-repo", description="Link a GitHub repo to this project")
    @staff_only()
    @app_commands.describe(url="GitHub repository URL")
    async def link_repo(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)
        try:
            member = await require_member(interaction)
        except RuntimeError:
            return
        project = await self.project_svc.resolve_active_or_abort(member.id, interaction)
        if not project:
            return
        repo = normalize_repo(url)
        if repo is None:
            await interaction.followup.send(
                "That doesn't look like a GitHub repository. Use `https://github.com/owner/repo` or `owner/repo`",
                ephemeral=True
            )
            return

        # Stored as owner/repo: GitHub events for it are routed to this server by this link.
        await self.project_svc.link_repo(project.id, f"https://github.com/{repo}")
        await interaction.followup.send(
            f"Linked **{repo}** to **{project.name}**. Pushes and PRs on it now post in this server",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ProjectsCog(bot))
