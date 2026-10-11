"""Tests for TrackService — no live Supabase needed."""
from __future__ import annotations

import os
os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.services.track_service import TrackService
from app.utils.db import row_or_none

MEMBER_ID = uuid4()
TRACK_ID = uuid4()
OTHER_TRACK_ID = uuid4()


def _checkpoint(cp_id: str, track_id: UUID = TRACK_ID, sequence: int = 1, xp_value: int = 10) -> dict:
    return {
        "id": cp_id, "track_id": str(track_id), "sequence": sequence, "title": f"cp {sequence}",
        "resource_url": None, "exercise": None, "knowledge_check": None, "answer_hash": None,
        "xp_value": xp_value, "created_at": None,
    }


CP_1 = _checkpoint("aaaaaaaa-0000-4000-8000-000000000001")
CP_2 = _checkpoint("bbbbbbbb-0000-4000-8000-000000000002", sequence=2)

PROGRESS_ROW = {
    "id": str(uuid4()), "member_id": str(MEMBER_ID), "track_id": str(TRACK_ID),
    "enrolled_at": None, "completed_at": None, "checkpoints_done": 0,
}


class _Query:
    """Records filters and resolves rows through a per-table callback."""

    def __init__(self, table: str, resolve):
        self.table, self._resolve = table, resolve
        self.filters: dict = {}
        self.single = False
        self.op = "select"

    def select(self, *_, **__): return self
    def order(self, *_, **__): return self
    def limit(self, *_): return self

    def insert(self, _row): self.op = "insert"; return self
    def update(self, _row): self.op = "update"; return self

    def eq(self, col, val): self.filters[col] = val; return self
    def in_(self, col, vals): self.filters[col] = list(vals); return self

    def maybe_single(self): self.single = True; return self

    def execute(self):
        rows = self._resolve(self) if self.op == "select" else []
        if self.single:
            # Mirrors postgrest: zero rows from maybe_single() is None, not an empty response.
            return MagicMock(data=rows[0]) if rows else None
        return MagicMock(data=rows, count=len(rows))


def _make_svc(resolve):
    db = MagicMock()
    db.table.side_effect = lambda name: _Query(name, resolve)
    xp = MagicMock()
    xp.award = AsyncMock(side_effect=lambda _m, _a, _meta=None, xp_override=None: MagicMock(
        xp_awarded=xp_override if xp_override is not None else 15
    ))
    badges = MagicMock()
    badges.check_and_award = AsyncMock(return_value=[])
    return TrackService(db, xp_svc=xp, badge_svc=badges), xp


def test_row_or_none_handles_missing_response():
    assert row_or_none(None) is None
    assert row_or_none(MagicMock(data={"id": 1})) == {"id": 1}


async def test_get_progress_returns_none_when_not_enrolled():
    svc, _ = _make_svc(lambda q: [])
    assert await svc.get_progress(MEMBER_ID, TRACK_ID) is None


async def test_next_checkpoint_is_filtered_by_track():
    seen: list[dict] = []

    def resolve(q):
        if q.table == "companion_track_checkpoints":
            seen.append(q.filters)
            return [CP_1, CP_2]
        return []

    svc, _ = _make_svc(resolve)
    next_cp = await svc.get_next_checkpoint(MEMBER_ID, TRACK_ID)

    assert str(next_cp.id) == CP_1["id"]
    assert seen == [{"track_id": str(TRACK_ID)}]


async def test_find_checkpoint_by_short_id_matches_prefix_in_enrolled_tracks():
    def resolve(q):
        if q.table == "companion_member_track_progress":
            return [{"track_id": str(TRACK_ID)}]
        if q.table == "companion_track_checkpoints":
            assert q.filters == {"track_id": [str(TRACK_ID)]}
            return [CP_1, CP_2]
        return []

    svc, _ = _make_svc(resolve)

    found = await svc.find_checkpoint_by_short_id(MEMBER_ID, "BBBBBBBB")
    assert str(found.id) == CP_2["id"]
    assert await svc.find_checkpoint_by_short_id(MEMBER_ID, "cccccccc") is None


@pytest.mark.parametrize("bad_id", ["%", "aaaa", "aaaaaaa%"])
async def test_find_checkpoint_rejects_malformed_ids(bad_id):
    svc, _ = _make_svc(lambda q: pytest.fail("malformed ID should not query the database"))
    assert await svc.find_checkpoint_by_short_id(MEMBER_ID, bad_id) is None


async def test_complete_checkpoint_awards_the_checkpoints_own_xp():
    cp = _checkpoint(CP_1["id"], xp_value=30)

    def resolve(q):
        if q.table == "companion_track_checkpoints":
            return [cp, CP_2] if "id" not in q.filters else [cp]
        if q.table == "companion_member_track_progress":
            return [PROGRESS_ROW]
        return []  # no existing completion

    svc, xp = _make_svc(resolve)
    checkpoint, total_xp = await svc.complete_checkpoint(MEMBER_ID, UUID(cp["id"]))

    actions = [call.args[1] for call in xp.award.await_args_list]
    # 1 of 2 checkpoints = 50%, which crosses both the 25% and 50% milestones.
    assert actions == ["track_checkpoint", "track_25pct", "track_50pct"]
    assert xp.award.await_args_list[0].kwargs == {"xp_override": 30}
    assert total_xp == 30 + 15 + 15
    assert str(checkpoint.id) == cp["id"]
