CREATE OR REPLACE FUNCTION update_ownership_metrics()
RETURNS TRIGGER AS $$
DECLARE
    victim_id INTEGER;
BEGIN
    -- 1. Penalize the "Victims" (Bob, or in this case, Math Person A)
    IF NEW.overwritten_engineer_ids IS NOT NULL THEN
        FOREACH victim_id IN ARRAY NEW.overwritten_engineer_ids
        LOOP
            UPDATE file_ownership_metrics 
            SET lines_owned = lines_owned - NEW.lines_deleted
            WHERE engineer_id = victim_id 
              AND file_id = NEW.file_id;
        END LOOP;
    END IF;

    -- 2. Reward the "Author" (Alice/Math Person B & C)
    -- This assumes you have added the 'engineer_id' column to commit_hunks as discussed
    INSERT INTO file_ownership_metrics (file_id, engineer_id, lines_owned, commit_count)
    VALUES (NEW.file_id, NEW.engineer_id, NEW.lines_added, 1)
    ON CONFLICT (file_id, engineer_id) 
    DO UPDATE SET 
        lines_owned = file_ownership_metrics.lines_owned + EXCLUDED.lines_owned,
        commit_count = file_ownership_metrics.commit_count + 1;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Hook the trigger
DROP TRIGGER IF EXISTS trigger_update_blame_metrics ON commit_hunks;
CREATE TRIGGER trigger_update_blame_metrics
AFTER INSERT ON commit_hunks
FOR EACH ROW
EXECUTE FUNCTION update_ownership_metrics();