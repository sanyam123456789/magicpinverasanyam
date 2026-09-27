"""Generic validation harness for FREE LLM providers/models (evidence only; production code and .env are not changed).

    python tests/validate_free_llm.py --provider openrouter --model google/gemma-4-26b-a4b-it:free --phase smoke
    python tests/validate_free_llm.py --provider openrouter --model qwen/qwen3.8-27b:free --phase sequential --budget 12
    python tests/validate_free_llm.py --provider openrouter --model ... --phase report

Providers that speak the OpenAI chat-completions style are injected into llm.PROVIDERS inside THIS process only. A provider is testable
only when its API key variable is present in .env / the environment (names below); nothing is created or written to .env.

    openrouter  OPENROUTER_API_KEY                               https://openrouter.ai/api/v1/chat/completions
    groq        GROQ_API_KEY                                     https://api.groq.com/openai/v1/chat/completions
    gemini      GEMINI_API_KEY                                   https://generativelanguage.googleapis.com/v1beta/openai/chat/completions
    cloudflare  CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID     https://api.cloudflare.com/client/v4/accounts/<id>/ai/v1/chat/completions
    mistral     MISTRAL_API_KEY                                  https://api.mistral.ai/v1/chat/completions
    cohere      COHERE_API_KEY                                   https://api.cohere.ai/compatibility/v1/chat/completions

Same production prompt (composer.build_messages), request body (llm._post: temperature 0, max_tokens 450, seed 7), validator, audit_lib and
compose_detailed retry/fallback as production. Calls are paced (--min-interval seconds between HTTP calls) to respect RPM limits.
Every HTTP call is logged (status, latency, tokens, upstream provider, raw content). Rate-limit / quota / account errors are classified
separately from model failures.
"""
import os
import sys

# ---- read CLI first: the environment must be prepared before the app modules import config.py
_argv = sys.argv[1:]


def _opt(name, default=None):
    return _argv[_argv.index(name) + 1] if name in _argv else default


PROVIDER = _opt("--provider", "openrouter")
MODEL = _opt("--model")
if not MODEL:
    raise SystemExit("--model is required")
if PROVIDER != "openrouter":
    os.environ["OPENROUTER_API_KEY"] = ""
if PROVIDER != "groq":
    os.environ["GROQ_API_KEY"] = ""  # only the provider under test may be configured
if PROVIDER == "openrouter":
    os.environ["OPENROUTER_MODEL"] = MODEL

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import statistics  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import requests  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import audit_lib  # noqa: E402
import composer  # noqa: E402
import llm  # noqa: E402
import tick as ticker  # noqa: E402
import validator  # noqa: E402
from bakeoff_openrouter_models import pctl  # noqa: E402
from config import env  # noqa: E402
from live_audit_30_pairs import load  # noqa: E402

# ---- advisory grounding heuristics beyond the production validator (same as tests/validate_gpt41mini.py; copied so importing that module
# ---- cannot override this process' model/env)
EVENT_RE = re.compile(r"\b(diwali|navratri|holi|eid|christmas|ganesh chaturthi|ganesh|dussehra|durga puja|pongal|onam|raksha bandhan|rakhi|"
                      r"new year|valentine'?s?|karva chauth|dhanteras|lohri|baisakhi|ipl|world cup|black friday|independence day|"
                      r"republic day|mother'?s day|women'?s day|monsoon|summer|winter|wedding season)\b", re.I)
AVAIL_RE = re.compile(r"\b(slots?|available|availability|timings?|capacity|seats?|walk-?ins?|vacant|open till|morning|afternoon|evening)\b", re.I)
FEATURE_RE = re.compile(r"\b(button|feature|app|dashboard|widget|click|toggle|enable|integration|plugin|chatbot|qr code|calling)\b", re.I)
OFFER_RE = re.compile(r"(\bfree\b|complimentary|\bdiscount\b|\d+\s*%\s*off|\bcombo\b|\bpackage\b|\bbuy\s*\d|\bcashback\b|\bcoupon\b|\bvoucher\b|"
                      r"\bmin(?:imum)?\b|\bdelivery\b)", re.I)
INVENTED_TIME_RE = re.compile(r"\b(in \d+ days|\d+ days (?:away|left|to go)|tomorrow|tonight|today|this week|by \w+day)\b", re.I)


def _present(word, text):
    return re.search(r"\b" + re.escape(word.lower()) + r"\b", text) is not None


def extra_flags(body, ctx):
    own = json.dumps({k: ctx.get(k) for k in ("merchant", "trigger", "customer", "derived_facts")}, ensure_ascii=False).lower()
    cat = json.dumps(ctx.get("category"), ensure_ascii=False).lower()
    flags = {}
    for name, rx in (("event", EVENT_RE), ("availability", AVAIL_RE), ("feature", FEATURE_RE), ("offer_term", OFFER_RE), ("time_claim", INVENTED_TIME_RE)):
        hits = []
        for m in rx.finditer(body):
            w = m.group(0).lower()
            where = "merchant/trigger/customer" if _present(w, own) else ("category only" if _present(w, cat) else "ABSENT from all context")
            if where != "merchant/trigger/customer":
                hits.append(f"{w} [{where}]")
        if hits:
            flags[name] = sorted(set(hits))
    return flags


REGISTRY = {
    "groq": {"url": "https://api.groq.com/openai/v1/chat/completions", "key_env": "GROQ_API_KEY"},
    "gemini": {"url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "key_env": "GEMINI_API_KEY"},
    "cloudflare": {"url": "https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions",
                   "key_env": "CLOUDFLARE_API_TOKEN"},
    "mistral": {"url": "https://api.mistral.ai/v1/chat/completions", "key_env": "MISTRAL_API_KEY"},
    "cohere": {"url": "https://api.cohere.ai/compatibility/v1/chat/completions", "key_env": "COHERE_API_KEY"},
    "cerebras": {"url": "https://api.cerebras.ai/v1/chat/completions", "key_env": "CEREBRAS_API_KEY"},
    "openai": {"url": "https://api.openai.com/v1/chat/completions", "key_env": "OPENAI_API_KEY"},
    "opencode": {"url": "https://opencode.ai/zen/v1/chat/completions", "key_env": "OPENCODE_API_KEY"},
}
if PROVIDER != "openrouter":
    spec = REGISTRY[PROVIDER]
    llm.PROVIDERS = tuple(p for p in llm.PROVIDERS if p["name"] == PROVIDER) + (
        () if any(p["name"] == PROVIDER for p in llm.PROVIDERS) else
        ({"name": PROVIDER, "url": spec["url"].replace("{CLOUDFLARE_ACCOUNT_ID}", env("CLOUDFLARE_ACCOUNT_ID")),
          "models_url": "", "key_env": spec["key_env"], "model_env": PROVIDER.upper() + "_MODEL", "default_model": MODEL},))
    os.environ[PROVIDER.upper() + "_MODEL"] = MODEL

TAG = _opt("--tag") or re.sub(r"[^A-Za-z0-9._-]+", "_", f"{PROVIDER}__{MODEL}")
OUT = ROOT / "out" / "free_llm" / TAG

CATS, MERS, CUSS, TRGS = (load("categories/*.json", "slug"), load("merchants/*.json", "merchant_id"),
                          load("customers/*.json", "customer_id"), load("triggers/*.json", "id"))
PAIRS = json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]
TRIG2PAIR = {p["trigger_id"]: p["test_id"] for p in PAIRS}
STATIC = {}
for _p in PAIRS:
    _m = MERS[_p["merchant_id"]]
    _cat = CATS[_m["category_slug"]]
    _t = TRGS[_p["trigger_id"]]
    _c = CUSS.get(_p["customer_id"]) if _p["customer_id"] else None
    STATIC[_p["test_id"]] = {"ctx": composer.build_context(_cat, _m, _t, _c), "category": _cat, "merchant": _m, "trigger": _t, "customer": _c,
                             "prior": [t.get("body") for t in _m.get("conversation_history") or [] if t.get("from") == "vera"]}

# ------------------------------------------------------------------ instrumentation (this process only)
CALLS, LOCK = [], threading.Lock()
STATE = {"phase": "", "t0": time.perf_counter(), "last_call": 0.0, "min_interval": float(_opt("--min-interval", "3.1"))}
TRIGGER_LINE = re.compile(r"^TRIGGER: (\{.*\})$", re.M)
QUOTA_HINTS = ("rate limit", "rate-limit", "quota", "free-models-per-day", "too many requests", "resource_exhausted", "daily")


def pair_of(messages):
    try:
        return TRIG2PAIR.get(json.loads(TRIGGER_LINE.search(messages[1]["content"]).group(1)).get("id"))
    except Exception:  # noqa: BLE001
        return None


def classify(http, error):
    if http == 200:
        return "ok"
    text = (error or "").lower()
    if http == 429 or any(h in text for h in QUOTA_HINTS):
        return "RATE_LIMIT_OR_QUOTA"
    if http in (401, 402, 403):
        return "ACCOUNT/CREDIT/AUTH"
    if http == 404:
        return "MODEL_OR_ENDPOINT_NOT_FOUND"
    if http and http >= 500:
        return "PROVIDER_ERROR"
    if http is None:
        return "TRANSPORT/TIMEOUT"
    return f"HTTP_{http}"


EXTRA = {}
if _opt("--reasoning-effort"):
    EXTRA["reasoning_effort"] = _opt("--reasoning-effort")
_mt = _opt("--max-tokens")
NO_MAX_TOKENS = _mt == "0"  # --max-tokens 0 means: omit the field entirely, let the model use its own ceiling
MAX_TOKENS_OVERRIDE = int(_mt) if (_mt and not NO_MAX_TOKENS) else None


def _post_with_extras(provider, messages, max_tokens, timeout):
    """Identical to production llm._post (temperature 0, seed 7, same headers/timeouts) plus the optional test-only extras."""
    headers = {"Authorization": f"Bearer {env(provider['key_env'])}", "Content-Type": "application/json"}
    body = {"model": llm.model_for(provider), "messages": messages, "temperature": 0, "seed": 7}
    if not NO_MAX_TOKENS:
        body["max_tokens"] = MAX_TOKENS_OVERRIDE or max_tokens
    body.update(EXTRA)
    return requests.post(provider["url"], headers=headers, json=body, timeout=(min(3.05, timeout), timeout))


_orig_post = _post_with_extras if (EXTRA or MAX_TOKENS_OVERRIDE or NO_MAX_TOKENS) else llm._post


def wrapped_post(provider, messages, max_tokens, timeout):
    wait = STATE["min_interval"] - (time.monotonic() - STATE["last_call"])
    if wait > 0:
        time.sleep(wait)  # RPM pacing, kept outside the measured latency
    STATE["last_call"] = time.monotonic()
    rec = {"phase": STATE["phase"], "pair": pair_of(messages), "provider": provider["name"], "model": llm.model_for(provider),
           "timeout_param": round(timeout, 2), "http": None, "error": None, "upstream": None, "prompt_tokens": None,
           "completion_tokens": None, "reasoning_tokens": None, "finish": None, "content": "", "parsable": None}
    started = time.perf_counter()
    try:
        resp = _orig_post(provider, messages, max_tokens, timeout)
    except Exception as exc:  # noqa: BLE001
        rec.update(error=type(exc).__name__, latency=round(time.perf_counter() - started, 2))
        rec["class"] = classify(None, rec["error"])
        with LOCK:
            CALLS.append(rec)
        raise
    rec["latency"] = round(time.perf_counter() - started, 2)
    rec["http"] = resp.status_code
    try:
        if resp.status_code == 200:
            j = resp.json()
            choice = (j.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            rec["content"] = (message.get("content") or "")[:1500]
            rec["finish"] = choice.get("finish_reason")
            usage = j.get("usage") or {}
            rec["prompt_tokens"], rec["completion_tokens"] = usage.get("prompt_tokens"), usage.get("completion_tokens")
            rec["reasoning_tokens"] = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            rec["upstream"] = j.get("provider")
            rec["parsable"] = llm.extract_json(rec["content"]) is not None
            if not rec["content"].strip():
                rec["error"] = "empty content" + (" (has reasoning field)" if message.get("reasoning") else "")
            if j.get("error"):
                rec["error"] = str(j["error"])[:200]
        else:
            rec["error"] = resp.text[:220]
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"parse:{type(exc).__name__}"
    rec["class"] = classify(rec["http"], rec["error"]) if rec["http"] != 200 else ("ok" if rec["parsable"] else "MALFORMED_OR_EMPTY")
    with LOCK:
        CALLS.append(rec)
    return resp


llm._post = wrapped_post


def quota_snapshot():
    """OpenRouter only: numbers from GET /key (never the key itself)."""
    if PROVIDER != "openrouter":
        return None
    try:
        d = requests.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {env('OPENROUTER_API_KEY')}"}, timeout=15).json()["data"]
        return {"free_model_daily_requests": d.get("free_model_daily_requests"), "usage": d.get("usage"), "is_free_tier": d.get("is_free_tier")}
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ evaluation
def draft_eval(pid, content):
    st = STATIC[pid]
    obj = llm.extract_json(content) if content else None
    if not isinstance(obj, dict) or not isinstance(obj.get("body"), str) or not obj["body"].strip():
        return {"body": None, "hard": ["malformed_or_empty_json"], "soft": []}
    msg = composer.finalize(obj, st["ctx"], st["merchant"], st["trigger"], st["customer"])
    verdict = validator.validate(msg["body"], msg["cta"], st["ctx"], st["category"], st["prior"])
    return {"body": msg["body"], "cta": msg["cta"], "hard": verdict.hard, "soft": verdict.soft,
            "extra": extra_flags(msg["body"], st["ctx"]), "hindi_markers": validator.hindi_marker_count(msg["body"]),
            "audit": {k: v for k, v in audit_lib.audit_message(msg["body"], msg["cta"], st["ctx"], st["category"]).items()
                      if k in ("url", "taboo", "ungrounded_numbers", "offer_flags", "urgency_flags", "ask_flags") and v}}


def evaluate(pid, msg, meta, seconds, calls):
    st = STATIC[pid]
    body = msg["body"]
    verdict = validator.validate(body, msg["cta"], st["ctx"], st["category"], st["prior"])
    audit = audit_lib.audit_message(body, msg["cta"], st["ctx"], st["category"])
    attempts = []
    for i, c in enumerate(calls, 1):
        d = {k: c.get(k) for k in ("http", "class", "latency", "prompt_tokens", "completion_tokens", "reasoning_tokens", "finish", "parsable", "error", "upstream")}
        d["attempt"] = i
        if c["http"] == 200 and c["content"]:
            d["draft"] = draft_eval(pid, c["content"])
        attempts.append(d)
    cause = None
    if meta["source"] == "fallback":
        classes = {c.get("class") for c in calls}
        if classes & {"RATE_LIMIT_OR_QUOTA"}:
            cause = "RATE_LIMIT_OR_QUOTA"
        elif classes & {"ACCOUNT/CREDIT/AUTH"}:
            cause = "ACCOUNT/CREDIT/AUTH"
        elif classes & {"TRANSPORT/TIMEOUT", "PROVIDER_ERROR", "MODEL_OR_ENDPOINT_NOT_FOUND"}:
            cause = "PROVIDER/MODEL: " + ",".join(sorted(classes - {"ok"}))
        elif not calls:
            cause = "no call made"
        else:
            cause = "APPLICATION: validator rejected every draft / malformed"
    return {"pair": pid, "kind": st["trigger"]["kind"], "merchant": st["merchant"]["identity"]["name"], "mode": st["ctx"]["language_mode"],
            "placeholder": bool((st["trigger"].get("payload") or {}).get("placeholder")), "source": meta["source"], "attempts": meta["attempts"],
            "issues": meta["issues"], "seconds": round(seconds, 2), "body": body, "cta": msg["cta"], "final_hard": verdict.hard, "final_soft": verdict.soft,
            "audit": {k: audit[k] for k in ("url", "taboo", "ungrounded_numbers", "offer_flags", "urgency_flags", "ask_flags")},
            "similarity_rejected": audit["similarity"]["would_be_rejected"], "extra": extra_flags(body, st["ctx"]),
            "hindi_markers": validator.hindi_marker_count(body), "question_marks": body.count("?"), "calls": attempts, "fallback_cause": cause}


def calls_for(phase, pid):
    with LOCK:
        return [c for c in CALLS if c["phase"] == phase and c["pair"] == pid]


def stat(values):
    return {"n": len(values), "avg": round(statistics.mean(values), 2) if values else None, "p50": round(statistics.median(values), 2) if values else None,
            "p95": pctl(values, 0.95), "max": max(values) if values else None, "gt6": sum(v > 6 for v in values), "gt8": sum(v > 8 for v in values),
            "gt10": sum(v > 10 for v in values)}


def run_metrics(rows):
    calls = [c for r in rows for c in r["calls"]]
    ok = [c for c in calls if c["http"] == 200]
    classes = {}
    for c in calls:
        classes[c["class"]] = classes.get(c["class"], 0) + 1
    first = [c["draft"] for r in rows for c in r["calls"][:1] if c.get("draft")]
    llm_rows = [r for r in rows if r["source"].startswith("llm")]
    return {"pairs": len(rows), "http_calls": len(calls), "http_200": len(ok), "call_classes": classes,
            "latency_http200": stat([c["latency"] for c in ok]), "per_pair_compose_s": stat([r["seconds"] for r in rows]),
            "prompt_tokens": sum(c["prompt_tokens"] or 0 for c in ok), "completion_tokens": sum(c["completion_tokens"] or 0 for c in ok),
            "reasoning_tokens": sum(c["reasoning_tokens"] or 0 for c in ok), "finish_length": sum(1 for c in ok if c["finish"] == "length"),
            "empty_or_malformed_200": sum(1 for c in ok if not c["parsable"]), "retried_pairs": sum(1 for r in rows if len(r["calls"]) > 1),
            "first_draft_total": len(first), "first_draft_hard_reject": sum(1 for d in first if d["hard"]),
            "first_draft_soft_reject": sum(1 for d in first if d["soft"]), "from_llm": len(llm_rows),
            "fallback_total": sum(1 for r in rows if r["source"] == "fallback"),
            "fallback_by_cause": {k: sum(1 for r in rows if r["fallback_cause"] == k) for k in {r["fallback_cause"] for r in rows if r["fallback_cause"]}},
            "final_hard": sum(1 for r in llm_rows if r["final_hard"]), "final_soft_language": sum(1 for r in llm_rows if r["final_soft"]),
            "url": sum(1 for r in llm_rows if r["audit"]["url"]), "taboo": sum(1 for r in llm_rows if r["audit"]["taboo"]),
            "ungrounded_numbers": sum(1 for r in llm_rows if r["audit"]["ungrounded_numbers"]),
            "similarity_rejected": sum(1 for r in llm_rows if r["similarity_rejected"]), "two_plus_questions": sum(1 for r in llm_rows if r["question_marks"] >= 2)}


def save(name, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


# ------------------------------------------------------------------ phases
def phase_smoke(pids):
    STATE["phase"] = "smoke"
    q0 = quota_snapshot()
    out = []
    for pid in pids:
        st = STATE
        t0 = time.perf_counter()
        try:
            text, _prov = llm.chat(composer.build_messages(STATIC[pid]["ctx"], None), max_tokens=450, timeout=30.0)
            err = None
        except Exception as exc:  # noqa: BLE001
            text, err = "", f"{type(exc).__name__}: {exc}"[:240]
        calls = calls_for("smoke", pid)
        rec = {"pair": pid, "wall_s": round(time.perf_counter() - t0, 2), "error": err, "call": calls[-1] if calls else None}
        rec["draft"] = draft_eval(pid, text) if text else None
        out.append(rec)
        c = rec["call"] or {}
        print(f"SMOKE {PROVIDER} {MODEL} {pid}: class={c.get('class')} http={c.get('http')} latency={c.get('latency')} tokens={c.get('prompt_tokens')}/{c.get('completion_tokens')} "
              f"reasoning={c.get('reasoning_tokens')} parsable={c.get('parsable')} err={(c.get('error') or err or '')[:140]}", flush=True)
        if rec["draft"]:
            print("   body:", rec["draft"]["body"], "| hard:", rec["draft"]["hard"], "| soft:", [s[:30] for s in rec["draft"]["soft"]], "| extra:", rec["draft"].get("extra"), flush=True)
    save("smoke.json", {"provider": PROVIDER, "model": MODEL, "quota_before": q0, "quota_after": quota_snapshot(), "results": out})


def _raw_call_one(pid, budget):
    """Bypass composer.compose_detailed's hardcoded 6s-per-attempt cap: call the model directly with the full
    per-test --budget as the request timeout. Used for --raw mode, where the point is to see the model's own
    behaviour (grounding, Hinglish, JSON) at whatever latency it actually needs, not production's timeout policy."""
    st = STATIC[pid]
    t0 = time.perf_counter()
    try:
        obj, provider = llm.chat_json(composer.build_messages(st["ctx"], None), max_tokens=450, timeout=budget)
        msg = composer.finalize(obj, st["ctx"], st["merchant"], st["trigger"], st["customer"])
        meta = {"source": f"llm:{provider}", "attempts": 1, "issues": []}
    except Exception as exc:  # noqa: BLE001
        msg = composer.finalize(composer.fallback.build(st["category"], st["merchant"], st["trigger"], st["customer"], st["ctx"],
                                                         composer.addressee(st["category"], st["merchant"], st["customer"])),
                                st["ctx"], st["merchant"], st["trigger"], st["customer"])
        meta = {"source": "fallback", "attempts": 1, "issues": [f"raw_mode: {type(exc).__name__}: {exc}"[:200]]}
    return evaluate(pid, msg, meta, time.perf_counter() - t0, calls_for("sequential", pid))


def phase_sequential(budget, raw=False):
    STATE["phase"] = "sequential"
    q0 = quota_snapshot()
    composer.clear_cache()
    llm._cooldown_until.clear()
    rows, started = [], time.time()
    only = {x.strip() for x in (_opt("--only") or "").split(",") if x.strip()}
    for p in PAIRS:
        pid = p["test_id"]
        if only and pid not in only:
            continue
        if raw:
            rows.append(_raw_call_one(pid, budget))
        else:
            st = STATIC[pid]
            t0 = time.perf_counter()
            d = composer.compose_detailed(st["category"], st["merchant"], st["trigger"], st["customer"], timeout=budget)
            rows.append(evaluate(pid, d["message"], d["meta"], time.perf_counter() - t0, calls_for("sequential", pid)))
        r = rows[-1]
        print(f"{pid} {r['source']:16} {r['seconds']:>6}s calls={[(c['http'], c['latency'], c['class']) for c in r['calls']]}", flush=True)
        if sum(1 for c in CALLS if c.get("class") == "RATE_LIMIT_OR_QUOTA") >= 3:
            print("STOP: 3 rate-limit/quota responses; not burning more quota", flush=True)
            break
    save("sequential.json", {"provider": PROVIDER, "model": MODEL, "budget_s": budget, "wall_s": round(time.time() - started, 1),
                             "quota_before": q0, "quota_after": quota_snapshot(), "rows": rows})
    print("sequential done", flush=True)


def phase_report():
    d = json.load(open(OUT / "sequential.json", encoding="utf-8"))
    m = run_metrics(d["rows"])
    save("summary.json", {"provider": PROVIDER, "model": MODEL, "quota_before": d["quota_before"], "quota_after": d["quota_after"], "metrics": m})
    L = [f"# {PROVIDER} / {MODEL}: 30-pair validation (budget {d['budget_s']} s)", "", "```json", json.dumps(m, indent=1, ensure_ascii=False), "```",
         f"quota before: {d['quota_before']}  after: {d['quota_after']}", ""]
    for r in d["rows"]:
        L.append(f"### {r['pair']} {r['kind']} | {r['merchant']} | mode {r['mode']} | placeholder={r['placeholder']} | {r['source']} | {r['seconds']} s | attempts {r['attempts']}")
        L += ["", "> " + r["body"].replace("\n", "\n> "), ""]
        fl = {"hard": r["final_hard"], "soft": [s[:40] for s in r["final_soft"]], "audit": {k: v for k, v in r["audit"].items() if v}, "extra": r["extra"],
              "hindi_markers": r["hindi_markers"], "fallback_cause": r["fallback_cause"]}
        L.append("flags: " + json.dumps({k: v for k, v in fl.items() if v not in (None, [], {}, 0)}, ensure_ascii=False))
        L.append("calls: " + json.dumps([{k: c.get(k) for k in ("http", "class", "latency", "prompt_tokens", "completion_tokens", "reasoning_tokens", "error")} for c in r["calls"]], ensure_ascii=False))
        for i, c in enumerate(r["calls"], 1):
            dr = c.get("draft")
            if dr and (len(r["calls"]) > 1 or dr["body"] != r["body"]):
                L.append(f"draft {i}: hard={dr['hard']} soft={[s[:30] for s in dr['soft']]} body={dr['body']!r}")
        L.append("")
    (OUT / "report.md").write_text("\n".join(L), encoding="utf-8")
    print(json.dumps(m, indent=1, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", default="openrouter")
    ap.add_argument("--model", required=True)
    ap.add_argument("--tag")
    ap.add_argument("--phase", required=True, choices=["smoke", "sequential", "report"])
    ap.add_argument("--pairs", default="T29")
    ap.add_argument("--budget", type=float, default=6.0)
    ap.add_argument("--min-interval", default="3.1")
    ap.add_argument("--only", help="sequential phase: comma-separated pair ids to run (others skipped)")
    ap.add_argument("--raw", action="store_true", help="sequential phase: bypass composer's hardcoded 6s-per-attempt cap, call the model directly with --budget as the timeout")
    ap.add_argument("--reasoning-effort", help="test-only: adds reasoning_effort to the request body (e.g. low)")
    ap.add_argument("--max-tokens", help="test-only: overrides max_tokens (production uses 450)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print("LLM setup for this process:", llm.label(), flush=True)
    if not llm.configured_providers():
        print(f"NOT TESTABLE: no key configured for provider '{PROVIDER}' (needs {REGISTRY.get(PROVIDER, {}).get('key_env', 'OPENROUTER_API_KEY')} in .env)")
        return 2
    if args.phase == "smoke":
        phase_smoke([p.strip() for p in args.pairs.split(",")])
    elif args.phase == "sequential":
        phase_sequential(args.budget, raw=args.raw)
    else:
        phase_report()
    with open(OUT / f"calls_{args.phase}.jsonl", "w", encoding="utf-8") as f:
        for c in CALLS:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
