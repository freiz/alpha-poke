"""Minimal OpenRouter chat client with a disk cache and cost accounting.

Configuration comes from the project-level ``.env`` (git-ignored):
    OPENROUTER_API_KEY=...
    LLM_MODEL=google/gemini-3.8-flash

Every response is cached under ``data/llm_cache/<sha256>.json`` keyed by (model, messages,
params), so re-running an analysis never pays twice. Usage/cost reported by OpenRouter is
accumulated in ``LLMClient.spent_usd`` and appended to a project-wide ledger
(``data/llm_cache/ledger.jsonl``). Before every paid call the ledger total is checked against
``LLM_BUDGET_USD`` (env / .env, default 3.0) and ``BudgetExceeded`` is raised instead of calling.
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
LEDGER = CACHE / "ledger.jsonl"


class BudgetExceeded(RuntimeError):
    pass


class TruncatedResponse(RuntimeError):
    pass


def ledger_total() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(
        json.loads(line).get("cost", 0.0) for line in LEDGER.read_text().splitlines() if line
    )


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
    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        budget_usd: float | None = None,
        reasoning_effort: str | None = None,
    ):
        env = load_env()
        self.budget_usd = float(
            budget_usd
            if budget_usd is not None
            else os.environ.get("LLM_BUDGET_USD") or env.get("LLM_BUDGET_USD") or 3.0
        )
        self.last_latency = 0.0
        self.reasoning_effort = reasoning_effort  # e.g. "low"; None = provider default
        self.reasoning_tokens = 0
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
            [
                self.model,
                messages,
                self.temperature,
                self.max_tokens,
                json_mode,
                self.reasoning_effort,
            ],
            sort_keys=True,
        )
        return hashlib.sha256(blob.encode()).hexdigest()

    def chat(self, messages: list[dict], json_mode: bool = False) -> str:
        path = CACHE / f"{self._key(messages, json_mode)}.json"
        if path.exists():
            self.cache_hits += 1
            cached = json.loads(path.read_text())
            self.last_latency = cached.get("latency", 0.0)
            return cached["content"]
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "usage": {"include": True},
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.reasoning_effort:
            body["reasoning"] = {"effort": self.reasoning_effort}
        total = ledger_total()
        if total >= self.budget_usd:
            raise BudgetExceeded(f"LLM spend ${total:.2f} >= budget ${self.budget_usd:.2f}")
        t0 = time.monotonic()
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
        self.last_latency = time.monotonic() - t0
        data = r.json()
        choice = data["choices"][0]
        content = choice["message"].get("content") or ""
        usage = data.get("usage", {})
        cost = float(usage.get("cost") or 0.0)
        self.spent_usd += cost
        self.calls += 1
        self.reasoning_tokens += int(
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0
        )
        with LEDGER.open("a") as f:
            f.write(json.dumps({"t": time.time(), "model": self.model, "cost": cost}) + "\n")
        if not content.strip() or choice.get("finish_reason") == "length":
            # never cache empty / truncated answers (e.g. reasoning used up max_tokens)
            raise TruncatedResponse(
                f"{self.model}: empty or truncated response "
                f"(finish_reason={choice.get('finish_reason')}, "
                f"completion_tokens={usage.get('completion_tokens')})"
            )
        path.write_text(
            json.dumps(
                {
                    "model": self.model,
                    "content": content,
                    "usage": usage,
                    "latency": self.last_latency,
                }
            )
        )
        return content

    def chat_json(self, messages: list[dict]) -> dict:
        """Chat expecting a JSON object. Tolerates code fences / surrounding prose, retries once
        with a stricter instruction, and once with a doubled token limit if truncated."""
        for attempt in range(2):
            try:
                text = self.chat(messages, json_mode=True)
            except TruncatedResponse:
                if attempt:
                    raise
                self.max_tokens *= 2
                continue
            parsed = _parse_json_object(text)
            if parsed is not None:
                return parsed
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": "Return ONLY the JSON object, no other text."},
            ]
        raise ValueError(f"{self.model}: could not parse a JSON object")


def _parse_json_object(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else {"answers": out}
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
