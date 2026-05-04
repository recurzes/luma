from __future__ import annotations

import discord

from app import database
from app.models.member import Member
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

    return member