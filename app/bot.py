from __future__ import annotations

import pkgutil
import time
from pathlib import Path

import discord
import structlog
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from app import database
from app.config import settings

log = structlog.get_logger()

_start_time = time.monotonic()


def _configure_logging() -> None:
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso")
    ]
    if settings.DEBUG:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.DEBUG else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True
    )


class LumaBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)
        self.scheduler = AsyncIOScheduler()

    async def setup_hook(self) -> None:
        await self._load_cogs()
        self.scheduler.start()
        log.info("scheduler.started")

    async def _load_cogs(self) -> None:
        cogs_path = Path(__file__).parent / "cogs"
        for module_info in pkgutil.iter_modules([str(cogs_path)]):
            module_name = f"app.cogs.{module_info.name}"
            await self.load_extension(module_name)
            log.info("cog.loaded", cog=module_name)

        guild = discord.Object(id=settings.DISCORD_GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        log.info("commands.synced", count=len(synced), guild_id=settings.DISCORD_GUILD_ID)

    async def on_ready(self) -> None:
        assert self.user is not None
        db_ok = await database.ping()
        log.info(
            "bot.ready",
            user=str(self.user),
            guild_id=settings.DISCORD_GUILD_ID,
            supabase=db_ok
        )
        if not db_ok:
            log.warning("supabase.unreachable", hint="Apply migrations before using bot features")


def main() -> None:
    _configure_logging()
    bot = LumaBot()
    bot.run(settings.DISCORD_TOKEN, log_handler=None)


if __name__ == '__main__':
    main()