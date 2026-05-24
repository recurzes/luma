from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from dateutil.parser import parse as parse_dt

import structlog
from supabase import Client

from app.models.badge import Badge, BadgeDefinition
from app.services.xp_service import XPService

log = structlog.get_logger()

_TRIGGER_MAP: dict[str, list[str]] = {
    "helped_stuck": ["rubber_duck"],
    "streak_check": ["streak_starter", "on_fire", "unstoppable", "legendary"],
    "standup": ["standup_champion"],
    "shoutout_given": ["helpful_human"],
    "close_t1":      ["clutch_coder"],
    "close_t2":      ["clutch_coder"],
    "close_t3":      ["clutch_coder"],
    "pr_merged": ["shit_it", "no_any_club"],
    "knowledge_drop": ["knowledge_dealer"]
}


class BadgeService:
    def __init__(self, db: Client, xp: XPService):
        self._db = db
        self._xp = xp

    async def _run(self, fn):
        return await asyncio.get_event_loop().run_in_executor(None, fn)

    async def _get_definition(self, key: str) -> BadgeDefinition | None:
        def _fetch():
            return (
                self._db.table("bot_badge_definitions")
                .select("*")
                .eq("key", key)
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        if not result.data:
            return None

        return BadgeDefinition.model_validate(result.data[0])

    async def _already_earned(self, member_id: str, badge_id: str) -> bool:
        def _fetch():
            return (
                self._db.table("bot_badges_earned")
                .select("id")
                .eq("member_id", member_id)
                .eq("badge_id", badge_id)
                .limit(1)
                .execute()
            )

        result = await self._run(_fetch)
        return bool(result.data)

    async def _award(self, member_id: str, badge_id: str) -> bool:
        try:
            def _insert():
                return (
                    self._db.table("bot_badges_earned")
                    .insert(
                        {
                            "member_id": member_id,
                            "badge_id": badge_id,
                            "earned_at": datetime.now(timezone.utc).isoformat()
                        }
                    )
                    .execute()
                )
            await self._run(_insert)
            return True
        except Exception as exc:
            if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
                return False
            raise


    async def check_and_award(
            self,
            member_id: str,
            trigger_event: str,
            context: dict | None = None
    ) -> list[Badge]:
        context = context or {}
        badge_keys = _TRIGGER_MAP.get(trigger_event, [])
        awarded: list[Badge] = []

        for key in badge_keys:
            earned = await self._check_single(member_id, key, context)
            if earned:
                awarded.append(earned)

        return awarded

    async def get_member_badges(self, member_id: str) -> list[Badge]:
        def _fetch():
            return (
                self._db.table("bot_badges_earned")
                .select("id, member_id, badge_id, earned_at, bot_badge_definitions(key, name, description, emoji)")
                .eq("member_id", member_id)
                .order("earned_at", desc=False)
                .execute()
            )

        result = await self._run(_fetch)
        badges = []
        for row in result.data:
            defn = row.get("bot_badge_definitions") or {}
            badges.append(Badge(
                id=row["id"],
                member_id=row["member_id"],
                badge_id=row["badge_id"],
                key=defn.get("key", ""),
                name=defn.get("name", ""),
                description=defn.get("description", ""),
                emoji=defn.get("emoji", ""),
                earned_at=row["earned_at"],
            ))

        return badges

    # Trigger Checks

    async def _check_single(self, member_id: str, key: str, context: dict) -> Badge | None:
        defn = await self._get_definition(key)
        if defn is None:
            return None
        if await self._already_earned(member_id, str(defn.id)):
            return None

        unlocked = False
        if key == "rubber_duck":
            unlocked = await self._check_rubber_duck(member_id)
        elif key == "streak_starter":
            unlocked = (context.get("current_streak", 0) >= 3)
        elif key == "on_fire":
            unlocked = (context.get("current_streak", 0) >= 7)
        elif key == "unstoppable":
            unlocked = (context.get("current_streak", 0) >= 14)
        elif key == "legendary":
            unlocked = (context.get("current_streak", 0) >= 30)
        elif key == "standup_champion":
            unlocked = await self._check_standup_champion(member_id)
        elif key == "helpful_human":
            unlocked = await self._check_helpful_human(member_id)
        elif key == "clutch_coder":
            ticket = context.get("ticket")
            if ticket:
                unlocked = self._check_clutch_coder(ticket)
        elif key == "ship_it":
            unlocked = self._check_ship_it(
                context.get("pr_opened_at", context.get("pr_merged_at"))
            )
        elif key == "no_any_club":
            unlocked = await self._check_no_any_club(member_id)
        elif key == "knowledge_dealer":
            unlocked = await self._check_knowledge_dealer(member_id)

        if not unlocked:
            return None

        awarded = await self._award(member_id, str(defn.id))
        if not awarded:
            return None

        log.info("badge.awarded", member_id=member_id, badge_key=key)
        earned_at = datetime.now(timezone.utc)
        return Badge(
            id=defn.id,
            member_id=member_id, # type: ignore[arg-type]
            badge_id=defn.id,
            key=defn.key,
            name=defn.name,
            description=defn.description,
            emoji=defn.emoji,
            earned_at=earned_at
        )

    async def _check_rubber_duck(self, member_id: str) -> bool:
        def _count():
            return (
                self._db.table("bot_xp_ledger")
                .select("id", count="exact")
                .eq("member_id", member_id)
                .eq("action", "helped_stuck")
                .execute()
            )

        result = await self._run(_count)
        return (result.count or 0) >= 5

    async def _check_standup_champion(self, member_id: str) -> bool:
        def _fetch():
            return (
                self._db.table("bot_xp_ledger")
                .select("awarded_at")
                .eq("member_id", member_id)
                .eq("action", "standup")
                .order("awarded_at", desc=True)
                .limit(7)
                .execute()
            )

        result = await self._run(_fetch)
        return len(result.data) >= 7

    async def _check_helpful_human(self, member_id: str) -> bool:
        def _count():
            return (
                self._db.table("bot_xp_ledger")
                .select("id", count="exact")
                .eq("member_id", member_id)
                .eq("action", "shoutout_given")
                .execute()
            )

        result = await self._run(_count)
        return (result.data or 0) >= 3

    def _check_clutch_coder(self, ticket: dict) -> bool:
        deadline = ticket.get("deadline")
        closed_at = ticket.get("closed_at")
        if not deadline or not closed_at:
            return False
        try:
            if isinstance(deadline, str):
                deadline = parse_dt(deadline)
            if isinstance(closed_at, str):
                closed_at = parse_dt(closed_at)
            return abs((deadline - closed_at).total_seconds()) <= 3600
        except Exception:
            return False

    def _check_ship_it(self, pr_opened_at, pr_merged_at) -> bool:
        if not pr_opened_at or not pr_merged_at:
            return False
        try:
            if isinstance(pr_opened_at, str):
                pr_opened_at = parse_dt(pr_opened_at)
            if isinstance(pr_merged_at, str):
                pr_merged_at = parse_dt(pr_merged_at)
            return pr_opened_at.date() == pr_merged_at.date()

        except Exception:
            return False

    async def _check_no_any_club(self, member_id: str) -> bool:
        def _fetch():
            return (
                self._db.table("bot_xp_ledger")
                .select("metadata")
                .eq("member_id", member_id)
                .eq("action", "pr_merged")
                .execute()
            )

        result = await self._run(_fetch)
        clean_prs = [
            r for r in result.data
            if not (r.get("metadata") or {}).get("any_flag", False)
        ]
        return len(clean_prs) >= 10

    async def _check_knowledge_dealer(self, member_id: str) -> bool:
        def _count():
            return (
                self._db.table("bot_xp_ledger")
                .select("id", count="exact")
                .eq("member_id", member_id)
                .eq("action", "knowledge_drop")
                .execute()
            )

        result = await self._run(_count)
        return (result.count or 0) >= 5
