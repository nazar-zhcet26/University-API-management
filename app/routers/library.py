"""
routers/library.py
------------------
Library domain — Books and Borrowings.

This router is worth studying because it demonstrates:
1. Business rule enforcement (the 422 scenarios from Sprint 1)
2. Server-managed fields (returned_at, available_copies)
3. The top-level resource pattern for borrowings (queryable from both directions)
4. Side effects on PATCH (returning a book updates available_copies)

Role matrix:
  Books:
    GET /books, GET /books/{id}         → any authenticated user
    POST, PUT, PATCH, DELETE /books     → librarian or admin
  
  Borrowings:
    GET /borrowings                     → librarian or admin
    POST /borrowings (borrow)           → student (for themselves) or librarian/admin
    PATCH /borrowings/{id} (return)     → student (self) or librarian/admin
    GET /borrowings/{id}                → self or librarian/admin
"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.core.security import TokenData
from app.dependencies.auth import (
    require_role,
    require_self_or_role,
    require_admin_or_librarian,
    require_any_authenticated,
)
from app.models.models import Book, Borrowing, Student
from app.schemas.schemas import (
    BookCreate, BookUpdate, BookResponse, BookListResponse,
    BorrowingCreate, BorrowingUpdate, BorrowingResponse, BorrowingListResponse,
    PaginationMeta, BorrowingStatus,
)
import math

router = APIRouter(tags=["Library - Books"])
borrowings_router = APIRouter(tags=["Library - Borrowings"])


def build_pagination(page, limit, total):
    return PaginationMeta(
        page=page, limit=limit, total_items=total,
        total_pages=math.ceil(total / limit) if total > 0 else 0,
    )


async def compute_available_copies(db: AsyncSession, book: Book) -> int:
    """
    Compute available copies as: total_copies - active borrowings.
    
    This is never stored in the database — it's always computed fresh.
    Why? Because storing it means we have two sources of truth that can
    get out of sync. One source (the borrowings table count) is always correct.
    
    This is the principle of avoiding derived data in the DB.
    The trade-off: slightly more work on every read. For most systems, this
    is the right call. If it becomes a performance issue, we add caching
    (Sprint 4) — not a denormalized column that can go stale.
    """
    result = await db.execute(
        select(func.count(Borrowing.id)).where(
            and_(Borrowing.book_id == book.id, Borrowing.status == "active")
        )
    )
    active_borrowings = result.scalar()
    return max(0, book.total_copies - active_borrowings)


# ── BOOKS ─────────────────────────────────────────────────────────────────────

@router.get("/books", response_model=BookListResponse)
async def list_books(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    sort: str = Query(default="title"),
    genre: str | None = Query(default=None),
    available: bool | None = Query(default=None),
    author: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Full-text search across title and author"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    conditions = []
    if genre:
        conditions.append(Book.genre == genre)
    if author:
        conditions.append(Book.author.ilike(f"%{author}%"))
    if q:
        # Simple ILIKE search — in Sprint 4 we'd add PostgreSQL full-text search
        conditions.append(
            Book.title.ilike(f"%{q}%") | Book.author.ilike(f"%{q}%")
        )

    count_query = select(func.count(Book.id))
    if conditions:
        count_query = count_query.where(and_(*conditions))
    total = (await db.execute(count_query)).scalar()

    sort_column = getattr(Book, sort, Book.title)
    data_query = select(Book)
    if conditions:
        data_query = data_query.where(and_(*conditions))
    data_query = data_query.order_by(sort_column).offset((page - 1) * limit).limit(limit)

    books = (await db.execute(data_query)).scalars().all()

    # Build responses with computed available_copies
    book_responses = []
    for book in books:
        avail = await compute_available_copies(db, book)
        # If filtering by available=True, skip books with 0 available
        if available is True and avail == 0:
            continue
        if available is False and avail > 0:
            continue
        response = BookResponse.model_validate(book)
        response.available_copies = avail
        book_responses.append(response)

    return BookListResponse(
        data=book_responses,
        pagination=build_pagination(page, limit, total),
    )


@router.post("/books", response_model=BookResponse, status_code=status.HTTP_201_CREATED)
async def create_book(
    body: BookCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_librarian),
):
    existing = await db.execute(select(Book).where(Book.isbn == body.isbn))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "ISBN_EXISTS", "message": f"A book with ISBN '{body.isbn}' already exists."}}
        )

    book = Book(**body.model_dump())
    db.add(book)
    await db.flush()
    await db.refresh(book)

    response = BookResponse.model_validate(book)
    response.available_copies = book.total_copies  # new book, nothing borrowed yet
    return response


@router.get("/books/{book_id}", response_model=BookResponse)
async def get_book(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Not found."}})

    response = BookResponse.model_validate(book)
    response.available_copies = await compute_available_copies(db, book)
    return response


@router.patch("/books/{book_id}", response_model=BookResponse)
async def update_book(
    book_id: str,
    body: BookUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_librarian),
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Not found."}})

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(book, field, value)

    await db.flush()
    await db.refresh(book)
    response = BookResponse.model_validate(book)
    response.available_copies = await compute_available_copies(db, book)
    return response


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_librarian),
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Not found."}})
    await db.delete(book)


@router.get("/books/{book_id}/borrowings", response_model=BorrowingListResponse)
async def get_book_borrowings(
    book_id: str,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_librarian),
):
    book_result = await db.execute(select(Book).where(Book.id == book_id))
    if not book_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Not found."}})

    conditions = [Borrowing.book_id == book_id]
    if status_filter:
        conditions.append(Borrowing.status == status_filter)

    total = (await db.execute(select(func.count(Borrowing.id)).where(and_(*conditions)))).scalar()
    borrowings = (await db.execute(
        select(Borrowing).where(and_(*conditions)).offset((page - 1) * limit).limit(limit)
    )).scalars().all()

    return BorrowingListResponse(
        data=[BorrowingResponse.model_validate(b) for b in borrowings],
        pagination=build_pagination(page, limit, total),
    )


# ── BORROWINGS ────────────────────────────────────────────────────────────────

@borrowings_router.get("/borrowings", response_model=BorrowingListResponse)
async def list_borrowings(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    student_id: str | None = Query(default=None),
    book_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_librarian),
):
    """
    Top-level borrowings resource.
    This is the endpoint your librarian uses for overdue reports, audit logs, etc.
    GET /borrowings?status=overdue → all overdue borrowings across the entire library
    """
    conditions = []
    if student_id:
        conditions.append(Borrowing.student_id == student_id)
    if book_id:
        conditions.append(Borrowing.book_id == book_id)
    if status_filter:
        conditions.append(Borrowing.status == status_filter)

    total = (await db.execute(
        select(func.count(Borrowing.id)).where(and_(*conditions)) if conditions
        else select(func.count(Borrowing.id))
    )).scalar()

    query = select(Borrowing)
    if conditions:
        query = query.where(and_(*conditions))
    borrowings = (await db.execute(query.offset((page - 1) * limit).limit(limit))).scalars().all()

    return BorrowingListResponse(
        data=[BorrowingResponse.model_validate(b) for b in borrowings],
        pagination=build_pagination(page, limit, total),
    )


@borrowings_router.post("/borrowings", response_model=BorrowingResponse, status_code=status.HTTP_201_CREATED)
async def borrow_book(
    body: BorrowingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """
    Borrow a book — the most business-rule-heavy endpoint in this domain.
    
    Business rules (this is our Process API layer in MuleSoft terms):
    1. Book must exist
    2. Student must exist  
    3. Available copies must be > 0 (422 if not — valid request, fails business rule)
    4. Student must not already have this book borrowed (409 Conflict)
    
    Notice we validate each rule separately with specific error codes.
    Generic "something went wrong" errors are useless to API consumers.
    Each error code is actionable.
    """
    # Rule: students can only borrow for themselves
    if current_user.role == "student" and current_user.subject != body.student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": {"code": "FORBIDDEN", "message": "Students can only borrow books for themselves."}}
        )

    # Rule 1: Book must exist
    book_result = await db.execute(select(Book).where(Book.id == body.book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Book not found."}})

    # Rule 2: Student must exist
    student_result = await db.execute(select(Student).where(Student.id == body.student_id))
    if not student_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail={"error": {"code": "STUDENT_NOT_FOUND", "message": "Student not found."}})

    # Rule 3: Available copies > 0
    available = await compute_available_copies(db, book)
    if available == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "error": {
                    "code": "NO_COPIES_AVAILABLE",
                    "message": f"No copies of '{book.title}' are currently available. All {book.total_copies} copies are borrowed."
                }
            }
        )

    # Rule 4: Student doesn't already have this book
    existing_borrow = await db.execute(
        select(Borrowing).where(
            and_(
                Borrowing.book_id == body.book_id,
                Borrowing.student_id == body.student_id,
                Borrowing.status == "active",
            )
        )
    )
    if existing_borrow.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": {"code": "ALREADY_BORROWED", "message": "This student already has this book borrowed."}}
        )

    borrowing = Borrowing(
        book_id=body.book_id,
        student_id=body.student_id,
        due_date=body.due_date,
        status="active",
    )
    db.add(borrowing)
    await db.flush()
    await db.refresh(borrowing)

    return BorrowingResponse.model_validate(borrowing)


@borrowings_router.get("/borrowings/{borrowing_id}", response_model=BorrowingResponse)
async def get_borrowing(
    borrowing_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    result = await db.execute(select(Borrowing).where(Borrowing.id == borrowing_id))
    borrowing = result.scalar_one_or_none()
    if not borrowing:
        raise HTTPException(status_code=404, detail={"error": {"code": "BORROWING_NOT_FOUND", "message": "Not found."}})

    # BOLA check: students can only see their own borrowings
    if current_user.role == "student" and current_user.subject != borrowing.student_id:
        raise HTTPException(status_code=403, detail={"error": {"code": "ACCESS_DENIED", "message": "Access denied."}})

    return BorrowingResponse.model_validate(borrowing)


@borrowings_router.patch("/borrowings/{borrowing_id}", response_model=BorrowingResponse)
async def update_borrowing(
    borrowing_id: str,
    body: BorrowingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """
    Update a borrowing — primarily used to return a book.
    
    The server-managed side effect:
    When status changes to 'returned', we automatically set returned_at
    to the current timestamp. The client never sends this field.
    
    This is what we documented in our OpenAPI spec with the description:
    "Setting status to 'returned' automatically triggers: returned_at set to
    current server timestamp"
    
    The spec made a promise. This code keeps that promise.
    """
    result = await db.execute(select(Borrowing).where(Borrowing.id == borrowing_id))
    borrowing = result.scalar_one_or_none()

    if not borrowing:
        raise HTTPException(status_code=404, detail={"error": {"code": "BORROWING_NOT_FOUND", "message": "Not found."}})

    # BOLA: students can only update their own borrowings
    if current_user.role == "student" and current_user.subject != borrowing.student_id:
        raise HTTPException(status_code=403, detail={"error": {"code": "ACCESS_DENIED", "message": "Access denied."}})

    new_status = body.status.value

    # Server-managed side effect: set returned_at when status → returned
    if new_status == "returned" and borrowing.status == "active":
        borrowing.returned_at = datetime.now(timezone.utc)

    borrowing.status = new_status

    await db.flush()
    await db.refresh(borrowing)
    return BorrowingResponse.model_validate(borrowing)
