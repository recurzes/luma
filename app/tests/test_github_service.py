"""Tests for GitHubService — no live Supabase or Discord needed."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")
for _i, _ch in enumerate(
    [
        "CHANNEL_TASK_FEED", "CHANNEL_STANDUP_LOG", "CHANNEL_GITHUB_FEED",
        "CHANNEL_CODE_REVIEW", "CHANNEL_PHASE_TRACKER", "CHANNEL_HELP",
        "CHANNEL_SHOUTOUTS", "CHANNEL_ANNOUNCEMENTS", "CHANNEL_TIP_OF_THE_DAY",
        "CHANNEL_RESOURCES", "CHANNEL_RETRO", "CHANNEL_RANKINGS", "CHANNEL_GENERAL",
    ],
    1,
):
    os.environ.setdefault(_ch, str(_i))

import pytest

from app.models.member import Member
from app.services.github_service import GitHubService


def _member() -> Member:
    return Member.model_validate({
        "id": str(uuid4()),
        "discord_id": "111",
        "discord_name": "Dev",
        "github_username": "devuser",
        "role": "beginner",
        "tier_max": "T1",
        "created_at": "2026-01-01T00:00:00+00:00",
    })


def _make_svc() -> GitHubService:
    db = MagicMock()
    members = MagicMock()
    xp = MagicMock()
    streak = MagicMock()
    return GitHubService(db=db, members=members, xp=xp, streak=streak, bot=None)


@pytest.mark.asyncio
async def test_process_pull_request_merged_calls_handle_pr_merged_with_correct_args():
    svc = _make_svc()
    author = _member()
    event_row = {"event_type": "pull_request", "actor": "devuser", "payload": {}}
    pr = {
        "number": 42,
        "title": "Fix bug",
        "html_url": "https://github.com/org/repo/pull/42",
        "body": "ticket:abcd1234",
        "merged": True,
        "user": {"login": "devuser"},
        "head": {"repo": {"full_name": "org/repo"}},
    }
    event_row["payload"] = {
        "action": "closed",
        "pull_request": pr,
    }

    with patch.object(svc, "get_member_by_github", AsyncMock(return_value=author)):
        with patch.object(svc, "_delete_pr_reviewer_ro", AsyncMock()):
            with patch.object(svc, "_handle_pr_merged", AsyncMock()) as merged_mock:
                await svc.process_pull_request(event_row)

    merged_mock.assert_awaited_once_with(event_row, pr, author, "ticket:abcd1234")


def test_count_any_violations_counts_added_typescript_lines_only():
    from app.services.github_service import _count_any_violations

    files = [
        {"filename": "src/a.ts", "patch": "+const x: any = 1\n-const y: any = 2\n+// any in a comment\n+let z: any, w: any"},
        {"filename": "src/b.py", "patch": "+any(x)"},
        {"filename": "src/c.tsx", "patch": "+const company = 1"},
    ]
    assert _count_any_violations(files) == {"src/a.ts": 3}


async def test_fetch_pr_files_is_none_without_token(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "GITHUB_TOKEN", "")
    assert await _make_svc()._fetch_pr_files("org/repo", 1) is None


def test_pair_channels_are_recognised_by_their_markers():
    import discord
    from app.cogs.stuck import _is_pair_channel

    def _text(name, topic):
        ch = MagicMock(spec=discord.TextChannel)
        ch.name, ch.topic = name, topic
        return ch

    def _voice(name):
        ch = MagicMock(spec=discord.VoiceChannel)
        ch.name = name
        return ch

    assert _is_pair_channel(_text("pair-auth-bug", "Pair session: auth bug"))
    assert not _is_pair_channel(_text("pair-programming-tips", None))
    assert not _is_pair_channel(_text("general", "Pair session: nope"))
    assert _is_pair_channel(_voice("🎤 pair-auth bug"))
    assert not _is_pair_channel(_voice("General"))
