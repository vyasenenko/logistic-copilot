"""Invite-based authentication and organization context endpoints."""

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import (
    AccessRequest,
    AuthSession,
    EmailConnection,
    ExtensionAuthCode,
    Invite,
    Organization,
    OrganizationMember,
    OrganizationOutlookCredentials,
    OrganizationTmsIntegration,
    Shipment,
    User,
    WorkflowEvent,
    get_session,
)
from app.schemas import (
    AccessRequestApproveRequest,
    AccessRequestCreate,
    AccessRequestRecord,
    AdminCreateOrganizationInviteRequest,
    AdminInviteRecord,
    AdminOrganizationRecord,
    AdminOverviewResponse,
    AuthSessionResponse,
    CurrentUserResponse,
    EmailConnectionCreateRequest,
    EmailConnectionRecord,
    EmailConnectionUpdateRequest,
    ExtensionAuthorizeRequest,
    ExtensionAuthorizeResponse,
    ExtensionTokenRequest,
    InviteAcceptRequest,
    InviteCreateRequest,
    InviteCreateResponse,
    LoginRequest,
    OrganizationInviteRecord,
    OrganizationMemberRecord,
    OrganizationMemberRoleUpdate,
    OrganizationOutlookCredentialsRecord,
    OrganizationOutlookCredentialsUpdate,
    OrganizationRecord,
    OrganizationTmsInboundTokenRotateResponse,
    OrganizationTmsIntegrationRecord,
    OrganizationTmsIntegrationUpdate,
    OutlookUserSyncStatusResponse,
)
from app.services.auth import (
    CurrentUserContext,
    accept_invite,
    create_access_request,
    create_invite,
    create_session,
    get_current_user_context,
    get_current_user_context_for_token,
    hash_token,
    is_business_email,
    log_audit,
    login_with_password,
    require_permission,
    revoke_all_sessions_for_user,
    verify_turnstile,
)

from app.services.integration_crypto import encrypt_integration_secret
from app.services.outlook_org_crypto import encrypt_outlook_client_secret
from app.services.outlook_organization import (
    apply_graph_subscription_to_email_connection,
    build_outlook_graph_client,
    missing_fields_for_outlook_row,
    outlook_mailbox_conflict_other_org,
)

router = APIRouter()


def _is_platform_admin(context: CurrentUserContext) -> bool:
    return context.email.strip().lower() == settings.bootstrap_owner_email.strip().lower()


async def require_platform_admin(
    context: CurrentUserContext = Depends(get_current_user_context),
) -> CurrentUserContext:
    if not _is_platform_admin(context):
        raise HTTPException(status_code=403, detail="Platform admin access is required.")
    return context


def _session_response(*, context: CurrentUserContext, access_token: str, expires_at) -> AuthSessionResponse:
    return AuthSessionResponse(
        access_token=access_token,
        expires_at=expires_at,
        user_id=str(context.user_id),
        organization_id=str(context.organization_id),
        role=context.role,
        permissions=list(context.permissions),
        email=context.email,
    )


def _email_connection_record(connection: EmailConnection) -> EmailConnectionRecord:
    auto_sync_enabled = False
    if connection.status == "active" and connection.graph_subscription_id:
        expires_at = connection.subscription_expires_at
        auto_sync_enabled = expires_at is None or expires_at > datetime.now(timezone.utc)
    return EmailConnectionRecord(
        id=str(connection.id),
        user_id=str(connection.user_id),
        organization_id=str(connection.organization_id),
        provider=connection.provider,
        mailbox=connection.mailbox,
        status=connection.status,
        visibility_mode=(connection.visibility_mode or "private"),
        graph_subscription_id=connection.graph_subscription_id,
        subscription_expires_at=connection.subscription_expires_at,
        auto_sync_enabled=auto_sync_enabled,
        metadata=dict(connection.metadata_json or {}),
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _organization_member_record(member: OrganizationMember, user: User) -> OrganizationMemberRecord:
    return OrganizationMemberRecord(
        id=str(member.id),
        user_id=str(user.id),
        organization_id=str(member.organization_id),
        email=user.email,
        name=user.name,
        role=member.role,
        status=member.status,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


def _organization_invite_record(invite: Invite) -> OrganizationInviteRecord:
    return OrganizationInviteRecord(
        id=str(invite.id),
        organization_id=str(invite.organization_id),
        email=invite.email,
        role=invite.role,
        status=invite.status,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        created_at=invite.created_at,
    )


def _organization_tms_integration_record(
    row: OrganizationTmsIntegration | None,
) -> OrganizationTmsIntegrationRecord:
    if row is None:
        return OrganizationTmsIntegrationRecord()
    return OrganizationTmsIntegrationRecord(
        tms_system=row.tms_system or "generic",
        base_url=row.base_url,
        api_key_configured=bool(row.api_key_encrypted),
        inbound_token_configured=bool(row.inbound_token_hash),
        status=row.status,
        metadata=dict(row.metadata_json or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _domain_from_email(email: str) -> str:
    return email.split("@", 1)[1].strip().lower() if "@" in email else ""


def _user_mailbox_for_org(context: CurrentUserContext, organization: Organization) -> str:
    mailbox = context.email.strip().lower()
    org_domain = (organization.primary_domain or "").strip().lower()
    if not mailbox or "@" not in mailbox:
        raise HTTPException(status_code=400, detail="Current user email cannot be used as an Outlook mailbox.")
    if org_domain and _domain_from_email(mailbox) != org_domain:
        raise HTTPException(
            status_code=400,
            detail="Current user email must match the organization domain before Outlook sync can be enabled.",
        )
    return mailbox


async def _current_user_outlook_connection(
    session: AsyncSession,
    context: CurrentUserContext,
    *,
    create: bool = False,
) -> EmailConnection | None:
    organization = await session.get(Organization, context.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    mailbox = _user_mailbox_for_org(context, organization)
    connection = await session.scalar(
        select(EmailConnection).where(
            EmailConnection.user_id == context.user_id,
            EmailConnection.organization_id == context.organization_id,
            EmailConnection.provider == "outlook",
            EmailConnection.mailbox == mailbox,
        )
    )
    if connection is None and create:
        connection = EmailConnection(
            user_id=context.user_id,
            organization_id=context.organization_id,
            provider="outlook",
            mailbox=mailbox,
            status="inactive",
            visibility_mode="private",
            metadata_json={"source": "user_outlook_sync"},
        )
        session.add(connection)
        await session.flush()
    return connection


async def _outlook_user_sync_status_response(
    session: AsyncSession,
    context: CurrentUserContext,
    *,
    connection: EmailConnection | None = None,
    message: str | None = None,
) -> OutlookUserSyncStatusResponse:
    organization = await session.get(Organization, context.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    mailbox = context.email.strip().lower()
    row = await session.get(OrganizationOutlookCredentials, context.organization_id)
    microsoft_configured = not missing_fields_for_outlook_row(row)
    webhook_configured = bool(settings.microsoft_webhook_notification_url)
    domain_ok = not organization.primary_domain or _domain_from_email(mailbox) == organization.primary_domain.strip().lower()
    if connection is None:
        connection = await _current_user_outlook_connection(session, context, create=False) if domain_ok else None
    status_value = "not_configured"
    if not microsoft_configured:
        status_value = "needs_microsoft_setup"
    elif not webhook_configured:
        status_value = "needs_webhook_url"
    elif not domain_ok:
        status_value = "domain_mismatch"
    elif connection and connection.status == "active" and connection.graph_subscription_id:
        expires_at = connection.subscription_expires_at
        status_value = "auto_sync_on" if expires_at is None or expires_at > datetime.now(timezone.utc) else "expired"
    elif connection:
        status_value = "auto_sync_off"
    else:
        status_value = "ready"
    return OutlookUserSyncStatusResponse(
        mailbox=mailbox,
        organization_domain=organization.primary_domain,
        connection=_email_connection_record(connection) if connection else None,
        microsoft_configured=microsoft_configured,
        webhook_public_url_configured=webhook_configured,
        can_enable=microsoft_configured and webhook_configured and domain_ok,
        status=status_value,
        message=message,
    )


def _require_internal_admin_secret(x_admin_secret: str | None = Header(default=None)) -> None:
    if not settings.api_secret_key or x_admin_secret != settings.api_secret_key:
        raise HTTPException(status_code=403, detail="Internal admin secret is required.")


def _access_request_record(access_request: AccessRequest) -> AccessRequestRecord:
    return AccessRequestRecord(
        id=str(access_request.id),
        email=access_request.email,
        company_name=access_request.company_name,
        domain=access_request.domain,
        status=access_request.status,
        review_notes=access_request.review_notes,
        created_at=access_request.created_at,
        updated_at=access_request.updated_at,
    )


def _admin_invite_record(invite: Invite, organization: Organization | None = None) -> AdminInviteRecord:
    return AdminInviteRecord(
        id=str(invite.id),
        organization_id=str(invite.organization_id),
        organization_name=organization.name if organization is not None else None,
        email=invite.email,
        role=invite.role,
        status=invite.status,
        expires_at=invite.expires_at,
        accepted_at=invite.accepted_at,
        created_at=invite.created_at,
    )


@router.post("/auth/access-requests", response_model=AccessRequestRecord)
async def request_access(
    payload: AccessRequestCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AccessRequestRecord:
    await verify_turnstile(payload.turnstile_token, request=request)
    access_request = await create_access_request(
        session,
        email=payload.email,
        company_name=payload.company_name,
        request=request,
        payload=payload.payload,
    )
    return _access_request_record(access_request)


@router.get("/admin/overview", response_model=AdminOverviewResponse)
async def admin_overview(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_platform_admin),
) -> AdminOverviewResponse:
    _ = context
    return AdminOverviewResponse(
        organizations_count=await session.scalar(select(func.count()).select_from(Organization)) or 0,
        users_count=await session.scalar(select(func.count()).select_from(User)) or 0,
        pending_access_requests_count=await session.scalar(
            select(func.count()).select_from(AccessRequest).where(AccessRequest.status == "pending")
        )
        or 0,
        pending_invites_count=await session.scalar(
            select(func.count()).select_from(Invite).where(Invite.status == "pending")
        )
        or 0,
        active_email_connections_count=await session.scalar(
            select(func.count()).select_from(EmailConnection).where(EmailConnection.status == "active")
        )
        or 0,
        shipments_count=await session.scalar(select(func.count()).select_from(Shipment)) or 0,
        workflow_events_count=await session.scalar(select(func.count()).select_from(WorkflowEvent)) or 0,
    )


@router.get("/admin/organizations", response_model=list[AdminOrganizationRecord])
async def admin_list_organizations(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_platform_admin),
) -> list[AdminOrganizationRecord]:
    _ = context
    orgs_result = await session.execute(select(Organization).order_by(Organization.created_at.desc()))
    orgs = list(orgs_result.scalars().all())
    if not orgs:
        return []
    org_ids = [org.id for org in orgs]

    def _count_map(rows) -> dict[UUID, int]:
        return {organization_id: int(total or 0) for organization_id, total in rows}

    members = _count_map(
        (
            await session.execute(
                select(OrganizationMember.organization_id, func.count(OrganizationMember.id))
                .where(OrganizationMember.organization_id.in_(org_ids))
                .group_by(OrganizationMember.organization_id)
            )
        ).all()
    )
    email_connections = _count_map(
        (
            await session.execute(
                select(EmailConnection.organization_id, func.count(EmailConnection.id))
                .where(EmailConnection.organization_id.in_(org_ids))
                .group_by(EmailConnection.organization_id)
            )
        ).all()
    )
    shipments = _count_map(
        (
            await session.execute(
                select(Shipment.organization_id, func.count(Shipment.id))
                .where(Shipment.organization_id.in_(org_ids))
                .group_by(Shipment.organization_id)
            )
        ).all()
    )
    active_shipments = _count_map(
        (
            await session.execute(
                select(Shipment.organization_id, func.count(Shipment.id))
                .where(Shipment.organization_id.in_(org_ids), Shipment.is_archived.is_(False))
                .group_by(Shipment.organization_id)
            )
        ).all()
    )
    workflow_events = _count_map(
        (
            await session.execute(
                select(WorkflowEvent.organization_id, func.count(WorkflowEvent.id))
                .where(WorkflowEvent.organization_id.in_(org_ids))
                .group_by(WorkflowEvent.organization_id)
            )
        ).all()
    )
    return [
        AdminOrganizationRecord(
            id=str(org.id),
            name=org.name,
            primary_domain=org.primary_domain,
            status=org.status,
            created_at=org.created_at,
            updated_at=org.updated_at,
            members_count=members.get(org.id, 0),
            email_connections_count=email_connections.get(org.id, 0),
            shipments_count=shipments.get(org.id, 0),
            active_shipments_count=active_shipments.get(org.id, 0),
            workflow_events_count=workflow_events.get(org.id, 0),
        )
        for org in orgs
    ]


@router.get("/admin/access-requests", response_model=list[AccessRequestRecord])
async def admin_list_access_requests(
    include_resolved: bool = False,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_platform_admin),
) -> list[AccessRequestRecord]:
    _ = context
    query = select(AccessRequest).order_by(AccessRequest.created_at.desc())
    if not include_resolved:
        query = query.where(AccessRequest.status == "pending")
    result = await session.execute(query)
    return [_access_request_record(item) for item in result.scalars().all()]


@router.get("/admin/invites", response_model=list[AdminInviteRecord])
async def admin_list_invites(
    include_accepted: bool = False,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_platform_admin),
) -> list[AdminInviteRecord]:
    _ = context
    query = select(Invite, Organization).join(Organization, Organization.id == Invite.organization_id)
    if not include_accepted:
        query = query.where(Invite.status == "pending")
    result = await session.execute(query.order_by(Invite.created_at.desc()))
    return [_admin_invite_record(invite, organization) for invite, organization in result.all()]


@router.post("/admin/organizations/invite-owner", response_model=InviteCreateResponse)
async def admin_create_organization_and_invite_owner(
    payload: AdminCreateOrganizationInviteRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_platform_admin),
) -> InviteCreateResponse:
    normalized_domain = payload.organization_domain.strip().lower()
    normalized_email = payload.owner_email.strip().lower()
    if not normalized_domain or "." not in normalized_domain:
        raise HTTPException(status_code=400, detail="A valid organization domain is required.")
    if not normalized_email.endswith(f"@{normalized_domain}"):
        raise HTTPException(status_code=400, detail="Owner email must match the organization domain.")

    existing_user = await session.scalar(select(User).where(User.email == normalized_email))
    if existing_user is not None:
        existing_member = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == existing_user.id,
                OrganizationMember.status == "active",
            )
        )
        if existing_member is not None:
            raise HTTPException(status_code=409, detail="This owner user already belongs to an organization.")

    organization = await session.scalar(select(Organization).where(Organization.primary_domain == normalized_domain))
    if organization is None:
        organization = Organization(
            name=payload.organization_name.strip(),
            primary_domain=normalized_domain,
            status="active",
        )
        session.add(organization)
        await session.flush()
    else:
        organization.name = payload.organization_name.strip()
        organization.status = "active"

    invite, token = await create_invite(
        session,
        organization_id=organization.id,
        email=normalized_email,
        role=payload.role or "owner",
        actor=context,
        request=request,
        allow_owner_role=True,
    )
    return InviteCreateResponse(
        id=str(invite.id),
        organization_id=str(invite.organization_id),
        email=invite.email,
        role=invite.role,
        expires_at=invite.expires_at,
        invite_token=token,
    )


@router.post("/auth/admin/access-requests/{request_id}/approve", response_model=InviteCreateResponse)
async def approve_access_request(
    request_id: UUID,
    payload: AccessRequestApproveRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    _admin: None = Depends(_require_internal_admin_secret),
) -> InviteCreateResponse:
    access_request = await session.get(AccessRequest, request_id)
    if access_request is None:
        raise HTTPException(status_code=404, detail="Access request not found.")
    if access_request.status not in {"pending", "approved"}:
        raise HTTPException(status_code=400, detail=f"Access request is {access_request.status}.")
    if not access_request.domain:
        raise HTTPException(status_code=400, detail="Access request has no business domain.")

    organization = await session.scalar(
        select(Organization).where(Organization.primary_domain == access_request.domain)
    )
    if organization is None:
        organization = Organization(
            name=(payload.organization_name or access_request.company_name).strip(),
            primary_domain=access_request.domain,
            status="active",
        )
        session.add(organization)
        await session.flush()

    access_request.status = "approved"
    access_request.review_notes = payload.review_notes

    invite, token = await create_invite(
        session,
        organization_id=organization.id,
        email=access_request.email,
        role=payload.role or "owner",
        actor=None,
        request=request,
        allow_owner_role=True,
    )
    return InviteCreateResponse(
        id=str(invite.id),
        organization_id=str(invite.organization_id),
        email=invite.email,
        role=invite.role,
        expires_at=invite.expires_at,
        invite_token=token,
    )


@router.get("/auth/organization-members", response_model=list[OrganizationMemberRecord])
async def list_organization_members(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_permission("members:invite")),
) -> list[OrganizationMemberRecord]:
    result = await session.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(
            OrganizationMember.organization_id == context.organization_id,
            OrganizationMember.status == "active",
        )
        .order_by(OrganizationMember.created_at.asc())
    )
    return [_organization_member_record(member, user) for member, user in result.all()]


@router.patch("/auth/organization-members/{member_id}", response_model=OrganizationMemberRecord)
async def update_organization_member_role(
    member_id: UUID,
    payload: OrganizationMemberRoleUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_permission("members:invite")),
) -> OrganizationMemberRecord:
    member = await session.get(OrganizationMember, member_id)
    if member is None or member.organization_id != context.organization_id:
        raise HTTPException(status_code=404, detail="Organization member not found.")
    if member.user_id == context.user_id:
        raise HTTPException(status_code=400, detail="You cannot change your own role.")
    new_role = payload.role.strip().lower()
    if new_role not in {"admin", "member", "viewer"}:
        raise HTTPException(status_code=400, detail="Unsupported member role.")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="Owner role cannot be changed from user management.")
    user = await session.get(User, member.user_id)
    organization = await session.get(Organization, context.organization_id)
    if user is None or organization is None:
        raise HTTPException(status_code=404, detail="Member user or organization not found.")
    organization_domain = (organization.primary_domain or "").strip().lower()
    user_domain = _domain_from_email(user.email)
    requires_viewer_only = not is_business_email(user.email) or bool(
        organization_domain and user_domain != organization_domain
    )
    if requires_viewer_only and new_role != "viewer":
        raise HTTPException(
            status_code=400,
            detail="This user can only have the Viewer role.",
        )
    previous_role = member.role
    member.role = new_role
    member.updated_at = datetime.now(timezone.utc)
    await log_audit(
        session,
        event_type="member_role_changed",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
        payload={
            "member_id": str(member.id),
            "member_user_id": str(member.user_id),
            "member_email": user.email,
            "previous_role": previous_role,
            "new_role": new_role,
        },
    )
    await session.commit()
    await session.refresh(member)
    return _organization_member_record(member, user)


async def _tear_down_outlook_auto_sync_best_effort(
    session: AsyncSession,
    *,
    organization_id: UUID,
    connection: EmailConnection,
) -> None:
    """Deactivate mailbox connection and remove Graph webhook when revoking membership."""
    subscription_id = connection.graph_subscription_id
    if subscription_id:
        try:
            outlook = await build_outlook_graph_client(
                session,
                organization_id,
                mailbox=connection.mailbox,
                email_connection_id=connection.id,
            )
            await outlook.delete_subscription(subscription_id)
        except RuntimeError:
            pass
    connection.status = "inactive"
    connection.graph_subscription_id = None
    connection.subscription_expires_at = None
    connection.updated_at = datetime.now(timezone.utc)


@router.delete("/auth/organization-members/{member_id}", response_model=OrganizationMemberRecord)
async def remove_organization_member(
    member_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_permission("members:invite")),
) -> OrganizationMemberRecord:
    member = await session.get(OrganizationMember, member_id)
    if member is None or member.organization_id != context.organization_id:
        raise HTTPException(status_code=404, detail="Organization member not found.")
    if member.user_id == context.user_id:
        raise HTTPException(status_code=400, detail="You cannot remove your own access.")
    if member.role == "owner":
        raise HTTPException(status_code=400, detail="Owner access cannot be removed from user management.")
    user = await session.get(User, member.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Member user not found.")
    previous_status = member.status
    member.status = "inactive"
    member.updated_at = datetime.now(timezone.utc)
    email_connections = await session.execute(
        select(EmailConnection).where(
            EmailConnection.user_id == member.user_id,
            EmailConnection.organization_id == context.organization_id,
        )
    )
    for connection in email_connections.scalars().all():
        await _tear_down_outlook_auto_sync_best_effort(
            session,
            organization_id=context.organization_id,
            connection=connection,
        )
    active_sessions = await session.execute(
        select(AuthSession).where(
            AuthSession.user_id == member.user_id,
            AuthSession.organization_id == context.organization_id,
            AuthSession.revoked_at.is_(None),
        )
    )
    now = datetime.now(timezone.utc)
    for auth_session in active_sessions.scalars().all():
        auth_session.revoked_at = now
    await log_audit(
        session,
        event_type="member_removed",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
        payload={
            "member_id": str(member.id),
            "member_user_id": str(member.user_id),
            "member_email": user.email,
            "previous_status": previous_status,
        },
    )
    await session.commit()
    await session.refresh(member)
    return _organization_member_record(member, user)


@router.get("/auth/invites", response_model=list[OrganizationInviteRecord])
async def list_organization_invites(
    status: str = "pending",
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_permission("members:invite")),
) -> list[OrganizationInviteRecord]:
    query = select(Invite).where(Invite.organization_id == context.organization_id)
    normalized_status = status.strip().lower()
    if normalized_status and normalized_status != "all":
        query = query.where(Invite.status == normalized_status)
    result = await session.execute(query.order_by(Invite.created_at.desc()))
    return [_organization_invite_record(invite) for invite in result.scalars().all()]


@router.post("/auth/invites", response_model=InviteCreateResponse)
async def invite_user(
    payload: InviteCreateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_permission("members:invite")),
) -> InviteCreateResponse:
    try:
        organization_id = UUID(payload.organization_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid organization id.") from exc
    if organization_id != context.organization_id:
        raise HTTPException(status_code=403, detail="Cannot invite users into another organization.")
    invite, token = await create_invite(
        session,
        organization_id=organization_id,
        email=payload.email,
        role=payload.role,
        actor=context,
        request=request,
    )
    return InviteCreateResponse(
        id=str(invite.id),
        organization_id=str(invite.organization_id),
        email=invite.email,
        role=invite.role,
        expires_at=invite.expires_at,
        invite_token=token,
    )


@router.delete("/auth/invites/{invite_id}", status_code=204)
async def revoke_organization_invite(
    invite_id: UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(require_permission("members:invite")),
) -> None:
    invite = await session.get(Invite, invite_id)
    if invite is None:
        raise HTTPException(status_code=404, detail="Invite not found.")
    if invite.organization_id != context.organization_id:
        raise HTTPException(status_code=403, detail="Cannot revoke invites for another organization.")
    if invite.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending invites can be revoked.")
    invite.status = "revoked"
    invite.updated_at = datetime.now(timezone.utc)
    await log_audit(
        session,
        event_type="invite_revoked",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
        payload={"invite_id": str(invite.id), "email": invite.email},
    )
    await session.commit()


@router.post("/auth/invites/accept", response_model=AuthSessionResponse)
async def accept_invite_endpoint(
    payload: InviteAcceptRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthSessionResponse:
    await verify_turnstile(payload.turnstile_token, request=request)
    user, auth_session, token = await accept_invite(
        session,
        token=payload.token,
        name=payload.name,
        password=payload.password,
        request=request,
    )
    context = await get_current_user_context(authorization=f"Bearer {token}", session=session)
    return _session_response(context=context, access_token=token, expires_at=auth_session.expires_at)


@router.post("/auth/login", response_model=AuthSessionResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthSessionResponse:
    await verify_turnstile(payload.turnstile_token, request=request)
    _user, auth_session, token = await login_with_password(
        session,
        email=payload.email,
        password=payload.password,
        request=request,
    )
    context = await get_current_user_context(authorization=f"Bearer {token}", session=session)
    return _session_response(context=context, access_token=token, expires_at=auth_session.expires_at)


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> None:
    await revoke_all_sessions_for_user(session, context=context, request=request)


@router.get("/auth/me", response_model=CurrentUserResponse)
async def me(context: CurrentUserContext = Depends(get_current_user_context)) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=str(context.user_id),
        organization_id=str(context.organization_id),
        role=context.role,
        permissions=list(context.permissions),
        email=context.email,
    )


@router.post("/auth/extension/authorize", response_model=ExtensionAuthorizeResponse)
async def authorize_extension_session(
    payload: ExtensionAuthorizeRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> ExtensionAuthorizeResponse:
    """Create a short-lived one-time code for Chrome Identity redirect flow."""
    if not payload.redirect_uri.startswith("https://") and not payload.redirect_uri.startswith("chrome-extension://"):
        raise HTTPException(status_code=400, detail="Unsupported extension redirect_uri.")
    raw_code = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    session.add(
        ExtensionAuthCode(
            user_id=context.user_id,
            organization_id=context.organization_id,
            code_hash=hash_token(raw_code),
            state=payload.state,
            redirect_uri=payload.redirect_uri,
            expires_at=expires_at,
        )
    )
    await log_audit(
        session,
        event_type="extension_auth_code_created",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
    )
    await session.commit()
    separator = "&" if "?" in payload.redirect_uri else "?"
    redirect_url = f"{payload.redirect_uri}{separator}{urlencode({'code': raw_code, 'state': payload.state})}"
    return ExtensionAuthorizeResponse(redirect_url=redirect_url, expires_at=expires_at)


@router.post("/auth/extension/token", response_model=AuthSessionResponse)
async def exchange_extension_code(
    payload: ExtensionTokenRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthSessionResponse:
    now = datetime.now(timezone.utc)
    code_row = await session.scalar(
        select(ExtensionAuthCode).where(
            ExtensionAuthCode.code_hash == hash_token(payload.code),
            ExtensionAuthCode.consumed_at.is_(None),
            ExtensionAuthCode.expires_at > now,
        )
    )
    if code_row is None or code_row.state != payload.state:
        raise HTTPException(status_code=401, detail="Invalid or expired extension authorization code.")
    user = await session.get(User, code_row.user_id)
    member = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == code_row.user_id,
            OrganizationMember.organization_id == code_row.organization_id,
            OrganizationMember.status == "active",
        )
    )
    if user is None or member is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Invalid extension authorization context.")

    auth_session, raw_token = await create_session(
        session,
        user=user,
        organization_id=code_row.organization_id,
        request=request,
        commit=False,
    )
    code_row.consumed_at = now
    await log_audit(
        session,
        event_type="extension_token_issued",
        organization_id=code_row.organization_id,
        user_id=user.id,
        actor=user.email,
        request=request,
    )
    await session.commit()
    await session.refresh(auth_session)
    context = await get_current_user_context(authorization=f"Bearer {raw_token}", session=session)
    return _session_response(context=context, access_token=raw_token, expires_at=auth_session.expires_at)


def _require_org_outlook_admin(context: CurrentUserContext) -> None:
    if context.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only organization owners or admins can update Microsoft Outlook credentials.",
        )


def _require_org_integration_admin(context: CurrentUserContext) -> None:
    if context.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only organization owners or admins can manage organization integrations.",
        )


@router.get("/organizations/current", response_model=OrganizationRecord)
async def current_organization(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OrganizationRecord:
    organization = await session.get(Organization, context.organization_id)
    return OrganizationRecord(
        id=str(organization.id),
        name=organization.name,
        primary_domain=organization.primary_domain,
        status=organization.status,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


@router.get("/organizations/current/tms-integration", response_model=OrganizationTmsIntegrationRecord)
async def get_organization_tms_integration(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OrganizationTmsIntegrationRecord:
    row = await session.get(OrganizationTmsIntegration, context.organization_id)
    return _organization_tms_integration_record(row)


@router.put("/organizations/current/tms-integration", response_model=OrganizationTmsIntegrationRecord)
async def put_organization_tms_integration(
    payload: OrganizationTmsIntegrationUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OrganizationTmsIntegrationRecord:
    _require_org_integration_admin(context)
    row = await session.get(OrganizationTmsIntegration, context.organization_id)
    is_new = row is None
    if row is None:
        row = OrganizationTmsIntegration(organization_id=context.organization_id)
        session.add(row)
    row.tms_system = (payload.tms_system or "generic").strip().lower() or "generic"
    row.base_url = (payload.base_url or "").strip().rstrip("/") or None
    row.status = payload.status.strip().lower() or "inactive"
    row.metadata_json = dict(payload.metadata or {})
    row.updated_at = datetime.now(timezone.utc)
    api_key = payload.api_key.strip()
    if api_key:
        try:
            row.api_key_encrypted = encrypt_integration_secret(api_key)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    if is_new:
        row.created_at = datetime.now(timezone.utc)
    await log_audit(
        session,
        event_type="tms_integration_updated",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
        payload={
            "tms_system": row.tms_system,
            "has_base_url": bool(row.base_url),
            "has_api_key": bool(row.api_key_encrypted),
            "status": row.status,
        },
    )
    await session.commit()
    await session.refresh(row)
    return _organization_tms_integration_record(row)


@router.post(
    "/organizations/current/tms-integration/rotate-inbound-token",
    response_model=OrganizationTmsInboundTokenRotateResponse,
)
async def rotate_organization_tms_inbound_token(
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OrganizationTmsInboundTokenRotateResponse:
    _require_org_integration_admin(context)
    row = await session.get(OrganizationTmsIntegration, context.organization_id)
    if row is None:
        row = OrganizationTmsIntegration(
            organization_id=context.organization_id,
            status="active",
        )
        session.add(row)
    raw_token = secrets.token_urlsafe(40)
    row.inbound_token_hash = hash_token(raw_token)
    row.status = "active"
    row.updated_at = datetime.now(timezone.utc)
    await log_audit(
        session,
        event_type="tms_inbound_token_rotated",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
    )
    await session.commit()
    await session.refresh(row)
    return OrganizationTmsInboundTokenRotateResponse(
        inbound_token=raw_token,
        integration=_organization_tms_integration_record(row),
    )


@router.get("/organizations/current/outlook-credentials", response_model=OrganizationOutlookCredentialsRecord)
async def get_organization_outlook_credentials(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OrganizationOutlookCredentialsRecord:
    row = await session.get(OrganizationOutlookCredentials, context.organization_id)
    if row is None:
        return OrganizationOutlookCredentialsRecord()
    return OrganizationOutlookCredentialsRecord(
        tenant_id=row.tenant_id,
        client_id=row.client_id,
        mailbox=row.mailbox,
        client_secret_configured=bool(row.client_secret_encrypted),
        graph_subscription_id=row.graph_subscription_id,
        subscription_expires_at=row.subscription_expires_at,
    )


@router.put("/organizations/current/outlook-credentials", response_model=OrganizationOutlookCredentialsRecord)
async def put_organization_outlook_credentials(
    payload: OrganizationOutlookCredentialsUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OrganizationOutlookCredentialsRecord:
    _require_org_outlook_admin(context)
    mailbox_in = (payload.mailbox or "").strip().lower()
    if mailbox_in and await outlook_mailbox_conflict_other_org(
        session,
        mailbox=mailbox_in,
        organization_id=context.organization_id,
    ):
        raise HTTPException(
            status_code=409,
            detail="This mailbox is already linked to another organization's Outlook credentials.",
        )
    row = await session.get(OrganizationOutlookCredentials, context.organization_id)
    is_new = row is None
    if is_new:
        row = OrganizationOutlookCredentials(organization_id=context.organization_id)
        session.add(row)
    secret_in = payload.client_secret.strip()
    if is_new and not secret_in:
        raise HTTPException(
            status_code=400,
            detail="client_secret is required when saving Outlook credentials for the first time.",
        )
    row.tenant_id = payload.tenant_id.strip()
    row.client_id = payload.client_id.strip()
    row.mailbox = mailbox_in or None
    if secret_in:
        try:
            row.client_secret_encrypted = encrypt_outlook_client_secret(secret_in)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
    await log_audit(
        session,
        event_type="outlook_credentials_updated",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
        payload={"mailbox": row.mailbox, "has_tenant": bool(row.tenant_id), "has_client_id": bool(row.client_id)},
    )
    await session.commit()
    await session.refresh(row)
    return OrganizationOutlookCredentialsRecord(
        tenant_id=row.tenant_id,
        client_id=row.client_id,
        mailbox=row.mailbox,
        client_secret_configured=bool(row.client_secret_encrypted),
        graph_subscription_id=row.graph_subscription_id,
        subscription_expires_at=row.subscription_expires_at,
    )


@router.get("/auth/email-connections", response_model=list[EmailConnectionRecord])
async def list_email_connections(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> list[EmailConnectionRecord]:
    if context.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only organization owners or admins can view team mailbox connections.",
        )
    result = await session.execute(
        select(EmailConnection).where(EmailConnection.organization_id == context.organization_id)
    )
    return [_email_connection_record(connection) for connection in result.scalars().all()]


@router.get("/auth/email-connections/me/outlook", response_model=OutlookUserSyncStatusResponse)
async def current_user_outlook_sync_status(
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OutlookUserSyncStatusResponse:
    return await _outlook_user_sync_status_response(session, context)


@router.post("/auth/email-connections/me/outlook/enable", response_model=OutlookUserSyncStatusResponse)
async def enable_current_user_outlook_sync(
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OutlookUserSyncStatusResponse:
    connection = await _current_user_outlook_connection(session, context, create=True)
    if connection is None:
        raise HTTPException(status_code=400, detail="Unable to create Outlook email connection.")
    base_status = await _outlook_user_sync_status_response(session, context, connection=connection)
    if not base_status.can_enable:
        raise HTTPException(status_code=400, detail=base_status.status)
    connection.status = "active"
    connection.updated_at = datetime.now(timezone.utc)
    try:
        outlook = await build_outlook_graph_client(
            session,
            context.organization_id,
            mailbox=connection.mailbox,
            email_connection_id=connection.id,
        )
        subscription = await outlook.ensure_inbox_webhook_subscription()
        await apply_graph_subscription_to_email_connection(session, connection.id, subscription)
    except RuntimeError as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await log_audit(
        session,
        event_type="outlook_user_sync_enabled",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
        payload={"mailbox": connection.mailbox},
    )
    await session.commit()
    await session.refresh(connection)
    return await _outlook_user_sync_status_response(
        session,
        context,
        connection=connection,
        message="Outlook auto-sync is enabled for your mailbox.",
    )


@router.post("/auth/email-connections/me/outlook/disable", response_model=OutlookUserSyncStatusResponse)
async def disable_current_user_outlook_sync(
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OutlookUserSyncStatusResponse:
    connection = await _current_user_outlook_connection(session, context, create=False)
    if connection is None:
        return await _outlook_user_sync_status_response(
            session,
            context,
            message="Outlook auto-sync is already off for your mailbox.",
        )
    subscription_id = connection.graph_subscription_id
    if subscription_id:
        try:
            outlook = await build_outlook_graph_client(
                session,
                context.organization_id,
                mailbox=connection.mailbox,
                email_connection_id=connection.id,
            )
            await outlook.delete_subscription(subscription_id)
        except RuntimeError:
            # Local disable is still authoritative; stale Graph notifications are ignored because the connection is inactive.
            pass
    connection.status = "inactive"
    connection.graph_subscription_id = None
    connection.subscription_expires_at = None
    connection.updated_at = datetime.now(timezone.utc)
    await log_audit(
        session,
        event_type="outlook_user_sync_disabled",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
        payload={"mailbox": connection.mailbox},
    )
    await session.commit()
    await session.refresh(connection)
    return await _outlook_user_sync_status_response(
        session,
        context,
        connection=connection,
        message="Outlook auto-sync is off for your mailbox.",
    )


@router.patch("/auth/email-connections/me/outlook", response_model=OutlookUserSyncStatusResponse)
async def update_current_user_outlook_sync_settings(
    payload: EmailConnectionUpdateRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> OutlookUserSyncStatusResponse:
    connection = await _current_user_outlook_connection(session, context, create=True)
    if connection is None:
        raise HTTPException(status_code=400, detail="Unable to create Outlook email connection.")
    previous_visibility = connection.visibility_mode or "private"
    if payload.visibility_mode is not None:
        visibility_mode = payload.visibility_mode.strip().lower()
        if visibility_mode not in {"private", "shared_ops", "metadata_only"}:
            raise HTTPException(status_code=400, detail="Unsupported email visibility mode.")
        connection.visibility_mode = visibility_mode
    connection.updated_at = datetime.now(timezone.utc)
    if connection.visibility_mode != previous_visibility:
        await log_audit(
            session,
            event_type="email_connection_visibility_changed",
            organization_id=context.organization_id,
            user_id=context.user_id,
            actor=context.email,
            request=request,
            payload={
                "mailbox": connection.mailbox,
                "previous_visibility_mode": previous_visibility,
                "new_visibility_mode": connection.visibility_mode,
            },
        )
    await session.commit()
    await session.refresh(connection)
    return await _outlook_user_sync_status_response(
        session,
        context,
        connection=connection,
        message="Outlook email privacy settings updated.",
    )


@router.post("/auth/email-connections", response_model=EmailConnectionRecord)
async def create_email_connection(
    payload: EmailConnectionCreateRequest,
    session: AsyncSession = Depends(get_session),
    context: CurrentUserContext = Depends(get_current_user_context),
) -> EmailConnectionRecord:
    connection = EmailConnection(
        user_id=context.user_id,
        organization_id=context.organization_id,
        provider=payload.provider.strip().lower(),
        mailbox=payload.mailbox.strip().lower(),
        visibility_mode="private",
        metadata_json=payload.metadata,
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return _email_connection_record(connection)
