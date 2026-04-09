"""Memory-related tools — allow the agent to save and recall information."""

from langchain_core.tools import tool


@tool
async def save_to_memory(content: str, metadata: str = "") -> str:
    """Save important information to long-term memory for future reference.
    Use this when the user asks you to remember something, or when you
    encounter important facts that should be recalled later.

    Args:
        content: The information to remember.
        metadata: Optional tags or context (e.g., 'user preference', 'project info').
    """
    from app.memory.vector_store import store_memory

    await store_memory(content, metadata)
    return f"Saved to memory: {content[:100]}..."


@tool
async def search_memory(query: str) -> str:
    """Search long-term memory for previously saved information.
    Use this when you need to recall something saved earlier or find
    relevant context from past conversations.

    Args:
        query: What to search for in memory.
    """
    from app.memory.vector_store import search_memories

    results = await search_memories(query, top_k=5)

    if not results:
        return "No relevant memories found."

    formatted = []
    for i, r in enumerate(results, 1):
        formatted.append(f"{i}. {r['content']}")
        if r.get("metadata"):
            formatted.append(f"   (context: {r['metadata']})")

    return "\n".join(formatted)
