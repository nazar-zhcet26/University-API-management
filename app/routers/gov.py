"""
app/routers/gov.py
------------------
UAE Government reporting endpoints.

These endpoints expose your existing university data in the shape that
the UAE Ministry of Education and Higher Education (MOEHE) expects for
API-first integrations and periodic reporting.

Auth model:
  All three endpoints require the X-API-Key header with role=service.
  They do NOT accept JWT Bearer tokens — these are machine-to-machine
  endpoints, not user-facing ones. This is enforced by using
  get_api_key_user directly rather than get_current_user.

Import pattern:
  - Models from app.models.models (Student, Program, Enrollment — all in one file)
  - Auth dep from app.middleware.api_key_auth
  - require_role from app.dependencies.auth
  - TokenData from app.core.security
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.security import TokenData
from app.middleware.api_key_auth import get_api_key_user
from app.models.models import Student, Program, Enrollment

router = APIRouter(prefix="/gov", tags=["UAE Government"])

INSTITUTION_CODE = "UAE-UNI-001"
API_VERSION      = "1.0"


async def require_service_key(
    token: TokenData = Depends(get_api_key_user),
) -> TokenData:
    """
    Gov-endpoint guard: must be an API key AND role must be 'service'.
    Using get_api_key_user as the inner dep means JWT Bearer tokens are
    rejected outright — these endpoints are machine-to-machine only.
    """
    from fastapi import HTTPException, status
    if token.role != "service":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "INSUFFICIENT_PERMISSIONS", "message": "Gov endpoints require service role"}},
        )
    return token


def _gov_meta(total: int) -> dict:
    """Standard UAE API-first response envelope metadata."""
    return {
        "total":            total,
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "institution_code": INSTITUTION_CODE,
        "api_version":      API_VERSION,
    }


def _map_nqf_level(department: Optional[str]) -> int:
    """
    Map department/program name to UAE National Qualifications Framework level.
    NQF levels 1-10. Most university programs sit at 7 (bachelor) or above.
    We infer from program name since degree_type isn't a column in your Program model.
    """
    if not department:
        return 7
    dept = department.lower()
    if any(x in dept for x in ["phd", "doctorate", "doctoral"]):
        return 10
    if any(x in dept for x in ["master", "msc", "mba", "meng"]):
        return 9
    if any(x in dept for x in ["diploma", "hnd", "foundation"]):
        return 5
    return 7  # default — bachelor level


# ── GET /v1/gov/students ──────────────────────────────────────────────────────

@router.get(
    "/students",
    summary="UAE Gov — student roster",
    description="Student list in UAE MOEHE API-first format. Requires X-API-Key with service role.",
)
async def gov_students(
    page:  int = Query(default=1,   ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    db:    AsyncSession = Depends(get_db),
    _:     TokenData    = Depends(require_service_key),
):

    offset = (page - 1) * limit

    result = await db.execute(
        select(Student, Program)
        .outerjoin(Program, Student.program_id == Program.id)
        .order_by(Student.last_name)
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()

    count_result = await db.execute(select(func.count()).select_from(Student))
    total        = count_result.scalar_one()

    data = [
        {
            "student_id":        s.id,
            "full_name_en":      f"{s.first_name} {s.last_name}",
            "email":             s.email,
            "enrollment_status": s.status,
            "enrollment_year":   s.enrollment_year,
            "program_code":      p.code if p else None,
            "program_name":      p.name if p else None,
            "department":        p.department if p else None,
            "academic_level":    _map_nqf_level(p.name if p else None),
            "date_of_birth":     s.date_of_birth.isoformat() if s.date_of_birth else None,
        }
        for s, p in rows
    ]

    return {"data": data, "meta": _gov_meta(total)}


# ── GET /v1/gov/enrollment-stats ──────────────────────────────────────────────

@router.get(
    "/enrollment-stats",
    summary="UAE Gov — enrollment statistics",
    description="Aggregated enrollment stats in MOEHE reporting format. Requires X-API-Key with service role.",
)
async def gov_enrollment_stats(
    db: AsyncSession = Depends(get_db),
    _:  TokenData    = Depends(require_service_key),
):

    status_rows = await db.execute(
        select(Student.status, func.count().label("count")).group_by(Student.status)
    )
    by_status = {row.status: row.count for row in status_rows}

    # Students per program
    prog_rows = await db.execute(
        select(Program.code, Program.name, Program.department, func.count(Student.id).label("count"))
        .outerjoin(Student, Student.program_id == Program.id)
        .group_by(Program.id, Program.code, Program.name, Program.department)
        .order_by(func.count(Student.id).desc())
    )
    by_program = [
        {
            "program_code":  r.code,
            "program_name":  r.name,
            "department":    r.department,
            "student_count": r.count,
        }
        for r in prog_rows
    ]

    # Students by enrollment year
    year_rows = await db.execute(
        select(Student.enrollment_year, func.count().label("count"))
        .group_by(Student.enrollment_year)
        .order_by(Student.enrollment_year.desc())
        .limit(5)
    )
    by_year = {str(r.enrollment_year): r.count for r in year_rows}

    # Active enrollments (course enrollments, not student status)
    active_enroll = await db.execute(
        select(func.count()).select_from(Enrollment).where(Enrollment.status == "active")
    )
    total_active_enrollments = active_enroll.scalar_one()

    total_result = await db.execute(select(func.count()).select_from(Student))
    total        = total_result.scalar_one()

    stats = {
        "total_students":           total,
        "total_active_enrollments": total_active_enrollments,
        "by_status": {
            "active":    by_status.get("active",    0),
            "inactive":  by_status.get("inactive",  0),
            "graduated": by_status.get("graduated", 0),
            "suspended": by_status.get("suspended", 0),
        },
        "by_program":        by_program,
        "by_enrollment_year": by_year,
    }

    return {"data": stats, "meta": _gov_meta(1)}


# ── GET /v1/gov/programs ──────────────────────────────────────────────────────

@router.get(
    "/programs",
    summary="UAE Gov — program catalog",
    description="Program catalog with NQF levels for MOEHE reporting. Requires X-API-Key with service role.",
)
async def gov_programs(
    db: AsyncSession = Depends(get_db),
    _:  TokenData    = Depends(require_service_key),
):
    result   = await db.execute(select(Program).order_by(Program.code))
    programs = result.scalars().all()

    # Student count per program
    count_rows = await db.execute(
        select(Student.program_id, func.count().label("count"))
        .group_by(Student.program_id)
    )
    student_counts = {row.program_id: row.count for row in count_rows}

    data = [
        {
            "program_id":      p.id,
            "program_code":    p.code,
            "program_name":    p.name,
            "department":      p.department,
            "duration_years":  p.duration_years,
            "description":     p.description,
            "nqf_level":       _map_nqf_level(p.name),
            "total_students":  student_counts.get(p.id, 0),
        }
        for p in programs
    ]

    return {"data": data, "meta": _gov_meta(len(data))}