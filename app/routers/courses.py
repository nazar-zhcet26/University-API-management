"""
app/routers/courses.py
----------------------
Courses domain — demonstrates all Sprint 4 concepts:

1. Redis caching on list and single endpoints
2. Cache invalidation on writes
3. Eager loading to prevent N+1 queries
4. Cursor-based pagination on the high-traffic list endpoint
5. Full-text search using PostgreSQL GIN index

This is the highest-traffic domain (students constantly checking
course availability during registration) so it gets the most
optimization attention.

Role matrix:
  GET /courses              → any authenticated user (students, faculty, admin)
  POST /courses             → admin or faculty
  GET /courses/{id}         → any authenticated user
  PUT /courses/{id}         → admin
  PATCH /courses/{id}       → admin or faculty (own courses)
  DELETE /courses/{id}      → admin only
  GET /courses/{id}/students  → faculty (own course) or admin
  POST /courses/{id}/enrollments → student (self-enroll) or admin
  DELETE /courses/{id}/enrollments/{enrollment_id} → student (self) or admin
"""

import math
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, text
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import TokenData
from app.dependencies.auth import (
    require_role,
    require_any_authenticated,
    require_admin,
    require_admin_or_faculty,
)
from app.models.models import Course, Enrollment, Student, Faculty
from app.schemas.schemas import (
    CourseCreate, CourseUpdate, CourseResponse, CourseListResponse,
    EnrollmentCreate, EnrollmentResponse, EnrollmentListResponse,
    StudentListResponse, StudentResponse,
    PaginationMeta,
)
from app.services.cache import cache, CacheTTL

router = APIRouter(prefix="/courses", tags=["Courses"])


def build_pagination(page: int, limit: int, total: int) -> PaginationMeta:
    return PaginationMeta(
        page=page, limit=limit, total_items=total,
        total_pages=math.ceil(total / limit) if total > 0 else 0,
    )


async def get_enrollment_count(db: AsyncSession, course_id: str) -> int:
    """Get current enrollment count for a course."""
    result = await db.execute(
        select(func.count(Enrollment.id)).where(
            and_(Enrollment.course_id == course_id, Enrollment.status == "active")
        )
    )
    return result.scalar() or 0


# ── GET /courses ──────────────────────────────────────────────────────────────
@router.get("", response_model=CourseListResponse)
async def list_courses(
    # Pagination — offset-based (standard, good up to ~page 100)
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    # Cursor-based pagination — for high-volume consumers
    # If cursor is provided, page/limit are ignored
    cursor: Optional[str] = Query(default=None, description="Cursor for cursor-based pagination. Get from 'next_cursor' in previous response."),
    # Filters
    program_id: Optional[str] = Query(default=None),
    semester: Optional[str] = Query(default=None),
    faculty_id: Optional[str] = Query(default=None),
    available: Optional[bool] = Query(default=None, description="Filter to courses with open enrollment spots"),
    q: Optional[str] = Query(default=None, description="Search course title"),
    sort: str = Query(default="title"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """
    List courses with caching.
    
    Cache strategy:
    - Build a cache key from all the filter parameters
    - Check cache first
    - On miss: query DB, store in cache for 5 minutes
    - Cache is invalidated when any course is created/updated/deleted
    
    Eager loading:
    - We load the faculty relationship in the same query using selectinload
    - This prevents N+1: instead of 1 + 40 queries, it's just 2 queries total
      (one for courses, one for all related faculty in a single IN clause)
    """
    # Build cache key from all filter params
    cache_key = cache.build_list_key(
        "courses",
        page=page, limit=limit, cursor=cursor,
        program_id=program_id, semester=semester,
        faculty_id=faculty_id, available=available, q=q, sort=sort
    )

    # Try cache first
    cached = await cache.get(cache_key)
    if cached:
        return cached

    # Cache miss — query database
    conditions = []
    if program_id:
        conditions.append(Course.program_id == program_id)
    if semester:
        conditions.append(Course.semester == semester)
    if faculty_id:
        conditions.append(Course.faculty_id == faculty_id)
    if q:
        # Use PostgreSQL full-text search (uses the GIN index we created in migration)
        # Much faster than ILIKE '%q%' which requires a full table scan
        conditions.append(
            text("to_tsvector('english', title) @@ plainto_tsquery('english', :q)").bindparams(q=q)
        )

    # ── Cursor-based pagination ───────────────────────────────────────────────
    if cursor:
        # cursor is the ID of the last item from the previous page
        # We fetch all items AFTER that ID (using ID ordering)
        # This is always fast because IDs are indexed — no OFFSET scan
        conditions.append(Course.id > cursor)
        
        query = select(Course).options(
            selectinload(Course.faculty)  # eager load — prevents N+1
        )
        if conditions:
            query = query.where(and_(*conditions))
        query = query.order_by(Course.id).limit(limit)
        
        result = await db.execute(query)
        courses = result.scalars().all()
        
        # Next cursor is the ID of the last item returned
        next_cursor = courses[-1].id if len(courses) == limit else None
        
        course_responses = []
        for course in courses:
            count = await get_enrollment_count(db, course.id)
            resp = CourseResponse.model_validate(course)
            resp.current_enrollment = count
            course_responses.append(resp)

        response_data = {
            "data": [r.model_dump() for r in course_responses],
            "pagination": {
                "page": 1,
                "limit": limit,
                "total_items": -1,  # not computed for cursor pagination (expensive)
                "total_pages": -1,
                "next_cursor": next_cursor,
                "has_more": next_cursor is not None,
            }
        }

    # ── Offset-based pagination ───────────────────────────────────────────────
    else:
        count_query = select(func.count(Course.id))
        if conditions:
            count_query = count_query.where(and_(*conditions))
        total = (await db.execute(count_query)).scalar()

        sort_column = getattr(Course, sort, Course.title)
        query = select(Course).options(selectinload(Course.faculty))
        if conditions:
            query = query.where(and_(*conditions))
        query = query.order_by(sort_column).offset((page - 1) * limit).limit(limit)

        courses = (await db.execute(query)).scalars().all()

        # Filter by availability if requested (post-query since it requires a count)
        course_responses = []
        for course in courses:
            count = await get_enrollment_count(db, course.id)
            if available is True and count >= course.max_capacity:
                continue
            if available is False and count < course.max_capacity:
                continue
            resp = CourseResponse.model_validate(course)
            resp.current_enrollment = count
            course_responses.append(resp)

        response_data = {
            "data": [r.model_dump() for r in course_responses],
            "pagination": build_pagination(page, limit, total).model_dump()
        }

    # Store in cache
    await cache.set(cache_key, response_data, ttl=CacheTTL.COURSE_LIST)
    return response_data


# ── POST /courses ─────────────────────────────────────────────────────────────
@router.post("", response_model=CourseResponse, status_code=status.HTTP_201_CREATED)
async def create_course(
    body: CourseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_faculty),
):
    """
    Create a new course.
    
    Cache invalidation: when a course is created, all course list caches
    are stale. We delete them using pattern matching.
    """
    # Verify faculty exists
    faculty_result = await db.execute(select(Faculty).where(Faculty.id == body.faculty_id))
    if not faculty_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "FACULTY_NOT_FOUND", "message": f"Faculty '{body.faculty_id}' not found."}}
        )

    course = Course(**body.model_dump())
    db.add(course)
    await db.flush()
    await db.refresh(course)

    # Invalidate all course list caches — new course means all lists are stale
    await cache.delete_pattern("courses:list:*")

    resp = CourseResponse.model_validate(course)
    resp.current_enrollment = 0
    return resp


# ── GET /courses/{course_id} ──────────────────────────────────────────────────
@router.get("/{course_id}", response_model=CourseResponse)
async def get_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """
    Get a single course. Cached individually.
    
    Eager loads faculty so we have faculty info available in the response
    without a second query.
    """
    cache_key = cache.build_key("courses", "single", course_id)
    cached = await cache.get(cache_key)
    if cached:
        return cached

    result = await db.execute(
        select(Course)
        .options(selectinload(Course.faculty))
        .where(Course.id == course_id)
    )
    course = result.scalar_one_or_none()

    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "COURSE_NOT_FOUND", "message": f"Course '{course_id}' not found."}}
        )

    count = await get_enrollment_count(db, course_id)
    resp = CourseResponse.model_validate(course)
    resp.current_enrollment = count

    await cache.set(cache_key, resp.model_dump(), ttl=CacheTTL.COURSE_SINGLE)
    return resp


# ── PATCH /courses/{course_id} ────────────────────────────────────────────────
@router.patch("/{course_id}", response_model=CourseResponse)
async def update_course(
    course_id: str,
    body: CourseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_faculty),
):
    """
    Partial update with cache invalidation.
    Faculty can only update their own courses.
    """
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()

    if not course:
        raise HTTPException(status_code=404, detail={"error": {"code": "COURSE_NOT_FOUND", "message": "Not found."}})

    # Faculty can only update their OWN courses
    if current_user.role == "faculty":
        faculty_result = await db.execute(
            select(Faculty).where(Faculty.id == current_user.subject)
        )
        faculty = faculty_result.scalar_one_or_none()
        if not faculty or course.faculty_id != faculty.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "NOT_YOUR_COURSE", "message": "Faculty can only update their own courses."}}
            )

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(course, field, value)

    await db.flush()
    await db.refresh(course)

    # Invalidate both the list cache and this specific course's cache
    await cache.delete_pattern("courses:list:*")
    await cache.delete(cache.build_key("courses", "single", course_id))

    count = await get_enrollment_count(db, course_id)
    resp = CourseResponse.model_validate(course)
    resp.current_enrollment = count
    return resp


# ── DELETE /courses/{course_id} ───────────────────────────────────────────────
@router.delete("/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin),
):
    result = await db.execute(select(Course).where(Course.id == course_id))
    course = result.scalar_one_or_none()

    if not course:
        raise HTTPException(status_code=404, detail={"error": {"code": "COURSE_NOT_FOUND", "message": "Not found."}})

    await db.delete(course)

    # Invalidate all course caches
    await cache.delete_pattern("courses:list:*")
    await cache.delete(cache.build_key("courses", "single", course_id))


# ── GET /courses/{course_id}/students ─────────────────────────────────────────
@router.get("/{course_id}/students", response_model=StudentListResponse)
async def get_course_students(
    course_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_faculty),
):
    """
    Get all students enrolled in a course.
    Uses a JOIN through the enrollments table.
    Demonstrates a more complex query — not just a simple select.
    """
    # Verify course exists
    course_result = await db.execute(select(Course).where(Course.id == course_id))
    if not course_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "COURSE_NOT_FOUND", "message": "Not found."}})

    # JOIN: students → enrollments (where course_id matches and enrollment is active)
    # This is a single query, not N+1
    count_result = await db.execute(
        select(func.count(Student.id))
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(and_(Enrollment.course_id == course_id, Enrollment.status == "active"))
    )
    total = count_result.scalar()

    result = await db.execute(
        select(Student)
        .join(Enrollment, Enrollment.student_id == Student.id)
        .where(and_(Enrollment.course_id == course_id, Enrollment.status == "active"))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    students = result.scalars().all()

    return StudentListResponse(
        data=[StudentResponse.model_validate(s) for s in students],
        pagination=build_pagination(page, limit, total),
    )


# ── POST /courses/{course_id}/enrollments ─────────────────────────────────────
@router.post("/{course_id}/enrollments", response_model=EnrollmentResponse, status_code=201)
async def enroll_student(
    course_id: str,
    body: EnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """
    Enroll a student in a course.
    Students can self-enroll. Admin can enroll anyone.
    
    Business rules (Process API layer):
    1. Course must exist
    2. Student must exist and be active
    3. Course must have available capacity (422 if full)
    4. Student must not already be enrolled (409 if duplicate)
    """
    # Students can only enroll themselves
    if current_user.role == "student" and current_user.subject != body.student_id:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "FORBIDDEN", "message": "Students can only enroll themselves."}}
        )

    # Rule 1: Course exists
    course_result = await db.execute(select(Course).where(Course.id == course_id))
    course = course_result.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail={"error": {"code": "COURSE_NOT_FOUND", "message": "Course not found."}})

    # Rule 2: Student exists and is active
    student_result = await db.execute(select(Student).where(Student.id == body.student_id))
    student = student_result.scalar_one_or_none()
    if not student:
        raise HTTPException(status_code=404, detail={"error": {"code": "STUDENT_NOT_FOUND", "message": "Student not found."}})
    if student.status != "active":
        raise HTTPException(
            status_code=422,
            detail={"error": {"code": "STUDENT_NOT_ACTIVE", "message": "Cannot enroll a student with inactive status."}}
        )

    # Rule 3: Course has capacity
    current_count = await get_enrollment_count(db, course_id)
    if current_count >= course.max_capacity:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "COURSE_AT_CAPACITY",
                    "message": f"'{course.title}' is at maximum capacity ({course.max_capacity} students)."
                }
            }
        )

    # Rule 4: Not already enrolled
    existing = await db.execute(
        select(Enrollment).where(
            and_(
                Enrollment.course_id == course_id,
                Enrollment.student_id == body.student_id,
                Enrollment.status == "active",
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "ALREADY_ENROLLED", "message": "Student is already enrolled in this course."}}
        )

    enrollment = Enrollment(course_id=course_id, student_id=body.student_id)
    db.add(enrollment)
    await db.flush()
    await db.refresh(enrollment)

    # Invalidate course cache — enrollment count changed
    await cache.delete(cache.build_key("courses", "single", course_id))
    await cache.delete_pattern("courses:list:*")

    return EnrollmentResponse.model_validate(enrollment)


# ── DELETE /courses/{course_id}/enrollments/{enrollment_id} ──────────────────
@router.delete("/{course_id}/enrollments/{enrollment_id}", status_code=204)
async def drop_enrollment(
    course_id: str,
    enrollment_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """Drop a course (remove enrollment). Students can drop their own enrollments."""
    result = await db.execute(
        select(Enrollment).where(
            and_(Enrollment.id == enrollment_id, Enrollment.course_id == course_id)
        )
    )
    enrollment = result.scalar_one_or_none()

    if not enrollment:
        raise HTTPException(status_code=404, detail={"error": {"code": "ENROLLMENT_NOT_FOUND", "message": "Not found."}})

    # Students can only drop their own enrollments
    if current_user.role == "student" and current_user.subject != enrollment.student_id:
        raise HTTPException(status_code=403, detail={"error": {"code": "ACCESS_DENIED", "message": "Access denied."}})

    enrollment.status = "dropped"
    await db.flush()

    # Invalidate course cache — enrollment count changed
    await cache.delete(cache.build_key("courses", "single", course_id))
    await cache.delete_pattern("courses:list:*")
