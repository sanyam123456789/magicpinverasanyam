"""Vera challenge bot: HTTP surface (FastAPI).

Run:  python -m uvicorn bot:app --host 0.0.0.0 --port 8080

Endpoints follow challenge-testing-brief.md §2 and examples/api-call-examples.md.
"""
import logging
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import llm
import replies
import tick as ticker
from composer import compose  # noqa: F401  (challenge-brief.md §7.1: bot.py exposes compose())
from config import env
from store import SCOPES, Store, utc_now_iso

DEFAULT_APPROACH = (
    "Trigger-routed LLM composer over category+merchant+trigger(+customer) contexts (OpenCode Zen / DeepSeek V4.1 Flash): one "
    "strongest signal per message, temperature 0 + input-hash cache for determinism, post-LLM validator (grounded numbers, one CTA, "
    "language, taboo words, no URLs, no copying) with a deterministic local fallback when the LLM is slow/unavailable/rejected, and a "
    "rule-first reply engine (auto-reply detection, opt-out, intent-to-action, off-topic handling)."
)
log = logging.getLogger("vera")


@asynccontextmanager
async def lifespan(_app):
    # The judge may call up to 10 requests/second (testing brief §5) and each tick/reply can wait on an LLM for a few
    # seconds, so allow more concurrent worker threads than the default 40.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 100
    yield


app = FastAPI(title="Vera challenge bot", lifespan=lifespan)
store = Store()


def _context_error(status: int, reason: str, details: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"accepted": False, "reason": reason, "details": details})


async def _read_json(request: Request):
    """Return (parsed_json, None) or (None, error_response) for an unreadable body."""
    try:
        return await request.json(), None
    except Exception:
        return None, JSONResponse(status_code=400, content={"error": "malformed_json", "details": "request body is not valid JSON"})


@app.get("/v1/healthz")
async def healthz():
    return {"status": "ok", "uptime_seconds": store.uptime_seconds(), "contexts_loaded": store.counts()}


@app.get("/v1/metadata")
async def metadata():
    # Team details come from .env / environment: they must be supplied by the participant.
    members = [m.strip() for m in env("TEAM_MEMBERS", "TO_BE_SET").split(",") if m.strip()]
    return {
        "team_name": env("TEAM_NAME", "TO_BE_SET"),
        "team_members": members,
        "model": env("BOT_MODEL_LABEL") or llm.label(),
        "approach": env("BOT_APPROACH") or DEFAULT_APPROACH,
        "contact_email": env("CONTACT_EMAIL", "TO_BE_SET"),
        "version": env("BOT_VERSION", "0.1.0"),
        "submitted_at": env("SUBMITTED_AT", "TO_BE_SET"),
    }


@app.post("/v1/context")
async def push_context(request: Request):
    body, error = await _read_json(request)
    if error is not None:
        return _context_error(400, "malformed_json", "request body is not valid JSON")
    if not isinstance(body, dict):
        return _context_error(400, "malformed_body", "request body must be a JSON object")

    scope = body.get("scope")
    if scope not in SCOPES:
        return _context_error(400, "invalid_scope", f"scope must be one of {list(SCOPES)}")

    context_id = body.get("context_id")
    version = body.get("version")
    payload = body.get("payload")
    if not isinstance(context_id, str) or not context_id:
        return _context_error(400, "malformed_body", "context_id must be a non-empty string")
    if isinstance(version, bool) or not isinstance(version, int):
        return _context_error(400, "malformed_body", "version must be an integer")
    if not isinstance(payload, dict):
        return _context_error(400, "malformed_body", "payload must be a JSON object")

    accepted, current_version = store.put_context(scope, context_id, version, payload)
    if not accepted:
        return JSONResponse(
            status_code=409,
            content={"accepted": False, "reason": "stale_version", "current_version": current_version},
        )
    return {"accepted": True, "ack_id": f"ack_{context_id}_v{version}", "stored_at": utc_now_iso()}


@app.post("/v1/tick")
async def tick(request: Request):
    body, error = await _read_json(request)
    if error is not None:
        return error
    try:
        # Blocking LLM calls run in the threadpool so healthz/context stay responsive.
        return await run_in_threadpool(ticker.run_tick, store, body if isinstance(body, dict) else {})
    except Exception:  # noqa: BLE001  an empty list is always a valid answer (testing brief §2.2)
        log.exception("tick handler failed")
        return {"actions": []}


@app.post("/v1/reply")
async def reply(request: Request):
    body, error = await _read_json(request)
    if error is not None:
        return error
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"error": "malformed_body", "details": "request body must be a JSON object"})
    try:
        # Blocking LLM calls run in the threadpool so healthz/context stay responsive.
        return await run_in_threadpool(replies.handle_reply, store, body)
    except Exception:  # noqa: BLE001  never return a malformed response (testing brief §10: -2)
        log.exception("reply handler failed")
        return {"action": "wait", "wait_seconds": 1800, "rationale": "internal error handled; backing off"}


@app.post("/v1/teardown")
async def teardown():
    # challenge-testing-brief.md §11: wipe all state when the judge signals end of test.
    store.reset()
    return {"ok": True}
