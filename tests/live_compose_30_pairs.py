"""LIVE composer check: compose the 30 canonical pairs with the real LLM providers and write them for review.

Run from E:\\MAGICPIN:
    python tests/live_compose_30_pairs.py                    # needs GROQ_API_KEY and/or OPENROUTER_API_KEY in .env
    python tests/live_compose_30_pairs.py --allow-fallback   # no keys: shows the deterministic fallback messages

Output: out/compose_30_pairs.jsonl  (test_id, kind, merchant, send_as, cta, body, rationale, source, seconds, issues)
Read the bodies yourself (the material says fabrication is the top rejection reason) and note anything odd.
"""
import glob
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import composer  # noqa: E402
import llm  # noqa: E402

allow_fallback = "--allow-fallback" in sys.argv


def load(pattern, key):
    return {json.load(open(f, encoding="utf-8"))[key]: json.load(open(f, encoding="utf-8")) for f in glob.glob(str(ROOT / "expanded" / pattern))}


cats, mers = load("categories/*.json", "slug"), load("merchants/*.json", "merchant_id")
cuss, trgs = load("customers/*.json", "customer_id"), load("triggers/*.json", "id")
pairs = json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]

if not llm.configured_providers() and not allow_fallback:
    print("No LLM key configured (GROQ_API_KEY / OPENROUTER_API_KEY in .env).")
    print("Add a key, or run with --allow-fallback to see the deterministic fallback output only.")
    sys.exit(2)
print("LLM setup:", llm.label())


def run(pair):
    m = mers[pair["merchant_id"]]
    cus = cuss.get(pair["customer_id"]) if pair["customer_id"] else None
    t0 = time.time()
    d = composer.compose_detailed(cats[m["category_slug"]], m, trgs[pair["trigger_id"]], cus, timeout=8.0)
    return pair, m, d, time.time() - t0


out_dir = ROOT / "out"
out_dir.mkdir(exist_ok=True)
rows = []
with ThreadPoolExecutor(max_workers=4) as pool:
    for pair, m, d, secs in pool.map(run, pairs):
        msg, meta = d["message"], d["meta"]
        rows.append({"test_id": pair["test_id"], "kind": trgs[pair["trigger_id"]]["kind"], "merchant": m["identity"]["name"],
                     "send_as": msg["send_as"], "cta": msg["cta"], "body": msg["body"], "rationale": msg["rationale"],
                     "source": meta["source"], "seconds": round(secs, 2), "issues": meta["issues"]})
with open(out_dir / "compose_30_pairs.jsonl", "w", encoding="utf-8") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

for row in rows:
    print(f"\n[{row['test_id']}] {row['kind']} | {row['merchant']} | {row['send_as']} | {row['cta']} | {row['source']} | {row['seconds']}s")
    print("   " + row["body"])
    if row["issues"]:
        print("   issues:", "; ".join(row["issues"])[:300])

llm_rows = [r for r in rows if r["source"].startswith("llm")]
print(f"\nSUMMARY: {len(rows)} messages | from LLM: {len(llm_rows)} | fallback: {len(rows) - len(llm_rows)} | "
      f"slowest {max(r['seconds'] for r in rows)}s")
print("Written to out/compose_30_pairs.jsonl")
