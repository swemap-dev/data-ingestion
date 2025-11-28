-- Define the Logic as a reusable View
-- This view calculates ownership arrays for ALL modules at once.

CREATE OR REPLACE VIEW module_ownership_summary AS
SELECT
   m.name AS module_name,
   
   -- 1. List Designers
   array_agg(e.name) FILTER (WHERE mc.interaction_type = 'DESIGNED') AS designers,

   -- 2. List Writers
   array_agg(e.name) FILTER (WHERE mc.interaction_type = 'WROTE') AS writers,

   -- 3. List Reviewers
   array_agg(e.name) FILTER (WHERE mc.interaction_type = 'REVIEWED') AS reviewers

FROM
   modules m
JOIN
   module_contributions mc ON m.id = mc.module_id
JOIN
   engineers e ON mc.engineer_id = e.id
GROUP BY
   m.name;

-- Filtering happened first due to push down