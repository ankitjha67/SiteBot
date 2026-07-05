# Feature Parity Plan

Gap analysis against the major starred open-source and commercial chatbot
products (July 2026): Open WebUI (~135k stars), Chatwoot, LibreChat,
AnythingLLM, Botpress, Typebot, DocsGPT, RAGFlow, Danswer/Onyx, and the
commercial benchmarks Chatbase and SiteGPT.

Legend: ✅ SiteBot has it · 🅐/🅑/🅒 planned batch · ✖ deliberately out of scope.

## Gap matrix

| Feature | Seen in | SiteBot |
| --- | --- | --- |
| Grounded RAG with citations | Chatbase, DocsGPT, Danswer | ✅ |
| Crawl website + sitemap | Chatbase, SiteGPT | ✅ |
| **Multi-turn conversation memory** | every chat product | ✅ |
| **File upload sources (PDF/DOCX/TXT/MD)** | Chatbase, AnythingLLM, DocsGPT | ✅ |
| **Manual Q&A + raw text sources** | Chatbase, SiteGPT | ✅ |
| **Knowledge-base browser (view/delete indexed content)** | AnythingLLM, Danswer | ✅ |
| **Per-bot model choice (multi-provider)** | Chatbase (15+ models), LibreChat | ✅ |
| **Custom instructions per bot** | Chatbase, Open WebUI | ✅ |
| **Hybrid retrieval (vector + keyword fusion)** | RAGFlow, Danswer | ✅ |
| **In-dashboard playground / test chat** | Chatbase, Botpress | ✅ |
| **Live agent takeover (inbox reply → widget)** | Chatwoot, Chatbase Slack handoff | ✅ |
| **Transcript export (CSV/JSON)** | Chatwoot, Chatbase | ✅ |
| **Data retention auto-purge (GDPR)** | Chatwoot, enterprise buyers | ✅ |
| **Proactive engagement teaser** | Intercom-style, Chatwoot campaigns | ✅ |
| **Widget conversation persistence across pages** | all widget products | ✅ |
| **Widget dark mode + markdown rendering** | Open WebUI, LibreChat | ✅ |
| Multi-channel: Telegram, Slack, WhatsApp | Chatwoot, Botpress, Chatbase | ✅ |
| Follow-up question suggestions | Perplexity-style, Chatbase | ✅ |
| Widget UI localisation (en/es/fr/de/hi/pt) | SiteGPT (95+ languages) | ✅ (answers already follow visitor language) |
| Team members / roles per tenant | Chatwoot, Chatbase | ✅ |
| Weekly email/webhook digest | Chatwoot reports | ✅ |
| Auto re-sync on content change | SiteGPT auto-sync | ✅ (scheduled re-crawl + content hashing) |
| Lead capture | Chatbase, SiteGPT | ✅ |
| Analytics + unanswered report | Chatbase | ✅ |
| AI Actions / tool calling (lookups, workflows) | Chatbase Actions, Botpress LLMz | ✅ |
| Visual flow builder | Typebot, Botpress | ✖ (different product category) |
| Omnichannel shared inbox (email/social) | Chatwoot | ✖ (Chatwoot-scale scope) |
| SOC 2 / SSO | Chatbase | Phase-3 roadmap (docs/ROADMAP.md) |

## Batch A (shipped) — product parity core

1. Conversation memory: last N turns (per-site `history_turns`) passed to the
   model; answer cache applies to first turns only.
2. Knowledge sources beyond the crawler: file upload (PDF/DOCX/TXT/MD), raw
   text, and Q&A pairs; sources browser with per-source delete; indexed pages
   browser with per-page delete. Full re-index preserves uploaded sources.
3. Hybrid retrieval: reciprocal-rank fusion of pgvector and trigram results.
4. Per-site `model_provider` + `model_name` override and `custom_instructions`
   appended to the system prompt.
5. Live agent inbox: reply to any conversation from the dashboard; the widget
   polls for agent messages and renders them distinctly.
6. Playground chat inside the dashboard (admin-authenticated, bypasses CORS).
7. Transcript export as CSV or JSON.
8. Retention: per-site `retention_days`; nightly purge cron on the worker.
9. Widget: persistent conversation across page loads, proactive teaser
   (`proactive_message` + delay), markdown-lite rendering, dark-mode support.

## Batch B (shipped)

All shipped: Telegram + Slack channels (webhook-verified, background replies,
per-visitor conversation memory), follow-up question suggestions (SSE
`followups` event + widget chips), widget i18n (en/es/fr/de/hi/pt), team
member keys with admin/viewer roles, weekly digest webhook (Monday 08:00 UTC
cron). WhatsApp moves to Batch C alongside AI Actions.

## Batch C (shipped)

AI Actions: declarative per-site tools (`http` calls with {param} templating,
static headers for API keys, SSRF guard, 8s timeout, 4KB result cap; `link`
hand-offs). Provider-agnostic two-phase loop: a JSON planner call decides
whether an action applies, the result is injected into the grounded prompt as
fresh authoritative-but-untrusted data, surfaced as an `action` SSE event, and
never cached. Plus the WhatsApp Cloud API channel (verify handshake,
X-Hub-Signature-256 checks, background replies with conversation memory).

Sources: [NocoBase top-starred AI projects](https://www.nocobase.com/en/blog/github-open-source-ai-projects),
[Botpress open-source chatbot survey](https://botpress.com/blog/open-source-chatbots),
[Chatbase review](https://sitegpt.ai/blog/chatbase-review),
[Chatbase vs SiteGPT](https://sitespeak.ai/blog/chatbase-vs-sitegpt),
[CustomGPT vs Chatbase](https://customgpt.ai/comparison/customgpt-vs-chatbase/).
