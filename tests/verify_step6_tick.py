"""Step 6 verification (offline): /v1/tick selection rules, action shape, new-context adaptation, time budget.

Run from E:\\MAGICPIN:  python tests/verify_step6_tick.py
No API key needed: the LLM is mocked (or absent, which exercises the deterministic fallback).

Policy under test (see tick.py): every trigger the judge lists is eligible; highest urgency first; at most 20 actions per tick;
a trigger / (merchant, customer, suppression_key) is never sent twice; several triggers of one merchant may share a tick
(challenge-testing-brief.md:536); only a hostile merchant (api-call-examples.md:529) or an opted-out customer is skipped.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)

import composer  # noqa: E402
import llm  # noqa: E402
import replies  # noqa: E402
import tick as ticker  # noqa: E402
from prompts import CTA_TYPES  # noqa: E402
from store import Store  # noqa: E402

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
M1 = "m_001_drmeera_dentist_delhi"
NOW = "2026-04-26T10:35:00Z"

# ---------------------------------------------------------------- mock LLM: a valid, grounded-looking Hinglish body per call
PROMPTS, CALLS = [], {"n": 0}
FILLER = ["zaroori", "naya", "taaza", "khaas", "chhota", "seedha", "aasan", "tez", "saaf", "pakka", "halka", "gehra", "bada", "sahi"]


def mock_llm(delay=0.0):
    def fake(messages, max_tokens=450, timeout=6.0):
        CALLS["n"] += 1
        n = CALLS["n"]
        user = messages[1]["content"]
        PROMPTS.append(user)
        kind = re.search(r'"kind":"([a-z_]+)"', user).group(1).replace("_", " ")
        if delay:
            time.sleep(delay)
        body = (f"Namaste, aapke {kind} ke baare mein ek {FILLER[n % len(FILLER)]} update hai aur main isme help kar sakti hoon. "
                f"Kya main details bhej dun?")
        return {"body": body, "cta": "binary_yes_no", "rationale": "mock"}, "groq"
    llm.chat_json = fake
    composer.clear_cache()
    CALLS["n"] = 0
    PROMPTS.clear()


def fresh_store(triggers=True):
    s = Store()
    for slug, c in cats.items():
        s.put_context("category", slug, 1, c)
    for mid, m in mers.items():
        s.put_context("merchant", mid, 1, m)
    for cid, c in cuss.items():
        s.put_context("customer", cid, 1, c)
    if triggers:
        for tid, t in trgs.items():
            s.put_context("trigger", tid, 1, t)
    return s


REQUIRED = {"conversation_id", "merchant_id", "customer_id", "send_as", "trigger_id", "template_name", "template_params",
            "body", "cta", "suppression_key", "rationale"}
ids30 = [p["trigger_id"] for p in pairs]

# ================================================================ 1. selection over the 30 canonical triggers
mock_llm()
S = fresh_store()
r1 = ticker.run_tick(S, {"now": NOW, "available_triggers": ids30})
acts = r1["actions"]
check("tick returns {'actions': [...]} and never more than 20 actions (testing brief l.333)", isinstance(acts, list) and len(acts) == 20, f"{len(acts)} actions")
urg = [trgs[a["trigger_id"]]["urgency"] for a in acts]
check("highest urgency first", urg == sorted(urg, reverse=True), str(urg))
check("every action has exactly the 11 fields of the examples (api-call-examples.md:212-231)", all(set(a) == REQUIRED for a in acts))
check("field types: template_params list[str] (>=2), body non-empty, cta valid, rationale non-empty",
      all(isinstance(a["template_params"], list) and len(a["template_params"]) >= 2 and all(isinstance(x, str) for x in a["template_params"])
          and a["body"].strip() and a["cta"] in CTA_TYPES and a["rationale"].strip() for a in acts))
check("customer_id is set exactly for merchant_on_behalf actions, and matches the trigger",
      all((a["customer_id"] is not None) == (a["send_as"] == "merchant_on_behalf") and a["customer_id"] == trgs[a["trigger_id"]]["customer_id"] for a in acts))
check("send_as follows the trigger scope", all(a["send_as"] == ("merchant_on_behalf" if trgs[a["trigger_id"]]["scope"] == "customer" else "vera") for a in acts))
check("suppression_key comes from the trigger; merchant_id from the trigger",
      all(a["suppression_key"] == trgs[a["trigger_id"]]["suppression_key"] and a["merchant_id"] == trgs[a["trigger_id"]]["merchant_id"] for a in acts))
check("conversation_ids are unique and decodable (conv_<trigger_id>)", len({a["conversation_id"] for a in acts}) == len(acts) and all(a["conversation_id"] == f"conv_{a['trigger_id']}" for a in acts))
check("template naming: vera_<kind>_v1 / merchant_<kind>_v1",
      all(a["template_name"] == f"{'vera' if a['send_as'] == 'vera' else 'merchant'}_{trgs[a['trigger_id']]['kind']}_v1" for a in acts))
check("conversation state is recorded for the reply engine (first turn = sent body)",
      all(S.conversations[a["conversation_id"]]["turns"][0]["body"] == a["body"] for a in acts))
per_merchant = Counter(a["merchant_id"] for a in acts)
check("several triggers of one merchant go out in the SAME tick, each in its own conversation (FAQ l.536)",
      max(per_merchant.values()) >= 2, str(dict(per_merchant.most_common(3))))
recall = [a for a in acts if trgs[a["trigger_id"]]["kind"] == "recall_due" and a["customer_id"] == "c_001_priya_for_m001"]
check("slot labels of the recall trigger are stored so 'reply 2' can be booked",
      bool(recall) and S.conversations[recall[0]["conversation_id"]]["options"] == ["Wed 5 Nov, 6pm", "Thu 6 Nov, 5pm"])

sent = [a["trigger_id"] for a in acts]
r2 = ticker.run_tick(S, {"now": NOW, "available_triggers": ids30})["actions"]
sent += [a["trigger_id"] for a in r2]
r3 = ticker.run_tick(S, {"now": NOW, "available_triggers": ids30})["actions"]
check("2nd tick sends the 10 that did not fit under the cap, 3rd tick sends nothing", len(r2) == 10 and r3 == [], f"{len(r2)} then {len(r3)}")
check("across ticks every one of the 30 canonical triggers is sent exactly once (none dropped, none repeated)",
      sorted(sent) == sorted(ids30), f"{len(sent)} sends, {len(set(sent))} distinct")
check("no merchant is held back for having 'too many' triggers (Dr. Meera and Mylari have 3-4 each)",
      all(t in sent for t in ids30 if trgs[t]["merchant_id"] in (M1, "m_006_southindiancafe_restaurant_bangalore")))

# ================================================================ 2. missing / odd input
mock_llm()
s_empty = fresh_store(triggers=False)
check("no triggers pushed -> empty actions", ticker.run_tick(s_empty, {"now": NOW, "available_triggers": ids30}) == {"actions": []})
for odd in (None, [], "abc", [1, 2, None], {"a": 1}):
    check(f"available_triggers={odd!r} -> empty actions, no crash", ticker.run_tick(fresh_store(), {"now": NOW, "available_triggers": odd}) == {"actions": []})
check("missing available_triggers key -> empty actions", ticker.run_tick(fresh_store(), {"now": NOW}) == {"actions": []})
check("unparseable 'now' is tolerated", len(ticker.run_tick(fresh_store(), {"now": "garbage", "available_triggers": ids30[:1]})["actions"]) == 1)
check("unknown trigger ids are skipped silently", ticker.run_tick(fresh_store(), {"now": NOW, "available_triggers": ["trg_does_not_exist"]}) == {"actions": []})

s_nomerchant = fresh_store(triggers=False)
s_nomerchant.put_context("trigger", "t_x", 1, {**trgs["trg_024_perf_spike_zen"], "id": "t_x", "merchant_id": "m_ghost"})
check("trigger whose merchant was never pushed is skipped (nothing invented)", ticker.run_tick(s_nomerchant, {"now": NOW, "available_triggers": ["t_x"]}) == {"actions": []})
s_nocust = fresh_store(triggers=False)
s_nocust.contexts.pop(("customer", "c_001_priya_for_m001"))
s_nocust.put_context("trigger", "trg_003_recall_due_priya", 1, trgs["trg_003_recall_due_priya"])
check("customer-scope trigger whose customer was never pushed is skipped", ticker.run_tick(s_nocust, {"now": NOW, "available_triggers": ["trg_003_recall_due_priya"]}) == {"actions": []})
s_nocat = fresh_store()
s_nocat.contexts.pop(("category", "dentists"))
check("merchant whose category is missing is skipped", ticker.run_tick(s_nocat, {"now": NOW, "available_triggers": ["trg_001_research_digest_dentists"]}) == {"actions": []})
check("expires_at is NOT used to drop triggers (simulator sends the real clock; the judge's list is already 'active right now')",
      len(ticker.run_tick(fresh_store(), {"now": "2026-09-26T10:00:00Z", "available_triggers": ["trg_024_perf_spike_zen"]})["actions"]) == 1)
odd_kind = {**trgs["trg_024_perf_spike_zen"], "id": "t_new_kind", "kind": "brand_new_kind_from_judge", "suppression_key": "new:kind", "payload": {"foo": 1}}
s_kind = fresh_store(triggers=False)
s_kind.put_context("trigger", "t_new_kind", 1, odd_kind)
out = ticker.run_tick(s_kind, {"now": NOW, "available_triggers": ["t_new_kind"]})["actions"]
check("a trigger kind the bot has never seen still yields a valid message (default guidance / generic fallback)",
      len(out) == 1 and out[0]["body"].strip() and out[0]["template_name"] == "vera_brand_new_kind_from_judge_v1")
s_pl = fresh_store(triggers=False)
legacy = {k: v for k, v in trgs["trg_024_perf_spike_zen"].items() if k not in ("merchant_id", "customer_id")}
legacy["id"], legacy["payload"] = "t_legacy", {**legacy["payload"], "merchant_id": "m_008_zenyoga_gym_chennai"}
s_pl.put_context("trigger", "t_legacy", 1, legacy)
check("defensive: merchant_id inside the payload (challenge-brief.md:259 wording) is also understood",
      len(ticker.run_tick(s_pl, {"now": NOW, "available_triggers": ["t_legacy"]})["actions"]) == 1)

# ================================================================ 3. suppression rules
mock_llm()
s = fresh_store()
s.flags(M1)["suppressed"] = True  # a hostile merchant (examples 4.3)
check("hostile merchant: none of that merchant's triggers goes out (examples 4.3)",
      ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_001_research_digest_dentists", "trg_003_recall_due_priya"]}) == {"actions": []})
s = fresh_store()
s.suppressed_customers.add("c_001_priya_for_m001")
check("customer who asked to stop is skipped", ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_003_recall_due_priya"]}) == {"actions": []})

# opt-out / auto-reply exit / 'busy' are conversation-level (examples 2.5, 2.6, 4.1) and must not swallow other triggers
s = fresh_store()
first = ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_001_research_digest_dentists"]})["actions"][0]
conv = first["conversation_id"]


def say(text, cv=conv):
    return replies.handle_reply(s, {"conversation_id": cv, "merchant_id": M1, "from_role": "merchant", "message": text,
                                    "received_at": NOW, "turn_number": 2})


say("Not interested. Stop messaging me.")
after = ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_023_competitor_opened_dentist", "trg_002_compliance_dci_radiograph"]})["actions"]
check("plain opt-out ends only that conversation: the merchant's OTHER triggers are still sent (examples 2.6)", len(after) == 2, f"{len(after)} actions")
AUTO = "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."
for i in (1, 2, 3):
    say(AUTO, cv=f"conv_auto_{i}")
check("3 auto-replies end that conversation but the merchant stays eligible (examples 4.1 says 'closing', not 'suppressing')", not s.flags(M1)["suppressed"])
say("I'm busy right now, will check later", cv="conv_busy")
check("'busy' is a wait on that conversation only: no merchant-level gate is set", not s.flags(M1)["suppressed"] and set(s.flags(M1)) == {"auto_replies", "hostile", "suppressed"})
say("You are useless idiots. Stop sending these.", cv="conv_hostile")
check("opt-out WITH hostility (examples 4.3) suppresses the merchant", s.flags(M1)["suppressed"] is True)

# same suppression key twice in one tick
s = fresh_store(triggers=False)
base = trgs["trg_024_perf_spike_zen"]
s.put_context("trigger", "dup_a", 1, {**base, "id": "dup_a", "suppression_key": "spike:shared"})
s.put_context("trigger", "dup_b", 1, {**base, "id": "dup_b", "suppression_key": "spike:shared"})
check("same (merchant, suppression_key) twice in one tick -> sent once", len(ticker.run_tick(s, {"now": NOW, "available_triggers": ["dup_a", "dup_b"]})["actions"]) == 1)
s = fresh_store(triggers=False)
s.put_context("trigger", "dup_a", 1, {**base, "id": "dup_a", "suppression_key": "research:dentists:2026-W17"})
s.put_context("trigger", "dup_c", 1, {**trgs["trg_001_research_digest_dentists"], "id": "dup_c", "suppression_key": "research:dentists:2026-W17"})
check("a category-level suppression_key shared by two DIFFERENT merchants must not block either (examples 2.1 key style)",
      len(ticker.run_tick(s, {"now": NOW, "available_triggers": ["dup_a", "dup_c"]})["actions"]) == 2)

# ================================================================ 4. adaptation to post-submission context (testing brief Phase 3)
mock_llm()
s = fresh_store()
cat2 = json.loads(json.dumps(cats["dentists"]))
cat2["digest"].append({"id": "d_NEW_1", "kind": "research", "title": "Zzqx new radiograph guidance", "source": "DCI circular 2026-11-04",
                       "summary": "fresh item pushed after submission", "actionable": "read it"})
check("category v2 accepted", s.put_context("category", "dentists", 2, cat2)[0])
newtrg = {**trgs["trg_001_research_digest_dentists"], "id": "trg_new_research", "suppression_key": "research:dentists:new",
          "payload": {"category": "dentists", "top_item_id": "d_NEW_1"}}
s.put_context("trigger", "trg_new_research", 1, newtrg)
ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_new_research"]})
check("new digest item (category v2) is what the composer sees for the new trigger",
      "Zzqx new radiograph guidance" in PROMPTS[-1] and "fluoride varnish recall outperforms" not in PROMPTS[-1])

mock_llm()
s = fresh_store()
m2 = json.loads(json.dumps(mers["m_008_zenyoga_gym_chennai"]))
m2["performance"]["views"] = 987654
s.put_context("merchant", "m_008_zenyoga_gym_chennai", 2, m2)
ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_024_perf_spike_zen"]})
check("updated performance snapshot (merchant v2) reaches the composer", "987654" in PROMPTS[-1])
before = CALLS["n"]
s.put_context("merchant", "m_008_zenyoga_gym_chennai", 3, {**m2, "performance": {**m2["performance"], "views": 111222}})
s.sent_trigger_ids.clear(); s.sent_keys.clear(); s.conversations.clear()
ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_024_perf_spike_zen"]})
check("a newer merchant version invalidates the cached message (fresh compose, new numbers)", CALLS["n"] > before and "111222" in PROMPTS[-1])

mock_llm()
s = fresh_store(triggers=False)
newcust = {**cuss["c_001_priya_for_m001"], "customer_id": "c_NEW_9", "identity": {**cuss["c_001_priya_for_m001"]["identity"], "name": "Zoravar"}}
s.put_context("customer", "c_NEW_9", 1, newcust)
rec = {**trgs["trg_003_recall_due_priya"], "id": "trg_new_recall", "customer_id": "c_NEW_9", "suppression_key": "recall:c_NEW_9:6mo"}
s.put_context("trigger", "trg_new_recall", 1, rec)
out = ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_new_recall"]})["actions"]
check("customer pushed mid-test + its recall trigger -> customer-facing action using that customer",
      len(out) == 1 and out[0]["send_as"] == "merchant_on_behalf" and out[0]["customer_id"] == "c_NEW_9" and "Zoravar" in PROMPTS[-1])
newm = json.loads(json.dumps(mers[M1]))
newm["merchant_id"] = "m_BRAND_NEW"
newm["identity"]["name"] = "Brand New Clinic"
s.put_context("merchant", "m_BRAND_NEW", 1, newm)
s.put_context("category", "dentists", 1, cats["dentists"])
s.put_context("trigger", "trg_bn", 1, {**trgs["trg_024_perf_spike_zen"], "id": "trg_bn", "merchant_id": "m_BRAND_NEW", "suppression_key": "spike:bn"})
check("a merchant never seen before, pushed mid-test, is handled like any other (testing brief FAQ)",
      len(ticker.run_tick(s, {"now": NOW, "available_triggers": ["trg_bn"]})["actions"]) == 1)

# ================================================================ 5. time budget (10 s table) + background results are kept
mock_llm(delay=1.5)
s = fresh_store()
eight, seen_merchants = [], set()
for t in trgs.values():
    if t["scope"] == "merchant" and t["merchant_id"] not in seen_merchants:
        seen_merchants.add(t["merchant_id"])
        eight.append(t["id"])
    if len(eight) == 8:
        break
t0 = time.time()
a1 = ticker.run_tick(s, {"now": NOW, "available_triggers": eight}, budget=2.0)["actions"]
took = time.time() - t0
check("slow LLM: tick returns at its budget with the drafts that finished", took < 2.8 and len(a1) == 6, f"{took:.2f}s, {len(a1)} actions")
time.sleep(1.6)
t1 = time.time()
a2 = ticker.run_tick(s, {"now": NOW, "available_triggers": eight}, budget=2.0)["actions"]
check("the unfinished drafts finished in the background: next tick returns them instantly (no recompute)",
      len(a2) == 2 and time.time() - t1 < 0.5 and CALLS["n"] == 8, f"{len(a2)} actions, {time.time() - t1:.2f}s, llm calls={CALLS['n']}")
check("all 8 triggers were eventually sent exactly once", sorted(a["trigger_id"] for a in a1 + a2) == sorted(eight))

# ================================================================ 6. determinism of the tick itself
mock_llm()
d1 = ticker.run_tick(fresh_store(), {"now": NOW, "available_triggers": ids30})["actions"]
d2 = ticker.run_tick(fresh_store(), {"now": NOW, "available_triggers": list(reversed(ids30))})["actions"]
check("same state + same trigger set (any order) -> identical actions in identical order", d1 == d2 and len(d1) == 20)

# ================================================================ 7. LLM completely down -> fallback messages, fast
import importlib  # noqa: E402
importlib.reload(llm)  # restores the real llm.chat_json (the mock is gone) and clears provider cooldowns
composer.clear_cache()
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)
s = fresh_store()
t0 = time.time()
down = ticker.run_tick(s, {"now": NOW, "available_triggers": ids30})["actions"]
check("no LLM at all: tick still answers with valid fallback actions, fast",
      len(down) == 20 and all(set(a) == REQUIRED and a["body"].strip() for a in down) and time.time() - t0 < 3, f"{len(down)} actions {time.time() - t0:.2f}s")

# ================================================================ 8. HTTP endpoint (in-process) + real server with the judge simulator's client
mock_llm()
from fastapi.testclient import TestClient  # noqa: E402
import bot  # noqa: E402

bot.store.reset()
client = TestClient(bot.app)
for slug, c in cats.items():
    client.post("/v1/context", json={"scope": "category", "context_id": slug, "version": 1, "payload": c, "delivered_at": NOW})
for mid, m in mers.items():
    client.post("/v1/context", json={"scope": "merchant", "context_id": mid, "version": 1, "payload": m, "delivered_at": NOW})
for tid in ("trg_001_research_digest_dentists", "trg_024_perf_spike_zen"):
    client.post("/v1/context", json={"scope": "trigger", "context_id": tid, "version": 1, "payload": trgs[tid], "delivered_at": NOW})
r = client.post("/v1/tick", json={"now": NOW, "available_triggers": ["trg_001_research_digest_dentists", "trg_024_perf_spike_zen"]})
check("POST /v1/tick over HTTP -> 200 with two well-formed actions", r.status_code == 200 and len(r.json()["actions"]) == 2 and all(set(a) == REQUIRED for a in r.json()["actions"]))
r2 = client.post("/v1/tick", json={"now": NOW, "available_triggers": ["trg_001_research_digest_dentists"]})
check("the same trigger over HTTP a second time -> empty actions (suppressed)", r2.status_code == 200 and r2.json() == {"actions": []})
first = r.json()["actions"][0]
rr = client.post("/v1/reply", json={"conversation_id": first["conversation_id"], "merchant_id": first["merchant_id"], "customer_id": None,
                                    "from_role": "merchant", "message": "Ok lets do it. Whats next?", "received_at": NOW, "turn_number": 2})
check("a reply to a conversation created by /v1/tick works end to end", rr.status_code == 200 and rr.json()["action"] == "send")
check("teardown clears sent-trigger state too", client.post("/v1/teardown").status_code == 200 and not bot.store.sent_trigger_ids and not bot.store.conversations)
check("bot.py exposes compose() (brief §7.1)", callable(bot.compose))

import judge_simulator as js  # noqa: E402

PORT = 8768
logfile = open(ROOT / "tests" / "_step6_server.log", "w", encoding="utf-8")
env_clean = {k: v for k, v in os.environ.items() if k not in ("GROQ_API_KEY", "OPENROUTER_API_KEY")}
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "bot:app", "--host", "127.0.0.1", "--port", str(PORT)], cwd=str(ROOT),
                        stdout=logfile, stderr=subprocess.STDOUT, env=env_clean)
try:
    import requests
    for _ in range(60):
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/v1/healthz", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.25)
    js.BOT_URL = f"http://127.0.0.1:{PORT}"
    judge = js.JudgeSimulator(object())
    judge.dataset.load()
    c = judge.client
    # exactly what judge_simulator._full pushes: categories, ALL merchants, ALL triggers - and no customers
    for slug, cat in judge.dataset.categories.items():
        c.push_context("category", slug, 1, cat)
    for mid, m in judge.dataset.merchants.items():
        c.push_context("merchant", mid, 1, m)
    for tid, t in judge.dataset.triggers.items():
        c.push_context("trigger", tid, 1, t)
    ids = list(judge.dataset.triggers)
    merchant_scope = [t for t in ids if judge.dataset.triggers[t]["scope"] == "merchant"]
    all_actions, worst, malformed = [], 0.0, 0
    for i in range(0, len(ids), 5):  # exactly how judge_simulator._full batches its ticks (each trigger is listed ONCE)
        data, err, lat = c.tick(ids[i:i + 5])
        worst = max(worst, lat)
        if err or not isinstance(data, dict) or not isinstance(data.get("actions"), list):
            malformed += 1
            continue
        for a in data["actions"]:
            all_actions.append(a)
            malformed += 0 if (set(a) == REQUIRED and a["body"].strip()) else 1
    check("SIMULATOR-style run (seed data, real clock as 'now', batches of 5, triggers listed once): every action well-formed",
          malformed == 0 and len(all_actions) > 0, f"{len(all_actions)} actions from {len(ids)} seed triggers, {malformed} malformed")
    check("...and NO merchant-scope trigger is dropped (each of them gets its message, no matter how many triggers a merchant has)",
          sorted(a["trigger_id"] for a in all_actions) == sorted(merchant_scope), f"{len(merchant_scope)} merchant-scope triggers")
    check("...customer-scope triggers are skipped only because the simulator never pushes customers", all(judge.dataset.triggers[a["trigger_id"]]["scope"] == "merchant" for a in all_actions))
    check("every tick answered inside the simulator's 15 s timeout", worst < 15000, f"slowest {worst:.0f} ms")
    check("no body contains a URL", not any(re.search(r"https?://|www\.", a["body"]) for a in all_actions))
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logfile.close()

log = (ROOT / "tests" / "_step6_server.log").read_text(encoding="utf-8", errors="replace")
check("server log has no Traceback", "Traceback" not in log)
try:
    (ROOT / "tests" / "_step6_server.log").unlink()
except OSError:
    pass

print("\nRESULT:", "ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
