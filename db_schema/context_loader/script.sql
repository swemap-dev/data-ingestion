-- Required Oracle: get overwritten_engineer_ids for this new commit

-- commit_hunks (commit_hash, file_id, line_range, overwritten_engineer_ids, lines_added, lines_deleted, engineer_id)
CREATE OR REPLACE FUNCTION update_ownership_metrics()
RETURNS TRIGGER AS $$
DECLARE
    victim_id INTEGER;
    new_total_lines INTEGER;
    net_change INTEGER;
BEGIN
    -- 1. CALCULATE NET CHANGE & UPDATE FILE TOTAL
    -- "Net Change" = (Lines Added) - (Lines Deleted)
    net_change := NEW.lines_added - NEW.lines_deleted;

    -- Update the master 'files' table and capture the new total size
    UPDATE files 
    SET line_count = COALESCE(line_count, 0) + net_change
    WHERE id = NEW.file_id
    RETURNING line_count INTO new_total_lines;

    -- Safety Check: If file is somehow empty or negative, force 1 to avoid DivisionByZero errors later
    -- (Though logically it should be 0, math-wise we want to avoid crashing)
    IF new_total_lines <= 0 THEN
        new_total_lines := 0; 
    END IF;

    -- 2. UPDATE RAW OWNERSHIP COUNTS (Your Original Logic)
    
    -- A. Penalize the "Victims"
    IF NEW.overwritten_engineer_ids IS NOT NULL THEN
        FOREACH victim_id IN ARRAY NEW.overwritten_engineer_ids
        LOOP
            UPDATE file_ownership_metrics 
            SET lines_owned = GREATEST(lines_owned - NEW.lines_deleted, 0) -- Safety: Prevent negative ownership
            WHERE engineer_id = victim_id 
              AND file_id = NEW.file_id;
        END LOOP;
    END IF;

    -- B. Reward the "Author"
    INSERT INTO file_ownership_metrics (file_id, engineer_id, lines_owned, commit_count)
    VALUES (NEW.file_id, NEW.engineer_id, NEW.lines_added, 1)
    ON CONFLICT (file_id, engineer_id)
    DO UPDATE SET 
        lines_owned = file_ownership_metrics.lines_owned + EXCLUDED.lines_owned,
        commit_count = file_ownership_metrics.commit_count + 1;

    -- 3. MASS UPDATE PERCENTAGES
    -- Because the "Pie" (new_total_lines) changed size, we must resize EVERY slice.
    IF new_total_lines > 0 THEN
        UPDATE file_ownership_metrics
        SET lines_owned_percentage = (lines_owned::DOUBLE PRECISION / new_total_lines)
        WHERE file_id = NEW.file_id;
    ELSE
        -- If file is empty, everyone owns 0%
        UPDATE file_ownership_metrics
        SET lines_owned_percentage = 0.0
        WHERE file_id = NEW.file_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Hook the trigger (No changes needed here, but included for completeness)
DROP TRIGGER IF EXISTS trigger_update_blame_metrics ON commit_hunks;
CREATE TRIGGER trigger_update_blame_metrics
AFTER INSERT ON commit_hunks
FOR EACH ROW
EXECUTE FUNCTION update_ownership_metrics();