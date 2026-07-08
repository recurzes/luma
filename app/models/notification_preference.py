from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

NOTIFICATION_FEATURES: dict[str, str] = {
    "standup": "Daily standup DMs",
    "mood": "Monday mood check-in",
    "journal": "End-of-day journal prompts",
    "streak": "Streak risk and broken streak alerts",
    "track": "Track progress nudges",
    "blitz": "Blitz inactivity reminders",
    "stuck": "Stuck thread escalation (leads only)",
}


class NotificationPreference(BaseModel):
    id: UUID
    member_id: UUID
    guild_id: str
    feature: str
    enabled: bool
    updated_at: datetime
