-- Migration 002: Seed data
-- Requires 001_bot_tables.sql to be applied first.

-- ─────────────────────────────────────────────────────────────────────────────
-- XP action reference table
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO bot_xp_actions (action, xp, description) VALUES
    ('close_t1',        10,  'Closed a T1 ticket'),
    ('close_t2',        25,  'Closed a T2 ticket'),
    ('close_t3',        50,  'Closed a T3 ticket'),
    ('commit',           5,  'Pushed a commit to GitHub'),
    ('pr_merged',       20,  'Had a PR merged'),
    ('pr_reviewed',     15,  'Submitted a PR review'),
    ('helped_stuck',    15,  'Resolved a /stuck thread'),
    ('standup',          5,  'Responded to daily standup'),
    ('shoutout_given',  10,  'Sent a /shoutout'),
    ('shoutout_recv',   10,  'Received a /shoutout'),
    ('knowledge_drop',   8,  'Shared a resource via /share');

-- ─────────────────────────────────────────────────────────────────────────────
-- Phase registry (mirrors master plan roadmap)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO bot_phases (key, name, description, status) VALUES
    ('phase-0', 'Bot Foundation',
     'Running bot in server, connected to Supabase, no features yet.',
     'active'),
    ('phase-1', 'Tickets & Members',
     'Team can create, assign, and update tickets in Discord.',
     'pending'),
    ('phase-2', 'XP, Streaks & Standup',
     'XP system live, daily standups running.',
     'pending'),
    ('phase-3', 'GitHub Integration & Stuck System',
     'GitHub events flowing into Discord, 15-minute rule enforced.',
     'pending'),
    ('phase-4', 'Badges, Phases & Polish',
     'Full gamification running, phase tracker live.',
     'pending');

-- ─────────────────────────────────────────────────────────────────────────────
-- Badge definitions (Section 10.3 of master plan)
-- ─────────────────────────────────────────────────────────────────────────────
INSERT INTO bot_badge_definitions (key, name, description, emoji, trigger) VALUES
    ('block_builder',     'Block Builder',      'Shipped a complete block type end-to-end',                             '🏗️',  'Ticket closed + PR merged for a full block type'),
    ('tier_guard',        'Tier Guard',         'First to catch a vibe-coded PR in review',                            '🔍',  'Flagged by reviewer, confirmed by Lead'),
    ('rubber_duck',       'Rubber Duck',        'Resolved 5 /stuck threads as the helper',                             '🦆',  'helps_given reaches 5'),
    ('contract_keeper',   'Contract Keeper',    'Contributed to the API contract doc',                                  '📐',  'PR merged to LMA_API_Contract.md'),
    ('no_any_club',       'No `any` Club',      '10 PRs merged with zero TypeScript any flags',                         '🚫',  'prs_merged reaches 10 with no any flags'),
    ('ship_it',           'Ship It',            'PR merged same day it was opened',                                     '🚀',  'PR open and merged within same calendar day'),
    ('stress_tester',     'Stress Tester',      'Submitted a Phase 4 bug bash issue',                                   '🧪',  'Bug bash issue submitted during Phase 4'),
    ('streak_starter',    'Streak Starter',     'First 3-day streak',                                                   '🔥',  'current_streak reaches 3'),
    ('on_fire',           'On Fire',            '7-day streak',                                                         '🔥',  'current_streak reaches 7'),
    ('unstoppable',       'Unstoppable',        '14-day streak',                                                        '🔥',  'current_streak reaches 14'),
    ('legendary',         'Legendary',          '30-day streak',                                                        '👑',  'current_streak reaches 30'),
    ('standup_champion',  'Standup Champion',   '7 consecutive standup responses',                                      '☀️',  '7 consecutive standup responses'),
    ('helpful_human',     'Helpful Human',      'Used /shoutout 3 times',                                               '🤝',  'shoutout_given count reaches 3'),
    ('knowledge_dealer',  'Knowledge Dealer',   'Shared 5 resources via /share that got 3+ upvotes',                    '📚',  '5 /share posts with 3+ upvotes each'),
    ('clutch_coder',      'Clutch Coder',       'Closed a ticket within 1 hour of deadline',                            '⚡',  'Ticket closed within 1h of deadline'),
    ('retro_voice',       'Retro Voice',        'Responded to 3 sprint retrospectives',                                 '🪞',  '3 sprint retro responses recorded');
