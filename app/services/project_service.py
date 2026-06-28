from __future__ import annotations

import discord
from uuid import UUID
from datetime import datetime, timezone

from supabase import Client

from app.models.project import Project, ProjectCreate, ProjectMember


class ProjectService:
    def __init__(self, db: Client):
        self.db = db


    # Creation
    async def create(self, payload: ProjectCreate, creator_id: UUID) -> Project:
        result = (
            self.db.table("companion_projects")
            .insert({
                "name": payload.name,
                "description": payload.description,
                "type": payload.type,
                "github_repo_url": payload.github_repo_url,
                "owner_id": str(creator_id),
                "discord_guild_id": payload.guild_id
            })
            .execute()
        )
        project = Project(**result.data[0])

        self.db.table("companion_project_members").insert({
            "project_id": str(project.id),
            "member_id": str(creator_id),
            "role": "owner"
        }).execute()
        await self.set_active_project(creator_id, project.id)
        return project


    # Context
    async def set_active_project(self, member_id: UUID, project_id: UUID) -> None:
        self.db.table("companion_member_context").upsert({
            "member_id": str(member_id),
            "active_project_id": str(project_id),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="member_id").execute()


    async def get_active_project(self, member_id: UUID) -> Project | None:
        ctx = (
            self.db.table("companion_member_context")
            .select("active_project_id")
            .eq("member_id", str(member_id))
            .maybe_single()
            .execute()
        )
        if not ctx.data or not ctx.data["active_project_id"]:
            return None
        return await self.get_by_id(UUID(ctx.data["active_project_id"]))


    async def resolve_active_or_abort(
            self,
            member_id: UUID,
            interaction: discord.Interaction
    ) -> "Project | None":
        project = await self.get_active_project(member_id)
        if not project:
            await interaction.followup.send(
                "No active project set. Use `/project switch <name>` or `/project create` first.",
                ephemeral=True
            )
            return None
        return project


    # Queries
    async def get_by_id(self, project_id: UUID) -> Project | None:
        result = (
            self.db.table("companion_projects")
            .select("*")
            .eq("id", str(project_id))
            .maybe_single()
            .execute()
        )
        return Project(**result.data) if result.data else None


    async def list_active(self, guild_id: str, member_id: UUID | None = None) -> list[Project]:
        if member_id:
            result = (
                self.db.table("companion_project_members")
                .select("companion_projects(*)")
                .eq("member_id", str(member_id))
                .eq("companion_projects.discord_guild_id", guild_id)
                .eq("companion_projects.status", "active")
                .execute()
            )
            return [Project(**r["companion_projects"]) for r in result.data]

        result = (
            self.db.table("companion_projects")
            .select("*")
            .eq("discord_guild_id", guild_id)
            .eq("status", "active")
            .order("created_at")
            .execute()
        )
        return [Project(**r) for r in result.data]


    # Mutations
    async def archive(self, project_id: UUID) -> None:
        self.db.table("companion_projects").update({
            "status": "archived",
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", str(project_id)).execute()


    async def link_repo(self, project_id: UUID, repo_url: str) -> None:
        self.db.table("companion_projects").update({
            "github_repo_url": repo_url,
        }).eq("id", str(project_id)).execute()


    async def add_member(self, project_id: UUID, member_id: UUID, role: str = "contributor") -> None:
        self.db.table("companion_project_members").upsert({
            "project_id": str(project_id),
            "member_id": str(member_id),
            "role": role,
        }, on_conflict="project_id,member_id").execute()