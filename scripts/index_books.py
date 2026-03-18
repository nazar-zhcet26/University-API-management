"""
scripts/index_books.py
-----------------------
Generate and store embeddings for all books in the catalog.

Run this once after:
  1. Applying the 002_add_book_embeddings migration
  2. Running the seeder (scripts/seed.py)

After that, new books are indexed automatically when added via the API.
Re-run this script if you update many book descriptions at once.

Usage:
  python scripts/index_books.py

  # Only index books without embeddings (skip already-indexed):
  python scripts/index_books.py --skip-existing

What this does:
  1. Fetches all books from the database
  2. For each book, builds a text representation (title + author + genre + description)
  3. Sends to Azure OpenAI text-embedding-ada-002 in batches of 16
  4. Stores the 1536-dimensional vector in the books.embedding column
  5. Reports progress and any errors
"""

import asyncio
import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app.models.models
from app.models.api_key import ApiKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, text
from app.models.models import Book
from app.services.ai.embeddings import generate_embeddings_batch, build_book_text
from datetime import datetime, timezone

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/university_db"
)


async def index_all_books(skip_existing: bool = False):
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with SessionLocal() as db:
        print("📚 Starting book indexing...")

        # Fetch books
        if skip_existing:
            result = await db.execute(
                select(Book).where(Book.embedding == None)  # noqa
            )
            print("  Mode: skipping already-indexed books")
        else:
            result = await db.execute(select(Book))
            print("  Mode: indexing all books (including re-indexing existing)")

        books = result.scalars().all()

        if not books:
            print("  No books to index.")
            return

        print(f"  Found {len(books)} books to index")
        print()

        # Process in batches of 16
        BATCH_SIZE = 16
        indexed = 0
        errors = 0

        for i in range(0, len(books), BATCH_SIZE):
            batch = books[i:i + BATCH_SIZE]

            # Build text representations for this batch
            texts = [build_book_text(book) for book in batch]

            try:
                # Generate embeddings (one API call for the whole batch)
                embeddings = await generate_embeddings_batch(texts)

                # Store each embedding
                now = datetime.now(timezone.utc)
                for book, embedding in zip(batch, embeddings):
                    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                    await db.execute(
                        text("""
                            UPDATE books
                            SET embedding = :embedding, embedding_updated_at = :updated_at
                            WHERE id = :book_id
                        """),
                        {
                            "embedding": embedding_str,
                            "updated_at": now,
                            "book_id": book.id,
                        }
                    )
                    indexed += 1
                    print(f"  ✅ [{indexed}/{len(books)}] {book.title[:60]}")

                await db.commit()

            except Exception as e:
                errors += 1
                print(f"  ❌ Batch {i//BATCH_SIZE + 1} failed: {e}")
                await db.rollback()

        print()
        print(f"✅ Indexing complete: {indexed} books indexed, {errors} errors")
        print()
        print("The library assistant can now search these books semantically.")
        print("Test it: GET /v1/assistant/search?q=machine+learning")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index book embeddings for semantic search")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip books that already have embeddings"
    )
    args = parser.parse_args()
    asyncio.run(index_all_books(skip_existing=args.skip_existing))
