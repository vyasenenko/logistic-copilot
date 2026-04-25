"""Smoke tests for the agent tools."""

from app.tools.builtin import calculate, current_datetime
from app.tools.freight_tools import get_freight_tools


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
