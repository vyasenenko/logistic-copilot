"""Unit tests for structured tool_start / tool_end SSE payloads."""

from app.agent.graph import _tool_end_sse_payload, _tool_start_sse_payload


def test_tool_start_extracts_name_and_input_dict() -> None:
    event = {"name": "freight_get_overview", "data": {"input": {}}}
    out = _tool_start_sse_payload(event)
    assert out["tool_name"] == "freight_get_overview"
    assert out["tool_input"] == {}


def test_tool_start_nested_input() -> None:
    event = {"name": "web_search", "data": {"input": {"query": "copilot"}}}
    out = _tool_start_sse_payload(event)
    assert out["tool_name"] == "web_search"
    assert out["tool_input"] == {"query": "copilot"}


def test_tool_start_fallback_tool_input_key() -> None:
    event = {"name": "calculate", "data": {"tool_input": {"expression": "1+1"}}}
    out = _tool_start_sse_payload(event)
    assert out["tool_input"] == {"expression": "1+1"}


def test_tool_end_includes_name_and_truncates() -> None:
    long = "x" * 5000
    event = {"name": "calculate", "data": {"output": long}}
    out = _tool_end_sse_payload(event, long)
    assert out["tool_name"] == "calculate"
    assert len(out["tool_output"]) == 4000
