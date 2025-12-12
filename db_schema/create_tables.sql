-- 1. Create Custom ENUM Types first
-- These limit columns to specific string values
CREATE TYPE skill_type_enum AS ENUM ('LANGUAGE', 'FRAMEWORK', 'TOOL', 'PLATFORM');
CREATE TYPE commit_type_enum AS ENUM ('COMMIT', 'PR');
CREATE TYPE interaction_type_enum AS ENUM ('DESIGNED', 'WROTE', 'REVIEWED');
CREATE TYPE dep_type_enum AS ENUM ('INTERNAL', 'EXTERNAL');

-- 2. Create Independent Tables (No Foreign Keys)

CREATE TABLE engineers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    team VARCHAR(100),
    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active TIMESTAMP,
    recs JSONB
);

CREATE TABLE repos (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    url VARCHAR(255),
    language VARCHAR(100),
    risk_score DOUBLE PRECISION,
    rec JSONB
);

CREATE TABLE skills (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    type skill_type_enum
);

-- 3. Create Dependent Tables (Reference the tables above)

CREATE TABLE modules (
    id SERIAL PRIMARY KEY,
    repo_id INTEGER REFERENCES repos(id) ON DELETE CASCADE,
    name VARCHAR(255),
    dir_path VARCHAR(512),
    description TEXT,
    risk_score DOUBLE PRECISION,
    time_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_update TIMESTAMP,
    recs JSONB
);

CREATE TABLE files (
    id SERIAL PRIMARY KEY,
    module_id INTEGER REFERENCES modules(id) ON DELETE CASCADE,
    file_path VARCHAR(512) NOT NULL,
    checksum VARCHAR(255), -- Useful for detecting changes
    line_count INTEGER,
    ast_summary JSONB      -- Great usage of JSONB for cached analysis
);

CREATE TABLE commits (
    hash TEXT PRIMARY KEY, -- Git hashes are strings, not integers
    repo_id INTEGER REFERENCES repos(id) ON DELETE CASCADE,
    file_id INTEGER REFERENCES files(id) ON DELETE SET NULL, -- See note below
    type commit_type_enum,
    timestamp TIMESTAMP,
    message TEXT
);

CREATE TABLE reviews (
    id SERIAL PRIMARY KEY,
    engineer_id INTEGER REFERENCES engineers(id) ON DELETE SET NULL,
    lines INTEGER,
    file_path VARCHAR(512),
    message TEXT
);

-- 4. Create Join Tables (Many-to-Many relationships)
-- These use Composite Primary Keys (two columns make the row unique)

CREATE TABLE module_contributions (
    engineer_id INTEGER REFERENCES engineers(id) ON DELETE CASCADE,
    module_id INTEGER REFERENCES modules(id) ON DELETE CASCADE,
    interaction_type interaction_type_enum,
    PRIMARY KEY (engineer_id, module_id, interaction_type)
);

CREATE TABLE file_contributions (
    engineer_id INTEGER REFERENCES engineers(id) ON DELETE CASCADE,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    interaction_type interaction_type_enum,
    PRIMARY KEY (engineer_id, file_id, interaction_type)
);

CREATE TABLE module_skills (
    module_id INTEGER REFERENCES modules(id) ON DELETE CASCADE,
    skill_id INTEGER REFERENCES skills(id) ON DELETE CASCADE,
    score DOUBLE PRECISION,
    PRIMARY KEY (module_id, skill_id)
);

CREATE TABLE engineer_skills (
    engineer_id INTEGER REFERENCES engineers(id) ON DELETE CASCADE,
    skill_id INTEGER REFERENCES skills(id) ON DELETE CASCADE,
    score DOUBLE PRECISION,
    last_used TIMESTAMP,
    PRIMARY KEY (engineer_id, skill_id)
);

CREATE TABLE file_dependencies (
    id SERIAL PRIMARY KEY,
    importer_file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    resolved_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
    -- Note: external_package_id table was not defined in diagram, so storing as generic INT for now
    external_package_id INTEGER, 
    dependency_type dep_type_enum,
    raw_import_statement VARCHAR(512)
);

-- The "Hunk" table now acts purely as a metadata pointer
CREATE TABLE commit_hunks (
    id SERIAL PRIMARY KEY,
    commit_hash TEXT REFERENCES commits(hash) ON DELETE CASCADE,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    engineer_id INTEGER REFERENCES engineers(id) ON DELETE CASCADE,
    
    -- The critical metadata: "The code of interest is between lines 20 and 50"
    line_range int4range NOT NULL, 
    
    -- Who lost code? (For ownership calculation)
    overwritten_engineer_id INTEGER, 
    
    -- Stats
    lines_added INTEGER,
    lines_deleted INTEGER
);

-- The Ownership Cache (Snapshot)
-- Running tally that we update after every commit.
CREATE TABLE file_ownership_metrics (
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    engineer_id INTEGER REFERENCES engineers(id) ON DELETE CASCADE,
    
    -- The Net Line Count (Current Ownership)
    -- Logic: If I overwrite 5 of your lines with 5 of mine:
    -- You: -5, Me: +5
    lines_owned INTEGER DEFAULT 0,
    lines_owned_percentage DOUBLE PRECISION,
    
    -- The "Influence" Score (Optional for ML)
    -- How many times has this person touched this file?
    commit_count INTEGER DEFAULT 0,
    
    PRIMARY KEY (file_id, engineer_id)
);

-- Create Indexes for performance
CREATE INDEX idx_contributions_module_id
ON module_contributions(module_id, interaction_type);

CREATE INDEX idx_modules_name ON modules(name);