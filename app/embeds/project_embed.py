import discord
from app.models.project import Project


TYPE_EMOJI = {
    "web": "🌐",
    "mobile": "📱",
    "game": "🎮",
    "research": "🔬",
    "capstone": "🎓",
    "hackathon": "⚡",
    "other": "📦",
}

STATUS_COLOR = {
    "active": discord.Color.green(),
    "paused": discord.Color.orange(),
    "archived": discord.Color.greyple(),
}


def project_info_embed(project: Project) -> discord.Embed:
    emoji = TYPE_EMOJI.get(project.type, "📦")
    embed = discord.Embed(
        title=f"{emoji} {project.name}",
        description=project.description or "_No description_",
        color=STATUS_COLOR.get(project.status, discord.Color.blurple()),
    )
    embed.add_field(name="Type", value=project.type.capitalize(), inline=True)
    embed.add_field(name="Status", value=project.status.capitalize(), inline=True)
    if project.github_repo_url:
        embed.add_field(name="Repo", value=f"[GitHub]({project.github_repo_url})", inline=True)
    if project.created_at:
        embed.set_footer(text=f"Created {project.created_at.strftime('%b %d, %Y')}")
    return embed


def project_list_embed(projects: list[Project]) -> discord.Embed:
    embed = discord.Embed(
        title="📂 Active Projects",
        color=discord.Color.blurple(),
    )
    for p in projects:
        emoji = TYPE_EMOJI.get(p.type, "📦")
        embed.add_field(
            name=f"{emoji} {p.name}",
            value=f"Type: `{p.type}` | Status: `{p.status}`",
            inline=False,
        )
    embed.set_footer(text=f"{len(projects)} project(s) · Use /project switch <name> to set active")
    return embed
