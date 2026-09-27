"""Run every verification script (Steps 1-6) and print one summary.

Run from E:\\MAGICPIN:  python tests/run_all.py
All of them are offline (mocked LLM / no key needed). The LIVE quality check is separate:
    python tests/live_compose_30_pairs.py        (needs GROQ_API_KEY and/or OPENROUTER_API_KEY in .env)
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    ("Step 1  dataset + 30 pairs", "verify_step1_dataset.py"),
    ("Step 2  endpoints", "verify_step2_endpoints.py"),
    ("Step 3  composer + LLM failover", "verify_step3_composer.py"),
    ("Step 4  validator + fallback", "verify_step4_validator.py"),
    ("Step 5  reply engine", "verify_step5_replies.py"),
    ("Step 6  tick policy + adaptation", "verify_step6_tick.py"),
    ("AUDIT   endpoint contract + examples replay", "audit_contract_replay.py"),
    ("AUDIT   context, guards, replies, tick", "audit_context_and_guards.py"),
]

results = []
for label, script in SCRIPTS:
    t0 = time.time()
    proc = subprocess.run([sys.executable, str(ROOT / "tests" / script)], cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    lines = proc.stdout.splitlines()
    passed = sum(1 for line in lines if line.startswith("PASS") or re.search(r"\| PASS +\|", line))
    failed = [line for line in lines if line.startswith("FAIL") or re.search(r"\| FAIL +\|", line)]
    results.append((label, proc.returncode == 0, passed, failed, time.time() - t0))
    print(f"{'OK  ' if proc.returncode == 0 else 'FAIL'}  {label:36} {passed:3} checks passed  ({time.time() - t0:.1f}s)")
    for line in failed:
        print("        " + line)
    if proc.returncode != 0 and not failed:
        print("        " + (proc.stderr.strip().splitlines() or ["(no output)"])[-1])

total = sum(r[2] for r in results)
ok = all(r[1] for r in results)
print(f"\n{'ALL STEPS PASS' if ok else 'SOME STEPS FAILED'}: {total} checks passed across {len(results)} scripts")
sys.exit(0 if ok else 1)
