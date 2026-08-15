-- Raw SQL schema — equivalent to app/db/migrations/versions/0001..0003 (SQLAlchemy/Alembic),
-- written without an ORM. Demonstrates the same normalized (3NF) design two ways, per the
-- Phase 2 requirement "Creation of db with and without ORM".
--
-- Usage: psql -U postgres -d project_mgmt -f sql/schema.sql

CREATE TABLE users (
    id              UUID PRIMARY KEY,
    login           VARCHAR(64) NOT NULL UNIQUE,
    hashed_password VARCHAR(128) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_users_login ON users (login);

CREATE TABLE projects (
    id                UUID PRIMARY KEY,
    name              VARCHAR(128) NOT NULL,
    description       TEXT,
    owner_id          UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    total_size_bytes  BIGINT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_projects_owner_id ON projects (owner_id);

CREATE TYPE project_role AS ENUM ('owner', 'participant');

CREATE TABLE project_members (
    id          UUID PRIMARY KEY,
    project_id  UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role        project_role NOT NULL,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_user UNIQUE (project_id, user_id)
);
CREATE INDEX ix_project_members_project_id ON project_members (project_id);
CREATE INDEX ix_project_members_user_id ON project_members (user_id);

CREATE TABLE documents (
    id              UUID PRIMARY KEY,
    project_id      UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    filename        VARCHAR(256) NOT NULL,
    s3_key          VARCHAR(512) NOT NULL UNIQUE,
    content_type    VARCHAR(128) NOT NULL,
    size_bytes      BIGINT NOT NULL,
    uploaded_by_id  UUID REFERENCES users (id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_documents_project_id ON documents (project_id);

CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked     BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_refresh_tokens_user_id ON refresh_tokens (user_id);

CREATE TABLE project_share_tokens (
    id             UUID PRIMARY KEY,
    project_id     UUID NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
    invited_email  VARCHAR(256) NOT NULL,
    token_hash     VARCHAR(64) NOT NULL UNIQUE,
    expires_at     TIMESTAMPTZ NOT NULL,
    used           BOOLEAN NOT NULL DEFAULT false,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_project_share_tokens_project_id ON project_share_tokens (project_id);

-- ── Denormalized read model (see docs/db-design.md for the tradeoff discussion) ──
-- Optional materialized view: precomputes per-project aggregates that would
-- otherwise require joining/aggregating project_members + documents on every
-- read of GET /projects. Trades storage + staleness for read speed.
CREATE MATERIALIZED VIEW project_summary AS
SELECT
    p.id                AS project_id,
    p.name,
    u.login             AS owner_login,
    p.total_size_bytes,
    COUNT(DISTINCT pm.user_id)  AS member_count,
    COUNT(DISTINCT d.id)        AS document_count
FROM projects p
JOIN users u ON u.id = p.owner_id
LEFT JOIN project_members pm ON pm.project_id = p.id
LEFT JOIN documents d ON d.project_id = p.id
GROUP BY p.id, p.name, u.login, p.total_size_bytes;

CREATE UNIQUE INDEX ix_project_summary_project_id ON project_summary (project_id);
-- Refresh strategy: REFRESH MATERIALIZED VIEW CONCURRENTLY project_summary;
-- (would be triggered from document_service.py / project_service.py after writes,
-- or on a schedule — not wired into the live app, kept as a documented example).
