CREATE OR REPLACE FUNCTION journal_fts_search(
    p_member_id  UUID,
    p_project_id UUID,
    p_query      TEXT
)
RETURNS SETOF companion_journal_entries
LANGUAGE sql STABLE AS $$
    SELECT *
    FROM companion_journal_entries
    WHERE member_id = p_member_id
      AND (p_project_id IS NULL OR project_id = p_project_id)
      AND to_tsvector('english', content) @@ plainto_tsquery('english', p_query)
    ORDER BY created_at DESC
    LIMIT 20;
$$;

-- Stale learning track enrollment detection (used by Monday nudge job)
CREATE OR REPLACE FUNCTION get_stale_track_enrollments(cutoff TIMESTAMPTZ)
RETURNS TABLE(member_id UUID, track_id UUID, track_name TEXT, discord_id TEXT)
LANGUAGE sql STABLE AS $$
    SELECT
        p.member_id,
        p.track_id,
        t.name AS track_name,
        m.discord_id
    FROM companion_member_track_progress p
    JOIN companion_tracks t ON t.id = p.track_id
    JOIN bot_members m ON m.id = p.member_id
    WHERE p.completed_at IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM companion_checkpoint_completions c
          WHERE c.member_id = p.member_id
            AND c.completed_at > cutoff
      );
$$;