"""Tests for StreakService — no live Supabase needed."""
from __future__ import annotations

import os
os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
for _i, _ch in enumerate(
    ["CHANNEL_TASK_FEED","CHANNEL_STANDUP_LOG","CHANNEL_GITHUB_FEED","CHANNEL_CODE_REVIEW",
     "CHANNEL_PHASE_TRACKER","CHANNEL_HELP","CHANNEL_SHOUTOUTS","CHANNEL_ANNOUNCEMENTS",
     "CHANNEL_TIP_OF_THE_DAY","CHANNEL_RESOURCES","CHANNEL_RETRO","CHANNEL_RANKINGS","CHANNEL_GENERAL"], 1
):
    os.environ.setdefault(_ch, str(_i))

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.member_service import MemberService
from app.services.steak_service import StreakService

MEMBER_ID = str(uuid4())


def _chain(data=None, count=0):
    c = MagicMock()
    r = MagicMock()
    r.data = data or []
    r.count = count
    c.execute.return_value = r
    for m in ["select", "insert", "update", "upsert", "eq", "neq", "order",
              "limit", "in_", "is_", "lt", "gt"]:
        getattr(c, m).return_value = c
    return c


def _make_svc(streak_log_exists=False, current_streak=1, longest_streak=1):
    db = MagicMock()
    members_svc = MagicMock(spec=MemberService)
    members_svc.get_all_active = MagicMock()

    stats_data = [{"current_streak": current_streak, "longest_streak": longest_streak}]

    log_data = [{"id": "x"}] if streak_log_exists else []

    def _table(name):
        if "streak_log" in name:
            return _chain(data=log_data)
        if "stat" in name:
            return _chain(data=stats_data)
        return _chain()

    db.table.side_effect = _table
    return StreakService(db, members_svc), db, members_svc


# ── record_activity ───────────────────────────────────────────────────────────

async def test_record_activity_increments_streak():
    db = MagicMock()
    members_svc = MagicMock(spec=MemberService)

    log_chain = _chain(data=[])  # no log row → will insert
    stats_chain = _chain(data=[{"current_streak": 2, "longest_streak": 2}])

    def _table(name):
        if "streak_log" in name:
            return log_chain
        if "stat" in name:
            return stats_chain
        return _chain()

    db.table.side_effect = _table
    svc = StreakService(db, members_svc)
    await svc.record_activity(MEMBER_ID, "commit")
    stats_chain.update.assert_called()


async def test_record_activity_same_day_is_idempotent():
    db = MagicMock()
    members_svc = MagicMock(spec=MemberService)

    log_chain = _chain(data=[{"id": "x"}])  # row exists → return early
    stats_chain = _chain(data=[])

    def _table(name):
        if "streak_log" in name:
            return log_chain
        if "stat" in name:
            return stats_chain
        return _chain()

    db.table.side_effect = _table
    svc = StreakService(db, members_svc)
    await svc.record_activity(MEMBER_ID, "commit")
    log_chain.insert.assert_not_called()


async def test_longest_streak_updated_when_current_exceeds():
    db = MagicMock()
    members_svc = MagicMock(spec=MemberService)

    log_chain = _chain(data=[])
    stats_chain = _chain(data=[{"current_streak": 5, "longest_streak": 3}])

    def _table(name):
        if "streak_log" in name:
            return log_chain
        if "stat" in name:
            return stats_chain
        return _chain()

    db.table.side_effect = _table
    svc = StreakService(db, members_svc)
    await svc.record_activity(MEMBER_ID, "standup")
    # new_current=6, new_longest=max(3,6)=6 → update called
    stats_chain.update.assert_called()


# ── check_all_streaks ─────────────────────────────────────────────────────────

async def test_check_all_streaks_resets_inactive_member():
    db = MagicMock()
    members_svc = MagicMock(spec=MemberService)

    member_obj = MagicMock()
    member_obj.id = uuid4()
    members_svc.get_all_active = MagicMock(return_value=None)

    import asyncio

    async def _fake_get_all():
        return [member_obj]

    members_svc.get_all_active = _fake_get_all

    call_n = {"n": 0}

    def _table(name):
        c = _chain()
        if "streak_log" in name:
            # No activity today
            r = MagicMock()
            r.data = []
            c.execute.return_value = r
        elif "stat" in name:
            r = MagicMock()
            r.data = [{"current_streak": 4}]
            c.execute.return_value = r
        return c

    db.table.side_effect = _table
    svc = StreakService(db, members_svc)
    broken = await svc.check_all_streaks()
    assert str(member_obj.id) in broken


async def test_check_all_streaks_skips_zero_streak_member():
    db = MagicMock()
    members_svc = MagicMock(spec=MemberService)

    member_obj = MagicMock()
    member_obj.id = uuid4()

    async def _fake_get_all():
        return [member_obj]

    members_svc.get_all_active = _fake_get_all

    def _table(name):
        c = _chain()
        if "streak_log" in name:
            r = MagicMock()
            r.data = []
            c.execute.return_value = r
        elif "stat" in name:
            r = MagicMock()
            r.data = [{"current_streak": 0}]  # already zero — no reset needed
            c.execute.return_value = r
        return c

    db.table.side_effect = _table
    svc = StreakService(db, members_svc)
    broken = await svc.check_all_streaks()
    assert broken == []
