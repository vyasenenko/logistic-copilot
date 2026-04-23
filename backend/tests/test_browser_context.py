from app.services.browser_context import (
    build_browser_context_excerpt,
    normalize_browser_context,
)


def test_normalize_browser_context_trims_and_deduplicates_snapshot() -> None:
    payload = normalize_browser_context(
        {
            "page_snapshot": {
                "url": "https://example.com/test",
                "title": " Example page ",
                "origin": "https://example.com",
                "selection_text": " Selected text " * 100,
                "visible_text_excerpt": " main body " * 2000,
                "headings": [" One ", "One", "Two", "", None],
                "meta_description": " Description ",
                "action_labels": ["Save", "Save", "Cancel", "Launch"],
            },
            "attach_hint": True,
        }
    )
    assert payload is not None
    snapshot = payload["page_snapshot"]
    assert snapshot["title"] == "Example page"
    assert snapshot["selection_text"].startswith("Selected text")
    assert snapshot["selection_text"].endswith("…")
    assert len(snapshot["headings"]) == 2
    assert snapshot["action_labels"] == ["Save", "Cancel", "Launch"]
    assert snapshot["page_type_hint"] in {"interactive_app", "selected_text_focus"}
    assert payload["attach_hint"] is True


def test_build_browser_context_excerpt_marks_missing_context() -> None:
    excerpt = build_browser_context_excerpt(None)
    assert excerpt["available"] is False
    assert "No browser page context" in excerpt["reason"]
