DROP TABLE IF EXISTS engineers, repos, skills, modules, files, commits, reviews, module_contributions, file_contributions, module_skills, engineer_skills, file_dependencies CASCADE;

DROP TYPE IF EXISTS skill_type_enum, commit_type_enum, interaction_type_enum, dep_type_enum CASCADE;