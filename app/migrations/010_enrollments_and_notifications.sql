-- Migration 010: Guild enrollments and per-feature DM notification preferences
-- Requires 001_bot_tables.sql to be applied first.

CREATE TABLE bot_member_enrollments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id     UUID NOT NULL REFERENCES bot_members(id) ON DELETE CASCADE,
    guild_id      TEXT NOT NULL,
    guild_name    TEXT NOT NULL,
    signed_out_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(member_id, guild_id)
);

CREATE TABLE bot_notification_preferences (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id  UUID NOT NULL REFERENCES bot_members(id) ON DELETE CASCADE,
    guild_id   TEXT NOT NULL,
    feature    TEXT NOT NULL,
    enabled    BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(member_id, guild_id, feature)
);

CREATE INDEX bot_member_enrollments_guild_active
    ON bot_member_enrollments(guild_id)
    WHERE signed_out_at IS NULL;

CREATE INDEX bot_notification_preferences_lookup
    ON bot_notification_preferences(member_id, guild_id, feature);
