"""Agent state — shared data flowing through the LangGraph graph."""

from dataclasses import dataclass, field
from uuid import UUID

from langchain_core.messages import BaseMessage


@dataclass
class AgentState:
    """State that flows through every node of the agent graph.

    LangGraph passes this state between nodes. Each node can read and
    mutate it. The `messages` list is the core conversation history
    that the LLM sees.
    """

    messages: list[BaseMessage] = field(default_factory=list)
    conversation_id: UUID | None = None
    # How many tool-call loops we've done (safety cap)
    iteration: int = 0
    max_iterations: int = 15
    # Accumulated tool calls for the response
    tool_calls_log: list[dict] = field(default_factory=list)
