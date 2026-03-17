"""
app/routers/assistant.py
-------------------------
Library Assistant API endpoints.

Endpoints:

  POST /v1/assistant/chat
    Non-streaming. Returns complete response.
    Good for: mobile apps, simple integrations, programmatic use.

  POST /v1/assistant/chat/stream
    Streaming via Server-Sent Events (SSE).
    Returns tokens as they're generated.
    Good for: web UI, showing real-time typing effect.

  GET /v1/assistant/search
    Pure semantic search — returns matching books without AI generation.
    Good for: autocomplete, book discovery, programmatic search.

  POST /v1/assistant/books/{book_id}/index
    Manually trigger re-indexing of a book's embedding.
    Called by librarians after updating a book's description.
    Auth: librarian or admin only.

Access control:
  All assistant endpoints require authentication.
  Any role (student, faculty, librarian, admin) can use the chat.
  Only librarians and admins can trigger re-indexing.

Rate limiting:
  Chat endpoints are rate-limited more aggressively than regular endpoints
  because each request makes an Azure OpenAI API call (costs money).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
from typing import Optional

from app.core.database import get_db
from app.core.security import TokenData
from app.dependencies.auth import require_any_authenticated, require_role
from app.models.models import Book
from sqlalchemy import select
from app.services.ai.assistant import ask_library_assistant, stream_library_assistant
from app.services.ai.search import semantic_search, index_book_embedding
from app.core.logging import get_logger
from app.core.context import get_request_id

logger = get_logger("api.assistant")

router = APIRouter(prefix="/assistant", tags=["Library Assistant"])


# ── Request / Response Schemas ─────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Natural language question about books",
        examples=["I need a book about machine learning for my CS301 course"]
    )
    conversation_history: list[ChatMessage] = Field(
        default=[],
        max_length=10,
        description="Previous messages for multi-turn conversation"
    )
    available_only: bool = Field(
        default=False,
        description="If true, only recommend books with available copies"
    )


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]
    query: str
    request_id: str


class SearchResponse(BaseModel):
    results: list[dict]
    query: str
    total: int


# ── POST /assistant/chat ───────────────────────────────────────────────────────
@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """
    Ask the library assistant a question. Returns complete response.

    Supports multi-turn conversation via conversation_history.

    Example request:
    ```json
    {
      "query": "I need a beginner-friendly machine learning book",
      "available_only": true
    }
    ```

    Example response:
    ```json
    {
      "answer": "I recommend 'Python Crash Course' by Eric Matthes...",
      "sources": [{"title": "Python Crash Course", "available_copies": 4, ...}]
    }
    ```
    """
    logger.info(
        "chat_request",
        extra={
            "request_id": get_request_id(),
            "user_id": current_user.subject,
            "role": current_user.role,
            "query_length": len(body.query),
            "has_history": len(body.conversation_history) > 0,
        }
    )

    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]

    try:
        # Run semantic search to get sources (we need them for the response)
        search_results = await semantic_search(
            query=body.query,
            db=db,
            limit=5,
            available_only=body.available_only,
        )

        # Generate AI response
        answer = await ask_library_assistant(
            query=body.query,
            db=db,
            conversation_history=history,
            available_only=body.available_only,
        )

        return ChatResponse(
            answer=answer,
            sources=[r.to_dict() for r in search_results],
            query=body.query,
            request_id=get_request_id(),
        )

    except Exception as e:
        logger.error(
            "chat_request_failed",
            extra={"request_id": get_request_id(), "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": {
                    "code": "AI_SERVICE_UNAVAILABLE",
                    "message": "The library assistant is temporarily unavailable. Please try again shortly.",
                    "request_id": get_request_id(),
                }
            }
        )


# ── POST /assistant/chat/stream ────────────────────────────────────────────────
@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """
    Ask the library assistant a question. Returns tokens as Server-Sent Events.

    The response is a stream of SSE events:

    ```
    data: {"type": "token", "content": "Based"}
    data: {"type": "token", "content": " on"}
    data: {"type": "token", "content": " our catalog..."}
    data: {"type": "sources", "books": [{...}, {...}]}
    data: {"type": "done"}
    ```

    Client-side JavaScript example:
    ```javascript
    const response = await fetch('/v1/assistant/chat/stream', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: "machine learning books" })
    });

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const text = decoder.decode(value);
      const lines = text.split('\\n').filter(l => l.startsWith('data: '));

      for (const line of lines) {
        const event = JSON.parse(line.slice(6));
        if (event.type === 'token') {
          appendToUI(event.content);  // append each token as it arrives
        }
      }
    }
    ```
    """
    logger.info(
        "chat_stream_request",
        extra={
            "request_id": get_request_id(),
            "user_id": current_user.subject,
            "query_length": len(body.query),
        }
    )

    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]

    return StreamingResponse(
        stream_library_assistant(
            query=body.query,
            db=db,
            conversation_history=history,
            available_only=body.available_only,
        ),
        media_type="text/event-stream",
        headers={
            # These headers are required for SSE to work correctly
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",      # disables Nginx response buffering
            "X-Request-ID": get_request_id(),
        }
    )


# ── GET /assistant/search ──────────────────────────────────────────────────────
@router.get("/search", response_model=SearchResponse)
async def semantic_book_search(
    q: str = Query(..., min_length=2, max_length=300, description="Search query"),
    limit: int = Query(default=5, ge=1, le=20),
    available_only: bool = Query(default=False),
    min_similarity: float = Query(default=0.65, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_any_authenticated),
):
    """
    Semantic book search — returns matching books without AI generation.

    Returns books ranked by semantic similarity to the query.
    Faster than /chat since no LLM generation step.

    Use for:
    - Autocomplete/suggestions as user types
    - Direct book search in the library portal
    - Programmatic book discovery

    Example: GET /v1/assistant/search?q=algorithms+data+structures&available_only=true
    """
    results = await semantic_search(
        query=q,
        db=db,
        limit=limit,
        min_similarity=min_similarity,
        available_only=available_only,
    )

    return SearchResponse(
        results=[r.to_dict() for r in results],
        query=q,
        total=len(results),
    )


# ── POST /assistant/books/{book_id}/index ──────────────────────────────────────
@router.post(
    "/books/{book_id}/index",
    status_code=status.HTTP_202_ACCEPTED,
)
async def index_book(
    book_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_role(["librarian", "admin"])),
):
    """
    Trigger re-indexing of a book's embedding.

    Call this after:
    - Adding a new book (handled automatically in library router)
    - Updating a book's title, author, or description
    - Fixing a book's genre or metadata

    Returns 202 Accepted — indexing may take a moment.
    Only librarians and admins can trigger this.
    """
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()

    if not book:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "BOOK_NOT_FOUND", "message": f"Book '{book_id}' not found."}}
        )

    await index_book_embedding(book, db)
    await db.commit()

    return {
        "message": f"Book '{book.title}' has been re-indexed for semantic search.",
        "book_id": book_id,
    }
