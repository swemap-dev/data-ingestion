-- 1. Define the Logic as a View
-- This "saves" your complex math into a virtual table called 'module_risk_metrics'
CREATE OR REPLACE VIEW module_risk_metrics AS
WITH contribution_counts AS (
   SELECT
       m.name AS module_name, -- We keep the name so we can filter later
       COUNT(*) FILTER (WHERE mc.interaction_type = 'DESIGNED') AS num_designed,
       COUNT(*) FILTER (WHERE mc.interaction_type = 'WROTE') AS num_wrote,
       COUNT(*) FILTER (WHERE mc.interaction_type = 'REVIEWED') AS num_reviewed
   FROM
       modules m
   JOIN
       module_contributions mc ON m.id = mc.module_id
   GROUP BY
       m.name -- Calculate for every module found
),
s_calculation AS (
   SELECT
       module_name,
       (
           (0.50 * num_wrote) +
           (0.25 * num_designed) +
           (0.25 * num_reviewed)
       ) / 5.0 AS score_s
   FROM
       contribution_counts
)
SELECT
   module_name,
   CASE
       WHEN score_s = 0 THEN NULL
       ELSE 1.0 / score_s
   END AS risk_metric
FROM
   s_calculation;

-- main contributor (1): has a button to expand the full list:
-- list of top-5 contributors with >15% ownership
-- on-call: assigned (not included in the risk score)

-- Design with Blame in mind
-- Keep track of commits: use line chunks.
-- Blame has [start_line - end_line]; don't worry about performance for now.