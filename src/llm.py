"""LLM client with Ollama (local) and OpenAI (remote) fallback."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT = 60


class LLMError(Exception):
    """Raised when LLM communication fails."""


class LLMClient:
    """Unified LLM client that tries Ollama first, then falls back to OpenAI."""

    def __init__(
        self,
        ollama_url: str | None = None,
        ollama_model: str | None = None,
        openai_api_key: str | None = None,
        openai_model: str | None = None,
    ) -> None:
        self.ollama_url = ollama_url or os.environ.get(
            "OLLAMA_HOST", DEFAULT_OLLAMA_URL
        )
        self.ollama_model = ollama_model or os.environ.get(
            "OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL
        )
        self.openai_api_key = openai_api_key or os.environ.get("OPENAI_API_KEY", "")
        self.openai_model = openai_model or os.environ.get(
            "OPENAI_MODEL", DEFAULT_OPENAI_MODEL
        )

    def chat(self, prompt: str, system: str = "") -> str:
        """Send a prompt and return the response text.

        Tries Ollama first; falls back to OpenAI if Ollama is unavailable.
        """
        try:
            return self._chat_ollama(prompt, system)
        except (LLMError, urllib.error.URLError, OSError):
            if self.openai_api_key:
                return self._chat_openai(prompt, system)
            raise LLMError(
                "Ollama is unavailable and no OPENAI_API_KEY is set. "
                f"Ensure Ollama is running at {self.ollama_url} or set OPENAI_API_KEY."
            )

    def _chat_ollama(self, prompt: str, system: str) -> str:
        """Send a chat request to a local Ollama instance."""
        url = f"{self.ollama_url}/api/generate"
        payload: dict[str, Any] = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc

        response_text = body.get("response", "")
        if not response_text:
            raise LLMError("Ollama returned an empty response.")
        return response_text

    def _chat_openai(self, prompt: str, system: str) -> str:
        """Send a chat request to the OpenAI API."""
        url = "https://api.openai.com/v1/chat/completions"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.openai_model,
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 1024,
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc

        choices = body.get("choices", [])
        if not choices:
            raise LLMError("OpenAI returned no choices.")
        return choices[0].get("message", {}).get("content", "")
