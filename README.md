# University Services API

A production-grade REST API platform for university digital services — built with FastAPI, PostgreSQL, Redis, Azure APIM, and an AI-powered library assistant using RAG.

---

## What's included

| Sprint | What was built |
|--------|----------------|
| 1 | OpenAPI 3.0 spec — 49 endpoints across 9 domains |
| 2 | FastAPI app — JWT auth, OAuth 2.0, RBAC (5 roles), rate limiting |
| 3 | Azure APIM — ARM template, 4 products, gateway policies, versioning governance |
| 4 | Database layer — async SQLAlchemy, Alembic migrations, Redis caching, pgvector |
| 5 | Observability — structured JSON logging, Prometheus metrics, health checks |
| 6 | CI/CD — GitHub Actions (test → build → deploy), full test suite |
| 7 | AI/ML — RAG library assistant, semantic search, streaming SSE responses |
| 8 | Capstone — API governance document, Azure deployment architecture |
| 9 | API Keys + UAE Gov — X-API-Key auth, key rotation, UAE MOEHE reporting endpoints |

---

## Quick start (local)

**Prerequisites:** Docker Desktop installed and running.

```bash
# 1. Clone and enter the project
git clone https://github.com/nazar-zhcet26/University-API-management.git
cd University-API-management

# 2. Create your .env file (see Environment Variables section below)

# 3. Start everything (API + PostgreSQL + Redis)
docker compose up --build -d

# 4. Seed test data
docker compose exec api python scripts/seed.py

# 5. Open the admin dashboard
open http://localhost:8000/admin

# 6. Or open the Swagger docs
open http://localhost:8000/docs
```

> Migrations run automatically on startup via `start.sh`. No manual `alembic upgrade head` needed.

**Test credentials after seeding:**

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@university.ac.ae | Admin@1234 |
| Student | student1@university.ac.ae | Student@1234 |
| Faculty | faculty1@university.ac.ae | Faculty@1234 |
| Librarian | librarian@university.ac.ae | Librarian@1234 |

---

## Project structure

```
university-api/
├── app/
│   ├── core/               # config, database, security, logging, context
│   ├── models/
│   │   ├── models.py       # all SQLAlchemy ORM models
│   │   └── api_key.py      # API key model (Sprint 9)
│   ├── schemas/
│   │   ├── schemas.py      # all Pydantic request/response schemas
│   │   └── api_key.py      # API key schemas (Sprint 9)
│   ├── dependencies/       # FastAPI dependency injection (auth, RBAC)
│   ├── middleware/
│   │   ├── logging.py      # structured request logging
│   │   ├── metrics.py      # Prometheus metrics collection
│   │   ├── rate_limit.py   # SlowAPI rate limiting
│   │   └── api_key_auth.py # X-API-Key validation (Sprint 9)
│   ├── routers/
│   │   ├── auth.py         # login, refresh
│   │   ├── students.py     # student CRUD
│   │   ├── courses.py      # course catalog + enrollments
│   │   ├── library.py      # books + borrowings
│   │   ├── assistant.py    # RAG AI assistant
│   │   ├── health.py       # liveness + readiness probes
│   │   ├── api_keys.py     # API key management (Sprint 9)
│   │   └── gov.py          # UAE MOEHE reporting endpoints (Sprint 9)
│   └── services/
│       ├── cache.py        # Redis cache service
│       └── ai/             # embeddings, semantic search, RAG assistant
├── alembic/                # database migrations (001, 002, 003)
├── tests/                  # unit + integration test suite
├── scripts/                # seed.py, index_books.py
├── infrastructure/
│   ├── apim/               # ARM template, gateway policies, versioning doc
│   └── azure/              # setup.sh — one-time Azure resource creation
├── start.sh                # production entrypoint (migrations + uvicorn)
├── Dockerfile
├── docker-compose.yml      # local development only
└── openapi.yaml            # full API spec (all 49 endpoints)
```

---

## API domains

### Core
- `POST /v1/auth/login` — get JWT tokens
- `POST /v1/auth/refresh` — refresh access token

### Students
- `GET/POST /v1/students` — list and create students
- `GET/PUT/PATCH/DELETE /v1/students/{id}` — manage individual students
- `GET /v1/students/{id}/enrollments` — student's course enrollments
- `GET /v1/students/{id}/borrowings` — student's borrowing history

### Courses
- `GET/POST /v1/courses` — course catalog with Redis caching
- `GET/PATCH/DELETE /v1/courses/{id}` — manage individual courses
- `POST /v1/courses/{id}/enrollments` — enroll a student
- `DELETE /v1/courses/{id}/enrollments/{enrollment_id}` — drop enrollment

### Library
- `GET/POST /v1/books` — book catalog
- `GET/PATCH/DELETE /v1/books/{id}` — manage individual books
- `GET/POST /v1/borrowings` — borrowing management
- `PATCH /v1/borrowings/{id}` — update borrowing status

### AI Library Assistant
- `POST /v1/assistant/chat` — RAG chat (complete response)
- `POST /v1/assistant/chat/stream` — RAG chat (streaming SSE)
- `GET /v1/assistant/search` — semantic book search (pgvector)
- `POST /v1/assistant/books/{id}/index` — index book into vector store

### API Keys (Sprint 9)
- `POST /v1/api-keys` — create API key (admin only)
- `GET /v1/api-keys` — list all keys (admin only)
- `PATCH /v1/api-keys/{id}` — update key metadata
- `DELETE /v1/api-keys/{id}` — revoke key
- `POST /v1/api-keys/{id}/rotate` — rotate key, invalidate old

### UAE Government Reporting (Sprint 9)
- `GET /v1/gov/students` — student roster in UAE MOEHE format
- `GET /v1/gov/enrollment-stats` — aggregated enrollment statistics
- `GET /v1/gov/programs` — program catalog with NQF levels

> Gov endpoints require `X-API-Key` header with `service` role. JWT Bearer tokens are rejected.

### Observability
- `GET /health/live` — liveness probe
- `GET /health/ready` — readiness probe (checks DB + Redis)
- `GET /metrics` — Prometheus-format metrics

---

## Authentication

### JWT (most endpoints)
```
POST /v1/auth/login → { access_token, refresh_token }
Authorization: Bearer <access_token>
```

### API Key (gov endpoints + machine-to-machine)
```
POST /v1/api-keys → { key: "uak_..." }  ← shown once, store it
X-API-Key: uak_your_key_here
```

---

## Running tests

```bash
# Run all tests
docker compose exec api pytest

# Unit tests only (no database needed)
docker compose exec api pytest tests/unit/ -v

# Integration tests only
docker compose exec api pytest tests/integration/ -v

# With coverage report
docker compose exec api pytest --cov=app --cov-report=term-missing
```

---

## Environment variables

Create a `.env` file at the project root (never commit this file):

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/university_db

# Security
SECRET_KEY=your-random-secret-key-minimum-32-characters
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7

# Redis
REDIS_URL=redis://redis:6379/0

# Azure OpenAI (for library assistant)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o

# App
ENVIRONMENT=development
DEBUG=true
```

---

## Deploying to Railway

1. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
2. Add PostgreSQL plugin → copy `DATABASE_URL`
3. Add Redis plugin → copy `REDIS_URL`
4. Set environment variables in Railway dashboard (see above)
5. Deploy — migrations run automatically on startup

---

## Deploying to Azure

See `infrastructure/azure/DEPLOYMENT.md` for the complete step-by-step guide.

```bash
# 1. Create Azure resources (one time)
chmod +x infrastructure/azure/setup.sh
./infrastructure/azure/setup.sh

# 2. Add GitHub secrets (printed at end of setup.sh)

# 3. Push to main — pipeline deploys automatically
git push origin main
```