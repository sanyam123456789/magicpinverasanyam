"""LLM access: Groq first, OpenRouter as automatic fallback. Temperature 0.

Only prompts built from the (synthetic) challenge contexts are sent to these LLM APIs
(challenge-testing-brief.md §11). API keys come from the environment / .env and are never logged.

CLI helpers:
    python llm.py --check            ping every configured provider with a tiny request
    python llm.py --models groq      list model ids the provider offers (needs the key for groq)
    python llm.py --models openrouter [substring]
"""
import json
import re
import threading
import time

import requests

from config import env

PROVIDERS = (
    {
        "name": "opencode",
        "url": "https://opencode.ai/zen/v1/chat/completions",
        "models_url": "",
        "key_env": "OPENCODE_API_KEY",
        "model_env": "OPENCODE_MODEL",
        # deepseek-v4.1-flash is the only OpenCode Zen model verified (30/30 live pairs, this session) to answer
        # reliably in the OpenAI chat-completions shape this file speaks. It is a reasoning model: latency is high
        # (see MAGICPIN_VERA_AI_STEPS_1_TO_6.md "OpenCode Zen live validation" for the measured numbers and the
        # resulting timeout-budget decision) and it needs a large max_tokens ceiling for its hidden reasoning
        # tokens (composer.py / replies.py already send 1500 / 900, not the old 450 / 350).
        "default_model": "deepseek-v4.1-flash",
    },
    {
        "name": "groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "models_url": "https://api.groq.com/openai/v1/models",
        "key_env": "GROQ_API_KEY",
        "model_env": "GROQ_MODEL",
        "default_model": "llama-3.3-70b-versatile",
    },
    {
        "name": "openrouter",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "models_url": "https://openrouter.ai/api/v1/models",
        "key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
    },
)

_lock = threading.Lock()
_cooldown_until: dict[str, float] = {}   # provider name -> time.monotonic() until which we skip it
last_errors: dict[str, str] = {}         # provider name -> short diagnostic (never contains keys)


class LLMUnavailable(Exception):
    """Raised when no configured provider could return a usable answer."""


def model_for(provider: dict) -> str:
    return env(provider["model_env"], provider["default_model"])


def configured_providers() -> list[dict]:
    return [p for p in PROVIDERS if env(p["key_env"])]


def label() -> str:
    """Human-readable description of the LLM setup (for /v1/metadata)."""
    names = [f"{p['name']}:{model_for(p)}" for p in configured_providers()]
    return " -> ".join(names) + (" (automatic fallback)" if len(names) > 1 else "") if names else "no LLM configured"


def _set_cooldown(provider: dict, seconds: float, reason: str) -> None:
    with _lock:
        _cooldown_until[provider["name"]] = time.monotonic() + seconds
        last_errors[provider["name"]] = reason


def _post(provider: dict, messages: list[dict], max_tokens: int, timeout: float) -> requests.Response:
    headers = {"Authorization": f"Bearer {env(provider['key_env'])}", "Content-Type": "application/json"}
    body = {"model": model_for(provider), "messages": messages, "temperature": 0, "max_tokens": max_tokens, "seed": 7}
    return requests.post(provider["url"], headers=headers, json=body, timeout=(min(3.05, timeout), timeout))


def chat(messages: list[dict], max_tokens: int = 500, timeout: float = 6.0) -> tuple[str, str]:
    """Return (text, provider_name). Fails over to the next provider immediately on any error.

    `timeout` is the TOTAL budget for this call across providers (the examples table allows 10 s per tick/reply). A provider
    that still has another one behind it gets at most 60% of what is left, so a slow Groq hands over to OpenRouter quickly.
    """
    providers = configured_providers()
    if not providers:
        raise LLMUnavailable("no LLM API key configured (set GROQ_API_KEY and/or OPENROUTER_API_KEY)")
    now = time.monotonic()
    with _lock:
        ready = [p for p in providers if _cooldown_until.get(p["name"], 0.0) <= now]
    order = ready or providers  # if every provider is cooling down, still try rather than give up
    deadline = time.monotonic() + timeout
    for index, provider in enumerate(order):
        remaining = deadline - time.monotonic()
        if remaining < 0.7:
            break
        per_call = remaining if index == len(order) - 1 else max(1.0, remaining * 0.6)
        try:
            response = _post(provider, messages, max_tokens, per_call)
        except requests.RequestException as exc:
            _set_cooldown(provider, 20, f"{type(exc).__name__}")
            continue
        code = response.status_code
        if code == 200:
            try:
                text = response.json()["choices"][0]["message"]["content"] or ""
            except Exception:
                text = ""
            if text.strip():
                last_errors.pop(provider["name"], None)
                return text, provider["name"]
            _set_cooldown(provider, 10, "empty response")
        elif code == 429:
            try:
                wait = min(float(response.headers.get("retry-after", 20)), 30.0)
            except (TypeError, ValueError):
                wait = 20.0
            _set_cooldown(provider, wait, "HTTP 429 rate limited")
        elif code >= 500:
            _set_cooldown(provider, 20, f"HTTP {code}")
        else:  # 400/401/403/404: bad key or model name, i.e. a configuration problem
            _set_cooldown(provider, 300, f"HTTP {code}: {response.text[:160]}")
    raise LLMUnavailable("all configured providers failed: " + "; ".join(f"{k}={v}" for k, v in last_errors.items()))


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def extract_json(text: str):
    """Pull the first JSON object out of a model reply (tolerates code fences and <think> blocks)."""
    text = _THINK.sub("", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    raw = text[start:end + 1]
    for candidate in (raw, re.sub(r",\s*([}\]])", r"\1", raw)):
        try:
            obj = json.loads(candidate)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            continue
    return None


def chat_json(messages: list[dict], max_tokens: int = 500, timeout: float = 6.0) -> tuple[dict, str]:
    """Like chat(), but returns parsed JSON. A provider that answers with non-JSON is skipped once (same total budget)."""
    deadline = time.monotonic() + timeout
    for _ in range(2):
        remaining = deadline - time.monotonic()
        if remaining < 1.0:
            break
        text, provider = chat(messages, max_tokens, remaining)
        obj = extract_json(text)
        if obj is not None:
            return obj, provider
        for p in PROVIDERS:
            if p["name"] == provider:
                _set_cooldown(p, 10, "non-JSON answer")
    raise LLMUnavailable("providers returned no parseable JSON")


def _cli() -> None:
    import sys

    args = sys.argv[1:]
    if "--check" in args:
        for p in PROVIDERS:
            if not env(p["key_env"]):
                print(f"{p['name']:10} NOT CONFIGURED ({p['key_env']} is empty)")
                continue
            t0 = time.time()
            try:
                r = _post(p, [{"role": "user", "content": "Reply with the single word OK."}], 10, 15)
                ms = int((time.time() - t0) * 1000)
                if r.status_code == 200:
                    print(f"{p['name']:10} OK   model={model_for(p)}  {ms} ms")
                else:
                    print(f"{p['name']:10} FAIL model={model_for(p)}  HTTP {r.status_code}: {r.text[:200]}")
            except requests.RequestException as exc:
                print(f"{p['name']:10} FAIL {type(exc).__name__}")
    elif "--models" in args:
        name = args[args.index("--models") + 1]
        needle = args[args.index("--models") + 2].lower() if len(args) > args.index("--models") + 2 else ""
        p = next((x for x in PROVIDERS if x["name"] == name), None)
        if p is None:
            print("provider must be groq or openrouter")
            return
        headers = {"Authorization": f"Bearer {env(p['key_env'])}"} if env(p["key_env"]) else {}
        r = requests.get(p["models_url"], headers=headers, timeout=15)
        ids = sorted(m.get("id", "") for m in r.json().get("data", []))
        for mid in ids:
            if needle in mid.lower():
                print(mid)
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
