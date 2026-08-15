# Project Management Dashboard

A production-grade project management API 

## Stack
- **FastAPI** — async REST API
- **PostgreSQL** + **SQLAlchemy 2.0** (async) — relational storage
- **AWS S3** — document storage (docx, pdf)
- **AWS Lambda** — file size aggregation + project storage limit enforcement
- **Docker Compose** — local dev orchestration
- **GitHub Actions** — lint → test → build → push → deploy CI/CD
- **JWT (HS256)** — 1-hour access tokens, role-based (owner / participant)
- **Pydantic v2** — full request/response validation

## Features
- User registration & login with hashed passwords (bcrypt)
- Project CRUD with owner-only delete
- Document upload/download via S3 presigned URLs
- Invite users to projects (owner-only), granting participant access
- AWS Lambda triggered on S3 events: sums file sizes, enforces 100MB project limit
- Full test suite (pytest-asyncio + moto for AWS mocking)
- CI/CD: lint (ruff), type-check (mypy), test, Docker build & push, deploy

## Quick Start
```bash
cp .env.example .env   # fill in your values
docker compose up --build
# API at http://localhost:8000
# Docs at http://localhost:8000/docs
```

By default `docker compose up` targets real AWS (S3 bucket + Lambda) using the
credentials in `.env`. For local dev against LocalStack instead, layer the
overlay file:
```bash
docker compose -f docker-compose.yml -f docker-compose.localstack.yml up --build
```

## API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/register` | Register user |
| POST | `/api/v1/auth/login` | Login → JWT |
| POST | `/api/v1/projects` | Create project |
| GET | `/api/v1/projects` | List accessible projects |
| GET | `/api/v1/projects/{id}/info` | Project details |
| PUT | `/api/v1/projects/{id}/info` | Update project |
| DELETE | `/api/v1/projects/{id}` | Delete project (owner only) |
| GET | `/api/v1/projects/{id}/documents` | List documents |
| POST | `/api/v1/projects/{id}/documents` | Upload document(s) |
| GET | `/api/v1/documents/{id}` | Download document |
| PUT | `/api/v1/documents/{id}` | Update document |
| DELETE | `/api/v1/documents/{id}` | Delete document |
| POST | `/api/v1/projects/{id}/invite` | Invite user (owner only) |
| GET | `/api/v1/projects/{id}/share?with=<email>` | Generate hashed join link, email it (owner only, optional) |
| GET | `/api/v1/join?token=<token>` | Redeem a share join link → participant access |
| GET | `/api/v1/projects/{id}/storage` | Storage usage vs. project limit |

## Database design

See [docs/db-design.md](docs/db-design.md) for the normalization rationale, a documented
denormalized read-model example (`sql/schema.sql`), and the raw-SQL schema (no ORM) alongside
the SQLAlchemy/Alembic one.
