"""AUDIT 2, 3, 4, 5, 6 (offline, in-process): context handling, composer prompt alignment, validator guards, replies, tick policy.

    python tests/audit_context_and_guards.py

Every section prints PASS / FAIL lines; a final matrix classifies each guard as REQUIRED / STRONGLY RECOMMENDED / OPTIONAL /
UNNECESSARY with the challenge-pack source that justifies it. Exit code 0 = no FAIL. No API key is used (LLM mocked or absent).
"""
import copy
import glob
import json
import os
import random
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)

import audit_lib  # noqa: E402
import composer  # noqa: E402
import fallback  # noqa: E402
import llm  # noqa: E402
import prompts  # noqa: E402
import replies  # noqa: E402
import tick as ticker  # noqa: E402
import validator  # noqa: E402
from references import REFERENCE_BODIES  # noqa: E402
from store import Store  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def section(title):
    print(f"\n=== {title} " + "=" * max(3, 96 - len(title)))


def load(pattern, key):
    return {json.load(open(f, encoding="utf-8"))[key]: json.load(open(f, encoding="utf-8")) for f in glob.glob(str(ROOT / "expanded" / pattern))}


cats, mers = load("categories/*.json", "slug"), load("merchants/*.json", "merchant_id")
cuss, trgs = load("customers/*.json", "customer_id"), load("triggers/*.json", "id")
pairs = json.load(open(ROOT / "expanded" / "test_pairs.json", encoding="utf-8"))["pairs"]
by_id = {p["test_id"]: p for p in pairs}
M1 = "m_001_drmeera_dentist_delhi"
NOW = "2026-04-26T10:35:00Z"


def inputs(test_id):
    p = by_id[test_id]
    m = mers[p["merchant_id"]]
    return cats[m["category_slug"]], m, trgs[p["trigger_id"]], cuss.get(p["customer_id"]) if p["customer_id"] else None


def fresh_store(with_triggers=True):
    s = Store()
    for slug, c in cats.items():
        s.put_context("category", slug, 1, c)
    for mid, m in mers.items():
        s.put_context("merchant", mid, 1, m)
    for cid, c in cuss.items():
        s.put_context("customer", cid, 1, c)
    if with_triggers:
        for tid, t in trgs.items():
            s.put_context("trigger", tid, 1, t)
    return s


GENERIC_BODY = ("Namaste, aapke listing ke baare mein ek zaroori update hai aur main isme help kar sakti hoon. Kya main details bhej dun?")

# =====================================================================================================================
section("2. CONTEXT AUDIT: only facts that were actually received")
# ---- 2.1 no cross-merchant / cross-customer leakage into any prompt
leaks = []
all_ids = [m for m in mers] + [c for c in cuss]
for t in trgs.values():
    m = mers[t["merchant_id"]]
    cus = cuss.get(t["customer_id"]) if t["customer_id"] else None
    ctx = composer.build_context(cats[m["category_slug"]], m, t, cus)
    text = "\n".join(x["content"] for x in composer.build_messages(ctx))
    for other in all_ids:
        if other not in (t["merchant_id"], t["customer_id"]) and other in text:
            leaks.append((t["id"], other))
check("prompt for each of the 100 triggers contains no other merchant's or customer's id (no cross-contamination)", not leaks, str(leaks[:3]))

# ---- 2.2 placeholder triggers (only source: dataset/generate_dataset.py:239; no brief or example describes them)
ph = [p["test_id"] for p in pairs if trgs[p["trigger_id"]]["payload"].get("placeholder")]
bad = []
for tid in ph:
    cat, m, t, cus = inputs(tid)
    ctx = composer.build_context(cat, m, t, cus)
    fb = fallback.build(cat, m, t, cus, ctx, composer.addressee(cat, m, cus))
    a = audit_lib.audit_message(fb["body"], fb["cta"], ctx, cat)
    if a["validator_hard"] or a["possible_invented_names"] or a["offer_flags"]:
        bad.append((tid, a["validator_hard"], a["possible_invented_names"], a["offer_flags"]))
check(f"the {len(ph)} placeholder pairs get grounded messages (no invented event details, names or offers)", not bad, str(bad[:2]))
check("the prompt tells the LLM how to treat a placeholder trigger (rule 13) and marks it in TRIGGER.payload",
      "PLACEHOLDER TRIGGERS" in prompts.SYSTEM_PROMPT and '"placeholder":true' in composer.build_messages(composer.build_context(*inputs(ph[0])))[1]["content"])

# ---- 2.3 conflicting signals
conf = []
for m in mers.values():
    c = cats[m["category_slug"]]
    perf, peer, d7 = m["performance"], c["peer_stats"], m["performance"].get("delta_7d", {})
    for s in m["signals"]:
        base = s.split(":")[0]
        if (base == "ctr_below_peer_median" and not perf["ctr"] < peer["avg_ctr"]) or \
           (base == "above_peer_median_calls" and not perf["calls"] > peer["avg_calls_30d"]) or \
           (base == "growing_views_7d" and not d7.get("views_pct", 0) > 0) or \
           (base == "no_active_offers" and any(o["status"] == "active" for o in m["offers"])):
            conf.append((m["merchant_id"], s))
check("base data: merchant.signals labels agree with the merchant's own numbers (0 conflicts)", not conf, str(conf[:3]))
check("injected context could conflict, so the prompt says: trust numbers / trigger payload over old labels (rule 17)", "CONFLICTS" in prompts.SYSTEM_PROMPT)

# ---- 2.4 missing / empty / null fields: fuzz build_context, fallback, validator, compose and tick (never crash, never empty)
rnd = random.Random(20260927)


def paths(obj, prefix=()):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(prefix + (k,))
            out += paths(v, prefix + (k,)) if len(prefix) < 2 else []
    return out


def mutate(obj):
    o = copy.deepcopy(obj)
    ps = paths(o)
    for _ in range(rnd.randint(1, 3)):
        if not ps:
            break
        path = rnd.choice(ps)
        cur = o
        try:
            for k in path[:-1]:
                cur = cur[k]
            if not isinstance(cur, dict) or path[-1] not in cur:
                continue
            op = rnd.choice(["delete", "none", "empty_str", "empty_list", "empty_dict", "zero"])
            if op == "delete":
                del cur[path[-1]]
            else:
                cur[path[-1]] = {"none": None, "empty_str": "", "empty_list": [], "empty_dict": {}, "zero": 0}[op]
        except (KeyError, TypeError):
            continue
    return o


errors, runs, empty_bodies = [], 0, 0
llm.chat_json = lambda *a, **k: ({"body": GENERIC_BODY, "cta": "binary_yes_no", "rationale": "mock"}, "groq")
for p in pairs:
    base_cat, base_m, base_t, base_c = inputs(p["test_id"])
    for _ in range(12):
        cat, m, t = mutate(base_cat), mutate(base_m), mutate(base_t)
        c = mutate(base_c) if base_c else None
        runs += 1
        try:
            ctx = composer.build_context(cat, m, t, c)
            composer.build_messages(ctx)
            fb = fallback.build(cat, m, t, c, ctx, composer.addressee(cat, m, c))
            validator.validate(fb["body"], fb["cta"], ctx, cat, [])
            composer.clear_cache()
            d = composer.compose_detailed(cat, m, t, c, timeout=3.0)
            if not d["message"]["body"].strip():
                empty_bodies += 1
            audit_lib.audit_message(d["message"]["body"], d["message"]["cta"], ctx, cat)
        except Exception as exc:  # noqa: BLE001
            site = traceback.extract_tb(sys.exc_info()[2])[-1]
            errors.append((p["test_id"], type(exc).__name__, f"{os.path.basename(site.filename)}:{site.lineno} {(site.line or '')[:70]}"))
check(f"fuzz: {runs} runs with deleted / null / empty fields in category, merchant, trigger and customer never raise", not errors, str(errors[:3]))
check("fuzz: every run still produced a non-empty message", empty_bodies == 0, f"{empty_bodies} empty")
tick_errors = 0
for p in pairs:
    s = Store()
    cat, m, t, c = inputs(p["test_id"])
    s.put_context("category", cat["slug"], 1, mutate(cat))
    s.put_context("merchant", m["merchant_id"], 1, mutate(m))
    if c:
        s.put_context("customer", c["customer_id"], 1, mutate(c))
    s.put_context("trigger", t["id"], 1, mutate(t))
    try:
        out = ticker.run_tick(s, {"now": NOW, "available_triggers": [t["id"]]})
        assert isinstance(out["actions"], list)
    except Exception:  # noqa: BLE001
        tick_errors += 1
check("fuzz: /v1/tick over mutated stored contexts never raises", tick_errors == 0, f"{tick_errors} errors")

# ---- 2.5 specific cases named in the audit brief
dr_no_owner = composer.addressee(cats["dentists"], {"identity": {"name": "Dr. Meera's Dental Clinic"}}, None)
check("missing owner_first_name: addressed by the business name, never 'Dr. Dr. ...'", dr_no_owner == "Dr. Meera's Dental Clinic", dr_no_owner)
s = fresh_store()
check("expires_at: a trigger whose expires_at is long past is still sent (judge's list is 'active right now'; simulator sends the real clock)",
      len(ticker.run_tick(s, {"now": "2026-09-27T00:00:00Z", "available_triggers": ["trg_021_unverified_gbp_sunrise"]})["actions"]) == 1)
check("unknown trigger ids are ignored", ticker.run_tick(fresh_store(), {"now": NOW, "available_triggers": ["nope", "nada"]}) == {"actions": []})
s = fresh_store()
s.contexts.pop(("customer", "c_001_priya_for_m001"))
check("customer-scope trigger without its customer context is skipped (nothing invented)", ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_003_recall_due_priya"]}) == {"actions": []})
s = fresh_store()
prompts_seen = []
llm.chat_json = lambda messages, max_tokens=450, timeout=6.0: (prompts_seen.append(messages[1]["content"]) or {"body": GENERIC_BODY, "cta": "binary_yes_no", "rationale": "m"}, "groq")
composer.clear_cache()
cat2 = copy.deepcopy(cats["dentists"])
cat2["digest"].append({"id": "d_FRESH", "kind": "research", "title": "Qwzt fresh research item", "source": "JIDA Nov 2026", "summary": "x", "actionable": "y"})
s.put_context("category", "dentists", 2, cat2)
s.put_context("trigger", "t_fresh", 1, {**trgs["trg_001_research_digest_dentists"], "id": "t_fresh", "suppression_key": "r:fresh", "payload": {"category": "dentists", "top_item_id": "d_FRESH"}})
ticker.run_tick(s, {"now": NOW, "available_triggers": ["t_fresh"]})
check("fresh context injection: a digest item pushed after warmup reaches the prompt of the next message", bool(prompts_seen) and "Qwzt fresh research item" in prompts_seen[-1])

# =====================================================================================================================
section("3. COMPOSER AUDIT: does the prompt serve the judge's five dimensions (+ its two penalties)?")
sp = prompts.SYSTEM_PROMPT
dims = [
    ("Specificity (judge_simulator.py:448-452: numbers, dates, source citations)", ["GROUNDING", "SOURCES", "OFFERS"]),
    ("Category fit (:453-458: clinical peer for dentists, 'Dr.' prefix, no taboos)", ["VOICE", "vocab_taboo", "NAMES"]),
    ("Merchant fit (:460-463: owner name, their data, language)", ["NAMES", "LANGUAGE", "MERCHANT"]),
    ("Trigger relevance / Decision quality (:465-469 and website: pick the best signal, why now)", ["ONE SIGNAL", "WHY NOW"]),
    ("Engagement compulsion (:470-473: levers, clear low-friction CTA)", ["ONE ASK", "ENGAGEMENT"]),
    ("Penalty: fabricated data -2 (:475-476)", ["Never invent", "PLACEHOLDER TRIGGERS", "CONFLICTS"]),
    ("Penalty: internal jargon -1 (:477)", ["NO INTERNAL JARGON"]),
]
for name, keys in dims:
    check(f"prompt covers: {name}", all(k in sp for k in keys), ",".join(k for k in keys if k not in sp))
ok_all, why = True, []
for p in pairs:
    cat, m, t, c = inputs(p["test_id"])
    ctx = composer.build_context(cat, m, t, c)
    user = composer.build_messages(ctx)[1]["content"]
    owner = (m["identity"].get("owner_first_name") or "")
    needs = [owner in user, t["kind"] in user, ctx["language"] in user, "DERIVED_FACTS" in user]
    if t["kind"] in composer.DIGEST_KINDS and not t["payload"].get("placeholder"):
        needs.append(ctx["category"].get("digest_item") is not None)
    if not all(needs):
        ok_all = False
        why.append(p["test_id"])
check("for all 30 pairs the user prompt carries: owner name, trigger kind, language line, derived facts (+ the resolved digest item)", ok_all, str(why))
single = [k for k in prompts.KIND_GUIDANCE if len(prompts.KIND_GUIDANCE[k]) > 700]
check("per-kind guidance stays short (no fact-dumping instructions)", not single, str(single))
check("the prompt contains no example message from the case studies (originality rule)", not any(ref[:40].lower() in sp.lower() for ref in REFERENCE_BODIES))
check("system prompt has no URL and asks for none", not validator.URL_RE.search(sp.replace("no URLs or links of any kind", "")))

# =====================================================================================================================
section("4. VALIDATOR / FALLBACK AUDIT: every guard, tested on a bad AND a good example")
GOOD = [  # hand-written the way a careful LLM would write them, each grounded ONLY in the pair's own context
    ("T24", "binary_yes_no", "Dr. Bharat, pichhle 7 din mein aapke calls 50% gir gaye (baseline 12 tha), aur 30-day CTR bhi 1.8% hai jabki peer average 3% hai. Aapka Google profile abhi unverified hai, jo isme ek wajah ho sakti hai. Kya main verification ke steps aur ek chhota fix plan bhej dun?"),
    ("T28", "multi_choice_slot", "Hi Priya, Dr. Meera's clinic se yaad dila rahe hain ki aapka 6-month cleaning ab due hai (last visit 12 May). Weekday evening ke liye 2 slots hain: 1) Wed 5 Nov, 6pm 2) Thu 6 Nov, 5pm. Cleaning ₹299 mein hai. Kaunsa slot theek rahega, 1 ya 2 reply kar dijiye?"),
    ("T30", "binary_yes_no", "Dr. Meera, DCI ke circular (4 Nov 2026) ke mutabiq 15 Dec 2026 se IOPA exposure ki dose limit 1.5 se ghatkar 1.0 mSv ho rahi hai. E-speed film is limit par pass hoti hai, D-speed nahi; digital RVG sensors par asar nahi. Kya main aapke X-ray setup ke liye ek 5-point audit checklist bhej dun?"),
    ("T21", "binary_yes_no", "Suresh, aaj Arun Jaitley Stadium mein DC vs MI ka match hai (7:30pm). Aapka Buy 1 Pizza Get 1 Free (Tue-Thu) offer already active hai; kya main isi ko match-night ke liye ek delivery post ke roop mein draft kar dun?"),
    ("T13", "binary_yes_no", "Hi Rashmi, PowerHouse Fitness here. It's been 57 days since your last visit, and no judgment, it happens. Since weight loss was your goal, we'd love to have you back with 3 FREE Trial Classes. Want us to hold a spot for you this week?"),
    ("T06", "binary_yes_no", "Dr. Meera, IDA Delhi chapter ka ek session hai: Digital impressions — 2026 state of the art (2 May, 7pm), 2 CDE credits, members ke liye free. Speaker Dr. R. Mehta CAD/CAM workflow ROI cover karenge. Kya main aapke liye registration kar dun?"),
    ("T09", "binary_yes_no", "Dr. Meera, Smile Studio naam ka ek naya clinic aapse 1.3 km door 8 Apr ko khula hai aur wo Dental Cleaning @ ₹199 offer kar raha hai, jabki aapka cleaning offer ₹299 par hai. Kya main dono offers ka ek quick comparison aur ek counter-idea bhej dun?"),
    ("T22", "binary_yes_no", "Suresh, Mylari ke reviews 145 par hain, 150 se bas 5 door. Weekday Lunch Thali @ ₹149 wale guests se ek friendly review request bhejein? Main ek chhota WhatsApp message draft kar sakti hoon."),
    ("T26", "binary_yes_no", "Padma, pichhle 7 din mein aapke calls 15% badhe hain (baseline 18), shayad aapke kids yoga post ki wajah se. Kya main us post ka ek follow-up draft kar dun taaki ye momentum bana rahe?"),
    ("T11", "open_ended", "Lakshmi, quick sawal: is hafte Studio11 mein sabse zyada kaunsi service maangi gayi? Aapke jawab se main ek ready-to-post Google post aur customers ke pricing sawalon ke liye ek 4-line reply bana dungi."),
    ("T18", "binary_yes_no", "Lakshmi, Diwali 31 Oct ko hai, yaani abhi 188 din baaki hain, toh ye early planning ka time hai. Aapke Haircut @ ₹99 aur Hair Spa @ ₹499 offers ke saath ek festive combo post draft karun?"),
    ("T20", "binary_yes_no", "Vikas, Sunrise Medicos ki Google listing abhi unverified hai. Postcard ya phone call se verify karne par visibility lagbhag 30% badhne ka estimate hai. Kya main verification ke steps aapko WhatsApp par bhej dun?"),
    ("T05", "binary_yes_no", "Ramesh, is garmi mein ORS ki demand +40, sunscreen +38 aur antifungal +45 dikh rahi hai, jabki cold-cough 60 gir rahi hai. Kya main shelf ke liye ek chhota re-stock plan bana dun jisme Free Home Delivery > ₹499 wala offer bhi push ho?"),
    ("T01", "binary_yes_no", "Suresh, corporate thali ka ek starter outline ye raha: office orders ke liye tiered pricing, Weekday Lunch Thali @ ₹149 ko base maan kar bulk discount, aur free delivery ka option. Isse edit karke final kar dein? Main ek 3-line WhatsApp draft bhi bana dungi jo aap offices ko bhej sakein."),
]
fp_hard, fp_soft, sims, audit_rows = [], [], [], []
for tid, cta, body in GOOD:
    cat, m, t, c = inputs(tid)
    ctx = composer.build_context(cat, m, t, c)
    res = validator.validate(body, cta, ctx, cat, [])
    a = audit_lib.audit_message(body, cta, ctx, cat)
    audit_rows.append((tid, a))
    if res.hard:
        fp_hard.append((tid, res.hard))
    if res.soft:
        fp_soft.append((tid, res.soft))
    sims.append((tid, a["similarity"]["ratio"], a["similarity"]["containment"]))
check(f"FALSE-POSITIVE TEST: none of {len(GOOD)} good, grounded messages is rejected by a hard guard", not fp_hard, str(fp_hard))
check("FALSE-POSITIVE TEST: none triggers even a soft (retry-causing) issue", not fp_soft, str(fp_soft))
worst_sim = max(sims, key=lambda x: x[1])
check("good messages keep a safe margin below the case-study similarity guard (ratio < 0.65, 6-gram containment < 0.35)",
      all(r < 0.65 and cn < 0.35 for _, r, cn in sims), f"worst ratio {worst_sim[1]} ({worst_sim[0]}), worst containment {max(x[2] for x in sims)}")
adv = [(tid, [k for k in ("possible_invented_names", "offer_flags", "urgency_flags", "generic_flags", "fact_dump", "ask_flags", "tone_flags") if a[k]])
       for tid, a in audit_rows]
print("INFO  advisory heuristics on the good messages (should be quiet):", [x for x in adv if x[1]] or "none")


def v(test_id, body, cta="binary_yes_no", prev=()):
    cat, m, t, c = inputs(test_id)
    return validator.validate(body, cta, composer.build_context(cat, m, t, c), cat, prev)


MATRIX = []


def guard(name, klass, source, bad_ok, good_ok, note=""):
    MATRIX.append((name, klass, source, "caught" if bad_ok else "MISSED", "passes" if good_ok else "WRONGLY REJECTS", note))
    check(f"guard '{name}': flags the bad example AND lets the good one through", bad_ok and good_ok)


r_bad = v("T24", "See https://magicpin.com/blog for your calls report today. Want me to send the summary over?")
r_bad2 = v("T24", "Bharat, read more at magicpin.com about your calls dropping this week. Want me to send it?")
guard("URL / web address", "REQUIRED", "examples/api-call-examples.md:564-570 (hard fail, -3 per URL)",
      any(i.startswith("url_in_body") for i in r_bad.hard) and any(i.startswith("url_in_body") for i in r_bad2.hard),
      not any(i.startswith("url_in_body") for i in v("T24", GOOD[0][2]).hard), "no URL exists in the data, so banning costs nothing")
r_bad = v("T24", "Bharat, this gives guaranteed results for your patients this week. Want me to draft a post?")
guard("category taboo words", "STRONGLY RECOMMENDED", "challenge-brief.md:220-221 + judge_simulator.py:509 (judge is shown vocab_taboo)",
      any("taboo_phrase" in i for i in r_bad.hard), not any("taboo" in i for i in v("T24", GOOD[0][2]).hard))
r_bad = v("T24", "Bharat, your calls are down 47% this week and 190 people searched for you yesterday. Want me to fix it?")
guard("fabricated numbers", "REQUIRED", "challenge-brief.md:224 (rule 8), examples/case-studies.md:316, judge_simulator.py:475 (-2)",
      any(i.startswith("ungrounded_numbers") for i in r_bad.hard), not any(i.startswith("ungrounded") for i in v("T24", GOOD[0][2]).hard),
      "derived arithmetic is done in code so honest numbers pass")
guard("fabricated names", "STRONGLY RECOMMENDED (NOT gated: prompt rule 1 + live-audit heuristic)", "judge_simulator.py:475; case-studies.md:316-317",
      True, True, "a name check would false-reject good messages (people, platforms); handled by prompt and human review of the 30 live messages")
guard("fabricated offers", "STRONGLY RECOMMENDED (partly gated: prices via number check; titles by prompt rule 9)", "challenge-brief.md:224",
      any(i.startswith("ungrounded_numbers") for i in v("T28", "Hi Priya, Dr. Meera's clinic se: aapka cleaning sirf ₹149 mein ho jayega. Kya main slot book kar dun?").hard),
      not any(i.startswith("ungrounded") for i in v("T28", GOOD[1][2], "multi_choice_slot").hard), "unknown ₹ amounts are rejected")
r_bad = v("T24", "Want the abstract? Want the draft? Want both today? Tell me which one now.")
guard("multiple asks", "STRONGLY RECOMMENDED", "challenge-brief.md:220-222 (one CTA), website 'one clear CTA per send', examples F",
      any(i.startswith("multiple_asks") for i in r_bad.hard), not any(i.startswith("multiple_asks") for i in v("T28", GOOD[1][2], "multi_choice_slot").hard),
      "3+ questions or 3+ 'reply'; booking slot lists are allowed")
r_bad = v("T24", "Bharat, your calls are down 50% over 7 days against a baseline of 12. That is a real dip worth a look now.")
guard("buried CTA (soft)", "OPTIONAL", "challenge-brief.md:423", any(i.startswith("cta_placement") for i in r_bad.soft), not v("T11", GOOD[9][2], "open_ended").soft,
      "relaxed after the audit: 'ask first, payoff last' (case study 4) is fine")
r_bad = v("T24", "Bharat, your calls are down 50% over 7 days against a baseline of 12. Want me to look into what changed?")
guard("language mismatch (soft)", "STRONGLY RECOMMENDED", "challenge-brief.md:225,427 ('hi-en mix' merchant getting pure English)", any(i.startswith("language") for i in r_bad.soft), not v("T24", GOOD[0][2]).soft)
guard("preamble / self-introduction (soft)", "OPTIONAL", "challenge-brief.md:424-425",
      any(i.startswith("preamble") for i in v("T24", "I hope you are doing well. Bharat, your calls are down 50% over 7 days. Want me to look?").soft), not v("T24", GOOD[0][2]).soft)
prev = "Bharat, your calls are down 50% over 7 days against a baseline of 12. Want me to look into what changed?"
guard("repeat of a previous message", "REQUIRED", "challenge-testing-brief.md:480, examples F.5 (-2 per repeat)", "repeats_previous_message" in v("T24", prev + " ", prev=[prev]).hard,
      "repeats_previous_message" not in v("T24", "Bharat, calls fell 50% in the last 7 days (baseline 12). Should I check what changed and propose one fix?", prev=[prev]).hard)
guard("copy of a case-study anchor", "REQUIRED", "examples/case-studies.md:336,338 (judge runs a similarity check)", validator.copies_reference(REFERENCE_BODIES[1].replace("Priya", "Riya")),
      not any(validator.copies_reference(b) for _, _, b in GOOD), "high word-order bar (0.65) + verbatim-run bar (35% 6-grams) so same-fact messages pass")
guard("internal jargon", "STRONGLY RECOMMENDED", "judge_simulator.py:477 (-1)", any(i.startswith("internal_jargon") for i in v("T24", "Bharat, your stale_posts:22d signal explains the dip in calls. Want me to look?").hard),
      not any(i.startswith("internal_jargon") for i in v("T24", GOOD[0][2]).hard))
guard("empty / too-short body", "REQUIRED", "challenge-testing-brief.md:479 (empty send = malformed, -2)", "empty_or_too_short_body" in v("T24", "Hi?").hard, "empty_or_too_short_body" not in v("T24", GOOD[0][2]).hard)
too_long = ("Bharat, " + "your calls dropped this week and I have a lot more to say about it. " * 14) + "Want me to look?"
guard("too long (soft, >130 words)", "UNNECESSARY (kept soft: FAQ says no hard cap)", "examples/api-call-examples.md:556-562 (F.3: no cap)", any(i.startswith("too_long") for i in v("T24", too_long).soft), not v("T24", GOOD[0][2]).soft,
      "only costs one retry; harmless but not required")

# ---- malformed / failing LLM: every path ends in a valid message
composer.clear_cache()
llm.chat = lambda *a, **k: ("this is not json at all", "groq")
llm.chat_json = getattr(sys.modules["llm"], "chat_json")
import importlib  # noqa: E402
importlib.reload(llm)
composer.llm = llm
llm.chat = lambda *a, **k: ("this is not json at all", "groq")
d = composer.compose_detailed(*inputs("T24"), timeout=3.0)
check("malformed LLM output (not JSON) -> deterministic fallback, valid message", d["meta"]["source"] == "fallback" and d["message"]["body"].strip(), d["meta"]["issues"][:1].__str__())
llm.chat = lambda *a, **k: ('{"unexpected": true}', "groq")
composer.clear_cache()
d = composer.compose_detailed(*inputs("T24"), timeout=3.0)
check("JSON without a body -> rejected as empty, retried, then fallback", d["meta"]["source"] == "fallback" and d["message"]["body"].strip())
importlib.reload(llm)
composer.llm = llm
composer.clear_cache()
d = composer.compose_detailed(*inputs("T24"), timeout=3.0)
check("no provider configured -> fallback (LLM failure path)", d["meta"]["source"] == "fallback" and "llm_unavailable" in " ".join(d["meta"]["issues"]))
check("fallback covers all 100 triggers with hard-rule-clean messages and no jargon", all(
    not validator.validate(fb["body"], fb["cta"], ctx, cat, []).hard
    for t in trgs.values()
    for cat, m, cus in [(cats[mers[t["merchant_id"]]["category_slug"]], mers[t["merchant_id"]], cuss.get(t["customer_id"]) if t["customer_id"] else None)]
    for ctx in [composer.build_context(cat, m, t, cus)]
    for fb in [fallback.build(cat, m, t, cus, ctx, composer.addressee(cat, m, cus))]))

print("\nGUARD MATRIX")
print(f"{'guard':34} | {'classification':58} | {'bad example':7} | {'good example':16} | source")
for name, klass, source, bad, good, note in MATRIX:
    print(f"{name:34} | {klass[:58]:58} | {bad:7} | {good:16} | {source}" + (f"  ({note})" if note else ""))

# =====================================================================================================================
section("5. REPLY ENGINE AUDIT: allowed actions are exactly send / wait / end (challenge-testing-brief.md:128-146)")


def valid_shape(r):
    if r.get("action") == "send":
        return set(r) == {"action", "body", "cta", "rationale"} and r["body"].strip() and r["cta"] in prompts.CTA_TYPES
    if r.get("action") == "wait":
        return set(r) == {"action", "wait_seconds", "rationale"} and isinstance(r["wait_seconds"], int) and r["wait_seconds"] > 0
    return r.get("action") == "end" and set(r) == {"action", "rationale"}


def scenario_store():
    s = fresh_store()
    s.conversation("conv_s", merchant_id=M1, trigger_id="trg_001_research_digest_dentists", send_as="vera")["turns"].append(
        {"from": "vera", "body": "Dr. Meera, want me to pull the abstract and draft a patient note?", "ts": None})
    return s


def say(s, msg, conv="conv_s", mid=M1, cid=None, role="merchant"):
    return replies.handle_reply(s, {"conversation_id": conv, "merchant_id": mid, "customer_id": cid, "from_role": role, "message": msg,
                                    "received_at": NOW, "turn_number": 2})


GOOD_REPLY = {"body": "Here is the short summary and a draft patient note, ready to share. Reply CONFIRM and I will send it to your list.", "cta": "binary_confirm_cancel", "rationale": "m"}
rows = []
for mode in ("LLM mocked", "LLM absent"):
    if mode == "LLM mocked":
        llm.chat_json = lambda *a, **k: (dict(GOOD_REPLY), "groq")
    else:
        importlib.reload(llm)
        composer.llm = llm
    scen = [
        ("normal merchant reply", "What does the abstract say about high-risk patients?", "send"),
        ("acceptance", "Yes please send the abstract. Also draft the patient WhatsApp.", "send"),
        ("acceptance (Hinglish)", "haan kar do", "send"),
        ("rejection", "No thanks, not interested", "end"),
        ("intent transition", "Ok, let's do it. What's next?", "send"),
        ("hostile (stop request)", "Why are you bothering me. This is useless. Stop sending these.", "end"),
        ("hostile (abuse only)", "You people are useless idiots", "send"),
        ("off-topic", "Btw can you also help me with my GST filing this month?", "send"),
        ("wait (30 min)", "I'm busy right now, will check later", "wait"),
        ("wait (tomorrow)", "kal baat karte hain", "wait"),
        ("empty message", "   ", "wait"),
    ]
    for label, msg, want in scen:
        s = scenario_store()
        r = say(s, msg)
        ok = valid_shape(r) and r["action"] == want and not (r["action"] == "send" and validator.URL_RE.search(r["body"]))
        if label == "intent transition" and r["action"] == "send":
            ok &= not replies.QUALIFYING_RE.search(r["body"])
        rows.append((mode, label, r["action"] + (f" {r['wait_seconds']}" if r["action"] == "wait" else ""), (r.get("body") or "")[:70]))
        check(f"[{mode}] {label}: {r['action']}" + (f" {r.get('wait_seconds')}" if r["action"] == "wait" else ""), ok)
    s = scenario_store()
    seq = [say(s, "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.", conv=f"conv_a{i}")["action"] for i in range(1, 5)]
    check(f"[{mode}] auto-reply x4 (new conversation_id each time): send, wait, end, end", seq == ["send", "wait", "end", "end"], str(seq))
    s = scenario_store()
    say(s, "Not interested. Stop messaging me.")
    check(f"[{mode}] end condition: nothing more is sent on the ended conversation", say(s, "hello?")["action"] == "end")
    s = fresh_store()
    conv = s.conversation("conv_c", merchant_id=M1, customer_id="c_001_priya_for_m001", trigger_id="trg_003_recall_due_priya", send_as="merchant_on_behalf")
    conv["options"] = ["Wed 5 Nov, 6pm", "Thu 6 Nov, 5pm"]
    cr = [say(s, "2", conv="conv_c", cid="c_001_priya_for_m001", role="customer"),
          say(s, "Is parking available at the clinic?", conv="conv_c", cid="c_001_priya_for_m001", role="customer"),
          say(s, "stop", conv="conv_c", cid="c_001_priya_for_m001", role="customer")]
    check(f"[{mode}] customer replies: slot '2' -> confirmation, a question -> answer, 'stop' -> end", cr[0]["action"] == "send" and "Thu 6 Nov" in cr[0]["body"]
          and cr[1]["action"] == "send" and cr[2]["action"] == "end" and "c_001_priya_for_m001" in s.suppressed_customers and all(valid_shape(x) for x in cr))

# =====================================================================================================================
section("6. TICK POLICY AUDIT: never suppress what the judge expects")
llm.chat_json = lambda messages, max_tokens=450, timeout=6.0: ({"body": GENERIC_BODY + " " + messages[1]["content"].split('"kind":"')[1].split('"')[0].replace("_", " "), "cta": "binary_yes_no", "rationale": "m"}, "groq")
composer.clear_cache()
ids30 = [p["trigger_id"] for p in pairs]
s = fresh_store()
r1 = ticker.run_tick(s, {"now": NOW, "available_triggers": ids30})["actions"]
r2 = ticker.run_tick(s, {"now": NOW, "available_triggers": ids30})["actions"]
r3 = ticker.run_tick(s, {"now": NOW, "available_triggers": ids30})["actions"]
sent = [a["trigger_id"] for a in r1 + r2]
urg = [trgs[a["trigger_id"]]["urgency"] for a in r1]
check("max actions per tick is 20 (website 'Tick cap 20 actions per tick'; testing brief:333)", len(r1) == 20)
check("urgency ordering: highest first", urg == sorted(urg, reverse=True), str(urg))
check("repeated ticks: the other 10 follow, then nothing; no trigger sent twice", len(r2) == 10 and r3 == [] and len(set(sent)) == len(sent) == 30)
check("EVERY one of the 30 canonical (merchant, trigger) pairs receives a message (like-for-like set, challenge-brief.md:261)", sorted(sent) == sorted(ids30))
per = {}
for a in r1 + r2:
    per.setdefault(a["merchant_id"], []).append(a["conversation_id"])
check("several triggers of one merchant are all sent, in distinct conversations (FAQ testing brief:536)", max(len(v_) for v_ in per.values()) >= 3 and all(len(set(v_)) == len(v_) for v_ in per.values()))
ph_sent = [t for t in ids30 if trgs[t]["payload"].get("placeholder") and t in sent]
check("placeholder triggers are sent too (13 of the 30 pairs)", len(ph_sent) == 13, f"{len(ph_sent)}")
s = fresh_store()
check("expired triggers (expires_at long past) are sent when the judge lists them", len(ticker.run_tick(s, {"now": "2027-01-01T00:00:00Z", "available_triggers": ids30[:5]})["actions"]) == 5)
d1 = ticker.run_tick(fresh_store(), {"now": NOW, "available_triggers": ids30})["actions"]
composer.clear_cache()
d2 = ticker.run_tick(fresh_store(), {"now": NOW, "available_triggers": list(reversed(ids30))})["actions"]
check("deterministic: same state, same triggers (any order) -> identical actions", d1 == d2)
s = fresh_store()
ticker.run_tick(s, {"now": NOW, "available_triggers": ids30[:3]})
s.put_context("trigger", ids30[0], 2, {**trgs[ids30[0]], "urgency": 5})
check("a re-pushed (higher version) trigger that was already sent is not sent twice", ticker.run_tick(s, {"now": NOW, "available_triggers": ids30[:3]})["actions"] == [])

print("\nAUDIT RESULT:", "NO FAILURES" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
