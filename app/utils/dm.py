from __future__ import annotations

from uuid import UUID

import discord

from app.services.notification_service import NotificationService
from app.utils.dm import format_dm


async def send_notification_dm(
        bot: discord.Client,
        *,
        discord_id: str,
        member_id: UUID,
        guild: discord.Guild,
        feature: str,
        body: str,
        notification_svc: NotificationService,
) -> bool:
    if not await notification_svc.is_enabled(member_id, str(guild.id), feature):
        return False

    try:
        user = bot.get_user(int(discord_id)) or await bot.fetch_user(int(discord_id))
        await user.send(format_dm(guild.name, body))
        return True
    except (discord.Forbidden, discord.NotFound):
        return False
