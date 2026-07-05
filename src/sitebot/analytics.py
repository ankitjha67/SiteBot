"""Conversation analytics: volume, deflection, feedback, top and unanswered
questions. Powers the dashboard and the per-site analytics API."""

from __future__ import annotations

from typing import Any

from sitebot.db import get_pool


async def site_summary(site_id: int, days: int = 30) -> dict[str, Any]:
    """Headline numbers for one site over the trailing window."""
    pool = await get_pool()
    # Bind days as text: a str bound to ::interval directly fails in asyncpg.
    interval = str(int(days))
    row = await pool.fetchrow(
        """
        SELECT
          count(*) FILTER (WHERE m.role = 'assistant')                    AS answers,
          count(*) FILTER (WHERE m.role = 'assistant' AND m.answered)     AS answered,
          count(*) FILTER (WHERE m.role = 'assistant' AND NOT m.answered) AS unanswered,
          count(*) FILTER (WHERE m.feedback = 1)                          AS feedback_up,
          count(*) FILTER (WHERE m.feedback = -1)                         AS feedback_down,
          count(DISTINCT m.conversation_id)                               AS conversations
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.site_id = $1 AND m.created_at > now() - ($2 || ' days')::interval
        """,
        site_id,
        interval,
    )
    leads = await pool.fetchval(
        "SELECT count(*) FROM leads WHERE site_id = $1 "
        "AND created_at > now() - ($2 || ' days')::interval",
        site_id, interval,
    )
    handoffs = await pool.fetchval(
        "SELECT count(*) FROM handoffs WHERE site_id = $1 "
        "AND created_at > now() - ($2 || ' days')::interval",
        site_id, interval,
    )
    answers = int(row["answers"] or 0)
    answered = int(row["answered"] or 0)
    return {
        "days": days,
        "conversations": int(row["conversations"] or 0),
        "messages_answered": answers,
        "deflection_rate": round(answered / answers, 3) if answers else None,
        "unanswered": int(row["unanswered"] or 0),
        "feedback_up": int(row["feedback_up"] or 0),
        "feedback_down": int(row["feedback_down"] or 0),
        "leads": int(leads or 0),
        "handoffs": int(handoffs or 0),
    }


async def messages_per_day(site_id: int, days: int = 30) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT date_trunc('day', m.created_at)::date AS day, count(*) AS messages
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.site_id = $1 AND m.role = 'assistant'
          AND m.created_at > now() - ($2 || ' days')::interval
        GROUP BY 1 ORDER BY 1
        """,
        site_id,
        str(int(days)),
    )
    return [{"day": str(r["day"]), "messages": int(r["messages"])} for r in rows]


async def top_questions(site_id: int, days: int = 30, limit: int = 20) -> list[dict[str, Any]]:
    """Most frequent visitor questions, lightly normalized."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT lower(trim(m.content)) AS question, count(*) AS n
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.site_id = $1 AND m.role = 'user'
          AND m.created_at > now() - ($2 || ' days')::interval
        GROUP BY 1 ORDER BY n DESC, question LIMIT $3
        """,
        site_id,
        str(int(days)),
        limit,
    )
    return [{"question": r["question"], "count": int(r["n"])} for r in rows]


async def unanswered_questions(
    site_id: int, days: int = 30, limit: int = 50
) -> list[dict[str, Any]]:
    """Questions the bot could not answer: the content-gap report."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT u.content AS question, m.created_at
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        JOIN LATERAL (
            SELECT content FROM messages
            WHERE conversation_id = m.conversation_id AND role = 'user' AND id < m.id
            ORDER BY id DESC LIMIT 1
        ) u ON true
        WHERE c.site_id = $1 AND m.role = 'assistant' AND NOT m.answered
          AND m.created_at > now() - ($2 || ' days')::interval
        ORDER BY m.created_at DESC LIMIT $3
        """,
        site_id,
        str(int(days)),
        limit,
    )
    return [
        {"question": r["question"], "asked_at": r["created_at"].isoformat()} for r in rows
    ]


async def recent_conversations(site_id: int, limit: int = 25) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT c.id, c.visitor_id, c.created_at,
               count(m.id) FILTER (WHERE m.role = 'user') AS user_messages,
               max(m.created_at) AS last_activity
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE c.site_id = $1
        GROUP BY c.id ORDER BY last_activity DESC NULLS LAST LIMIT $2
        """,
        site_id,
        limit,
    )
    return [
        {
            "id": int(r["id"]),
            "visitor_id": r["visitor_id"],
            "started_at": r["created_at"].isoformat(),
            "user_messages": int(r["user_messages"] or 0),
        }
        for r in rows
    ]


async def conversation_transcript(site_id: int, conversation_id: int) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT m.role, m.content, m.answered, m.feedback, m.created_at
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        WHERE c.site_id = $1 AND m.conversation_id = $2
        ORDER BY m.id
        """,
        site_id,
        conversation_id,
    )
    return [
        {
            "role": r["role"],
            "content": r["content"],
            "answered": r["answered"],
            "feedback": r["feedback"],
            "at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def list_leads(site_id: int, limit: int = 100) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, email, name, note, visitor_id, conversation_id, created_at "
        "FROM leads WHERE site_id = $1 ORDER BY created_at DESC LIMIT $2",
        site_id,
        limit,
    )
    return [
        {
            "id": int(r["id"]),
            "email": r["email"],
            "name": r["name"],
            "note": r["note"],
            "conversation_id": r["conversation_id"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def list_handoffs(site_id: int, limit: int = 100) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT id, email, message, status, conversation_id, created_at "
        "FROM handoffs WHERE site_id = $1 ORDER BY created_at DESC LIMIT $2",
        site_id,
        limit,
    )
    return [
        {
            "id": int(r["id"]),
            "email": r["email"],
            "message": r["message"],
            "status": r["status"],
            "conversation_id": r["conversation_id"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
