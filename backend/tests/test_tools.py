"""Smoke tests for the agent tools."""

from uuid import uuid4

import pytest

from app.agent.runtime import reset_current_user_context, set_current_user_context
from app.services.auth import CurrentUserContext
from app.tools.builtin import calculate, current_datetime
from app.tools.freight_tools import get_freight_tools
from app.tools.registry import get_tools_for_context


def test_calculate():
    result = calculate.invoke({"expression": "2 + 2"})
    assert result == "4"


def test_calculate_sqrt():
    result = calculate.invoke({"expression": "sqrt(144)"})
    assert result == "12.0"


def test_calculate_rejects_dangerous():
    result = calculate.invoke({"expression": "__import__('os').system('ls')"})
    assert "not allowed" in result or "Error" in result


def test_current_datetime():
    result = current_datetime.invoke({})
    assert "UTC" in result


def test_freight_shipment_listing_tools_are_registered():
    names = {tool.name for tool in get_freight_tools()}

    assert "freight_query_shipments" in names
    assert "freight_list_shipments" in names
    assert "freight_list_today_shipments" in names
    assert "freight_send_carrier_followup" in names


def _viewer_context() -> CurrentUserContext:
    return CurrentUserContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="viewer",
        permissions=("dashboard:read", "freight:read"),
        session_id=uuid4(),
        email="viewer@example.com",
    )


def _member_context() -> CurrentUserContext:
    return CurrentUserContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="member",
        permissions=("dashboard:read", "freight:read", "freight:write", "email:connect"),
        session_id=uuid4(),
        email="member@example.com",
    )


def test_registry_filters_mutating_tools_for_viewer():
    tools = get_tools_for_context(_viewer_context())
    names = {t.name for t in tools}
    assert "freight_update_shipment_details" not in names
    assert "freight_archive_shipment" not in names
    assert "freight_send_customer_quote" not in names
    assert "save_to_memory" not in names
    assert "freight_get_overview" in names


@pytest.mark.asyncio
async def test_http_request_blocks_post_for_viewer():
    from app.tools.builtin import http_request

    token = set_current_user_context(_viewer_context())
    try:
        result = await http_request.ainvoke({"url": "https://example.com", "method": "POST"})
        assert "permission denied" in result.lower()
    finally:
        reset_current_user_context(token)


@pytest.mark.asyncio
async def test_http_request_allows_post_for_non_viewer(monkeypatch):
    from app.tools.builtin import http_request

    class FakeResp:
        headers = {"content-type": "text/plain"}
        text = "ok"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, _method, _url):
            return FakeResp()

    monkeypatch.setattr("app.tools.builtin.httpx.AsyncClient", FakeClient)

    token = set_current_user_context(_member_context())
    try:
        result = await http_request.ainvoke({"url": "https://example.com", "method": "POST"})
        assert result == "ok"
    finally:
        reset_current_user_context(token)
