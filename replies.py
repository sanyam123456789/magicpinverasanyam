"""Reply engine for POST /v1/reply.

Rules decide first; the LLM only writes open-ended answers. Order of decisions and their sources:

  1  conversation already ended                    -> end            examples 2.6 ("must not send any further messages
                                                                      on this conversation_id")
  2  explicit opt-out ("stop messaging me")        -> end            examples 2.6 (suppresses THIS conversation only); if the
                                                                      message is also hostile: examples 4.3 (merchant suppressed)
  3  plain decline ("no thanks")                   -> end            brief §12.5 (knowing when to stop)
  4  abuse without an opt-out                      -> calm reply,    testing brief Phase 4 #3 (stay on mission, politely)
                                                     end on the 2nd
  5  auto-reply (canned text / same text again)    -> send once, then wait 24h, then end        examples 4.1
  6  customer picks one of the offered slots       -> booking confirmation                      brief App. B
  7  commitment ("let's do it", "yes")             -> ACTION reply, no qualifying question      brief §12.2, Pattern D, examples 4.2
  8  out-of-scope ask (GST, tax, ...)              -> polite decline + back to the topic         examples 2.7
  9  asks for time ("busy", "kal")                 -> wait                                       testing brief §2.3
  10 anything else                                 -> LLM answer (one ask, grounded)

Auto-reply counting is kept per MERCHANT because the judge's auto-reply scenario changes the conversation_id every turn
(judge_simulator.py). The only merchant-level suppression is for a hostile merchant (examples 4.3) and it only stops
*proactive* sends in /v1/tick; a new conversation is still answered. Everything else (opt-out, decline, auto-reply exit,
"busy") is conversation-level, so no other trigger of that merchant is silently dropped.
"""
import json
import re
import time

import composer
import llm
import validator
from prompts import REPLY_SYSTEM_PROMPT

# Raised from 6.5: see tick.py's comment on TICK_BUDGET_SECONDS/COMPOSE_TIMEOUT_SECONDS - same reasoning-model
# latency reality, same 30s-hard-limit margin.
REPLY_BUDGET_SECONDS = 22.0
QUALIFYING_RE = re.compile(r"\b(would you|do you|can you tell|what if|how about)\b", re.I)

# ------------------------------------------------------------------ message classification
STRONG_STOP_RE = re.compile(
    r"\b(stop (messag\w*|send\w*|text\w*|contact\w*|bother\w*|call\w*|whatsapp\w*|this|these|it|now)"
    r"|unsubscribe|opt[ -]?out|(do not|don'?t|dont|never) (message|contact|text|call|send|whatsapp)"
    r"|leave me alone|remove (me|my number)|delete my number"
    r"|band kar\w*|mat bhej\w*|message mat|msg mat|pareshan mat)\b", re.I)
STOP_WORDS = {"stop", "unsubscribe", "stop it", "please stop", "stop please"}
DECLINE_RE = re.compile(r"\b(not interested|no interest|nahi chahiye|nahin chahiye|interested nahi|no thanks|no thank you)\b", re.I)
DECLINE_WORDS = {"no", "nope", "nahi", "nahin", "not required"}
HOSTILE_RE = re.compile(
    r"\b(idiot\w*|stupid|useless|nonsense|rubbish|shut up|f+u+c+k\w*|bastard|scam\w*|fraud\w*|waste of (my )?time|pagal|"
    r"bakwas|harami\w*|chutiy\w*|bewakoof|gandu|madarchod|behenchod|disgusting|hate you|get lost|fed up|spam\w*)\b", re.I)
AUTO_REPLY_RE = re.compile(
    r"(thank(s| you) for (contacting|reaching out|messaging|your message|writing)"
    r"|(our|the) team will (get back|respond|reply|contact|reach|connect)"
    r"|(will|shall) (get back|respond|reply|revert) (to you )?(shortly|soon|as soon|within)"
    r"|we (have )?received your (message|query|request)"
    r"|(this is|i am|i'm) (an? )?(automated|auto)[ -]?(reply|response|assistant|message|bot)"
    r"|automated (reply|response|assistant|message)|auto[- ]?reply"
    r"|(currently|right now) (unavailable|away|closed|busy)|(we are|we're) (currently )?(closed|away|unavailable)"
    r"|(our )?(business|working|office) hours"
    r"|(main|hum) ek automated|aapki jaankari ke liye|team tak pahunch|hum jald(i)? hi (aapse )?sampark"
    r"|sandesh ke liye (dhanyavaad|shukriya)|dhanyavaad.{0,40}sampark)", re.I)
INTENT_RE = re.compile(
    r"\b(let'?s (do|go|start|begin|proceed)( it| ahead)?|lets do it|let us do it|go ahead|please proceed|proceed|"
    r"do it|sounds good|send (it|me|them)|start (now|it|karo)|book (it|me)|i'?m in|i am in|count me in|sign me up|"
    r"what'?s next|whats next|what next|next step|kar do|karo na|bhej do|shuru karo|chalo|"
    r"(i (want|wanna|would like) to|want to) join|mujhe .{0,25}(join|judna|judrna|jodna)\w*|jud(na|ne) (hai|chahta|chahti)|join karna)\b", re.I)
ACCEPT_START_RE = re.compile(r"^(yes|yeah|yep|yup|ok|okay|sure|haan|ha|han|hanji|done|theek hai|thik hai)\b")
OFF_TOPIC_RE = re.compile(r"\b(gst|gstr|itr|income tax|tax return|tax(es)?|loan|insurance|lawyer|court|visa|passport|salary|"
                          r"payroll|accountant|accounting)\b", re.I)
QUESTION_WORD_RE = re.compile(r"\b(what|how|when|why|which|who|where|price|cost|charge|charges|fees?|kitna|kitne|kya|kab|kaise|kyun|kaun|kahan)\b", re.I)
WAIT_RE = re.compile(
    r"\b(busy|later|baad (mein|me)|thodi der|abhi nahi|not now|call (you|me) (back|later)|will (check|see|revert|get back|let you know)|"
    r"let me (check|think|see)|give me (some )?(time|a (bit|while|moment))|in a (bit|while)|kal|tomorrow|next week|agle hafte|"
    r"ek ghante|an hour|half an hour|remind me)\b", re.I)
WAIT_LONG_RE = re.compile(r"\b(kal|tomorrow|next week|agle hafte)\b", re.I)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def classify(message: str, repeats: int = 0) -> str:
    """Return one of: empty opt_out decline hostile auto_reply intent off_topic wait normal."""
    text = (message or "").strip()
    norm = _norm(text)
    if not norm:
        return "empty"
    if norm in STOP_WORDS or STRONG_STOP_RE.search(text):
        return "opt_out"
    if norm in DECLINE_WORDS or (DECLINE_RE.search(text) and len(norm.split()) <= 8):
        return "decline"
    if HOSTILE_RE.search(text):
        return "hostile"
    if AUTO_REPLY_RE.search(text) or (repeats >= 1 and len(norm) > 20):
        return "auto_reply"
    if INTENT_RE.search(text) or (ACCEPT_START_RE.match(norm) and "?" not in text and not QUESTION_WORD_RE.search(text)):
        return "intent"
    if OFF_TOPIC_RE.search(text):
        return "off_topic"
    if WAIT_RE.search(text):
        return "wait"
    return "normal"


def match_slot(message: str, options: list[str]) -> int | None:
    """Which of the offered slot labels did the customer choose? ("2", "Wed works", "thursday")."""
    if not options:
        return None
    text = (message or "").strip().lower()
    m = re.match(r"^\W*(?:option\s*|slot\s*|number\s*)?([1-9])\b", text)
    if m and int(m.group(1)) <= len(options):
        return int(m.group(1)) - 1
    for i, label in enumerate(options):
        low = label.lower()
        if low in text:
            return i
        tokens = [t for t in re.findall(r"[a-z]+", low) if len(t) >= 3]
        if tokens and re.search(rf"\b{tokens[0]}\w*", text):
            return i
    return None


# ------------------------------------------------------------------ deterministic replies (used when the LLM is down/invalid)
# (english, hinglish, cta). Own wording; kept clear of the reference messages (validator.copies_reference is tested).
FALLBACK = {
    "auto_flag": [(
        "That looks like an automatic reply. Whenever the owner has a minute, a simple YES to my last message is all I need to get started.",
        "Ye ek automatic reply lagta hai. Owner ko jab time mile, meri pichhli baat par bas YES likh dijiye, main aage sambhal lungi.",
        "binary_yes_no")],
    "calm": [(
        "Sorry for the trouble, that was not the intent. If you would rather not get these, reply STOP and I will close this chat; otherwise I am here whenever a quick hand with your listing would help.",
        "Pareshani ke liye maafi, meri aisi koi mansha nahi thi. Agar aap ye messages nahi chahte toh STOP likh dijiye, main chat band kar dungi; warna listing mein jab bhi help chahiye, main yahin hoon.",
        "binary_yes_no")],
    "action": [
        ("Great, starting right away. I will put the first draft together and send it here in a few minutes; just reply CONFIRM once you have seen it.",
         "Badhiya, abhi shuru karti hoon. Pehla draft taiyar karke yahin bhej dungi; dekhne ke baad bas CONFIRM likh dijiye.", "binary_confirm_cancel"),
        ("On it. I am preparing the draft now and will share it in this chat shortly; reply CONFIRM when you are happy for me to go ahead.",
         "Ho jayega. Main abhi draft bana rahi hoon aur is chat mein jaldi share karungi; theek lage toh CONFIRM likh dijiye.", "binary_confirm_cancel")],
    "action_customer": [
        ("Great, we are on it. We will confirm the details here shortly; just reply CONFIRM if everything looks right.",
         "Badhiya, hum kar rahe hain. Details yahin jaldi confirm karenge; sab theek lage toh CONFIRM likh dijiye.", "binary_confirm_cancel")],
    "off_topic": [(
        "That one is outside what I can help with here, so it is best to check with your CA or the relevant expert. Shall I go ahead with my earlier suggestion for your listing?",
        "Ye mere scope se bahar hai, isliye apne CA ya relevant expert se baat karna behtar rahega. Kya main listing ke liye apni pichhli suggestion par aage badhun?",
        "binary_yes_no")],
    "normal": [
        ("Thanks for the message, noted. I will check this and get back to you here with specifics. Meanwhile, shall I continue with my earlier suggestion?",
         "Message ke liye shukriya. Main ise check karke yahin specifics ke saath wapas aati hoon. Tab tak kya main apni pichhli suggestion par aage badhun?", "binary_yes_no"),
        ("Understood. I am looking into it and will update you here shortly.",
         "Samajh gayi. Main ise dekh rahi hoon aur jaldi hi yahin update dungi.", "none")],
    "normal_customer": [
        ("Thanks for your message, noted. We will check and confirm here shortly.",
         "Aapke message ke liye shukriya. Hum check karke yahin jaldi confirm karenge.", "none")],
}


def _pick(kind: str, prior: list[str], hinglish: bool):
    for english, hindi, cta in FALLBACK[kind]:
        body = hindi if hinglish else english
        if body not in prior:
            return {"body": body, "cta": cta}
    return None


# ------------------------------------------------------------------ LLM replies
def reply_language(message: str, category: dict, merchant: dict, customer: dict | None) -> tuple[str, str]:
    """Mirror the sender's language (brief §12.4: language detection per turn)."""
    mode, instruction = composer.language_spec(category, merchant, customer)
    hindi = validator.hindi_marker_count(message) >= 1 or bool(validator.DEVANAGARI_RE.search(message))
    if hindi:
        if mode in ("hinglish", "hi_roman"):
            return mode, instruction
        return "hinglish_light", "Mirror the sender: mostly English with natural Hindi words in Roman script."
    if len(message.split()) <= 3:
        return mode, instruction
    return "en", "English (mirror the sender's language)."


def _llm_reply(ctx: dict, mode: str, sender: str, off_topic: bool, category: dict, prior: list[str]):
    deadline = time.monotonic() + REPLY_BUDGET_SECONDS
    feedback = None
    for _ in (1, 2):
        remaining = deadline - time.monotonic()
        if remaining < 1.0:
            return None
        user = (
            f"MODE: {mode}\nSENDER: {sender}\nLANGUAGE: {ctx['language']}\nOFF_TOPIC_HINT: {str(off_topic).lower()}\n"
            f"CATEGORY: {composer._dump(ctx['category'])}\nMERCHANT: {composer._dump(ctx['merchant'])}\n"
            f"TRIGGER: {composer._dump(ctx['trigger'])}\nCUSTOMER: {composer._dump(ctx['customer'])}\n"
            f"CONVERSATION: {composer._dump(ctx['conversation'])}\nLATEST_MESSAGE: {json.dumps(ctx['latest_message'], ensure_ascii=False)}\n\n"
            "Write the reply now. Return only the JSON object."
        )
        if feedback:
            user += f"\n\nYour previous draft was rejected for: {feedback}. Rewrite it fixing every point."
        try:
            # See composer.py's compose_detailed for why this is high: it is a model-capability ceiling (room for a
            # reasoning model's hidden reasoning tokens), not the requested reply length (20-60 words, rule 6 in
            # REPLY_SYSTEM_PROMPT), which validator.py still enforces independently.
            obj, _provider = llm.chat_json([{"role": "system", "content": REPLY_SYSTEM_PROMPT}, {"role": "user", "content": user}],
                                           max_tokens=900, timeout=min(remaining, 20.0))
        except llm.LLMUnavailable:
            return None
        body = str(obj.get("body", "")).strip()
        cta = composer._map_cta(obj.get("cta"))
        result = validator.validate(body, cta, ctx, category, prior, min_words=3)
        problems = list(result.hard)
        if mode == "ACTION" and QUALIFYING_RE.search(body):
            problems.append("qualifying_question_after_commitment (do not ask; deliver the next step)")
        if not problems:
            return {"body": body, "cta": cta, "rationale": str(obj.get("rationale") or "").strip()[:300] or f"{mode} reply"}
        feedback = "; ".join(problems + result.soft)
    return None


# ------------------------------------------------------------------ response helpers
def _send(body: str, cta: str, rationale: str) -> dict:
    return {"action": "send", "body": body, "cta": cta, "rationale": rationale}


def _wait(seconds: int, rationale: str) -> dict:
    return {"action": "wait", "wait_seconds": int(seconds), "rationale": rationale}


def _end(rationale: str) -> dict:
    return {"action": "end", "rationale": rationale}


# ------------------------------------------------------------------ main entry point
def handle_reply(store, request: dict) -> dict:
    """Turn a judge /v1/reply request into {"action": send|wait|end, ...}. Always returns a valid response."""
    conv_id = str(request.get("conversation_id") or "")
    role = "customer" if str(request.get("from_role") or "merchant").lower() == "customer" else "merchant"
    message = str(request.get("message") or "").strip()[:2000]

    with store.lock:
        conv = store.conversation(conv_id, merchant_id=request.get("merchant_id"), customer_id=request.get("customer_id"))
        mid = conv.get("merchant_id") or request.get("merchant_id") or conv_id
        cid = conv.get("customer_id") or request.get("customer_id")
        flags = store.flags(mid)
        norm = _norm(message)
        seen = store.inbound_seen.setdefault(mid, {})
        repeats = seen.get(norm, 0) if norm else 0
        if norm:
            seen[norm] = repeats + 1
        conv["turns"].append({"from": role, "body": message, "ts": request.get("received_at")})
        options = list(conv.get("options") or [])
        ended = conv["ended"]
        prior = [t["body"] for t in conv["turns"] if t["from"] in ("vera", "merchant_on_behalf")]
    if ended:
        return _end("This conversation was already closed; sending nothing further on this conversation_id.")

    label = "slot" if match_slot(message, options) is not None else classify(message, repeats)
    if label != "auto_reply" and role == "merchant":
        with store.lock:
            flags["auto_replies"] = 0  # a real message ends the auto-reply streak

    merchant = store.get("merchant", mid) or {}
    customer = store.get("customer", cid) if cid else None
    category = store.get("category", merchant.get("category_slug", "")) or {}
    mode_lang, lang_text = reply_language(message, category, merchant, customer)
    hinglish = mode_lang != "en"

    def finish(response: dict) -> dict:
        with store.lock:
            if response["action"] == "send":
                conv["turns"].append({"from": conv.get("send_as") or ("merchant_on_behalf" if role == "customer" else "vera"),
                                      "body": response["body"], "ts": None})
            elif response["action"] == "end":
                conv["ended"] = True
        return response

    if label == "empty":
        return finish(_wait(1800, "Empty message; giving the sender time instead of replying."))

    if label == "opt_out":
        hostile = bool(HOSTILE_RE.search(message))
        with store.lock:
            if hostile:
                flags["suppressed"] = True  # examples 4.3: "Suppressing all triggers for this merchant for 30 days"
            if cid:
                store.suppressed_customers.add(cid)
        why = ("Explicit opt-out with open hostility; closing and suppressing this merchant's proactive messages."
               if hostile else "Explicit opt-out; closing this conversation and not sending anything further on it.")
        return finish(_end(why))

    if label == "decline":
        return finish(_end("The sender declined; not pushing further and closing the conversation."))

    if label == "auto_reply":
        with store.lock:
            flags["auto_replies"] += 1
            n = flags["auto_replies"]
        if n == 1:
            pick = _pick("auto_flag", prior, hinglish)
            return finish(_send(pick["body"], pick["cta"], "Detected a canned auto-reply; one short note for the owner instead of a full pitch."))
        if n == 2:
            return finish(_wait(86400, "Same auto-reply again: the owner is not at the phone. Waiting 24 hours before any retry."))
        return finish(_end("Third auto-reply in a row with no human reply; closing the conversation."))

    if label == "wait":
        seconds = 86400 if WAIT_LONG_RE.search(message) else 1800
        return finish(_wait(seconds, "The sender asked for time; backing off."))

    if label == "slot":
        idx = match_slot(message, options)
        name = str(((customer or {}).get("identity") or {}).get("name") or "there")
        with store.lock:
            conv["booked"] = options[idx]
        body = (f"Ho gaya, {name}, aapki booking {options[idx]} ke liye confirm hai. Milte hain! Badalna ho toh yahin reply kijiye."
                if hinglish else f"Done, {name}, you are booked for {options[idx]}. See you then! Reply here if you need to change it.")
        return finish(_send(body, "none", "The customer picked one of the offered slots; confirming it."))

    # ---- open-ended replies: LLM first, deterministic fallback second
    if label == "hostile":
        with store.lock:
            flags["hostile"] += 1
            n = flags["hostile"]
            if n >= 2:
                flags["suppressed"] = True
        if n >= 2:
            return finish(_end("The sender stayed hostile after a calm reply; closing the conversation."))
        llm_mode, fb_kind, why = "DE_ESCALATE", "calm", "De-escalating a rude message: calm acknowledgement plus an easy way to stop."
    elif label == "intent":
        llm_mode, fb_kind = "ACTION", "action_customer" if role == "customer" else "action"
        why = "The sender committed, so switching from pitching to action right away."
    elif label == "off_topic":
        llm_mode, fb_kind, why = "NORMAL", "off_topic", "Out-of-scope request: politely declined and steered back to the original topic."
    else:
        llm_mode, fb_kind = "NORMAL", "normal_customer" if role == "customer" else "normal"
        why = "Answering the message directly and moving the conversation forward."

    trigger = store.get("trigger", conv.get("trigger_id") or "") or {"kind": "", "scope": "merchant", "payload": {}}
    ctx = composer.build_context(category, merchant, trigger, customer)
    with store.lock:
        recent = [{"from": t["from"], "body": t["body"][:400]} for t in conv["turns"][-7:-1]]
    ctx.update({"language_mode": mode_lang, "language": lang_text, "conversation": recent, "latest_message": message[:600]})

    reply = _llm_reply(ctx, llm_mode, role, label == "off_topic", category, prior)
    if reply is not None:
        return finish(_send(reply["body"], reply["cta"], reply["rationale"]))
    pick = _pick(fb_kind, prior, hinglish)
    if pick is None:
        return finish(_end("No new, non-repeating reply available; closing rather than repeating myself."))
    return finish(_send(pick["body"], pick["cta"], why + " (deterministic reply: the LLM was unavailable or its draft failed validation)"))
