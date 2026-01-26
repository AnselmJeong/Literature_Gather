-- Citation Snowball SQLite Schema

-- Projects table
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    config JSON NOT NULL,
    current_iteration INTEGER DEFAULT 0,
    is_complete INTEGER DEFAULT 0
);

-- Papers table
CREATE TABLE IF NOT EXISTS papers (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    openalex_id TEXT NOT NULL,
    doi TEXT,
    pmid TEXT,
    title TEXT NOT NULL,
    authors JSON NOT NULL,
    publication_year INTEGER,
    journal TEXT,
    abstract TEXT,
    language TEXT,
    type TEXT,
    cited_by_count INTEGER DEFAULT 0,
    counts_by_year JSON,
    referenced_works JSON,

    -- Discovery metadata
    score REAL DEFAULT 0.0,
    score_components JSON,
    discovery_method TEXT CHECK(discovery_method IN ('seed', 'forward', 'backward', 'author', 'related')),
    discovered_from JSON,
    iteration_added INTEGER DEFAULT 0,

    -- Download status
    download_status TEXT DEFAULT 'pending' CHECK(download_status IN ('pending', 'success', 'failed', 'skipped')),
    local_path TEXT,
    oa_url TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(project_id, openalex_id)
);

-- Iterations table
CREATE TABLE IF NOT EXISTS iterations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    iteration_number INTEGER NOT NULL,
    started_at DATETIME,
    completed_at DATETIME,
    metrics JSON,

    UNIQUE(project_id, iteration_number)
);

-- API cache table
CREATE TABLE IF NOT EXISTS api_cache (
    cache_key TEXT PRIMARY KEY,
    response JSON NOT NULL,
    cached_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_papers_project ON papers(project_id);
CREATE INDEX IF NOT EXISTS idx_papers_openalex ON papers(openalex_id);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_score ON papers(project_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_papers_discovery ON papers(project_id, discovery_method);
CREATE INDEX IF NOT EXISTS idx_papers_iteration ON papers(project_id, iteration_added);
CREATE INDEX IF NOT EXISTS idx_iterations_project ON iterations(project_id);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON api_cache(expires_at);
