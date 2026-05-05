"""Invite-based auth and organization context helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx
from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.memory.database import (
    AccessRequest,
    AuditLog,
    AuthMethod,
    AuthSession,
    Invite,
    Organization,
    OrganizationMember,
    User,
    get_session,
)
from app.services.invite_email import send_invite_email_if_configured

FREE_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "me.com",
    "aol.com",
    "proton.me",
    "protonmail.com",
}

SESSION_TTL_DAYS = 14
INVITE_TTL_DAYS = 7


@dataclass(frozen=True)
class CurrentUserContext:
    user_id: UUID
    organization_id: UUID
    role: str
    permissions: tuple[str, ...]
    session_id: UUID
    email: str


def normalize_email(email: str) -> str:
    return email.strip().lower()


def email_domain(email: str) -> str:
    normalized = normalize_email(email)
    if "@" not in normalized:
        return ""
    return normalized.rsplit("@", 1)[1]


def is_business_email(email: str) -> bool:
    domain = email_domain(email)
    return bool(domain and domain not in FREE_EMAIL_DOMAINS)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 240_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, salt, expected = encoded.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, f"{algorithm}${salt}${expected}")


def permissions_for_role(role: str) -> tuple[str, ...]:
    if role == "owner":
        return ("*",)
    if role == "admin":
        return (
            "dashboard:read",
            "freight:read",
            "freight:write",
            "email:connect",
            "members:invite",
            "audit:read",
        )
    if role == "member":
        return ("dashboard:read", "freight:read", "freight:write", "email:connect")
    if role == "viewer":
        return ("dashboard:read", "freight:read")
    return ()


async def log_audit(
    session: AsyncSession,
    *,
    event_type: str,
    organization_id: UUID | None = None,
    user_id: UUID | None = None,
    actor: str | None = None,
    request: Request | None = None,
    payload: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            organization_id=organization_id,
            user_id=user_id,
            event_type=event_type,
            actor=actor,
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
            payload_json=payload or {},
        )
    )


async def verify_turnstile(token: str | None, *, request: Request | None = None) -> None:
    if not settings.auth_require_turnstile:
        return
    if not token:
        raise HTTPException(status_code=400, detail="Cloudflare Turnstile challenge is required.")
    if not settings.turnstile_secret_key:
        raise HTTPException(status_code=500, detail="Turnstile is required but not configured.")
    payload = {
        "secret": settings.turnstile_secret_key,
        "response": token,
    }
    if request and request.client:
        payload["remoteip"] = request.client.host
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(settings.turnstile_verify_url, data=payload)
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail="Turnstile verification failed.")
    result = response.json()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail="Turnstile verification failed.")


async def create_access_request(
    session: AsyncSession,
    *,
    email: str,
    company_name: str,
    request: Request | None = None,
    payload: dict | None = None,
) -> AccessRequest:
    normalized_email = normalize_email(email)
    if not is_business_email(normalized_email):
        raise HTTPException(status_code=400, detail="A business email is required for production access.")
    access_request = AccessRequest(
        email=normalized_email,
        company_name=company_name.strip(),
        domain=email_domain(normalized_email),
        payload_json=payload or {},
    )
    session.add(access_request)
    await log_audit(
        session,
        event_type="access_requested",
        actor=normalized_email,
        request=request,
        payload={"company_name": company_name.strip(), "domain": email_domain(normalized_email)},
    )
    await session.commit()
    await session.refresh(access_request)
    return access_request


async def create_invite(
    session: AsyncSession,
    *,
    organization_id: UUID,
    email: str,
    role: str,
    actor: CurrentUserContext | None = None,
    request: Request | None = None,
    allow_owner_role: bool = False,
) -> tuple[Invite, str]:
    normalized_email = normalize_email(email)
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    now_ts = datetime.now(timezone.utc)
    pending_duplicate = await session.scalar(
        select(Invite).where(
            Invite.organization_id == organization_id,
            Invite.email == normalized_email,
            Invite.status == "pending",
            Invite.expires_at > now_ts,
        )
    )
    if pending_duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail="A pending invite already exists for this email.",
        )
    existing_user = await session.scalar(select(User).where(User.email == normalized_email))
    if existing_user is not None:
        active_here = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == existing_user.id,
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.status == "active",
            )
        )
        if active_here is not None:
            raise HTTPException(
                status_code=409,
                detail="This user is already an active member of this organization.",
            )
        conflicting = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == existing_user.id,
                OrganizationMember.organization_id != organization_id,
                OrganizationMember.status == "active",
            )
        )
        if conflicting is not None:
            raise HTTPException(
                status_code=409,
                detail="This email belongs to an active member of another organization.",
            )
    normalized_role = (role or "member").strip().lower()
    allowed_roles = {"admin", "member", "viewer"}
    if allow_owner_role:
        allowed_roles.add("owner")
    if normalized_role not in allowed_roles:
        raise HTTPException(status_code=400, detail="Unsupported invite role.")
    organization_domain = (organization.primary_domain or "").strip().lower()
    invited_domain = email_domain(normalized_email)
    requires_viewer_only = not is_business_email(normalized_email) or bool(
        organization_domain and invited_domain != organization_domain
    )
    if requires_viewer_only and normalized_role != "viewer":
        raise HTTPException(
            status_code=400,
            detail="This email can only be invited with the Viewer role.",
        )
    token = secrets.token_urlsafe(32)
    invite = Invite(
        organization_id=organization.id,
        email=normalized_email,
        role=normalized_role,
        token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=INVITE_TTL_DAYS),
        created_by_user_id=actor.user_id if actor else None,
    )
    session.add(invite)
    await log_audit(
        session,
        event_type="invite_sent",
        organization_id=organization.id,
        user_id=actor.user_id if actor else None,
        actor=actor.email if actor else None,
        request=request,
        payload={"email": normalized_email, "role": normalized_role, "email_domain": invited_domain},
    )
    await session.commit()
    await session.refresh(invite)
    await send_invite_email_if_configured(
        to_email=normalized_email,
        raw_token=token,
        organization_name=organization.name.strip(),
        role=normalized_role,
        inviter_email=actor.email if actor else None,
        invite_ttl_days=INVITE_TTL_DAYS,
    )
    return invite, token


async def accept_invite(
    session: AsyncSession,
    *,
    token: str,
    name: str | None,
    password: str,
    request: Request | None = None,
) -> tuple[User, AuthSession, str]:
    invite = await session.scalar(select(Invite).where(Invite.token_hash == hash_token(token)))
    now = datetime.now(timezone.utc)
    if invite is None or invite.status != "pending" or invite.expires_at < now:
        raise HTTPException(status_code=400, detail="Invite is invalid or expired.")

    user = await session.scalar(select(User).where(User.email == invite.email))
    if user is not None:
        conflicting = await session.scalar(
            select(OrganizationMember).where(
                OrganizationMember.user_id == user.id,
                OrganizationMember.organization_id != invite.organization_id,
                OrganizationMember.status == "active",
            )
        )
        if conflicting is not None:
            raise HTTPException(
                status_code=409,
                detail="This user already belongs to another organization.",
            )
    if user is None:
        user = User(
            email=invite.email,
            name=name.strip() if name else None,
            status="active",
            email_verified_at=now,
        )
        session.add(user)
        await session.flush()
    elif name and not user.name:
        user.name = name.strip()
        user.email_verified_at = user.email_verified_at or now

    password_method = await session.scalar(
        select(AuthMethod).where(AuthMethod.user_id == user.id, AuthMethod.method_type == "password")
    )
    if password_method is None:
        password_method = AuthMethod(user_id=user.id, method_type="password", enabled_at=now)
        session.add(password_method)
    password_method.secret_hash = hash_password(password)

    member = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user.id,
            OrganizationMember.organization_id == invite.organization_id,
        )
    )
    if member is None:
        member = OrganizationMember(
            user_id=user.id,
            organization_id=invite.organization_id,
            role=invite.role,
            status="active",
        )
        session.add(member)
    else:
        member.role = invite.role
        member.status = "active"

    invite.status = "accepted"
    invite.accepted_at = now
    auth_session, raw_token = await create_session(
        session,
        user=user,
        organization_id=invite.organization_id,
        request=request,
        commit=False,
    )
    await log_audit(
        session,
        event_type="invite_accepted",
        organization_id=invite.organization_id,
        user_id=user.id,
        actor=user.email,
        request=request,
    )
    await session.commit()
    await session.refresh(auth_session)
    return user, auth_session, raw_token


async def create_session(
    session: AsyncSession,
    *,
    user: User,
    organization_id: UUID,
    request: Request | None = None,
    commit: bool = True,
) -> tuple[AuthSession, str]:
    raw_token = secrets.token_urlsafe(40)
    auth_session = AuthSession(
        user_id=user.id,
        organization_id=organization_id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS),
        ip_address=request.client.host if request and request.client else None,
        user_agent=request.headers.get("user-agent") if request else None,
    )
    session.add(auth_session)
    await log_audit(
        session,
        event_type="login_success",
        organization_id=organization_id,
        user_id=user.id,
        actor=user.email,
        request=request,
    )
    if commit:
        await session.commit()
        await session.refresh(auth_session)
    return auth_session, raw_token


async def login_with_password(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    request: Request | None = None,
) -> tuple[User, AuthSession, str]:
    normalized_email = normalize_email(email)
    user = await session.scalar(select(User).where(User.email == normalized_email, User.status == "active"))
    if user is None:
        await log_audit(session, event_type="login_failed", actor=normalized_email, request=request)
        await session.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    password_method = await session.scalar(
        select(AuthMethod).where(AuthMethod.user_id == user.id, AuthMethod.method_type == "password")
    )
    if not verify_password(password, password_method.secret_hash if password_method else None):
        await log_audit(session, event_type="login_failed", user_id=user.id, actor=normalized_email, request=request)
        await session.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    membership_query = select(OrganizationMember).where(
        OrganizationMember.user_id == user.id,
        OrganizationMember.status == "active",
    )
    member = await session.scalar(membership_query.order_by(OrganizationMember.created_at.asc()))
    if member is None:
        raise HTTPException(status_code=403, detail="No active organization membership.")
    auth_session, raw_token = await create_session(
        session,
        user=user,
        organization_id=member.organization_id,
        request=request,
    )
    return user, auth_session, raw_token


async def get_current_user_context(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> CurrentUserContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    raw_token = authorization.split(" ", 1)[1].strip()
    return await get_current_user_context_for_token(raw_token, session)


async def get_current_user_context_for_token(raw_token: str, session: AsyncSession) -> CurrentUserContext:
    auth_session = await session.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(timezone.utc),
        )
    )
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired session.")
    user = await session.get(User, auth_session.user_id)
    member = await session.scalar(
        select(OrganizationMember).where(
            OrganizationMember.user_id == auth_session.user_id,
            OrganizationMember.organization_id == auth_session.organization_id,
            OrganizationMember.status == "active",
        )
    )
    if user is None or member is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session context.")
    return CurrentUserContext(
        user_id=user.id,
        organization_id=auth_session.organization_id,
        role=member.role,
        permissions=permissions_for_role(member.role),
        session_id=auth_session.id,
        email=user.email,
    )


def require_permission(permission: str):
    async def _dependency(context: CurrentUserContext = Depends(get_current_user_context)) -> CurrentUserContext:
        if "*" not in context.permissions and permission not in context.permissions:
            raise HTTPException(status_code=403, detail="Permission denied.")
        return context

    return _dependency


async def revoke_session(
    session: AsyncSession,
    *,
    context: CurrentUserContext,
    request: Request | None = None,
) -> None:
    auth_session = await session.get(AuthSession, context.session_id)
    if auth_session:
        auth_session.revoked_at = datetime.now(timezone.utc)
    await log_audit(
        session,
        event_type="session_revoked",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
    )
    await session.commit()


async def revoke_all_sessions_for_user(
    session: AsyncSession,
    *,
    context: CurrentUserContext,
    request: Request | None = None,
) -> int:
    """Invalidate every active bearer session for this user (all browsers, dashboard, extension)."""
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == context.user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    count = int(result.rowcount or 0)
    await log_audit(
        session,
        event_type="sessions_revoked_all",
        organization_id=context.organization_id,
        user_id=context.user_id,
        actor=context.email,
        request=request,
        payload={"sessions_invalidated": count},
    )
    await session.commit()
    return count
