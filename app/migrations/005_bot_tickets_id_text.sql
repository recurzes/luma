-- Generated text form of ticket UUID for short-ID lookups (last 8 chars, etc.)
ALTER TABLE bot_tickets
    ADD COLUMN IF NOT EXISTS id_text TEXT GENERATED ALWAYS AS (id::text) STORED;

CREATE INDEX IF NOT EXISTS idx_bot_tickets_id_text ON bot_tickets (id_text);
