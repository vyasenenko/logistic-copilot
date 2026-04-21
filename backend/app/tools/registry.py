"""Tool registry — single place to collect all tools for the agent."""

from langchain_core.tools import BaseTool

from app.tools.builtin import calculate, current_datetime, http_request, web_search
from app.tools.memory_tools import save_to_memory, search_memory
from app.tools.freight_tools import get_freight_tools


def get_all_tools() -> list[BaseTool]:
    """Return all tools available to the agent."""
    return [
        web_search,
        http_request,
        calculate,
        current_datetime,
        save_to_memory,
        search_memory,
        *get_freight_tools(),
    ]
