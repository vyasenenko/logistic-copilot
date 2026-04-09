"""Tool registry — single place to collect all tools for the agent."""

from langchain_core.tools import BaseTool

from app.tools.builtin import calculate, current_datetime, http_request, web_search
from app.tools.content_tools import (
    create_carousel,
    create_video_with_voiceover,
    list_available_voices,
    list_uploaded_videos,
)
from app.tools.memory_tools import save_to_memory, search_memory


def get_all_tools() -> list[BaseTool]:
    """Return all tools available to the agent."""
    return [
        web_search,
        http_request,
        calculate,
        current_datetime,
        save_to_memory,
        search_memory,
        create_carousel,
        create_video_with_voiceover,
        list_uploaded_videos,
        list_available_voices,
    ]
