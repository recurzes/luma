from __future__ import annotations

import asyncio
import pkgutil
import time
import sys
from pathlib import Path

import discord
import structlog
from postgrest.exceptions import APIError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord import app_commands
from discord.ext import commands

from app import database
from app.channels import CHANNEL_MANIFEST
from app.config import settings
from app.logging_config import configure_logging
from dotenv import load_dotenv

from app.scheduler.jobs import register_all_jobs

log = structlog.get_logger()

load_dotenv()

_start_time = time.monotonic()


def _configure_logging() -> None:
    configure_logging()

INTENTS = discord.Intents.default()
INTENTS.members = True
INTENTS.message_content = True


class LumaBot(commands.AutoShardedBot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

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
        register_all_jobs(self.scheduler, self)
        self.scheduler.start()
        log.info("scheduler.started")
        self.tree.on_error = self._on_app_command_error
        await self.tree.sync()
        self.loop.create_task(self._github_event_poll_loop())

    async def _load_cogs(self) -> None:
        cogs_path = Path(__file__).parent / "cogs"
        for module_info in pkgutil.iter_modules([str(cogs_path)]):
            module_name = f"app.cogs.{module_info.name}"
            await self.load_extension(module_name)
            log.info("cog.loaded", cog=module_name)

        # if settings.DISCORD_GUILD_ID:
        #     guild = discord.Object(id=settings.DISCORD_GUILD_ID)
        #     self.tree.copy_global_to(guild=guild)
        #     synced = await self.tree.sync(guild=guild)
        #     log.info("commands.synced", count=len(synced), guild_id=settings.DISCORD_GUILD_ID)
        # else:
        #     synced = await self.tree.sync()
        #     log.info("commands.synced", count=len(synced), scope="global")

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
        # Guild channels are not cached before on_ready, and events may be waiting from downtime.
        await self.wait_until_ready()
        log.info("github.poll_loop.started")

        while not self.is_closed():
            await asyncio.sleep(5)
            try:
                processed, failed = await self._github_service().process_pending()
                if processed or failed:
                    log.info("github.poll_loop.batch", processed=processed, failed=failed)

            except APIError as e:
                err = e.args[0] if e.args else {}
                log.error(
                    "github.poll_loop.error",
                    code=err.get("code"),
                    message=err.get("message"),
                    details=err.get("details"),
                )
            except Exception as e:
                log.error("github.poll_loop.error", error=str(e))

    def _github_service(self):
        from app.services.github_service import GitHubService
        from app.services.member_service import MemberService
        from app.services.steak_service import StreakService
        from app.services.xp_service import XPService

        db = database.get_db()
        members = MemberService(db)
        return GitHubService(
            db=db, members=members, xp=XPService(db), streak=StreakService(db, members), bot=self
        )


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
        # Subclasses first: all of these except the last are CheckFailures.
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"Slow down! Try again in **{error.retry_after:.0f}s**"
        elif isinstance(error, app_commands.MissingAnyRole):
            roles = " or ".join(str(r) for r in error.missing_roles)
            msg = f"Only {roles} can use this command"
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = "I'm missing Discord permissions to do that"
        elif isinstance(error, app_commands.CheckFailure):
            msg = "You don't have permission to use this command"
        else:
            original = getattr(error, "original", error)
            log.error(
                "app_command.error",
                command=interaction.command and interaction.command.qualified_name,
                error_type=type(original).__name__,
                error=str(original)
            )
            msg = "Something went wrong. Try again or ping the Lead"

        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except discord.HTTPException as e:
            log.warning("app_command.error_reply_failed", error=str(e))


async def main() -> None:
    _configure_logging()
    try:
        settings.require("DISCORD_TOKEN", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
    except RuntimeError as e:
        log.error("config.invalid", error=str(e))
        sys.exit(1)
    if settings.DISCORD_TOKEN == "place_holder_set_before_running_bot":
        log.error("DISCORD_TOKEN is not set. Set it in .env before running the bot")
        sys.exit(1)
    bot = LumaBot()
    async with bot:
        await bot.start(settings.DISCORD_TOKEN)


if __name__ == '__main__':
    asyncio.run(main())