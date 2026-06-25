CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    name_normalized TEXT NOT NULL UNIQUE,
    ats_provider TEXT,
    ats_token TEXT,
    company_url TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    locations_json TEXT NOT NULL,
    url TEXT NOT NULL,
    ats_provider TEXT,
    ats_token TEXT,
    season TEXT,
    category TEXT,
    degrees_json TEXT,
    sponsorship TEXT,
    is_internship INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    posted_at INTEGER,
    updated_at INTEGER,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
    raw_payload TEXT NOT NULL,
    UNIQUE(source, source_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS idx_jobs_active ON jobs(active);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_at);
CREATE TABLE IF NOT EXISTS match_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    profile_version TEXT NOT NULL,
    resume_version TEXT NOT NULL,
    qualification_score INTEGER NOT NULL,
    fit_score INTEGER NOT NULL,
    class_year_eligible INTEGER NOT NULL,
    top_matches_json TEXT NOT NULL,
    top_gaps_json TEXT NOT NULL,
    fit_reasoning TEXT,
    summary TEXT,
    tier TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(job_id, profile_version, resume_version)
);

CREATE INDEX IF NOT EXISTS idx_scores_job ON match_scores(job_id);
CREATE INDEX IF NOT EXISTS idx_scores_qualification ON match_scores(qualification_score);
CREATE INDEX IF NOT EXISTS idx_scores_fit ON match_scores(fit_score);