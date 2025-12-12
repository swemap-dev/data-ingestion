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
INSERT INTO repos (id, name) VALUES (1, 'CoreRepo');
INSERT INTO modules (id, repo_id, name) VALUES (10, 1, 'AuthModule');
INSERT INTO files (id, module_id, file_path, line_count) VALUES 
(100, 10, 'auth.py', 0); -- Start with 0 lines

-- ==========================================
-- TEST A: THE DILUTION EVENT (Creation)
-- Alice creates 100 lines. Bob adds 100 lines.
-- Goal: Alice should own 50% despite losing 0 lines.
-- ==========================================
INSERT INTO commits (hash, repo_id, message) VALUES ('hash_init', 1, 'Init');

-- Alice adds 100 lines
INSERT INTO commit_hunks (commit_hash, file_id, engineer_id, line_range, overwritten_engineer_id, lines_added, lines_deleted)
VALUES ('hash_init', 100, 1, '[1,100)', NULL, 100, 0);

-- Bob adds 100 lines (appended)
INSERT INTO commit_hunks (commit_hash, file_id, engineer_id, line_range, overwritten_engineer_id, lines_added, lines_deleted)
VALUES ('hash_init', 100, 2, '[101,200)', NULL, 100, 0);

-- CHECKPOINT EXPECTATION:
-- File Size: 200 lines
-- Alice: 100 lines (50%)
-- Bob: 100 lines (50%)
DO $$
BEGIN
    ASSERT (SELECT COUNT(*) FROM file_ownership_metrics WHERE file_id = 100 AND engineer_id = 1 AND lines_owned = 100 AND lines_owned_percentage = 0.5) = 1, 'Alice verification failed';
    ASSERT (SELECT COUNT(*) FROM file_ownership_metrics WHERE file_id = 100 AND engineer_id = 2 AND lines_owned = 100 AND lines_owned_percentage = 0.5) = 1, 'Bob verification failed';
END $$;

SELECT 
    'CHECKPOINT A' as stage,
    e.name,
    m.lines_owned as actual_lines,
    100 as expected_lines,
    ROUND((m.lines_owned_percentage * 100)::numeric, 2) as actual_pct,
    50.00 as expected_pct,
    f.line_count as file_lines,
    200 as expected_file_lines
FROM file_ownership_metrics m
JOIN engineers e ON m.engineer_id = e.id
JOIN files f ON m.file_id = f.id
WHERE m.file_id = 100
ORDER BY e.name;


-- ==========================================
-- TEST B: THE MULTI-VICTIM STRIKE
-- Charlie rewrites lines 90 to 110.
-- This overlaps Alice (90-100) and Bob (101-110).
-- Charlie adds 10 lines, but deletes 20 lines (10 from A, 10 from B).
-- ==========================================
INSERT INTO commits (hash, repo_id, message) VALUES ('hash_rewrite', 1, 'Charlie Rewrite');

-- Note: 'lines_deleted' is total (20). Logic assumes overlapping victims split this penalty.
-- *CRITICAL NOTE*: Your current trigger logic subtracts 'lines_deleted' from EVERY victim in the array.
-- If lines_deleted is 20, Alice loses 20 and Bob loses 20? 
-- Or did you mean for them to share it?
-- STRICT INTERPRETATION OF YOUR CODE: The loop runs `UPDATE ... SET lines_owned - NEW.lines_deleted`.
-- This means if we pass 20, BOTH lose 20. 
-- FOR THIS TEST: We will assume Charlie deletes 10 from Alice specifically, and 10 from Bob specifically, 
-- requiring TWO separate hunks if we want precise accounting, OR we accept the double penalty in the array loop.
--
-- REFINED TEST FOR ACCURACY: Let's do two hunks to ensure math is precise.
-- Hunk 1: Charlie overwrites Alice (10 lines)
INSERT INTO commit_hunks (commit_hash, file_id, engineer_id, line_range, overwritten_engineer_id, lines_added, lines_deleted)
VALUES ('hash_rewrite', 100, 3, '[90,100)', 1, 10, 10);

-- Hunk 2: Charlie overwrites Bob (10 lines)
INSERT INTO commit_hunks (commit_hash, file_id, engineer_id, line_range, overwritten_engineer_id, lines_added, lines_deleted)
VALUES ('hash_rewrite', 100, 3, '[101,110)', 2, 10, 10);

-- CHECKPOINT EXPECTATION:
-- File Size: 200 lines (Charlie overwrites Alice and Bob; still the same).
-- Alice: 100 - 10 = 90 lines.
-- Bob: 100 - 10 = 90 lines.
-- Charlie: 10 + 10 = 20 lines.

SELECT 
    'CHECKPOINT B' as stage,
    e.name,
    m.lines_owned as actual_lines,
    CASE 
        WHEN e.name = 'Alice' THEN 90
        WHEN e.name = 'Bob' THEN 90
        WHEN e.name = 'Charlie' THEN 10
    END as expected_lines,
    ROUND((m.lines_owned_percentage * 100)::numeric, 2) as actual_pct,
    CASE 
        WHEN e.name = 'Alice' THEN 45
        WHEN e.name = 'Bob' THEN 45
        WHEN e.name = 'Charlie' THEN 10 -- 20/200
    END as expected_pct,
    f.line_count as file_lines,
    200 as expected_file_lines
FROM file_ownership_metrics m
JOIN engineers e ON m.engineer_id = e.id
JOIN files f ON m.file_id = f.id
WHERE m.file_id = 100
ORDER BY e.name;


-- ==========================================
-- TEST C: SELF-OVERWRITE (Refactoring)
-- Alice looks at her own 90 lines and optimizes them to 50 lines.
-- She deletes 40 of her own lines.
-- ==========================================
INSERT INTO commits (hash, repo_id, message) VALUES ('hash_refactor', 1, 'Alice Refactor');

INSERT INTO commit_hunks (commit_hash, file_id, engineer_id, line_range, overwritten_engineer_id, lines_added, lines_deleted)
VALUES ('hash_refactor', 100, 1, '[1,90)', 1, 50, 90);
-- Math:
-- Victim (Alice): -90 lines.
-- Author (Alice): +50 lines.
-- Net Change for Alice: -40 lines.
-- File Net Change: -40 lines.

-- CHECKPOINT EXPECTATION:
-- File Size: 200 - 40 = 160 lines.
-- Alice: 90 - 40 = 50 lines.

SELECT 
    'CHECKPOINT C' as stage,
    e.name,
    m.lines_owned as actual_lines,
    CASE 
        WHEN e.name = 'Alice' THEN 50
        WHEN e.name = 'Bob' THEN 90
        WHEN e.name = 'Charlie' THEN 10
    END as expected_lines,
    ROUND((m.lines_owned_percentage * 100)::numeric, 2) as actual_pct,
    CASE 
        WHEN e.name = 'Alice' THEN 31.25 -- 50/160
        WHEN e.name = 'Bob' THEN 56.25   -- 90/160
        WHEN e.name = 'Charlie' THEN 12.5 -- 20/160
    END as expected_pct,
    f.line_count as file_lines,
    160 as expected_file_lines
FROM file_ownership_metrics m
JOIN engineers e ON m.engineer_id = e.id
JOIN files f ON m.file_id = f.id
WHERE m.file_id = 100
ORDER BY e.name;

-- ==========================================
-- TEST D: Charlie overwrites + Add new lines
-- Charlie overwrites Alice and Bob (5 for Alice, 10 for Bob), and adds 5 new lines.
-- ==========================================
INSERT INTO commits (hash, repo_id, message) VALUES ('hash_overwrite_add', 1, 'Charlie Overwrite + Add');

INSERT INTO commit_hunks (commit_hash, file_id, engineer_id, line_range, overwritten_engineer_id, lines_added, lines_deleted)
VALUES ('hash_overwrite_add', 100, 3, '[1, 5)', 1, 5, 5),
       ('hash_overwrite_add', 100, 3, '[6, 15)', 2, 10, 10),
       ('hash_overwrite_add', 100, 3, '[160, 165)', 2, 5, 0);

-- CHECKPOINT EXPECTATION:
-- File Size: 160 + 5 = 165 lines.
-- Alice: 50 - 5 = 45 lines.
-- Bob: 90 - 10 = 80 lines.
-- Charlie: 20 + 5 + 10 + 5 = 40 lines.

SELECT 
    'CHECKPOINT D' as stage,
    e.name,
    m.lines_owned as actual_lines,
    CASE 
        WHEN e.name = 'Alice' THEN 45
        WHEN e.name = 'Bob' THEN 80
        WHEN e.name = 'Charlie' THEN 40
    END as expected_lines,
    ROUND((m.lines_owned_percentage * 100)::numeric, 2) as actual_pct,
    CASE 
        WHEN e.name = 'Alice' THEN 27.27 -- 45/165
        WHEN e.name = 'Bob' THEN 48.48   -- 80/165
        WHEN e.name = 'Charlie' THEN 24.24 -- 40/165
    END as expected_pct,
    f.line_count as file_lines,
    165 as expected_file_lines
FROM file_ownership_metrics m
JOIN engineers e ON m.engineer_id = e.id
JOIN files f ON m.file_id = f.id
WHERE m.file_id = 100
ORDER BY e.name;

ROLLBACK; -- Use COMMIT; if you want to keep the data