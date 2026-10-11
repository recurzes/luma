-- Migration 013: Make the badge catalogue match what the bot can actually award
-- Requires 001–002 to be applied first. Safe to re-run.

-- 1. Badges for the blitz and track triggers the code already fires.
INSERT INTO bot_badge_definitions (key, name, description, emoji, trigger) VALUES
    ('blitz_rookie',   'Blitz Rookie',   'Joined your first Tech Blitz',                              '⚡', 'First blitz joined'),
    ('show_and_tell',  'Show & Tell',    'Submitted your first blitz showcase',                       '🎤', 'First blitz showcase submitted'),
    ('speed_learner',  'Speed Learner',  'Submitted a showcase in the first quarter of a blitz',      '🏎️', 'Showcase within 25% of blitz duration'),
    ('trailhead',      'Trailhead',      'Enrolled in your first learning track',                     '🧭', 'First track enrollment'),
    ('track_graduate', 'Track Graduate', 'Completed every checkpoint of a learning track',            '🎓', 'Track reaches 100%')
ON CONFLICT (key) DO NOTHING;

-- 2. Descriptions that promised more than the rule checks.
UPDATE bot_badge_definitions
SET description = 'Shared 5 resources via /share',
    trigger     = '5 knowledge_drop XP events'
WHERE key = 'knowledge_dealer';

UPDATE bot_badge_definitions
SET description = '10 PRs merged with zero added TypeScript any',
    trigger     = '10 merged PRs scanned clean (requires GITHUB_TOKEN)'
WHERE key = 'no_any_club';

-- 3. Seeded badges with no feature behind them. Nothing in the bot can award or display
--    these. Rows are kept if anyone holds the badge (e.g. it was granted by hand).
--    Delete this statement if you plan to build them.
DELETE FROM bot_badge_definitions d
WHERE d.key IN ('block_builder', 'tier_guard', 'contract_keeper', 'stress_tester', 'retro_voice')
  AND NOT EXISTS (SELECT 1 FROM bot_badges_earned e WHERE e.badge_id = d.id);
