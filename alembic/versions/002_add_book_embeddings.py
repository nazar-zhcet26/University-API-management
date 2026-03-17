"""
alembic/versions/002_add_book_embeddings.py
--------------------------------------------
Add vector embeddings support to the books table.

What this migration does:
1. Installs the pgvector extension in PostgreSQL
   (enables storing and searching embedding vectors)
2. Adds an 'embedding' column to the books table
   (stores the 1536-dimensional vector from text-embedding-ada-002)
3. Creates an HNSW index on the embedding column
   (makes similarity search fast — O(log n) instead of O(n))

Why 1536 dimensions?
  text-embedding-ada-002 (Azure OpenAI's embedding model) produces
  vectors with exactly 1536 numbers. Each number captures a different
  aspect of semantic meaning. This is the standard for OpenAI embeddings.

Why HNSW index?
  Without an index, finding the nearest vector requires comparing your
  query against EVERY stored vector — O(n). With 10,000 books that's
  10,000 comparisons per search query.
  
  HNSW (Hierarchical Navigable Small World) is an approximate nearest
  neighbor algorithm. It finds the closest vectors in O(log n) time
  with ~99% accuracy. For our use case (book search), approximate is
  perfectly fine — the difference between #1 and #2 closest book
  is imperceptible to the student.

  vector_cosine_ops = use cosine similarity (standard for text embeddings)
  Cosine similarity measures the angle between vectors, not their length.
  This is what you want for text — two texts about the same topic should
  be similar regardless of how long they are.
"""

from alembic import op
import sqlalchemy as sa

revision = '002_add_book_embeddings'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Install pgvector extension
    # This is a one-time operation per database
    # Requires the pgvector package to be installed in PostgreSQL
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Step 2: Add embedding column to books
    # vector(1536) = a fixed-length array of 1536 floats
    # NULL allowed — books without embeddings yet are simply not searchable
    op.execute("""
        ALTER TABLE books
        ADD COLUMN IF NOT EXISTS embedding vector(1536)
    """)

    # Step 3: Create HNSW index for fast similarity search
    # m=16: number of connections per layer (higher = better recall, more memory)
    # ef_construction=64: size of search during index build (higher = better index, slower build)
    # These are standard defaults — good for most use cases
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_books_embedding_hnsw
        ON books
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # Step 4: Track when each book was last indexed
    # Useful for knowing which books need re-embedding after description changes
    op.execute("""
        ALTER TABLE books
        ADD COLUMN IF NOT EXISTS embedding_updated_at TIMESTAMP WITH TIME ZONE
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE books DROP COLUMN IF EXISTS embedding_updated_at")
    op.execute("DROP INDEX IF EXISTS ix_books_embedding_hnsw")
    op.execute("ALTER TABLE books DROP COLUMN IF EXISTS embedding")
    # Note: we don't drop the vector extension on downgrade
    # other tables might be using it
