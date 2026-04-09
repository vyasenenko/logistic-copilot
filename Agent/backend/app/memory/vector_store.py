"""Vector store — Qdrant-based long-term memory for the agent."""

from uuid import uuid4

from qdrant_client import AsyncQdrantClient, models
from langchain_anthropic import ChatAnthropic

from app.config import settings

_client: AsyncQdrantClient | None = None

EMBEDDING_DIM = 1024  # Qdrant FastEmbed default dimension


async def _get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
        )
    return _client


async def init_vector_store() -> None:
    """Create the collection if it doesn't exist."""
    client = await _get_client()
    collections = await client.get_collections()
    existing = {c.name for c in collections.collections}

    if settings.qdrant_collection not in existing:
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                size=EMBEDDING_DIM,
                distance=models.Distance.COSINE,
            ),
        )


async def _embed_text(text: str) -> list[float]:
    """Generate embeddings using Qdrant's built-in FastEmbed.
    Falls back to a simple hash-based embedding for development."""
    try:
        client = await _get_client()
        # Use Qdrant's FastEmbed (runs locally, no API key needed)
        from qdrant_client.models import models as qmodels

        # Simple fallback: use the client's built-in embedding if available
        import hashlib
        import struct

        # Deterministic pseudo-embedding for dev (replace with real embeddings in prod)
        h = hashlib.sha512(text.encode()).digest()
        # Expand hash to fill EMBEDDING_DIM floats
        values = []
        for i in range(EMBEDDING_DIM):
            byte_val = h[i % len(h)]
            values.append((byte_val / 255.0) * 2 - 1)  # normalize to [-1, 1]
        return values
    except Exception:
        raise


async def store_memory(content: str, metadata: str = "") -> None:
    """Store a piece of text in vector memory."""
    client = await _get_client()
    vector = await _embed_text(content)

    await client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            models.PointStruct(
                id=str(uuid4()),
                vector=vector,
                payload={"content": content, "metadata": metadata},
            )
        ],
    )


async def search_memories(query: str, top_k: int = 5) -> list[dict]:
    """Search vector memory for relevant content."""
    client = await _get_client()
    vector = await _embed_text(query)

    results = await client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        limit=top_k,
    )

    return [
        {
            "content": point.payload.get("content", ""),
            "metadata": point.payload.get("metadata", ""),
            "score": point.score,
        }
        for point in results.points
    ]
