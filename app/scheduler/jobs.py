from __future__ import annotations

import structlog

log = structlog.get_logger()

async def standup_dm() -> None:
    raise NotImplementedError


async def standup_compile() -> None:
    raise NotImplementedError


async def standup_nag() -> None:
    raise NotImplementedError


async def stuck_check() -> None:
    raise NotImplementedError


async def stale_ticket_check() -> None:
    raise NotImplementedError


async def streak_check() -> None:
    raise NotImplementedError


async def leaderboard_post() -> None:
    raise NotImplementedError


async def tip_of_day() -> None:
    raise NotImplementedError


async def mood_checkin() -> None:
    raise NotImplementedError


async def pr_stale_check() -> None:
    raise NotImplementedError