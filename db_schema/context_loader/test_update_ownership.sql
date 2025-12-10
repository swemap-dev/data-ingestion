BEGIN;

-- 1. SETUP: Clean Slate & Base Data
TRUNCATE engineers, repos, modules, files, commits, commit_hunks, file_ownership_metrics CASCADE;

-- Create the 3 engineers
INSERT INTO engineers (id, name, email) VALUES 
(1, 'Engineer A', 'a@eng.com'), 
(2, 'Engineer B', 'b@eng.com'), 
(3, 'Engineer C', 'c@eng.com');

-- Create Repo1 and Modules
INSERT INTO repos (id, name) VALUES (1, 'Repo1');
INSERT INTO modules (id, repo_id, name) VALUES (10, 1, 'ModuleA'), (11, 1, 'ModuleB');

-- Create Files (ModuleA has File 100, ModuleB has File 101)
INSERT INTO files (id, module_id, file_path, line_count) VALUES 
(100, 10, 'src/moduleA/main.py', 0), 
(101, 11, 'src/moduleB/utils.py', 0);


-- 2. PHASE 1: GENESIS (Engineer A creates everything)
INSERT INTO commits (hash, repo_id, message) VALUES ('hash_init', 1, 'Initial Commit');

-- Engineer A adds 50 lines to both files.
-- IMPORTANT: Trigger fires here to give A +50 ownership on both.
-- We must manually supply 'engineer_id' to the hunks for the trigger to work efficiently.
-- (Assuming column exists or is joined).
INSERT INTO commit_hunks (commit_hash, file_id, line_range, overwritten_engineer_ids, lines_added, lines_deleted, engineer_id)
VALUES 
('hash_init', 100, '[1,50)', NULL, 50, 0, 1), -- File 100 (Module A)
('hash_init', 101, '[1,50)', NULL, 50, 0, 1); -- File 101 (Module B)


-- 3. PHASE 2: THE OVERWRITE (B and C attack)

-- Engineer B updates ModuleA (File 100)
-- "from start_line=5 to end_line=30" -> inclusive range is 26 lines.
-- Victim is Engineer A (id=1).
INSERT INTO commits (hash, repo_id, message) VALUES ('hash_B', 1, 'B Update');

INSERT INTO commit_hunks (commit_hash, file_id, line_range, overwritten_engineer_ids, lines_added, lines_deleted, engineer_id)
VALUES 
('hash_B', 100, '[5,31)', ARRAY[1], 26, 26, 2);


-- Math Person C updates ModuleB (File 101)
-- "from start_line=10 to end_line=15" -> inclusive range is 6 lines.
-- Victim is Person A (id=1).
INSERT INTO commits (hash, repo_id, message) VALUES ('hash_C', 1, 'C Update');

INSERT INTO commit_hunks (commit_hash, file_id, line_range, overwritten_engineer_ids, lines_added, lines_deleted, engineer_id)
VALUES 
('hash_C', 101, '[10,16)', ARRAY[1], 6, 6, 3); 


COMMIT;

-- 4. VERIFICATION
-- Check the scorecard.

SELECT 
    f.file_path,
    e.name as engineer,
    m.lines_owned as lines_owned,
    m.lines_owned_percentage as lines_owned_percentage,
    m.commit_count
FROM file_ownership_metrics m
JOIN engineers e ON m.engineer_id = e.id
JOIN files f ON m.file_id = f.id
ORDER BY f.file_path, e.name;