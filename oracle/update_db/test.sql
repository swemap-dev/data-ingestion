BEGIN;

-- ==========================================
-- 0. SETUP: CLEAN SLATE
-- ==========================================
TRUNCATE engineers, repos, modules, files, commits, commit_hunks, file_ownership_metrics CASCADE;

-- Create Engineers
INSERT INTO engineers (id, name, email) VALUES 
(1, 'Alice', 'alice@test.com'), 
(2, 'Bob', 'bob@test.com'), 
(3, 'Charlie', 'charlie@test.com');

-- Create Context
INSERT INTO repos (id, name) VALUES (1, 'Webhook_Testing');
INSERT INTO modules (id, repo_id, name) VALUES (1, 1, 'Webhook_Module');

COMMIT;