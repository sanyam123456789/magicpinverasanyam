# HANDOFF: Magicpin VERA AI Challenge (read this first in the new chat)

Written 2026-09-27 (IST, ~03:00). **Deadline: today 2026-09-27 15:00** (told by the user; official material says Not specified).
Project folder: `E:\MAGICPIN`. User writes Hinglish/English; reply in simple Hinglish.

## 0. How the user wants me to work (IMPORTANT)
- **Ask / wait for a go-ahead before starting or running anything** unless the prompt explicitly says to. The user got angry when I acted after a plain yes/no question, and the last tool call (live audit) was rejected because chat limit was close.
- Only use what the provided material says. No invented requirements. Mark gaps as "Not specified in the provided material". Flag conflicts between sources and say which one is followed.
- Do not over-engineer. Do not jump to later steps. Explain in Hinglish.
- Never ask for API keys in chat. Keys live only in `E:\MAGICPIN\.env` (user fills it).
- **Tooling gotcha:** never put regex/escape sequences (`\b`, `\u...`) in heredoc Python patch scripts (the tool layer collapses `\\`, `\b` became a backspace byte before). Use the Edit/Write tools or `chr(92)`.

## 1. The challenge (from the pack: 5 docs, examples/, judge_simulator.py, website screenshots)
Build a public HTTP bot that acts like magicpin's "Vera" merchant WhatsApp assistant. Judge calls 5 endpoints: `POST /v1/context`, `POST /v1/tick`, `POST /v1/reply`, `GET /v1/healthz`, `GET /v1/metadata` (+ optional `POST /v1/teardown`). Bot composes messages from 4 contexts (category, merchant, trigger, optional customer). Judge (LLM) scores 0-10 on 5 dimensions (Specificity, Category fit, Merchant fit, Trigger relevance/Decision quality, Engagement compulsion) with penalties (fabrication -2, internal jargon -1, URL -3, repeat -2, timeouts, malformed). Top 10 get replay tests (auto-reply, intent transition, hostile/off-topic). FAQ: "score depends on fresh scenarios, not the 30 pairs".
Submission (per pack): one **public base URL** + keep bot live; README (1 page, website says "can"), `submission.jsonl` (30 lines, brief §7), `bot.py`; portal fields Not specified. Solo only.

## 2. DONE (Steps 1-6 + final audit) — all in `E:\MAGICPIN`
- Data: `expanded/` generated (50 merchants, 200 customers, 100 triggers, 30 canonical pairs in `expanded/test_pairs.json`; 13 of the 30 are `placeholder` triggers; 9 are customer-facing).
- Code: `bot.py` (FastAPI app, all endpoints, exposes `compose`), `store.py`, `config.py` (.env loader), `llm.py` (Groq primary, OpenRouter automatic fallback, shared time budget), `prompts.py` (`composer_v2`, 18 rules, 26 kind guidances), `composer.py`, `validator.py` (hard/soft guards), `fallback.py` (deterministic messages), `references.py` (case-study similarity guard only), `replies.py` (reply engine), `tick.py` (tick policy), `requirements.txt`, `.env.example`, `.gitignore`.
- Tests: `python tests/run_all.py` -> **ALL STEPS PASS: 359 checks across 8 scripts** (steps 1-6 + `audit_contract_replay.py` + `audit_context_and_guards.py`).
- Docs: `MAGICPIN_VERA_AI_STEPS_1_TO_6.md` (source of truth: requirements R01-R55, conflicts C1-C14, traceability matrix, risks, "Final Audit Before Step 7" with discrepancy table). `PROJECT-GUIDE-HINGLISH.md` (older overview).
- **Final audit verdict: GREEN — Steps 1-6 are ready for live validation** (offline only).
- `.env` now exists with keys. `python llm.py --check` shows **groq OK model=openai/gpt-oss-120b (~1.2 s)** and **openrouter OK model=meta-llama/llama-3.3-70b-instruct (~1.5 s)**. (`GROQ_MODEL=openai/gpt-oss-120b` set in .env; default llama-3.3-70b-versatile does not exist for this key.)

## 3. Key design decisions (all traced to the pack; see doc for sources)
- `POST /v1/context`: same or lower version -> **409** `{"accepted":false,"reason":"stale_version","current_version":N}` (Example 1.5); higher replaces; 400 for bad scope/body.
- Latency: hard limit 30 s, examples table 10 s; bot uses tick 8 s, compose 6 s, reply 6.5 s.
- Tick: only judge's `available_triggers`; **no `expires_at` filter** (simulator sends real UTC clock); max 20 actions, urgency order; several triggers of one merchant may go in one tick (FAQ); dedupe on `(merchant, customer, suppression_key)`; skip only hostile merchants and customers who said STOP; missing merchant/category/customer context -> skip.
- Replies: auto-reply -> send once, then wait 86400, then end (Example 4.1; counted per merchant since simulator changes conversation_id); opt-out -> end that conversation only (Ex 2.6), opt-out+hostile -> merchant suppressed (Ex 4.3); intent -> action without qualifying phrases; off-topic (GST) -> polite decline; "busy/kal" -> wait 1800/86400.
- Composer: LLM (temp 0, seed, input-hash cache) -> validator (URL, taboo, ungrounded numbers, multiple asks, repeat, case-study copy (ratio 0.65 / 6-gram 35%), internal jargon; soft: language, CTA placement, preamble) -> one retry -> deterministic fallback. No URLs ever. Arithmetic done in code (derived facts).

## 4. LEFT TO DO (in order)
1. **Live audit (NOT yet run):** `cd E:\MAGICPIN` then `python tests/live_audit_30_pairs.py` (needs the user's OK; uses a few API credits). Writes `out/live_audit_report.md` + `out/live_audit_30_pairs.jsonl`. Checks: 14 checks per message, LLM-auditor second opinion, failover drill, determinism probe. Read every `REVIEW` item and all 30 bodies. Watch: `source` should be `llm:groq` (not `fallback`), latency mostly < 8 s, few retries. **Risk:** `openai/gpt-oss-120b` is a reasoning model, may be slow or return empty content because reasoning tokens eat `max_tokens=450`; if many fallbacks/empties, either add Groq's `reasoning_effort` low setting in `llm.py` or pick a non-reasoning model (`python llm.py --models groq`).
2. Fill `.env` personal fields if not done: `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL` (public via /v1/metadata); `SUBMITTED_AT` at submission time.
3. **Step 7:** run `judge_simulator.py` (edit its config: `BOT_URL`, `LLM_PROVIDER` groq/openrouter, `LLM_API_KEY` typed by the user, `LLM_MODEL`; set `TEST_SCENARIO = "full_evaluation"` — default `"all"` scores nothing). Improve weakest dimension. Do not overfit to it.
4. **Step 8:** deploy to a public URL. Always-on host, **single worker/process** (state is in memory; multiple workers would split state), env vars set in the host's dashboard (do not upload `.env`), start command like `uvicorn bot:app --host 0.0.0.0 --port $PORT`. Recommended Render or Railway (GitHub repo); ngrok only for testing. User must create account/payment/login. Then run the simulator and `tests/audit_contract_replay.py` against the public URL (`set BOT_URL=https://...`).
5. **Step 9:** stress (10 req/s), restart behaviour, LLM quota.
6. **Step 10:** README (1 page: approach, model choice, tradeoffs, what extra context would help), `submission.jsonl` (30 lines from the live audit output: `test_id, body, cta, send_as, suppression_key, rationale`), keep `bot.py`; `conversation_handlers.py` optional (skipped so far).
7. **Step 11:** user submits on the portal, keeps the bot live, no redeploys during evaluation.

## 5. Known residual risks
Live LLM quality/hallucination/latency unverified; model names may change; 13/30 pairs are placeholder triggers (no event details); replay scenarios may re-list an already-sent trigger (dedupe returns empty) — documented, not fixed; regional-language customers get plain English; in-memory state; 10 req/s untested; 3 source ambiguities kept as documented (same-version wording, first auto-reply Ex 2.5 vs 4.1, metadata values).

## 6. Handy commands (PowerShell, in `E:\MAGICPIN`)
- `python tests/run_all.py` — full offline suite (expect 359 checks).
- `python llm.py --check` / `python llm.py --models groq llama` — provider check / model list.
- `python -m uvicorn bot:app --host 127.0.0.1 --port 8080` — run bot locally.
- `python tests/audit_contract_replay.py` — HTTP contract audit (spawns its own server, or use `BOT_URL`).
