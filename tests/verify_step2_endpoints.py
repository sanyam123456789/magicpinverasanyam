"""Step 2 verification: the 5 endpoints (+ teardown) behave exactly like the examples.

Run from E:\\MAGICPIN:  python tests/verify_step2_endpoints.py
By default it starts a local uvicorn server on port 8765 and stops it afterwards.
To test an already running / public bot instead:  set BOT_URL=https://host  (then it does not spawn one).
Exit code 0 = every check passed.
"""
import glob
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
EXP = ROOT / "expanded"

failures = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        failures.append(name)


def envelope(scope, cid, version, payload):
    return {"scope": scope, "context_id": cid, "version": version, "payload": payload, "delivered_at": "2026-04-26T09:45:00Z"}


BASE = os.environ.get("BOT_URL", "").rstrip("/")
proc = None
logfile = None
if not BASE:
    port = 8765
    BASE = f"http://127.0.0.1:{port}"
    logfile = open(ROOT / "tests" / "_step2_server.log", "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bot:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(ROOT), stdout=logfile, stderr=subprocess.STDOUT,
    )
    for _ in range(60):
        try:
            if requests.get(BASE + "/v1/healthz", timeout=1).status_code == 200:
                break
        except Exception:
            time.sleep(0.25)
    else:
        print("FAIL  server did not start")
        proc.terminate()
        sys.exit(1)


def call(method, path, timeout=12, **kw):
    t0 = time.time()
    r = requests.request(method, BASE + path, timeout=timeout, **kw)
    return r, time.time() - t0


try:
    # ---- clean start (Example 1.1) -------------------------------------------------
    call("POST", "/v1/teardown")
    r, dt = call("GET", "/v1/healthz")
    j = r.json()
    check("healthz 200 with status/uptime/contexts_loaded", r.status_code == 200 and j.get("status") == "ok"
          and isinstance(j.get("uptime_seconds"), int) and set(j["contexts_loaded"]) == {"category", "merchant", "customer", "trigger"})
    check("healthz all zeros on a fresh bot (Example 1.1)", all(v == 0 for v in j["contexts_loaded"].values()))
    check("healthz under 2s (examples table)", dt < 2, f"{dt:.3f}s")

    r, dt = call("GET", "/v1/metadata")
    j = r.json()
    need = {"team_name", "team_members", "model", "approach", "contact_email", "version", "submitted_at"}
    check("metadata 200 with all 7 fields", r.status_code == 200 and need <= set(j) and isinstance(j["team_members"], list))
    check("metadata under 2s", dt < 2, f"{dt:.3f}s")

    # ---- context: accept / stale / replace (Examples 1.3, 1.5, 1.6) ----------------
    dentists = json.load(open(EXP / "categories" / "dentists.json", encoding="utf-8"))
    r, dt = call("POST", "/v1/context", json=envelope("category", "dentists", 1, dentists))
    j = r.json()
    check("context v1 -> 200 accepted + ack_id + stored_at", r.status_code == 200 and j.get("accepted") is True
          and j.get("ack_id") == "ack_dentists_v1" and str(j.get("stored_at", "")).endswith("Z"))
    check("context under 5s", dt < 5, f"{dt:.3f}s")

    r, _ = call("POST", "/v1/context", json=envelope("category", "dentists", 1, dentists))
    check("same version again -> 409 stale_version (Example 1.5)", r.status_code == 409
          and r.json() == {"accepted": False, "reason": "stale_version", "current_version": 1}, r.text[:120])

    r, _ = call("POST", "/v1/context", json=envelope("category", "dentists", 2, dentists))
    check("higher version replaces -> 200 (Example 1.6)", r.status_code == 200 and r.json().get("ack_id") == "ack_dentists_v2")
    r, _ = call("POST", "/v1/context", json=envelope("category", "dentists", 1, dentists))
    check("lower version -> 409 with current_version 2", r.status_code == 409 and r.json().get("current_version") == 2)
    check("replace did not create a duplicate (category count == 1)",
          call("GET", "/v1/healthz")[0].json()["contexts_loaded"]["category"] == 1)

    # ---- context: bad input -> 400, never 500 --------------------------------------
    r, _ = call("POST", "/v1/context", json=envelope("banana", "x", 1, {}))
    j = r.json()
    check("invalid scope -> 400 invalid_scope", r.status_code == 400 and j.get("accepted") is False and j.get("reason") == "invalid_scope" and "details" in j)
    r, _ = call("POST", "/v1/context", data="this is not json", headers={"Content-Type": "application/json"})
    check("non-JSON body -> 400", r.status_code == 400 and r.json().get("accepted") is False)
    r, _ = call("POST", "/v1/context", json={"scope": "merchant", "context_id": "m1", "version": 1})
    check("missing payload -> 400", r.status_code == 400)
    r, _ = call("POST", "/v1/context", json={"scope": "merchant", "context_id": "m1", "version": "1", "payload": {}})
    check("string version -> 400", r.status_code == 400)
    r, _ = call("POST", "/v1/context", json=[1, 2, 3])
    check("JSON array body -> 400", r.status_code == 400)

    # ---- warmup: full base dataset (Example 1.7) -----------------------------------
    call("POST", "/v1/teardown")
    worst = 0.0
    all_ok = True
    for scope, pattern, key in (("category", "categories/*.json", "slug"), ("merchant", "merchants/*.json", "merchant_id"),
                                ("customer", "customers/*.json", "customer_id")):
        for f in glob.glob(str(EXP / pattern)):
            obj = json.load(open(f, encoding="utf-8"))
            r, dt = call("POST", "/v1/context", json=envelope(scope, obj[key], 1, obj))
            worst = max(worst, dt)
            all_ok &= (r.status_code == 200)
    check("all 255 base contexts accepted", all_ok)
    j = call("GET", "/v1/healthz")[0].json()
    check("healthz shows 5/50/200/0 after warmup (Example 1.7)", j["contexts_loaded"] == {"category": 5, "merchant": 50, "customer": 200, "trigger": 0}, str(j["contexts_loaded"]))

    # ---- triggers arrive during the test (Example 2.1) -----------------------------
    for f in glob.glob(str(EXP / "triggers" / "*.json")):
        obj = json.load(open(f, encoding="utf-8"))
        r, dt = call("POST", "/v1/context", json=envelope("trigger", obj["id"], 1, obj))
        worst = max(worst, dt)
        all_ok &= (r.status_code == 200)
    check("all 100 triggers accepted", all_ok)
    check("healthz shows 100 triggers", call("GET", "/v1/healthz")[0].json()["contexts_loaded"]["trigger"] == 100)
    check("slowest /v1/context call under 5s", worst < 5, f"{worst:.3f}s")

    # ---- 500 KB payload cap (testing brief §5) -------------------------------------
    big = {"merchant_id": "m_big", "blob": "x" * 480_000}
    r, _ = call("POST", "/v1/context", json=envelope("merchant", "m_big", 1, big))
    check("~480 KB context payload accepted", r.status_code == 200)

    # ---- tick / reply skeleton shapes (Examples 2.3, 2.4) --------------------------
    r, dt = call("POST", "/v1/tick", json={"now": "2026-04-26T10:35:00Z", "available_triggers": ["trg_001_research_digest_dentists"]})
    check("tick -> 200 {'actions': [...]}", r.status_code == 200 and isinstance(r.json().get("actions"), list))
    check("tick under 10s", dt < 10, f"{dt:.3f}s")
    r, _ = call("POST", "/v1/tick", json={})
    check("tick with no fields still 200", r.status_code == 200 and "actions" in r.json())
    r, _ = call("POST", "/v1/tick", data="nope", headers={"Content-Type": "application/json"})
    check("tick with non-JSON -> 400 (not 500)", r.status_code == 400)

    r, dt = call("POST", "/v1/reply", json={"conversation_id": "conv_x", "merchant_id": "m_001_drmeera_dentist_delhi", "customer_id": None,
                                            "from_role": "merchant", "message": "Yes please", "received_at": "2026-04-26T10:42:00Z", "turn_number": 2})
    check("reply -> 200 with action in {send, wait, end}", r.status_code == 200 and r.json().get("action") in {"send", "wait", "end"})
    check("reply under 10s", dt < 10, f"{dt:.3f}s")

    # ---- teardown ------------------------------------------------------------------
    call("POST", "/v1/teardown")
    check("teardown wipes everything", all(v == 0 for v in call("GET", "/v1/healthz")[0].json()["contexts_loaded"].values()))

    # ---- in-process store checks: atomic replace + thread safety -------------------
    from store import Store
    s = Store()
    s.put_context("merchant", "m1", 1, {"v": 1})
    s.put_context("merchant", "m1", 2, {"v": 2})
    check("store: higher version replaces payload", s.get("merchant", "m1") == {"v": 2})
    check("store: lower version does not overwrite", s.put_context("merchant", "m1", 1, {"v": 99}) == (False, 2) and s.get("merchant", "m1") == {"v": 2})

    def worker(n):
        for v in range(1, 200):
            s.put_context("merchant", "race", v * 8 + n, {"v": v * 8 + n})
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check("store: concurrent pushes end on the highest version", s.contexts[("merchant", "race")]["version"] == 199 * 8 + 7)

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
    log = (ROOT / "tests" / "_step2_server.log").read_text(encoding="utf-8", errors="replace")
    check("server log has no Traceback", "Traceback" not in log)
    try:
        (ROOT / "tests" / "_step2_server.log").unlink()
    except OSError:
        pass

print("\nRESULT:", "ALL CHECKS PASSED" if not failures else f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
