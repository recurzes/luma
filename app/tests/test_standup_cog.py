"""Tests for the standup DM state machine — no live Discord or Supabase needed."""
from __future__ import annotations

import os
os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.cogs import standup
from app.cogs.standup import StandupCog, has_pending_standup

USER_ID = 42


def _dm(content: str) -> MagicMock:
    message = MagicMock()
    message.guild = None
    message.author.bot = False
    message.author.id = USER_ID
    message.content = content
    message.channel.send = AsyncMock()
    return message


def _state(guild_id: str, guild_name: str) -> dict:
    return {
        "session_id": f"session-{guild_id}",
        "member_id": f"member-{guild_id}",
        "guild_id": guild_id,
        "guild_name": guild_name,
        "stage": 0,
        "yesterday": None,
        "today": None,
        "blockers": None,
    }


@pytest.fixture
def pending():
    standup._PENDING[USER_ID] = deque([_state("1", "Server A")])
    yield standup._PENDING
    standup._PENDING.pop(USER_ID, None)


async def test_three_replies_complete_the_standup(pending, monkeypatch):
    svc = MagicMock()
    svc.save_response = AsyncMock(return_value=(MagicMock(), []))
    cog = StandupCog(MagicMock())
    monkeypatch.setattr(cog, "_svc", lambda: svc)

    assert has_pending_standup(USER_ID)

    first = _dm("shipped auth")
    await cog.on_message(first)
    first.channel.send.assert_awaited_once_with(standup._QUESTIONS[1])

    second = _dm("writing tests")
    await cog.on_message(second)
    second.channel.send.assert_awaited_once_with(standup._QUESTIONS[2])

    await cog.on_message(_dm("none"))

    svc.save_response.assert_awaited_once_with(
        session_id="session-1",
        member_id="member-1",
        yesterday="shipped auth",
        today="writing tests",
        blockers="none",
    )
    assert not has_pending_standup(USER_ID)


async def test_dm_without_pending_standup_is_ignored():
    cog = StandupCog(MagicMock())
    message = _dm("hello")
    await cog.on_message(message)
    message.channel.send.assert_not_awaited()
