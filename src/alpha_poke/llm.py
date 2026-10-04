"""Minimal OpenRouter chat client with a disk cache and cost accounting.

Configuration comes from the project-level ``.env`` (git-ignored):
    OPENROUTER_API_KEY=...
    LLM_MODEL=google/gemini-3.8-flash

Every response is cached under ``data/llm_cache/<sha256>.json`` keyed by (model, messages,
params), so re-running an analysis never pays twice. Usage/cost reported by OpenRouter is
accumulated in ``LLMClient.spent_usd``.
"""

import hashlib
import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "llm_cache"
URL = "https://openrouter.ai/api/v1/chat/completions"


def load_env(path: Path = ROOT / ".env") -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


class LLMClient:
    def __init__(self, model: str | None = None, temperature: float = 0.2, max_tokens: int = 2000):
        env = load_env()
        self.key = os.environ.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_API_KEY")
        if not self.key:
            raise RuntimeError("OPENROUTER_API_KEY missing (set it in .env)")
        self.model = model or os.environ.get("LLM_MODEL") or env.get("LLM_MODEL")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.spent_usd = 0.0
        self.calls = 0
        self.cache_hits = 0
        CACHE.mkdir(parents=True, exist_ok=True)

    def _key(self, messages, json_mode) -> str:
        blob = json.dumps(
            [self.model, messages, self.temperature, self.max_tokens, json_mode], sort_keys=True
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def chat(self, messages: list[dict], json_mode: bool = False) -> str:
        path = CACHE / f"{self._key(messages, json_mode)}.json"
        if path.exists():
            self.cache_hits += 1
            return json.loads(path.read_text())["content"]
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "usage": {"include": True},
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for attempt in range(4):
            r = requests.post(
                URL,
                headers={"Authorization": f"Bearer {self.key}"},
                json=body,
                timeout=120,
            )
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(5 * 2**attempt)
                continue
            r.raise_for_status()
            break
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        self.spent_usd += float(usage.get("cost") or 0.0)
        self.calls += 1
        path.write_text(json.dumps({"model": self.model, "content": content, "usage": usage}))
        return content

    def chat_json(self, messages: list[dict]) -> dict:
        text = self.chat(messages, json_mode=True).strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)
