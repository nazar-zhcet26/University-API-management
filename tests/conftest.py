"""
tests/conftest.py
-----------------
Shared pytest fixtures used across all tests.

conftest.py is a special pytest file — fixtures defined here are
automatically available to ALL test files without importing them.

Key fixtures we define:

  settings      → test-specific config (in-memory SQLite, fake Redis URL)
  engine        → async SQLAlchemy engine pointed at test database
  db_session    → fresh database session per test, rolled back after
  client        → FastAPI test client that makes real HTTP requests
  auth_headers  → pre-built Authorization headers for each role

The database pattern:
  Each test gets a fresh database state. We use transactions —
  each test runs inside a transaction that gets ROLLED BACK at the end.
  This means tests don't affect each other, and we don't need to
  clean up test data manually.

Why not use SQLite for tests?
  We DO use PostgreSQL for integration tests because:
  - SQLite doesn't support ARRAY types (we use those for specializations)
  - SQLite doesn't support our ENUM types properly
  - You want tests to run against the same database engine as production
  
  For unit tests (no DB), we don't need a database at all.
"""

import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base, get_db
from app.core.security import hash_password, create_access_token
from app.main import app
from app.models.models import User, Program, Student, Faculty


# ── Test Settings Override ─────────────────────────────────────────────────────
# Override settings for test environment
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"


@pytest.fixture(scope="session")
def event_loop():
    """
    Create a single event loop for the entire test session.
    pytest-asyncio needs this for async fixtures.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# ── Database Fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """
    Create the test database engine once per session.
    StaticPool means all connections share the same in-memory database.
    check_same_thread=False is required for SQLite in async context.
    """
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables after session ends
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    Fresh database session for each test.
    Uses nested transactions (savepoints) so each test starts clean.

    How it works:
    1. Begin an outer transaction
    2. Begin a savepoint (nested transaction)
    3. Run the test inside the savepoint
    4. Roll back the savepoint → test data is gone
    5. Roll back the outer transaction
    → Next test starts with clean state
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        await conn.begin_nested()  # savepoint

        session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        async with session_factory() as session:
            yield session

        await conn.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP test client.

    Overrides the get_db dependency to use our test session.
    This means every HTTP request in tests uses the test database
    that gets rolled back after each test.
    """
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Test Data Fixtures ─────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def test_program(db_session: AsyncSession) -> Program:
    """A program to use in tests."""
    program = Program(
        code="TEST-CS",
        name="Test Computer Science Program",
        department="computer_science",
        duration_years=4,
    )
    db_session.add(program)
    await db_session.flush()
    return program


@pytest_asyncio.fixture
async def test_student(db_session: AsyncSession, test_program: Program) -> Student:
    """A student to use in tests."""
    from datetime import date
    student = Student(
        first_name="Test",
        last_name="Student",
        email="test.student@university.ac.ae",
        date_of_birth=date(2000, 1, 1),
        program_id=test_program.id,
        enrollment_year=2024,
        status="active",
    )
    db_session.add(student)
    await db_session.flush()
    return student


@pytest_asyncio.fixture
async def test_faculty(db_session: AsyncSession) -> Faculty:
    """A faculty member to use in tests."""
    faculty = Faculty(
        first_name="Test",
        last_name="Faculty",
        email="test.faculty@university.ac.ae",
        department="computer_science",
        title="Lecturer",
    )
    db_session.add(faculty)
    await db_session.flush()
    return faculty


@pytest_asyncio.fixture
async def test_admin_user(db_session: AsyncSession) -> User:
    """An admin user for auth tests."""
    user = User(
        email="admin@test.ac.ae",
        hashed_password=hash_password("Admin@1234"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_student_user(db_session: AsyncSession, test_student: Student) -> User:
    """A student user linked to test_student."""
    user = User(
        email="student@test.ac.ae",
        hashed_password=hash_password("Student@1234"),
        role="student",
        is_active=True,
        student_id=test_student.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ── Auth Header Fixtures ───────────────────────────────────────────────────────
# Pre-built headers — use these in tests instead of calling /auth/login
# Faster than a real login flow and doesn't depend on the auth endpoint working

@pytest.fixture
def admin_headers(test_admin_user: User) -> dict:
    """Authorization headers for admin role."""
    token = create_access_token(subject=test_admin_user.id, role="admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def student_headers(test_student_user: User) -> dict:
    """Authorization headers for student role."""
    token = create_access_token(subject=test_student_user.id, role="student")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def librarian_headers() -> dict:
    """Authorization headers for librarian role."""
    token = create_access_token(subject="lib_001", role="librarian")
    return {"Authorization": f"Bearer {token}"}
