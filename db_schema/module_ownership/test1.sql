BEGIN;

-- 1. Load the View definition
-- This makes the 'module_ownership_summary' view available to this transaction
\i db_schema/module_ownership/script.sql

-- 2. Create Parent Repo
INSERT INTO repos (name, url, language)
VALUES ('backend-repo', 'http://github.com/test', 'Python');

-- 3. Create Engineers
INSERT INTO engineers (name, email)
VALUES 
    ('Alice', 'alice@test.com'),
    ('Bob', 'bob@test.com'),
    ('Charlie', 'charlie@test.com');

-- 4. Create Module
-- We dynamically fetch the repo_id to ensure the test never breaks
INSERT INTO modules (repo_id, name, dir_path)
VALUES (
    (SELECT id FROM repos WHERE name = 'backend-repo'), 
    'UserAuth', 
    '/src/auth'
);

-- 5. Link Engineers (Dynamic IDs)
WITH mod AS (SELECT id FROM modules WHERE name = 'UserAuth'),
     eng_a AS (SELECT id FROM engineers WHERE email = 'alice@test.com'),
     eng_b AS (SELECT id FROM engineers WHERE email = 'bob@test.com'),
     eng_c AS (SELECT id FROM engineers WHERE email = 'charlie@test.com')
INSERT INTO module_contributions (engineer_id, module_id, interaction_type)
VALUES 
    ((SELECT id FROM eng_a), (SELECT id FROM mod), 'DESIGNED'),
    ((SELECT id FROM eng_b), (SELECT id FROM mod), 'WROTE'),
    ((SELECT id FROM eng_c), (SELECT id FROM mod), 'REVIEWED');


-- 6. RUN THE TEST
-- We query the VIEW we created in step 1
SELECT 
    designers, 
    writers, 
    reviewers
FROM 
    module_ownership_summary
WHERE 
    module_name = 'UserAuth';

-- 7. Cleanup
ROLLBACK;

-- Expected Output:
-- designers |   writers   |  reviewers
-- ----------+-------------+-------------
-- {Alice}   | {Bob}       | {Charlie}