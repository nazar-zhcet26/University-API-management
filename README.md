# University Services API

A production-grade REST API platform for university digital services — built with FastAPI, PostgreSQL, Redis, Azure APIM, and an AI-powered library assistant using RAG.

---

## What's included

| Sprint | What was built |
|--------|---------------|
| 1 | OpenAPI 3.0 spec — 20 endpoints, 4 domains (Students, Courses, Library, Faculty) |
| 2 | FastAPI app — JWT auth, OAuth 2.0, RBAC (5 roles), rate limiting |
| 3 | Azure APIM — ARM template, 4 products, gateway policies, versioning governance |
| 4 | Database layer — async SQLAlchemy, Alembic migrations, Redis caching, pgvector |
| 5 | Observability — structured JSON logging, Prometheus metrics, health checks |
| 6 | CI/CD — GitHub Actions (test → build → deploy), full test suite |
| 7 | AI/ML — RAG library assistant, semantic search, streaming SSE responses |
| 8 | Capstone — governance document, Azure deployment guide |

---

## Quick start (local)

**Prerequisites:** Docker Desktop installed and running.

```bash
# 1. Clone and enter the project
git clone <your-repo-url>
cd university-api

# 2. Start everything (API + PostgreSQL + Redis)
docker-compose up

# 3. Apply migrations
docker-compose exec api alembic upgrade head

# 4. Seed test data
docker-compose exec api python scripts/seed.py

# 5. Open the API docs
open http://localhost:8000/docs
```

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
│   ├── core/           # config, database, security, logging, context
│   ├── models/         # SQLAlchemy ORM models
│   ├── schemas/        # Pydantic request/response schemas
│   ├── dependencies/   # FastAPI dependency injection (auth, RBAC)
│   ├── middleware/     # request logging, metrics, rate limiting
│   ├── routers/        # one file per domain
│   └── services/
│       ├── cache.py    # Redis cache service
│       └── ai/         # embeddings, semantic search, RAG assistant
├── alembic/            # database migrations
├── tests/              # unit + integration test suite
├── scripts/            # seed.py, index_books.py
├── infrastructure/
│   ├── apim/           # ARM template, gateway policies, versioning doc
│   └── azure/          # setup.sh — one-time Azure resource creation
├── .github/workflows/  # GitHub Actions CI/CD pipeline
├── Dockerfile
├── docker-compose.yml
└── openapi.yaml        # Sprint 1 API spec
```

---

## Running tests

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Unit tests only (no database needed)
pytest tests/unit/ -v

# Integration tests only
pytest tests/integration/ -v

# With coverage report
pytest --cov=app --cov-report=term-missing
```

---

## Environment variables

Create a `.env` file at the project root:

```env
# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/university_db

# Security
SECRET_KEY=your-random-secret-key-minimum-32-characters
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Redis
REDIS_URL=redis://localhost:6379/0

# Azure OpenAI (for library assistant)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o

# App
ENVIRONMENT=development
DEBUG=true
```

---

## Deploying to Azure

See `infrastructure/azure/DEPLOYMENT.md` for the complete step-by-step guide.

Short version:
```bash
# 1. Create Azure resources (one time)
chmod +x infrastructure/azure/setup.sh
./infrastructure/azure/setup.sh

# 2. Add GitHub secrets (printed at end of setup.sh)

# 3. Push to main — pipeline deploys automatically
git push origin main
```

---

## API domains

- `POST /v1/auth/login` — get JWT tokens
- `GET /v1/students` — student management
- `GET /v1/courses` — course catalog with Redis caching
- `GET /v1/books` — library catalog
- `POST /v1/borrowings` — book borrowing with business rules
- `POST /v1/assistant/chat` — AI library assistant
- `POST /v1/assistant/chat/stream` — streaming AI responses (SSE)
- `GET /v1/assistant/search` — semantic book search
- `GET /health/ready` — readiness probe (checks DB + Redis)
- `GET /metrics` — Prometheus metrics
