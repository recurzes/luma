from __future__ import annotations

import discord

from app import database
from app.models.member import Member
from app.services.enrollment_service import EnrollmentService
from app.services.member_service import MemberService


async def require_member(interaction: discord.Interaction) -> Member:
    service = MemberService(database.get_db())
    member = await service.get_by_discord_id(str(interaction.user.id))

    if member is None:
        embed = discord.Embed(
            title="Not registered",
            description="You need to register first. Run `/member register` to get started",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        raise RuntimeError(f"User {interaction.user.id} is not a registered member")

    if interaction.guild is not None:
        enrollment_svc = EnrollmentService(database.get_db())
        if not await enrollment_svc.is_active(member.id, str(interaction.guild_id)):
            embed = discord.Embed(
                title="Signed out",
                description=(
                    "You are signed out of Luma in this server. "
                    "Run `/member register` to rejoin."
                ),
                color=discord.Color.orange(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            raise RuntimeError(f"User {interaction.user.id} is signed out in guild {interaction.guild_id}")

    return member
