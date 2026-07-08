from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import partial
from typing import Any
from uuid import UUID

import structlog
from supabase import Client

from app.models.notification_preference import NOTIFICATION_FEATURES, NotificationPreference

log = structlog.get_logger()


class NotificationService:
    def __init__(self, db: Client) -> None:
        self._db = db

    def _run(self, fn, *args, **kwargs):
        return asyncio.get_event_loop().run_in_executor(None, partial[Any](fn, *args, **kwargs))

    def _parse(self, data: dict) -> NotificationPreference:
        return NotificationPreference.model_validate(data)

    async def _get_preference(
            self,
            member_id: UUID,
            guild_id: str,
            feature: str
    ) -> NotificationPreference | None:
        def _fetch():
            return (
                self._db.table("bot_notification_preferences")
                .select("*")
                .eq("member_id", str(member_id))
                .eq("guild_id", guild_id)
                .eq("feature", feature)
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        if not result.data:
            return None
        return self._parse(result.data[0])

    async def is_enabled(self, member_id: UUID, guild_id: str, feature: str) -> bool:
        if feature not in NOTIFICATION_FEATURES:
            raise ValueError(f"Unknown notification feature: {feature!r}")
        pref = await self._get_preference(member_id, guild_id, feature)
        if pref is None:
            return True
        return pref.enabled

    async def set_enabled(
            self,
            member_id: UUID,
            guild_id: str,
            feature: str,
            enabled: bool
    ) -> NotificationPreference:
        if feature not in NOTIFICATION_FEATURES:
            raise ValueError(f"Unknown notification feature: {feature!r}")

        existing = await self._get_preference(member_id, guild_id, feature)
        now = datetime.now(tz=timezone.utc).isoformat()

        if existing is not None:
            def _update():
                return (
                    self._db.table("bot_notification_preferences")
                    .update({"enabled": enabled, "updated_at": now})
                    .eq("id", str(existing.id))
                    .execute()
                )

            result = await self._run(_update)
            log.info(
                "notification.updated",
                member_id=str(member_id),
                guild_id=guild_id,
                feature=feature,
                enabled=enabled,
            )
            return self._parse(result.data[0])

        def _insert():
            return (
                self._db.table("bot_notification_preferences")
                .insert(
                    {
                        "member_id": str(member_id),
                        "guild_id": guild_id,
                        "feature": feature,
                        "enabled": enabled,
                        "updated_at": now,
                    }
                )
                .execute()
            )

        result = await self._run(_insert)
        log.info(
            "notification.created",
            member_id=str(member_id),
            guild_id=guild_id,
            feature=feature,
            enabled=enabled,
        )
        return self._parse(result.data[0])

    async def list_preferences(self, member_id: UUID, guild_id: str) -> dict[str, bool]:
        def _fetch():
            return (
                self._db.table("bot_notification_preferences")
                .select("*")
                .eq("member_id", str(member_id))
                .eq("guild_id", guild_id)
                .execute()
            )

        result = await self._run(_fetch)
        stored = {row["feature"]: row["enabled"] for row in result.data}
        return {feature: stored.get(feature, True) for feature in NOTIFICATION_FEATURES}
