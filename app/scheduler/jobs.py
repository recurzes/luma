from __future__ import annotations

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from discord.ext import commands

log = structlog.get_logger()


def register_all_jobs(scheduler: AsyncIOScheduler, bot: commands.AutoShardedBot) -> None:
    _register_standup_jobs(scheduler, bot)
    _register_xp_jobs(scheduler, bot)
    _register_stuck_jobs(scheduler, bot)
    _register_monitoring_jobs(scheduler, bot)
    _register_journal_jobs(scheduler, bot)


def _register_standup_jobs(scheduler: AsyncIOScheduler, bot: commands.AutoShardedBot) -> None:
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


def _register_xp_jobs(scheduler: AsyncIOScheduler, bot: commands.AutoShardedBot) -> None:
    cog = bot.cogs.get("XPCog")
    if cog is None:
        log.warning("jobs.xp_cog_missing", hint="XPCog not loaded — XP/streak jobs skipped")
        return

    scheduler.add_job(
        cog._leaderboard_post_job,
        "cron",
        day_of_week="fri",
        hour=17,
        minute=0,
        id="leaderboard_post",
        replace_existing=True
    )
    scheduler.add_job(
        cog._streak_check_job,
        "cron",
        hour=23,
        minute=50,
        id="streak_check",
        replace_existing=True
    )
    scheduler.add_job(
        cog._streak_risk_dm_job,
        "cron",
        hour=20,
        minute=0,
        id="streak_risk_dm",
        replace_existing=True
    )


def _register_stuck_jobs(scheduler: AsyncIOScheduler, bot: commands.AutoShardedBot) -> None:
    cog = bot.cogs.get("StuckCog")
    if cog is None:
        log.warning("jobs.stuck_cog_missing", hint="StuckCog not loaded — stuck jobs skipped")
        return

    scheduler.add_job(
        cog._stuck_check_job,
        trigger=IntervalTrigger(minutes=5),
        id="stuck_check",
        replace_existing=True,
    )
    log.info("jobs.stuck_registered")


def _register_monitoring_jobs(scheduler: AsyncIOScheduler, bot: commands.AutoShardedBot) -> None:
    cog = bot.cogs.get("MonitoringCog")
    if cog is None:
        log.warning("jobs.monitoring_cog_missing", hint="MonitoringCog not loaded — monitoring skipped")
        return

    scheduler.add_job(
        cog._stale_ticket_check,
        "cron",
        hour=9,
        minute=0,
        id="stale_ticket_check",
        replace_existing=True
    )

    scheduler.add_job(
        cog._pr_stale_check,
        "cron",
        hour=10,
        minute=0,
        id="pr_stale_check",
        replace_existing=True
    )

    scheduler.add_job(
        cog._tip_of_the_day,
        "cron",
        hour=9,
        minute=30,
        id="tip_of_the_day",
        replace_existing=True
    )

    scheduler.add_job(
        cog._mood_checkin_dm,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        id="mood_checkin_dm",
        replace_existing=True
    )

    scheduler.add_job(
        cog._mood_aggregate_post,
        "cron",
        day_of_week="mon",
        hour=15,
        minute=0,
        id="mood_aggregate_post",
        replace_existing=True
    )

    log.info("jobs.monitoring_registered")


def _register_journal_jobs(scheduler: AsyncIOScheduler, bot: commands.AutoShardedBot) -> None:
    cog = bot.cogs.get("JournalCog")
    if cog is None:
        log.warning("jobs.journal_cog_missing", hint="JournalCog not loaded — journaling skipped")
        return

    scheduler.add_job(
        cog._send_eod_journal_prompts,
        "cron",
        day_of_week="mon-fri",
        hour=17,
        minute=0,
        id="journal_eod_prompt",
        replace_existing=True,
    )

    log.info("jobs.journal_registered")
