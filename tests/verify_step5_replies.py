"""Step 5 verification (offline): reply classification, every reply flow, and the judge simulator's own scenarios.

Run from E:\\MAGICPIN:  python tests/verify_step5_replies.py
No API key needed: the LLM is mocked or absent (deterministic replies are then used).
"""
import contextlib
import glob
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)

import llm  # noqa: E402
import replies  # noqa: E402
import validator  # noqa: E402
from store import Store  # noqa: E402

failures = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def load(pattern, key):
    return {json.load(open(f, encoding="utf-8"))[key]: json.load(open(f, encoding="utf-8")) for f in glob.glob(str(ROOT / "expanded" / pattern))}


cats, mers, cuss = load("categories/*.json", "slug"), load("merchants/*.json", "merchant_id"), load("customers/*.json", "customer_id")
M1 = "m_001_drmeera_dentist_delhi"

# ================================================================ A. classification
CASES = [
    ("Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.", "auto_reply"),
    ("Thank you for contacting us! Our team will respond shortly.", "auto_reply"),
    ("Aapki jaankari ke liye bahut-bahut shukriya. Main aapki yeh sabhi baatein aur sujhaav hamari team tak pahuncha deti hoon.", "auto_reply"),
    ("Aapki madad ke liye shukriya, lekin main ek automated assistant hoon", "auto_reply"),
    ("Not interested. Stop messaging me.", "opt_out"),
    ("Why are you bothering me. This is useless. Stop sending these.", "opt_out"),
    ("Stop messaging me. This is useless spam.", "opt_out"),
    ("stop", "opt_out"),
    ("mat bhejo ye messages", "opt_out"),
    ("band karo ye sab", "opt_out"),
    ("no thanks", "decline"),
    ("Not interested", "decline"),
    ("nahi", "decline"),
    ("You people are useless idiots, what a waste of my time", "hostile"),
    ("bakwas service hai", "hostile"),
    ("Ok, let's do it. What's next?", "intent"),
    ("Ok lets do it. Whats next?", "intent"),
    ("Yes please send the abstract. Also draft the patient WhatsApp.", "intent"),
    ("haan kar do", "intent"),
    ("Mujhe magicpin judrna hai.", "intent"),
    ("go ahead", "intent"),
    ("yes", "intent"),
    ("Sure", "intent"),
    ("Btw can you also help me with my GST filing this month?", "off_topic"),
    ("need a loan for expansion", "off_topic"),
    ("I'm busy right now, will check later", "wait"),
    ("kal baat karte hain", "wait"),
    ("give me some time", "wait"),
    ("What is the price of the whitening?", "normal"),
    ("how many views did I get last week?", "normal"),
    ("Yes but what does it cost?", "normal"),
    ("yes, kitna lagega", "normal"),
    ("Yes please, and what is the price?", "normal"),
    ("Ok please check & update the profile.", "intent"),
    ("Tell me more", "normal"),
    ("   ", "empty"),
]
wrong = [(m, want, replies.classify(m)) for m, want in CASES if replies.classify(m) != want]
check(f"classify: all {len(CASES)} sample messages land in the right bucket", not wrong, str(wrong[:3]))
check("classify: identical text seen before from the same merchant counts as an auto-reply",
      replies.classify("Thanks for the update, noted.", repeats=1) == "auto_reply" and replies.classify("Thanks for the update, noted.", 0) == "normal")
slots = ["Wed 5 Nov, 6pm", "Thu 6 Nov, 5pm"]
check("match_slot: number / weekday / label / no match",
      replies.match_slot("2", slots) == 1 and replies.match_slot("Wednesday works", slots) == 0 and replies.match_slot("thursday please", slots) == 1
      and replies.match_slot("maybe next week", slots) is None and replies.match_slot("3", slots) is None)


# ================================================================ helpers for flow tests
def fresh_store():
    s = Store()
    for slug, c in cats.items():
        s.put_context("category", slug, 1, c)
    for mid, m in mers.items():
        s.put_context("merchant", mid, 1, m)
    for cid, c in cuss.items():
        s.put_context("customer", cid, 1, c)
    return s


def req(conv, msg, mid=M1, cid=None, role="merchant", turn=2):
    return {"conversation_id": conv, "merchant_id": mid, "customer_id": cid, "from_role": role, "message": msg,
            "received_at": "2026-04-26T10:42:00Z", "turn_number": turn}


def valid_shape(r):
    if r.get("action") == "send":
        return bool(str(r.get("body", "")).strip()) and r.get("cta") and r.get("rationale")
    if r.get("action") == "wait":
        return isinstance(r.get("wait_seconds"), int) and r["wait_seconds"] > 0 and r.get("rationale")
    return r.get("action") == "end" and bool(r.get("rationale"))


AUTO = "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."
seen_responses = []


def call(s, *a, **k):
    r = replies.handle_reply(s, req(*a, **k))
    seen_responses.append(r)
    return r


# ================================================================ B1. auto-reply hell (simulator style: new conversation_id each turn)
s = fresh_store()
r1, r2, r3, r4 = (call(s, f"conv_auto_{i}", AUTO) for i in (1, 2, 3, 4))
check("auto-reply #1 -> one short send for the owner (examples 4.1)", r1["action"] == "send" and "auto" in r1["body"].lower())
check("auto-reply #2 -> wait 86400 (examples 4.1)", r2 == {"action": "wait", "wait_seconds": 86400, "rationale": r2["rationale"]})
check("auto-reply #3 -> end, even though every turn used a NEW conversation_id", r3["action"] == "end")
check("auto-reply #4 -> still end", r4["action"] == "end")
check("auto-reply exit is conversation-level (examples 4.1: 'closing'): the merchant is NOT suppressed, its other triggers still go out",
      s.flags(M1)["suppressed"] is False)
again = call(s, "conv_auto_3", "hello?")
check("an ended conversation never gets another send (examples 2.6)", again["action"] == "end")
fresh_conv = call(s, "conv_new_after_auto", "Ok lets do it. Whats next?")
check("a NEW conversation of the same merchant is still answered (replay scenarios reuse the merchant)", fresh_conv["action"] == "send")
check("a real message resets the auto-reply streak", s.flags(M1)["auto_replies"] == 0)

# same conversation, real-harness style
s = fresh_store()
seq = [call(s, "conv_same", AUTO, turn=t)["action"] for t in (2, 3, 4, 5)]
check("same conversation, 4 identical canned texts: send, wait, end, end", seq == ["send", "wait", "end", "end"], str(seq))

# ================================================================ B2. opt-out / decline / hostile
s = fresh_store()
r = call(s, "conv_out", "Not interested. Stop messaging me.")
check("opt-out -> end (examples 2.6)", r["action"] == "end")
check("plain opt-out ends THIS conversation only (examples 2.6 rationale): the merchant is not suppressed", s.flags(M1)["suppressed"] is False)
check("nothing more is sent on that conversation_id", call(s, "conv_out", "hello again")["action"] == "end")
s = fresh_store()
r = call(s, "conv_hs", "Why are you bothering me. This is useless. Stop sending these.")
check("the examples 4.3 message (hostile + stop) -> end, and that merchant is suppressed for proactive sends (30 days rule)",
      r["action"] == "end" and s.flags(M1)["suppressed"] is True)

s = fresh_store()
r = call(s, "conv_no", "no thanks")
check("plain decline -> end, but the merchant is NOT permanently suppressed", r["action"] == "end" and not s.flags(M1)["suppressed"])

s = fresh_store()
r = call(s, "conv_h", "You people are useless idiots")
check("abuse without opt-out -> one calm reply (stay on mission, testing brief Phase 4 #3)", r["action"] == "send" and "STOP" in r["body"])
check("calm reply is not a copy of the reference apology and has no URL",
      not validator.copies_reference(r["body"]) and not validator.URL_RE.search(r["body"]))
r2 = call(s, "conv_h", "you are still useless")
check("second abusive message -> end", r2["action"] == "end")

# ================================================================ B3. commitment -> ACTION (LLM mocked)
prompts_seen = []


def mock_llm(*bodies):
    it = iter(bodies)

    def fake(messages, max_tokens=350, timeout=6.0):
        prompts_seen.append(messages[1]["content"])
        body = next(it, bodies[-1])
        return {"body": body, "cta": "binary_confirm_cancel", "rationale": "mock"}, "groq"
    llm.chat_json = fake


s = fresh_store()
s.conversation("conv_int", merchant_id=M1, trigger_id="trg_001_research_digest_dentists", send_as="vera")["turns"].append(
    {"from": "vera", "body": "Dr. Meera, want me to pull the abstract and draft a patient note?", "ts": None})
s.put_context("trigger", "trg_001_research_digest_dentists", 1, json.load(open(ROOT / "expanded" / "triggers" / "trg_001_research_digest_dentists.json", encoding="utf-8")))
mock_llm("Here is the abstract summary and a short patient note draft, ready to share. Reply CONFIRM and I will send the note to your patients.")
r = call(s, "conv_int", "Ok, let's do it. What's next?")
check("intent + LLM: ACTION reply is sent, without qualifying phrases",
      r["action"] == "send" and not replies.QUALIFYING_RE.search(r["body"]) and "MODE: ACTION" in prompts_seen[-1])
check("ACTION prompt carries the earlier offer (conversation) and the latest message",
      "abstract" in prompts_seen[-1] and "let's do it" in prompts_seen[-1].lower())

s2 = fresh_store()
mock_llm("Excellent! Just to plan well, would you say most of your patients are high risk? Do you want a Hindi version too?")
r = call(s2, "conv_int2", "Ok lets do it. Whats next?")
check("LLM that keeps qualifying is rejected -> deterministic ACTION reply (no qualifying phrase, action words present)",
      r["action"] == "send" and not replies.QUALIFYING_RE.search(r["body"]) and re.search(r"draft|here|confirm", r["body"].lower()), r.get("body", "")[:80])

llm.chat_json = lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("down"))
s3 = fresh_store()
r = call(s3, "conv_int3", "Ok lets do it. Whats next?")
body_l = r["body"].lower()
check("LLM down: deterministic ACTION reply passes the simulator's keyword test (action words, no qualifying words)",
      any(w in body_l for w in ["done", "sending", "draft", "here", "confirm", "proceed", "next"]) and not any(w in body_l for w in ["would you", "do you", "can you tell", "what if", "how about"]))
unknown = call(s3, "conv_unknown", "Ok lets do it. Whats next?", mid="m_not_pushed")
check("unknown merchant + unknown conversation still gets a valid reply (no crash)", valid_shape(unknown))

# ================================================================ B4. off-topic, wait, normal
s = fresh_store()
mock_llm("GST filing is outside what I can help with, so please check with your CA. Coming back to your listing, shall I send the outline first?")
r = call(s, "conv_gst", "Btw can you also help me with my GST filing this month?")
check("off-topic (GST): LLM reply declines and steers back; prompt carries OFF_TOPIC_HINT",
      r["action"] == "send" and "OFF_TOPIC_HINT: true" in prompts_seen[-1] and "CA" in r["body"])
check("the decline is not a copy of the reference curveball reply", not validator.copies_reference(r["body"]))
llm.chat_json = lambda *a, **k: (_ for _ in ()).throw(llm.LLMUnavailable("down"))
r = call(fresh_store(), "conv_gst2", "Btw can you also help me with my GST filing this month?")
check("off-topic with LLM down: deterministic decline that names the CA", r["action"] == "send" and "CA" in r["body"])

s = fresh_store()
r = call(s, "conv_w1", "I'm busy right now, will check later")
check("'busy, later' -> wait 1800", r == {"action": "wait", "wait_seconds": 1800, "rationale": r["rationale"]})
check("wait is conversation-level: it sets no merchant-wide gate", not s.flags(M1)["suppressed"] and "wait_until" not in s.flags(M1))
check("'kal baat karte hain' -> wait 86400", call(s, "conv_w2", "kal baat karte hain")["wait_seconds"] == 86400)

s = fresh_store()
n1 = call(s, "conv_n", "What is the price of the whitening?")
n2 = call(s, "conv_n", "And how many views did I get?")
n3 = call(s, "conv_n", "ok what else can you do")
check("normal message, LLM down: two different deterministic replies, then end instead of repeating itself",
      n1["action"] == "send" and n2["action"] == "send" and n1["body"] != n2["body"] and n3["action"] in ("end", "send"), f"{n1['action']},{n2['action']},{n3['action']}")
check("no verbatim repeat in the whole normal conversation",
      len({t["body"] for t in s.conversations["conv_n"]["turns"] if t["from"] == "vera"}) == len([t for t in s.conversations["conv_n"]["turns"] if t["from"] == "vera"]))

# ================================================================ B5. language mirroring + customer slot booking
mode, _ = replies.reply_language("Haan kar do, aap bhej dijiye", cats["dentists"], mers[M1], None)
check("language: a Hinglish message gets a Hinglish-capable reply mode", mode in ("hinglish", "hinglish_light"))
mode, _ = replies.reply_language("Please send me the details of the offer for next week", cats["dentists"], mers[M1], None)
check("language: an English message is mirrored in English", mode == "en")

s = fresh_store()
conv = s.conversation("conv_priya", merchant_id=M1, customer_id="c_001_priya_for_m001", trigger_id="trg_003_recall_due_priya", send_as="merchant_on_behalf")
conv["options"] = ["Wed 5 Nov, 6pm", "Thu 6 Nov, 5pm"]
r = call(s, "conv_priya", "2", cid="c_001_priya_for_m001", role="customer")
check("customer picks slot '2' -> booking confirmation with the real slot label",
      r["action"] == "send" and "Thu 6 Nov, 5pm" in r["body"] and r["cta"] == "none" and conv["booked"] == "Thu 6 Nov, 5pm", r.get("body", "")[:90])

# ================================================================ C. deterministic replies are safe
bad = []
for kind, variants in replies.FALLBACK.items():
    for en, hi, cta in variants:
        for body in (en, hi):
            if validator.copies_reference(body) or validator.URL_RE.search(body) or replies.QUALIFYING_RE.search(body) and kind.startswith("action"):
                bad.append((kind, body[:50]))
check("no deterministic reply copies a reference message, contains a URL, or qualifies after a commitment", not bad, str(bad))
check("every response produced in this test has a valid shape", all(valid_shape(r) for r in seen_responses), f"{len(seen_responses)} responses")

# ================================================================ D. the judge simulator's own scenarios against a live server
import judge_simulator as js  # noqa: E402

PORT = 8767
logfile = open(ROOT / "tests" / "_step5_server.log", "w", encoding="utf-8")
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "bot:app", "--host", "127.0.0.1", "--port", str(PORT)], cwd=str(ROOT),
                        stdout=logfile, stderr=subprocess.STDOUT, env={k: v for k, v in os.environ.items() if k not in ("GROQ_API_KEY", "OPENROUTER_API_KEY")})
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

    def run_scenario(fn):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = fn()
        return ok, re.sub(r"\x1b\[[0-9;]*m", "", buf.getvalue())

    ok, out = run_scenario(judge._auto_reply)
    check("SIMULATOR auto_reply_hell: bot ENDED after detecting the auto-reply pattern", ok and "Bot ENDED" in out, out.strip().splitlines()[-1][:100])
    ok, out = run_scenario(judge._intent)
    check("SIMULATOR intent_transition (same merchant, right after auto-reply): bot switched to ACTION mode", ok and "correctly switched to ACTION mode" in out, out.strip().splitlines()[-1][:100])
    ok, out = run_scenario(judge._hostile)
    check("SIMULATOR hostile: bot correctly ENDED on hostile message", ok and "correctly ENDED on hostile message" in out, out.strip().splitlines()[-1][:100])
    t0 = time.time()
    requests.post(js.BOT_URL + "/v1/reply", json=req("conv_speed", "What is the price of the whitening?"), timeout=12)
    check("reply endpoint answers within the 10 s budget", time.time() - t0 < 10, f"{time.time() - t0:.2f}s")
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
    logfile.close()

log = (ROOT / "tests" / "_step5_server.log").read_text(encoding="utf-8", errors="replace")
check("server log has no Traceback", "Traceback" not in log)
try:
    (ROOT / "tests" / "_step5_server.log").unlink()
except OSError:
    pass

print("\nRESULT:", "ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
