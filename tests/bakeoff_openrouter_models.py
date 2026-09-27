"""OpenRouter model bake-off: EVIDENCE ONLY. It does not change the production configuration.

    python tests/bakeoff_openrouter_models.py --models anthropic/claude-haiku-4.5,openai/gpt-4.1-mini,google/gemini-3.5-flash-lite
    python tests/bakeoff_openrouter_models.py --regen        # rebuild summary/report from out/bakeoff/bakeoff_raw.jsonl (no paid calls)
    options: --pairs T01,T07,...  --seq-rounds 2  --par-workers 6  --client-timeout 45  --max-spend 2.0  --out-dir out/bakeoff

Every model receives the identical production prompt (composer.build_messages), identical request parameters (temperature 0,
max_tokens 450, seed 7: the same body llm._post sends) and is judged by the identical validator / audit_lib. The only variable is
the model id. Calls go straight to OpenRouter and bypass llm.chat(), so there is no provider order, cooldown, retry or fallback:
we see each model's raw first-draft behaviour. Prices come from OpenRouter's own public model list, fetched at run time.

Rounds: S1, S2 = sequential (isolates model latency, S2 also shows repeatability), P = one parallel burst of all pairs with
6 workers (like a tick). Every call is recorded. Latency statistics use only calls that returned HTTP 200: an error response
(for example HTTP 402 from the account) is not model latency and is reported separately.
"""
import argparse
import json
import math
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import audit_lib  # noqa: E402
import composer  # noqa: E402
import llm  # noqa: E402
import validator  # noqa: E402
from config import env  # noqa: E402
from live_audit_30_pairs import load  # noqa: E402

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
CATALOG_URL = "https://openrouter.ai/api/v1/models"
KEY_URL = "https://openrouter.ai/api/v1/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
DEFAULT_PAIRS = "T01,T07,T09,T13,T19,T24,T29,T30"
DEFAULT_MODELS = "anthropic/claude-haiku-4.5,openai/gpt-4.1-mini,google/gemini-3.5-flash-lite"
BUDGET_S = 6.0  # production compose budget (tick.COMPOSE_TIMEOUT_SECONDS)
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def pctl(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def account_status(key):
    """Numbers only (never the key or its label): key limit/usage and the account's purchased credits."""
    out = {}
    headers = {"Authorization": f"Bearer {key}"}
    try:
        d = requests.get(KEY_URL, headers=headers, timeout=15).json().get("data", {})
        out.update({k: d.get(k) for k in ("limit", "limit_remaining", "usage", "is_free_tier")})
    except Exception:  # noqa: BLE001  informational only
        pass
    try:
        d = requests.get(CREDITS_URL, headers=headers, timeout=15).json().get("data", {})
        out.update({"total_credits": d.get("total_credits"), "total_usage": d.get("total_usage")})
    except Exception:  # noqa: BLE001
        pass
    return out or None


def call_model(model, messages, key, timeout):
    body = {"model": model, "messages": messages, "temperature": 0, "max_tokens": 450, "seed": 7}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    out = {"http": None, "error": None, "content": "", "finish": None, "usage": {}, "provider": None}
    t0 = time.perf_counter()
    try:
        r = requests.post(CHAT_URL, headers=headers, json=body, timeout=(10, timeout))
        out["http"] = r.status_code
        if r.status_code == 200:
            j = r.json()
            choice = (j.get("choices") or [{}])[0]
            out["content"] = (choice.get("message") or {}).get("content") or ""
            out["finish"] = choice.get("finish_reason")
            out["usage"] = j.get("usage") or {}
            out["provider"] = j.get("provider")
            if j.get("error"):
                out["error"] = str(j["error"])[:200]
        else:
            out["error"] = r.text[:300]
    except requests.exceptions.Timeout as exc:
        out["error"] = f"client_timeout ({type(exc).__name__})"
    except requests.RequestException as exc:
        out["error"] = type(exc).__name__
    out["latency"] = round(time.perf_counter() - t0, 2)
    return out


def analyse(model, price, pair_id, static, res, round_name):
    ctx, category, merchant, trigger, customer, messages, prior = static
    usage = res["usage"]
    pt, ct = usage.get("prompt_tokens"), usage.get("completion_tokens")
    details = usage.get("completion_tokens_details") or {}
    cost = None
    if price and isinstance(pt, (int, float)) and isinstance(ct, (int, float)):
        cost = pt * float(price["prompt"]) + ct * float(price["completion"])
    row = {"model": model, "pair": pair_id, "round": round_name, "http": res["http"], "latency": res["latency"],
           "error": res["error"], "finish": res["finish"], "provider": res["provider"], "prompt_tokens": pt,
           "completion_tokens": ct, "reasoning_tokens": details.get("reasoning_tokens"), "cost_usd": cost,
           "raw_content": res["content"], "language_mode": ctx["language_mode"], "send_as": ctx["send_as"],
           "placeholder": bool((trigger.get("payload") or {}).get("placeholder"))}
    obj = llm.extract_json(res["content"]) if res["content"] else None
    body_ok = isinstance(obj, dict) and isinstance(obj.get("body"), str) and obj["body"].strip()
    row["malformed"] = bool(res["http"] == 200 and not body_ok)
    row["ok"] = bool(res["http"] == 200 and body_ok)
    if not body_ok:
        return row
    msg = composer.finalize(obj, ctx, merchant, trigger, customer)
    verdict = validator.validate(msg["body"], msg["cta"], ctx, category, prior)
    audit = audit_lib.audit_message(msg["body"], msg["cta"], ctx, category)
    sim = audit["similarity"]
    row.update({
        "body": msg["body"], "cta": msg["cta"], "rationale": msg["rationale"], "words": audit["words"],
        "hard": verdict.hard, "soft": verdict.soft,
        "url": audit["url"], "taboo": audit["taboo"], "ungrounded_numbers": audit["ungrounded_numbers"],
        "possible_invented_names": audit["possible_invented_names"], "offer_flags": audit["offer_flags"],
        "urgency_flags": audit["urgency_flags"], "generic_flags": audit["generic_flags"], "fact_dump": audit["fact_dump"],
        "ask_flags": audit["ask_flags"], "tone_flags": audit["tone_flags"],
        "sim_ratio": sim["ratio"], "sim_containment": sim["containment"], "sim_rejected": sim["would_be_rejected"],
        "hindi_markers": validator.hindi_marker_count(msg["body"]),
        "language_ok": not any(s.startswith("language") for s in verdict.soft),
        "needs_retry_or_fallback": bool(verdict.hard),
    })
    return row


def summarise(model, rows, price):
    mine = [r for r in rows if r["model"] == model]
    got = [r for r in mine if r["http"] == 200]
    okr = [r for r in mine if r.get("ok")]
    lat_ok = [r["latency"] for r in got]
    lat_seq = [r["latency"] for r in got if r["round"] != "P"]
    lat_par = [r["latency"] for r in got if r["round"] == "P"]
    lat_err = [r["latency"] for r in mine if r["http"] != 200]

    def cnt(key):
        return sum(1 for r in okr if r.get(key))

    def stat(values):
        return {"n": len(values), "avg": round(statistics.mean(values), 2) if values else None,
                "p50": round(statistics.median(values), 2) if values else None, "p95": pctl(values, 0.95),
                "max": max(values) if values else None}

    s1 = {r["pair"]: r.get("body") for r in mine if r["round"] == "S1"}
    s2 = {r["pair"]: r.get("body") for r in mine if r["round"] == "S2"}
    same = sum(1 for p in s1 if s1[p] and s1[p] == s2.get(p))
    both = sum(1 for p in s1 if s1[p] and s2.get(p))
    costs = [r["cost_usd"] for r in mine if r["cost_usd"] is not None]
    err_codes = {}
    for r in mine:
        if r["http"] != 200:
            err_codes[str(r["http"])] = err_codes.get(str(r["http"]), 0) + 1
    return {
        "calls": len(mine), "http_200": len(got), "usable": len(okr), "malformed": sum(1 for r in mine if r["malformed"]),
        "api_errors": sum(1 for r in mine if r["http"] not in (200, None)), "error_codes": err_codes,
        "rate_limited_429": sum(1 for r in mine if r["http"] == 429),
        "client_timeouts": sum(1 for r in mine if r["error"] and str(r["error"]).startswith("client_timeout")),
        "over_6s": sum(1 for v in lat_ok if v > BUDGET_S), "over_10s": sum(1 for v in lat_ok if v > 10),
        "latency_ok": stat(lat_ok), "latency_sequential": stat(lat_seq), "latency_parallel": stat(lat_par),
        "latency_error_responses": stat(lat_err),
        "finish_length": sum(1 for r in mine if r["finish"] == "length"),
        "providers_seen": sorted({str(r["provider"]) for r in mine if r["provider"]}),
        "hard_rejected_first_draft": cnt("needs_retry_or_fallback"),
        "soft_language_flag": sum(1 for r in okr if not r.get("language_ok", True)),
        "with_ungrounded_numbers": sum(1 for r in okr if r.get("ungrounded_numbers")),
        "with_possible_invented_names": sum(1 for r in okr if r.get("possible_invented_names")),
        "with_offer_flags": sum(1 for r in okr if r.get("offer_flags")),
        "with_urgency_flags": sum(1 for r in okr if r.get("urgency_flags")),
        "with_generic_flags": sum(1 for r in okr if r.get("generic_flags")),
        "with_fact_dump": sum(1 for r in okr if r.get("fact_dump")),
        "with_ask_flags": sum(1 for r in okr if r.get("ask_flags")),
        "with_two_or_more_questions": sum(1 for r in okr if r["body"].count("?") >= 2),
        "with_iso_date": sum(1 for r in okr if ISO_DATE_RE.search(r["body"])),
        "with_tone_flags": sum(1 for r in okr if r.get("tone_flags")),
        "url_violations": cnt("url"), "taboo_hits": sum(1 for r in okr if r.get("taboo")),
        "sim_max_ratio": max((r["sim_ratio"] for r in okr), default=None),
        "sim_max_containment": max((r["sim_containment"] for r in okr), default=None),
        "sim_would_be_rejected": cnt("sim_rejected"),
        "avg_hindi_markers": round(statistics.mean(r["hindi_markers"] for r in okr), 2) if okr else None,
        "avg_words": round(statistics.mean(r["words"] for r in okr), 1) if okr else None,
        "s1_s2_identical": f"{same}/{both}",
        "avg_prompt_tokens": round(statistics.mean(r["prompt_tokens"] for r in got if r["prompt_tokens"]), 0) if any(r["prompt_tokens"] for r in got) else None,
        "avg_completion_tokens": round(statistics.mean(r["completion_tokens"] for r in got if r["completion_tokens"]), 0) if any(r["completion_tokens"] for r in got) else None,
        "reasoning_tokens_total": sum(r["reasoning_tokens"] or 0 for r in mine),
        "cost_total_usd": round(sum(costs), 6) if costs else None,
        "cost_avg_per_call_usd": round(statistics.mean(costs), 6) if costs else None,
        "price_prompt_per_mtok": round(float(price["prompt"]) * 1e6, 4) if price else None,
        "price_completion_per_mtok": round(float(price["completion"]) * 1e6, 4) if price else None,
    }


def fmt_lat(v):
    return f"{v}s" + (" !" if v > BUDGET_S else "")


def metrics_table(L, title, models, summaries, skip=()):
    L += [f"## {title}", "", "| Metric | " + " | ".join(models) + " |", "|---|" + "---:|" * len(models)]

    def line(label, fn):
        if label.startswith(skip):
            return
        L.append(f"| {label} | " + " | ".join(str(fn(summaries[m])) for m in models) + " |")

    def frac(key):
        return lambda s: f"{s[key]}/{s['usable']}"

    line("Calls / HTTP 200 / usable", lambda s: f"{s['calls']} / {s['http_200']} / {s['usable']}")
    line("Error responses by HTTP code", lambda s: s["error_codes"] or "none")
    line("Latency avg (HTTP 200 only)", lambda s: s["latency_ok"]["avg"])
    line("Latency p50", lambda s: s["latency_ok"]["p50"])
    line("Latency p95 (nearest rank)", lambda s: s["latency_ok"]["p95"])
    line("Latency max", lambda s: s["latency_ok"]["max"])
    line("Sequential avg / max (n)", lambda s: f"{s['latency_sequential']['avg']} / {s['latency_sequential']['max']} ({s['latency_sequential']['n']})")
    line("Parallel burst avg / max (n)", lambda s: f"{s['latency_parallel']['avg']} / {s['latency_parallel']['max']} ({s['latency_parallel']['n']})")
    line("Successful calls over 6 s budget / over 10 s", lambda s: f"{s['over_6s']} / {s['over_10s']}")
    line("Client timeouts (45 s)", lambda s: s["client_timeouts"])
    line("Rate limits (429)", lambda s: s["rate_limited_429"])
    line("Malformed outputs / finish=length", lambda s: f"{s['malformed']} / {s['finish_length']}")
    line("First draft hard-rejected by validator", frac("hard_rejected_first_draft"))
    line("Not Hinglish as instructed (validator soft flag)", frac("soft_language_flag"))
    line("Avg Hindi markers per message", lambda s: s["avg_hindi_markers"])
    line("Ungrounded numbers (msgs)", frac("with_ungrounded_numbers"))
    line("Possible invented names (msgs, advisory)", frac("with_possible_invented_names"))
    line("Offer flags (msgs)", frac("with_offer_flags"))
    line("Urgency flags (msgs)", frac("with_urgency_flags"))
    line("Generic flags (msgs)", frac("with_generic_flags"))
    line("Fact-dump flags (msgs)", frac("with_fact_dump"))
    line("Single-ask flags (heuristic)", frac("with_ask_flags"))
    line("Messages with 2+ question marks", frac("with_two_or_more_questions"))
    line("Messages with raw ISO date (2026-04-01)", frac("with_iso_date"))
    line("Tone flags (msgs)", frac("with_tone_flags"))
    line("URL violations / taboo hits", lambda s: f"{s['url_violations']} / {s['taboo_hits']}")
    line("Case-study similarity max ratio / containment / rejected", lambda s: f"{s['sim_max_ratio']} / {s['sim_max_containment']} / {s['sim_would_be_rejected']}")
    line("Avg words", lambda s: s["avg_words"])
    line("Repeat S1 vs S2 identical", lambda s: s["s1_s2_identical"])
    line("Avg prompt / completion tokens", lambda s: f"{s['avg_prompt_tokens']} / {s['avg_completion_tokens']}")
    line("Reasoning tokens (total)", lambda s: s["reasoning_tokens_total"])
    line("Listed price USD per 1M tokens (in / out)", lambda s: f"{s['price_prompt_per_mtok']} / {s['price_completion_per_mtok']}")
    line("Computed cost of successful calls (USD, tokens x listed price)", lambda s: s["cost_total_usd"])
    line("Computed avg cost per successful call (USD)", lambda s: s["cost_avg_per_call_usd"])
    line("Upstream providers seen", lambda s: ", ".join(s["providers_seen"]) or "n/a")
    L.append("")


def write_report(out_dir, meta, models, rows, sum_all, sum_s1, pair_ids):
    L = [f"# OpenRouter model bake-off (evidence only, {meta['started']})", "",
         f"- Models: {', '.join(f'`{m}`' for m in models)}", f"- Pairs: {', '.join(pair_ids)}",
         "- Request body per call: temperature 0, max_tokens 450, seed 7 (same as production `llm._post`); prompt = production `composer.build_messages`",
         f"- Pricing source: {meta['pricing_source']} (fetched {meta['pricing_fetched_at']})",
         f"- Account meter (USD used by the key) before/after the run: {meta.get('usage_before')} -> {meta.get('usage_after')}",
         f"- Account status when the report was built (numbers only): {meta.get('account')}", ""]
    metrics_table(L, "A. Metrics, all rounds (S1 + S2 + P; only usable calls count in the flag rows)", models, sum_all)
    metrics_table(L, "B. Metrics, round S1 only (balanced: same 8 pairs, sequential, no account errors)", models, sum_s1,
                  skip=("Parallel burst", "Repeat S1 vs S2"))

    L += ["## Raw results: every call", "", "| Round | Pair | Model | HTTP | Latency | Finish | Tok in/out (reasoning) | Provider | Status | Hard | Soft |",
          "|---|---|---|---|---:|---|---|---|---|---|---|"]
    for r in rows:
        if r.get("ok"):
            status = "ok"
        elif r["malformed"]:
            status = "MALFORMED"
        elif r["http"] == 402:
            status = "HTTP 402 credits (account, not a model failure)"
        else:
            status = f"ERROR {str(r['error'])[:60]}"
        lat = fmt_lat(r["latency"]) if r["http"] == 200 else f"({r['latency']}s, error reply)"
        L.append(f"| {r['round']} | {r['pair']} | {r['model']} | {r['http']} | {lat} | {r['finish']} | "
                 f"{r['prompt_tokens']}/{r['completion_tokens']} ({r['reasoning_tokens']}) | {r['provider']} | {status} | "
                 f"{'; '.join(r.get('hard', []))[:120]} | {'; '.join(r.get('soft', []))[:80]} |")

    L += ["", "## Messages (round S1)", ""]
    for pid in pair_ids:
        L.append(f"### {pid}")
        for m in models:
            r = next((x for x in rows if x["model"] == m and x["pair"] == pid and x["round"] == "S1"), None)
            if not r:
                continue
            L += ["", f"**{m}** | {r['latency']} s | mode `{r['language_mode']}` | cta `{r.get('cta')}` | placeholder={r['placeholder']}", ""]
            if r.get("ok"):
                L.append("> " + r["body"].replace("\n", "\n> "))
                L += ["", f"*rationale:* {r['rationale']}"]
                flags = {k: r[k] for k in ("ungrounded_numbers", "possible_invented_names", "offer_flags", "urgency_flags", "generic_flags",
                                           "fact_dump", "ask_flags", "tone_flags", "taboo", "hard", "soft") if r.get(k)}
                if flags:
                    L.append(f"*flags:* {json.dumps(flags, ensure_ascii=False)[:600]}")
            else:
                L.append(f"(no usable message: http={r['http']} error={r['error']} raw={r['raw_content'][:200]!r})")
        L.append("")
    (out_dir / "bakeoff_report.md").write_text("\n".join(L), encoding="utf-8")


def finish(out_dir, meta, models, rows, prices, pair_ids):
    sum_all = {m: summarise(m, rows, prices.get(m)) for m in models}
    sum_s1 = {m: summarise(m, [r for r in rows if r["round"] == "S1"], prices.get(m)) for m in models}
    with open(out_dir / "bakeoff_raw.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out_dir / "bakeoff_summary.json").write_text(json.dumps({"meta": meta, "summary_all_rounds": sum_all, "summary_S1_only": sum_s1},
                                                            indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(out_dir, meta, models, rows, sum_all, sum_s1, pair_ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--pairs", default=DEFAULT_PAIRS)
    ap.add_argument("--seq-rounds", type=int, default=2)
    ap.add_argument("--par-workers", type=int, default=6)
    ap.add_argument("--client-timeout", type=float, default=45.0)
    ap.add_argument("--max-spend", type=float, default=2.0)
    ap.add_argument("--regen", action="store_true", help="rebuild summary and report from the saved raw rows (no API calls except a read-only account check)")
    ap.add_argument("--out-dir", default=str(ROOT / "out" / "bakeoff"))
    args = ap.parse_args()

    key = env("OPENROUTER_API_KEY")
    if not key:
        print("OPENROUTER_API_KEY is not configured.")
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.regen:
        rows = [json.loads(line) for line in open(out_dir / "bakeoff_raw.jsonl", encoding="utf-8")]
        pricing = json.load(open(out_dir / "pricing.json", encoding="utf-8"))
        old = json.load(open(out_dir / "bakeoff_summary.json", encoding="utf-8"))["meta"]
        models = list(pricing["models"])
        prices = {m: pricing["models"][m]["pricing"] for m in models}
        pair_ids = list(dict.fromkeys(r["pair"] for r in rows))
        old["account"] = account_status(key)
        finish(out_dir, old, models, rows, prices, pair_ids)
        print("Report rebuilt from saved rows:", out_dir / "bakeoff_report.md")
        return 0

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    pair_ids = [p.strip() for p in args.pairs.split(",") if p.strip()]
    catalog = {m["id"]: m for m in requests.get(CATALOG_URL, timeout=30).json()["data"]}
    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    prices, pricing_dump = {}, {}
    for m in list(models):
        entry = catalog.get(m)
        if not entry:
            print(f"MODEL NOT IN CATALOG, skipped: {m}")
            models.remove(m)
            continue
        prices[m] = entry.get("pricing") or {}
        pricing_dump[m] = {"pricing": entry.get("pricing"), "context_length": entry.get("context_length"),
                           "supported_parameters": entry.get("supported_parameters"),
                           "top_provider": entry.get("top_provider"), "name": entry.get("name")}
    (out_dir / "pricing.json").write_text(json.dumps({"fetched_at": fetched_at, "source": CATALOG_URL, "models": pricing_dump},
                                                    indent=2, ensure_ascii=False), encoding="utf-8")

    cats, mers, cuss, trgs = (load("categories/*.json", "slug"), load("merchants/*.json", "merchant_id"),
                              load("customers/*.json", "customer_id"), load("triggers/*.json", "id"))
    pairs = {p["test_id"]: p for p in json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]}
    static = {}
    for pid in pair_ids:
        p = pairs[pid]
        merchant = mers[p["merchant_id"]]
        category = cats[merchant["category_slug"]]
        trigger = trgs[p["trigger_id"]]
        customer = cuss.get(p["customer_id"]) if p["customer_id"] else None
        ctx = composer.build_context(category, merchant, trigger, customer)
        prior = [t.get("body") for t in merchant.get("conversation_history") or [] if t.get("from") == "vera"]
        static[pid] = (ctx, category, merchant, trigger, customer, composer.build_messages(ctx, None), prior)

    before = account_status(key)
    meta = {"started": datetime.now().strftime("%Y-%m-%d %H:%M"), "pricing_fetched_at": fetched_at,
            "pricing_source": "OpenRouter public model list (GET /api/v1/models), field `pricing` (USD per token)",
            "usage_before": (before or {}).get("usage")}
    rows, spent = [], [0.0]

    def run_one(model, pid, round_name):
        if spent[0] > args.max_spend:
            return None
        res = call_model(model, static[pid][5], key, args.client_timeout)
        row = analyse(model, prices.get(model), pid, static[pid], res, round_name)
        rows.append(row)
        spent[0] += row["cost_usd"] or 0.0
        state = "ok" if row.get("ok") else ("MALFORMED" if row["malformed"] else f"ERR {row['error']}")
        print(f"{round_name:2} {model:34} {pid} http={row['http']} {row['latency']:>5}s {state} hard={len(row.get('hard', []))} spent=${spent[0]:.4f}", flush=True)
        return row

    for i in range(args.seq_rounds):
        for pid in pair_ids:
            for m in models:  # interleave models within a pair so slow periods hit everyone alike
                run_one(m, pid, f"S{i + 1}")
    for m in models:
        with ThreadPoolExecutor(max_workers=args.par_workers) as pool:
            list(pool.map(lambda pid, mm=m: run_one(mm, pid, "P"), pair_ids))

    after = account_status(key)
    meta["usage_after"] = (after or {}).get("usage")
    meta["account"] = after
    finish(out_dir, meta, models, rows, prices, pair_ids)
    print(f"\nSaved to {out_dir}: bakeoff_report.md, bakeoff_summary.json, bakeoff_raw.jsonl, pricing.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
