"""Step 4 verification (offline): validator rules, deterministic fallback for ALL 100 triggers, retry/fallback flow.

Run from E:\\MAGICPIN:  python tests/verify_step4_validator.py
"""
import glob
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)

import composer  # noqa: E402
import fallback  # noqa: E402
import llm  # noqa: E402
import validator  # noqa: E402
from references import REFERENCE_BODIES  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def load(pattern, key):
    return {json.load(open(f, encoding="utf-8"))[key]: json.load(open(f, encoding="utf-8")) for f in glob.glob(str(ROOT / "expanded" / pattern))}


cats, mers = load("categories/*.json", "slug"), load("merchants/*.json", "merchant_id")
cuss, trgs = load("customers/*.json", "customer_id"), load("triggers/*.json", "id")
pairs = json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]
by_id = {p["test_id"]: p for p in pairs}


def inputs(test_id):
    p = by_id[test_id]
    m = mers[p["merchant_id"]]
    return cats[m["category_slug"]], m, trgs[p["trigger_id"]], cuss.get(p["customer_id"]) if p["customer_id"] else None


def ctx_for(test_id):
    return composer.build_context(*inputs(test_id))


def v(test_id, body, cta="binary_yes_no", prev=()):
    cat, _, _, _ = inputs(test_id)
    return validator.validate(body, cta, ctx_for(test_id), cat, prev)


# ================================================================ A. validator rules
r = v("T24", "See https://magicpin.com/blog for details on your calls. Want me to send the summary over?")
check("URL (https) is a hard issue", any(i.startswith("url_in_body") for i in r.hard))
r = v("T24", "Bharat, read more at magicpin.com about your calls dropping this week. Want me to send it?")
check("bare domain is a hard issue", any(i.startswith("url_in_body") for i in r.hard))
r = v("T24", "Bharat, this treatment gives guaranteed results for your patients this week. Want me to draft a post?")
check("category taboo word 'guaranteed' (dentists) is a hard issue", any("taboo_phrase 'guaranteed'" in i for i in r.hard))

r = v("T24", "Bharat, your stale_posts:22d and delta_pct are the reason for the dip. Want me to look into it today?")
check("internal jargon (snake_case field names) is a hard issue (judge_simulator.py:477: -1)", any(i.startswith("internal_jargon") for i in r.hard), str(r.hard))
r = v("T24", "Bharat, the payload shows a placeholder trigger for your calls this week. Want me to look into it today?")
check("system words (payload, placeholder) are a hard issue", any(i.startswith("internal_jargon") for i in r.hard))
r = v("T24", "Bharat, aapke ready-to-post updates aur 3-month plan ke saath calls ka ek quick review karein? Batao kab karein.")
check("normal hyphenated prose is not mistaken for jargon", not any(i.startswith("internal_jargon") for i in r.hard), str(r.hard))

r = v("T24", "Bharat, your calls are down 47% this week and 190 people searched for you yesterday. Want me to fix it?")
check("fabricated numbers (190, 47%) are a hard issue", any(i.startswith("ungrounded_numbers") and "190" in i and "47" in i for i in r.hard), str(r.hard))
r = v("T24", "Bharat, your calls dropped 50% over 7d against a baseline of 12; CTR is 1.8% vs 3% for peers. Want me to look into it?")
check("grounded numbers pass (fraction -0.5 -> 50%, baseline 12, CTR 1.8% vs 3%)", not r.hard, str(r.hard))
r = v("T24", "Bharat, I can prepare 2 drafts in 10 minutes and about 90 seconds of review time. Want them?")
check("small counts and effort durations are allowed (2 drafts, 10 minutes, 90 seconds)", not r.hard, str(r.hard))
r = v("T24", "Bharat, your listing got 5000 extra views last month according to our data. Want me to look?")
check("large invented counts are caught (5000)", any("5000" in i for i in r.hard))

r = v("T24", "Want the abstract? Want the draft? Want both today? Tell me which one now.")
check("three questions = multiple asks (hard)", any(i.startswith("multiple_asks") for i in r.hard))
r = v("T24", "Reply YES for the report. Reply NO to skip it. Reply MAYBE to hear more about it later.")
check("three 'reply' instructions = multiple asks (hard)", any(i.startswith("multiple_asks") for i in r.hard))
r = v("T28", "Reply 1 for Wed, reply 2 for Thu, or reply with a time that suits you better.", cta="multi_choice_slot")
check("multi_choice_slot may use several 'reply' words", not any(i.startswith("multiple_asks") for i in r.hard))

r = v("T24", "Bharat, your calls are down 50% over 7 days against a baseline of 12. That is a real dip worth a look now.")
check("ask not in the last sentence is a soft cta_placement issue", any(i.startswith("cta_placement") for i in r.soft), str(r.soft))
r = v("T24", "Bharat, your calls are down 50% over 7 days against a baseline of 12. That is a real dip worth a look now.", cta="none")
check("cta 'none' is not checked for placement", not any(i.startswith("cta_placement") for i in r.soft))

r = v("T24", "Bharat, your calls are down 50% over 7 days against a baseline of 12. Want me to look into what changed?")
check("English body for a Hinglish merchant is a soft language issue", any(i.startswith("language") for i in r.soft), str(r.soft))
r = v("T24", "Bharat, aapke calls pichhle 7 din mein 50% neeche hain, baseline 12 tha. Kya main dekh kar ek fix suggest kar dun?")
check("Hinglish body for a Hinglish merchant is clean", not r.soft and not r.hard, str(r.soft + r.hard))
r = v("T24", "Bharat, आपके calls पिछले 7 दिन में 50% कम हुए हैं. Kya main ek fix suggest kar dun?")
check("Devanagari is a soft issue (Roman script required)", any("Devanagari" in i for i in r.soft))
r = v("T04", "Hi Riya, Karim's Salon here. Your appointment is tomorrow. Please reply YES to confirm your visit.")
check("English body for a 'hi' customer (needs 4 Hindi markers) is a soft language issue", any(i.startswith("language") for i in r.soft), str(r.soft))
r = v("T04", "Hi Riya, salon se yaad dila rahe hain ki kal aapka appointment hai. Confirm karne ke liye YES reply kijiye.")
check("Roman-Hindi body for a 'hi' customer is clean", not r.soft and not r.hard, str(r.soft + r.hard))

r = v("T24", "I hope you are doing well. Bharat, your calls are down 50% over 7 days. Want me to look into it?")
check("preamble ('I hope you are doing well') is a soft issue", any(i.startswith("preamble") for i in r.soft))
r = v("T24", "Hi?")
check("too-short body is hard", "empty_or_too_short_body" in r.hard)

prev = "Bharat, your calls are down 50% over 7 days against a baseline of 12. Want me to look into what changed?"
r = v("T24", prev + " ", prev=[prev])
check("verbatim repeat of a previous message is hard", "repeats_previous_message" in r.hard)
r = v("T24", "Bharat, calls fell 50% in the last 7 days (baseline 12). Should I check what changed and propose one fix?", prev=[prev])
check("a genuinely different message is not a repeat", "repeats_previous_message" not in r.hard, str(r.hard))

check("similarity guard flags every reference message verbatim", all(validator.copies_reference(b) for b in REFERENCE_BODIES))
near = REFERENCE_BODIES[1].replace("Priya", "Riya")
check("similarity guard flags a near-copy (one word changed)", validator.copies_reference(near))
para = ("Dr. Meera, a new study reported in JIDA (Oct 2026, p.14) followed 2,100 high-risk adults: recalling every "
        "3 months with fluoride varnish cut caries recurrence by 38% compared with 6-monthly visits. Should I "
        "draft a short note for your patients?")
check("an honest paraphrase of the same facts is NOT flagged as a copy", not validator.copies_reference(para))
check("ctx-based allowed numbers include the digest facts (2100, 38, 14)",
      {"2100", "38", "14"} <= validator.allowed_numbers(composer.build_context(cats["dentists"], mers["m_001_drmeera_dentist_delhi"],
                                                                                trgs["trg_001_research_digest_dentists"], None)))

# ================================================================ B. fallback for ALL 100 triggers
hard_bad, soft_counter, sample = [], Counter(), {}
for t in trgs.values():
    m = mers[t["merchant_id"]]
    cat = cats[m["category_slug"]]
    cus = cuss.get(t["customer_id"]) if t["customer_id"] else None
    ctx = composer.build_context(cat, m, t, cus)
    fb = fallback.build(cat, m, t, cus, ctx, composer.addressee(cat, m, cus))
    res = validator.validate(fb["body"], fb["cta"], ctx, cat, [])
    if not fb["body"].strip() or res.hard:
        hard_bad.append((t["id"], t["kind"], fb["body"][:90], res.hard))
    for s in res.soft:
        soft_counter[s.split(" ")[0]] += 1
    sample.setdefault(t["kind"], fb["body"])
check("fallback builds a non-empty, hard-rule-clean message for all 100 triggers", not hard_bad, str(hard_bad[:3]))
print("INFO  soft issues over 100 fallbacks:", dict(soft_counter))
check("fallback covers every trigger kind", len(sample) == 26)
check("no template placeholders leak into any fallback body", not any(("None" in b or "{" in b or "nan" in b.split()) for b in sample.values()))
print("INFO  sample fallbacks:")
for k in ("recall_due", "perf_dip", "competitor_opened"):
    print(f"      [{k}] {sample[k]}")

# ================================================================ C. compose_detailed flow with a mocked LLM
GOOD = ("Bharat, aapke calls pichhle 7 din mein 50% neeche hain (baseline 12). Kya main dekh kar ek fix suggest kar dun?")
BAD_NUMBERS = "Bharat, aapke calls 47% neeche hain aur 190 log search kar rahe the. Kya main dekh kar ek fix suggest kar dun?"
ENGLISH_ONLY = "Bharat, your calls are down 50% over 7 days against a baseline of 12. Want me to look into what changed?"
calls = {"n": 0, "messages": []}


def script(*outputs, delay=0.0):
    """Mock llm.chat_json: return the given bodies in order (last one repeats); an Exception is raised."""
    calls["n"], calls["messages"] = 0, []

    def fake(messages, max_tokens=450, timeout=6.0):
        i = min(calls["n"], len(outputs) - 1)
        calls["n"] += 1
        calls["messages"].append(messages)
        if delay:
            time.sleep(delay)
        out = outputs[i]
        if isinstance(out, Exception):
            raise out
        return {"body": out, "cta": "binary_yes_no", "rationale": "test"}, "groq"
    llm.chat_json = fake


composer.clear_cache()
script(BAD_NUMBERS, GOOD)
d = composer.compose_detailed(*inputs("T24"))
check("retry: fabricated numbers rejected, second draft accepted", d["message"]["body"] == GOOD and calls["n"] == 2 and d["meta"]["source"] == "llm:groq")
check("retry prompt carries the validator feedback", "rejected for: ungrounded_numbers" in calls["messages"][1][1]["content"])
check("issues are recorded in meta", any("ungrounded_numbers" in i for i in d["meta"]["issues"]))

composer.clear_cache()
script(BAD_NUMBERS)
d = composer.compose_detailed(*inputs("T24"))
check("two bad drafts -> deterministic fallback used", d["meta"]["source"] == "fallback" and d["message"]["body"] and calls["n"] == 2)
before = calls["n"]
d2 = composer.compose_detailed(*inputs("T24"))
check("fallback after validation failure is cached (deterministic, no new LLM calls)", d2["message"] == d["message"] and calls["n"] == before)

composer.clear_cache()
script(llm.LLMUnavailable("providers down"))
d = composer.compose_detailed(*inputs("T24"))
check("LLM unavailable -> fallback, message still valid", d["meta"]["source"] == "fallback" and len(d["message"]["body"].split()) >= 6)
script(GOOD)
d2 = composer.compose_detailed(*inputs("T24"))
check("outage result is NOT cached: once the LLM is back the LLM message is used", d2["meta"]["source"] == "llm:groq" and d2["message"]["body"] == GOOD)

composer.clear_cache()
script(ENGLISH_ONLY)
d = composer.compose_detailed(*inputs("T24"))
check("soft-only issue (language): retried once, then the LLM draft is kept (not thrown away)",
      d["meta"]["source"] == "llm:groq" and calls["n"] == 2 and d["message"]["body"] == ENGLISH_ONLY)

composer.clear_cache()
script(BAD_NUMBERS, delay=0.7)
t0 = time.time()
d = composer.compose_detailed(*inputs("T24"), timeout=1.2)
check("time budget: slow first draft leaves no time for a retry -> fallback, no overrun",
      calls["n"] == 1 and d["meta"]["source"] == "fallback" and time.time() - t0 < 1.6, f"calls={calls['n']} {time.time() - t0:.2f}s")

composer.clear_cache()
hist_body = mers["m_001_drmeera_dentist_delhi"]["conversation_history"][0]["body"]
script(hist_body, "Dr. Meera, aapke 78 lapsed patients ke liye ek recall reminder ready hai. Kya main draft bhej dun?")
cat, m1, t1, _ = cats["dentists"], mers["m_001_drmeera_dentist_delhi"], trgs["trg_001_research_digest_dentists"], None
d = composer.compose_detailed(cat, m1, t1, None)
check("a draft identical to Vera's earlier message in conversation_history is rejected as a repeat",
      any("repeats_previous_message" in i for i in d["meta"]["issues"]) and d["message"]["body"] != hist_body)

check("compose() still returns exactly the 5 fields", set(composer.compose(*inputs("T24"))) == {"body", "cta", "send_as", "suppression_key", "rationale"})

print("\nRESULT:", "ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
