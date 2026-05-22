from __future__ import annotations

import asyncio
import pkgutil
import time
from datetime import datetime, timezone
from pathlib import Path

import discord
import structlog
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord import app_commands
from discord.ext import commands

from app import database
from app.channels import CHANNEL_MANIFEST
from app.config import settings
from app.logging_config import configure_logging

log = structlog.get_logger()

_start_time = time.monotonic()

_last_event_poll: str = datetime.now(timezone.utc).isoformat()


def _configure_logging() -> None:
    configure_logging()


class LumaBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)
        self.scheduler = AsyncIOScheduler()

        self.guild: discord.Guild | None = None
        self.channels: dict[tuple[int, str], int] = {}

    def get_text_channel(
            self,
            key: str,
            guild: discord.Guild | None = None
    ) -> discord.TextChannel | None:
        g = guild or self.guild
        if g is None:
            if len(self.guilds) == 1:
                g = self.guilds[0]
            else:
                return None

        cache_key = (g.id, key)
        ch_id = self.channels.get(cache_key)
        if ch_id:
            ch = g.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                return ch

        attr = f"CHANNEL_{key.upper()}"
        fallback_id = getattr(settings, attr, None)
        if fallback_id:
            ch = g.get_channel(int(fallback_id))
            if isinstance(ch, discord.TextChannel):
                self.channels[cache_key] = ch.id
                return ch

        manifest = CHANNEL_MANIFEST.get(key)
        if manifest:
            name, topic = manifest
            by_name = discord.utils.get(g.text_channels, name=name)
            if isinstance(by_name, discord.TextChannel):
                self.channels[cache_key] = by_name.id
                return by_name

        return None

    async def setup_hook(self) -> None:
        await self._load_cogs()
        self.scheduler.start()
        log.info("scheduler.started")
        self.tree.on_error = self._on_app_command_error
        self.loop.create_task(self._github_event_poll_loop())

    async def _load_cogs(self) -> None:
        cogs_path = Path(__file__).parent / "cogs"
        for module_info in pkgutil.iter_modules([str(cogs_path)]):
            module_name = f"app.cogs.{module_info.name}"
            await self.load_extension(module_name)
            log.info("cog.loaded", cog=module_name)

        if settings.DISCORD_GUILD_ID:
            guild = discord.Object(id=settings.DISCORD_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("commands.synced", count=len(synced), guild_id=settings.DISCORD_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("commands.synced", count=len(synced), scope="global")

    async def on_ready(self) -> None:
        assert self.user is not None
        if settings.DISCORD_GUILD_ID:
            if self.guild is None:
                self.guild = self.get_guild(settings.DISCORD_GUILD_ID)
                if self.guild is not None:
                    await self._ensure_channels(self.guild)
        else:
            for guild in self.guilds:
                await self._ensure_channels(guild)
        db_ok = await database.ping()
        log.info(
            "bot.ready",
            user=str(self.user),
            guild_id=settings.DISCORD_GUILD_ID,
            guilds=len(self.guilds),
            supabase=db_ok
        )
        if not db_ok:
            log.warning("supabase.unreachable", hint="Apply migrations before using bot features")

    async def _github_event_poll_loop(self) -> None:
        global _last_event_poll
        log.info("github.poll_loop.started")

        while not self.is_closed():
            await asyncio.sleep(5)
            try:
                cutoff = _last_event_poll

                def _fetch():
                    return (
                        database.get_db()
                        .table("bot_github_events")
                        .select("*")
                        .gt("received_at", cutoff)
                        .order("received_at", desc=False)
                        .execute()
                    )

                result = await asyncio.get_event_loop().run_in_executor(None, _fetch)

                if result.data:
                    _last_event_poll = result.data[-1]["received_at"]
                    await self._dispatch_github_events(result.data)

            except Exception as e:
                log.error("github.poll_loop.error", error=str(e))

    async def _dispatch_github_events(self, events: list[dict]) -> None:
        from app.services.github_service import GitHubService
        from app.services.member_service import MemberService
        from app.services.steak_service import StreakService
        from app.services.xp_service import XPService

        db = database.get_db()
        members = MemberService(db)
        xp = XPService(db)
        streak = StreakService(db, members)
        svc = GitHubService(db=db, members=members, xp=xp, streak=streak, bot=self)

        for event in events:
            await svc.dispatch(event)


    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("guild.joined", guild=guild.name, guild_id=guild.id)
        if settings.DISCORD_GUILD_ID is None:
            try:
                await self.tree.sync(guild=discord.Object(id=guild.id))
            except discord.Forbidden:
                log.warning("commands.sync_forbidden", guild_id=guild.id)
        self.guild = guild if settings.DISCORD_GUILD_ID else None
        await self._ensure_channels(guild)

        if settings.DISCORD_GUILD_ID:
            guild_obj = discord.Object(id=guild.id)
            self.tree.copy_global_to(guild=guild_obj)
            await self.tree.sync(guild=guild_obj)

    async def _ensure_channels(self, guild: discord.Guild) -> None:
        existing = {ch.name: ch for ch in guild.text_channels}

        category = discord.utils.get(guild.categories, name="LumaBot")
        if category is None:
            try:
                category = await guild.create_category("LumaBot")
                log.info("category.created", name="LumaBot", guild=guild.name)
            except discord.Forbidden:
                log.warning("category.create_forbidden", hint="Bot lacks Manage Channels permission")
                category = None

        created_count = 0
        for key, (name, topic) in CHANNEL_MANIFEST.items():
            cache_key = (guild.id, key)
            if name in existing:
                self.channels[cache_key] = existing[name].id
            else:
                try:
                    kwargs: dict = {"topic": topic}
                    if category is not None:
                        kwargs["category"] = category
                    ch = await guild.create_text_channel(name, **kwargs)
                    self.channels[cache_key] = ch.id
                    created_count += 1
                    log.info("channel.created", name=name, guild=guild.name)
                except discord.Forbidden:
                    log.warning("channel.create_forbidden", name=name, hint="Bot lacks Manage Channels permission")

        log.info("channels.ensured", found=len(self.channels), created=created_count, guild=guild.name)

    async def _on_app_command_error(
            self,
            interaction: discord.Interaction,
            error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"Slow down! Try again in **{error.retry_after:.0f}s**"
        elif isinstance(error, app_commands.CheckFailure):
            msg = "You don't have permission to use this command"
        elif isinstance(error, app_commands.MissingPermissions):
            msg = "I'm missing Discord permissions to do that"
        else:
            log.error(
                "app_command.error",
                command=interaction.command and interaction.command.name,
                error=str(error)
            )
            msg = "Service temporarily unavailable. Please try again"

        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_response(msg, ephemeral=True)
        except Exception:
            pass


def main() -> None:
    _configure_logging()
    bot = LumaBot()
    bot.run(settings.DISCORD_TOKEN, log_handler=None)


if __name__ == '__main__':
    main()