"""Tool registry — single place to collect all tools for the agent.

IMPORTANT: RBAC must be enforced server-side. Viewer users are read-only and must not
be able to invoke mutating tools (even if a client UI exposes them).
"""

from langchain_core.tools import BaseTool

from app.tools.browser_tools import get_browser_tools
from app.tools.builtin import calculate, current_datetime, http_request, web_search
from app.tools.memory_tools import save_to_memory, search_memory
from app.tools.freight_tools import get_freight_tools
from app.services.auth import CurrentUserContext


def _is_viewer(context: CurrentUserContext | None) -> bool:
    return bool((context.role or "").strip().lower() == "viewer")


def get_all_tools_unfiltered() -> list[BaseTool]:
    """Return the full tool list (no RBAC filtering)."""
    return [
        web_search,
        http_request,
        calculate,
        current_datetime,
        save_to_memory,
        search_memory,
        *get_browser_tools(),
        *get_freight_tools(),
    ]


def get_tools_for_context(context: CurrentUserContext | None) -> list[BaseTool]:
    """Return the tool list filtered by user context (RBAC).

    Viewer users must be strictly read-only: no freight mutations, no memory writes, and
    no arbitrary POST requests through http_request.
    """
    tools = get_all_tools_unfiltered()
    if not _is_viewer(context):
        return tools

    allowlist = {
        # Built-ins (read-only)
        "web_search",
        "calculate",
        "current_datetime",
        # Built-in HTTP (read-only for viewers; POST is blocked in-tool)
        "http_request",
        # Memory (read-only)
        "search_memory",
        # Browser context (read-only)
        "browser_get_current_page_context",
        "browser_get_current_page_excerpt",
        # Freight (read-only)
        "freight_domain_foundation",
        "freight_get_overview",
        "freight_list_shipments",
        "freight_query_shipments",
        "freight_get_shipment",
        "freight_get_shipment_by_token",
        "freight_get_shipment_thread",
        "freight_get_shipment_thread_by_token",
        "freight_search_shipments",
        "freight_list_shipments_by_city",
        "freight_list_today_shipments",
        "freight_summarize_shipment_case",
        "freight_diagnose_shipment_issue",
        "freight_diagnose_shipment_issue_by_token",
        "freight_search_archived_shipments",
        "freight_get_archived_shipment_by_token",
        "freight_summarize_archived_shipment",
        "freight_list_workflow_events",
        "freight_list_clients",
        "freight_list_carriers",
    }
    return [tool for tool in tools if getattr(tool, "name", None) in allowlist]


# Backwards-compatible alias used by older callers.
def get_all_tools(context: CurrentUserContext | None = None) -> list[BaseTool]:
    return get_tools_for_context(context)
