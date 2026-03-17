"""
app/services/ai/embeddings.py
------------------------------
Embedding generation using Azure OpenAI.

What is an embedding?
  A numerical representation of text meaning.
  text-embedding-ada-002 converts any text into a list of 1536 floats.
  Texts about similar topics produce similar vectors.
  This is what powers semantic search — "find books similar to this query"
  becomes a mathematical distance calculation.

Azure OpenAI vs OpenAI directly:
  Your university uses Microsoft/Azure — so we use Azure OpenAI.
  Same models (GPT-4o, ada-002), same API shape, different endpoint and auth.
  Azure OpenAI keeps data within your Azure tenant (data sovereignty).
  Important for a university handling student data.

Batching:
  Generating embeddings costs API calls and money.
  We batch multiple texts into a single API call when indexing books.
  Azure OpenAI supports up to 16 inputs per embedding request.

Caching:
  Once a book's embedding is stored in PostgreSQL, we never regenerate it
  unless the book description changes. Embeddings are deterministic —
  the same text always produces the same vector.

Environment variables needed (add to .env):
  AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
  AZURE_OPENAI_API_KEY=your-key-here
  AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002
  AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
  AZURE_OPENAI_API_VERSION=2024-02-01
"""

from typing import Optional
from openai import AsyncAzureOpenAI
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger("ai.embeddings")

# ── Azure OpenAI Client ────────────────────────────────────────────────────────
# Single async client reused across requests
# AsyncAzureOpenAI handles connection pooling internally
_client: Optional[AsyncAzureOpenAI] = None


def get_openai_client() -> AsyncAzureOpenAI:
    """Get or create the Azure OpenAI async client."""
    global _client
    if _client is None:
        _client = AsyncAzureOpenAI(
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
    return _client


# ── Embedding Generation ───────────────────────────────────────────────────────

def build_book_text(book) -> str:
    """
    Build the text we embed for a book.

    What you embed matters a lot for search quality.
    We include title, author, genre, and description — all the semantic
    content a student might be trying to match.

    We don't include ISBN, total_copies, or published_year — those are
    metadata that don't contribute to semantic meaning.
    """
    parts = [
        f"Title: {book.title}",
        f"Author: {book.author}",
        f"Genre: {book.genre.replace('_', ' ')}",
    ]
    if book.publisher:
        parts.append(f"Publisher: {book.publisher}")
    if book.published_year:
        parts.append(f"Published: {book.published_year}")
    

    return ". ".join(parts)


async def generate_embedding(text: str) -> list[float]:
    """
    Generate a single embedding vector for a text string.
    Returns a list of 1536 floats.

    Used for:
    - Query embedding: convert user's question to a vector for similarity search
    - Single book indexing: when a new book is added
    """
    client = get_openai_client()

    response = await client.embeddings.create(
        input=text,
        model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
    )

    embedding = response.data[0].embedding
    logger.debug(
        "embedding_generated",
        extra={
            "text_length": len(text),
            "dimensions": len(embedding),
            "model": settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        }
    )
    return embedding


async def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts in a single API call.
    More efficient than calling generate_embedding() in a loop.
    Azure OpenAI supports up to 16 inputs per request.
    """
    client = get_openai_client()

    # Split into batches of 16
    BATCH_SIZE = 16
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]

        response = await client.embeddings.create(
            input=batch,
            model=settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        )

        # Response items come back in the same order as input
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

        logger.info(
            "embedding_batch_generated",
            extra={
                "batch_size": len(batch),
                "total_processed": len(all_embeddings),
                "total_texts": len(texts),
            }
        )

    return all_embeddings
