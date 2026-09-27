"""Full validation of openai/gpt-4.1-mini on the 30 canonical pairs. EVIDENCE ONLY: production code and .env are not changed.

    python tests/validate_gpt41mini.py --phase existing     # runs the EXISTING tests/live_compose_30_pairs.py unmodified (4 workers, 8 s budget)
    python tests/validate_gpt41mini.py --phase sequential   # same compose path, one pair at a time, production tick budget (6 s)
    python tests/validate_gpt41mini.py --phase providers    # controlled tests A / B / C plus a total-deadline experiment on a local mock server
    python tests/validate_gpt41mini.py --phase report       # metrics, facts digest and per-message report (offline, no API calls)

How the model is selected: process-level environment overrides set BEFORE the app modules are imported (OPENROUTER_MODEL=openai/gpt-4.1-mini,
GROQ_API_KEY blank). Real environment variables win over .env (config.py), so nothing on disk changes.

Instrumentation: llm._post is wrapped IN THIS PROCESS ONLY to log every HTTP call (status, latency, tokens, upstream provider, raw content).
The composer, validator, fallback and llm.chat() logic that runs is exactly the production code.
"""
import os

MODEL = "openai/gpt-4.1-mini"
os.environ["OPENROUTER_MODEL"] = MODEL
os.environ["GROQ_API_KEY"] = ""

import argparse  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import runpy  # noqa: E402
import statistics  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
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
from bakeoff_openrouter_models import account_status, pctl  # noqa: E402
from config import env  # noqa: E402
from live_audit_30_pairs import load  # noqa: E402

OUT = ROOT / "out" / "gpt41mini"
CATALOG_URL = "https://openrouter.ai/api/v1/models"

# ------------------------------------------------------------------ static data (same contexts for every phase)
CATS, MERS, CUSS, TRGS = (load("categories/*.json", "slug"), load("merchants/*.json", "merchant_id"),
                          load("customers/*.json", "customer_id"), load("triggers/*.json", "id"))
PAIRS = json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]
TRIG2PAIR = {p["trigger_id"]: p["test_id"] for p in PAIRS}
assert len(TRIG2PAIR) == len(PAIRS), "trigger ids must be unique per pair for call attribution"
STATIC = {}
for _p in PAIRS:
    _m = MERS[_p["merchant_id"]]
    _cat = CATS[_m["category_slug"]]
    _t = TRGS[_p["trigger_id"]]
    _c = CUSS.get(_p["customer_id"]) if _p["customer_id"] else None
    _ctx = composer.build_context(_cat, _m, _t, _c)
    _prior = [t.get("body") for t in _m.get("conversation_history") or [] if t.get("from") == "vera"]
    STATIC[_p["test_id"]] = {"ctx": _ctx, "category": _cat, "merchant": _m, "trigger": _t, "customer": _c, "prior": _prior}

# ------------------------------------------------------------------ HTTP call instrumentation (this process only)
CALLS, LOCK = [], threading.Lock()
STATE = {"phase": "", "t0": time.perf_counter()}
TRIGGER_LINE = re.compile(r"^TRIGGER: (\{.*\})$", re.M)


def pair_of(messages):
    try:
        found = TRIGGER_LINE.search(messages[1]["content"])
        return TRIG2PAIR.get(json.loads(found.group(1)).get("id"))
    except Exception:  # noqa: BLE001
        return None


_orig_post = llm._post


def wrapped_post(provider, messages, max_tokens, timeout):
    rec = {"phase": STATE["phase"], "pair": pair_of(messages), "provider": provider["name"], "model": llm.model_for(provider),
           "local_mock": "127.0.0.1" in provider["url"], "timeout_param": round(timeout, 2),
           "t_start": round(time.perf_counter() - STATE["t0"], 2), "http": None, "error": None, "upstream": None,
           "prompt_tokens": None, "completion_tokens": None, "finish": None, "content": "", "parsable": None}
    started = time.perf_counter()
    try:
        resp = _orig_post(provider, messages, max_tokens, timeout)
    except Exception as exc:  # noqa: BLE001  recorded, then re-raised so production code behaves exactly as usual
        rec["error"] = type(exc).__name__
        rec["latency"] = round(time.perf_counter() - started, 2)
        with LOCK:
            CALLS.append(rec)
        raise
    rec["latency"] = round(time.perf_counter() - started, 2)
    rec["http"] = resp.status_code
    try:
        if resp.status_code == 200:
            j = resp.json()
            choice = (j.get("choices") or [{}])[0]
            rec["content"] = ((choice.get("message") or {}).get("content") or "")[:1500]
            rec["finish"] = choice.get("finish_reason")
            usage = j.get("usage") or {}
            rec["prompt_tokens"], rec["completion_tokens"] = usage.get("prompt_tokens"), usage.get("completion_tokens")
            rec["upstream"] = j.get("provider")
            rec["parsable"] = llm.extract_json(rec["content"]) is not None
        else:
            rec["error"] = resp.text[:200]
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"parse:{type(exc).__name__}"
    with LOCK:
        CALLS.append(rec)
    return resp


llm._post = wrapped_post

# ------------------------------------------------------------------ extra (advisory) grounding heuristics beyond the production validator
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
    for name, rx in (("event", EVENT_RE), ("availability", AVAIL_RE), ("feature", FEATURE_RE), ("offer_term", OFFER_RE),
                     ("time_claim", INVENTED_TIME_RE)):
        hits = []
        for m in rx.finditer(body):
            w = m.group(0).lower()
            where = "merchant/trigger/customer" if _present(w, own) else ("category only" if _present(w, cat) else "ABSENT from all context")
            if where != "merchant/trigger/customer":
                hits.append(f"{w} [{where}]")
        if hits:
            flags[name] = sorted(set(hits))
    return flags


# ------------------------------------------------------------------ per-pair evaluation
def draft_eval(pid, content):
    """Validator verdict on one raw model draft (what the model produced, before retry/fallback)."""
    st = STATIC[pid]
    obj = llm.extract_json(content) if content else None
    if not isinstance(obj, dict) or not isinstance(obj.get("body"), str) or not obj["body"].strip():
        return {"body": None, "hard": ["malformed_or_empty_json"], "soft": []}
    msg = composer.finalize(obj, st["ctx"], st["merchant"], st["trigger"], st["customer"])
    verdict = validator.validate(msg["body"], msg["cta"], st["ctx"], st["category"], st["prior"])
    return {"body": msg["body"], "hard": verdict.hard, "soft": verdict.soft}


def evaluate(run, pid, msg, meta, seconds, calls):
    st = STATIC[pid]
    ctx, category = st["ctx"], st["category"]
    body = msg["body"]
    verdict = validator.validate(body, msg["cta"], ctx, category, st["prior"])
    audit = audit_lib.audit_message(body, msg["cta"], ctx, category)
    drafts = []
    for i, c in enumerate(calls):
        d = {k: c.get(k) for k in ("http", "latency", "prompt_tokens", "completion_tokens", "finish", "parsable", "upstream", "error",
                                    "t_start", "timeout_param")}
        d["attempt"] = i + 1
        if c["http"] == 200:
            d["draft"] = draft_eval(pid, c["content"])
        drafts.append(d)
    source = meta["source"]
    had_402 = any(c["http"] == 402 for c in calls)
    cause = None
    if source == "fallback":
        if had_402:
            cause = "ACCOUNT/CREDIT FAILURE (HTTP 402)"
        elif any("llm_unavailable" in i for i in meta["issues"]):
            cause = "LLM unavailable / timeout: " + "; ".join(i for i in meta["issues"] if "llm_unavailable" in i)[:160]
        elif not calls:
            cause = "no LLM call made (budget exhausted before the call)"
        else:
            cause = "validator hard failure on every attempt"
    return {
        "run": run, "pair": pid, "kind": st["trigger"]["kind"], "merchant": st["merchant"]["identity"]["name"], "send_as": msg["send_as"],
        "mode": ctx["language_mode"], "placeholder": bool((st["trigger"].get("payload") or {}).get("placeholder")),
        "source": source, "attempts": meta["attempts"], "issues": meta["issues"], "seconds": round(seconds, 2),
        "body": body, "cta": msg["cta"], "rationale": msg["rationale"], "final_hard": verdict.hard, "final_soft": verdict.soft,
        "audit": {k: audit[k] for k in ("url", "taboo", "ungrounded_numbers", "possible_invented_names", "offer_flags", "urgency_flags",
                                        "generic_flags", "fact_dump", "ask_flags", "tone_flags", "words")},
        "similarity": {k: audit["similarity"][k] for k in ("ratio", "containment", "would_be_rejected")},
        "extra": extra_flags(body, ctx), "hindi_markers": validator.hindi_marker_count(body),
        "question_marks": body.count("?"), "calls": drafts, "account_failure": had_402, "fallback_cause": cause,
    }


def calls_for(phase, pid):
    with LOCK:
        return [c for c in CALLS if c["phase"] == phase and c["pair"] == pid]


def save(name, payload):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str), encoding="utf-8")


def pricing_for_model():
    entry = {m["id"]: m for m in requests.get(CATALOG_URL, timeout=30).json()["data"]}.get(MODEL)
    return {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": CATALOG_URL,
            "pricing": (entry or {}).get("pricing"), "in_catalog": bool(entry)}


# ------------------------------------------------------------------ phases
def phase_existing():
    STATE["phase"] = "existing"
    acct0 = account_status(env("OPENROUTER_API_KEY"))
    composer.clear_cache()
    sys.argv = ["live_compose_30_pairs.py"]
    buf = io.StringIO()
    started = time.time()
    with contextlib.redirect_stdout(buf):
        runpy.run_path(str(ROOT / "tests" / "live_compose_30_pairs.py"), run_name="__main__")
    wall = time.time() - started
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "existing_stdout.txt").write_text(buf.getvalue(), encoding="utf-8")
    raw = {json.loads(line)["test_id"]: json.loads(line) for line in open(ROOT / "out" / "compose_30_pairs.jsonl", encoding="utf-8")}
    rows = []
    for p in PAIRS:
        r = raw[p["test_id"]]
        msg = {"body": r["body"], "cta": r["cta"], "send_as": r["send_as"], "rationale": r["rationale"]}
        rows.append(evaluate("existing", p["test_id"], msg, {"source": r["source"], "attempts": len(calls_for("existing", p["test_id"])),
                                                              "issues": r["issues"]}, r["seconds"], calls_for("existing", p["test_id"])))
    save("existing.json", {"model": MODEL, "wall_s": round(wall, 1), "workers": 4, "budget_s": 8.0, "account_before": acct0,
                           "account_after": account_status(env("OPENROUTER_API_KEY")), "rows": rows})
    print(f"existing phase done: {len(rows)} pairs, wall {wall:.1f}s, http calls {len([c for c in CALLS if c['phase'] == 'existing'])}")


def phase_sequential():
    STATE["phase"] = "sequential"
    acct0 = account_status(env("OPENROUTER_API_KEY"))
    composer.clear_cache()
    llm._cooldown_until.clear()
    rows = []
    started = time.time()
    for p in PAIRS:
        pid = p["test_id"]
        st = STATIC[pid]
        t0 = time.perf_counter()
        d = composer.compose_detailed(st["category"], st["merchant"], st["trigger"], st["customer"], timeout=ticker.COMPOSE_TIMEOUT_SECONDS)
        secs = time.perf_counter() - t0
        rows.append(evaluate("sequential", pid, d["message"], d["meta"], secs, calls_for("sequential", pid)))
        print(f"{pid} {rows[-1]['source']:15} {rows[-1]['seconds']:>6}s calls={[(c['http'], c['latency']) for c in rows[-1]['calls']]}", flush=True)
    save("sequential.json", {"model": MODEL, "wall_s": round(time.time() - started, 1), "budget_s": ticker.COMPOSE_TIMEOUT_SECONDS,
                             "account_before": acct0, "account_after": account_status(env("OPENROUTER_API_KEY")),
                             "pricing": pricing_for_model(), "rows": rows})
    print("sequential phase done")


class MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    mode = "ok"
    trickle_seconds = 20

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        if self.mode == "500":
            body = b'{"error":"mock upstream failure"}'
            self.send_response(500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.mode == "hang":
            time.sleep(60)
        elif self.mode == "trickle":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(self.trickle_seconds):  # one byte per second: never idle long enough to trip a read timeout
                self.wfile.write(b"1\r\n \r\n")
                self.wfile.flush()
                time.sleep(1.0)
            payload = json.dumps({"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}).encode()
            self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n")
            self.wfile.flush()

    def log_message(self, *args):  # noqa: D401
        pass


def run_provider_case(label, pids, phase_name):
    rows = []
    for pid in pids:
        st = STATIC[pid]
        composer.clear_cache()
        llm._cooldown_until.clear()
        llm.last_errors.clear()
        STATE["phase"] = phase_name
        t0 = time.perf_counter()
        d = composer.compose_detailed(st["category"], st["merchant"], st["trigger"], st["customer"], timeout=ticker.COMPOSE_TIMEOUT_SECONDS)
        secs = time.perf_counter() - t0
        row = evaluate(label, pid, d["message"], d["meta"], secs, calls_for(phase_name, pid))
        rows.append(row)
        print(f"{label:34} {pid} source={row['source']:15} {row['seconds']:>6}s calls={[(c['http'], c['error'], c['latency']) for c in row['calls']]}", flush=True)
    return rows


def phase_providers():
    real_key = env("OPENROUTER_API_KEY")
    provider = next(p for p in llm.PROVIDERS if p["name"] == "openrouter")
    real_url = provider["url"]
    results = {"model": MODEL, "cases": {}}
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    local_url = f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"
    try:
        # Test A: real OpenRouter + gpt-4.1-mini available -> the model must serve
        results["cases"]["A_gpt_serves"] = run_provider_case("A: OpenRouter GPT-4.1 Mini available", ["T07", "T13", "T30"], "test_A")
        # Test B1: real OpenRouter rejects the credentials (HTTP 4xx) -> local deterministic fallback (no second LLM provider is configured)
        os.environ["OPENROUTER_API_KEY"] = "invalid-key-for-failover-drill"
        results["cases"]["B1_openrouter_rejects_key"] = run_provider_case("B1: OpenRouter 401 (invalid key)", ["T07", "T13", "T30"], "test_B1")
        # B2 to B4 use a local mock server, so the real key is never sent anywhere else
        os.environ["OPENROUTER_API_KEY"] = "local-mock-key"
        provider["url"] = local_url
        MockHandler.mode = "500"
        results["cases"]["B2_upstream_http_500"] = run_provider_case("B2: upstream HTTP 500", ["T07", "T13"], "test_B2")
        MockHandler.mode = "hang"
        results["cases"]["B3_upstream_hangs"] = run_provider_case("B3: upstream never answers", ["T07"], "test_B3")
        # B4: bytes trickle in every second. Is the 6 s budget a TRUE total deadline?
        MockHandler.mode = "trickle"
        MockHandler.trickle_seconds = 20
        STATE["phase"] = "test_B4_direct"
        started = time.perf_counter()
        try:
            llm._post(provider, [{"role": "system", "content": "s"}, {"role": "user", "content": "TRIGGER: {}"}], 450, 3.0)
            outcome = "returned"
        except Exception as exc:  # noqa: BLE001
            outcome = type(exc).__name__
        results["B4_direct_post_timeout_3s_vs_trickle_20s"] = {"timeout_param_s": 3.0, "elapsed_s": round(time.perf_counter() - started, 2), "outcome": outcome}
        print("B4 direct _post(timeout=3.0) against a 20 s trickle ->", results["B4_direct_post_timeout_3s_vs_trickle_20s"], flush=True)
        results["cases"]["B4_trickle_compose"] = run_provider_case("B4: trickling upstream (compose, 6 s budget)", ["T07"], "test_B4")
    finally:
        provider["url"] = real_url
        os.environ["OPENROUTER_API_KEY"] = real_key
        server.shutdown()
    # Test C: no LLM provider usable at all -> deterministic local fallback must be immediate
    os.environ["OPENROUTER_API_KEY"] = ""
    try:
        results["cases"]["C_no_provider"] = run_provider_case("C: no LLM provider configured", ["T07", "T13", "T30"], "test_C")
    finally:
        os.environ["OPENROUTER_API_KEY"] = real_key
    save("providers.json", results)
    print("providers phase done")


# ------------------------------------------------------------------ report
def lat_stats(values):
    return {"n": len(values), "avg": round(statistics.mean(values), 2) if values else None,
            "p50": round(statistics.median(values), 2) if values else None, "p95": pctl(values, 0.95), "max": max(values) if values else None,
            "gt6": sum(1 for v in values if v > 6), "gt8": sum(1 for v in values if v > 8), "gt10": sum(1 for v in values if v > 10)}


def run_metrics(rows, price):
    calls = [c for r in rows for c in r["calls"]]
    ok = [c for c in calls if c["http"] == 200]
    errs = {}
    for c in calls:
        if c["http"] != 200:
            key = str(c["http"]) if c["http"] is not None else (c["error"] or "unknown")
            errs[key] = errs.get(key, 0) + 1
    pt = sum(c["prompt_tokens"] or 0 for c in ok)
    ct = sum(c["completion_tokens"] or 0 for c in ok)
    cost = None
    if price:
        cost = pt * float(price["prompt"]) + ct * float(price["completion"])
    first_drafts = [c.get("draft") for r in rows for c in r["calls"][:1] if c.get("draft")]
    return {
        "pairs": len(rows), "http_calls": len(calls), "http_200": len(ok), "error_codes": errs,
        "http_402": errs.get("402", 0), "http_429": errs.get("429", 0),
        "timeouts": sum(v for k, v in errs.items() if "Timeout" in k),
        "malformed_200": sum(1 for c in ok if not c["parsable"]), "finish_length": sum(1 for c in ok if c["finish"] == "length"),
        "latency_http200": lat_stats([c["latency"] for c in ok]), "latency_per_pair_compose": lat_stats([r["seconds"] for r in rows]),
        "retried_pairs": sum(1 for r in rows if len(r["calls"]) > 1),
        "first_draft_hard_fail": sum(1 for d in first_drafts if d["hard"]), "first_draft_soft_fail": sum(1 for d in first_drafts if d["soft"]),
        "first_draft_total": len(first_drafts),
        "final_hard_fail": sum(1 for r in rows if r["final_hard"] and r["source"].startswith("llm")),
        "final_soft_fail": sum(1 for r in rows if r["final_soft"] and r["source"].startswith("llm")),
        "fallback_total": sum(1 for r in rows if r["source"] == "fallback"),
        "fallback_account_402": sum(1 for r in rows if r["fallback_cause"] and r["fallback_cause"].startswith("ACCOUNT")),
        "from_llm": sum(1 for r in rows if r["source"].startswith("llm")),
        "url": sum(1 for r in rows if r["audit"]["url"]), "taboo": sum(1 for r in rows if r["audit"]["taboo"]),
        "ungrounded_numbers": sum(1 for r in rows if r["audit"]["ungrounded_numbers"]),
        "urgency_flags": sum(1 for r in rows if r["audit"]["urgency_flags"]),
        "ask_flags": sum(1 for r in rows if r["audit"]["ask_flags"]),
        "two_plus_questions": sum(1 for r in rows if r["question_marks"] >= 2),
        "similarity_rejected": sum(1 for r in rows if r["similarity"]["would_be_rejected"]),
        "similarity_max_ratio": max((r["similarity"]["ratio"] for r in rows), default=None),
        "similarity_max_containment": max((r["similarity"]["containment"] for r in rows), default=None),
        "prompt_tokens": pt, "completion_tokens": ct, "cost_usd_computed": round(cost, 6) if cost is not None else None,
        "cost_per_http200_call": round(cost / len(ok), 6) if cost is not None and ok else None,
        "upstreams": sorted({str(c["upstream"]) for c in ok if c["upstream"]}),
    }


def facts_digest():
    lines = ["# Facts digest per pair (what the model was allowed to use)", ""]
    for p in PAIRS:
        pid = p["test_id"]
        st = STATIC[pid]
        ctx, m, c, t, cu = st["ctx"], st["merchant"], st["category"], st["trigger"], st["customer"]
        ident = m.get("identity") or {}
        offers = m.get("offers") or []
        perf = m.get("performance") or {}
        cat_offers = [(o.get("title") if isinstance(o, dict) else o) for o in (c.get("offer_catalog") or [])]
        hist = m.get("conversation_history") or []
        lines.append(f"### {pid} {t.get('kind')} | {ident.get('name')} (owner {ident.get('owner_first_name')}, {ident.get('locality')}, {ident.get('city')}) | "
                     f"languages={ident.get('languages')} | mode={ctx['language_mode']} | send_as={ctx['send_as']}")
        lines.append(f"- TRIGGER payload: {json.dumps(t.get('payload'), ensure_ascii=False)}")
        lines.append(f"- MERCHANT active offers: {[o.get('title') for o in offers if o.get('status') == 'active']} | other: "
                     f"{[str(o.get('title')) + ' [' + str(o.get('status')) + ']' for o in offers if o.get('status') != 'active']}")
        lines.append(f"- CATEGORY catalog offers (suggestion only): {cat_offers}")
        lines.append(f"- CATEGORY seasonal_beats: {json.dumps(c.get('seasonal_beats'), ensure_ascii=False)[:260]}")
        lines.append(f"- PERF: views={perf.get('views')} calls={perf.get('calls')} ctr={perf.get('ctr')} delta_7d={perf.get('delta_7d')}")
        lines.append(f"- DERIVED: {ctx['derived_facts']}")
        lines.append(f"- signals={m.get('signals')} | review_themes={m.get('review_themes')}")
        lines.append(f"- last conversation turn: {json.dumps(hist[-1], ensure_ascii=False)[:220] if hist else 'none'}")
        if cu:
            lines.append(f"- CUSTOMER: identity={json.dumps({k: v for k, v in (cu.get('identity') or {}).items() if k != 'phone_redacted'}, ensure_ascii=False)} | "
                         f"relationship={json.dumps(cu.get('relationship'), ensure_ascii=False)} | prefs={json.dumps(cu.get('preferences'), ensure_ascii=False)} | state={cu.get('state')}")
        lines.append("")
    (OUT / "facts_digest.md").write_text("\n".join(lines), encoding="utf-8")


def phase_report():
    runs = {}
    for name in ("existing", "sequential"):
        f = OUT / f"{name}.json"
        if f.exists():
            runs[name] = json.load(open(f, encoding="utf-8"))
    price = None
    for r in runs.values():
        if r.get("pricing") and r["pricing"].get("pricing"):
            price = r["pricing"]["pricing"]
    metrics = {name: run_metrics(r["rows"], price) for name, r in runs.items()}
    providers = json.load(open(OUT / "providers.json", encoding="utf-8")) if (OUT / "providers.json").exists() else None
    save("summary.json", {"model": MODEL, "pricing": (runs.get("sequential") or {}).get("pricing"), "metrics": metrics,
                          "account": {n: {"before": r.get("account_before"), "after": r.get("account_after")} for n, r in runs.items()}})
    facts_digest()
    L = [f"# {MODEL}: 30-pair validation report (generated {datetime.now().strftime('%Y-%m-%d %H:%M')})", ""]
    for name, m in metrics.items():
        L += [f"## Metrics: {name}", "", "```json", json.dumps(m, indent=1, ensure_ascii=False), "```", ""]
    if providers:
        L += ["## Provider tests", "", "```json", json.dumps(providers, indent=1, ensure_ascii=False)[:14000], "```", ""]
    seq = {r["pair"]: r for r in runs["sequential"]["rows"]} if "sequential" in runs else {}
    ex = {r["pair"]: r for r in runs["existing"]["rows"]} if "existing" in runs else {}
    L += ["## Per pair", ""]
    for p in PAIRS:
        pid = p["test_id"]
        for label, src in (("SEQ", seq), ("EXIST", ex)):
            r = src.get(pid)
            if not r:
                continue
            same = ""
            if label == "EXIST" and pid in seq:
                same = " | identical to SEQ" if seq[pid]["body"] == r["body"] else " | DIFFERENT from SEQ"
            L.append(f"### {pid} [{label}] {r['kind']} | {r['merchant']} | mode {r['mode']} | {r['send_as']} | cta {r['cta']} | source {r['source']} | "
                     f"{r['seconds']} s | attempts {r['attempts']}{same}")
            L += ["", "> " + r["body"].replace("\n", "\n> "), ""]
            flags = {"final_hard": r["final_hard"], "final_soft": r["final_soft"], "audit": {k: v for k, v in r["audit"].items() if v and k != "words"},
                     "extra": r["extra"], "hindi_markers": r["hindi_markers"], "fallback_cause": r["fallback_cause"]}
            L.append("flags: " + json.dumps({k: v for k, v in flags.items() if v not in (None, [], {}, 0)}, ensure_ascii=False))
            L.append("calls: " + json.dumps([{k: c.get(k) for k in ("http", "latency", "prompt_tokens", "completion_tokens", "error")} for c in r["calls"]]))
            drafts = [c.get("draft") for c in r["calls"] if c.get("draft")]
            if len(drafts) > 1 or (drafts and drafts[0]["body"] != r["body"]):
                for i, d in enumerate(drafts, 1):
                    L.append(f"draft {i}: hard={d['hard']} soft={d['soft']} body={d['body']!r}")
            L.append("")
    (OUT / "report.md").write_text("\n".join(L), encoding="utf-8")
    print("report written:", OUT / "report.md")
    print(json.dumps(metrics, indent=1, ensure_ascii=False)[:6000])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", required=True, choices=["existing", "sequential", "providers", "report"])
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print("LLM setup for this process:", llm.label(), flush=True)
    assert llm.model_for(next(p for p in llm.PROVIDERS if p["name"] == "openrouter")) == MODEL
    assert [p["name"] for p in llm.configured_providers()] == ["openrouter"], "only OpenRouter may be configured"
    if args.phase == "existing":
        phase_existing()
    elif args.phase == "sequential":
        phase_sequential()
    elif args.phase == "providers":
        phase_providers()
    else:
        phase_report()
    with open(OUT / f"calls_{args.phase}.jsonl", "w", encoding="utf-8") as f:
        for c in CALLS:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
