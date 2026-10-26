"""Provider-agnostic AI wrapper.

Supported providers:
  openai             - OpenAI Chat Completions API
  openai_compatible  - Any OpenAI-compatible endpoint (Groq, OpenRouter, Together, LM Studio, vLLM...)
  anthropic          - Anthropic Messages API
  gemini             - Google Gemini generateContent API
  ollama             - Local Ollama server
  command            - Any CLI that reads a prompt on stdin and prints a reply on stdout
  none               - AI disabled; callers fall back to heuristics
"""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from typing import Any

import httpx


class LLMError(RuntimeError):
    pass


def extract_json(text: str) -> Any:
    """Pull the first JSON object/array out of a model response (tolerates code fences and chatter)."""
    if text is None:
        raise LLMError("empty response")
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(cleaned):
        if ch in "{[":
            try:
                obj, _ = decoder.raw_decode(cleaned[i:])
                return obj
            except json.JSONDecodeError:
                continue
    raise LLMError(f"could not parse JSON from model output: {text[:300]!r}")


class LLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.provider = (self.cfg.get("provider") or "none").lower()
        self.model = self.cfg.get("model")
        self.api_key = self.cfg.get("api_key") or ""
        self.base_url = self.cfg.get("base_url")
        self.temperature = self.cfg.get("temperature")
        self.max_tokens = int(self.cfg.get("max_tokens") or 4000)
        self.timeout = float(self.cfg.get("timeout") or 120)
        self._client: httpx.Client | None = None

    @property
    def available(self) -> bool:
        if self.provider == "none":
            return False
        if self.provider in ("openai", "anthropic", "gemini"):
            return bool(self.api_key)
        if self.provider == "command":
            return bool(self.cfg.get("command"))
        return True  # ollama / openai_compatible may not need a key

    def unavailable_reason(self) -> str:
        """Human explanation of why AI is off ('' if it's on)."""
        if self.available:
            return ""
        if self.provider == "none":
            return "AI is turned off (provider: none) - using keyword scoring and templates"
        if self.provider in ("openai", "anthropic", "gemini"):
            env = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "gemini": "GEMINI_API_KEY"}[self.provider]
            return (f"AI provider is '{self.provider}' but no API key is set - add {env} to .env "
                    f"(or Settings > AI). Falling back to keyword scoring and templates")
        if self.provider == "command":
            return "AI provider is 'command' but no command is set - falling back to keyword scoring"
        return "AI is not available - falling back to keyword scoring"

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    # ------------------------------------------------------------------ public API
    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False,
                 max_tokens: int | None = None) -> str:
        if not self.available:
            raise LLMError(f"AI provider '{self.provider}' is not configured")
        handler = {
            "openai": self._openai,
            "openai_compatible": self._openai,
            "anthropic": self._anthropic,
            "gemini": self._gemini,
            "ollama": self._ollama,
            "command": self._command,
        }.get(self.provider)
        if handler is None:
            raise LLMError(f"unknown AI provider '{self.provider}'")
        return self._with_retries(lambda: handler(prompt, system, json_mode, max_tokens or self.max_tokens))

    def complete_json(self, prompt: str, system: str | None = None, max_tokens: int | None = None) -> Any:
        sys_prompt = (system + "\n\n" if system else "") + "Respond with valid JSON only. No prose, no code fences."
        text = self.complete(prompt, sys_prompt, json_mode=True, max_tokens=max_tokens)
        try:
            return extract_json(text)
        except LLMError:
            fix = self.complete(
                "The following was supposed to be valid JSON but is not. Return ONLY the corrected JSON.\n\n" + text,
                "You repair malformed JSON.", json_mode=True, max_tokens=max_tokens)
            return extract_json(fix)

    # ------------------------------------------------------------------ internals
    def _with_retries(self, fn, attempts: int = 4):
        delay = 2.0
        for i in range(attempts):
            try:
                return fn()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code in (429, 500, 502, 503, 504, 529) and i < attempts - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise LLMError(f"{self.provider} HTTP {code}: {e.response.text[:500]}") from e
            except (httpx.TransportError, subprocess.TimeoutExpired) as e:
                if i < attempts - 1:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise LLMError(f"{self.provider} request failed: {e}") from e

    def _openai(self, prompt, system, json_mode, max_tokens) -> str:
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.provider == "openai":
            body["max_completion_tokens"] = max_tokens
        else:
            body["max_tokens"] = max_tokens
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        r = self.client.post(f"{base}/chat/completions", json=body, headers=headers)
        if r.status_code == 400 and json_mode and "response_format" in r.text:
            body.pop("response_format")  # some compatible servers don't support JSON mode
            r = self.client.post(f"{base}/chat/completions", json=body, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""

    def _anthropic(self, prompt, system, json_mode, max_tokens) -> str:
        base = (self.base_url or "https://api.anthropic.com").rstrip("/")
        body: dict[str, Any] = {"model": self.model, "max_tokens": max_tokens,
                                "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        if self.temperature is not None:
            body["temperature"] = self.temperature
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        r = self.client.post(f"{base}/v1/messages", json=body, headers=headers)
        r.raise_for_status()
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")

    def _gemini(self, prompt, system, json_mode, max_tokens) -> str:
        base = (self.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        gen: dict[str, Any] = {"maxOutputTokens": max_tokens}
        if self.temperature is not None:
            gen["temperature"] = self.temperature
        if json_mode:
            gen["responseMimeType"] = "application/json"
        body: dict[str, Any] = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        r = self.client.post(f"{base}/models/{self.model}:generateContent", json=body,
                             headers={"x-goog-api-key": self.api_key})
        r.raise_for_status()
        cands = r.json().get("candidates") or []
        if not cands:
            raise LLMError(f"gemini returned no candidates: {r.text[:300]}")
        return "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))

    def _ollama(self, prompt, system, json_mode, max_tokens) -> str:
        base = (self.base_url or "http://localhost:11434").rstrip("/")
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False,
                                "options": {"num_predict": max_tokens}}
        if self.temperature is not None:
            body["options"]["temperature"] = self.temperature
        if json_mode:
            body["format"] = "json"
        r = self.client.post(f"{base}/api/chat", json=body)
        r.raise_for_status()
        return r.json()["message"]["content"]

    def _command(self, prompt, system, json_mode, max_tokens) -> str:
        cmd = self.cfg["command"]
        full = (f"{system}\n\n" if system else "") + prompt
        args = cmd if isinstance(cmd, list) else shlex.split(cmd, posix=False)
        proc = subprocess.run(args, input=full, capture_output=True, text=True, encoding="utf-8",
                              timeout=self.timeout)
        if proc.returncode != 0:
            raise LLMError(f"AI command failed ({proc.returncode}): {proc.stderr[:500]}")
        return proc.stdout
