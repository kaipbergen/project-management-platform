# Database design: normalization, denormalization, ORM vs. raw SQL

## Normalized schema (current, 3NF)

The live schema (`app/models/models.py`, applied via `app/db/migrations/`) is normalized to
3rd normal form:

- `users` — no repeating groups, all attributes depend only on `id` (1NF/2NF).
- `projects` — `owner_id` is a foreign key, not a duplicated `owner_login` string, so renaming
  a user's login never requires touching every project row (3NF: no transitive dependency on
  a non-key attribute).
- `project_members` — a pure junction table resolving the users↔projects many-to-many
  relationship, carrying only the relationship's own attributes (`role`, `joined_at`).
- `documents` — belongs to exactly one project via `project_id`; `size_bytes`/`content_type`
  live once per document, never duplicated onto `projects`.
- `refresh_tokens` / `project_share_tokens` — token material kept in dedicated tables (only a
  SHA-256 hash is stored, never the raw token) rather than bolted onto `users`/`projects`.

This avoids update/delete anomalies: e.g. deleting a project's last document can't
accidentally lose project metadata, and renaming a project doesn't touch document rows.

## Denormalized variant (read-optimized)

`GET /projects` (list all accessible projects) is the app's hottest read path and, normalized,
requires joining `projects` → `users` (owner login) → `project_members` (count) →
`documents` (count/size) on every request. `sql/schema.sql` includes a denormalized
alternative — a materialized view `project_summary` that precomputes:

```sql
project_id, name, owner_login, total_size_bytes, member_count, document_count
```

**Tradeoff:** reads become a single index lookup instead of a 3-way join, at the cost of
storage duplication (`owner_login` is now stored twice) and staleness — the view only reflects
reality after a `REFRESH MATERIALIZED VIEW`, which the live app does not currently trigger
automatically. For this project's actual scale (a lab/demo dataset), the normalized query is
already fast enough, so the materialized view is kept as a documented example rather than
wired into `project_service.py` — normalizing first and denormalizing only for a *measured*
hot path is the right default.

`projects.total_size_bytes` on the normalized schema itself is technically a denormalized,
cached aggregate too (it duplicates `SUM(documents.size_bytes)`), justified by the same
tradeoff: the storage-limit check on every upload would otherwise need to re-sum all of a
project's documents synchronously. It's kept in sync at write time
(`document_service.py`) and reconciled asynchronously by the S3-triggered Lambda
(`lambda/file_size_calculator.py`), which is the standard "cache + async reconciliation"
pattern for a denormalized counter.

## Schema creation with and without an ORM

Both are equivalent and versioned in this repo:

| Approach | Location | Notes |
|---|---|---|
| With ORM | `app/models/models.py` (SQLAlchemy 2.0 `Mapped`/`mapped_column`) + `app/db/migrations/versions/000{1,2,3}_*.py` (Alembic) | Source of truth for the running app; `alembic upgrade head` applies it. |
| Without ORM | `sql/schema.sql` | Plain DDL, run directly via `psql -f sql/schema.sql`. Same tables, constraints, indexes — hand-written, no SQLAlchemy/Alembic involved. |

The ORM path is what the app actually runs against (`app/db/session.py`); the raw-SQL path
exists to satisfy — and demonstrate — the "creation of db with and without ORM" requirement
without maintaining two divergent schemas long-term.
