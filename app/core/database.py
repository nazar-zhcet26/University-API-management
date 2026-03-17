"""
core/database.py
----------------
Async database setup using SQLAlchemy 2.0 with asyncpg.

Why async?
Your API will handle many concurrent requests. If each request
blocks a thread waiting for a database query, you quickly run out of
threads. Async DB access means a request can "pause" while waiting
for the DB, freeing the event loop to handle other requests.
This is why FastAPI + asyncpg is the standard for high-performance APIs.

Why SQLAlchemy ORM?
- You write Python classes instead of raw SQL
- It handles SQL injection prevention automatically
- Database migrations with Alembic (Sprint 4)
- Easy to swap databases (PostgreSQL in prod, SQLite in tests)

Connection Pooling:
A "pool" is a set of pre-established database connections that are
reused across requests. Opening a new DB connection is expensive (~100ms).
With pooling, you grab an existing connection from the pool (microseconds),
use it, and return it. pool_size=10 means max 10 simultaneous connections.
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings

settings = get_settings()

# ── Engine ────────────────────────────────────────────────────────────────────
# The engine manages the connection pool.
# echo=True logs SQL statements — useful in dev, turn off in production.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,           # keep 10 connections open
    max_overflow=20,        # allow up to 20 more if pool is exhausted
    pool_pre_ping=True,     # test connections before using them (handles DB restarts)
)

# ── Session Factory ───────────────────────────────────────────────────────────
# AsyncSession is used to execute queries.
# expire_on_commit=False means objects stay usable after commit
# (important for async — you might access attributes after the session closes)
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Base Class for All Models ─────────────────────────────────────────────────
# All SQLAlchemy models inherit from this.
# It gives them the mapping machinery (table name, column definitions etc.)
class Base(DeclarativeBase):
    pass


# ── Dependency: Get DB Session ────────────────────────────────────────────────
async def get_db() -> AsyncSession:
    """
    FastAPI dependency that provides a database session per request.
    
    The 'async with' pattern ensures:
    - Session is created at the start of the request
    - Session is committed (or rolled back on error) at the end
    - Session is always closed, even if an exception is raised
    
    This is the 'Unit of Work' pattern — one session per request,
    all DB operations in that request share one transaction.
    
    Usage in a router:
        async def get_student(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
