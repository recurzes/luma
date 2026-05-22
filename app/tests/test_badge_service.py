"""Tests for BadgeService — checks award logic without hitting Supabase."""
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

from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.badge_service import BadgeService
from app.services.xp_service import XPService

# ── Helpers ───────────────────────────────────────────────────────────────────

_BADGE_DEF_ID = str(uuid4())
_MEMBER_ID = str(uuid4())


def _make_db(
    badge_def_data=None,
    earned_data=None,
    ledger_count=0,
    ledger_data=None,
    insert_raises=None,
):
    """Build a mock Supabase client for BadgeService tests."""
    db = MagicMock()

    def _chain(final_data=None, final_count=0):
        chain = MagicMock()
        result = MagicMock()
        result.data = final_data or []
        result.count = final_count
        chain.execute = MagicMock(return_value=result)
        chain.eq = MagicMock(return_value=chain)
        chain.in_ = MagicMock(return_value=chain)
        chain.limit = MagicMock(return_value=chain)
        chain.order = MagicMock(return_value=chain)
        chain.select = MagicMock(return_value=chain)
        chain.insert = MagicMock(return_value=chain)
        chain.neq = MagicMock(return_value=chain)
        chain.lt = MagicMock(return_value=chain)
        chain.gt = MagicMock(return_value=chain)
        if insert_raises:
            chain.execute = MagicMock(side_effect=insert_raises)
        return chain

    table_map = {
        "bot_badge_definitions": _chain(badge_def_data or []),
        "bot_badges_earned": _chain(earned_data or [], ledger_count),
        "bot_xp_ledger": _chain(ledger_data or [], ledger_count),
    }

    def _table(name):
        return table_map.get(name, _chain())

    db.table = _table
    return db


def _make_svc(db=None, xp=None):
    db = db or _make_db()
    xp = xp or XPService(db)
    return BadgeService(db, xp)


# ── _check_rubber_duck ────────────────────────────────────────────────────────

async def test_rubber_duck_not_enough():
    db = _make_db(ledger_count=3)
    svc = _make_svc(db)
    result = await svc._check_rubber_duck(_MEMBER_ID)
    assert result is False


async def test_rubber_duck_exactly_five():
    db = _make_db(ledger_count=5)
    svc = _make_svc(db)
    result = await svc._check_rubber_duck(_MEMBER_ID)
    assert result is True


# ── _check_helpful_human ──────────────────────────────────────────────────────

async def test_helpful_human_threshold():
    db = _make_db(ledger_count=3)
    svc = _make_svc(db)
    result = await svc._check_helpful_human(_MEMBER_ID)
    assert result is True


async def test_helpful_human_below_threshold():
    db = _make_db(ledger_count=2)
    svc = _make_svc(db)
    result = await svc._check_helpful_human(_MEMBER_ID)
    assert result is False


# ── _check_ship_it ────────────────────────────────────────────────────────────

def test_ship_it_same_day():
    svc = _make_svc()
    opened = datetime(2025, 5, 4, 9, 0, tzinfo=timezone.utc)
    merged = datetime(2025, 5, 4, 23, 59, tzinfo=timezone.utc)
    assert svc._check_ship_it(opened, merged) is True


def test_ship_it_different_day():
    svc = _make_svc()
    opened = datetime(2025, 5, 4, 9, 0, tzinfo=timezone.utc)
    merged = datetime(2025, 5, 5, 10, 0, tzinfo=timezone.utc)
    assert svc._check_ship_it(opened, merged) is False


def test_ship_it_missing_dates():
    svc = _make_svc()
    assert svc._check_ship_it(None, None) is False


# ── _check_clutch_coder ───────────────────────────────────────────────────────

def test_clutch_coder_within_hour():
    svc = _make_svc()
    ticket = {
        "deadline": "2025-05-04T12:00:00+00:00",
        "closed_at": "2025-05-04T11:45:00+00:00",
    }
    assert svc._check_clutch_coder(ticket) is True


def test_clutch_coder_too_late():
    svc = _make_svc()
    ticket = {
        "deadline": "2025-05-04T12:00:00+00:00",
        "closed_at": "2025-05-04T13:30:00+00:00",
    }
    assert svc._check_clutch_coder(ticket) is False


def test_clutch_coder_missing_deadline():
    svc = _make_svc()
    assert svc._check_clutch_coder({"closed_at": "2025-05-04T12:00:00+00:00"}) is False


# ── check_and_award ───────────────────────────────────────────────────────────

async def test_check_and_award_no_trigger():
    svc = _make_svc()
    badges = await svc.check_and_award(_MEMBER_ID, "unknown_event")
    assert badges == []


async def test_check_and_award_streak_starter_awarded():
    badge_row = {
        "id": _BADGE_DEF_ID,
        "key": "streak_starter",
        "name": "Streak Starter",
        "description": "First 3-day streak",
        "emoji": "🔥",
        "trigger": "3-day streak",
    }
    db = _make_db(badge_def_data=[badge_row], earned_data=[])
    svc = _make_svc(db)
    badges = await svc.check_and_award(_MEMBER_ID, "streak_check", {"current_streak": 3})
    assert len(badges) == 1
    assert badges[0].key == "streak_starter"


async def test_check_and_award_already_earned():
    badge_row = {
        "id": _BADGE_DEF_ID,
        "key": "streak_starter",
        "name": "Streak Starter",
        "description": "First 3-day streak",
        "emoji": "🔥",
        "trigger": "3-day streak",
    }
    # already_earned returns data → skip award
    earned_row = [{"id": str(uuid4())}]
    db = _make_db(badge_def_data=[badge_row], earned_data=earned_row)
    svc = _make_svc(db)
    badges = await svc.check_and_award(_MEMBER_ID, "streak_check", {"current_streak": 3})
    assert badges == []


async def test_check_and_award_duplicate_insert_ignored():
    """If DB raises a unique violation on insert, award returns False and no badge is returned."""
    badge_row = {
        "id": _BADGE_DEF_ID,
        "key": "rubber_duck",
        "name": "Rubber Duck",
        "description": "Resolved 5 /stuck threads",
        "emoji": "🦆",
        "trigger": "5 helped_stuck",
    }

    # Custom mock: badge_definitions and earned (not-yet-earned check) return normally,
    # but the insert on bot_badges_earned raises a unique violation.
    db = MagicMock()

    def _normal_chain(data, count=0):
        chain = MagicMock()
        result = MagicMock()
        result.data = data
        result.count = count
        chain.execute = MagicMock(return_value=result)
        chain.eq = MagicMock(return_value=chain)
        chain.limit = MagicMock(return_value=chain)
        chain.select = MagicMock(return_value=chain)
        return chain

    def _raising_chain():
        chain = MagicMock()
        chain.execute = MagicMock(side_effect=Exception("duplicate key value violates unique constraint"))
        chain.eq = MagicMock(return_value=chain)
        chain.limit = MagicMock(return_value=chain)
        chain.select = MagicMock(return_value=chain)
        chain.insert = MagicMock(return_value=chain)
        return chain

    ledger_result_chain = _normal_chain([], count=5)

    call_count = {"n": 0}

    def _earned_table_factory():
        c = call_count["n"]
        call_count["n"] += 1
        if c == 0:
            # First call: _already_earned check → returns empty (not yet earned)
            return _normal_chain([])
        else:
            # Second call: _award insert → raises duplicate
            return _raising_chain()

    def _table(name):
        if name == "bot_badge_definitions":
            return _normal_chain([badge_row])
        if name == "bot_badges_earned":
            return _earned_table_factory()
        if name == "bot_xp_ledger":
            return ledger_result_chain
        return _normal_chain([])

    db.table = _table
    svc = BadgeService(db, XPService(db))
    badges = await svc.check_and_award(_MEMBER_ID, "helped_stuck")
    assert badges == []


# ── get_member_badges ─────────────────────────────────────────────────────────

async def test_get_member_badges_empty():
    svc = _make_svc()
    result = await svc.get_member_badges(_MEMBER_ID)
    assert result == []


# ── Streak badge thresholds ───────────────────────────────────────────────────

def _streak_badge_row(key: str, emoji: str) -> dict:
    return {
        "id": str(uuid4()),
        "key": key,
        "name": key.replace("_", " ").title(),
        "description": f"{key} badge",
        "emoji": emoji,
        "trigger": "streak milestone",
    }


async def _streak_check(key: str, emoji: str, streak_value: int, should_unlock: bool):
    from unittest.mock import patch, AsyncMock
    from app.models.badge import BadgeDefinition
    from uuid import uuid4

    svc = _make_svc()
    defn = BadgeDefinition(id=uuid4(), key=key, name=key.replace("_", " ").title(),
                           description=f"{key} badge", emoji=emoji, trigger="streak milestone")
    with patch.object(svc, "_get_definition", AsyncMock(return_value=defn)):
        with patch.object(svc, "_already_earned", AsyncMock(return_value=False)):
            with patch.object(svc, "_award", AsyncMock(return_value=True)):
                result = await svc._check_single(_MEMBER_ID, key, {"current_streak": streak_value})
    if should_unlock:
        assert result is not None and result.key == key
    else:
        assert result is None


async def test_streak_starter_unlocks_at_3():
    await _streak_check("streak_starter", "🔥", 3, True)


async def test_streak_starter_not_at_2():
    await _streak_check("streak_starter", "🔥", 2, False)


async def test_on_fire_unlocks_at_7():
    await _streak_check("on_fire", "🔥🔥", 7, True)


async def test_on_fire_not_at_6():
    await _streak_check("on_fire", "🔥🔥", 6, False)


async def test_unstoppable_unlocks_at_14():
    await _streak_check("unstoppable", "🔥🔥🔥", 14, True)


async def test_legendary_unlocks_at_30():
    await _streak_check("legendary", "👑", 30, True)


async def test_legendary_not_at_29():
    await _streak_check("legendary", "👑", 29, False)
