"""Messaging channels: the same grounded brain, reachable from Telegram and
Slack. Each channel maps its native identity to a visitor_id so conversation
memory works across messages.

Telegram: create a bot with @BotFather, paste the token in the dashboard.
  We call setWebhook automatically when PUBLIC_BASE_URL is configured, and
  verify Telegram's X-Telegram-Bot-Api-Secret-Token on every update.

Slack: create a Slack app with a bot token (chat:write) and event
  subscriptions for app_mention + message.im pointing at
  /v1/channels/slack/{public_key}. Requests are verified with the app's
  signing secret. Replies go to the originating channel/thread.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import parse_qs

import httpx

from sitebot import store
from sitebot.config import Settings
from sitebot.rag import answer_stream
from sitebot.store import SiteRow

log = logging.getLogger(__name__)


async def _collect_answer(
    site: SiteRow, question: str, settings: Settings, visitor_id: str
) -> str:
    """Run the full pipeline non-streaming, continuing the visitor's thread."""
    conversation_id = await store.latest_conversation_for_visitor(site.id, visitor_id)
    parts: list[str] = []
    async for ev in answer_stream(site, question, settings, visitor_id, conversation_id):
        if ev["event"] == "token":
            parts.append(ev["data"])
    return "".join(parts).strip()


# --------------------------------- telegram ---------------------------------
def telegram_secret(bot_token: str) -> str:
    """Deterministic webhook secret so we can verify updates without storing
    another credential."""
    return hashlib.sha256(("sitebot:" + bot_token).encode("utf-8")).hexdigest()[:32]


def parse_telegram_update(update: dict[str, Any]) -> tuple[int, str] | None:
    """Return (chat_id, text) for plain text messages; None for anything else."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        return None
    text = (message.get("text") or "").strip()
    chat_id = (message.get("chat") or {}).get("id")
    if not text or chat_id is None:
        return None
    return int(chat_id), text


async def handle_telegram_update(
    site: SiteRow, update: dict[str, Any], settings: Settings
) -> None:
    parsed = parse_telegram_update(update)
    if parsed is None:
        return
    chat_id, text = parsed
    try:
        answer = await _collect_answer(site, text, settings, f"tg_{chat_id}")
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{site.telegram_bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": answer or "Sorry, I could not answer that."},
            )
    except Exception:  # noqa: BLE001 - a channel error must never crash the API
        log.exception("telegram reply failed for site %s", site.slug)


async def set_telegram_webhook(bot_token: str, webhook_url: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": telegram_secret(bot_token),
                "allowed_updates": ["message"],
            },
        )
        return resp.json()


# ---------------------------------- slack ----------------------------------
def verify_slack_signature(
    signing_secret: str, timestamp: str, body: bytes, signature: str, now: float | None = None
) -> bool:
    """Slack's v0 HMAC scheme, with a 5-minute replay window."""
    if not signing_secret or not timestamp or not signature:
        return False
    try:
        ts = float(timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - ts) > 300:
        return False
    base = b"v0:" + timestamp.encode() + b":" + body
    digest = "v0=" + hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def parse_slack_event(payload: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """Return (channel, user, text, thread_ts) for human messages; None otherwise."""
    event = payload.get("event") or {}
    if event.get("bot_id") or event.get("subtype"):
        return None  # ignore our own replies and message edits/joins
    etype = event.get("type")
    if etype not in ("app_mention", "message"):
        return None
    if etype == "message" and event.get("channel_type") not in ("im",):
        return None  # in channels we only respond to explicit mentions
    text = (event.get("text") or "").strip()
    channel = event.get("channel") or ""
    user = event.get("user") or ""
    if not text or not channel or not user:
        return None
    thread_ts = event.get("thread_ts") or event.get("ts") or ""
    return channel, user, text, thread_ts


# --------------------------------- whatsapp ---------------------------------
def verify_whatsapp_signature(app_secret: str, body: bytes, signature: str) -> bool:
    """Meta's X-Hub-Signature-256 header: sha256=<hmac>. An empty app secret
    skips verification (documented as dev-only)."""
    if not app_secret:
        return True
    if not signature.startswith("sha256="):
        return False
    digest = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature[len("sha256="):])


def parse_whatsapp_payload(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(sender, text)] for incoming text messages."""
    out: list[tuple[str, str]] = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            value = change.get("value") or {}
            for message in value.get("messages") or []:
                if message.get("type") != "text":
                    continue
                sender = message.get("from") or ""
                text = ((message.get("text") or {}).get("body") or "").strip()
                if sender and text:
                    out.append((sender, text))
    return out


async def handle_whatsapp_payload(
    site: SiteRow, payload: dict[str, Any], settings: Settings
) -> None:
    for sender, text in parse_whatsapp_payload(payload):
        try:
            answer = await _collect_answer(site, text, settings, f"wa_{sender}")
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    f"https://graph.facebook.com/v19.0/{site.whatsapp_phone_id}/messages",
                    headers={"Authorization": f"Bearer {site.whatsapp_token}"},
                    json={
                        "messaging_product": "whatsapp",
                        "to": sender,
                        "text": {"body": answer or "Sorry, I could not answer that."},
                    },
                )
        except Exception:  # noqa: BLE001
            log.exception("whatsapp reply failed for site %s", site.slug)


async def handle_slack_event(
    site: SiteRow, payload: dict[str, Any], settings: Settings
) -> None:
    parsed = parse_slack_event(payload)
    if parsed is None:
        return
    channel, user, text, thread_ts = parsed
    try:
        answer = await _collect_answer(site, text, settings, f"slack_{user}")
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {site.slack_bot_token}"},
                json={
                    "channel": channel,
                    "text": answer or "Sorry, I could not answer that.",
                    "thread_ts": thread_ts or None,
                },
            )
    except Exception:  # noqa: BLE001
        log.exception("slack reply failed for site %s", site.slug)


# ------------------------------ twilio SMS ------------------------------
def verify_twilio_signature(
    auth_token: str, url: str, params: dict[str, str], signature: str
) -> bool:
    """Twilio's X-Twilio-Signature: base64(HMAC-SHA1(auth_token, url + sorted
    key+value concatenation)). Empty auth token skips (dev only)."""
    if not auth_token:
        return True
    if not signature:
        return False
    data = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), data.encode("utf-8"), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def parse_twilio_form(body: bytes) -> tuple[str, str] | None:
    """Return (from_number, text) from a Twilio inbound-SMS form post."""
    form = {k: v[0] for k, v in parse_qs(body.decode("utf-8")).items()}
    sender = form.get("From", "")
    text = (form.get("Body") or "").strip()
    return (sender, text) if sender and text else None


async def handle_twilio_sms(site: SiteRow, body: bytes, settings: Settings) -> None:
    parsed = parse_twilio_form(body)
    if parsed is None:
        return
    sender, text = parsed
    try:
        answer = await _collect_answer(site, text, settings, f"sms_{sender}")
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{site.twilio_account_sid}/Messages.json",
                auth=(site.twilio_account_sid, site.twilio_auth_token),
                data={
                    "From": site.twilio_from,
                    "To": sender,
                    "Body": (answer or "Sorry, I could not answer that.")[:1500],
                },
            )
    except Exception:  # noqa: BLE001
        log.exception("twilio SMS reply failed for site %s", site.slug)


# ------------------------------ twilio Voice ------------------------------
# Phone-call AI: Twilio answers the call, streams the caller's speech to us as
# text (<Gather input="speech">), we run the same RAG pipeline, and Twilio
# speaks the answer back (<Say>). One webhook URL handles every turn.

_VOICE_LANG = {
    "en": "en-US", "es": "es-ES", "fr": "fr-FR",
    "de": "de-DE", "hi": "hi-IN", "pt": "pt-BR",
}


def _xml_escape(text: str) -> str:
    from xml.sax.saxutils import escape

    return escape(text, {'"': "&quot;"})


def voice_answer_text(answer: str) -> str:
    """Make an answer speakable: no citation markers, no markdown, capped so
    a phone reply stays under ~45 seconds of speech."""
    import re as _re

    clean = _re.sub(r"\[\d+\]", "", answer)
    clean = _re.sub(r"[*_`#>|]", "", clean)
    clean = " ".join(clean.split())
    if len(clean) > 600:
        clean = clean[:600].rsplit(". ", 1)[0] + "."
    return clean


def twiml_voice_turn(say_text: str, action_url: str, language: str) -> str:
    """One conversational turn: speak, then listen for the next question."""
    lang = _VOICE_LANG.get(language, "en-US")
    say = _xml_escape(say_text)
    goodbye = _xml_escape(_VOICE_GOODBYE.get(language, _VOICE_GOODBYE["en"]))
    return (
        '<?xml version="1.0" encoding="UTF-8"?><Response>'
        f'<Gather input="speech" language="{lang}" speechTimeout="auto" '
        f'action="{_xml_escape(action_url)}" method="POST">'
        f'<Say language="{lang}">{say}</Say>'
        "</Gather>"
        f'<Say language="{lang}">{goodbye}</Say>'
        "</Response>"
    )


_VOICE_GOODBYE = {
    "en": "Thanks for calling. Goodbye!",
    "es": "Gracias por llamar. Hasta luego.",
    "fr": "Merci de votre appel. Au revoir.",
    "de": "Danke fuer Ihren Anruf. Auf Wiederhoeren.",
    "hi": "Call karne ke liye dhanyavaad. Namaste!",
    "pt": "Obrigado pela ligacao. Ate logo.",
}


async def handle_voice_turn(
    site: SiteRow, form: dict[str, str], settings: Settings, action_url: str
) -> str:
    """Return the TwiML for this turn of the phone conversation."""
    speech = (form.get("SpeechResult") or "").strip()
    caller = form.get("From", "caller")
    if not speech:
        # Call start (or nothing heard): greet and listen.
        greeting = site.welcome_message or f"Hello, you have reached {site.display_name}."
        return twiml_voice_turn(
            voice_answer_text(greeting), action_url, site.widget_language
        )
    try:
        answer = await _collect_answer(site, speech, settings, f"voice_{caller}")
    except Exception:  # noqa: BLE001 - a model hiccup must not drop the call
        log.exception("voice answer failed for site %s", site.slug)
        answer = "Sorry, I hit a problem answering that. Could you try asking again?"
    return twiml_voice_turn(
        voice_answer_text(answer or "Sorry, I do not have that information."),
        action_url, site.widget_language,
    )


# --------------------------- messenger / instagram ---------------------------
def parse_messenger_payload(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Return [(sender_id, text)] for incoming Messenger/Instagram messages."""
    out: list[tuple[str, str]] = []
    for entry in payload.get("entry") or []:
        for event in entry.get("messaging") or []:
            message = event.get("message") or {}
            if message.get("is_echo"):
                continue
            text = (message.get("text") or "").strip()
            sender = (event.get("sender") or {}).get("id", "")
            if sender and text:
                out.append((sender, text))
    return out


async def handle_messenger_payload(
    site: SiteRow, payload: dict[str, Any], settings: Settings
) -> None:
    for sender, text in parse_messenger_payload(payload):
        try:
            answer = await _collect_answer(site, text, settings, f"fb_{sender}")
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(
                    "https://graph.facebook.com/v19.0/me/messages",
                    params={"access_token": site.messenger_page_token},
                    json={
                        "recipient": {"id": sender},
                        "message": {"text": (answer or "Sorry, I could not answer that.")[:1900]},
                    },
                )
        except Exception:  # noqa: BLE001
            log.exception("messenger reply failed for site %s", site.slug)


# ------------------------------ microsoft teams ------------------------------
# Bot Framework signs every inbound request with a JWT issued by the Bot
# Connector. We validate its signature against Microsoft's published keys and
# check the issuer, audience (our bot's app id), and expiry.
_TEAMS_OPENID = "https://login.botframework.com/v1/.well-known/openidconfiguration"
_TEAMS_ISSUER = "https://api.botframework.com"
_jwk_client: Any = None


def _teams_jwk_client() -> Any:
    """Cached PyJWKClient pointed at the Bot Framework signing keys. PyJWKClient
    handles key caching and refetch-on-unknown-kid internally."""
    global _jwk_client
    if _jwk_client is None:
        from jwt import PyJWKClient

        cfg = httpx.get(_TEAMS_OPENID, timeout=10.0).json()
        _jwk_client = PyJWKClient(cfg["jwks_uri"])
    return _jwk_client


def _verify_teams_jwt_sync(app_id: str, token: str) -> bool:
    import jwt

    try:
        signing_key = _teams_jwk_client().get_signing_key_from_jwt(token)
        jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=app_id,
            issuer=_TEAMS_ISSUER,
            options={"require": ["exp", "iss", "aud"]},
        )
        return True
    except Exception:  # noqa: BLE001 - any validation failure = reject
        log.warning("teams JWT validation failed")
        return False


async def verify_teams_jwt(app_id: str, auth_header: str) -> bool:
    """Validate the Bot Framework bearer token. Raises RuntimeError if PyJWT is
    not installed (Teams requires the 'teams' extra)."""
    if not auth_header.lower().startswith("bearer "):
        return False
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return False
    try:
        import jwt  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            'Microsoft Teams requires PyJWT: pip install ".[teams]"'
        ) from exc
    return await asyncio.to_thread(_verify_teams_jwt_sync, app_id, token)


def parse_teams_activity(activity: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """Return (service_url, conversation_id, user_id, text) for a Teams message
    activity; None for non-message events."""
    if activity.get("type") != "message":
        return None
    text = (activity.get("text") or "").strip()
    service_url = activity.get("serviceUrl") or ""
    conv = (activity.get("conversation") or {}).get("id", "")
    user = (activity.get("from") or {}).get("id", "")
    if not (text and service_url and conv):
        return None
    return service_url, conv, user, text


async def _teams_token(site: SiteRow) -> str:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": site.teams_app_id,
                "client_secret": site.teams_app_password,
                "scope": "https://api.botframework.com/.default",
            },
        )
        return resp.json().get("access_token", "")


def _is_botframework_host(service_url: str) -> bool:
    """Only send authenticated replies to Bot Framework service hosts, so a
    (validly-signed) activity cannot redirect our bearer token elsewhere."""
    host = httpx.URL(service_url).host.lower()
    return (
        host.endswith(".botframework.com")
        or host.endswith(".trafficmanager.net")
        or host.endswith(".azure-api.net")
    )


async def handle_teams_activity(
    site: SiteRow, activity: dict[str, Any], settings: Settings
) -> None:
    parsed = parse_teams_activity(activity)
    if parsed is None:
        return
    service_url, conv, user, text = parsed
    if not _is_botframework_host(service_url):
        log.warning("teams reply blocked: non-Bot-Framework serviceUrl %s", service_url)
        return
    try:
        answer = await _collect_answer(site, text, settings, f"teams_{user}")
        token = await _teams_token(site)
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{service_url.rstrip('/')}/v3/conversations/{conv}/activities",
                headers={"Authorization": f"Bearer {token}"},
                json={"type": "message", "text": answer or "Sorry, I could not answer that."},
            )
    except Exception:  # noqa: BLE001
        log.exception("teams reply failed for site %s", site.slug)
