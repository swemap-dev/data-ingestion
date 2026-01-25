-- 1. Import your Logic/Schema file
-- Note: The path is relative to where you run psql from.
\i db_schema/module_risk/script.sql

BEGIN;

-- 2. Setup Test Data (The exact same setup as before)
INSERT INTO repos (name, url, language) VALUES ('calc-repo', 'http://test', 'Python');

INSERT INTO modules (repo_id, name, dir_path)
VALUES ((SELECT id FROM repos WHERE name = 'calc-repo'), 'RiskModule', '/src/risk');

INSERT INTO engineers (name, email) VALUES 
    ('Math Person A', 'a@calc.test'),
    ('Math Person B', 'b@calc.test'),
    ('Math Person C', 'c@calc.test');

-- Person A (D=1, R=1)
INSERT INTO module_contributions (engineer_id, module_id, interaction_type)
VALUES 
    ((SELECT id FROM engineers WHERE email='a@calc.test'), (SELECT id FROM modules WHERE name='RiskModule'), 'DESIGNED'),
    ((SELECT id FROM engineers WHERE email='a@calc.test'), (SELECT id FROM modules WHERE name='RiskModule'), 'REVIEWED');

-- Person B (D=1->Total 2, R=1->Total 2)
INSERT INTO module_contributions (engineer_id, module_id, interaction_type)
VALUES 
    ((SELECT id FROM engineers WHERE email='b@calc.test'), (SELECT id FROM modules WHERE name='RiskModule'), 'DESIGNED'),
    ((SELECT id FROM engineers WHERE email='b@calc.test'), (SELECT id FROM modules WHERE name='RiskModule'), 'REVIEWED');

-- Person C (W=1->Total 1, R=1->Total 3)
INSERT INTO module_contributions (engineer_id, module_id, interaction_type)
VALUES 
    ((SELECT id FROM engineers WHERE email='c@calc.test'), (SELECT id FROM modules WHERE name='RiskModule'), 'WROTE'),
    ((SELECT id FROM engineers WHERE email='c@calc.test'), (SELECT id FROM modules WHERE name='RiskModule'), 'REVIEWED');


-- 3. Run the Test
-- Notice how clean this part is now! We just query the View.
SELECT 
    risk_metric, 
    2.7027 AS expected
FROM 
    module_risk_metrics 
WHERE 
    module_name = 'RiskModule';

ROLLBACK;