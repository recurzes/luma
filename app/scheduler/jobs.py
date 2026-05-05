from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

log = structlog.get_logger()


def register_all_jobs(scheduler: AsyncIOScheduler, bot: commands.Bot) -> None:
    _register_standup_jobs(scheduler, bot)


def _register_standup_jobs(scheduler: AsyncIOScheduler, bot: commands.Bot) -> None:
    cog = bot.cogs.get("StandupCog")
    if cog is None:
        log.warning("jobs.standup_cog_missing", hint="StandupCog not loaded — standup jobs skipped")
        return

    scheduler.add_job(
        cog._standup_dm_job,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=0,
        id="standup_dm",
        replace_existing=True
    )
    scheduler.add_job(
        cog._standup_compile_job,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=30,
        id="standup_compile",
        replace_existing=True
    )
    scheduler.add_job(
        cog._standup_nag_job,
        "cron",
        day_of_week="mon-fri",
        hour=9,
        minute=45,
        id="standup_nag",
        replace_existing=True
    )
    log.info("jobs.standup_registered")