"""LIVE audit: compose the 30 canonical pairs with the REAL configured LLM and check every message.

    python tests/live_audit_30_pairs.py                    # needs GROQ_API_KEY and/or OPENROUTER_API_KEY in .env
    python tests/live_audit_30_pairs.py --allow-fallback   # no key: exercises the plumbing only (NOT a live result)
    options: --no-llm-audit  --no-drills  --no-determinism  --limit N  --workers N  --out-dir out

Per message it runs the 14 checks of the audit brief (facts supported, invented name/number/offer, unsupported urgency, URL, taboo,
category fit, one strongest signal, one clear ask, generic, copy of a case-study anchor, latency) plus, once per run, the
fail-over drills (primary provider broken -> secondary answers; both broken -> deterministic fallback) and a determinism probe.
The heuristics in tests/audit_lib.py are ADVISORY (they queue messages for a human to read); the optional LLM auditor adds a
second opinion. Results are saved to out/live_audit_30_pairs.jsonl and out/live_audit_report.md.
"""
import argparse
import glob
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import audit_lib  # noqa: E402
import composer  # noqa: E402
import llm  # noqa: E402
import tick as ticker  # noqa: E402

AUDITOR_SYSTEM = """You are a strict auditor of WhatsApp messages written by a merchant-growth bot for Indian merchants.
You receive FACTS (the ONLY context the bot was given) and the MESSAGE it wrote.
An item is UNSUPPORTED if it is neither stated in FACTS nor directly computable from them. Quote the exact words.
Return ONE JSON object and nothing else:
{"unsupported_claims": [..], "invented_names": [..], "invented_numbers": [..], "invented_offers": [..],
 "unsupported_urgency": [..], "generic": true|false, "single_signal": true|false, "single_ask": true|false,
 "category_appropriate": true|false, "notes": "<one sentence>"}
Use empty lists when everything is supported. single_signal is true when the message is built around ONE main fact.
single_ask is true when the message asks for exactly one low-effort next step."""


def load(pattern, key):
    out = {}
    for f in glob.glob(str(ROOT / "expanded" / pattern)):
        obj = json.load(open(f, encoding="utf-8"))
        out[obj[key]] = obj
    return out


def facts_for_auditor(ctx: dict) -> str:
    keep = {k: ctx.get(k) for k in ("category", "merchant", "trigger", "customer", "derived_facts")}
    return json.dumps(keep, ensure_ascii=False, separators=(",", ":"))


def llm_audit(ctx: dict, body: str) -> dict:
    user = f"FACTS: {facts_for_auditor(ctx)}\n\nMESSAGE: {json.dumps(body, ensure_ascii=False)}\n\nAudit the message now."
    try:
        obj, provider = llm.chat_json([{"role": "system", "content": AUDITOR_SYSTEM}, {"role": "user", "content": user}],
                                      max_tokens=500, timeout=15.0)
        obj["_provider"] = provider
        return obj
    except Exception as exc:  # noqa: BLE001  the auditor is advisory: never break the run
        return {"error": f"{type(exc).__name__}: {str(exc)[:120]}"}


def compose_row(pair, data, do_llm_audit):
    cats, mers, cuss, trgs = data
    merchant = mers[pair["merchant_id"]]
    category = cats[merchant["category_slug"]]
    trigger = trgs[pair["trigger_id"]]
    customer = cuss.get(pair["customer_id"]) if pair["customer_id"] else None
    t0 = time.time()
    detailed = composer.compose_detailed(category, merchant, trigger, customer, timeout=ticker.COMPOSE_TIMEOUT_SECONDS)
    seconds = time.time() - t0
    msg, meta = detailed["message"], detailed["meta"]
    ctx = composer.build_context(category, merchant, trigger, customer)
    row = {
        "test_id": pair["test_id"], "kind": trigger["kind"], "category": category["slug"], "merchant": merchant["identity"]["name"],
        "placeholder": bool((trigger.get("payload") or {}).get("placeholder")), "send_as": msg["send_as"], "cta": msg["cta"],
        "body": msg["body"], "rationale": msg["rationale"], "source": meta["source"], "attempts": meta["attempts"],
        "issues": meta["issues"], "seconds": round(seconds, 2),
        "audit": audit_lib.audit_message(msg["body"], msg["cta"], ctx, category),
    }
    row["llm_audit"] = llm_audit(ctx, msg["body"]) if do_llm_audit else None
    return row


def flags_for(row: dict) -> dict[int, list[str]]:
    """The 14 audit-brief checks -> list of reasons (empty = nothing to review)."""
    a, la = row["audit"], row.get("llm_audit") or {}

    def lst(key):
        v = la.get(key)
        return [str(x) for x in v] if isinstance(v, list) else []

    sim = a["similarity"]
    return {
        1: a["ungrounded_numbers"] + a["validator_hard"] + lst("unsupported_claims"),
        2: a["possible_invented_names"] + lst("invented_names"),
        3: a["ungrounded_numbers"] + lst("invented_numbers"),
        4: a["offer_flags"] + lst("invented_offers"),
        5: a["urgency_flags"] + lst("unsupported_urgency"),
        6: ["URL in body"] if a["url"] else [],
        7: a["taboo"],
        8: a["tone_flags"] + a["validator_soft"] + ([] if la.get("category_appropriate", True) else ["auditor: not category-appropriate"]),
        9: a["fact_dump"] + ([] if la.get("single_signal", True) else ["auditor: not built on one signal"]),
        10: a["ask_flags"] + ([] if la.get("single_ask", True) else ["auditor: not exactly one low-effort ask"]),
        11: a["generic_flags"] + (["auditor: generic"] if la.get("generic") is True else []),
        12: ([f"would be rejected by the similarity guard (ratio {sim['ratio']}, containment {sim['containment']})"] if sim["would_be_rejected"]
             else ([f"close to a case-study anchor (ratio {sim['ratio']}, containment {sim['containment']}): {sim['ref_preview']}"]
                    if sim["ratio"] >= 0.5 or sim["containment"] >= 0.2 else [])),
        13: ([f"{row['seconds']} s (> 30 s hard limit)"] if row["seconds"] > 30 else
             [f"{row['seconds']} s (> 10 s example budget)"] if row["seconds"] > 10 else
             [f"{row['seconds']} s (> 8 s tick budget)"] if row["seconds"] > 8 else []),
    }


CHECK_NAMES = {
    1: "Every factual claim supported by context", 2: "No invented name", 3: "No invented number", 4: "No invented offer",
    5: "No unsupported urgency", 6: "No URL", 7: "No taboo word", 8: "Category-appropriate voice",
    9: "One strongest signal (not a fact dump)", 10: "One clear low-friction next step", 11: "Not generic",
    12: "Does not copy a case-study anchor", 13: "Latency within target (<= 8 s tick budget; 10 s example; 30 s hard)",
    14: "Fallback works when the primary provider fails",
}


def run_drill(name, env_overrides, ids, data, expect):
    cats, mers, cuss, trgs = data
    pairs = {p["test_id"]: p for p in json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]}
    saved = {k: os.environ.get(k) for k in env_overrides}
    os.environ.update(env_overrides)
    llm._cooldown_until.clear()
    llm.last_errors.clear()
    composer.clear_cache()
    results = []
    try:
        for tid in ids:
            p = pairs[tid]
            m = mers[p["merchant_id"]]
            t0 = time.time()
            d = composer.compose_detailed(cats[m["category_slug"]], m, trgs[p["trigger_id"]], cuss.get(p["customer_id"]) if p["customer_id"] else None,
                                          timeout=ticker.COMPOSE_TIMEOUT_SECONDS)
            results.append({"test_id": tid, "source": d["meta"]["source"], "seconds": round(time.time() - t0, 2),
                            "body_ok": bool(d["message"]["body"].strip())})
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        llm._cooldown_until.clear()
        llm.last_errors.clear()
        composer.clear_cache()
    ok = all(r["source"].startswith(expect) and r["body_ok"] for r in results)
    return {"drill": name, "expected_source": expect, "ok": ok, "results": results}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--allow-fallback", action="store_true")
    ap.add_argument("--no-llm-audit", action="store_true")
    ap.add_argument("--no-drills", action="store_true")
    ap.add_argument("--no-determinism", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=ticker.MAX_WORKERS)
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    args = ap.parse_args(argv)

    providers = llm.configured_providers()
    if not providers and not args.allow_fallback:
        print("No LLM key configured (GROQ_API_KEY / OPENROUTER_API_KEY in .env).")
        print("Add a key, or run with --allow-fallback to exercise the plumbing only (NOT a live result).")
        return 2
    live = bool(providers)
    do_llm_audit = live and not args.no_llm_audit
    data = (load("categories/*.json", "slug"), load("merchants/*.json", "merchant_id"), load("customers/*.json", "customer_id"),
            load("triggers/*.json", "id"))
    pairs = json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]
    if args.limit:
        pairs = pairs[:args.limit]
    print(f"LLM setup: {llm.label()}  | live={live} | LLM auditor={'on' if do_llm_audit else 'off'} | pairs={len(pairs)}")

    composer.clear_cache()
    started = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        rows = list(pool.map(lambda p: compose_row(p, data, do_llm_audit), pairs))
    wall = time.time() - started

    # ---- determinism probe (LLM level: cache cleared, same inputs, compare the text)
    determinism = None
    if live and not args.no_determinism:
        probe = pairs[:5]
        composer.clear_cache()
        again = [compose_row(p, data, False) for p in probe]
        same = sum(1 for a, b in zip(rows, again) if a["body"] == b["body"])
        determinism = {"pairs": len(probe), "identical": same, "note": "cache cleared between runs, so this measures the LLM itself"}

    # ---- fail-over drills
    drills = []
    if live and not args.no_drills:
        ids = [r["test_id"] for r in rows[:3]]
        if len(providers) >= 2:
            drills.append(run_drill("primary (Groq) broken -> OpenRouter must answer", {"GROQ_API_KEY": "invalid-key-for-failover-drill"}, ids, data, "llm:openrouter"))
        drills.append(run_drill("every provider broken -> deterministic fallback",
                                {"GROQ_API_KEY": "invalid-key-for-failover-drill", "OPENROUTER_API_KEY": "invalid-key-for-failover-drill"}, ids, data, "fallback"))

    # ---- aggregate
    per_check = {n: [] for n in range(1, 15)}
    for row in rows:
        row["flags"] = flags_for(row)
        for n, reasons in row["flags"].items():
            if reasons:
                per_check[n].append(row["test_id"])
    per_check[14] = [] if (drills and all(d["ok"] for d in drills)) else (["not run"] if not drills else [d["drill"] for d in drills if not d["ok"]])
    secs = [r["seconds"] for r in rows]
    llm_rows = [r for r in rows if r["source"].startswith("llm")]
    stats = {"messages": len(rows), "from_llm": len(llm_rows), "fallback": len(rows) - len(llm_rows),
             "p50_s": round(statistics.median(secs), 2), "p95_s": round(sorted(secs)[max(0, int(len(secs) * 0.95) - 1)], 2),
             "max_s": max(secs), "wall_s": round(wall, 1), "retried": sum(1 for r in rows if r["attempts"] > 1)}

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "live_audit_30_pairs.jsonl", "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    lines = [f"# Live audit of the canonical pairs ({datetime.now().strftime('%Y-%m-%d %H:%M')})", ""]
    lines.append("**" + ("LIVE RESULT" if live else "NOT A LIVE RESULT: no LLM key was configured, every message below is the deterministic fallback") + "**")
    lines += ["", f"- LLM setup: `{llm.label()}`", f"- LLM auditor: {'on' if do_llm_audit else 'off'}",
              f"- Messages: {stats['messages']} | from LLM: {stats['from_llm']} | fallback: {stats['fallback']} | needed a retry: {stats['retried']}",
              f"- Latency per message (parallel, like a tick): p50 {stats['p50_s']} s, p95 {stats['p95_s']} s, max {stats['max_s']} s; whole batch {stats['wall_s']} s", ""]
    lines += ["## The 14 checks", "", "| # | Check | Result | Messages to review |", "|---|---|---|---|"]
    for n in range(1, 15):
        res = per_check[n]
        lines.append(f"| {n} | {CHECK_NAMES[n]} | {'PASS' if not res else 'REVIEW'} | {', '.join(res) if res else '-'} |")
    if determinism:
        lines += ["", f"Determinism probe: {determinism['identical']}/{determinism['pairs']} identical after clearing the cache ({determinism['note']})."]
    for d in drills:
        lines += ["", f"Drill: **{d['drill']}** -> {'OK' if d['ok'] else 'FAILED'}", ""]
        lines += [f"- {r['test_id']}: source `{r['source']}`, {r['seconds']} s" for r in d["results"]]
    lines += ["", "## Messages", ""]
    for row in rows:
        lines.append(f"### {row['test_id']} {row['kind']} | {row['merchant']} | {row['send_as']} | cta `{row['cta']}` | `{row['source']}` | {row['seconds']} s"
                     + (" | placeholder trigger" if row["placeholder"] else ""))
        lines += ["", "> " + row["body"].replace("\n", "\n> "), "", f"*rationale:* {row['rationale']}"]
        flagged = {n: r for n, r in row["flags"].items() if r}
        if flagged:
            lines += ["", "**Review:**"] + [f"- [{n}] {CHECK_NAMES[n]}: " + "; ".join(r)[:300] for n, r in flagged.items()]
        if row.get("llm_audit"):
            lines += ["", f"*auditor:* {json.dumps(row['llm_audit'], ensure_ascii=False)[:400]}"]
        if row["issues"]:
            lines += ["", "*validator/LLM issues during composition:* " + "; ".join(row["issues"])[:300]]
        lines.append("")
    (out_dir / "live_audit_report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines[:26]))
    print(f"\nSaved: {out_dir / 'live_audit_30_pairs.jsonl'} and {out_dir / 'live_audit_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
