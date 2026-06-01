"""Tool registry — single place to collect tools for the logistics agent.

IMPORTANT: RBAC must be enforced server-side. Viewer users are read-only and must not
be able to invoke mutating tools (even if a client UI exposes them).
"""

from langchain_core.tools import BaseTool

from app.tools.builtin import current_datetime
from app.tools.freight_tools import get_freight_tools
from app.services.auth import CurrentUserContext


def _is_viewer(context: CurrentUserContext | None) -> bool:
    if context is None:
        return False
    return bool((context.role or "").strip().lower() == "viewer")


def get_all_tools_unfiltered() -> list[BaseTool]:
    """Return the full logistics tool list (no RBAC filtering).

    Keep this registry intentionally narrow. The agent is a logistics copilot, not a
    general automation/content bot, so browser, memory, web, HTTP, carousel, audio,
    and video tools should not be exposed here.
    """
    return [
        current_datetime,
        *get_freight_tools(),
    ]


def get_tools_for_context(context: CurrentUserContext | None) -> list[BaseTool]:
    """Return the tool list filtered by user context (RBAC).

    Viewer users must be strictly read-only: no freight mutations.
    """
    tools = get_all_tools_unfiltered()
    if not _is_viewer(context):
        return tools

    allowlist = {
        "current_datetime",
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
