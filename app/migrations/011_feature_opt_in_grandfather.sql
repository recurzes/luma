-- Migration 011: Grandfather existing enrollments into all features (opt-in model)
-- Requires 010_enrollments_and_notifications.sql to be applied first.

INSERT INTO bot_notification_preferences (member_id, guild_id, feature, enabled)
SELECT e.member_id, e.guild_id, f.feature, true
FROM bot_member_enrollments e
CROSS JOIN (
    VALUES ('standup'), ('mood'), ('journal'), ('streak'), ('track'), ('blitz'), ('stuck')
) AS f(feature)
WHERE e.signed_out_at IS NULL
ON CONFLICT (member_id, guild_id, feature) DO NOTHING;
