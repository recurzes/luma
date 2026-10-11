-- Migration 014: Track which GitHub events the bot has processed
-- Requires 001_bot_tables.sql. Safe to re-run. Apply BEFORE deploying the bot version that
-- reads these columns.
--
-- The bot used to remember its place with an in-memory timestamp, so events received
-- while it was down were skipped and failed events were never retried.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'bot_github_events'
          AND column_name = 'processed_at'
    ) THEN
        ALTER TABLE bot_github_events
            ADD COLUMN processed_at TIMESTAMPTZ,
            ADD COLUMN attempts     INT NOT NULL DEFAULT 0,
            ADD COLUMN last_error   TEXT;

        -- Everything already in the table predates the queue; do not replay it.
        -- Inside the IF so a re-run never marks genuinely pending events as done.
        UPDATE bot_github_events SET processed_at = now();
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_bot_github_events_pending
    ON bot_github_events (received_at)
    WHERE processed_at IS NULL;
