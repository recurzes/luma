-- Migration 012: Enable Row Level Security on every bot_* / companion_* table that lacks it
-- Requires 001–011 to be applied first. Safe to re-run.
--
-- 001 enabled RLS only on the bot_* tables that existed when it ran. Tables added later
-- (bot_pr_reviewers, bot_sprints, all companion_*, bot_member_enrollments,
-- bot_notification_preferences) were left readable and writable with the anon key.
-- The bot uses the service-role key, which bypasses RLS, so it is unaffected.

DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOR tbl IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND (tablename LIKE 'bot\_%' OR tablename LIKE 'companion\_%')
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', tbl);

        IF NOT EXISTS (
            SELECT 1
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = tbl
              AND policyname = 'service_role_full_access'
        ) THEN
            EXECUTE format(
                'CREATE POLICY service_role_full_access ON public.%I
                 TO service_role
                 USING (true)
                 WITH CHECK (true)',
                tbl
            );
        END IF;
    END LOOP;
END;
$$;
