"""Tests for XPService — no live Supabase needed."""
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

from unittest.mock import MagicMock
from uuid import uuid4

from app.services.xp_service import XPService, compute_level, level_title

MEMBER_ID = str(uuid4())


def _make_db(old_total=0, old_level=1):
    db = MagicMock()

    def _chain(data=None, count=0):
        c = MagicMock()
        r = MagicMock()
        r.data = data or []
        r.count = count
        c.execute.return_value = r
        for m in ["select", "insert", "update", "eq", "neq", "order", "limit", "in_"]:
            getattr(c, m).return_value = c
        return c

    stats_row = [{"total_xp": old_total, "level": old_level}]

    def _table(name):
        if "ledger" in name:
            return _chain(data=[{"id": str(uuid4()), "member_id": MEMBER_ID, "action": "standup", "xp": 5, "awarded_at": "2025-01-01"}])
        if "stat" in name:
            return _chain(data=stats_row)
        if name == "bot_members":
            return _chain(data=[{"id": MEMBER_ID, "discord_id": "1", "discord_name": "Dev"}])
        return _chain()

    db.table.side_effect = _table
    return db


# ── compute_level helpers ─────────────────────────────────────────────────────

def test_level_1_below_threshold():
    assert compute_level(99) == 1


def test_level_2_at_threshold():
    assert compute_level(100) == 2


def test_level_3_at_250():
    assert compute_level(250) == 3


def test_level_titles_non_empty():
    for lvl in range(1, 8):
        assert level_title(lvl) != ""


# ── XPService.award ───────────────────────────────────────────────────────────

async def test_award_returns_result():
    db = _make_db(old_total=0, old_level=1)
    svc = XPService(db)
    result = await svc.award(MEMBER_ID, "standup")
    assert result.xp_awarded == 5
    assert result.new_total == 5
    assert result.level_up is False


async def test_award_level_up_detected():
    # old_total=95, awarding close_t1 (10 XP) → 105, crosses 100 threshold
    db = _make_db(old_total=95, old_level=1)
    svc = XPService(db)
    result = await svc.award(MEMBER_ID, "close_t1")
    assert result.new_total == 105
    assert result.new_level == 2
    assert result.level_up is True


async def test_award_no_level_up_when_already_past():
    db = _make_db(old_total=110, old_level=2)
    svc = XPService(db)
    result = await svc.award(MEMBER_ID, "standup")
    assert result.level_up is False


async def test_award_unknown_action_gives_zero_xp():
    db = _make_db()
    svc = XPService(db)
    result = await svc.award(MEMBER_ID, "nonexistent_action")
    assert result.xp_awarded == 0


# ── XPService.leaderboard ─────────────────────────────────────────────────────

async def test_leaderboard_empty_returns_empty():
    db = MagicMock()

    def _chain(data=None):
        c = MagicMock()
        r = MagicMock()
        r.data = data or []
        r.count = 0
        c.execute.return_value = r
        for m in ["select", "eq", "order", "limit", "in_"]:
            getattr(c, m).return_value = c
        return c

    db.table.side_effect = lambda name: _chain()
    svc = XPService(db)
    result = await svc.leaderboard()
    assert result == []


async def test_leaderboard_ordered_by_xp():
    mid1, mid2 = str(uuid4()), str(uuid4())
    db = MagicMock()

    call_count = {"n": 0}

    def _chain_stats():
        c = MagicMock()
        r = MagicMock()
        r.data = [
            {"member_id": mid1, "total_xp": 200, "level": 2, "current_streak": 5},
            {"member_id": mid2, "total_xp": 100, "level": 1, "current_streak": 1},
        ]
        c.execute.return_value = r
        for m in ["select", "eq", "order", "limit", "in_"]:
            getattr(c, m).return_value = c
        return c

    def _chain_members():
        c = MagicMock()
        r = MagicMock()
        r.data = [
            {"id": mid1, "discord_id": "10", "discord_name": "Alice"},
            {"id": mid2, "discord_id": "20", "discord_name": "Bob"},
        ]
        c.execute.return_value = r
        for m in ["select", "eq", "order", "limit", "in_"]:
            getattr(c, m).return_value = c
        return c

    def _table(name):
        if "stat" in name:
            return _chain_stats()
        return _chain_members()

    db.table.side_effect = _table
    svc = XPService(db)
    entries = await svc.leaderboard()
    assert len(entries) == 2
    assert entries[0].discord_name == "Alice"
    assert entries[0].rank == 1
    assert entries[1].rank == 2