"""AUDIT 1 + 5: endpoint contract and a replay of examples/api-call-examples.md against the running bot.

    python tests/audit_contract_replay.py                # spawns a local server on port 8770 (no LLM key needed)
    set BOT_URL=https://host && python tests/audit_contract_replay.py   # audit an already running / public bot

For every check it prints: area | check | source (file:line of the challenge pack) | expected | actual | PASS / FAIL / AMBIGUOUS.
AMBIGUOUS = two sources of the pack disagree and the bot follows one of them (documented in MAGICPIN_VERA_AI_STEPS_1_TO_6.md).
Exit code 0 = no FAIL.  A markdown copy is written to out/audit_contract_replay.md.
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EXP = ROOT / "expanded"

ROWS = []
TIMES = {}


def rec(area, check, source, expected, actual, status):
    ROWS.append((area, check, source, str(expected), str(actual), status))


def load(pattern):
    return [json.load(open(f, encoding="utf-8")) for f in sorted(glob.glob(str(EXP / pattern)))]


BASE = os.environ.get("BOT_URL", "").rstrip("/")
proc = None
logfile = None
if not BASE:
    port = 8770
    BASE = f"http://127.0.0.1:{port}"
    logfile = open(ROOT / "tests" / "_audit_contract_server.log", "w", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("GROQ_API_KEY", "OPENROUTER_API_KEY")}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "bot:app", "--host", "127.0.0.1", "--port", str(port)], cwd=str(ROOT),
                            stdout=logfile, stderr=subprocess.STDOUT, env=env)
    for _ in range(80):
        try:
            if requests.get(BASE + "/v1/healthz", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.25)


def call(method, path, kind=None, **kw):
    t0 = time.time()
    r = requests.request(method, BASE + path, timeout=35, **kw)
    if kind:
        TIMES.setdefault(kind, []).append(time.time() - t0)
    return r


def env_(scope, cid, version, payload):
    return {"scope": scope, "context_id": cid, "version": version, "payload": payload, "delivered_at": "2026-04-26T09:45:00Z"}


def reply(conv, msg, mid="m_001_drmeera_dentist_delhi", turn=2, cid=None, role="merchant"):
    return call("POST", "/v1/reply", "reply", json={"conversation_id": conv, "merchant_id": mid, "customer_id": cid, "from_role": role,
                                                  "message": msg, "received_at": "2026-04-26T10:42:00Z", "turn_number": turn})


QUALIFYING = re.compile(r"\b(would you|do you|can you tell|what if|how about)\b", re.I)
T = "challenge-testing-brief.md"
E = "examples/api-call-examples.md"
try:
    call("POST", "/v1/teardown")

    # ---------------------------------------------------------------- A. HTTP methods and paths
    for path in ("/v1/context", "/v1/tick", "/v1/reply", "/v1/teardown"):
        r = call("GET", path)
        rec("methods", f"GET {path}", f"{T}:33-70 (POST endpoint)", "405", r.status_code, "PASS" if r.status_code == 405 else "FAIL")
    for path in ("/v1/healthz", "/v1/metadata"):
        r = call("POST", path)
        rec("methods", f"POST {path}", f"{T}:150-159 (GET endpoint)", "405", r.status_code, "PASS" if r.status_code == 405 else "FAIL")
    r = call("GET", "/v1/nothing")
    rec("methods", "unknown path", "-", "404", r.status_code, "PASS" if r.status_code == 404 else "FAIL")

    # ---------------------------------------------------------------- B/C. healthz + metadata (Examples 1.1, 1.2)
    r = call("GET", "/v1/healthz", "healthz")
    j = r.json()
    rec("healthz", "fresh bot: 200, exact keys, all-zero counts", f"{E}:11-32 (Example 1.1)", "{status, uptime_seconds, contexts_loaded{4 zeros}}",
        f"{r.status_code} {sorted(j)} {j.get('contexts_loaded')}",
        "PASS" if r.status_code == 200 and set(j) == {"status", "uptime_seconds", "contexts_loaded"} and j["status"] == "ok"
        and j["contexts_loaded"] == {"category": 0, "merchant": 0, "customer": 0, "trigger": 0} and isinstance(j["uptime_seconds"], int) else "FAIL")
    r = call("GET", "/v1/metadata", "metadata")
    j = r.json()
    want = {"team_name", "team_members", "model", "approach", "contact_email", "version", "submitted_at"}
    rec("metadata", "200 with exactly the 7 documented fields (team_members is a list)", f"{T}:159-172, {E}:34-53 (Example 1.2)", sorted(want), sorted(j),
        "PASS" if r.status_code == 200 and set(j) == want and isinstance(j["team_members"], list) else "FAIL")
    unset = [k for k, v in j.items() if v == "TO_BE_SET" or v == ["TO_BE_SET"]]
    rec("metadata", "personal fields filled in (needed before submission)", f"{T}:159-172", "real team_name/team_members/contact_email/submitted_at",
        f"still TO_BE_SET: {unset}" if unset else "all filled", "AMBIGUOUS" if unset else "PASS")

    # ---------------------------------------------------------------- D. warmup: full base dataset (Examples 1.3, 1.4, 1.7)
    ack_ok, stored_ok, worst = True, True, 0.0
    for scope, pattern, key in (("category", "categories/*.json", "slug"), ("merchant", "merchants/*.json", "merchant_id"),
                                ("customer", "customers/*.json", "customer_id")):
        for obj in load(pattern):
            r = call("POST", "/v1/context", "context", json=env_(scope, obj[key], 1, obj))
            j = r.json()
            ack_ok &= r.status_code == 200 and set(j) == {"accepted", "ack_id", "stored_at"} and j["accepted"] is True and j["ack_id"] == f"ack_{obj[key]}_v1"
            stored_ok &= bool(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", j.get("stored_at", "")))
    rec("context", "255 base pushes: 200 {accepted:true, ack_id:'ack_<id>_v1', stored_at}", f"{T}:55-58, {E}:83-86", "all 255", "ok" if ack_ok else "mismatch", "PASS" if ack_ok else "FAIL")
    rec("context", "stored_at format YYYY-MM-DDTHH:MM:SS.mmmZ", f"{T}:57, {E}:85", "ms + Z", "ok" if stored_ok else "mismatch", "PASS" if stored_ok else "FAIL")
    j = call("GET", "/v1/healthz").json()
    rec("healthz", "after warmup counts are 5/50/200/0 (warmup passes only then)", f"{E}:144-155 (Example 1.7), {T}:269-276", {"category": 5, "merchant": 50, "customer": 200, "trigger": 0},
        j["contexts_loaded"], "PASS" if j["contexts_loaded"] == {"category": 5, "merchant": 50, "customer": 200, "trigger": 0} else "FAIL")

    # ---------------------------------------------------------------- E/F. version behaviour (Examples 1.5, 1.6)
    dentists = json.load(open(EXP / "categories" / "dentists.json", encoding="utf-8"))
    r = call("POST", "/v1/context", "context", json=env_("category", "dentists", 1, dentists))
    rec("context", "RE-POST SAME VERSION (idempotency check)", f"{E}:124-131 (Example 1.5); text {T}:51 says 'no-op'; website: 'Re-posting the same version is a no-op'",
        '409 {"accepted":false,"reason":"stale_version","current_version":1}', f"{r.status_code} {r.text.strip()}",
        "PASS" if r.status_code == 409 and r.json() == {"accepted": False, "reason": "stale_version", "current_version": 1} else "FAIL")
    rec("context", "same-version wording: text says 409 = 'higher version', example uses the SAME version", f"{T}:60 vs {E}:124-131", "one authoritative reading",
        "bot follows the example (exact request/response) and leaves state unchanged, which is also a 'no-op'", "AMBIGUOUS")
    r = call("POST", "/v1/context", "context", json=env_("category", "dentists", 2, dentists))
    rec("context", "higher version replaces (200, ack ..._v2)", f"{E}:133-142 (Example 1.6), {T}:52", "200 accepted ack_dentists_v2", f"{r.status_code} {r.json().get('ack_id')}",
        "PASS" if r.status_code == 200 and r.json().get("ack_id") == "ack_dentists_v2" else "FAIL")
    r = call("POST", "/v1/context", "context", json=env_("category", "dentists", 1, dentists))
    rec("context", "lower version -> 409 with the CURRENT version", f"{T}:60-62", '409 current_version 2', f"{r.status_code} {r.text.strip()}",
        "PASS" if r.status_code == 409 and r.json().get("current_version") == 2 else "FAIL")
    j = call("GET", "/v1/healthz").json()
    rec("context", "replacement is atomic and does not duplicate (category still 5)", f"{T}:52", 5, j["contexts_loaded"]["category"], "PASS" if j["contexts_loaded"]["category"] == 5 else "FAIL")

    # ---------------------------------------------------------------- H. error handling
    r = call("POST", "/v1/context", "context", json=env_("banana", "x", 1, {}))
    j = r.json()
    rec("context", "invalid scope -> 400 {accepted:false, reason:'invalid_scope', details}", f"{T}:65-68", "400 exact keys", f"{r.status_code} {sorted(j)} {j.get('reason')}",
        "PASS" if r.status_code == 400 and set(j) == {"accepted", "reason", "details"} and j["reason"] == "invalid_scope" and j["accepted"] is False else "FAIL")
    bad = [call("POST", "/v1/context", data="not json", headers={"Content-Type": "application/json"}),
           call("POST", "/v1/context", json={"scope": "merchant", "context_id": "m", "version": 1}),
           call("POST", "/v1/context", json={"scope": "merchant", "context_id": "m", "version": "1", "payload": {}}),
           call("POST", "/v1/context", json=[1, 2])]
    rec("context", "malformed bodies (non-JSON, no payload, string version, array) -> 400, never 500", f"{T}:65-68", "400 x4", [x.status_code for x in bad],
        "PASS" if all(x.status_code == 400 for x in bad) else "FAIL")
    for path in ("/v1/tick", "/v1/reply"):
        r = call("POST", path, data="not json", headers={"Content-Type": "application/json"})
        rec("errors", f"non-JSON body to {path} -> 4xx JSON, not a crash", f"{T}:470-481 (malformed = penalty)", "400", r.status_code, "PASS" if r.status_code == 400 else "FAIL")
    payload = {"merchant_id": "m_uni", "note": "₹299 🦷 आपका स्वागत है", "big": "x" * 480_000}
    r = call("POST", "/v1/context", "context", data=json.dumps(env_("merchant", "m_uni", 1, payload), ensure_ascii=False).encode("utf-8"),
             headers={"Content-Type": "application/json; charset=utf-8"})
    rec("context", "UTF-8 body (₹, emoji, Devanagari) with charset header + ~480 KB payload", f"{T}:33 (UTF-8), {T}:331 (500 KB cap)", "200", r.status_code, "PASS" if r.status_code == 200 else "FAIL")

    # ---------------------------------------------------------------- I/J/K. trigger push + tick (Examples 2.1, 2.2, 2.3)
    trg1 = json.load(open(EXP / "triggers" / "trg_001_research_digest_dentists.json", encoding="utf-8"))
    r = call("POST", "/v1/context", "context", json=env_("trigger", trg1["id"], 1, trg1))
    rec("context", "trigger push (top-level merchant_id/customer_id as in the data)", f"{E}:161-196 (Example 2.1)", "200 ack", f"{r.status_code} {r.json().get('ack_id')}",
        "PASS" if r.status_code == 200 else "FAIL")
    r = call("POST", "/v1/tick", "tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": [trg1["id"]]})
    j = r.json()
    a = j["actions"][0] if j.get("actions") else {}
    need = {"conversation_id", "merchant_id", "customer_id", "send_as", "trigger_id", "template_name", "template_params", "body", "cta", "suppression_key", "rationale"}
    rec("tick", "action has exactly the 11 documented fields", f"{E}:212-231 (Example 2.2), {T}:88-102", sorted(need), sorted(a),
        "PASS" if set(a) == need and list(j) == ["actions"] else "FAIL")
    rec("tick", "action content: merchant-facing, right ids, params list, key from trigger", f"{E}:212-231", "send_as=vera, customer_id=null, suppression_key=trigger's",
        {k: a.get(k) for k in ("send_as", "customer_id", "merchant_id", "trigger_id", "suppression_key")},
        "PASS" if a.get("send_as") == "vera" and a.get("customer_id") is None and a.get("merchant_id") == trg1["merchant_id"] and a.get("trigger_id") == trg1["id"]
        and a.get("suppression_key") == trg1["suppression_key"] and isinstance(a.get("template_params"), list) and a.get("body", "").strip() else "FAIL")
    rec("tick", "no URL in the body", f"{E}:564-570 (Example F.4: -3 per URL)", "no URL", "found" if re.search(r"https?://|www\.", a.get("body", "")) else "none",
        "FAIL" if re.search(r"https?://|www\.", a.get("body", "")) else "PASS")
    rec("tick", "the six fields the judge names as required are present", f"{E}:554 (Example F.2)", "conversation_id, send_as, trigger_id, cta, suppression_key, rationale",
        [k for k in ("conversation_id", "send_as", "trigger_id", "cta", "suppression_key", "rationale") if a.get(k)],
        "PASS" if all(a.get(k) for k in ("conversation_id", "send_as", "trigger_id", "cta", "suppression_key", "rationale")) else "FAIL")
    conv = a.get("conversation_id", "conv_x")
    r = call("POST", "/v1/tick", "tick", json={"now": "2026-04-26T10:40:00Z", "available_triggers": [trg1["id"]]})
    rec("tick", "same trigger listed again -> nothing (suppressed)", f"{E}:236-245 (Example 2.3), {T}:545 (restraint)", '{"actions": []}', r.text.strip(),
        "PASS" if r.status_code == 200 and r.json() == {"actions": []} else "FAIL")
    for label, body in (("empty list", {"now": "2026-04-26T10:45:00Z", "available_triggers": []}), ("no fields", {})):
        r = call("POST", "/v1/tick", "tick", json=body)
        rec("tick", f"idle tick ({label}) is valid", f"{T}:105, {T}:500", '{"actions": []}', r.text.strip(), "PASS" if r.status_code == 200 and r.json() == {"actions": []} else "FAIL")

    # ---------------------------------------------------------------- L-O. replies (Examples 2.4-2.7)
    r = reply(conv, "Yes please send the abstract. Also draft the patient WhatsApp.")
    j = r.json()
    rec("reply", "engaged reply -> send with body, cta, rationale", f"{E}:247-275 (Example 2.4), {T}:128-135", "{action:send, body, cta, rationale}", f"{j.get('action')} {sorted(j)}",
        "PASS" if r.status_code == 200 and j.get("action") == "send" and set(j) == {"action", "body", "cta", "rationale"} and j["body"].strip() else "FAIL")
    r = reply("conv_audit_auto_first", "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly.")
    j = r.json()
    rec("reply", "FIRST auto-reply of a conversation", f"{E}:277-301 (Example 2.5) says wait 14400; {E}:461-467 (Example 4.1 'Good bot response') says send once", "wait 14400 OR one short send",
        f"{j.get('action')} {j.get('wait_seconds', '')}", "AMBIGUOUS" if j.get("action") in ("send", "wait") else "FAIL")
    r = reply("conv_audit_no", "Not interested. Stop messaging me.")
    j = r.json()
    rec("reply", "hard no -> end with exactly {action, rationale}", f"{E}:303-324 (Example 2.6), {T}:143-146", '{"action":"end","rationale":...}', j,
        "PASS" if j.get("action") == "end" and set(j) == {"action", "rationale"} else "FAIL")
    j2 = reply("conv_audit_no", "hello?").json()
    rec("reply", "after end, nothing more on that conversation_id", f"{E}:324", "end again", j2.get("action"), "PASS" if j2.get("action") == "end" else "FAIL")
    j = reply("conv_audit_gst", "Btw can you also help me with my GST filing this month?").json()
    rec("reply", "off-topic (GST) -> polite decline that stays on mission, no URL", f"{E}:326-347 (Example 2.7)", "send; mentions CA / out of scope",
        f"{j.get('action')}: {str(j.get('body'))[:90]}", "PASS" if j.get("action") == "send" and re.search(r"\bCA\b|scope|expert|outside", j.get("body", ""), re.I) and not re.search(r"https?://", j.get("body", "")) else "FAIL")

    # ---------------------------------------------------------------- P/Q. adaptive injection + customer trigger (Examples 2.8, 2.9)
    cat3 = json.loads(json.dumps(dentists))
    cat3["digest"].append({"id": "d_2026W17_dci_radiograph_NEW", "kind": "compliance", "title": "DCI revised radiograph dose limits effective 2026-12-15",
                           "source": "DCI circular 2026-11-04", "summary": "Max dose drops 1.5 to 1.0 mSv per IOPA."})
    r = call("POST", "/v1/context", "context", json=env_("category", "dentists", 3, cat3))
    rec("context", "mid-test category update with a new digest item", f"{E}:349-378 (Example 2.8)", "200 ack_dentists_v3", f"{r.status_code} {r.json().get('ack_id')}",
        "PASS" if r.status_code == 200 and r.json().get("ack_id") == "ack_dentists_v3" else "FAIL")
    trg3 = json.load(open(EXP / "triggers" / "trg_003_recall_due_priya.json", encoding="utf-8"))
    call("POST", "/v1/context", "context", json=env_("trigger", trg3["id"], 1, trg3))
    r = call("POST", "/v1/tick", "tick", json={"now": "2026-04-26T11:00:00Z", "available_triggers": [trg3["id"]]})
    a = (r.json().get("actions") or [{}])[0]
    slots_in_body = all(s in a.get("body", "") for s in ("Wed 5 Nov", "Thu 6 Nov"))
    rec("tick", "customer-scoped recall: merchant_on_behalf + customer_id + the trigger's key + the real slots", f"{E}:380-436 (Example 2.9)",
        "send_as=merchant_on_behalf, customer_id=c_001_priya_for_m001, key recall:c_001_priya_for_m001:6mo, slots in body",
        {k: a.get(k) for k in ("send_as", "customer_id", "suppression_key")} | {"slots_in_body": slots_in_body},
        "PASS" if a.get("send_as") == "merchant_on_behalf" and a.get("customer_id") == "c_001_priya_for_m001" and a.get("suppression_key") == "recall:c_001_priya_for_m001:6mo" and slots_in_body else "FAIL")
    j = reply(a.get("conversation_id", "conv_x"), "2", cid="c_001_priya_for_m001", role="customer").json()
    rec("reply", "customer answers '2' -> booking confirmation for the second offered slot", f"{E}:429-433 ('Reply 1 for Wed, 2 for Thu')", "send mentioning Thu 6 Nov, 5pm",
        f"{j.get('action')}: {str(j.get('body'))[:80]}", "PASS" if j.get("action") == "send" and "Thu 6 Nov" in j.get("body", "") else "FAIL")

    # ---------------------------------------------------------------- R/S/T. replay scenarios (Examples 4.1-4.3)
    trg22 = json.load(open(EXP / "triggers" / "trg_022_cde_webinar_dentists.json", encoding="utf-8"))
    call("POST", "/v1/context", "context", json=env_("trigger", trg22["id"], 1, trg22))
    r = call("POST", "/v1/tick", "tick", json={"now": "2026-04-26T11:10:00Z", "available_triggers": [trg22["id"]]})
    a = (r.json().get("actions") or [{}])[0]
    conv41 = a.get("conversation_id", "conv_41")
    AUTO = "Thank you for contacting Dr. Meera's Dental Clinic! Our team will respond shortly."
    seq = [reply(conv41, AUTO, turn=t).json() for t in (2, 3, 4, 5)]
    got = [(x["action"], x.get("wait_seconds")) for x in seq]
    rec("reply", "auto-reply hell: 4 identical canned texts (turn 1 is the bot's own tick action)", f"{E}:444-488 (Example 4.1); {T}:308 (Phase 4 #1)",
        "send, wait 86400, end (then end)", got, "PASS" if got[:3] == [("send", None), ("wait", 86400), ("end", None)] and got[3][0] == "end" else "FAIL")
    j = reply("conv_replay_intent", "Ok, let's do it. What's next?", turn=3).json()
    rec("reply", "intent transition -> action now, no qualifying question", f"{E}:490-515 (Example 4.2); {T}:309 (Phase 4 #2)", "send without would you/do you/can you tell/what if/how about",
        f"{j.get('action')}: {str(j.get('body'))[:80]}", "PASS" if j.get("action") == "send" and not QUALIFYING.search(j.get("body", "")) else "FAIL")
    j = reply("conv_replay_hostile", "Why are you bothering me. This is useless. Stop sending these.").json()
    rec("reply", "hostile + stop -> graceful end", f"{E}:517-538 (Example 4.3); {T}:310 (Phase 4 #3)", '{"action":"end", ...}', j.get("action"), "PASS" if j.get("action") == "end" else "FAIL")
    j = reply("conv_replay_hostile2", "You are all useless idiots").json()
    rec("reply", "abuse WITHOUT a stop request -> stays on mission (calm reply), not an instant end", f"{T}:310 ('abuse, then asks an unrelated question ... stay on-mission politely')",
        "send", j.get("action"), "PASS" if j.get("action") == "send" else "FAIL")

    # ---------------------------------------------------------------- V/W. timeouts, retry, state
    budgets = {"healthz": 2, "metadata": 2, "context": 5, "tick": 10, "reply": 10}
    for kind, limit in budgets.items():
        worst_t = max(TIMES.get(kind, [0]))
        rec("timeouts", f"slowest {kind} call in this run", f"{E}:607-613 (latency budget {limit} s); hard limit {T}:148,331 (30 s)", f"< {limit} s", f"{worst_t:.3f} s", "PASS" if worst_t < limit else "FAIL")
    codes = [call("GET", "/v1/healthz", "healthz").status_code for _ in range(3)]
    rec("retry", "healthz answered 3 times in a row (the judge retries it x3; 3 failures = offline)", f"{E}:609; {T}:157", "200 x3", codes, "PASS" if codes == [200, 200, 200] else "FAIL")
    j = call("GET", "/v1/healthz").json()
    rec("state", "contexts persist across calls until teardown", f"{T}:50-53", "counts still loaded", j["contexts_loaded"], "PASS" if j["contexts_loaded"]["merchant"] >= 50 else "FAIL")
    r = call("POST", "/v1/teardown")
    j = call("GET", "/v1/healthz").json()
    rec("state", "POST /v1/teardown wipes everything", f"{T}:489-491 (§11)", "all zero", j["contexts_loaded"], "PASS" if r.status_code == 200 and all(v == 0 for v in j["contexts_loaded"].values()) else "FAIL")
finally:
    if proc is not None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    if logfile is not None:
        logfile.close()

if logfile is not None:
    log_path = ROOT / "tests" / "_audit_contract_server.log"
    text = log_path.read_text(encoding="utf-8", errors="replace")
    rec("server", "no Traceback in the server log", "-", "none", "found" if "Traceback" in text else "none", "FAIL" if "Traceback" in text else "PASS")
    try:
        log_path.unlink()
    except OSError:
        pass

width = [10, 62, 50, 44, 44]
print(f"{'AREA':10} | {'CHECK':62} | STATUS")
for area, check, source, expected, actual, status in ROWS:
    print(f"{area:10} | {check[:62]:62} | {status:9} | src: {source[:70]}")
    if status != "PASS":
        print(f"{'':10}   expected: {expected[:140]}\n{'':10}   actual:   {actual[:140]}")
counts = {s: sum(1 for r in ROWS if r[5] == s) for s in ("PASS", "AMBIGUOUS", "FAIL")}
print(f"\nSUMMARY: {counts['PASS']} PASS, {counts['AMBIGUOUS']} AMBIGUOUS (source conflicts / pending input), {counts['FAIL']} FAIL")

out = ROOT / "out"
out.mkdir(exist_ok=True)
md = ["| Area | Check | Source | Expected | Actual | Status |", "|---|---|---|---|---|---|"]
for area, check, source, expected, actual, status in ROWS:
    md.append("| " + " | ".join(x.replace("|", "/").replace("\n", " ")[:150] for x in (area, check, source, expected, actual, status)) + " |")
(out / "audit_contract_replay.md").write_text("\n".join(md), encoding="utf-8")
sys.exit(1 if counts["FAIL"] else 0)
