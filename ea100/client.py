"""Minimal OpenAI-compatible chat client (stdlib only).

Works against any server that speaks /v1/chat/completions:
llama.cpp llama-server, vLLM, LM Studio, Ollama, DeepSeek/OpenRouter/etc.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


class ChatClient:
    def __init__(self, base_url: str, api_key: str | None = None,
                 timeout: int = 300, max_retries: int = 3, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.verify_ssl = verify_ssl

    # -- public API ----------------------------------------------------------
    def chat(self, messages: list[dict], model: str,
             temperature: float = 0.0, max_tokens: int = 2048,
             extra: dict | None = None) -> dict:
        """Send a chat request. Returns:
        {text, prompt_tokens, completion_tokens, latency_s, finish_reason, raw}
        Raises RuntimeError after retries are exhausted.
        """
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **(extra or {}),
        }
        started = time.monotonic()
        raw = self._post(payload)
        latency = time.monotonic() - started
        try:
            choice = raw["choices"][0]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"unexpected response shape: {str(raw)[:300]}") from e
        msg = choice.get("message", {})
        text = normalize_content(msg.get("content"))
        if not text:
            text = normalize_content(msg.get("reasoning_content"))  # deepseek-reasoner style
        usage = raw.get("usage", {}) or {}
        timings = raw.get("timings", {}) or {}  # llama.cpp server provides these
        return {
            "text": text or "",
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "latency_s": round(latency, 3),
            "finish_reason": choice.get("finish_reason"),
            "prompt_tokens_per_s": timings.get("prompt_per_second"),
            "generation_tokens_per_s": timings.get("predicted_per_second"),
            "raw": raw,
        }

    def image_message(self, image_path: str | Path) -> dict:
        """Build a user message part that attaches a local image (PNG) as a data URL."""
        path = Path(image_path)
        b64 = base64.b64encode(path.read_bytes()).decode()
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}

    # -- internals -----------------------------------------------------------
    def _post(self, payload: dict) -> dict:
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            try:
                ctx = None if self.verify_ssl else _no_verify_ctx()
                with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
                    return json.loads(resp.read().decode())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:300]
                last_err = RuntimeError(f"HTTP {e.code} from {url}: {detail}")
                if e.code in (400, 401, 403, 404):
                    raise last_err  # not transient
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last_err = RuntimeError(f"network error: {e}")
            if attempt < self.max_retries:
                time.sleep(2 ** attempt)
        raise last_err or RuntimeError("request failed")


def _no_verify_ctx():
    import ssl

    return ssl._create_unverified_context()


def normalize_content(content) -> str:
    """Handle string content or list-of-parts content (OpenAI vision style)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, dict):
                if p.get("type") == "text":
                    parts.append(p.get("text", ""))
                elif p.get("type") == "image_url":
                    parts.append("[image]")
            else:
                parts.append(str(p))
        return "\n".join(parts)
    return str(content)
