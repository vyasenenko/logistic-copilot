"""Transactional invite emails via Resend HTTP API."""

from __future__ import annotations

import html
import logging
from urllib.parse import urlencode

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

RESEND_SEND_URL = "https://api.resend.com/emails"


def _invite_link(raw_token: str) -> str | None:
    base = (settings.public_app_base_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/invite?{urlencode({'token': raw_token})}"


def _role_display(role: str) -> str:
    r = (role or "member").strip().lower()
    if not r:
        return "Member"
    return r[0].upper() + r[1:] if len(r) > 1 else r.upper()


def _subject_and_html(
    *,
    invite_link: str,
    organization_name: str,
    role_display: str,
    invite_ttl_days: int,
    owner_flow: bool,
    inviter_email: str | None,
) -> tuple[str, str]:
    safe_org = html.escape(organization_name.strip() or "Organization")
    safe_link = html.escape(invite_link)
    safe_role = html.escape(role_display)

    if owner_flow:
        subject = f"Invitation: set up {organization_name.strip() or 'your organization'} on Logistic Copilot"
        intro = (
            f'<p style="margin:0 0 14px;">You’ve been invited as the <strong style="color:inherit;">owner</strong> of '
            f'<strong style="color:inherit;">{safe_org}</strong>.</p>'
            '<p style="margin:0;">Create your password using the button below to activate your '
            "organization workspace.</p>"
        )
    else:
        subject = f"Invitation to join {organization_name.strip() or 'an organization'} on Logistic Copilot"
        inviter_block = ""
        if inviter_email:
            inviter_block = (
                '<p style="margin:16px 0 14px;">Invited by '
                f'<strong style="color:inherit;">{html.escape(inviter_email)}</strong>.</p>'
            )
        intro = (
            f'<p style="margin:0 0 14px;">You’ve been invited to join <strong style="color:inherit;">{safe_org}</strong> '
            f'as <strong style="color:inherit;">{safe_role}</strong>.</p>'
            f"{inviter_block}"
            '<p style="margin:0;">Create your password using the button below.</p>'
        )

    expiry_line = html.escape(f"This invitation link expires in about {invite_ttl_days} days.")
    expiry_html = (
        f'<p style="margin:16px 0 0;font-size:13px;line-height:1.52;color:#6b7280;">{expiry_line}</p>'
    )

    html_body = _invite_html_document(intro_html=intro, safe_link=safe_link, expiry_html=expiry_html)
    return subject, html_body


def _invite_html_document(
    *,
    intro_html: str,
    safe_link: str,
    expiry_html: str,
) -> str:
    """Invitation layout aligned with the product (teal accent, clean card).

    Default is a **light** envelope (explicit inline colors). That avoids clients that “helpfully”
    invert a dark-only layout in light mode mail UIs. Dark mode users get a matching palette when
    ``@media (prefers-color-scheme: dark)`` is honored.
    """
    btn_txt = "#ffffff"
    btn_bg = "#0d9488"

    footer_line = html.escape(
        "Logistic Copilot · Secure invitations only — we never ask for your password by email."
    )

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="color-scheme" content="light dark" />
<meta name="supported-color-schemes" content="light dark" />
<style type="text/css">
:root {{ color-scheme: light dark; }}
@media screen and (max-width: 520px) {{
  .invite-shell {{ padding: 28px 16px !important; }}
}}
@media (prefers-color-scheme: dark) {{
  .invite-root, .invite-outer {{
    background-color: #0b1117 !important;
  }}
  .invite-card {{
    background-color: #121a22 !important;
    border-color: #2a3542 !important;
  }}
  .invite-pill-wrap {{
    background-color: rgba(148, 234, 255, 0.08) !important;
    border-color: rgba(148, 234, 255, 0.25) !important;
  }}
  .invite-heading {{
    color: #f1f5f9 !important;
  }}
  .invite-intro,
  .invite-intro p {{
    color: #cbd5e1 !important;
  }}
  .invite-kicker {{
    color: #93d4de !important;
  }}
}}
</style>
</head>
<body style="margin:0;padding:0;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" class="invite-root invite-outer"
       bgcolor="#f6f7f9" style="background-color:#f6f7f9;width:100%;">
<tr><td align="center" class="invite-shell"
        style="padding:40px 20px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Ubuntu,sans-serif;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="max-width:532px;">
<tr><td align="center" style="padding:0 6px 20px;">
<p class="invite-kicker" style="margin:0;font-size:10px;font-weight:750;letter-spacing:0.3em;color:#0f766e;text-transform:uppercase;">Logistic Copilot</p>
</td></tr>
<tr><td bgcolor="#ffffff" class="invite-card"
        style="background-color:#ffffff;border-radius:18px;border:solid 1px #e8ecef;
               box-shadow:0 16px 44px rgba(15,23,42,0.08);overflow:hidden;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"><tr><td style="padding:32px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="invite-pill-wrap"
       style="border-radius:14px;background-color:rgba(13,148,136,0.07);border:1px solid rgba(13,148,136,0.22);"><tr><td style="padding:14px 18px;text-align:center;">
<p style="margin:0;font-size:11px;font-weight:700;letter-spacing:0.22em;color:#0f766e;text-transform:uppercase;">Invitation</p>
</td></tr></table>
<h1 class="invite-heading"
    style="margin:24px 0 14px;font-size:24px;line-height:1.2;color:#111827;font-weight:750;letter-spacing:-0.025em;">
You’re invited</h1>
<div class="invite-intro" style="font-size:15px;line-height:1.65;color:#4b5563;">{intro_html}</div>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center" style="margin:30px auto 24px;"><tr><td bgcolor="{btn_bg}" align="center" style="border-radius:12px;">
<a href="{safe_link}"
   style="display:inline-block;padding:14px 34px;color:{btn_txt};font-size:15px;font-weight:650;text-decoration:none;
border-radius:12px;line-height:1.35;color:{btn_txt} !important;mso-padding-alt:14px 34px;">Accept invitation&nbsp;→</a>
</td></tr></table>
<div class="invite-expiry">{expiry_html}</div>
<p style="margin:18px 0 0;font-size:12px;line-height:1.55;color:#6b7280;">
If you didn’t expect this, ignore it — no account is activated without confirming the link above.</p>
</td></tr></table></td></tr>
<tr><td align="center"
        style="padding:22px 10px 8px;font-size:11px;line-height:1.55;color:#6b7280;">{footer_line}</td></tr>
</table></td></tr></table>
</body></html>
"""


async def send_invite_email_if_configured(
    *,
    to_email: str,
    raw_token: str,
    organization_name: str,
    role: str,
    inviter_email: str | None,
    invite_ttl_days: int,
) -> None:
    """Send invite email via Resend; no-op if misconfigured. Logs errors, never raises."""
    key = (settings.resend_api_key or "").strip()
    from_addr = (settings.resend_from_email or "").strip()
    if not key or not from_addr:
        logger.info(
            "Invite email skipped (configure RESEND_API_KEY and RESEND_FROM_EMAIL): to=%s",
            to_email,
        )
        return

    link = _invite_link(raw_token)
    if not link:
        logger.warning(
            "Invite email skipped (set PUBLIC_APP_BASE_URL to your frontend base URL, no trailing slash): to=%s",
            to_email,
        )
        return

    owner_flow = (role or "").strip().lower() == "owner"
    role_display = _role_display(role)
    subject, html_body = _subject_and_html(
        invite_link=link,
        organization_name=organization_name,
        role_display=role_display,
        invite_ttl_days=invite_ttl_days,
        owner_flow=owner_flow,
        inviter_email=inviter_email,
    )

    payload = {"from": from_addr, "to": [to_email], "subject": subject, "html": html_body}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(RESEND_SEND_URL, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error(
                "Resend invite email failed for %s: HTTP %s %s",
                to_email,
                response.status_code,
                response.text[:800],
            )
        else:
            logger.info("Invite email accepted by Resend for %s (HTTP %s)", to_email, response.status_code)
    except httpx.HTTPError:
        logger.exception("Resend invite email HTTP error for %s", to_email)
