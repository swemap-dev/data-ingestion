DROP TRIGGER IF EXISTS trigger_update_blame_metrics ON commit_hunks CASCADE;
DROP TABLE IF EXISTS engineers, repos, skills, modules, files, commits, reviews, module_contributions, file_contributions, module_skills, engineer_skills, file_dependencies, commit_hunks, file_ownership_metrics CASCADE;
DROP TYPE IF EXISTS skill_type_enum, commit_type_enum, interaction_type_enum, dep_type_enum CASCADE;