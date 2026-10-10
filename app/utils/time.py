from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.config import settings


def tz() -> ZoneInfo:
    return ZoneInfo(settings.TIMEZONE)


def now() -> datetime:
    return datetime.now(tz())


def today() -> date:
    return now().date()


def start_of_today() -> datetime:
    return datetime.combine(today(), time.min, tzinfo=tz())
