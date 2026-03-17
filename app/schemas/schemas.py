"""
schemas/schemas.py
------------------
Pydantic models for API request validation and response serialization.

These are DIFFERENT from SQLAlchemy models:
- SQLAlchemy models = database layer (what's stored)
- Pydantic schemas = API layer (what goes in/out of endpoints)

Why separate them?
1. Your DB model has 'hashed_password' — your API schema must NEVER expose that
2. Your API schema might combine data from multiple DB tables
3. Your DB schema has foreign key columns — your API response might embed nested objects
4. Input schemas (what client sends) differ from output schemas (what we return)

The pattern we use:
  XBase     → shared fields
  XCreate   → fields for POST (creation)
  XUpdate   → fields for PATCH (partial update, all optional)
  XResponse → fields returned by GET (includes server-generated fields)

model_config = ConfigDict(from_attributes=True) on response schemas means
Pydantic can read directly from SQLAlchemy model instances.
Without this, you'd have to manually convert every DB object to a dict.
"""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator
from enum import Enum


# ── ENUMS ─────────────────────────────────────────────────────────────────────
# Using Python Enums ensures only valid values are accepted.
# Pydantic validates against these automatically.

class UserRole(str, Enum):
    student = "student"
    faculty = "faculty"
    librarian = "librarian"
    admin = "admin"
    service = "service"

class StudentStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    graduated = "graduated"
    suspended = "suspended"

class EnrollmentStatus(str, Enum):
    active = "active"
    dropped = "dropped"
    completed = "completed"

class FacultyTitle(str, Enum):
    lecturer = "Lecturer"
    assistant_professor = "Assistant Professor"
    associate_professor = "Associate Professor"
    professor = "Professor"

class BorrowingStatus(str, Enum):
    active = "active"
    returned = "returned"
    overdue = "overdue"
    lost = "lost"


# ── PAGINATION ────────────────────────────────────────────────────────────────
# The consistent envelope structure we defined in Sprint 1.
# Every list endpoint returns this exact shape — consumers learn it once.

class PaginationMeta(BaseModel):
    page: int
    limit: int
    total_items: int
    total_pages: int


# ── ERROR RESPONSE ────────────────────────────────────────────────────────────
class ErrorDetail(BaseModel):
    field: Optional[str] = None
    issue: str

class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[list[ErrorDetail]] = None

class ErrorResponse(BaseModel):
    error: ErrorBody


# ── AUTH SCHEMAS ──────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds until access token expires

class RefreshRequest(BaseModel):
    refresh_token: str


# ── STUDENT SCHEMAS ───────────────────────────────────────────────────────────
class StudentBase(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    date_of_birth: date
    program_id: str
    enrollment_year: int
    status: StudentStatus = StudentStatus.active

    @field_validator("enrollment_year")
    @classmethod
    def validate_enrollment_year(cls, v):
        if v < 2000 or v > 2100:
            raise ValueError("Enrollment year must be between 2000 and 2100")
        return v

class StudentCreate(StudentBase):
    pass  # same as base for now — could add fields only relevant at creation

class StudentUpdate(BaseModel):
    """All fields optional for PATCH — only send what you want to change."""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[EmailStr] = None
    status: Optional[StudentStatus] = None

class StudentResponse(StudentBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime

class StudentListResponse(BaseModel):
    data: list[StudentResponse]
    pagination: PaginationMeta


# ── PROGRAM SCHEMAS ───────────────────────────────────────────────────────────
class ProgramBase(BaseModel):
    code: str
    name: str
    department: str
    duration_years: int
    description: Optional[str] = None

class ProgramCreate(ProgramBase):
    pass

class ProgramUpdate(BaseModel):
    name: Optional[str] = None
    department: Optional[str] = None
    duration_years: Optional[int] = None
    description: Optional[str] = None

class ProgramResponse(ProgramBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime

class ProgramListResponse(BaseModel):
    data: list[ProgramResponse]
    pagination: PaginationMeta


# ── FACULTY SCHEMAS ───────────────────────────────────────────────────────────
class FacultyBase(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    department: str
    title: FacultyTitle
    specializations: Optional[list[str]] = None
    office_number: Optional[str] = None

class FacultyCreate(FacultyBase):
    pass

class FacultyUpdate(BaseModel):
    title: Optional[FacultyTitle] = None
    department: Optional[str] = None
    specializations: Optional[list[str]] = None
    office_number: Optional[str] = None

class FacultyResponse(FacultyBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime

class FacultyListResponse(BaseModel):
    data: list[FacultyResponse]
    pagination: PaginationMeta


# ── COURSE SCHEMAS ────────────────────────────────────────────────────────────
class CourseBase(BaseModel):
    code: str
    title: str
    description: Optional[str] = None
    program_id: str
    credits: int
    semester: str
    faculty_id: str
    max_capacity: int

class CourseCreate(CourseBase):
    pass

class CourseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    faculty_id: Optional[str] = None
    max_capacity: Optional[int] = None

class CourseResponse(CourseBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    # current_enrollment is computed, not from the DB column directly
    # We'll populate it in the router using a COUNT query
    current_enrollment: int = 0
    created_at: datetime
    updated_at: datetime

class CourseListResponse(BaseModel):
    data: list[CourseResponse]
    pagination: PaginationMeta


# ── ENROLLMENT SCHEMAS ────────────────────────────────────────────────────────
class EnrollmentCreate(BaseModel):
    student_id: str

class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    course_id: str
    student_id: str
    enrolled_at: datetime
    status: EnrollmentStatus

class EnrollmentListResponse(BaseModel):
    data: list[EnrollmentResponse]
    pagination: PaginationMeta


# ── BOOK SCHEMAS ──────────────────────────────────────────────────────────────
class BookBase(BaseModel):
    title: str
    author: str
    isbn: str
    genre: str
    total_copies: int
    publisher: Optional[str] = None
    published_year: Optional[int] = None

class BookCreate(BookBase):
    pass

class BookUpdate(BaseModel):
    total_copies: Optional[int] = None
    genre: Optional[str] = None
    publisher: Optional[str] = None

class BookResponse(BookBase):
    model_config = ConfigDict(from_attributes=True)
    id: str
    # Computed from total_copies - COUNT(active borrowings)
    available_copies: int = 0
    created_at: datetime
    updated_at: datetime

class BookListResponse(BaseModel):
    data: list[BookResponse]
    pagination: PaginationMeta


# ── BORROWING SCHEMAS ─────────────────────────────────────────────────────────
class BorrowingCreate(BaseModel):
    book_id: str
    student_id: str
    due_date: date

class BorrowingUpdate(BaseModel):
    """Only status can be updated by the client — returned_at is server-managed."""
    status: BorrowingStatus

class BorrowingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    book_id: str
    student_id: str
    borrowed_at: datetime
    due_date: date
    returned_at: Optional[datetime] = None  # null until returned
    status: BorrowingStatus

class BorrowingListResponse(BaseModel):
    data: list[BorrowingResponse]
    pagination: PaginationMeta
