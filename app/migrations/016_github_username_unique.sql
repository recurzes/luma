-- 016: one GitHub username per server (audit B-29).
-- Commit and review XP is matched on github_username, so two members sharing one in the same
-- server means one of them collects the other's XP. The bot now refuses a taken username;
-- this index is the backstop. Idempotent.

DO $$
DECLARE
    dupes TEXT;
BEGIN
    SELECT string_agg(format('%s in server %s (%s members)', gh, guild_id, n), '; ')
      INTO dupes
      FROM (
          SELECT guild_id, lower(github_username) AS gh, count(*) AS n
            FROM bot_members
           WHERE github_username IS NOT NULL AND github_username <> ''
           GROUP BY guild_id, lower(github_username)
          HAVING count(*) > 1
      ) d;

    IF dupes IS NOT NULL THEN
        RAISE EXCEPTION 'Duplicate GitHub usernames must be resolved first (clear the wrong one): %', dupes;
    END IF;
END $$;

UPDATE bot_members SET github_username = NULL WHERE github_username = '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_bot_members_guild_github
    ON bot_members (guild_id, lower(github_username))
    WHERE github_username IS NOT NULL;

-- Superseded by the unique index above.
DROP INDEX IF EXISTS idx_bot_members_guild_github;
