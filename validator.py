"""Post-LLM validation (challenge-brief.md §13: "check the output for CTA shape and language match").

Two severities:
  hard - the message must not be sent as is (fabricated data, URL, taboo word, copy of a known example, ...).
         One retry with feedback, then the deterministic fallback.
  soft - quality issues (language mix, CTA placement, ...). One retry; if it persists the LLM message is kept.

Rules and where they come from:
  url            examples/api-call-examples.md F.4 (URL in body = hard fail, -3)
  ungrounded_numbers   brief §5.8 / §11 + FAQ: fabricated facts are the top rejection reason
  taboo          category voice.vocab_taboo (brief §5.6)
  multiple_asks  brief §11: "Multiple CTAs in one message"
  cta_placement  brief §11: "Buried call-to-action"
  language       brief §11: "Ignoring the language preference"
  preamble       brief §11: "Long preambles" / "Re-introducing yourself"
  repeats_previous_message   brief §11 / testing brief §10 (anti-repetition)
  copies_reference   examples/case-studies.md: near-copies of the case studies are penalised
  internal_jargon    judge_simulator.py:477 ("Exposing internal jargon to merchant: -1"): field names / system terms
"""
import difflib
import json
import re
from dataclasses import dataclass, field

from references import REFERENCE_BODIES

NUM_RE = re.compile(r"\d(?:[\d,]*\d)?(?:\.\d+)?")
URL_RE = re.compile(r"https?://|www\.|\b[a-z0-9][a-z0-9-]*\.(?:com|in|co|org|net|io|me|app|ly)\b", re.I)
DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
# snake_case identifiers (stale_posts, delta_pct, ...) and system words must never reach the merchant.
JARGON_RE = re.compile(r"\b[A-Za-z]+(?:_[A-Za-z0-9]+)+\b|\b(?:payload|suppression[ _]key|placeholder|json|llm|dataset|template_params?)\b", re.I)
ID_LIKE_RE = re.compile(r"\b[A-Za-z]+_[\w-]*\d[\w-]*\b")  # m_001_x, trg_013_y, d_2026W17_z ...
TIME_UNIT_RE = re.compile(r"^\s*-?\s*(?:min|mins|minute|minutes|sec|secs|second|seconds|hour|hours|hr|hrs)\b", re.I)
ASK_RE = re.compile(r"\b(reply|yes|confirm|let me know|tell me|share|send me|bolo|batao|bataiye|likh|bhej|haan|karun|"
                    r"kar dun|chahiye|chalega|go ahead)\b", re.I)
PREAMBLE_RE = re.compile(r"\b(i hope you|hope you(?:'re| are)|reaching out|my name is|this is vera|i am vera|i'm vera)\b", re.I)

HINDI_MARKERS = {
    "aap", "aapka", "aapki", "aapke", "apka", "apki", "apke", "hai", "hain", "hoga", "hogi", "kya", "kyun", "kaise",
    "ka", "ki", "ke", "ko", "mein", "par", "pe", "aur", "ya", "nahi", "bhi", "toh", "abhi", "kal", "aaj", "chahiye",
    "karein", "kare", "karo", "kijiye", "dijiye", "bataiye", "batao", "bolo", "bhejein", "sakta", "sakti", "sakte",
    "rahe", "raha", "rahi", "liye", "wala", "wali", "kuch", "sab", "jaldi", "shukriya", "dhanyavaad", "namaste", "ji",
    "dekhna", "milega", "milegi", "lagta", "tak", "saath", "hamare", "humare", "apne", "yeh", "ye", "woh", "wo", "hum",
    "mera", "meri", "mujhe", "tum", "tumhare", "khatam", "hongi", "hoti", "hota", "raho", "rakho", "bana", "banao",
    "dun", "du", "diya", "kiya", "gaya", "gayi", "lo", "lein", "dekhein", "dekh", "wapas", "phir", "sirf", "zyada",
}
MIN_HINDI_MARKERS = {"hinglish": 2, "hi_roman": 4, "hinglish_light": 1, "en": 0}


@dataclass
class Result:
    hard: list[str] = field(default_factory=list)
    soft: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.hard and not self.soft

    def feedback(self) -> str:
        return "; ".join(self.hard + self.soft)


# ------------------------------------------------------------------ numbers
def _canon(token: str) -> str:
    token = token.replace(",", "")
    if "." in token:
        return token.rstrip("0").rstrip(".") or "0"
    return str(int(token)) if token.isdigit() else token


def _float_leaves(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _float_leaves(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _float_leaves(v)
    elif isinstance(obj, float):
        yield obj


def allowed_numbers(ctx: dict) -> set[str]:
    """Every number that appears in the facts the LLM was shown (plus fractions expressed as percentages)."""
    facts = {k: ctx.get(k) for k in ("category", "merchant", "trigger", "customer", "derived_facts", "conversation",
                                     "latest_message")}
    text = ID_LIKE_RE.sub(" ", json.dumps(facts, ensure_ascii=False))
    allowed = {_canon(m) for m in NUM_RE.findall(text)}
    for x in _float_leaves(facts):
        if 0 < abs(x) <= 1:
            allowed.add(_canon(f"{abs(x) * 100:.1f}"))
            allowed.add(_canon(f"{abs(x) * 100:.2f}"))
            allowed.add(str(round(abs(x) * 100)))
    return allowed


def ungrounded_numbers(body: str, allowed: set[str]) -> list[str]:
    bad = []
    for m in NUM_RE.finditer(body):
        raw = m.group()
        token = _canon(raw)
        if token in allowed:
            continue
        before, after = body[max(0, m.start() - 2):m.start()], body[m.end():m.end() + 12]
        is_int = "." not in token
        value = float(token) if token.replace(".", "", 1).isdigit() else None
        if value is None:
            continue
        currency_or_pct = after.lstrip().startswith("%") or "₹" in before or before.lower().endswith("rs")
        if is_int and value <= 12 and not currency_or_pct:
            continue  # small counts / clock hours / day-of-month ("2 slots", "6pm", "5 Nov")
        if is_int and value <= 120 and TIME_UNIT_RE.match(after):
            continue  # effort / duration phrases ("2-min", "10 minutes", "90 seconds")
        bad.append(raw + ("%" if after.lstrip().startswith("%") else ""))
    return bad


# ------------------------------------------------------------------ language, CTA, similarity
def _sentences(body: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", body.strip())
    return [p.strip() for p in parts if p and p.strip()]


def hindi_marker_count(body: str) -> int:
    return sum(1 for w in re.findall(r"[a-z]+", body.lower()) if w in HINDI_MARKERS)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9₹%]+", text.lower())


def _ngrams(tokens: list[str], n: int = 6) -> set[tuple]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


_REFERENCE_TOKENS = [_tokens(r) for r in REFERENCE_BODIES]
_REFERENCE_NGRAMS = [_ngrams(t) for t in _REFERENCE_TOKENS]


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return difflib.SequenceMatcher(None, ta, tb, autojunk=False).ratio()


def copies_reference(body: str) -> bool:
    tokens = _tokens(body)
    grams = _ngrams(tokens)
    for ref_tokens, ref_grams in zip(_REFERENCE_TOKENS, _REFERENCE_NGRAMS):
        # A faithful message about the SAME facts (same slots, price, names) overlaps a case study in word order without copying it
        # (T28 vs case study 2 reaches ~0.47), so the ratio bar is high; verbatim runs (6-gram containment below) are the real signal.
        if difflib.SequenceMatcher(None, tokens, ref_tokens, autojunk=False).ratio() >= 0.65:
            return True
        if grams and len(grams & ref_grams) / len(grams) >= 0.35:
            return True
    return False


# ------------------------------------------------------------------ main entry point
def validate(body: str, cta: str, ctx: dict, category: dict, previous_bodies=(), min_words: int = 6) -> Result:
    res = Result()
    body = (body or "").strip()
    if len(body.split()) < min_words:
        res.hard.append("empty_or_too_short_body")
        return res

    if URL_RE.search(body):
        res.hard.append("url_in_body (no links or web addresses allowed)")

    if JARGON_RE.search(body):
        res.hard.append("internal_jargon (never show field names or system terms such as snake_case identifiers, payload, placeholder)")

    lowered = body.lower()
    for phrase in (category.get("voice") or {}).get("vocab_taboo") or []:
        core = str(phrase).split(" (")[0].strip().lower()
        if core and core in lowered:
            res.hard.append(f"taboo_phrase '{core}'")

    bad_numbers = ungrounded_numbers(body, allowed_numbers(ctx))
    if bad_numbers:
        res.hard.append("ungrounded_numbers " + ", ".join(bad_numbers) + " (not present in the provided facts; remove or replace with given facts)")

    sentences = _sentences(body)
    questions = sum(1 for s in sentences if s.rstrip().endswith("?"))
    replies = len(re.findall(r"\breply\b", body, re.I))
    if questions >= 3 or (cta != "multi_choice_slot" and replies >= 3):
        res.hard.append("multiple_asks (exactly one call to action is allowed)")

    if copies_reference(body):
        res.hard.append("copies_known_example (use your own wording)")
    for prev in previous_bodies:
        if prev and similarity(body, prev) >= 0.85:
            res.hard.append("repeats_previous_message")
            break

    # ---- soft checks
    if cta != "none" and sentences:
        # "ask, then payoff" (case-studies.md 4: question first, promise last) is fine; only an ask buried far from the end is flagged
        tail = " ".join(sentences[-3:])
        if "?" not in tail and not ASK_RE.search(tail):
            res.soft.append("cta_placement (put the single ask near the end of the message)")

    mode = ctx.get("language_mode", "en")
    if DEVANAGARI_RE.search(body):
        res.soft.append("language (write in Roman script, not Devanagari)")
    elif hindi_marker_count(body) < MIN_HINDI_MARKERS.get(mode, 0):
        res.soft.append(f"language (message must follow LANGUAGE: {ctx.get('language')})")

    if PREAMBLE_RE.search(body):
        res.soft.append("preamble (no greeting fluff or self-introduction)")
    if len(body.split()) > 130:
        res.soft.append("too_long (keep to about 35-75 words)")
    return res
