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


# ── Event queue ───────────────────────────────────────────────────────────────

async def test_process_pending_marks_success_and_keeps_failures_queued():
    svc = _make_svc()
    events = [
        {"id": "ok", "event_type": "push", "attempts": 0},
        {"id": "bad", "event_type": "push", "attempts": 1},
        {"id": "unknown", "event_type": "star", "attempts": 0},
    ]

    async def _push(event_row):
        if event_row["id"] == "bad":
            raise RuntimeError("discord down")

    marks: dict[str, dict] = {}

    async def _mark(event_id, fields):
        marks[event_id] = fields

    with patch.object(svc, "fetch_pending_events", AsyncMock(return_value=events)), \
            patch.object(svc, "process_push", _push), \
            patch.object(svc, "_mark_event", _mark):
        processed, failed = await svc.process_pending()

    assert (processed, failed) == (2, 1)
    assert "processed_at" in marks["ok"] and "processed_at" in marks["unknown"]
    assert marks["bad"] == {"attempts": 2, "last_error": "discord down"}


async def test_push_awards_each_commit_once_per_event():
    svc = _make_svc()
    svc._xp.award = AsyncMock()
    svc._streak.record_activity = AsyncMock()
    event_row = {
        "id": "evt-1", "event_type": "push", "actor": "devuser",
        "payload": {"pusher": {"name": "devuser"}, "ref": "refs/heads/main",
                    "commits": [{"id": "sha1", "message": "one"}, {"id": "sha2", "message": "two"}]},
    }

    with patch.object(svc, "get_member_by_github", AsyncMock(return_value=_member())), \
            patch("app.services.github_service.get_current_streak", AsyncMock(return_value=0)), \
            patch("app.services.github_service.BadgeService") as badge_cls, \
            patch.object(svc, "_post_to_channel", AsyncMock()):
        badge_cls.return_value.check_and_award = AsyncMock(return_value=[])
        await svc.process_push(event_row)

    keys = [call.kwargs["dedupe_key"] for call in svc._xp.award.await_args_list]
    assert keys == ["evt-1:sha1", "evt-1:sha2"]
