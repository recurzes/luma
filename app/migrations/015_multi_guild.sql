-- Migration 015: Separate data per Discord server
-- Requires 001–014. Safe to re-run. Stop the bot, apply this, then deploy the matching code:
-- the previous bot version cannot run against this schema.
--
-- A member becomes one row per (Discord user, server). Everything keyed by member_id
-- (stats, XP ledger, badges, streaks, standup responses, journal, track progress, ...) is
-- therefore per server without changing those tables. Tables with no member owner get a
-- guild_id column.
--
-- BEFORE RUNNING: set home_guild below to the Discord server ID that owns today's data.
-- Members who are also enrolled in other servers get a fresh, empty profile there.

DO $$
DECLARE
    home_guild TEXT := 'REPLACE_WITH_HOME_GUILD_ID';
    enrollment RECORD;
    new_member UUID;
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'bot_members' AND column_name = 'guild_id'
    ) THEN
        RAISE NOTICE 'Migration 015 already applied; skipping';
        RETURN;
    END IF;

    IF home_guild !~ '^[0-9]{15,20}$' THEN
        RAISE EXCEPTION 'Set home_guild to your Discord server ID before running migration 015';
    END IF;

    -- ── Members ──────────────────────────────────────────────────────────────
    ALTER TABLE bot_members ADD COLUMN guild_id TEXT;
    UPDATE bot_members SET guild_id = home_guild;
    ALTER TABLE bot_members ALTER COLUMN guild_id SET NOT NULL;
    ALTER TABLE bot_members DROP CONSTRAINT IF EXISTS bot_members_discord_id_key;
    ALTER TABLE bot_members ADD CONSTRAINT bot_members_discord_guild_key UNIQUE (discord_id, guild_id);

    -- Members enrolled in another server: give them a fresh profile there and move that
    -- server's enrolment and notification rows onto it.
    FOR enrollment IN
        SELECT e.id AS enrollment_id, e.guild_id, m.id AS old_member,
               m.discord_id, m.discord_name, m.github_username, m.role, m.tier_max
        FROM bot_member_enrollments e
        JOIN bot_members m ON m.id = e.member_id
        WHERE e.guild_id <> home_guild
    LOOP
        INSERT INTO bot_members (discord_id, discord_name, github_username, role, tier_max, guild_id)
        VALUES (enrollment.discord_id, enrollment.discord_name, enrollment.github_username,
                enrollment.role, enrollment.tier_max, enrollment.guild_id)
        RETURNING id INTO new_member;

        INSERT INTO bot_member_stats (member_id) VALUES (new_member);

        UPDATE bot_member_enrollments SET member_id = new_member WHERE id = enrollment.enrollment_id;
        UPDATE bot_notification_preferences SET member_id = new_member
        WHERE member_id = enrollment.old_member AND guild_id = enrollment.guild_id;
    END LOOP;

    -- ── Tables with no member owner ──────────────────────────────────────────
    ALTER TABLE bot_tickets ADD COLUMN guild_id TEXT;
    UPDATE bot_tickets SET guild_id = home_guild;
    ALTER TABLE bot_tickets ALTER COLUMN guild_id SET NOT NULL;

    ALTER TABLE bot_standup_sessions ADD COLUMN guild_id TEXT;
    UPDATE bot_standup_sessions SET guild_id = home_guild;
    ALTER TABLE bot_standup_sessions ALTER COLUMN guild_id SET NOT NULL;
    ALTER TABLE bot_standup_sessions DROP CONSTRAINT IF EXISTS bot_standup_sessions_date_key;
    ALTER TABLE bot_standup_sessions ADD CONSTRAINT bot_standup_sessions_guild_date_key UNIQUE (guild_id, date);

    ALTER TABLE bot_phases ADD COLUMN guild_id TEXT;
    UPDATE bot_phases SET guild_id = home_guild;
    ALTER TABLE bot_phases ALTER COLUMN guild_id SET NOT NULL;
    ALTER TABLE bot_phases DROP CONSTRAINT IF EXISTS bot_phases_key_key;
    ALTER TABLE bot_phases ADD CONSTRAINT bot_phases_guild_key_key UNIQUE (guild_id, key);

    ALTER TABLE bot_sprints ADD COLUMN guild_id TEXT;
    UPDATE bot_sprints SET guild_id = home_guild;
    ALTER TABLE bot_sprints ALTER COLUMN guild_id SET NOT NULL;

    -- Open-PR reminders are short-lived; rows without a repo cannot be routed, so start clean.
    DELETE FROM bot_pr_reviewers;
    ALTER TABLE bot_pr_reviewers ADD COLUMN guild_id TEXT NOT NULL;
    ALTER TABLE bot_pr_reviewers ADD COLUMN repo_full_name TEXT NOT NULL;
    ALTER TABLE bot_pr_reviewers DROP CONSTRAINT IF EXISTS bot_pr_reviewers_pkey;
    ALTER TABLE bot_pr_reviewers ADD PRIMARY KEY (guild_id, repo_full_name, pr_number);

    -- Set when an event is routed to a server; NULL means not routed (or pre-015).
    ALTER TABLE bot_github_events ADD COLUMN guild_id TEXT;

    -- NULL guild_id = built-in track shared by every server. Custom tracks made so far
    -- belong to the home server.
    ALTER TABLE companion_tracks ADD COLUMN guild_id TEXT;
    UPDATE companion_tracks SET guild_id = home_guild WHERE NOT COALESCE(is_builtin, false);
    ALTER TABLE companion_tracks DROP CONSTRAINT IF EXISTS companion_tracks_name_key;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS companion_tracks_guild_name_key
    ON companion_tracks (COALESCE(guild_id, ''), lower(name));

CREATE INDEX IF NOT EXISTS idx_bot_members_guild            ON bot_members (guild_id);
CREATE INDEX IF NOT EXISTS idx_bot_members_guild_github     ON bot_members (guild_id, lower(github_username));
CREATE INDEX IF NOT EXISTS idx_bot_tickets_guild_status     ON bot_tickets (guild_id, status);
CREATE INDEX IF NOT EXISTS idx_bot_sprints_guild_status     ON bot_sprints (guild_id, status);
CREATE INDEX IF NOT EXISTS idx_bot_phases_guild_status      ON bot_phases (guild_id, status);
