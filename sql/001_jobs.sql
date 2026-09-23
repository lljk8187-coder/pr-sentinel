-- Phase2 M5: jobs archive in Postgres (no ORM / Alembic)
CREATE TABLE IF NOT EXISTS jobs (
    id            UUID PRIMARY KEY,
    delivery_id   TEXT UNIQUE NULL,
    owner         TEXT,
    repo          TEXT,
    pr            INT,
    sha           TEXT,
    status        TEXT,
    error         TEXT,
    arq_job_id    TEXT,
    payload       JSONB,
    findings      JSONB DEFAULT '[]'::jsonb,
    report_md     TEXT,
    check_run_id  BIGINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs (created_at DESC);
