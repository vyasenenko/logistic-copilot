"""Tool metadata API endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.tools.registry import get_all_tools

router = APIRouter()


def _label_from_name(name: str) -> str:
    normalized = (
        str(name)
        .strip()
        .replace("freight_", "")
        .replace("browser_", "")
        .replace("tool_", "")
        .replace("_", " ")
    )
    normalized = " ".join(part for part in normalized.split(" ") if part)
    if not normalized:
        return str(name)
    return " ".join(part.capitalize() for part in normalized.split(" "))


@router.get("/tools/metadata")
def get_tools_metadata():
    """Return stable metadata for all registered tools."""
    tools = []
    labels: dict[str, str] = {}
    for tool in get_all_tools():
        name = str(getattr(tool, "name", "") or "").strip()
        if not name:
            continue
        description = str(getattr(tool, "description", "") or "").strip()
        label = _label_from_name(name)
        labels[name] = label
        tools.append(
            {
                "name": name,
                "label": label,
                "description": description,
            }
        )
    return {"tools": tools, "tool_labels": labels}
