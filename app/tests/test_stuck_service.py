"""Tests for StuckService — no live Supabase needed."""
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

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.stuck_service import StuckService
from app.services.xp_service import XPService

THREAD_ID = str(uuid4())
MEMBER_ID = str(uuid4())
HELPER_ID = str(uuid4())
NOW = datetime.now(timezone.utc)

_OPEN_ROW = {
    "id": THREAD_ID,
    "requester_id": MEMBER_ID,
    "problem": "Stuck on auth",
    "discord_thread_id": "999",
    "status": "open",
    "helper_id": None,
    "opened_at": NOW.isoformat(),
    "resolved_at": None,
    "escalated_at": None,
    "resolution_notes": None,
}

_RESOLVED_ROW = {**_OPEN_ROW, "status": "resolved", "helper_id": HELPER_ID, "resolved_at": NOW.isoformat()}
_ESCALATED_ROW = {**_OPEN_ROW, "status": "escalated", "escalated_at": NOW.isoformat()}


def _chain(data=None):
    c = MagicMock()
    r = MagicMock()
    r.data = data or []
    c.execute.return_value = r
    for m in ["select", "insert", "update", "eq", "neq", "order", "limit",
              "is_", "lt", "gt", "in_"]:
        getattr(c, m).return_value = c
    return c


def _make_svc(thread_data=None):
    db = MagicMock()
    xp_svc = MagicMock(spec=XPService)
    xp_svc.award = AsyncMock(return_value=MagicMock(xp_awarded=15))

    def _table(name):
        if "ledger" in name:
            return _chain()
        if "stat" in name:
            return _chain(data=[{"total_xp": 0, "level": 1}])
        if "help" in name:
            return _chain(data=thread_data if thread_data is not None else [_OPEN_ROW])
        return _chain()

    db.table.side_effect = _table
    return StuckService(db, xp_svc), xp_svc


# ── open_thread ───────────────────────────────────────────────────────────────

async def test_open_thread_returns_help_thread():
    svc, _ = _make_svc(thread_data=[_OPEN_ROW])
    thread = await svc.open_thread(MEMBER_ID, "Stuck on auth", "999")
    assert str(thread.id) == THREAD_ID
    assert thread.status == "open"


# ── get_open_threads ──────────────────────────────────────────────────────────

async def test_get_open_threads_returns_open():
    svc, _ = _make_svc(thread_data=[_OPEN_ROW])
    threads = await svc.get_open_threads()
    assert len(threads) == 1
    assert threads[0].status == "open"


async def test_get_open_threads_empty_when_none():
    svc, _ = _make_svc(thread_data=[])
    threads = await svc.get_open_threads()
    assert threads == []


# ── get_overdue_threads ───────────────────────────────────────────────────────

async def test_get_overdue_returns_old_threads():
    old_time = (NOW - timedelta(minutes=20)).isoformat()
    old_row = {**_OPEN_ROW, "opened_at": old_time}
    svc, _ = _make_svc(thread_data=[old_row])
    threads = await svc.get_overdue_threads(15)
    assert len(threads) == 1


async def test_get_overdue_returns_empty_when_none():
    svc, _ = _make_svc(thread_data=[])
    threads = await svc.get_overdue_threads(15)
    assert threads == []


# ── resolve ───────────────────────────────────────────────────────────────────

async def test_resolve_awards_xp_to_helper():
    svc, xp_svc = _make_svc(thread_data=[_RESOLVED_ROW])
    thread = await svc.resolve(THREAD_ID, HELPER_ID)
    xp_svc.award.assert_called_once_with(HELPER_ID, "helped_stuck", metadata={"thread_id": THREAD_ID})
    assert thread.status == "resolved"


async def test_resolve_not_found_raises():
    svc, _ = _make_svc(thread_data=[])
    with pytest.raises(ValueError, match="not found"):
        await svc.resolve("ghost-id", HELPER_ID)


# ── escalate ──────────────────────────────────────────────────────────────────

async def test_escalate_sets_escalated_status():
    svc, _ = _make_svc(thread_data=[_ESCALATED_ROW])
    thread = await svc.escalate(THREAD_ID)
    assert thread.status == "escalated"


async def test_escalate_not_found_raises():
    svc, _ = _make_svc(thread_data=[])
    with pytest.raises(ValueError, match="not found"):
        await svc.escalate("ghost-id")
