"""Native SMTP email delivery for lead/handoff alerts and weekly digests.

SMTP relay is configured once at the platform level (SMTP_* env vars); each
site sets its own recipient address (notify_email). Sending is offloaded to a
thread so it never blocks the async request, and failures are swallowed —
email is a notification, never a hard dependency of the visitor flow.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from sitebot.config import Settings

log = logging.getLogger(__name__)


def _send_sync(settings: Settings, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    if settings.smtp_use_tls:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)


async def send_email(settings: Settings, to: str, subject: str, body: str) -> bool:
    """Send one email. Returns True on success, False (logged) on any failure."""
    if not settings.smtp_configured or not to:
        return False
    try:
        await asyncio.to_thread(_send_sync, settings, to, subject, body)
        return True
    except Exception:  # noqa: BLE001 - notification, not a hard dependency
        log.exception("email send failed to %s", to)
        return False


def lead_email(site_slug: str, email: str, name: str, note: str) -> tuple[str, str]:
    subject = f"[SiteBot] New lead on {site_slug}"
    body = (
        f"A new lead was captured on {site_slug}.\n\n"
        f"Email: {email}\nName:  {name or '-'}\nNote:  {note or '-'}\n"
    )
    return subject, body


def handoff_email(site_slug: str, email: str, message: str) -> tuple[str, str]:
    subject = f"[SiteBot] Human handoff requested on {site_slug}"
    body = (
        f"A visitor on {site_slug} asked for a human.\n\n"
        f"Email:   {email or '-'}\nMessage: {message or '-'}\n"
    )
    return subject, body


def digest_email(site_slug: str, summary: dict) -> tuple[str, str]:
    subject = f"[SiteBot] Weekly digest for {site_slug}"
    defl = summary.get("deflection_rate")
    defl_s = f"{round(defl * 100)}%" if defl is not None else "n/a"
    body = (
        f"Weekly summary for {site_slug} (last 7 days):\n\n"
        f"Conversations:   {summary.get('conversations', 0)}\n"
        f"Messages:        {summary.get('messages_answered', 0)}\n"
        f"Deflection rate: {defl_s}\n"
        f"Unanswered:      {summary.get('unanswered', 0)}\n"
        f"Leads:           {summary.get('leads', 0)}\n"
        f"Handoffs:        {summary.get('handoffs', 0)}\n"
    )
    return subject, body
