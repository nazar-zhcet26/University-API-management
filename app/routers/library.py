"""
routers/library.py
------------------
Library domain — Books and Borrowings.

This router demonstrates:
1. Business rule enforcement
2. Server-managed fields
3. Top-level borrowings resource pattern
4. Live AI indexing on book create/update
"""

from datetime import datetime, timezone
import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.core.security import TokenData
from app.dependencies.auth import (
    require_admin_or_librarian,
    require_any_authenticated,
)
from app.models.models import Book, Borrowing, Student
from app.schemas.schemas import (
    BookCreate, BookUpdate, BookResponse, BookListResponse,
    BorrowingCreate, BorrowingUpdate, BorrowingResponse, BorrowingListResponse,
    PaginationMeta,
)
from app.services.ai.search import index_book_embedding

router = APIRouter(tags=["Library - Books"])
borrowings_router = APIRouter(tags=["Library - Borrowings"])


def build_pagination(page, limit, total):
    return PaginationMeta(
        page=page,
        limit=limit,
        total_items=total,
        total_pages=math.ceil(total / limit) if total > 0 else 0,
    )


async def compute_available_copies(db: AsyncSession, book: Book) -> int:
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

    book_responses = []
    for book in books:
        avail = await compute_available_copies(db, book)
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
            detail={
                "error": {
                    "code": "ISBN_EXISTS",
                    "message": f"A book with ISBN '{body.isbn}' already exists."
                }
            }
        )

    try:
        book = Book(**body.model_dump())
        db.add(book)

        # Give the book an ID in the DB transaction
        await db.flush()
        await db.refresh(book)

        # Live indexing: make the assistant aware of the book immediately
        await index_book_embedding(book, db)

        # Persist both the book row and the embedding update
        await db.commit()
        await db.refresh(book)

        response = BookResponse.model_validate(book)
        response.available_copies = book.total_copies
        return response

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "BOOK_CREATE_OR_INDEX_FAILED",
                    "message": f"Book was not fully created/indexed: {str(e)}"
                }
            }
        )


@router.get("/books/{book_id}", response_model=BookResponse)
async def get_book(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Not found."}}
        )

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
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Not found."}}
        )

    update_data = body.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(book, field, value)

    try:
        await db.flush()
        await db.refresh(book)

        # Only re-index if fields that affect retrieval changed
        searchable_fields = {
            "title",
            "author",
            "genre",
            "isbn",
            "publisher",
            "published_year",
            "description",
        }

        if searchable_fields.intersection(update_data.keys()):
            await index_book_embedding(book, db)

        await db.commit()
        await db.refresh(book)

        response = BookResponse.model_validate(book)
        response.available_copies = await compute_available_copies(db, book)
        return response

    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "BOOK_UPDATE_OR_REINDEX_FAILED",
                    "message": f"Book update/re-index failed: {str(e)}"
                }
            }
        )


@router.delete("/books/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_admin_or_librarian),
):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Not found."}}
        )

    await db.delete(book)
    await db.commit()
    return None


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
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Not found."}}
        )

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
    if current_user.role == "student" and current_user.subject != body.student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Students can only borrow books for themselves."
                }
            }
        )

    book_result = await db.execute(select(Book).where(Book.id == body.book_id))
    book = book_result.scalar_one_or_none()
    if not book:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "BOOK_NOT_FOUND", "message": "Book not found."}}
        )

    student_result = await db.execute(select(Student).where(Student.id == body.student_id))
    if not student_result.scalar_one_or_none():
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "STUDENT_NOT_FOUND", "message": "Student not found."}}
        )

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
            detail={
                "error": {
                    "code": "ALREADY_BORROWED",
                    "message": "This student already has this book borrowed."
                }
            }
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
    await db.commit()

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
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "BORROWING_NOT_FOUND", "message": "Not found."}}
        )

    if current_user.role == "student" and current_user.subject != borrowing.student_id:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "ACCESS_DENIED", "message": "Access denied."}}
        )

    return BorrowingResponse.model_validate(borrowing)


@borrowings_router.patch("/borrowings/{borrowing_id}", response_model=BorrowingResponse)
async def update_borrowing(
    borrowing_id: str,
    body: BorrowingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    result = await db.execute(select(Borrowing).where(Borrowing.id == borrowing_id))
    borrowing = result.scalar_one_or_none()

    if not borrowing:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "BORROWING_NOT_FOUND", "message": "Not found."}}
        )

    if current_user.role == "student" and current_user.subject != borrowing.student_id:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "ACCESS_DENIED", "message": "Access denied."}}
        )

    new_status = body.status.value

    if new_status == "returned" and borrowing.status == "active":
        borrowing.returned_at = datetime.now(timezone.utc)

    borrowing.status = new_status

    await db.flush()
    await db.refresh(borrowing)
    await db.commit()
    return BorrowingResponse.model_validate(borrowing)
