-- Migration 001: All bot_* tables
-- Apply in dependency order — do not reorder.
-- All timestamps use TIMESTAMPTZ DEFAULT now().

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. bot_members
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    discord_id      TEXT UNIQUE NOT NULL,
    discord_name    TEXT NOT NULL,
    github_username TEXT,
    role            TEXT NOT NULL CHECK (role IN ('lead', 'professor', 'beginner')),
    tier_max        TEXT NOT NULL DEFAULT 'T1' CHECK (tier_max IN ('T1', 'T2', 'T3')),
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 2. bot_member_stats
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_member_stats (
    member_id       UUID PRIMARY KEY REFERENCES bot_members(id) ON DELETE CASCADE,
    total_xp        INT NOT NULL DEFAULT 0,
    level           INT NOT NULL DEFAULT 1,
    current_streak  INT NOT NULL DEFAULT 0,
    longest_streak  INT NOT NULL DEFAULT 0,
    last_activity   TIMESTAMPTZ,
    tickets_closed  INT NOT NULL DEFAULT 0,
    prs_merged      INT NOT NULL DEFAULT 0,
    helps_given     INT NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 3. bot_tickets
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_tickets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           TEXT NOT NULL,
    description     TEXT,
    tier            TEXT NOT NULL CHECK (tier IN ('T1', 'T2', 'T3')),
    status          TEXT NOT NULL DEFAULT 'todo'
                        CHECK (status IN ('todo', 'in_progress', 'in_review', 'done')),
    priority        TEXT NOT NULL DEFAULT 'medium'
                        CHECK (priority IN ('low', 'medium', 'high', 'blocker')),
    phase           TEXT,
    assignee_id     UUID REFERENCES bot_members(id) ON DELETE SET NULL,
    reviewer_id     UUID REFERENCES bot_members(id) ON DELETE SET NULL,
    created_by      UUID REFERENCES bot_members(id) ON DELETE SET NULL,
    deadline        TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ,
    github_pr       TEXT,
    discord_msg_id  TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 4. bot_xp_ledger
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_xp_ledger (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id   UUID NOT NULL REFERENCES bot_members(id) ON DELETE CASCADE,
    action      TEXT NOT NULL,
    xp          INT NOT NULL,
    metadata    JSONB,
    awarded_at  TIMESTAMPTZ DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 5. bot_xp_actions (reference table)
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_xp_actions (
    action      TEXT PRIMARY KEY,
    xp          INT NOT NULL,
    description TEXT NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 6. bot_badge_definitions
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_badge_definitions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key         TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    emoji       TEXT NOT NULL,
    trigger     TEXT NOT NULL
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 7. bot_badges_earned
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_badges_earned (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id   UUID NOT NULL REFERENCES bot_members(id) ON DELETE CASCADE,
    badge_id    UUID NOT NULL REFERENCES bot_badge_definitions(id) ON DELETE CASCADE,
    earned_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE (member_id, badge_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 8. bot_streak_log
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_streak_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id   UUID NOT NULL REFERENCES bot_members(id) ON DELETE CASCADE,
    streak_date DATE NOT NULL,
    activity    TEXT NOT NULL,
    UNIQUE (member_id, streak_date)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 9. bot_standup_sessions
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_standup_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    date        DATE UNIQUE NOT NULL,
    posted_at   TIMESTAMPTZ,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 10. bot_standup_responses
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_standup_responses (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID NOT NULL REFERENCES bot_standup_sessions(id) ON DELETE CASCADE,
    member_id    UUID NOT NULL REFERENCES bot_members(id) ON DELETE CASCADE,
    yesterday    TEXT,
    today        TEXT,
    blockers     TEXT,
    responded_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (session_id, member_id)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 11. bot_help_threads
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_help_threads (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    requester_id      UUID NOT NULL REFERENCES bot_members(id) ON DELETE CASCADE,
    problem           TEXT NOT NULL,
    discord_thread_id TEXT,
    status            TEXT NOT NULL DEFAULT 'open'
                          CHECK (status IN ('open', 'resolved', 'escalated')),
    helper_id         UUID REFERENCES bot_members(id) ON DELETE SET NULL,
    opened_at         TIMESTAMPTZ DEFAULT now(),
    resolved_at       TIMESTAMPTZ,
    escalated_at      TIMESTAMPTZ,
    resolution_notes  TEXT
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 12. bot_phases
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_phases (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key          TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    description  TEXT,
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'active', 'complete')),
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 13a. bot_phase_criteria
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_phase_criteria (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phase_id    UUID NOT NULL REFERENCES bot_phases(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    checked     BOOLEAN NOT NULL DEFAULT false,
    checked_by  UUID REFERENCES bot_members(id) ON DELETE SET NULL,
    checked_at  TIMESTAMPTZ
);

-- ─────────────────────────────────────────────────────────────────────────────
-- 13b. bot_github_events
-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE bot_github_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type  TEXT NOT NULL,
    actor       TEXT NOT NULL,
    member_id   UUID REFERENCES bot_members(id) ON DELETE SET NULL,
    payload     JSONB NOT NULL,
    received_at TIMESTAMPTZ DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Row Level Security — service role has full access on all bot_* tables
-- ─────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public' AND tablename LIKE 'bot_%'
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format(
            'CREATE POLICY service_role_full_access ON %I
             TO service_role
             USING (true)
             WITH CHECK (true)',
            tbl
        );
    END LOOP;
END;
$$;
