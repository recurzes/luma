"""Each Discord server has its own data: tests against a small in-memory Supabase fake."""
from __future__ import annotations

import os
os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")

from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.cogs import monitoring, standup
from app.cogs.monitoring import MonitoringCog
from app.cogs.standup import StandupCog
from app.models.ticket import TicketCreate
from app.services.github_service import UNLINKED_REPO, GitHubService
from app.services.member_service import MemberService
from app.services.phase_service import PhaseService
from app.services.ticket_service import TicketService
from app.utils.github_repo import normalize_repo

GUILD_A = "111111111111111111"
GUILD_B = "222222222222222222"
NOW = datetime.now(timezone.utc).isoformat()

_DEFAULTS = {
    "bot_members": {"github_username": None},
    "bot_tickets": {
        "description": None, "phase": None, "assignee_id": None, "reviewer_id": None,
        "created_by": None, "deadline": None, "closed_at": None, "github_pr": None,
        "discord_msg_id": None, "project_id": None,
    },
    "bot_phases": {"description": None, "started_at": None, "completed_at": None},
    "bot_phase_criteria": {"checked": False, "checked_by": None, "checked_at": None},
}


class _Query:
    def __init__(self, db: "FakeDB", table: str):
        self._db, self._table = db, table
        self._filters: list = []
        self._op, self._payload, self._limit = "select", None, None

    # writes
    def insert(self, row): self._op, self._payload = "insert", row; return self
    def update(self, row): self._op, self._payload = "update", row; return self

    # filters
    def select(self, *_, **__): return self
    def order(self, *_, **__): return self
    def limit(self, n): self._limit = n; return self
    def eq(self, col, val): self._filters.append(lambda r: r.get(col) == val); return self
    def neq(self, col, val): self._filters.append(lambda r: r.get(col) != val); return self
    def lt(self, col, val): self._filters.append(lambda r: r.get(col) is not None and r[col] < val); return self

    def is_(self, col, val):
        assert val == "null"
        self._filters.append(lambda r: r.get(col) is None)
        return self

    def ilike(self, col, pattern):
        needle = pattern.lower().replace("\\", "")
        if needle.startswith("%"):
            self._filters.append(lambda r: str(r.get(col) or r.get("id")).lower().endswith(needle[1:]))
        else:
            self._filters.append(lambda r: str(r.get(col) or "").lower() == needle)
        return self

    @property
    def not_(self):
        outer = self

        class _Not:
            def is_(self, col, val):
                outer._filters.append(lambda r: r.get(col) is not None)
                return outer

        return _Not()

    def execute(self):
        rows = self._db.rows.setdefault(self._table, [])
        if self._op == "insert":
            row = {"id": str(uuid4()), "created_at": NOW, "updated_at": NOW,
                   **_DEFAULTS.get(self._table, {}), **self._payload}
            rows.append(row)
            return MagicMock(data=[row], count=1)

        matched = [r for r in rows if all(f(r) for f in self._filters)]
        if self._op == "update":
            for r in matched:
                r.update(self._payload)
        if self._limit is not None:
            matched = matched[:self._limit]
        return MagicMock(data=matched, count=len(matched))


class FakeDB:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {}

    def table(self, name: str) -> _Query:
        return _Query(self, name)


# ── Members ───────────────────────────────────────────────────────────────────

async def test_same_discord_user_is_a_separate_member_in_each_server():
    members = MemberService(FakeDB())

    in_a = await members.register("42", GUILD_A, "Dev", "lead", "T3")
    in_b = await members.register("42", GUILD_B, "Dev", "beginner", "T1")

    assert in_a.id != in_b.id
    assert (await members.get_by_discord_id("42", GUILD_A)).role == "lead"
    assert (await members.get_by_discord_id("42", GUILD_B)).role == "beginner"
    assert [m.id for m in await members.get_all_active(GUILD_A)] == [in_a.id]
    assert len(await members.get_all()) == 2


async def test_registering_twice_in_one_server_is_rejected():
    members = MemberService(FakeDB())
    await members.register("42", GUILD_A, "Dev", "beginner", "T1")
    with pytest.raises(ValueError, match="already registered"):
        await members.register("42", GUILD_A, "Dev", "beginner", "T1")


# ── Tickets ───────────────────────────────────────────────────────────────────

async def test_tickets_are_invisible_from_another_server():
    db = FakeDB()
    members = MemberService(db)
    tickets_a = TicketService(db, members, GUILD_A)
    tickets_b = TicketService(db, members, GUILD_B)

    ticket = await tickets_a.create(TicketCreate(title="Fix login", tier="T1"), created_by_discord_id="42")
    short_id = str(ticket.id)[-8:]

    assert (await tickets_a.get(short_id)).id == ticket.id
    assert await tickets_b.get(short_id) is None
    assert await tickets_b.get(str(ticket.id)) is None
    assert [t.id for t in await tickets_a.get_all()] == [ticket.id]
    assert await tickets_b.get_all() == []
    with pytest.raises(ValueError, match="not found"):
        await tickets_b.close(short_id, "42")


# ── Phases ────────────────────────────────────────────────────────────────────

async def test_each_server_has_its_own_phases():
    db = FakeDB()
    phases_a, phases_b = PhaseService(db, GUILD_A), PhaseService(db, GUILD_B)

    assert await phases_b.get_current() is None

    first = await phases_a.create("phase-1", "Foundations")
    second = await phases_a.create("phase-2", "Build")
    assert (first.status, second.status) == ("active", "pending")
    with pytest.raises(ValueError, match="already exists"):
        await phases_a.create("phase-1", "Again")

    # The same key is free in another server, and A's phases do not leak into it.
    b_first = await phases_b.create("phase-1", "Kickoff")
    assert b_first.status == "active"
    assert [p.name for p in await phases_b.get_all()] == ["Kickoff"]
    assert (await phases_a.get_current()).name == "Foundations"

    await phases_a.complete_phase("phase-1", "lead")
    assert (await phases_a.get_current()).key == "phase-2"
    assert (await phases_b.get_current()).name == "Kickoff"


# ── GitHub routing ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, expected", [
    ("https://github.com/Acme/Web-App", "acme/web-app"),
    ("https://github.com/acme/web-app.git", "acme/web-app"),
    ("git@github.com:acme/web-app.git", "acme/web-app"),
    ("github.com/acme/web-app/", "acme/web-app"),
    ("acme/web-app", "acme/web-app"),
    ("https://gitlab.com/acme/web-app", None),
    ("not a repo", None),
    (None, None),
])
def test_normalize_repo(value, expected):
    assert normalize_repo(value) == expected


def _github(db: FakeDB) -> GitHubService:
    return GitHubService(db=db, members=MemberService(db), xp=MagicMock(), streak=MagicMock(), bot=None)


def _link(db: FakeDB, guild_id: str, url: str | None, status: str = "active") -> None:
    db.table("companion_projects").insert(
        {"discord_guild_id": guild_id, "github_repo_url": url, "status": status}
    ).execute()


async def test_event_is_routed_only_to_servers_that_linked_the_repo():
    db = FakeDB()
    _link(db, GUILD_A, "https://github.com/acme/web-app")
    _link(db, GUILD_B, "https://github.com/acme/other")
    _link(db, GUILD_B, None)
    _link(db, "333", "https://github.com/acme/web-app", status="archived")
    svc = _github(db)

    seen: list[dict] = []

    async def _push(event_row):
        seen.append(event_row)

    event = {"id": "evt", "event_type": "push", "payload": {"repository": {"full_name": "Acme/Web-App"}}}
    with patch.object(svc, "process_push", _push):
        routed = await svc.dispatch(event)

    assert routed == [GUILD_A]
    assert [(e["guild_id"], e["repo_full_name"]) for e in seen] == [(GUILD_A, "acme/web-app")]


async def test_event_from_unlinked_repo_is_closed_without_running_handlers():
    db = FakeDB()
    _link(db, GUILD_A, "https://github.com/acme/web-app")
    db.table("bot_github_events").insert({
        "event_type": "push", "actor": "dev", "attempts": 0, "processed_at": None, "received_at": NOW,
        "payload": {"repository": {"full_name": "stranger/repo"}},
    }).execute()
    svc = _github(db)

    with patch.object(svc, "process_push", AsyncMock()) as handler:
        processed, failed = await svc.process_pending()

    handler.assert_not_awaited()
    assert (processed, failed) == (1, 0)
    stored = db.rows["bot_github_events"][0]
    assert stored["processed_at"] is not None and stored["last_error"] == UNLINKED_REPO


async def test_github_username_resolves_to_the_member_of_that_server():
    db = FakeDB()
    members = MemberService(db)
    in_a = await members.register("42", GUILD_A, "Dev", "beginner", "T1")
    in_b = await members.register("42", GUILD_B, "Dev", "beginner", "T1")
    await members.update_github_username("42", GUILD_A, "DevUser")
    await members.update_github_username("42", GUILD_B, "DevUser")
    svc = _github(db)

    assert (await svc.get_member_by_github("devuser", GUILD_A)).id == in_a.id
    assert (await svc.get_member_by_github("devuser", GUILD_B)).id == in_b.id
    assert await svc.get_member_by_github("devuser", "999") is None


# ── DM flows ──────────────────────────────────────────────────────────────────

USER_ID = 42


def _dm(content: str) -> MagicMock:
    import discord

    message = MagicMock()
    message.guild = None
    message.author.bot = False
    message.author.id = USER_ID
    message.content = content
    message.channel = MagicMock(spec=discord.DMChannel)
    message.channel.send = AsyncMock()
    return message


def _standup_state(guild_id: str, guild_name: str) -> dict:
    return {
        "session_id": f"session-{guild_id}", "member_id": f"member-{guild_id}",
        "guild_id": guild_id, "guild_name": guild_name, "stage": 0,
        "yesterday": None, "today": None, "blockers": None,
    }


async def test_standups_for_two_servers_are_answered_one_after_the_other(monkeypatch):
    standup._PENDING[USER_ID] = deque([_standup_state("A", "Server A"), _standup_state("B", "Server B")])
    svc = MagicMock()
    svc.save_response = AsyncMock(return_value=(MagicMock(), []))
    cog = StandupCog(MagicMock())
    monkeypatch.setattr(cog, "_svc", lambda: svc)

    try:
        for answer in ("a1", "a2"):
            await cog.on_message(_dm(answer))
        last_of_a = _dm("a3")
        await cog.on_message(last_of_a)

        # Server B's first question arrives only once A is finished.
        assert "Server B" in last_of_a.channel.send.await_args_list[-1].args[0]
        assert standup.has_pending_standup(USER_ID)

        for answer in ("b1", "b2", "b3"):
            await cog.on_message(_dm(answer))
    finally:
        standup._PENDING.pop(USER_ID, None)

    saved = [(c.kwargs["session_id"], c.kwargs["member_id"], c.kwargs["yesterday"])
             for c in svc.save_response.await_args_list]
    assert saved == [("session-A", "member-A", "a1"), ("session-B", "member-B", "b1")]
    assert not standup.has_pending_standup(USER_ID)


async def test_mood_replies_are_recorded_per_server():
    monitoring._mood_prompts.clear()
    monitoring._mood_scores.clear()
    monitoring._mood_prompts.update({100: (1, USER_ID), 200: (2, USER_ID)})

    with patch("app.cogs.monitoring.database.get_db", return_value=MagicMock()):
        cog = MonitoringCog(MagicMock())

    try:
        await cog.on_message(_dm("4"))   # oldest prompt first: server 1
        await cog.on_message(_dm("2"))   # then server 2
        ignored = _dm("5")
        await cog.on_message(ignored)    # nothing pending any more
    finally:
        scores = {g: dict(s) for g, s in monitoring._mood_scores.items()}
        monitoring._mood_prompts.clear()
        monitoring._mood_scores.clear()

    assert scores == {1: {USER_ID: 4}, 2: {USER_ID: 2}}
    ignored.channel.send.assert_not_awaited()
