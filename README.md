# Vera bot — Magicpin VERA AI Challenge

A FastAPI service that plays magicpin's merchant WhatsApp assistant "Vera". It exposes the five contract endpoints
(`POST /v1/context`, `POST /v1/tick`, `POST /v1/reply`, `GET /v1/healthz`, `GET /v1/metadata`, plus optional
`POST /v1/teardown`) and composes each outbound message from the four contexts the judge pushes: category, merchant,
trigger, and (for customer-facing sends) customer.

## Approach

`compose(category, merchant, trigger, customer)` ([composer.py](composer.py)) builds a context dict — the merchant's
own state, the category's voice/offer catalog, the trigger's payload, arithmetic already done in code (`derive_facts`,
so the LLM never has to compute a percentage or a "days remaining") — and sends it to an LLM with a versioned system
prompt ([prompts.py](prompts.py), `composer_v2`: 18 rules covering grounding, one signal, one CTA, voice, language,
no filler/URLs, and no internal jargon). The LLM's JSON draft passes through a post-hoc validator
([validator.py](validator.py)) before anything is sent:

- **Hard** rejects (message never goes out as drafted; one retry with feedback, then the deterministic fallback):
  URLs, category taboo words, numbers not present anywhere in the input context, more than one call-to-action,
  near-verbatim repeats of a previous message, near-copies of the challenge's own case-study examples
  (word-order ratio ≥ 0.65 or 6-gram containment ≥ 35%), and internal jargon (field names, `payload`, `placeholder`,
  snake_case identifiers) leaking into merchant-facing text.
- **Soft** flags (one retry, then kept if still present): language mismatch, buried CTA, greeting preamble,
  over-length.

If the LLM is unreachable, too slow, or every draft still fails after retry, [fallback.py](fallback.py) builds a
grounded message from the same category/merchant/trigger/customer data with zero LLM involvement — the bot never
sends an empty or malformed body.

`/v1/tick` ([tick.py](tick.py)) composes drafts for up to 20 triggers in parallel inside an 8s budget, in urgency
order, deduping on `(merchant, customer, suppression_key)` and skipping only hostile merchants and customers who
opted out. `/v1/reply` ([replies.py](replies.py)) is a small decision tree in front of the LLM: auto-reply detection,
explicit opt-out, plain decline, "let's do it" → immediate action (no re-qualifying question), off-topic → polite
decline and back on-mission, "busy" → `wait`, everything else → LLM answer grounded in the same validator.

## Model / provider

**OpenCode Zen (`deepseek-v4.1-flash`)** is the sole configured LLM provider ([llm.py](llm.py); set `OPENCODE_API_KEY`
and, optionally, `OPENCODE_MODEL` in `.env`). Temperature 0, a fixed seed, and an input-hash cache
(`composer.py`/`_cache_key`) make `compose()` deterministic for identical inputs. `max_tokens` is set high (1500 for
compose, 900 for reply) because this model spends hidden reasoning tokens out of the same completion budget before
writing its answer — that ceiling is a model-capability allowance, not the requested message length, which is still
governed by the prompt (35–75 words) and enforced independently by the validator's length check.

**Known tradeoff:** this model is noticeably slower than a non-reasoning model — in this session's 30-pair validation
it averaged ~18s per call (range 7–41s), which is above the examples table's 10s guidance and, in the worst case,
close to the challenge's 30s hard limit. There is currently no second LLM provider configured, so when a call is slow
or fails, the bot falls straight to the deterministic local fallback rather than to another model. That fallback is
always grounded and always fast, but plainer than an LLM draft. If a faster non-reasoning model becomes available
under the same provider account, swapping `OPENCODE_MODEL` is the only change needed.

## What additional context would have helped most

1. **Which of the 30 canonical pairs the judge actually replays** — 13/30 pairs have `placeholder` triggers with no
   event detail, so the bot can only work from merchant/customer/category facts for those; a hint about what real
   payload data looks like for those trigger kinds would sharpen them.
2. **The exact judging weight of latency vs. quality** — the brief gives a 30s hard limit and a softer 10s example
   budget but no scoring curve between them, which made the provider/latency tradeoff above a judgment call rather
   than an optimization.
3. **Whether the judge's replay phase re-lists a trigger already sent in the tick phase** — if it does, the bot's own
   dedupe (`(merchant, customer, suppression_key)`) would silently return no action for it; this is documented as a
   risk in `MAGICPIN_VERA_AI_STEPS_1_TO_6.md` but not resolved, since the material doesn't say.

## Design decisions worth knowing (traced to the material)

- `POST /v1/context`: same-or-lower version → `409 {"accepted":false,"reason":"stale_version",...}`, matching the
  worked example in `examples/api-call-examples.md` (Example 1.5) over the testing brief's looser prose.
- No `expires_at` filtering in `/v1/tick`: the judge's own `available_triggers` list is already "active right now",
  and the simulator sends the real UTC clock against dataset dates months out — filtering by expiry would silently
  drop every trigger.
- URLs are never emitted, even though the brief says they're "allowed when they add value": the worked example
  (F.4) hard-fails on any URL with a -3 penalty, so the strictest reading is followed.
- Case-study similarity uses a high word-order-ratio bar (0.65) plus a 6-gram containment check (35%): a faithful
  message about the *same* facts as a case study (same slots, price, names) naturally overlaps it in word order
  without copying it, so a low bar produced false positives during testing.

Full requirement-by-requirement traceability, the conflicts found in the material and how they were resolved, and
every verification run are in [MAGICPIN_VERA_AI_STEPS_1_TO_6.md](MAGICPIN_VERA_AI_STEPS_1_TO_6.md).

## Running locally

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in OPENCODE_API_KEY, TEAM_NAME, TEAM_MEMBERS, CONTACT_EMAIL
python -m uvicorn bot:app --host 0.0.0.0 --port 8080
```

## Running the tests

```bash
python tests/run_all.py                    # full offline suite (contract, composer, validator, replies, tick — ~360 checks, no LLM key needed)
python llm.py --check                      # confirm the configured provider/model answers
python tests/live_compose_30_pairs.py      # compose the 30 canonical pairs with the real LLM and print them for review
python tests/audit_contract_replay.py      # HTTP contract replay against examples/api-call-examples.md
```

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `OPENCODE_API_KEY` | Yes | OpenCode Zen API key (sole LLM provider) |
| `OPENCODE_MODEL` | No (defaults to `deepseek-v4.1-flash`) | Model id, as OpenCode Zen's catalog lists it |
| `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL` | Yes, before submission | Served verbatim by `GET /v1/metadata` |
| `SUBMITTED_AT` | Set at submission time | ISO 8601 timestamp, served by `GET /v1/metadata` |

Never commit `.env`; `.env.example` documents every variable with no real values.

## Deployment notes

Run a **single worker/process** — state (contexts, conversations, sent-trigger dedupe) lives in memory, so multiple
workers would each see a different, incomplete state. Set environment variables in the host's dashboard, not by
uploading `.env`. Start command: `uvicorn bot:app --host 0.0.0.0 --port $PORT`.
