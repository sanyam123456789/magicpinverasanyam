"""Step 3 verification (offline): prompt building, compose() wiring, determinism/cache, LLM failover.

These checks use a mocked LLM / mocked HTTP, so they need no API key. The LIVE quality check
(real Groq/OpenRouter outputs for the 30 pairs) is a separate script: tests/live_compose_30_pairs.py

Run from E:\\MAGICPIN:  python tests/verify_step3_composer.py
"""
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)

import composer  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def load(pattern, key):
    return {json.load(open(f, encoding="utf-8"))[key]: json.load(open(f, encoding="utf-8")) for f in glob.glob(str(ROOT / "expanded" / pattern))}


cats = load("categories/*.json", "slug")
mers = load("merchants/*.json", "merchant_id")
cuss = load("customers/*.json", "customer_id")
trgs = load("triggers/*.json", "id")
pairs = json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]


def inputs(p):
    m = mers[p["merchant_id"]]
    return cats[m["category_slug"]], m, trgs[p["trigger_id"]], cuss.get(p["customer_id"]) if p["customer_id"] else None


# ---------------------------------------------------------------- prompt building for all 30 pairs
sizes, built_ok = [], True
expect_lang = {"T03": "en", "T04": "hi_roman", "T07": "hi_roman", "T08": "en", "T13": "en", "T14": "en", "T15": "hinglish",
               "T28": "hinglish", "T29": "en"}
lang_ok, sendas_ok = True, True
for p in pairs:
    cat, mer, trg, cus = inputs(p)
    try:
        ctx = composer.build_context(cat, mer, trg, cus)
        msgs = composer.build_messages(ctx)
        sizes.append(sum(len(m["content"]) for m in msgs))
    except Exception as exc:  # noqa: BLE001
        built_ok = False
        print("   build failed for", p["test_id"], repr(exc))
        continue
    sendas_ok &= (ctx["send_as"] == ("merchant_on_behalf" if cus else "vera"))
    if p["test_id"] in expect_lang:
        lang_ok &= (ctx["language_mode"] == expect_lang[p["test_id"]])
    elif not cus:
        lang_ok &= ctx["language_mode"] in ("hinglish", "hinglish_light")
check("prompt builds for all 30 pairs", built_ok)
check("send_as = merchant_on_behalf exactly for the customer pairs", sendas_ok)
check("language mode follows customer language_pref / merchant languages + category code_mix", lang_ok)
check("prompts are compact (largest under 20k chars ~5k tokens)", max(sizes) < 20000, f"max={max(sizes)} chars")

# ---------------------------------------------------------------- specific context checks
by_id = {p["test_id"]: p for p in pairs}
c30 = composer.build_context(*inputs(by_id["T30"]))
check("T30 regulation_change resolves its digest item and adds authorities",
      c30["category"].get("digest_item", {}).get("id") == "d_2026W17_dci_radiograph" and "regulatory_authorities" in c30["category"])
c06 = composer.build_context(*inputs(by_id["T06"]))
check("T06 cde_opportunity resolves its digest item", c06["category"].get("digest_item", {}).get("id") == "d_2026W17_ida_webinar")
c21 = composer.build_context(*inputs(by_id["T21"]))
check("non-digest kinds do not carry the digest (one-signal focus)", "digest" not in c21["category"] and "digest_item" not in c21["category"])
c03 = composer.build_context(*inputs(by_id["T03"]))
check("placeholder trigger keeps its placeholder flag", c03["trigger"]["payload"].get("placeholder") is True)
check("customer block excludes phone", "phone_redacted" not in json.dumps(c03["customer"]))
check("merchant block excludes place_id", "place_id" not in json.dumps(c03["merchant"]))

d24 = " ".join(composer.build_context(*inputs(by_id["T24"]))["derived_facts"])
check("T24 perf_dip: delta_pct -0.5 is spelled out as -50%", "-50%" in d24, d24[:160])
d22 = " ".join(composer.build_context(*inputs(by_id["T22"]))["derived_facts"])
check("T22 milestone: remaining count computed in code (145 -> 150 = 5)", "5 more" in d22, d22[:160])
d26 = " ".join(composer.build_context(*inputs(by_id["T26"]))["derived_facts"])
check("T26 perf_spike: +15% spelled out", "+15%" in d26, d26[:160])
d20 = " ".join(composer.build_context(*inputs(by_id["T20"]))["derived_facts"])
check("T20 gbp_unverified: estimated_uplift_pct 0.3 -> +30%", "+30%" in d20, d20[:160])
d28 = composer.build_context(*inputs(by_id["T28"]))
m1 = mers["m_001_drmeera_dentist_delhi"]
d01 = " ".join(composer.build_context(cats["dentists"], m1, trgs["trg_001_research_digest_dentists"], None)["derived_facts"])
check("CTR gap vs peer computed (2.1% vs 3%)", "2.1%" in d01 and "3%" in d01, d01[:120])
check("lapsed share computed (78 of 540 = 14%)", "78 of 540" in d01 and "14%" in d01)
check("addressee: dentist -> 'Dr. Meera'; customer -> 'Priya'",
      composer.addressee(cats["dentists"], m1, None) == "Dr. Meera" and composer.addressee(cats["dentists"], m1, cuss["c_001_priya_for_m001"]) == "Priya")

# ---------------------------------------------------------------- prompt hygiene (no case-study wording)
blob = prompts.SYSTEM_PROMPT + " ".join(prompts.KIND_GUIDANCE.values())
banned = ["2,100-patient", "JIDA's Oct issue landed", "Dr. Meera, JIDA", "Apke liye 2 slots", "Sharma ji ki 3 monthly", "Saturday IPL matches"]
check("system prompt / guidance embed no case-study wording", not any(b.lower() in blob.lower() for b in banned))
check("every guidance key is a real trigger kind in the dataset", all(k in {t["kind"] for t in trgs.values()} for k in prompts.KIND_GUIDANCE))
missing = sorted({t["kind"] for t in trgs.values()} - set(prompts.KIND_GUIDANCE))
print(f"INFO  dataset kinds without specific guidance (use default): {missing}")

# ---------------------------------------------------------------- compose() wiring with a mocked LLM
calls = {"n": 0}
real_chat_json = llm.chat_json  # restored before the llm.chat_json failover test below


PRIYA_BODY = ("Hi Priya, Dr. Meera's clinic se: aapka 6-month cleaning recall due hai. Wed 5 Nov 6pm ya Thu 6 Nov 5pm "
              "mein se kaunsa slot theek rahega? Reply 1 ya 2.")
SURESH_BODY = ("Suresh, aaj DC vs MI ka match hai Arun Jaitley Stadium mein 7:30pm. Kya main aapke current offer ke saath "
               "ek match-night post draft kar dun?")


def fake_chat_json(messages, max_tokens=450, timeout=6.0):
    calls["n"] += 1
    return {"body": PRIYA_BODY, "cta": "multi_choice_slot", "rationale": "because"}, "groq"


llm.chat_json = fake_chat_json
composer.clear_cache()
cat, mer, trg, cus = inputs(by_id["T28"])
r1 = composer.compose(cat, mer, trg, cus)
check("compose returns exactly the 5 brief fields", set(r1) == {"body", "cta", "send_as", "suppression_key", "rationale"})
check("compose: send_as merchant_on_behalf for the customer trigger; suppression_key from trigger",
      r1["send_as"] == "merchant_on_behalf" and r1["suppression_key"] == trg["suppression_key"])
r2 = composer.compose(cat, mer, trg, cus)
check("determinism: same inputs -> identical output and only ONE llm call", r1 == r2 and calls["n"] == 1)
mer2 = json.loads(json.dumps(mer))
mer2["performance"]["views"] += 1
composer.compose(cat, mer2, trg, cus)
check("changed merchant context (new version) -> cache miss -> fresh compose", calls["n"] == 2)
llm.chat_json = lambda *a, **k: ({"body": SURESH_BODY, "cta": "weird value", "rationale": ""}, "groq")
composer.clear_cache()
d3 = composer.compose_detailed(*inputs(by_id["T21"]))
r3 = d3["message"]
check("unknown cta is mapped to a valid value; empty rationale gets a default",
      r3["cta"] in prompts.CTA_TYPES and r3["rationale"] != "" and r3["send_as"] == "vera")
check("the mocked LLM draft was accepted (source llm:groq, not the fallback)", d3["meta"]["source"] == "llm:groq", str(d3["meta"]))

# ---------------------------------------------------------------- llm.extract_json
check("extract_json: fenced json", llm.extract_json('```json\n{"a": 1}\n```') == {"a": 1})
check("extract_json: <think> block + trailing comma", llm.extract_json('<think>hmm {x}</think> {"a": 1, "b": [1,2,],}') == {"a": 1, "b": [1, 2]})
check("extract_json: garbage -> None", llm.extract_json("no json here") is None and llm.extract_json("") is None)


# ---------------------------------------------------------------- llm failover with mocked HTTP
class FakeResp:
    def __init__(self, status=200, content="OK", headers=None):
        self.status_code, self._content, self.headers, self.text = status, content, headers or {}, "err"

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def reset_llm(env_keys=("GROQ_API_KEY", "OPENROUTER_API_KEY")):
    llm._cooldown_until.clear()
    llm.last_errors.clear()
    for k in env_keys:
        os.environ[k] = "test-key-not-real"


seq = []


def make_post(script):
    def fake_post(url, headers=None, json=None, timeout=None):
        provider = "groq" if "groq" in url else "openrouter"
        seq.append(provider)
        outcome = script[provider]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    return fake_post


import requests  # noqa: E402

msgs = [{"role": "user", "content": "hi"}]
reset_llm()
seq.clear()
llm.requests.post = make_post({"groq": FakeResp(429, headers={"retry-after": "5"}), "openrouter": FakeResp(200, "from-or")})
text, prov = llm.chat(msgs)
check("failover: Groq 429 -> OpenRouter answers immediately", (text, prov) == ("from-or", "openrouter") and seq == ["groq", "openrouter"], str(seq))
seq.clear()
text, prov = llm.chat(msgs)
check("cooldown: next call skips the rate-limited Groq and goes straight to OpenRouter", prov == "openrouter" and seq == ["openrouter"], str(seq))

reset_llm()
seq.clear()
llm.requests.post = make_post({"groq": requests.exceptions.ReadTimeout("slow"), "openrouter": FakeResp(200, "or-ok")})
check("failover: Groq timeout -> OpenRouter", llm.chat(msgs)[1] == "openrouter")

reset_llm()
llm.requests.post = make_post({"groq": FakeResp(200, "groq-ok"), "openrouter": FakeResp(200, "or-ok")})
check("normal path: Groq is tried first and used", llm.chat(msgs) == ("groq-ok", "groq"))

reset_llm()
seq.clear()
llm.requests.post = make_post({"groq": FakeResp(500), "openrouter": FakeResp(401)})
try:
    llm.chat(msgs)
    check("both providers failing raises LLMUnavailable", False)
except llm.LLMUnavailable as exc:
    check("both providers failing raises LLMUnavailable (with diagnostics, no key leaked)", "test-key-not-real" not in str(exc) and "openrouter" in str(exc), str(exc)[:120])

reset_llm(env_keys=("OPENROUTER_API_KEY",))
os.environ.pop("GROQ_API_KEY", None)
seq.clear()
llm.requests.post = make_post({"groq": FakeResp(200, "no"), "openrouter": FakeResp(200, "only-or")})
check("only OpenRouter configured -> Groq is never called", llm.chat(msgs)[1] == "openrouter" and seq == ["openrouter"])

llm.chat_json = real_chat_json
reset_llm()
seq.clear()
llm.requests.post = make_post({"groq": FakeResp(200, "not json at all"), "openrouter": FakeResp(200, '{"ok": true}')})
obj, prov = llm.chat_json(msgs)
check("chat_json: Groq returns non-JSON -> retried on OpenRouter", obj == {"ok": True} and prov == "openrouter", str(seq))

# ---------------------------------------------------------------- total time budget across providers
import time as _time  # noqa: E402

reset_llm()
given = []


def slow_post(url, headers=None, json=None, timeout=None):
    given.append(timeout[1])
    _time.sleep(timeout[1])            # behave like a provider that never answers within its timeout
    raise requests.exceptions.ReadTimeout("slow")


llm.requests.post = slow_post
t0 = _time.time()
try:
    llm.chat(msgs, timeout=2.0)
except llm.LLMUnavailable:
    pass
elapsed = _time.time() - t0
check("budget: two slow providers together stay inside the total timeout (not 2x)", elapsed < 2.4, f"{elapsed:.2f}s for timeout=2.0")
check("budget: the first provider gets <=60% so the fallback provider still has real time", len(given) == 2 and given[0] <= 1.3 and given[1] >= 0.6, str([round(g, 2) for g in given]))

# ---------------------------------------------------------------- no keys at all
llm._cooldown_until.clear()
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)
try:
    llm.chat(msgs)
    check("no key configured raises LLMUnavailable", False)
except llm.LLMUnavailable:
    check("no key configured raises LLMUnavailable", True)

print("\nRESULT:", "ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
