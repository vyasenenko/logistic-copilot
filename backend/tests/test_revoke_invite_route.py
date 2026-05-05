"""Ensure revoke-invite route is registered (integration with DB is optional)."""


def test_delete_invite_registered_in_openapi() -> None:
    from app.main import app

    paths = app.openapi().get("paths", {})
    invite_path = paths.get("/api/auth/invites/{invite_id}")
    assert invite_path is not None, "DELETE /api/auth/invites/{invite_id} missing from OpenAPI"
    assert "delete" in invite_path
