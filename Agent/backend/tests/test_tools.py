"""Smoke tests for the agent tools."""

from app.tools.builtin import calculate, current_datetime


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
