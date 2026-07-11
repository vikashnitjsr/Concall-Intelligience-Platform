-- Reference DDL for the Concall Intelligence Platform.
-- The application creates tables via SQLAlchemy (app/db.py::init_db); this file
-- documents the schema and is a starting point for Alembic migrations / pgvector.
-- Enable pgvector in Postgres:  CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE company (
    id       SERIAL PRIMARY KEY,
    ticker   VARCHAR(32) UNIQUE NOT NULL,
    name     VARCHAR(256) NOT NULL,
    sector   VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE transcript (
    id            SERIAL PRIMARY KEY,
    company_id    INT REFERENCES company(id),
    fiscal_year   INT NOT NULL,
    quarter       INT NOT NULL,
    call_date     TIMESTAMPTZ,
    source_blob   VARCHAR(512),
    content_hash  VARCHAR(64) NOT NULL,
    raw_text      TEXT,
    status        VARCHAR(32) DEFAULT 'uploaded',
    created_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE (company_id, fiscal_year, quarter)
);

-- Optional: chunk-level embeddings for semantic search / RAG.
-- CREATE TABLE transcript_chunk (
--     id SERIAL PRIMARY KEY,
--     transcript_id INT REFERENCES transcript(id),
--     section VARCHAR(64), speaker_role VARCHAR(32), seq INT,
--     text TEXT, embedding vector(1536)
-- );

CREATE TABLE metric (
    id            SERIAL PRIMARY KEY,
    transcript_id INT REFERENCES transcript(id),
    name          VARCHAR(128) NOT NULL,
    value_numeric DOUBLE PRECISION,
    unit          VARCHAR(32),
    yoy_pct       DOUBLE PRECISION,
    qoq_pct       DOUBLE PRECISION,
    raw_quote     TEXT
);

CREATE TABLE guidance (
    id                     SERIAL PRIMARY KEY,
    company_id             INT REFERENCES company(id),
    source_transcript_id   INT REFERENCES transcript(id),
    category               VARCHAR(64),
    metric_name            VARCHAR(128),
    direction              VARCHAR(16),
    target_value           DOUBLE PRECISION,
    target_unit            VARCHAR(32),
    target_period_ordinal  INT NOT NULL,
    raw_quote              TEXT NOT NULL,
    confidence             DOUBLE PRECISION DEFAULT 0.5,
    created_period_ordinal INT NOT NULL,
    status                 VARCHAR(16) DEFAULT 'open'
);

CREATE TABLE guidance_outcome (
    id                     SERIAL PRIMARY KEY,
    guidance_id            INT REFERENCES guidance(id),
    resolved_transcript_id INT REFERENCES transcript(id),
    resolved_period_ordinal INT NOT NULL,
    actual_value           DOUBLE PRECISION,
    status                 VARCHAR(16) NOT NULL,
    variance_pct           DOUBLE PRECISION,
    evidence_quote         TEXT
);

CREATE TABLE red_flag (
    id            SERIAL PRIMARY KEY,
    transcript_id INT REFERENCES transcript(id),
    type          VARCHAR(64),
    severity      VARCHAR(16),
    description   TEXT,
    raw_quote     TEXT
);

CREATE TABLE section_score (
    id                  SERIAL PRIMARY KEY,
    company_id          INT REFERENCES company(id),
    as_of_period_ordinal INT NOT NULL,
    section_no          INT NOT NULL,
    section_name        VARCHAR(64),
    score_0_10          DOUBLE PRECISION,
    rationale           TEXT
);

CREATE TABLE company_score (
    id                        SERIAL PRIMARY KEY,
    company_id                INT REFERENCES company(id),
    as_of_period_ordinal      INT NOT NULL,
    total_0_100               DOUBLE PRECISION,
    decision_band             VARCHAR(32),
    growth_score              DOUBLE PRECISION DEFAULT 0,
    aggression_score          DOUBLE PRECISION DEFAULT 0,
    consistency_score         DOUBLE PRECISION DEFAULT 0,
    guidance_reliability_score DOUBLE PRECISION DEFAULT 0,
    composite                 DOUBLE PRECISION DEFAULT 0,
    UNIQUE (company_id, as_of_period_ordinal)
);

CREATE TABLE research_sheet (
    id                   SERIAL PRIMARY KEY,
    company_id           INT REFERENCES company(id),
    as_of_period_ordinal INT NOT NULL,
    market_cap           VARCHAR(64),
    business_summary     TEXT,
    revenue_cagr_5y      DOUBLE PRECISION,
    pat_eps_cagr_5y      DOUBLE PRECISION,
    roe                  DOUBLE PRECISION,
    roce                 DOUBLE PRECISION,
    debt_equity          DOUBLE PRECISION,
    interest_coverage    DOUBLE PRECISION,
    moat_notes           TEXT,
    mgmt_notes           TEXT,
    industry_notes       TEXT,
    valuation_view       TEXT,
    key_red_flags        TEXT,
    final_thesis         TEXT,
    decision             VARCHAR(16),
    UNIQUE (company_id, as_of_period_ordinal)
);
