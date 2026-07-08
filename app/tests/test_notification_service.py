"""Tests for services/notification_service.py — Supabase client is mocked."""
from __future__ import annotations

import os

os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("CHANNEL_TASK_FEED", "1")
os.environ.setdefault("CHANNEL_STANDUP_LOG", "2")
os.environ.setdefault("CHANNEL_GITHUB_FEED", "3")
os.environ.setdefault("CHANNEL_CODE_REVIEW", "4")
os.environ.setdefault("CHANNEL_PHASE_TRACKER", "5")
os.environ.setdefault("CHANNEL_HELP", "6")
os.environ.setdefault("CHANNEL_SHOUTOUTS", "7")
os.environ.setdefault("CHANNEL_ANNOUNCEMENTS", "8")
os.environ.setdefault("CHANNEL_TIP_OF_THE_DAY", "9")
os.environ.setdefault("CHANNEL_RESOURCES", "10")
os.environ.setdefault("CHANNEL_RETRO", "11")
os.environ.setdefault("CHANNEL_RANKINGS", "12")
os.environ.setdefault("CHANNEL_GENERAL", "13")

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.services.notification_service import NotificationService

MEMBER_ID = uuid4()
PREF_ID = uuid4()
GUILD_ID = "999"
NOW = datetime.now(tz=timezone.utc)

PREF_ROW = {
    "id": str(PREF_ID),
    "member_id": str(MEMBER_ID),
    "guild_id": GUILD_ID,
    "feature": "standup",
    "enabled": False,
    "updated_at": NOW.isoformat(),
}


def _mock_db(rows: list[dict] | None = None):
    result = MagicMock()
    result.data = rows or []

    chain = MagicMock()
    chain.execute.return_value = result
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain

    db = MagicMock()
    db.table.return_value = chain
    return db, chain, result


@pytest.mark.asyncio
async def test_is_enabled_default_false():
    db, chain, _ = _mock_db(rows=[])
    service = NotificationService(db)
    assert await service.is_enabled(MEMBER_ID, GUILD_ID, "standup") is False


@pytest.mark.asyncio
async def test_is_enabled_respects_stored_false():
    db, chain, _ = _mock_db(rows=[PREF_ROW])
    service = NotificationService(db)
    assert await service.is_enabled(MEMBER_ID, GUILD_ID, "standup") is False


@pytest.mark.asyncio
async def test_is_enabled_invalid_feature_raises():
    db, _, _ = _mock_db()
    service = NotificationService(db)
    with pytest.raises(ValueError, match="Unknown notification feature"):
        await service.is_enabled(MEMBER_ID, GUILD_ID, "invalid")


@pytest.mark.asyncio
async def test_set_enabled_creates_preference():
    db, chain, _ = _mock_db()
    results = [MagicMock(data=[]), MagicMock(data=[PREF_ROW])]
    call_count = 0

    def side_effect():
        nonlocal call_count
        r = results[call_count]
        call_count += 1
        return r

    chain.execute.side_effect = side_effect

    service = NotificationService(db)
    pref = await service.set_enabled(MEMBER_ID, GUILD_ID, "standup", False)

    assert pref.enabled is False


@pytest.mark.asyncio
async def test_list_preferences_defaults_all_disabled():
    db, chain, _ = _mock_db(rows=[])
    service = NotificationService(db)
    prefs = await service.list_preferences(MEMBER_ID, GUILD_ID)

    assert prefs["standup"] is False
    assert prefs["mood"] is False
    assert len(prefs) == 7


@pytest.mark.asyncio
async def test_list_preferences_merges_stored():
    db, chain, _ = _mock_db(rows=[PREF_ROW])
    service = NotificationService(db)
    prefs = await service.list_preferences(MEMBER_ID, GUILD_ID)

    assert prefs["standup"] is False
    assert prefs["journal"] is False
