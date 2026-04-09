"""Built-in tools for the agent.

Each tool is a LangChain Tool that the agent can call during reasoning.
Add new tools here and register them in registry.py.
"""

import httpx
from langchain_core.tools import tool


@tool
async def web_search(query: str) -> str:
    """Search the web for information. Use this when you need up-to-date facts,
    current events, or any information you're not confident about.

    Args:
        query: The search query string.
    """
    # Using DuckDuckGo instant answer API (no API key required)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1"},
        )
        data = resp.json()

    # Extract useful parts
    results = []
    if data.get("AbstractText"):
        results.append(data["AbstractText"])
    for topic in data.get("RelatedTopics", [])[:5]:
        if isinstance(topic, dict) and topic.get("Text"):
            results.append(topic["Text"])

    return "\n\n".join(results) if results else "No results found. Try a different query."


@tool
async def http_request(url: str, method: str = "GET") -> str:
    """Make an HTTP request to a URL and return the response.
    Use this to fetch data from APIs or web pages.

    Args:
        url: The URL to request.
        method: HTTP method (GET or POST).
    """
    if method.upper() not in ("GET", "POST"):
        return "Error: only GET and POST methods are supported."

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.request(method.upper(), url)
        content_type = resp.headers.get("content-type", "")

        if "json" in content_type:
            return str(resp.json())[:5000]
        return resp.text[:5000]


@tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression safely. Supports basic arithmetic,
    powers, and common math functions.

    Args:
        expression: A math expression like '2 + 2', 'sqrt(144)', '2**10'.
    """
    import math

    allowed_names = {
        k: v for k, v in math.__dict__.items() if not k.startswith("_")
    }
    allowed_names["abs"] = abs
    allowed_names["round"] = round

    try:
        # Compile to AST first to block dangerous code
        code = compile(expression, "<calc>", "eval")
        for name in code.co_names:
            if name not in allowed_names:
                return f"Error: '{name}' is not allowed in calculations."
        result = eval(code, {"__builtins__": {}}, allowed_names)  # noqa: S307
        return str(result)
    except Exception as e:
        return f"Error evaluating expression: {e}"


@tool
def current_datetime() -> str:
    """Get the current date and time. Use this when the user asks about
    the current time, today's date, or anything time-related."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S UTC")
