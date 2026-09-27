"""Heuristic message checks for the LIVE audit (tests/live_audit_30_pairs.py).

These are ADVISORY: they point a human reviewer at things worth reading twice. They never gate what the bot sends
(the production gate is validator.py). Every function takes the exact `ctx` that composer.build_context() produced, i.e. the
same facts the LLM was shown.
"""
import json
import re

import validator
from references import REFERENCE_BODIES

DAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "january", "february", "march",
          "april", "june", "july", "august", "september", "october", "november", "december"}
COMMON = {"hi", "hello", "namaste", "dr", "mr", "mrs", "ms", "reply", "yes", "no", "ok", "okay", "whatsapp", "google", "gbp", "vera",
          "kya", "want", "would", "should", "can", "quick", "today", "tomorrow", "sunday", "cdE", "cde", "ors", "rvg", "iopa", "msv",
          "cta", "ctr", "roi", "gst", "ipl", "dc", "mi", "hiit", "pt", "roi", "post", "story", "instagram", "swiggy", "zomato"}
PROMO_RE = re.compile(r"\b(amazing|mega|bumper|blockbuster|jackpot|bonanza|super deal|grab now|hurry|don'?t miss)\b", re.I)
URGENCY_RE = re.compile(r"\b(urgent(?:ly)?|immediately|right now|asap|last chance|hurry|don'?t miss|before it'?s too late|limited time|"
                        r"today only|expires? (?:today|soon)|act now|turant|jaldi se jaldi)\b", re.I)
GENERIC_RE = re.compile(r"\b(increase your sales|boost your (?:business|sales)|grow your business|next level|special offer for you|"
                        r"don'?t miss out|best deals?)\b", re.I)
ALLOWED_CAPS = {"YES", "STOP", "CONFIRM", "CANCEL", "WHATSAPP", "JIDA", "IDA", "DCI", "GBP", "IOPA", "CDE", "OPG", "RCT", "MRP", "GST",
                "IPL", "RVG", "ORS", "HIIT", "BOGO", "MSV", "CTR", "ROI", "PT", "MI", "DC", "FSSAI", "OK"}
CLINICAL = {"dentists", "pharmacies"}


def context_blob(ctx: dict) -> str:
    facts = {k: ctx.get(k) for k in ("category", "merchant", "trigger", "customer", "derived_facts")}
    return json.dumps(facts, ensure_ascii=False).lower()


def sentence_starts(body: str) -> set[int]:
    starts, prev_end = {0}, True
    for m in re.finditer(r"\S+", body):
        if prev_end:
            starts.add(m.start())
        prev_end = bool(re.search(r"[.!?\n:—-]$", m.group()))
    return starts


def possible_invented_names(body: str, ctx: dict) -> list[str]:
    """Capitalised words (not at a sentence start) that do not appear anywhere in the context."""
    blob = context_blob(ctx)
    starts = sentence_starts(body)
    out = []
    for m in re.finditer(r"[A-Z][a-zA-Z'’\-]{2,}", body):
        word = m.group().strip("'’-")
        low = word.lower()
        if m.start() in starts or low in COMMON or low in DAYS or low in MONTHS or word.upper() in ALLOWED_CAPS:
            continue
        if low in blob or low.rstrip("s") in blob or low.rstrip("'s") in blob:
            continue
        if word not in out:
            out.append(word)
    return out


def offer_claims(body: str, ctx: dict) -> list[str]:
    """Rupee amounts that are unsupported, or catalog offers presented as the merchant's own."""
    merchant, category, trigger = ctx["merchant"], ctx["category"], ctx["trigger"]
    active = [str(o.get("title", "")) for o in merchant.get("offers") or [] if o.get("status") == "active"]
    catalog = [str(o.get("title", "")) for o in category.get("offer_catalog") or []]
    payload_text = json.dumps(trigger.get("payload") or {}, ensure_ascii=False).replace(",", "")
    blob = context_blob(ctx).replace(",", "")
    flags = []
    for m in re.finditer(r"₹\s?([\d,]+)", body):
        amount = m.group(1).replace(",", "")
        in_active = any(amount in t.replace(",", "") for t in active)
        in_catalog = any(amount in t.replace(",", "") for t in catalog)
        if not (in_active or in_catalog or amount in payload_text or amount in blob):
            flags.append(f"price ₹{amount} is not in the context")
        elif in_catalog and not in_active and amount not in payload_text:
            window = body[max(0, m.start() - 70):m.start()]
            if re.search(r"\b(your|aapka|aapki|aapke)\b", window, re.I):
                flags.append(f"catalog offer ₹{amount} described as the merchant's own (merchant has no such active offer)")
    return flags


def urgency_flags(body: str, ctx: dict) -> list[str]:
    trigger = ctx["trigger"]
    payload = trigger.get("payload") or {}
    hits = [m.group() for m in URGENCY_RE.finditer(body)]
    if not hits:
        return []
    supported = (trigger.get("urgency") or 0) >= 4 or any(k in payload for k in ("deadline_iso", "stock_runs_out_iso"))
    if isinstance(payload.get("days_until"), (int, float)) and payload["days_until"] > 30:
        supported = False
    return [] if supported else [f"urgency wording {hits} but trigger urgency={trigger.get('urgency')} and no deadline in the payload"]


def generic_flags(body: str, ctx: dict) -> list[str]:
    allowed = validator.allowed_numbers(ctx)
    grounded = [n for n in validator.NUM_RE.findall(body) if validator._canon(n) in allowed and float(validator._canon(n)) > 12]
    identity = ctx["merchant"].get("identity") or {}
    names = [str(identity.get("owner_first_name") or "").lower(), str(identity.get("name") or "").lower(),
             str(identity.get("locality") or "").lower()]
    named = any(n and n in body.lower() for n in names)
    flags = []
    if GENERIC_RE.search(body):
        flags.append("stock marketing phrase")
    if not grounded and not named:
        flags.append("no verifiable number and no merchant name/locality: reads generic")
    return flags


def fact_dump(body: str, ctx: dict) -> list[str]:
    allowed = validator.allowed_numbers(ctx)
    distinct = {validator._canon(n) for n in validator.NUM_RE.findall(body)
                if validator._canon(n) in allowed and float(validator._canon(n)) > 12}
    return [f"{len(distinct)} distinct grounded figures in one message ({sorted(distinct)[:8]}): may be a fact dump"] if len(distinct) > 4 else []


def ask_check(body: str, cta: str) -> list[str]:
    sentences = validator._sentences(body)
    questions = sum(1 for s in sentences if s.rstrip().endswith("?"))
    tail = " ".join(sentences[-3:])
    flags = []
    if questions >= 3:
        flags.append(f"{questions} question sentences (more than one ask?)")
    if cta != "none" and "?" not in tail and not validator.ASK_RE.search(tail):
        flags.append("no clear ask near the end")
    if cta == "none" and body.rstrip().endswith("?"):
        flags.append("cta is 'none' but the body ends with a question")
    return flags


def tone_flags(body: str, category: dict, raw_context: str = "") -> list[str]:
    slug = category.get("slug")
    slug = slug if isinstance(slug, str) else ""
    flags = []
    promo = PROMO_RE.findall(body)
    # ALL-CAPS words that come straight from the merchant's own data (e.g. the offer title "3 FREE Trial Classes") are not shouting
    caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", body) if w not in ALLOWED_CAPS and w not in raw_context]
    if promo:
        flags.append(f"promotional wording {promo}")
    if body.count("!") >= 2:
        flags.append("exclamation-mark heavy")
    if caps:
        flags.append(f"ALL-CAPS words {caps}")
    if slug in CLINICAL and (promo or body.count("!") >= 2):
        flags.append(f"clinical category '{slug}' needs a peer/clinical voice")
    return flags


def taboo_hits(body: str, category: dict) -> list[str]:
    lowered = body.lower()
    hits = []
    for phrase in (category.get("voice") or {}).get("vocab_taboo") or []:
        core = str(phrase).split(" (")[0].strip().lower()
        if core and core in lowered:
            hits.append(core)
    return hits


def vocab_used(body: str, category: dict) -> list[str]:
    lowered = body.lower()
    return [w for w in (category.get("voice") or {}).get("vocab_allowed") or [] if w.lower() in lowered]


def similarity_report(body: str) -> dict:
    """Highest similarity to any reference message: word-sequence ratio and 6-gram containment."""
    tokens = validator._tokens(body)
    grams = validator._ngrams(tokens)
    best = {"ratio": 0.0, "containment": 0.0, "ref": None}
    for i, (rt, rg) in enumerate(zip(validator._REFERENCE_TOKENS, validator._REFERENCE_NGRAMS)):
        import difflib
        ratio = difflib.SequenceMatcher(None, tokens, rt, autojunk=False).ratio()
        cont = len(grams & rg) / len(grams) if grams else 0.0
        if ratio > best["ratio"]:
            best.update(ratio=round(ratio, 3), ref=i)
        best["containment"] = round(max(best["containment"], cont), 3)
    best["would_be_rejected"] = validator.copies_reference(body)
    best["ref_preview"] = REFERENCE_BODIES[best["ref"]][:60] if best["ref"] is not None else None
    return best


def audit_message(body: str, cta: str, ctx: dict, category: dict) -> dict:
    """All advisory checks for one message. Empty lists mean 'nothing to review'."""
    hard = validator.validate(body, cta, ctx, category, ())
    return {
        "validator_hard": hard.hard,
        "validator_soft": hard.soft,
        "url": bool(validator.URL_RE.search(body)),
        "taboo": taboo_hits(body, category),
        "ungrounded_numbers": validator.ungrounded_numbers(body, validator.allowed_numbers(ctx)),
        "possible_invented_names": possible_invented_names(body, ctx),
        "offer_flags": offer_claims(body, ctx),
        "urgency_flags": urgency_flags(body, ctx),
        "generic_flags": generic_flags(body, ctx),
        "fact_dump": fact_dump(body, ctx),
        "ask_flags": ask_check(body, cta),
        "tone_flags": tone_flags(body, category, json.dumps({k: ctx.get(k) for k in ("category", "merchant", "trigger", "customer")}, ensure_ascii=False)),
        "vocab_used": vocab_used(body, category),
        "similarity": similarity_report(body),
        "words": len(body.split()),
    }
