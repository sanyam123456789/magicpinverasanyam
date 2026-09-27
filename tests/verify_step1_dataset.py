"""Step 1 verification: expanded dataset + 30 canonical test pairs are consistent.

Run from E:\\MAGICPIN:  python tests/verify_step1_dataset.py
Exit code 0 = every check passed.
"""
import glob
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "expanded"


def load(pattern, key):
    out = {}
    for f in glob.glob(str(EXP / pattern)):
        obj = json.load(open(f, encoding="utf-8"))
        out[obj[key]] = obj
    return out


failures = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


cats = load("categories/*.json", "slug")
mers = load("merchants/*.json", "merchant_id")
cuss = load("customers/*.json", "customer_id")
trgs = load("triggers/*.json", "id")
pairs = json.load(open(EXP / "test_pairs.json", encoding="utf-8"))["pairs"]

check("5 categories", len(cats) == 5, str(sorted(cats)))
check("50 merchants", len(mers) == 50)
check("200 customers", len(cuss) == 200)
check("100 triggers", len(trgs) == 100)
check("30 canonical test pairs", len(pairs) == 30)

check("every merchant's category exists", all(m["category_slug"] in cats for m in mers.values()))
check("every trigger has top-level merchant_id + customer_id keys",
      all("merchant_id" in t and "customer_id" in t for t in trgs.values()))
check("no trigger keeps merchant_id inside payload", not any("merchant_id" in t["payload"] for t in trgs.values()))
check("every trigger's merchant exists", all(t["merchant_id"] in mers for t in trgs.values()))
check("every customer-scope trigger has an existing customer",
      all(t["customer_id"] in cuss for t in trgs.values() if t["scope"] == "customer"))

bad = []
for p in pairs:
    t = trgs.get(p["trigger_id"])
    if not t or p["merchant_id"] not in mers or t["merchant_id"] != p["merchant_id"]:
        bad.append(p["test_id"])
    elif p["customer_id"] and (p["customer_id"] not in cuss or t["customer_id"] != p["customer_id"]):
        bad.append(p["test_id"])
check("all 30 pairs resolve (merchant, trigger, customer, category)", not bad, ",".join(bad))

all_digest_ids = {i["id"] for c in cats.values() for i in c["digest"]}
refs = [(t["id"], t["payload"].get(k)) for t in trgs.values() for k in ("top_item_id", "digest_item_id") if k in t["payload"]]
check("all digest references in triggers resolve to a category digest item",
      all(r in all_digest_ids for _, r in refs), f"{len(refs)} refs")

kinds = Counter(t["kind"] for t in trgs.values())
placeholder_pairs = [p["test_id"] for p in pairs if trgs[p["trigger_id"]]["payload"].get("placeholder")]
print(f"\nINFO  trigger kinds: {len(kinds)}")
print(f"INFO  placeholder-payload pairs: {len(placeholder_pairs)}/30 -> {','.join(placeholder_pairs)}")
print(f"INFO  customer pairs: {sum(bool(p['customer_id']) for p in pairs)}/30")
print(f"INFO  merchant languages: {dict(Counter(tuple(m['identity']['languages']) for m in mers.values()))}")

print("\nRESULT:", "ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
