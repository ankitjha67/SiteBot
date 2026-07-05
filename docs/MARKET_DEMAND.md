# Market Demand → SiteBot Coverage

Analysis of 50 live "chatbot" job postings (Upwork, July 2026;
`upwork_chatbot_jobs_all_pages.csv.xlsx`) mapped to SiteBot capabilities.
Each theme shows how many of the 50 jobs mention it.

## Demand vs. coverage

| Demand theme | Jobs | SiteBot |
| --- | ---: | --- |
| OpenAI / GPT models | 24 | ✅ `ANSWER_PROVIDER=openai` per site or globally |
| Automation (n8n / Make / Zapier) | 23 | ✅ AI Actions (outbound HTTP) + lead/handoff/digest webhooks + public `/v1/chat` API |
| **Voice AI (speech in/out)** | 22 | ✅ **new:** browser STT (dictate) + TTS (spoken answers) in the widget, 6 locales |
| CRM (HubSpot, GHL, Zoho, Salesforce) | 19 | ✅ via AI Actions (HTTP POST) + lead webhooks |
| Lead generation / qualification | 18 | ✅ Lead capture + webhooks + high-intent trigger |
| RAG / knowledge base | 17 | ✅ Crawl + files + text + Q&A + **DB dump**, hybrid retrieval, citations |
| Claude / Anthropic | 16 | ✅ default provider |
| Website widget / WordPress / Webflow | 15 | ✅ one-tag embeddable widget, Shadow DOM |
| Database (Supabase / Postgres / MySQL) | 14 | ✅ Postgres+pgvector; **new:** learn from a `.sql` database dump |
| Email notifications | 11 | ✅ native SMTP alerts for leads/handoffs + email digest, plus webhooks |
| Gemini | 9 | ✅ `ANSWER_PROVIDER=gemini` |
| Analytics / reporting | 9 | ✅ Analytics, unanswered report, weekly digest |
| Appointment / booking | 8 | ✅ AI Actions (link to Cal.com/Calendly, or HTTP booking API) |
| E-commerce (Shopify / orders) | 8 | ✅ AI Actions (order-status lookups) + DB-dump product catalog |
| Multilingual | 7 | ✅ Answers follow visitor language; widget UI in 6 languages |
| SMS (Twilio) | 6 | ✅ Twilio SMS channel (signature-verified inbound, out-of-band reply) |
| Messenger / Instagram | 6 | ✅ Meta Messenger/Instagram channel (verify handshake + signature) |
| Human handoff / live agent | 5 | ✅ Live agent inbox → widget, plus handoff webhooks |
| LangChain / LlamaIndex | 5 | ✅ equivalent pipeline built in; no lock-in |
| **Local / open-source models (Llama, Qwen, Mistral)** | 5 | ✅ **`ANSWER_PROVIDER=openai_compatible`** → Ollama/vLLM/LM Studio |
| **Security / privacy / confidentiality** | 5 | ✅ **new:** Secrets Guardian (never-reveal), GDPR retention, per-site CORS, hashed keys |
| Avatar persona | 4 | ✅ animated avatar (pulse/bounce while composing & speaking) + custom image |
| WhatsApp | 4 | ✅ WhatsApp Cloud API channel |
| Payments (Stripe) | 3 | ✅ Stripe billing built in; checkout via AI Actions |
| Telegram | 1 | ✅ Telegram channel |
| Slack | 1 | ✅ Slack channel |
| Microsoft Teams | 1 | ✅ Bot Framework channel (client-credentials reply) |

**Covered or exceeded: all 26 themes.** The former partial items (native SMTP
email, SMS/Twilio, Messenger/Instagram, Microsoft Teams, animated avatar) are
now shipped. Full 3D/WebGL avatars remain a deliberate non-goal for a
dependency-free embeddable widget; the animated 2D persona covers the demand.

## Running on local open-source models (Qwen, Llama, Mistral)

SiteBot answers through a provider seam ([llm.py](../src/sitebot/llm.py)), so a
fully local, zero-API-cost, data-never-leaves-your-server deployment is a config
change — no code:

```bash
# 1. Run a local model with Ollama (or vLLM / LM Studio — all expose an
#    OpenAI-compatible API).
ollama run qwen2.5        # or: ollama run llama3.1  /  mistral

# 2. Point SiteBot at it (per site in the dashboard, or globally in .env):
ANSWER_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=http://localhost:11434/v1
ANSWER_MODEL=qwen2.5
# OPENAI_COMPATIBLE_API_KEY is optional (Ollama ignores it).
```

Pair it with local embeddings (`EMBED_PROVIDER=local`) and the whole pipeline —
crawl, embed, retrieve, answer, guard — runs on your own hardware with no
outbound API calls. The Secrets Guardian's semantic auditor also runs on the
local model, so confidentiality enforcement works offline too.

## Security: the Secrets Guardian

See the "Secrets Guardian" section in the [README](../README.md). It is
defense-in-depth and does **not** rely on the model obeying a prompt: secret
content is filtered out of retrieval, the finished answer is deterministically
scanned for owner-defined secrets (this holds even under a successful
jailbreak), and an optional AI auditor catches paraphrased or translated topic
leaks. Verified live against direct extraction, "ignore all instructions /
developer mode" jailbreaks, and social-engineering attempts.
