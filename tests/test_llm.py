import json

import httpx
import pytest

from applybot.llm import LLM, LLMError, extract_json


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('```json\n{"a": [1, 2]}\n```') == {"a": [1, 2]}
    assert extract_json('Sure! Here you go: {"x": "y"} hope that helps') == {"x": "y"}
    assert extract_json("[1, 2, 3]") == [1, 2, 3]
    with pytest.raises(LLMError):
        extract_json("no json here")


def _llm(provider, handler, **extra):
    llm = LLM({"provider": provider, "model": "m", "api_key": "k", **extra})
    llm._client = httpx.Client(transport=httpx.MockTransport(handler))
    return llm


def test_openai_provider():
    def handler(req):
        body = json.loads(req.content)
        assert req.headers["authorization"] == "Bearer k"
        assert body["messages"][-1]["content"] == "hi"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]})
    assert _llm("openai", handler).complete_json("hi") == {"ok": True}


def test_openai_compatible_retries_without_json_mode():
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        if "response_format" in body:
            return httpx.Response(400, text="response_format not supported")
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": 1}'}}]})
    llm = _llm("openai_compatible", handler, base_url="http://local/v1")
    assert llm.complete_json("x") == {"ok": 1}
    assert len(calls) == 2


def test_anthropic_provider():
    def handler(req):
        assert req.url.path == "/v1/messages"
        assert req.headers["x-api-key"] == "k"
        body = json.loads(req.content)
        assert "system" in body
        return httpx.Response(200, json={"content": [{"type": "text", "text": "hello"}]})
    assert _llm("anthropic", handler).complete("hi", system="s") == "hello"


def test_gemini_provider():
    def handler(req):
        assert req.url.path.endswith("/models/m:generateContent")
        body = json.loads(req.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"v": 2}'}]}}]})
    assert _llm("gemini", handler).complete_json("hi") == {"v": 2}


def test_ollama_provider():
    def handler(req):
        body = json.loads(req.content)
        assert body["stream"] is False and body["format"] == "json"
        return httpx.Response(200, json={"message": {"content": '{"z": 3}'}})
    assert _llm("ollama", handler).complete_json("hi") == {"z": 3}


def test_retry_on_429(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    n = {"c": 0}

    def handler(req):
        n["c"] += 1
        if n["c"] < 3:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})
    assert _llm("openai", handler).complete("x") == "done"
    assert n["c"] == 3


def test_unavailable_provider():
    assert not LLM({"provider": "none"}).available
    assert not LLM({"provider": "openai", "api_key": ""}).available
    with pytest.raises(LLMError):
        LLM({"provider": "none"}).complete("x")


def test_command_provider():
    import sys
    llm = LLM({"provider": "command", "command": [sys.executable, "-c",
                                                 "import sys; print(sys.stdin.read().upper())"]})
    assert llm.complete("abc").strip() == "ABC"
