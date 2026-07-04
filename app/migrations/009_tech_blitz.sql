-- =============================================================================
-- 007_tech_blitz.sql
-- Tech Blitz — global timed team learning sprints
-- Run AFTER 005_companion_layer.sql
-- Branch: feature/tech-blitz
-- =============================================================================

-- ─── BLITZ SESSIONS ───────────────────────────────────────────────────────────
-- One active blitz per guild at a time (enforced at service layer).

CREATE TABLE companion_blitz_sessions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    guild_id         TEXT NOT NULL,
    created_by       UUID REFERENCES bot_members(id),

    -- What are we learning?
    technology       TEXT NOT NULL,        -- e.g. "Godot 4 / GDScript", "Rust", "SvelteKit"
    tech_category    TEXT NOT NULL         -- 'language', 'framework', 'engine', 'tool', 'other'
                     CHECK (tech_category IN ('language', 'framework', 'engine', 'tool', 'other')),

    -- What are we building?
    goal             TEXT NOT NULL,        -- e.g. "a playable 2D platformer", "a REST API", "a CLI"
    deliverable_type TEXT NOT NULL DEFAULT 'any'
                     CHECK (deliverable_type IN (
                         'game', 'web_app', 'mobile_app', 'cli', 'api',
                         'library', 'prototype', 'any')),

    -- Timer
    duration_hours   INT NOT NULL DEFAULT 48,
    started_at       TIMESTAMPTZ DEFAULT now(),
    ends_at          TIMESTAMPTZ NOT NULL,          -- computed: started_at + duration_hours
    extended_hours   INT DEFAULT 0,                 -- Lead can add time

    -- Lifecycle
    status           TEXT DEFAULT 'active'
                     CHECK (status IN ('active', 'showcase', 'completed', 'cancelled')),
    -- 'active'    → timer running, check-ins open
    -- 'showcase'  → timer expired, showcase submissions open (grace period)
    -- 'completed' → gallery posted, blitz archived
    -- 'cancelled' → Lead cancelled early

    -- Discord anchors
    announce_msg_id  TEXT,    -- ID of the pinned countdown embed in #blitz
    guild_channel_id TEXT,    -- #blitz channel ID

    completed_at     TIMESTAMPTZ,
    cancelled_at     TIMESTAMPTZ
);

-- ─── PARTICIPANTS ─────────────────────────────────────────────────────────────

CREATE TABLE companion_blitz_participants (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blitz_id     UUID REFERENCES companion_blitz_sessions(id) ON DELETE CASCADE,
    member_id    UUID REFERENCES bot_members(id) ON DELETE CASCADE,
    joined_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(blitz_id, member_id)
);

-- ─── CHECK-INS ────────────────────────────────────────────────────────────────
-- Members post periodic progress updates during the blitz.

CREATE TABLE companion_blitz_checkins (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blitz_id     UUID REFERENCES companion_blitz_sessions(id) ON DELETE CASCADE,
    member_id    UUID REFERENCES bot_members(id) ON DELETE CASCADE,
    content      TEXT NOT NULL,           -- what did you do / build?
    media_url    TEXT,                    -- optional screenshot, GIF, video link
    mood         INT CHECK (mood BETWEEN 1 AND 5),
    posted_at    TIMESTAMPTZ DEFAULT now()
);

-- ─── SHOWCASE SUBMISSIONS ─────────────────────────────────────────────────────
-- Final deliverable submitted at end of blitz.

CREATE TABLE companion_blitz_showcases (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blitz_id     UUID REFERENCES companion_blitz_sessions(id) ON DELETE CASCADE,
    member_id    UUID REFERENCES bot_members(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,           -- project title
    description  TEXT NOT NULL,           -- what was built
    repo_url     TEXT,                    -- GitHub / GitLab link
    demo_url     TEXT,                    -- playable link, hosted URL, video
    media_url    TEXT,                    -- screenshot or GIF
    submitted_at TIMESTAMPTZ DEFAULT now(),
    -- Community voting
    vote_count   INT DEFAULT 0,
    UNIQUE(blitz_id, member_id)
);

-- ─── BLITZ MILESTONES LOG ─────────────────────────────────────────────────────
-- Tracks which automated milestone alerts have been sent (prevents duplicates).

CREATE TABLE companion_blitz_milestones (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    blitz_id     UUID REFERENCES companion_blitz_sessions(id) ON DELETE CASCADE,
    milestone    TEXT NOT NULL,           -- '75pct_done', '50pct_done', '25pct_left', '1h_left'
    fired_at     TIMESTAMPTZ DEFAULT now(),
    UNIQUE(blitz_id, milestone)
);

-- ─── XP ADDITIONS ─────────────────────────────────────────────────────────────

INSERT INTO bot_xp_actions (action, xp, description) VALUES
    ('blitz_join',       5,   'Joined a Tech Blitz'),
    ('blitz_checkin',   10,   'Posted a Tech Blitz check-in'),
    ('blitz_showcase',  25,   'Submitted a Blitz showcase'),
    ('blitz_complete',  50,   'Completed a full Tech Blitz (participant + showcase)'),
    ('blitz_first_in',   5,   'First check-in of the blitz');

-- ─── INDEXES ──────────────────────────────────────────────────────────────────

CREATE INDEX blitz_sessions_guild    ON companion_blitz_sessions(guild_id, status);
CREATE INDEX blitz_participants_blitz ON companion_blitz_participants(blitz_id);
CREATE INDEX blitz_checkins_blitz    ON companion_blitz_checkins(blitz_id, posted_at DESC);
CREATE INDEX blitz_showcases_blitz   ON companion_blitz_showcases(blitz_id);
