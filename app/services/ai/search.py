"""
app/services/ai/search.py
--------------------------
Semantic search over the book catalog using pgvector.

The full search pipeline:

  1. User query: "machine learning for beginners"
  2. Generate query embedding (Azure OpenAI ada-002)
  3. PostgreSQL pgvector finds the N closest book embeddings
     using cosine similarity (HNSW index makes this fast)
  4. For each result, check real-time availability from borrowings table
  5. Return books sorted by semantic relevance + availability

Why combine semantic search with availability?
  Recommending a book that has 0 available copies is frustrating.
  We rank available books higher and clearly indicate availability.
  A student gets relevant AND obtainable recommendations.

Cosine similarity scoring:
  pgvector returns a distance (lower = more similar).
  We convert to a similarity score (higher = better match):
    similarity = 1 - cosine_distance
  Score of 1.0 = identical meaning
  Score of 0.0 = completely unrelated
  Typical good match: 0.75+
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, func, and_
from app.models.models import Book, Borrowing
from app.services.ai.embeddings import generate_embedding, build_book_text
from app.core.logging import get_logger

logger = get_logger("ai.search")


class BookSearchResult:
    """A book result with its semantic similarity score and availability."""

    def __init__(self, book: Book, similarity: float, available_copies: int):
        self.book = book
        self.similarity = round(similarity, 4)
        self.available_copies = available_copies
        self.is_available = available_copies > 0

    def to_dict(self) -> dict:
        return {
            "id": self.book.id,
            "title": self.book.title,
            "author": self.book.author,
            "isbn": self.book.isbn,
            "genre": self.book.genre,
            "publisher": self.book.publisher,
            "published_year": self.book.published_year,
            "total_copies": self.book.total_copies,
            "available_copies": self.available_copies,
            "is_available": self.is_available,
            "relevance_score": self.similarity,
        }


async def semantic_search(
    query: str,
    db: AsyncSession,
    limit: int = 5,
    min_similarity: float = 0.65,
    available_only: bool = False,
) -> list[BookSearchResult]:
    """
    Find books semantically similar to the query.

    Args:
        query: Natural language search query
        db: Database session
        limit: Maximum number of results to return
        min_similarity: Minimum relevance score (0-1). 0.65 filters obvious mismatches.
        available_only: If True, only return books with available copies

    Returns:
        List of BookSearchResult sorted by relevance (highest first)
    """
    logger.info("semantic_search_started", extra={"query": query, "limit": limit})

    # Step 1: Embed the query
    query_embedding = await generate_embedding(query)

    # Convert to pgvector format string: '[0.1, 0.2, ...]'
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    # Step 2: Vector similarity search using pgvector
    # <=> is pgvector's cosine distance operator
    # 1 - distance = cosine similarity
    # We fetch more than limit so we can filter by availability afterward
    fetch_limit = limit * 3  # fetch extra to account for availability filtering

    vector_query = text("""
        SELECT
            b.id,
            b.title,
            b.author,
            b.isbn,
            b.genre,
            b.publisher,
            b.published_year,
            b.total_copies,
            1 - (b.embedding <=> :embedding) AS similarity
        FROM books b
        WHERE
            b.embedding IS NOT NULL
            AND 1 - (b.embedding <=> :embedding) >= :min_similarity
        ORDER BY b.embedding <=> :embedding
        LIMIT :limit
    """)

    result = await db.execute(
        vector_query,
        {
            "embedding": embedding_str,
            "min_similarity": min_similarity,
            "limit": fetch_limit,
        }
    )
    rows = result.fetchall()

    if not rows:
        logger.info("semantic_search_no_results", extra={"query": query})
        return []

    # Step 3: Get real-time availability for each result
    book_ids = [row.id for row in rows]

    # Count active borrowings per book in one query (not N+1)
    availability_query = text("""
        SELECT book_id, COUNT(*) as borrowed_count
        FROM borrowings
        WHERE book_id = ANY(:book_ids) AND status = 'active'
        GROUP BY book_id
    """)
    avail_result = await db.execute(availability_query, {"book_ids": book_ids})
    borrowed_counts = {row.book_id: row.borrowed_count for row in avail_result}

    # Step 4: Build results with availability
    # Get full book objects for the matched IDs
    books_query = await db.execute(
        select(Book).where(Book.id.in_(book_ids))
    )
    books_by_id = {book.id: book for book in books_query.scalars().all()}

    search_results = []
    for row in rows:
        book = books_by_id.get(row.id)
        if not book:
            continue

        borrowed = borrowed_counts.get(row.id, 0)
        available = max(0, book.total_copies - borrowed)

        if available_only and available == 0:
            continue

        search_results.append(BookSearchResult(
            book=book,
            similarity=row.similarity,
            available_copies=available,
        ))

        if len(search_results) >= limit:
            break

    logger.info(
        "semantic_search_completed",
        extra={
            "query": query,
            "results_found": len(search_results),
            "top_score": search_results[0].similarity if search_results else 0,
        }
    )

    return search_results


async def index_book_embedding(book: Book, db: AsyncSession) -> None:
    """
    Generate and store the embedding for a single book.
    Called when a new book is added or a book's description changes.
    """
    from datetime import datetime, timezone

    book_text = build_book_text(book)
    embedding = await generate_embedding(book_text)
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    await db.execute(
        text("""
            UPDATE books
            SET embedding = :embedding, embedding_updated_at = :updated_at
            WHERE id = :book_id
        """),
        {
            "embedding": embedding_str,
            "updated_at": datetime.now(timezone.utc),
            "book_id": book.id,
        }
    )
    logger.info("book_indexed", extra={"book_id": book.id, "title": book.title})
