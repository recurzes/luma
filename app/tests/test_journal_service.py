"""Tests for JournalService — no live Supabase needed."""
from __future__ import annotations

import os
os.environ.setdefault("DISCORD_TOKEN", "test")
os.environ.setdefault("DISCORD_GUILD_ID", "1")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-secret")

import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.journal_service import JournalService
from app.utils.db import run_query

MEMBER_ID = uuid4()
PROJECT_ID = uuid4()
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
SPRINT_START = NOW - timedelta(days=14)


def _entry(entry_type="freeform", mood=None, tags=None) -> dict:
    return {
        "id": str(uuid4()), "member_id": str(MEMBER_ID), "project_id": str(PROJECT_ID),
        "entry_type": entry_type, "content": "did things", "mood": mood, "tags": tags or [],
        "created_at": (NOW - timedelta(days=1)).isoformat(),
    }


def _adr(entry_id: str, sequence: int, title: str) -> dict:
    return {
        "id": str(uuid4()), "entry_id": entry_id, "project_id": str(PROJECT_ID), "sequence": sequence,
        "title": title, "context": "c", "decision": "d", "alternatives": None,
        "status": "proposed", "superseded_by": None,
    }


def _make_svc(entries: list[dict], adrs: list[dict]):
    calls: dict[str, MagicMock] = {}

    def _table(name):
        chain = MagicMock()
        for m in ["select", "eq", "gte", "lte", "order"]:
            getattr(chain, m).return_value = chain
        chain.execute.return_value = MagicMock(data=entries if "entries" in name else adrs)
        calls[name] = chain
        return chain

    db = MagicMock()
    db.table.side_effect = _table
    return JournalService(db, xp_svc=MagicMock()), calls


async def test_run_query_executes_off_the_event_loop():
    query = MagicMock()
    query.execute.side_effect = threading.get_ident
    assert await run_query(query) != threading.get_ident()


async def test_sprint_summary_covers_entries_moods_tags_and_own_adrs():
    adr_entry = _entry(entry_type="adr", tags=["#adr"])
    entries = [_entry(mood=4, tags=["#backend"]), _entry(mood=2, tags=["#backend", "#bug"]), adr_entry]
    adrs = [_adr(adr_entry["id"], 1, "Use Postgres"), _adr(str(uuid4()), 2, "Someone else's decision")]
    svc, calls = _make_svc(entries, adrs)

    summary = await svc.synthesize_sprint(MEMBER_ID, PROJECT_ID, SPRINT_START, NOW)

    assert "3 entries" in summary and "Mood avg: 3.0/5" in summary
    assert "#backend (2)" in summary
    assert "Use Postgres" in summary and "Someone else's decision" not in summary

    entries_query = calls["companion_journal_entries"]
    entries_query.gte.assert_called_once_with("created_at", SPRINT_START.isoformat())
    entries_query.lte.assert_called_once_with("created_at", NOW.isoformat())


async def test_sprint_summary_with_no_entries():
    svc, _ = _make_svc([], [])
    assert await svc.synthesize_sprint(MEMBER_ID, PROJECT_ID, SPRINT_START, NOW) == "No journal entries this sprint"
