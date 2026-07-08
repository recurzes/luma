"""Tests for services/enrollment_service.py — Supabase client is mocked."""
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
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.services.enrollment_service import EnrollmentService

MEMBER_ID = uuid4()
ENROLLMENT_ID = uuid4()
GUILD_ID = "999"
NOW = datetime.now(tz=timezone.utc)

ENROLLMENT_ROW = {
    "id": str(ENROLLMENT_ID),
    "member_id": str(MEMBER_ID),
    "guild_id": GUILD_ID,
    "guild_name": "Test Guild",
    "signed_out_at": None,
    "created_at": NOW.isoformat(),
}

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
    result = MagicMock()
    result.data = rows or []

    chain = MagicMock()
    chain.execute.return_value = result
    chain.select.return_value = chain
    chain.insert.return_value = chain
    chain.update.return_value = chain
    chain.eq.return_value = chain
    chain.is_.return_value = chain
    chain.limit.return_value = chain

    db = MagicMock()
    db.table.return_value = chain
    return db, chain, result


@pytest.mark.asyncio
async def test_enroll_creates_new():
    db, chain, result = _mock_db()
    result.data = []
    results = [MagicMock(data=[]), MagicMock(data=[ENROLLMENT_ROW])]
    call_count = 0

    def side_effect():
        nonlocal call_count
        r = results[call_count] if call_count < len(results) else MagicMock(data=[])
        call_count += 1
        return r

    chain.execute.side_effect = side_effect

    service = EnrollmentService(db)
    enrollment = await service.enroll(MEMBER_ID, GUILD_ID, "Test Guild")

    assert enrollment.guild_id == GUILD_ID
    assert enrollment.signed_out_at is None


@pytest.mark.asyncio
async def test_enroll_reactivates_signed_out():
    signed_out = {**ENROLLMENT_ROW, "signed_out_at": NOW.isoformat()}
    reactivated = {**ENROLLMENT_ROW, "signed_out_at": None}
    db, chain, _ = _mock_db()
    results = [MagicMock(data=[signed_out]), MagicMock(data=[reactivated])]
    call_count = 0

    def side_effect():
        nonlocal call_count
        r = results[call_count]
        call_count += 1
        return r

    chain.execute.side_effect = side_effect

    service = EnrollmentService(db)
    enrollment = await service.enroll(MEMBER_ID, GUILD_ID, "Test Guild")

    assert enrollment.signed_out_at is None


@pytest.mark.asyncio
async def test_sign_out_sets_timestamp():
    db, chain, _ = _mock_db()
    signed = {**ENROLLMENT_ROW, "signed_out_at": NOW.isoformat()}
    results = [MagicMock(data=[ENROLLMENT_ROW]), MagicMock(data=[signed])]
    call_count = 0

    def side_effect():
        nonlocal call_count
        r = results[call_count]
        call_count += 1
        return r

    chain.execute.side_effect = side_effect

    service = EnrollmentService(db)
    enrollment = await service.sign_out(MEMBER_ID, GUILD_ID)

    assert enrollment.signed_out_at is not None


@pytest.mark.asyncio
async def test_is_active_true():
    db, chain, _ = _mock_db(rows=[ENROLLMENT_ROW])
    service = EnrollmentService(db)
    assert await service.is_active(MEMBER_ID, GUILD_ID) is True


@pytest.mark.asyncio
async def test_is_active_false_when_signed_out():
    signed_out = {**ENROLLMENT_ROW, "signed_out_at": NOW.isoformat()}
    db, chain, _ = _mock_db(rows=[signed_out])
    service = EnrollmentService(db)
    assert await service.is_active(MEMBER_ID, GUILD_ID) is False


@pytest.mark.asyncio
async def test_get_dm_targets_returns_members():
    db, chain, _ = _mock_db(
        rows=[{"bot_members": MEMBER_ROW}]
    )
    service = EnrollmentService(db)
    members = await service.get_dm_targets(GUILD_ID)

    assert len(members) == 1
    assert members[0].discord_id == "123456789"


@pytest.mark.asyncio
async def test_get_feature_targets_filters_by_notification():
    db, chain, _ = _mock_db(rows=[{"bot_members": MEMBER_ROW}])
    service = EnrollmentService(db)
    notification_svc = MagicMock()
    notification_svc.is_enabled = AsyncMock(return_value=True)

    members = await service.get_feature_targets(GUILD_ID, "standup", notification_svc)

    assert len(members) == 1
    notification_svc.is_enabled.assert_called_once()


@pytest.mark.asyncio
async def test_get_feature_targets_excludes_disabled():
    db, chain, _ = _mock_db(rows=[{"bot_members": MEMBER_ROW}])
    service = EnrollmentService(db)
    notification_svc = MagicMock()
    notification_svc.is_enabled = AsyncMock(return_value=False)

    members = await service.get_feature_targets(GUILD_ID, "standup", notification_svc)

    assert members == []
