from __future__ import annotations

from datetime import date, datetime, time, timedelta
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


def previous_working_day(day: date) -> date:
    """The most recent Monday-Friday before `day`."""
    previous = day - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous
