"""Tests for services/member_service.py — Supabase client is mocked."""
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
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from app.services.member_service import MemberService

# ─── fixtures ─────────────────────────────────────────────────────────────────

MEMBER_ID = uuid4()
NOW = datetime.now(tz=timezone.utc)

MEMBER_ROW = {
    "id": str(MEMBER_ID),
    "discord_id": "123456789",
    "discord_name": "TestDev",
    "github_username": None,
    "role": "beginner",
    "tier_max": "T1",
    "created_at": NOW.isoformat(),
}


def _mock_db(rows: list[dict] | None = None):
    """Build a minimal Supabase client mock."""
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


# ─── tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_register_success():
    db, chain, result = _mock_db()
    # first call (exists check) returns empty, second call (insert) returns row
    result.data = []
    results = [MagicMock(data=[]), MagicMock(data=[MEMBER_ROW]), MagicMock(data=[])]
    call_count = 0

    def side_effect():
        nonlocal call_count
        r = results[call_count] if call_count < len(results) else MagicMock(data=[])
        call_count += 1
        return r

    chain.execute.side_effect = side_effect

    service = MemberService(db)
    member = await service.register("123456789", "TestDev", "beginner", "T1")

    assert member.discord_id == "123456789"
    assert member.role == "beginner"
    assert member.tier_max == "T1"


@pytest.mark.asyncio
async def test_register_duplicate_raises():
    db, chain, result = _mock_db(rows=[MEMBER_ROW])
    service = MemberService(db)

    with pytest.raises(ValueError, match="already registered"):
        await service.register("123456789", "TestDev", "beginner", "T1")


@pytest.mark.asyncio
async def test_get_by_discord_id_found():
    db, chain, _ = _mock_db(rows=[MEMBER_ROW])
    service = MemberService(db)

    member = await service.get_by_discord_id("123456789")
    assert member is not None
    assert member.discord_name == "TestDev"


@pytest.mark.asyncio
async def test_get_by_discord_id_not_found():
    db, chain, _ = _mock_db(rows=[])
    service = MemberService(db)

    member = await service.get_by_discord_id("nonexistent")
    assert member is None


@pytest.mark.asyncio
async def test_update_github_username():
    updated_row = {**MEMBER_ROW, "github_username": "testdev-gh"}
    db, chain, _ = _mock_db(rows=[updated_row])
    service = MemberService(db)

    member = await service.update_github_username("123456789", "testdev-gh")
    assert member.github_username == "testdev-gh"


@pytest.mark.asyncio
async def test_update_github_username_not_found_raises():
    db, chain, _ = _mock_db(rows=[])
    service = MemberService(db)

    with pytest.raises(ValueError, match="No member found"):
        await service.update_github_username("ghost", "some-gh")


@pytest.mark.asyncio
async def test_exists_true():
    db, chain, _ = _mock_db(rows=[MEMBER_ROW])
    service = MemberService(db)
    assert await service.exists("123456789") is True


@pytest.mark.asyncio
async def test_exists_false():
    db, chain, _ = _mock_db(rows=[])
    service = MemberService(db)
    assert await service.exists("ghost") is False


@pytest.mark.asyncio
async def test_register_invalid_role_raises():
    db, _, _ = _mock_db()
    service = MemberService(db)
    with pytest.raises(ValueError, match="Invalid role"):
        await service.register("1", "Dev", "wizard", "T1")


@pytest.mark.asyncio
async def test_register_invalid_tier_raises():
    db, _, _ = _mock_db()
    service = MemberService(db)
    with pytest.raises(ValueError, match="Invalid tier_max"):
        await service.register("1", "Dev", "beginner", "T9")
