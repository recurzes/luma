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

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.ticket import TicketCreate, TierViolationError
from app.services.ticket_service import TicketService


MEMBER_ID = uuid4()
TICKET_ID = uuid4()
NOW = datetime.now(tz=timezone.utc)

BEGINNER_ROW = {
    "id": str(MEMBER_ID),
    "discord_id": "111",
    "discord_name": "BeginnerDev",
    "github_username": None,
    "role": "beginner",
    "tier_max": "T1",
    "created_at": NOW.isoformat(),
}

LEAD_ROW = {
    "id": str(uuid4()),
    "discord_id": "222",
    "discord_name": "LeadDev",
    "github_username": None,
    "role": "lead",
    "tier_max": "T3",
    "created_at": NOW.isoformat(),
}

TICKET_ROW = {
    "id": str(TICKET_ID),
    "title": "Test Ticket",
    "description": "Some desc",
    "tier": "T1",
    "status": "todo",
    "priority": "medium",
    "phase": None,
    "assignee_id": None,
    "reviewer_id": None,
    "created_by": None,
    "deadline": None,
    "closed_at": None,
    "github_pr": None,
    "discord_msg_id": None,
    "created_at": NOW.isoformat(),
    "updated_at": NOW.isoformat(),
}


def _mock_db(ticket_rows=None, member_rows=None, stats_rows=None, t2_count=0):
    def _chain(rows):
        result = MagicMock()
        result.data = rows
        result.count = len(rows)
        c = MagicMock()
        c.execute.return_value = result
        c.select.return_value = c
        c.insert.return_value = c
        c.update.return_value = c
        c.eq.return_value = c
        c.neq.return_value = c
        c.ilike.return_value = c
        c.filter.return_value = c
        c.limit.return_value = c
        c.order.return_value = c
        return c, result

    ticket_chain, ticket_result = _chain(ticket_rows if ticket_rows is not None else [TICKET_ROW])
    member_chain, member_result = _chain(member_rows if member_rows is not None else [BEGINNER_ROW])
    stats_chain, stats_result = _chain(stats_rows if stats_rows is not None else [{"tickets_closed": 0}])

    def _table(name):
        if name == "bot_tickets":
            return ticket_chain
        if name == "bot_members":
            return member_chain
        if name == "bot_member_stats":
            return stats_chain
        return MagicMock()

    db = MagicMock()
    db.table.side_effect = _table
    return db


def _make_service(db, member_rows=None):
    from app.services.member_service import MemberService
    member_svc = MemberService(db)
    return TicketService(db, member_svc)


@pytest.mark.asyncio
async def test_create_ticket():
    db = _mock_db(ticket_rows=[TICKET_ROW])
    service = _make_service(db)

    ticket = await service.create(
        TicketCreate(title="Test Ticket", tier="T1"),
        created_by_discord_id="111",
    )

    assert ticket.title == "Test Ticket"
    assert ticket.tier == "T1"
    assert ticket.status == "todo"


@pytest.mark.asyncio
async def test_assign_t3_to_beginner_raises_tier_violation():
    t3_ticket_row = {**TICKET_ROW, "tier": "T3", "id": str(uuid4())}
    db = _mock_db(ticket_rows=[t3_ticket_row], member_rows=[BEGINNER_ROW])
    service = _make_service(db)

    with pytest.raises(TierViolationError) as exc_info:
        await service.assign(str(t3_ticket_row["id"]), "111")

    assert exc_info.value.requested_tier == "T3"
    assert exc_info.value.max_tier == "T1"
    assert "BeginnerDev" in exc_info.value.assignee_name


@pytest.mark.asyncio
async def test_assign_t2_to_beginner_with_t1_max_raises():
    t2_ticket_row = {**TICKET_ROW, "tier": "T2", "id": str(uuid4())}
    db = _mock_db(ticket_rows=[t2_ticket_row], member_rows=[BEGINNER_ROW])
    service = _make_service(db)

    with pytest.raises(TierViolationError) as exc_info:
        await service.assign(str(t2_ticket_row["id"]), "111")

    assert exc_info.value.requested_tier == "T2"


@pytest.mark.asyncio
async def test_assign_t2_beginner_with_t2_max_first_time_returns_first_t2():
    beginner_t2 = {**BEGINNER_ROW, "tier_max": "T2"}
    t2_ticket_row = {
        **TICKET_ROW,
        "tier": "T2",
        "id": str(uuid4()),
        "assignee_id": str(MEMBER_ID),
        "status": "in_progress",
    }

    call_counts: dict[str, int] = {"member": 0, "ticket": 0, "stats": 0}

    def _table(name):
        chain = MagicMock()

        if name == "bot_members":
            result = MagicMock()
            result.data = [beginner_t2]
            result.count = 1
        elif name == "bot_tickets":
            call_counts["ticket"] += 1
            result = MagicMock()
            if call_counts["ticket"] == 2:
                result.data = []
                result.count = 0
            else:
                result.data = [t2_ticket_row]
                result.count = 1
        else:
            result = MagicMock()
            result.data = []
            result.count = 0

        chain.execute.return_value = result
        chain.select.return_value = chain
        chain.insert.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.neq.return_value = chain
        chain.ilike.return_value = chain
        chain.filter.return_value = chain
        chain.limit.return_value = chain
        chain.order.return_value = chain
        return chain

    db = MagicMock()
    db.table.side_effect = _table
    service = _make_service(db)

    result = await service.assign(str(t2_ticket_row["id"]), "111")
    assert result.first_t2 is True
    assert result.ticket.tier == "T2"


@pytest.mark.asyncio
async def test_assign_t1_to_lead_always_ok():
    t1_row = {**TICKET_ROW, "assignee_id": str(uuid4()), "status": "in_progress"}
    db = _mock_db(ticket_rows=[t1_row], member_rows=[LEAD_ROW])
    service = _make_service(db)

    result = await service.assign(str(TICKET_ID), "222")
    assert result.first_t2 is False


@pytest.mark.asyncio
async def test_status_todo_to_in_progress():
    in_progress_row = {**TICKET_ROW, "status": "in_progress"}
    db = _mock_db(ticket_rows=[in_progress_row])
    service = _make_service(db)

    updated = await service.update_status(str(TICKET_ID), "in_progress", "111")
    assert updated.status == "in_progress"


@pytest.mark.asyncio
async def test_status_in_progress_to_in_review():
    in_review_row = {**TICKET_ROW, "status": "in_review"}
    db = _mock_db(ticket_rows=[in_review_row])
    service = _make_service(db)

    updated = await service.update_status(str(TICKET_ID), "in_review", "111")
    assert updated.status == "in_review"


@pytest.mark.asyncio
async def test_close_sets_closed_at_and_increments_stats():
    closed_row = {**TICKET_ROW, "status": "done", "closed_at": NOW.isoformat()}
    db = _mock_db(ticket_rows=[closed_row])
    service = _make_service(db)

    result = await service.close(str(TICKET_ID), "111")

    assert result.ticket.status == "done"
    assert result.ticket.closed_at is not None


@pytest.mark.asyncio
async def test_get_by_short_id_suffix():
    short_id = str(TICKET_ID).replace("-", "")[-8:]
    db = _mock_db(ticket_rows=[TICKET_ROW])
    service = _make_service(db)

    ticket = await service.get(short_id)
    assert ticket is not None
    assert ticket.id == TICKET_ID

    assert db.table.call_args_list[0].args[0] == "bot_tickets"
    chain = db.table("bot_tickets")
    chain.ilike.assert_called_once_with("id_text", f"%{short_id}")


@pytest.mark.asyncio
async def test_close_nonexistent_ticket_raises():
    db = _mock_db(ticket_rows=[])
    service = _make_service(db)

    with pytest.raises(ValueError, match="not found"):
        await service.close("nonexistent", "111")


@pytest.mark.asyncio
async def test_invalid_status_raises():
    db = _mock_db()
    service = _make_service(db)

    with pytest.raises(ValueError, match="Invalid status"):
        await service.update_status(str(TICKET_ID), "flying", "111")
