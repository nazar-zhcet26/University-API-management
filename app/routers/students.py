"""
routers/students.py
-------------------
Students domain — full CRUD with authentication and authorization.

This router demonstrates:
1. How dependencies (auth) are applied per-endpoint
2. BOLA prevention — students can only see their own data
3. Async database queries with SQLAlchemy
4. Proper pagination
5. Consistent response envelope structure

Role matrix for this router:
  GET /students          → admin, faculty (not students — they can't see all students)
  POST /students         → admin only (only admin registers new students)
  GET /students/{id}     → self OR admin OR faculty
  PUT /students/{id}     → admin only
  PATCH /students/{id}   → self (limited fields) OR admin
  DELETE /students/{id}  → admin only
  GET /students/{id}/enrollments → self OR admin OR faculty
  GET /students/{id}/borrowings  → self OR admin OR librarian
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import TokenData
from app.dependencies.auth import (
    require_role,
    require_self_or_role,
    require_admin,
)
from app.models.models import Student, Enrollment, Borrowing
from app.schemas.schemas import (
    StudentCreate, StudentUpdate, StudentResponse, StudentListResponse,
    EnrollmentListResponse, EnrollmentResponse,
    BorrowingListResponse, BorrowingResponse,
    PaginationMeta,
)

router = APIRouter(prefix="/students", tags=["Students"])


# ── Helper: Build pagination metadata ────────────────────────────────────────
def build_pagination(page: int, limit: int, total: int) -> PaginationMeta:
    import math
    return PaginationMeta(
        page=page,
        limit=limit,
        total_items=total,
        total_pages=math.ceil(total / limit) if total > 0 else 0,
    )


# ── GET /students ─────────────────────────────────────────────────────────────
@router.get("", response_model=StudentListResponse)
async def list_students(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    sort: str = Query(default="last_name"),
    program: str | None = Query(default=None),
    year: int | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    # Only admin and faculty can list all students
    current_user: TokenData = Depends(require_role(["admin", "faculty"])),
):
    """
    List all students with pagination and filtering.
    
    Query building pattern:
    We build the WHERE clause dynamically based on which filters are provided.
    Only apply a filter if the query param is not None.
    This is cleaner than building SQL strings manually and safe from injection.
    """
    # Build dynamic WHERE conditions
    conditions = []
    if program:
        # We'd join to programs here — simplified for now
        conditions.append(Student.program_id == program)
    if year:
        conditions.append(Student.enrollment_year == year)
    if status:
        conditions.append(Student.status == status)

    # Count query — total items for pagination metadata
    count_query = select(func.count(Student.id))
    if conditions:
        count_query = count_query.where(and_(*conditions))
    total_result = await db.execute(count_query)
    total = total_result.scalar()

    # Data query with pagination
    data_query = select(Student)
    if conditions:
        data_query = data_query.where(and_(*conditions))

    # Dynamic sorting — default to last_name
    # In production, validate sort field against allowed columns
    sort_column = getattr(Student, sort, Student.last_name)
    data_query = data_query.order_by(sort_column)
    data_query = data_query.offset((page - 1) * limit).limit(limit)

    result = await db.execute(data_query)
    students = result.scalars().all()

    return StudentListResponse(
        data=[StudentResponse.model_validate(s) for s in students],
        pagination=build_pagination(page, limit, total),
    )


# ── POST /students ────────────────────────────────────────────────────────────
@router.post("", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    body: StudentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    """
    Register a new student. Admin only.
    
    The 409 Conflict case: email must be unique.
    We check before inserting rather than catching a DB constraint error,
    so we can return our consistent ErrorResponse format.
    """
    # Check for duplicate email
    existing = await db.execute(select(Student).where(Student.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "EMAIL_ALREADY_EXISTS",
                    "message": f"A student with email '{body.email}' already exists."
                }
            }
        )

    student = Student(**body.model_dump())
    db.add(student)
    await db.flush()  # flush to get the generated ID without committing yet
    await db.refresh(student)

    return StudentResponse.model_validate(student)


# ── GET /students/{student_id} ────────────────────────────────────────────────
@router.get("/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: str,
    db: AsyncSession = Depends(get_db),
    # Self, admin, or faculty can view a student profile
    # This is the BOLA fix — student can only see their own profile
    current_user: TokenData = Depends(
        require_self_or_role("student_id", ["admin", "faculty"])
    ),
):
    """
    Get a specific student by ID.
    
    BOLA protection:
    - Student stu_10042 requesting GET /students/stu_10042 → ALLOWED (self)
    - Student stu_10042 requesting GET /students/stu_99999 → 403 FORBIDDEN
    - Admin requesting GET /students/stu_99999 → ALLOWED (privileged role)
    """
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()

    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "STUDENT_NOT_FOUND", "message": f"Student '{student_id}' not found."}}
        )

    return StudentResponse.model_validate(student)


# ── PUT /students/{student_id} ────────────────────────────────────────────────
@router.put("/{student_id}", response_model=StudentResponse)
async def replace_student(
    student_id: str,
    body: StudentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    """
    Full replacement of student record. Admin only.
    PUT = send the complete resource. All fields required.
    """
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail={"error": {"code": "STUDENT_NOT_FOUND", "message": "Not found."}})

    for field, value in body.model_dump().items():
        setattr(student, field, value)

    await db.flush()
    await db.refresh(student)
    return StudentResponse.model_validate(student)


# ── PATCH /students/{student_id} ──────────────────────────────────────────────
@router.patch("/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    body: StudentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(
        require_self_or_role("student_id", ["admin"])
    ),
):
    """
    Partial update. Students can update their own email.
    Admins can update any field including status.
    
    PATCH design: only update fields that were actually sent.
    model_dump(exclude_unset=True) is the key — it returns only fields
    the client explicitly included, not all fields with defaults.
    
    So PATCH {"email": "new@uni.ac.ae"} only changes email.
    PATCH {} changes nothing.
    """
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail={"error": {"code": "STUDENT_NOT_FOUND", "message": "Not found."}})

    # Only update provided fields
    updates = body.model_dump(exclude_unset=True)

    # Non-admin students can only update their own email (not status)
    if current_user.role == "student" and "status" in updates:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN_FIELD", "message": "Students cannot update their own status."}}
        )

    for field, value in updates.items():
        setattr(student, field, value)

    await db.flush()
    await db.refresh(student)
    return StudentResponse.model_validate(student)


# ── DELETE /students/{student_id} ─────────────────────────────────────────────
@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    """
    Delete a student. Admin only.
    Returns 204 No Content — no body on successful delete.
    """
    result = await db.execute(select(Student).where(Student.id == student_id))
    student = result.scalar_one_or_none()

    if not student:
        raise HTTPException(status_code=404, detail={"error": {"code": "STUDENT_NOT_FOUND", "message": "Not found."}})

    await db.delete(student)


# ── GET /students/{student_id}/enrollments ────────────────────────────────────
@router.get("/{student_id}/enrollments", response_model=EnrollmentListResponse)
async def get_student_enrollments(
    student_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(
        require_self_or_role("student_id", ["admin", "faculty"])
    ),
):
    """
    Get all course enrollments for a student.
    Cross-domain relationship: Students → Courses.
    """
    # Verify student exists first
    student_result = await db.execute(select(Student).where(Student.id == student_id))
    if not student_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "STUDENT_NOT_FOUND", "message": "Not found."}})

    count_result = await db.execute(
        select(func.count(Enrollment.id)).where(Enrollment.student_id == student_id)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(Enrollment)
        .where(Enrollment.student_id == student_id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    enrollments = result.scalars().all()

    return EnrollmentListResponse(
        data=[EnrollmentResponse.model_validate(e) for e in enrollments],
        pagination=build_pagination(page, limit, total),
    )


# ── GET /students/{student_id}/borrowings ─────────────────────────────────────
@router.get("/{student_id}/borrowings", response_model=BorrowingListResponse)
async def get_student_borrowings(
    student_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(
        require_self_or_role("student_id", ["admin", "librarian"])
    ),
):
    """
    Get all library borrowings for a student.
    Cross-domain relationship: Students → Library.
    """
    student_result = await db.execute(select(Student).where(Student.id == student_id))
    if not student_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "STUDENT_NOT_FOUND", "message": "Not found."}})

    count_result = await db.execute(
        select(func.count(Borrowing.id)).where(Borrowing.student_id == student_id)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(Borrowing)
        .where(Borrowing.student_id == student_id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    borrowings = result.scalars().all()

    return BorrowingListResponse(
        data=[BorrowingResponse.model_validate(b) for b in borrowings],
        pagination=build_pagination(page, limit, total),
    )
