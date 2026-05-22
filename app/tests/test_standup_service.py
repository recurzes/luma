"""Tests for StandupService — no live Supabase needed."""
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

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.services.member_service import MemberService
from app.services.standup_service import StandupService
from app.services.xp_service import XPService

SESSION_ID = str(uuid4())
MEMBER_ID = str(uuid4())
TODAY = date.today().isoformat()
NOW = datetime.now(timezone.utc).isoformat()

SESSION_ROW = {"id": SESSION_ID, "date": TODAY, "posted_at": None, "created_at": NOW}
RESPONSE_ROW = {
    "id": str(uuid4()), "session_id": SESSION_ID, "member_id": MEMBER_ID,
    "yesterday": "worked on auth", "today": "write tests", "blockers": "none",
    "responded_at": NOW,
}


def _chain(data=None):
    c = MagicMock()
    r = MagicMock()
    r.data = data or []
    c.execute.return_value = r
    for m in ["select", "insert", "update", "upsert", "eq", "order", "limit"]:
        getattr(c, m).return_value = c
    return c


def _make_svc(session_exists=True):
    db = MagicMock()
    members_svc = MagicMock(spec=MemberService)
    xp_svc = MagicMock(spec=XPService)
    xp_svc.award = AsyncMock(return_value=MagicMock(xp_awarded=5))

    select_chain = _chain(data=[SESSION_ROW] if session_exists else [])
    insert_chain = _chain(data=[SESSION_ROW])  # insert always returns the row
    response_chain = _chain(data=[RESPONSE_ROW])
    update_chain = _chain()

    def _table(name):
        if "session" in name:
            # Return a chain where select → empty/exists and insert → row
            c = MagicMock()
            c.select.return_value = select_chain
            c.insert.return_value = insert_chain
            c.update.return_value = update_chain
            for m in ["eq", "order", "limit"]:
                getattr(c, m).return_value = c
            select_chain.eq.return_value = select_chain
            select_chain.limit.return_value = select_chain
            return c
        if "response" in name:
            return response_chain
        return _chain()

    db.table.side_effect = _table
    return StandupService(db, members_svc, xp_svc), members_svc, xp_svc


# ── get_or_create_today ───────────────────────────────────────────────────────

async def test_get_or_create_returns_existing_session():
    svc, _, _ = _make_svc(session_exists=True)
    session = await svc.get_or_create_today()
    assert str(session.id) == SESSION_ID


async def test_get_or_create_creates_when_missing():
    svc, _, _ = _make_svc(session_exists=False)
    session = await svc.get_or_create_today()
    assert session is not None


# ── save_response ─────────────────────────────────────────────────────────────

async def test_save_response_returns_response():
    svc, _, xp_svc = _make_svc()
    response = await svc.save_response(SESSION_ID, MEMBER_ID, "old work", "new work", "none")
    assert response.session_id.hex.replace("-", "") in RESPONSE_ROW["session_id"].replace("-", "")


async def test_save_response_awards_xp():
    svc, _, xp_svc = _make_svc()
    await svc.save_response(SESSION_ID, MEMBER_ID, "yesterday", "today", "blockers")
    xp_svc.award.assert_called_once_with(MEMBER_ID, "standup")


# ── non_responders ────────────────────────────────────────────────────────────

async def test_non_responders_excludes_responders():
    svc, members_svc, _ = _make_svc()

    responder = MagicMock()
    responder.id = uuid4()
    non_responder = MagicMock()
    non_responder.id = uuid4()

    # RESPONSE_ROW has MEMBER_ID — patch response to match responder
    from unittest.mock import patch
    import uuid

    async def _fake_get_all():
        return [responder, non_responder]

    members_svc.get_all_active = _fake_get_all

    # Override get_responses to return a response for `responder.id`
    with patch.object(svc, "get_responses", new=AsyncMock(return_value=[])):
        non = await svc.non_responders(SESSION_ID)
        # Both should be non-responders since no responses
        assert len(non) == 2
