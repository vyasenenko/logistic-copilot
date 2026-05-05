from uuid import uuid4

import pytest

from app.api import freight
from app.memory.database import EmailConnection, EmailThread, EmailTriageItem
from app.services.auth import CurrentUserContext


class FakePrivacySession:
    def __init__(self, *, thread, connection):
        self.thread = thread
        self.connection = connection

    async def get(self, model, key):
        if model is EmailThread and key == self.thread.id:
            return self.thread
        return None

    async def scalar(self, _query):
        return self.connection


def _context(*, user_id, organization_id, role="member"):
    return CurrentUserContext(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        permissions=(),
        session_id=uuid4(),
        email="user@example.com",
    )


@pytest.mark.asyncio
async def test_private_triage_email_is_owner_only():
    org_id = uuid4()
    owner_id = uuid4()
    other_user_id = uuid4()
    thread = EmailThread(id=uuid4(), organization_id=org_id, provider="outlook", mailbox="owner@example.com")
    item = EmailTriageItem(id=uuid4(), organization_id=org_id, thread_id=thread.id, email_message_id=uuid4())
    connection = EmailConnection(
        id=uuid4(),
        user_id=owner_id,
        organization_id=org_id,
        provider="outlook",
        mailbox="owner@example.com",
        visibility_mode="private",
    )
    session = FakePrivacySession(thread=thread, connection=connection)

    owner_access = await freight._triage_email_access(session, item, _context(user_id=owner_id, organization_id=org_id))
    other_access = await freight._triage_email_access(session, item, _context(user_id=other_user_id, organization_id=org_id, role="admin"))

    assert owner_access["can_view_body"] is True
    assert owner_access["can_take_action"] is True
    assert other_access["can_view_record"] is False
    assert other_access["can_take_action"] is False


@pytest.mark.asyncio
async def test_shared_ops_triage_email_allows_org_operator():
    org_id = uuid4()
    owner_id = uuid4()
    operator_id = uuid4()
    thread = EmailThread(id=uuid4(), organization_id=org_id, provider="outlook", mailbox="owner@example.com")
    item = EmailTriageItem(id=uuid4(), organization_id=org_id, thread_id=thread.id, email_message_id=uuid4())
    connection = EmailConnection(
        id=uuid4(),
        user_id=owner_id,
        organization_id=org_id,
        provider="outlook",
        mailbox="owner@example.com",
        visibility_mode="shared_ops",
    )
    session = FakePrivacySession(thread=thread, connection=connection)

    operator_access = await freight._triage_email_access(
        session,
        item,
        _context(user_id=operator_id, organization_id=org_id, role="member"),
    )

    assert operator_access["can_view_record"] is True
    assert operator_access["can_view_body"] is True
    assert operator_access["can_take_action"] is True


@pytest.mark.asyncio
async def test_metadata_only_triage_email_masks_body_and_actions_for_operator():
    org_id = uuid4()
    owner_id = uuid4()
    operator_id = uuid4()
    thread = EmailThread(id=uuid4(), organization_id=org_id, provider="outlook", mailbox="owner@example.com")
    item = EmailTriageItem(id=uuid4(), organization_id=org_id, thread_id=thread.id, email_message_id=uuid4())
    connection = EmailConnection(
        id=uuid4(),
        user_id=owner_id,
        organization_id=org_id,
        provider="outlook",
        mailbox="owner@example.com",
        visibility_mode="metadata_only",
    )
    session = FakePrivacySession(thread=thread, connection=connection)

    operator_access = await freight._triage_email_access(
        session,
        item,
        _context(user_id=operator_id, organization_id=org_id, role="admin"),
    )

    assert operator_access["can_view_record"] is True
    assert operator_access["can_view_body"] is False
    assert operator_access["can_take_action"] is False
