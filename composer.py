"""Composer: compose(category, merchant, trigger, customer=None) -> message dict.

Returns {body, cta, send_as, suppression_key, rationale} (challenge-brief.md §5, §7.1).

Deterministic (brief §7.1): temperature 0 in llm.py, plus a cache keyed by a hash of the exact
inputs, so the same inputs always return the same message even when the LLM is not bit-stable.
Arithmetic is done here in code (DERIVED_FACTS) so the LLM never has to calculate.
"""
import copy
import hashlib
import json
import re
import threading
import time

import fallback
import llm
import validator
from prompts import COMPOSER_VERSION, CTA_TYPES, SYSTEM_PROMPT, guidance_for

DIGEST_KINDS = {"research_digest", "regulation_change", "cde_opportunity"}

_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()


# ------------------------------------------------------------------ small helpers
def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _pct(x: float) -> str:
    return f"{round(x * 100, 1):g}%"


def _signed_pct(x: float) -> str:
    return f"{round(x * 100, 1):+g}%"


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def resolve_digest_item(category: dict, trigger: dict):
    """Find the category digest item a trigger points at (top_item_id / digest_item_id)."""
    payload = trigger.get("payload") or {}
    item_id = payload.get("top_item_id") or payload.get("digest_item_id")
    if not item_id:
        return None
    for item in category.get("digest") or []:
        if item.get("id") == item_id:
            return item
    return None


# ------------------------------------------------------------------ language + addressee
def language_spec(category: dict, merchant: dict, customer: dict | None) -> tuple[str, str]:
    """Return (mode, instruction). Modes: en | hi_roman | hinglish | hinglish_light."""
    if customer:
        pref = str((customer.get("identity") or {}).get("language_pref", "")).lower().strip()
        if pref in ("", "en", "english"):
            return "en", "English (plain, warm and simple)."
        if pref == "hi":
            return "hi_roman", ("Hindi written in Roman script (simple and respectful); keep names, services and "
                                "prices in English.")
        if pref.startswith("hi"):
            return "hinglish", ("Hinglish: a natural Hindi-English mix in Roman script; keep names, services and "
                                "prices in English.")
        return "en", "English (plain and warm), even though the customer prefers a regional-language mix."
    languages = (merchant.get("identity") or {}).get("languages") or []
    if "hi" in languages:
        if (category.get("voice") or {}).get("code_mix") == "english_primary_some_hindi":
            return "hinglish_light", "Mostly English with a few natural Hindi words in Roman script."
        return "hinglish", ("Natural Hindi-English mix (Hinglish, Roman script) the way Indian merchants chat on "
                            "WhatsApp; keep technical terms, names and numbers in English.")
    return "en", "English."


def addressee(category: dict, merchant: dict, customer: dict | None) -> str:
    """Who the message is addressed to (also used for template_params)."""
    if customer:
        return str((customer.get("identity") or {}).get("name") or "there")
    identity = merchant.get("identity") or {}
    owner = identity.get("owner_first_name")
    if not owner:  # no first name in the context: use the business name as is (never invent "Dr. <business>")
        return str(identity.get("name") or "there")
    salutations = (category.get("voice") or {}).get("salutation_examples") or []
    if salutations and str(salutations[0]).lower().startswith("dr."):
        return f"Dr. {owner}"
    return str(owner)


# ------------------------------------------------------------------ derived facts (arithmetic in code)
def derive_facts(category: dict, merchant: dict, trigger: dict) -> list[str]:
    facts: list[str] = []
    perf = merchant.get("performance") or {}
    peer = category.get("peer_stats") or {}

    if _is_num(perf.get("ctr")) and _is_num(peer.get("avg_ctr")):
        side = "below" if perf["ctr"] < peer["avg_ctr"] else "at or above"
        facts.append(f"Merchant 30-day CTR is {_pct(perf['ctr'])} vs peer average {_pct(peer['avg_ctr'])} ({side} peers).")
    for key in ("views", "calls", "directions"):
        mine, avg = perf.get(key), peer.get(f"avg_{key}_30d")
        if _is_num(mine) and _is_num(avg):
            facts.append(f"Merchant 30-day {key}: {mine} vs peer average {avg}.")
    delta = perf.get("delta_7d") or {}
    parts = [f"{k[:-4]} {_signed_pct(v)}" for k, v in delta.items() if k.endswith("_pct") and _is_num(v)]
    if parts:
        facts.append("7-day change: " + ", ".join(parts) + ".")

    agg = merchant.get("customer_aggregate") or {}
    total = agg.get("total_unique_ytd")
    for key, label in (("lapsed_180d_plus", "lapsed for 180+ days"), ("lapsed_90d_plus", "lapsed for 90+ days")):
        if _is_num(agg.get(key)) and _is_num(total) and total:
            facts.append(f"{agg[key]} of {total} customers this year ({round(agg[key] / total * 100)}%) are {label}.")

    payload = trigger.get("payload") or {}
    for key, value in payload.items():
        if _is_num(value) and key.endswith("_pct"):
            facts.append(f"TRIGGER.payload.{key} = {value} means {_signed_pct(value)}.")
    if _is_num(payload.get("value_now")) and _is_num(payload.get("milestone_value")):
        remaining = payload["milestone_value"] - payload["value_now"]
        metric = str(payload.get("metric", "count")).replace("_", " ")
        if remaining >= 0:
            facts.append(f"{remaining:g} more ({metric}) needed to reach {payload['milestone_value']}.")
    return facts


# ------------------------------------------------------------------ prompt context
def build_context(category: dict, merchant: dict, trigger: dict, customer: dict | None) -> dict:
    kind = trigger.get("kind")
    kind = kind if isinstance(kind, str) else ""
    send_as = "merchant_on_behalf" if (trigger.get("scope") == "customer" and customer) else "vera"

    cat = {k: category[k] for k in ("slug", "display_name", "voice", "peer_stats", "offer_catalog",
                                    "seasonal_beats", "trend_signals") if k in category}
    cat["content_library"] = [{"id": i.get("id"), "title": i.get("title")}
                              for i in category.get("patient_content_library") or []]
    if kind in DIGEST_KINDS:
        item = resolve_digest_item(category, trigger)
        if item:
            cat["digest_item"] = item
        else:
            cat["digest"] = category.get("digest") or []
        for key in ("regulatory_authorities", "professional_journals"):
            if key in category:
                cat[key] = category[key]

    identity = dict(merchant.get("identity") or {})
    identity.pop("place_id", None)
    history = []
    for turn in (merchant.get("conversation_history") or [])[-3:]:
        turn = dict(turn)
        turn["body"] = str(turn.get("body", ""))[:300]
        history.append(turn)
    mer = {
        "merchant_id": merchant.get("merchant_id"),
        "identity": identity,
        "subscription": merchant.get("subscription"),
        "performance": merchant.get("performance"),
        "offers": merchant.get("offers"),
        "conversation_history": history,
        "customer_aggregate": merchant.get("customer_aggregate"),
        "signals": merchant.get("signals"),
        "review_themes": merchant.get("review_themes"),
    }
    trg = {k: trigger.get(k) for k in ("id", "kind", "scope", "source", "urgency", "payload")}

    cus = None
    if customer:
        cus = {k: customer.get(k) for k in ("customer_id", "identity", "relationship", "state", "preferences", "consent")}
        cus["identity"] = {k: v for k, v in (customer.get("identity") or {}).items() if k != "phone_redacted"}

    mode, language = language_spec(category, merchant, customer)
    return {
        "language_mode": mode,
        "language": language,
        "send_as": send_as,
        "guidance": guidance_for(kind),
        "category": cat,
        "merchant": mer,
        "trigger": trg,
        "customer": cus,
        "derived_facts": derive_facts(category, merchant, trigger),
    }


def build_messages(ctx: dict, feedback: str | None = None) -> list[dict]:
    user = (
        f"LANGUAGE: {ctx['language']}\n"
        f"SEND_AS: {ctx['send_as']}\n"
        f"GUIDANCE: {ctx['guidance']}\n"
        f"CATEGORY: {_dump(ctx['category'])}\n"
        f"MERCHANT: {_dump(ctx['merchant'])}\n"
        f"TRIGGER: {_dump(ctx['trigger'])}\n"
        f"CUSTOMER: {_dump(ctx['customer'])}\n"
        f"DERIVED_FACTS: {_dump(ctx['derived_facts'])}\n\n"
        "Write the message now. Return only the JSON object."
    )
    if feedback:
        user += (f"\n\nYour previous draft was rejected for: {feedback}. Rewrite the message fixing every point, "
                 "keeping all facts grounded in the input.")
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


# ------------------------------------------------------------------ result assembly
def _map_cta(raw) -> str:
    s = str(raw or "").lower()
    if s in CTA_TYPES:
        return s
    if "confirm" in s:
        return "binary_confirm_cancel"
    if "slot" in s or "choice" in s:
        return "multi_choice_slot"
    if "yes" in s or "binary" in s:
        return "binary_yes_no"
    if s in ("", "null", "no"):
        return "none" if s else "open_ended"
    return "open_ended"


def _normalize_cta(body: str, cta: str) -> str:
    """Keep the cta label consistent with what the body actually does (the judge sees both)."""
    tail = " ".join(re.split(r"(?<=[.!?])\s+", body.strip())[-2:])
    asks = "?" in tail or bool(validator.ASK_RE.search(tail))
    if cta == "none" and body.rstrip().endswith("?"):
        return "open_ended"
    if cta != "none" and not asks:
        return "none"
    return cta


def default_suppression_key(trigger: dict, merchant: dict, customer: dict | None) -> str:
    key = f"{trigger.get('kind', 'trigger')}:{merchant.get('merchant_id', 'merchant')}"
    return key + (f":{customer.get('customer_id')}" if customer else "")


def finalize(candidate: dict, ctx: dict, merchant: dict, trigger: dict, customer: dict | None) -> dict:
    """Turn the model's JSON into the 5-field compose() result."""
    body = str(candidate.get("body", "")).strip()
    rationale = str(candidate.get("rationale", "")).strip()[:500] or f"Composed from {trigger.get('kind', 'trigger')} trigger."
    return {
        "body": body,
        "cta": _normalize_cta(body, _map_cta(candidate.get("cta"))),
        "send_as": ctx["send_as"],
        "suppression_key": trigger.get("suppression_key") or default_suppression_key(trigger, merchant, customer),
        "rationale": rationale,
    }


# ------------------------------------------------------------------ public API
def _cache_key(category, merchant, trigger, customer) -> str:
    blob = json.dumps({"v": COMPOSER_VERSION, "category": category, "merchant": merchant, "trigger": trigger,
                       "customer": customer}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compose_detailed(category: dict, merchant: dict, trigger: dict, customer: dict | None = None,
                     timeout: float = 7.0, previous_bodies=()) -> dict:
    """Return {"message": {...5 fields...}, "meta": {...}}. Never raises for LLM problems.

    Flow: LLM draft -> validator -> (one retry with feedback) -> best acceptable draft, else the deterministic
    fallback. `timeout` is the TOTAL LLM budget in seconds (examples table: tick/reply budget is 10 s).
    Results are cached by input hash for determinism, except when the LLM was unreachable (transient).
    """
    key = _cache_key(category, merchant, trigger, customer)
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return copy.deepcopy(hit)

    ctx = build_context(category, merchant, trigger, customer)
    prior = list(previous_bodies) + [t.get("body") for t in merchant.get("conversation_history") or []
                                     if t.get("from") == "vera"]
    deadline = time.monotonic() + timeout
    best, best_soft, feedback, attempts, issues, transient = None, 99, None, 0, [], False

    for attempt in (1, 2):
        remaining = deadline - time.monotonic()
        if remaining < 1.0:
            transient = transient or attempts == 0
            break
        attempts += 1
        try:
            # max_tokens is a MODEL-CAPABILITY ceiling, not the requested message length: reasoning-capable models
            # (gpt-oss, DeepSeek, GLM, Qwen-thinking, ...) spend hidden reasoning tokens out of the same budget before
            # writing the JSON body, so a low ceiling here starves them (finish_reason "length", empty content) even
            # though the actual WhatsApp message stays short. The APPLICATION-level brevity ask (35-75 words, rule 15
            # in SYSTEM_PROMPT) and enforcement (validator.py "too_long" soft check) are unchanged by this number.
            # min(remaining, 10.0): 10.0 matches tick.COMPOSE_TIMEOUT_SECONDS. The judge_simulator.py harness gives
            # /v1/tick and /v1/reply only 15s (its own BotClient's client-side timeout, not the brief's 30s text),
            # so this must stay safely under that regardless of the caller's own `timeout` budget.
            candidate, provider = llm.chat_json(build_messages(ctx, feedback), max_tokens=1500, timeout=min(remaining, 10.0))
        except llm.LLMUnavailable as exc:
            issues.append(f"llm_unavailable: {exc}")
            transient = True
            break
        message = finalize(candidate, ctx, merchant, trigger, customer)
        result = validator.validate(message["body"], message["cta"], ctx, category, prior)
        issues.extend(f"attempt{attempt}: {i}" for i in result.hard + result.soft)
        if not result.hard and len(result.soft) < best_soft:
            best, best_soft = (message, provider), len(result.soft)
        if result.ok:
            break
        feedback = result.feedback()

    if best is not None:
        message, provider = best
        source = f"llm:{provider}"
    else:
        message = finalize(fallback.build(category, merchant, trigger, customer, ctx,
                                          addressee(category, merchant, customer)), ctx, merchant, trigger, customer)
        source = "fallback"

    detailed = {"message": message, "meta": {"source": source, "attempts": attempts, "issues": issues,
                                             "prompt_version": COMPOSER_VERSION}}
    if not transient:
        with _cache_lock:
            _cache[key] = detailed
    return copy.deepcopy(detailed)


def compose(category: dict, merchant: dict, trigger: dict, customer: dict | None = None) -> dict:
    """challenge-brief.md §7.1: returns dict with body, cta, send_as, suppression_key, rationale."""
    return compose_detailed(category, merchant, trigger, customer)["message"]


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
