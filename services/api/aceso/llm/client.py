"""The only module that talks to a language model (the "Swap Test" seam).

external -> any OpenAI-compatible endpoint (Groq by default)
onprem   -> Ollama on this machine; nothing leaves it
"""
import json
import logging
from typing import Protocol

import httpx

from aceso.config import settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    id: str

    def extract_json(self, system: str, user: str) -> dict: ...


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])


class ExternalLLM:
    def __init__(self):
        if not settings.llm_api_key:
            raise LLMError("LLM_API_KEY is not set in .env")
        self.id = f"external:{settings.llm_model}"

    def _call(self, messages: list[dict]) -> str:
        response = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.llm_model, "messages": messages, "temperature": 0,
                  "response_format": {"type": "json_object"}},
            timeout=90,
        )
        if response.status_code != 200:
            raise LLMError(f"LLM HTTP {response.status_code}: {response.text[:300]}")
        return response.json()["choices"][0]["message"]["content"] or ""

    def extract_json(self, system: str, user: str) -> dict:
        return _with_one_repair(self._call, system, user)


class OllamaLLM:
    def __init__(self):
        self.id = f"onprem:{settings.ollama_model}"

    def _call(self, messages: list[dict]) -> str:
        response = httpx.post(
            f"{settings.ollama_url.rstrip('/')}/api/chat",
            json={"model": settings.ollama_model, "messages": messages, "stream": False,
                  "format": "json", "options": {"temperature": 0}},
            timeout=300,
        )
        if response.status_code != 200:
            raise LLMError(f"Ollama HTTP {response.status_code}: {response.text[:300]}")
        return response.json()["message"]["content"]

    def extract_json(self, system: str, user: str) -> dict:
        return _with_one_repair(self._call, system, user)


class RecordingLLM:
    """Wraps any client and keeps every prompt handed to it, in order.

    The pipeline stores these as the record of what left the machine, so the
    record cannot drift from what the adapter was actually given.
    """

    def __init__(self, inner: LLMClient):
        self.inner, self.id = inner, inner.id
        self.sent: list[dict] = []

    def extract_json(self, system: str, user: str) -> dict:
        self.sent.append({"system": system, "user": user})
        return self.inner.extract_json(system, user)


def _with_one_repair(call, system: str, user: str) -> dict:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        raw = call(messages)
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM unreachable: {exc}") from exc
    try:
        return _parse_json(raw)
    except ValueError:
        logger.warning("LLM returned invalid JSON; asking once for a repair")
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "That was not valid JSON. Reply with the JSON object only."}]
        try:
            return _parse_json(call(messages))
        except (ValueError, httpx.HTTPError) as exc:
            raise LLMError(f"LLM did not return valid JSON: {exc}") from exc


def get_llm() -> LLMClient:
    return OllamaLLM() if settings.llm_mode == "onprem" else ExternalLLM()
