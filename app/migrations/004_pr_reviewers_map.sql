CREATE TABLE bot_pr_reviewers (
    pr_number            INT PRIMARY KEY,
    reviewer_member_id   UUID NOT NULL REFERENCES bot_members(id) ON DELETE CASCADE,
    pr_url               TEXT NOT NULL,
    pr_created_at        TIMESTAMPTZ NOT NULL,
    updated_at           TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE bot_pr_reviewers ENABLE ROW LEVEL SECURITY;

CREATE POLICY service_role_full_access ON bot_pr_reviewers
    TO service_role
    USING (true)
    WITH CHECK (true);