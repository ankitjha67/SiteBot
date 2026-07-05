"""AI Actions: declarative per-site tools the bot can use while answering.

Provider-agnostic two-phase design (works identically on Claude, GPT, Gemini,
and local models — no native tool-calling API required):

1. Plan: a small model call decides whether the question needs an action and
   with which arguments, replying strict JSON.
2. Execute: http actions call the external API (SSRF-guarded, timeboxed,
   response truncated); link actions produce a hand-off URL. The result is
   injected into the grounded answer prompt as fresh, authoritative context.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from sitebot.config import Settings
from sitebot.llm import stream_answer

log = logging.getLogger(__name__)

MAX_RESULT_CHARS = 4000
ACTION_TIMEOUT_S = 8.0

PLANNER_PROMPT = (
    "You decide whether a website assistant needs to call one of its actions "
    "to answer the visitor's question. Reply ONLY with JSON: "
    '{"action": "<name>", "args": {...}} to call one, or {"action": null} if '
    "no action is needed. Never invent argument values the visitor did not "
    "provide; if a required argument is missing, reply {\"action\": null}."
)


@dataclass(slots=True)
class ActionDef:
    id: int
    name: str
    description: str
    kind: str            # http | link
    method: str          # GET | POST
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    params: list[dict[str, str]] = field(default_factory=list)


def catalog_prompt(actions: list[ActionDef]) -> str:
    lines = []
    for a in actions:
        params = ", ".join(
            f"{p.get('name')} ({'required' if p.get('required') else 'optional'}: "
            f"{p.get('description', '')})"
            for p in a.params
        ) or "no arguments"
        lines.append(f"- {a.name}: {a.description} | arguments: {params}")
    return "Available actions:\n" + "\n".join(lines)


def parse_plan(raw: str) -> tuple[str, dict[str, Any]] | None:
    """Parse the planner's JSON defensively; None means no action."""
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    name = data.get("action")
    if not name or not isinstance(name, str):
        return None
    args = data.get("args") or {}
    return name, args if isinstance(args, dict) else {}


def validate_args(action: ActionDef, args: dict[str, Any]) -> dict[str, str]:
    """Only declared parameters pass through; required ones must be present."""
    declared = {str(p.get("name")): p for p in action.params if p.get("name")}
    clean: dict[str, str] = {}
    for name, spec in declared.items():
        value = args.get(name)
        if value is None or str(value).strip() == "":
            if spec.get("required"):
                raise ValueError(f"Missing required argument: {name}")
            continue
        clean[name] = str(value).strip()[:500]
    return clean


def is_safe_url(url: str) -> bool:
    """SSRF guard: only public http(s) endpoints, no loopback/private/link-local."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname
    if host.lower() in ("localhost",):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            return False
    return True


def build_url(action: ActionDef, args: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Substitute {param} placeholders; leftover args become query/body params."""
    url = action.url
    leftover = dict(args)
    for name, value in args.items():
        placeholder = "{" + name + "}"
        if placeholder in url:
            url = url.replace(placeholder, quote(value, safe=""))
            leftover.pop(name, None)
    return url, leftover


async def plan_action(
    question: str,
    history: list[dict[str, str]],
    actions: list[ActionDef],
    settings: Settings,
    provider: str | None,
    model: str | None,
    api_key: str | None = None,
) -> tuple[ActionDef, dict[str, str]] | None:
    """Ask the model whether an action applies. None on any doubt."""
    context = ""
    if history:
        recent = history[-4:]
        context = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in recent) + "\n"
    prompt = f"{catalog_prompt(actions)}\n\n{context}visitor: {question}"
    try:
        parts: list[str] = []
        async for text in stream_answer(
            PLANNER_PROMPT, [{"role": "user", "content": prompt}], settings,
            provider=provider, model=model, api_key=api_key,
        ):
            parts.append(text)
        plan = parse_plan("".join(parts))
        if plan is None:
            return None
        name, raw_args = plan
        by_name = {a.name: a for a in actions}
        action = by_name.get(name)
        if action is None:
            return None
        return action, validate_args(action, raw_args)
    except Exception:  # noqa: BLE001 - planning is best-effort
        log.exception("action planning failed")
        return None


async def execute_action(action: ActionDef, args: dict[str, str]) -> str:
    """Run the action and return a text result for the answer prompt."""
    if action.kind == "link":
        url, _ = build_url(action, args)
        return (
            f"Share this link with the visitor so they can proceed: {url} "
            f"({action.description})"
        )

    url, leftover = build_url(action, args)
    if not is_safe_url(url):
        raise ValueError(f"Action URL failed the safety check: {url}")
    async with httpx.AsyncClient(timeout=ACTION_TIMEOUT_S, follow_redirects=False) as client:
        if action.method.upper() == "POST":
            resp = await client.post(url, headers=action.headers, json=leftover or {})
        else:
            resp = await client.get(url, headers=action.headers, params=leftover or None)
    body = resp.text[:MAX_RESULT_CHARS]
    return f"HTTP {resp.status_code} from {action.name}:\n{body}"
