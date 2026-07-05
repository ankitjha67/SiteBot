"""Answer-model providers. One streaming seam, many backends.

The default is Anthropic Claude. Switch globally with ANSWER_PROVIDER, or per
site via the site's model_provider/model_name settings:

  anthropic          Claude via the official SDK (default).
  openai             OpenAI chat completions (GPT models).
  gemini             Google Gemini (pip install ".[gemini]").
  openai_compatible  Any OpenAI-compatible endpoint: Ollama, Groq, Together,
                     Mistral, vLLM, LM Studio... set OPENAI_COMPATIBLE_BASE_URL.

Every provider implements the same contract: given a system prompt and a
user/assistant message history (last entry is the current question), yield
answer text chunks. rag.py stays provider-agnostic.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from sitebot.config import Settings

Messages = list[dict[str, str]]  # [{"role": "user"|"assistant", "content": ...}]


class Provider(Protocol):
    def __call__(
        self, system: str, messages: Messages, settings: Settings, model: str
    ) -> AsyncIterator[str]: ...


# Client cache: SDK clients hold a connection pool, so recreating one per
# request means a fresh TCP/TLS handshake for every chat. Reusing them keeps
# connections warm under concurrent load. Keyed by (sdk, base_url, api_key);
# bounded because keys come from site configs, not user input.
_CLIENT_CACHE: dict[tuple[str, str, str], object] = {}
_CLIENT_CACHE_MAX = 256


def _cached_client(kind: str, base_url: str, api_key: str, factory):  # type: ignore[no-untyped-def]
    key = (kind, base_url, api_key)
    client = _CLIENT_CACHE.get(key)
    if client is None:
        if len(_CLIENT_CACHE) >= _CLIENT_CACHE_MAX:
            _CLIENT_CACHE.clear()  # crude but safe; refills on demand
        client = factory()
        _CLIENT_CACHE[key] = client
    return client


# -------------------------------- anthropic --------------------------------
async def _stream_anthropic(
    system: str, messages: Messages, settings: Settings, model: str
) -> AsyncIterator[str]:
    from anthropic import AsyncAnthropic

    client = _cached_client(
        "anthropic", "", settings.anthropic_api_key,
        lambda: AsyncAnthropic(api_key=settings.anthropic_api_key),
    )
    async with client.messages.stream(
        model=model,
        max_tokens=settings.answer_max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        async for text in stream.text_stream:
            yield text


# --------------------------------- openai ----------------------------------
async def _stream_openai(
    system: str, messages: Messages, settings: Settings, model: str,
    base_url: str | None = None, api_key: str | None = None,
) -> AsyncIterator[str]:
    from openai import AsyncOpenAI

    resolved_key = api_key if api_key is not None else settings.openai_api_key
    client = _cached_client(
        "openai", base_url or "", resolved_key,
        lambda: AsyncOpenAI(api_key=resolved_key, base_url=base_url),
    )
    stream = await client.chat.completions.create(
        model=model,
        max_tokens=settings.answer_max_tokens,
        messages=[{"role": "system", "content": system}, *messages],
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


async def _stream_openai_compatible(
    system: str, messages: Messages, settings: Settings, model: str
) -> AsyncIterator[str]:
    """Ollama, Groq, Together, Mistral, vLLM, LM Studio - anything that speaks
    the OpenAI chat-completions protocol at a custom base URL."""
    if not settings.openai_compatible_base_url:
        raise RuntimeError(
            "ANSWER_PROVIDER=openai_compatible requires OPENAI_COMPATIBLE_BASE_URL "
            "(e.g. http://localhost:11434/v1 for Ollama)."
        )
    async for text in _stream_openai(
        system, messages, settings, model,
        base_url=settings.openai_compatible_base_url,
        # Many local servers ignore the key but the client requires one.
        api_key=settings.openai_compatible_api_key or "not-needed",
    ):
        yield text


# --------------------------------- gemini ----------------------------------
async def _stream_gemini(
    system: str, messages: Messages, settings: Settings, model: str
) -> AsyncIterator[str]:
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as exc:
        raise RuntimeError(
            'ANSWER_PROVIDER=gemini requires the google-genai package: pip install ".[gemini]"'
        ) from exc

    client = _cached_client(
        "gemini", "", settings.gemini_api_key,
        lambda: genai.Client(api_key=settings.gemini_api_key),
    )
    contents = [
        genai_types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[genai_types.Part(text=m["content"])],
        )
        for m in messages
    ]
    stream = await client.aio.models.generate_content_stream(
        model=model,
        contents=contents,
        config=genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=settings.answer_max_tokens,
        ),
    )
    async for chunk in stream:
        if chunk.text:
            yield chunk.text


# -------------------------------- dispatch ---------------------------------
PROVIDERS: dict[str, Provider] = {
    "anthropic": _stream_anthropic,
    "openai": _stream_openai,
    "gemini": _stream_gemini,
    "openai_compatible": _stream_openai_compatible,
}


# Which Settings field holds the key for each provider.
_KEY_FIELD = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "openai_compatible": "openai_compatible_api_key",
}


def stream_answer(
    system: str,
    messages: Messages,
    settings: Settings,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> AsyncIterator[str]:
    """Stream answer chunks. provider/model/api_key default to the server-wide
    config and can each be overridden per site (client brings its own key)."""
    name = provider or settings.answer_provider
    impl = PROVIDERS.get(name)
    if impl is None:
        raise RuntimeError(
            f"Unknown answer provider {name!r}. Choose one of: {', '.join(sorted(PROVIDERS))}"
        )
    # A per-site key is injected by copying Settings with the provider's key
    # field overridden — no provider signature changes needed.
    eff = settings.model_copy(update={_KEY_FIELD[name]: api_key}) if api_key else settings
    return impl(system, messages, eff, model or settings.answer_model)
