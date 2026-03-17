"""
app/services/ai/assistant.py
-----------------------------
RAG (Retrieval Augmented Generation) library assistant.

This is the core AI service. It orchestrates:
  1. Semantic search → find relevant books from the catalog
  2. Context building → format retrieved books for the LLM
  3. LLM generation → produce a natural language response
  4. Streaming → yield tokens as they're generated

The system prompt is carefully designed to:
  - Ground the LLM in ONLY the retrieved books (no hallucination)
  - Include availability information
  - Give the LLM a persona appropriate for a university library
  - Instruct it to suggest alternatives when nothing is available

Conversation history:
  The assistant supports multi-turn conversation.
  Each request can include previous messages so the LLM has context.
  "Can I borrow that book?" after a recommendation works because
  the LLM can see what it previously recommended.

  History is kept short (last 6 messages) to stay within token limits.
  For a university chatbot, students rarely need more than a few turns.
"""

from typing import AsyncGenerator
from openai import AsyncAzureOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.ai.search import semantic_search
from app.services.ai.embeddings import get_openai_client
from app.core.config import get_settings
from app.core.logging import get_logger

settings = get_settings()
logger = get_logger("ai.assistant")


SYSTEM_PROMPT = """You are the University Library Assistant — a helpful, knowledgeable AI assistant for the university library system.

Your role:
- Help students and faculty find books from the university library catalog
- Provide honest, accurate information about book availability
- Suggest relevant alternatives when a book is unavailable
- Be concise and friendly, like a knowledgeable librarian

CRITICAL RULES:
1. ONLY recommend books that appear in the CATALOG CONTEXT below
2. NEVER invent or suggest books not in the catalog context
3. ALWAYS mention availability (available copies vs total copies)
4. If no relevant books are found, say so honestly — do not make up alternatives
5. If a student asks about a book not in your context, tell them to speak with a librarian

Response style:
- Conversational and helpful, not robotic
- Lead with the most relevant recommendation
- Include title, author, and availability for each suggestion
- Keep responses focused — 2-3 sentences per recommendation is enough
- For unavailable books, mention when they might return if the student asks

You are part of the university's digital services platform. Be professional and supportive."""


def build_catalog_context(search_results) -> str:
    """
    Format search results into a context string for the LLM.

    This is the "Augmented" part of RAG — we're injecting real data
    from our database into the LLM's context window.

    The format matters: structured, clear, with explicit availability.
    """
    if not search_results:
        return "No relevant books found in the catalog for this query."

    lines = ["CATALOG CONTEXT (books from our library relevant to this query):"]
    lines.append("")

    for i, result in enumerate(search_results, 1):
        book = result.book
        availability = (
            f"{result.available_copies} of {book.total_copies} copies available"
            if result.is_available
            else f"Currently unavailable (0 of {book.total_copies} copies available)"
        )

        lines.append(f"[Book {i}]")
        lines.append(f"  Title: {book.title}")
        lines.append(f"  Author: {book.author}")
        lines.append(f"  Genre: {book.genre.replace('_', ' ').title()}")
        lines.append(f"  Availability: {availability}")
        if book.published_year:
            lines.append(f"  Published: {book.published_year}")
        lines.append(f"  Relevance: {result.similarity:.0%} match to your query")
        lines.append("")

    return "\n".join(lines)


async def ask_library_assistant(
    query: str,
    db: AsyncSession,
    conversation_history: list[dict] | None = None,
    available_only: bool = False,
) -> str:
    """
    Non-streaming version: returns the complete response as a string.
    Use for simple integrations or when streaming isn't needed.
    """
    client = get_openai_client()

    # Step 1: Retrieve relevant books
    search_results = await semantic_search(
        query=query,
        db=db,
        limit=5,
        available_only=available_only,
    )

    # Step 2: Build catalog context
    catalog_context = build_catalog_context(search_results)

    # Step 3: Build messages array
    messages = _build_messages(query, catalog_context, conversation_history)

    # Step 4: Generate response
    logger.info(
        "assistant_generating",
        extra={
            "query": query,
            "books_retrieved": len(search_results),
            "streaming": False,
        }
    )

    response = await client.chat.completions.create(
        model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
        messages=messages,
        max_tokens=600,
        temperature=0.3,  # low temperature = more factual, less creative
    )

    answer = response.choices[0].message.content

    logger.info(
        "assistant_response_generated",
        extra={
            "query": query,
            "response_length": len(answer),
            "tokens_used": response.usage.total_tokens,
        }
    )

    return answer


async def stream_library_assistant(
    query: str,
    db: AsyncSession,
    conversation_history: list[dict] | None = None,
    available_only: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Streaming version: yields text chunks as the LLM generates them.

    Used with FastAPI's StreamingResponse for real-time token streaming.

    Yields Server-Sent Events (SSE) format:
      data: {"type": "token", "content": "Based"}
      data: {"type": "token", "content": " on"}
      data: {"type": "token", "content": " our"}
      ...
      data: {"type": "sources", "books": [...]}
      data: {"type": "done"}

    The client-side JavaScript reads these events and appends tokens
    to the UI in real time — exactly like ChatGPT.
    """
    import json

    client = get_openai_client()

    # Step 1: Retrieve (this happens BEFORE streaming starts)
    search_results = await semantic_search(
        query=query,
        db=db,
        limit=5,
        available_only=available_only,
    )

    # Step 2: Build context
    catalog_context = build_catalog_context(search_results)
    messages = _build_messages(query, catalog_context, conversation_history)

    logger.info(
        "assistant_streaming_started",
        extra={"query": query, "books_retrieved": len(search_results)}
    )

    # Step 3: Stream the response token by token
    try:
        stream = await client.chat.completions.create(
            model=settings.AZURE_OPENAI_CHAT_DEPLOYMENT,
            messages=messages,
            max_tokens=600,
            temperature=0.3,
            stream=True,  # ← this is what enables streaming
        )

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                # Yield each token as an SSE event
                event = json.dumps({"type": "token", "content": delta.content})
                yield f"data: {event}\n\n"

        # After all tokens: send the source books so the UI can show them
        sources = [result.to_dict() for result in search_results]
        sources_event = json.dumps({"type": "sources", "books": sources})
        yield f"data: {sources_event}\n\n"

        # Signal completion
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

        logger.info(
            "assistant_streaming_completed",
            extra={"query": query, "sources_count": len(sources)}
        )

    except Exception as e:
        error_event = json.dumps({
            "type": "error",
            "message": "An error occurred while generating the response."
        })
        yield f"data: {error_event}\n\n"
        logger.error(
            "assistant_streaming_error",
            extra={"query": query, "error": str(e)},
            exc_info=True,
        )


def _build_messages(
    query: str,
    catalog_context: str,
    conversation_history: list[dict] | None,
) -> list[dict]:
    """
    Build the messages array for the chat completion API.

    Structure:
      [system prompt]
      [history: last 6 messages for context, if any]
      [user message with catalog context injected]

    We inject the catalog context INTO the user message rather than
    the system prompt because:
    - It's specific to this query (different searches → different context)
    - It ensures the LLM sees the context right before generating
    - The system prompt stays constant and cacheable
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Include recent conversation history (last 6 messages = 3 turns)
    if conversation_history:
        recent_history = conversation_history[-6:]
        messages.extend(recent_history)

    # The user message: query + catalog context
    user_content = f"""{query}

---
{catalog_context}
---
Please answer based only on the catalog context above."""

    messages.append({"role": "user", "content": user_content})

    return messages
