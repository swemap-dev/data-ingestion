-- Designer and Writer are the same person for module 'UserAuth'

BEGIN;

-- 1. Create a dummy Repo
INSERT INTO repos (name, url, language)
VALUES ('backend-repo', 'http://github.com/test', 'Python');

-- 2. Create 3 Engineers
INSERT INTO engineers (name, email)
VALUES 
    ('Alice', 'alice@test.com'),
    ('Bob', 'bob@test.com'),
    ('Charlie', 'charlie@test.com');

-- 3. Create the Module
-- FIX: Instead of writing '1', we ask for the ID of the repo we named 'backend-repo'
INSERT INTO modules (repo_id, name, dir_path)
VALUES (
    (SELECT id FROM repos WHERE name = 'backend-repo' LIMIT 1), 
    'UserAuth', 
    '/src/auth'
);

-- 4. Link Engineers to Module
-- FIX: We dynamically look up Alice's ID and the Module's ID
INSERT INTO module_contributions (engineer_id, module_id, interaction_type)
VALUES 
    (
        (SELECT id FROM engineers WHERE email = 'alice@test.com'), 
        (SELECT id FROM modules WHERE name = 'UserAuth'), 
        'DESIGNED'
    ),
    (
        (SELECT id FROM engineers WHERE email = 'alice@test.com'), 
        (SELECT id FROM modules WHERE name = 'UserAuth'), 
        'WROTE'
    ),
    (
        (SELECT id FROM engineers WHERE email = 'charlie@test.com'), 
        (SELECT id FROM modules WHERE name = 'UserAuth'), 
        'REVIEWED'
    );

-- 5. Run your test query
SELECT 
    designers, 
    writers, 
    reviewers
FROM 
    module_ownership_summary
WHERE 
    module_name = 'UserAuth';
    
ROLLBACK;

-- -- Wipes the data AND resets the counter to 1
-- TRUNCATE TABLE engineers RESTART IDENTITY CASCADE;

-- Expected Output:
--  designers | writers | reviewers 
-- -----------+---------+-----------
--  {Alice}   | {Alice} | {Charlie}