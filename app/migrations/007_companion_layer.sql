CREATE TABLE companion_projects (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL,
    description      TEXT,
    type             TEXT NOT NULL CHECK (type IN (
                         'web', 'mobile', 'game', 'research', 'capstone', 'hackathon', 'other')),
    status           TEXT DEFAULT 'active'
                     CHECK (status IN ('active', 'paused', 'archived')),
    github_repo_url  TEXT,
    owner_id         UUID REFERENCES bot_members(id),
    discord_guild_id TEXT NOT NULL,
    created_at       TIMESTAMPTZ DEFAULT now(),
    archived_at      TIMESTAMPTZ
);

CREATE TABLE companion_project_members (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  UUID REFERENCES companion_projects(id) ON DELETE CASCADE,
    member_id   UUID REFERENCES bot_members(id) ON DELETE CASCADE,
    role        TEXT DEFAULT 'contributor'
                CHECK (role IN ('owner', 'lead', 'contributor', 'observer')),
    joined_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id, member_id)
);

CREATE TABLE companion_member_context (
    member_id           UUID PRIMARY KEY REFERENCES bot_members(id) ON DELETE CASCADE,
    active_project_id   UUID REFERENCES companion_projects(id),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Backward-compatible FK additions to existing bot tables
ALTER TABLE bot_tickets        ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES companion_projects(id);
ALTER TABLE bot_phases         ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES companion_projects(id);
ALTER TABLE bot_github_events  ADD COLUMN IF NOT EXISTS project_id UUID REFERENCES companion_projects(id);

-- ─── CHALLENGES ───────────────────────────────────────────────────────────────

CREATE TABLE companion_challenges (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     UUID REFERENCES companion_projects(id),
    created_by     UUID REFERENCES bot_members(id),
    type           TEXT NOT NULL CHECK (type IN (
                       'quick_fire', 'mini_sprint', 'code_golf', 'bug_hunt', 'architecture')),
    title          TEXT NOT NULL,
    description    TEXT NOT NULL,
    duration_min   INT,                        -- NULL = async, no timer
    status         TEXT DEFAULT 'open'
                   CHECK (status IN ('open', 'closed', 'graded')),
    discord_msg_id TEXT,
    opened_at      TIMESTAMPTZ DEFAULT now(),
    closed_at      TIMESTAMPTZ
);

CREATE TABLE companion_challenge_submissions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    challenge_id UUID REFERENCES companion_challenges(id) ON DELETE CASCADE,
    member_id    UUID REFERENCES bot_members(id),
    content      TEXT NOT NULL,                -- code block or URL
    submitted_at TIMESTAMPTZ DEFAULT now(),
    score        INT CHECK (score BETWEEN 0 AND 100),
    xp_awarded   INT DEFAULT 0,
    UNIQUE(challenge_id, member_id)
);

-- ─── LEARNING TRACKS ──────────────────────────────────────────────────────────

CREATE TABLE companion_tracks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT UNIQUE NOT NULL,
    description TEXT,
    level       TEXT CHECK (level IN ('beginner', 'intermediate', 'advanced')),
    created_by  UUID REFERENCES bot_members(id),
    is_builtin  BOOLEAN DEFAULT false,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE companion_track_checkpoints (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    track_id        UUID REFERENCES companion_tracks(id) ON DELETE CASCADE,
    sequence        INT NOT NULL,
    title           TEXT NOT NULL,
    resource_url    TEXT,
    exercise        TEXT,
    knowledge_check TEXT,
    answer_hash     TEXT,                      -- bcrypt hash of expected answer
    xp_value        INT DEFAULT 10,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(track_id, sequence)
);

CREATE TABLE companion_member_track_progress (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id        UUID REFERENCES bot_members(id),
    track_id         UUID REFERENCES companion_tracks(id),
    enrolled_at      TIMESTAMPTZ DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    checkpoints_done INT DEFAULT 0,
    UNIQUE(member_id, track_id)
);

CREATE TABLE companion_checkpoint_completions (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id     UUID REFERENCES bot_members(id),
    checkpoint_id UUID REFERENCES companion_track_checkpoints(id),
    completed_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(member_id, checkpoint_id)
);

-- ─── JOURNAL ──────────────────────────────────────────────────────────────────

CREATE TABLE companion_journal_entries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id   UUID REFERENCES bot_members(id),
    project_id  UUID REFERENCES companion_projects(id),
    entry_type  TEXT DEFAULT 'freeform'
                CHECK (entry_type IN ('freeform', 'adr', 'reflection', 'blocker')),
    content     TEXT NOT NULL,
    mood        INT CHECK (mood BETWEEN 1 AND 5),
    tags        TEXT[] DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Full-text search index
CREATE INDEX companion_journal_fts ON companion_journal_entries
    USING GIN (to_tsvector('english', content));

CREATE TABLE companion_adrs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entry_id      UUID REFERENCES companion_journal_entries(id) UNIQUE,
    project_id    UUID REFERENCES companion_projects(id),
    sequence      INT NOT NULL,               -- ADR #1, #2… per project
    title         TEXT NOT NULL,
    context       TEXT NOT NULL,
    decision      TEXT NOT NULL,
    alternatives  TEXT,
    status        TEXT DEFAULT 'proposed'
                  CHECK (status IN ('proposed', 'accepted', 'deprecated', 'superseded')),
    superseded_by UUID REFERENCES companion_adrs(id),
    UNIQUE(project_id, sequence)
);

-- ─── GOOGLE CALENDAR ──────────────────────────────────────────────────────────

CREATE TABLE companion_calendar_tokens (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id      UUID REFERENCES bot_members(id) UNIQUE,
    -- access_token stored in Supabase Vault; this column holds the vault secret ID
    vault_secret_id TEXT NOT NULL,
    token_expiry   TIMESTAMPTZ,
    calendar_id    TEXT DEFAULT 'primary',
    connected_at   TIMESTAMPTZ DEFAULT now(),
    last_sync_at   TIMESTAMPTZ
);

CREATE TABLE companion_calendar_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id       UUID REFERENCES bot_members(id),
    project_id      UUID REFERENCES companion_projects(id),
    google_event_id TEXT NOT NULL,
    source_type     TEXT NOT NULL
                    CHECK (source_type IN ('ticket_deadline', 'sprint', 'phase', 'focus_block')),
    source_id       UUID,
    synced_at       TIMESTAMPTZ DEFAULT now(),
    deleted_at      TIMESTAMPTZ
);

-- ─── COMPANION XP ACTIONS ─────────────────────────────────────────────────────

INSERT INTO bot_xp_actions (action, xp, description) VALUES
    ('challenge_submit',        10,  'Submitted a dev challenge before deadline'),
    ('challenge_score_60',      20,  'Challenge score 60–79'),
    ('challenge_score_80',      35,  'Challenge score 80–94'),
    ('challenge_score_95',      50,  'Challenge score 95–100'),
    ('challenge_first',         15,  'First correct challenge submission'),
    ('track_checkpoint',        10,  'Completed a learning track checkpoint'),
    ('track_25pct',             15,  'Completed 25% of a track'),
    ('track_50pct',             20,  'Completed 50% of a track'),
    ('track_complete',          75,  'Completed an entire learning track'),
    ('journal_entry',            5,  'Daily journal entry (once per day)'),
    ('journal_adr',             15,  'Recorded an architectural decision'),
    ('journal_mood',             2,  'Logged mood with a journal entry'),
    ('calendar_focus_block',     5,  'Created a focus block on Google Calendar');

-- ─── INDEXES ──────────────────────────────────────────────────────────────────

CREATE INDEX companion_challenges_status    ON companion_challenges(status);
CREATE INDEX companion_challenges_project   ON companion_challenges(project_id);
CREATE INDEX companion_submissions_member   ON companion_challenge_submissions(member_id);
CREATE INDEX companion_journal_member       ON companion_journal_entries(member_id, created_at DESC);
CREATE INDEX companion_journal_project      ON companion_journal_entries(project_id, created_at DESC);
CREATE INDEX companion_adr_project          ON companion_adrs(project_id, sequence);
CREATE INDEX companion_calendar_member      ON companion_calendar_events(member_id, deleted_at);
