"""
models/models.py
----------------
SQLAlchemy ORM models — these define your database tables.

Key principle: these are NOT the same as your API schemas (Pydantic models).
Models = database shape. Schemas = API shape.

For example:
- The User model has a 'hashed_password' column — never exposed via API
- The Student schema has no password field — that's an API concern, not a DB concern

Relationship to our OpenAPI spec:
These tables back the endpoints we defined in Sprint 1.
student_id in the Enrollment table is a foreign key to students.id —
this is how we enforce referential integrity at the database level.

Note on UUIDs vs sequential IDs:
We use UUID primary keys instead of auto-incrementing integers.
Why? Sequential IDs leak information (competitor can see you have 10,042 students
by looking at their own student ID). UUIDs are unguessable.
Also easier in distributed systems — no central sequence to coordinate.
"""

import uuid
from datetime import datetime, date
from sqlalchemy import (
    String, Integer, Boolean, Date, DateTime, ForeignKey,
    Text, Enum as SAEnum, ARRAY, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

# Helper: generate UUID as string (our ID format: "stu_xxxxx", "fac_xxxxx" etc)
# We store as UUID in the DB for indexing efficiency, display with prefix in API
def generate_uuid() -> str:
    return str(uuid.uuid4())


# ── USER MODEL ────────────────────────────────────────────────────────────────
# Separate from Student/Faculty — handles authentication concerns only.
# A user can be linked to a student profile OR a faculty profile OR neither (admin).
# This separation keeps auth clean and separate from domain data.
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        SAEnum("student", "faculty", "librarian", "admin", "service", name="user_role"),
        nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Link to domain profile — nullable because admin users have no student/faculty profile
    student_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("students.id"), nullable=True)
    faculty_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("faculty.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="owner")


# ── PROGRAM MODEL ─────────────────────────────────────────────────────────────
class Program(Base):
    __tablename__ = "programs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    department: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    duration_years: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships — SQLAlchemy loads related objects when you access these attributes
    courses: Mapped[list["Course"]] = relationship("Course", back_populates="program")
    students: Mapped[list["Student"]] = relationship("Student", back_populates="program")


# ── STUDENT MODEL ─────────────────────────────────────────────────────────────
class Student(Base):
    __tablename__ = "students"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    program_id: Mapped[str] = mapped_column(String(36), ForeignKey("programs.id"), nullable=False, index=True)
    enrollment_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        SAEnum("active", "inactive", "graduated", "suspended", name="student_status"),
        default="active",
        nullable=False,
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    program: Mapped["Program"] = relationship("Program", back_populates="students")
    enrollments: Mapped[list["Enrollment"]] = relationship("Enrollment", back_populates="student")
    borrowings: Mapped[list["Borrowing"]] = relationship("Borrowing", back_populates="student")


# ── FACULTY MODEL ─────────────────────────────────────────────────────────────
class Faculty(Base):
    __tablename__ = "faculty"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    title: Mapped[str] = mapped_column(
        SAEnum("Lecturer", "Assistant Professor", "Associate Professor", "Professor", name="faculty_title"),
        nullable=False
    )
    # PostgreSQL ARRAY type for the list of specializations
    specializations: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    office_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    courses: Mapped[list["Course"]] = relationship("Course", back_populates="faculty")


# ── COURSE MODEL ──────────────────────────────────────────────────────────────
class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    program_id: Mapped[str] = mapped_column(String(36), ForeignKey("programs.id"), nullable=False, index=True)
    credits: Mapped[int] = mapped_column(Integer, nullable=False)
    semester: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    faculty_id: Mapped[str] = mapped_column(String(36), ForeignKey("faculty.id"), nullable=False, index=True)
    max_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    program: Mapped["Program"] = relationship("Program", back_populates="courses")
    faculty: Mapped["Faculty"] = relationship("Faculty", back_populates="courses")
    enrollments: Mapped[list["Enrollment"]] = relationship("Enrollment", back_populates="course")

    # Note: current_enrollment is NOT stored — it's a COUNT query on enrollments.
    # We never store derived/computed data that can go stale. We compute it on read.


# ── ENROLLMENT MODEL ──────────────────────────────────────────────────────────
# Junction table between Student and Course
# Represents the "enroll a student in a course" business operation
class Enrollment(Base):
    __tablename__ = "enrollments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    course_id: Mapped[str] = mapped_column(String(36), ForeignKey("courses.id"), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("students.id"), nullable=False, index=True)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(
        SAEnum("active", "dropped", "completed", name="enrollment_status"),
        default="active",
        nullable=False
    )

    # Relationships
    course: Mapped["Course"] = relationship("Course", back_populates="enrollments")
    student: Mapped["Student"] = relationship("Student", back_populates="enrollments")


# ── BOOK MODEL ────────────────────────────────────────────────────────────────
class Book(Base):
    __tablename__ = "books"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    isbn: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    genre: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    total_copies: Mapped[int] = mapped_column(Integer, nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # available_copies is NOT stored — computed as: total_copies - COUNT(active borrowings)
    # Same principle as current_enrollment on courses.
    borrowings: Mapped[list["Borrowing"]] = relationship("Borrowing", back_populates="book")


# ── BORROWING MODEL ───────────────────────────────────────────────────────────
# Top-level resource representing the relationship between Student and Book.
# We discussed in Sprint 1 why this is top-level (queryable from either direction).
class Borrowing(Base):
    __tablename__ = "borrowings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    book_id: Mapped[str] = mapped_column(String(36), ForeignKey("books.id"), nullable=False, index=True)
    student_id: Mapped[str] = mapped_column(String(36), ForeignKey("students.id"), nullable=False, index=True)
    borrowed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        SAEnum("active", "returned", "overdue", "lost", name="borrowing_status"),
        default="active",
        nullable=False,
        index=True
    )

    # Relationships
    book: Mapped["Book"] = relationship("Book", back_populates="borrowings")
    student: Mapped["Student"] = relationship("Student", back_populates="borrowings")
