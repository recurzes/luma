from __future__ import annotations

import time

import discord
import structlog
from discord import app_commands
from discord.ext import commands
from markdown_it.rules_core import inline

from app import database

log = structlog.get_logger()

_bot_start: float = time.monotonic()


class Ping(commands.GroupCog, name="bot"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        super().__init__()

    @app_commands.command(name="ping", description="Check bot latency and service health")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        latency_ms = round(self.bot.latency * 1000)
        db_ok = await database.ping()
        uptime_s = int(time.monotonic() - _bot_start)
        uptime_str = f"{uptime_s // 3600}h {(uptime_s % 3600)}m {uptime_s % 60}s"

        db_status = "✓ Supabase" if db_ok else "✗ Supabase (unreachable)"

        embed = discord.Embed(title="Pong!", color=discord.Color.green() if db_ok else discord.Color.red())
        embed.add_field(name="Latency", value=f"{latency_ms} ms", inline=True)
        embed.add_field(name="Database", value=db_status, inline=True)
        embed.add_field(name="Uptime", value=uptime_str, inline=True)

        log.info("ping.command", latency_ms=latency_ms, db_ok=db_ok)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Ping(bot))