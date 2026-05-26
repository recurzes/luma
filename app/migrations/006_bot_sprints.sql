CREATE TABLE IF NOT EXISTS bot_sprints (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    days        INT NOT NULL,
    started_by  TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    ended_at    TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'ended'))
);

ALTER TABLE bot_sprints ENABLE ROW LEVEL SECURITY;

CREATE POLICY service_role_full_access ON bot_sprints
    TO service_role
    USING (true)
    WITH CHECK (true);
