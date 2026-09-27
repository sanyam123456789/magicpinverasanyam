"""Deterministic fallback messages (no LLM).

Used only when no LLM answer passes validation (or every LLM provider is down), so a `send` never has an
empty body (testing brief §10: -2) and the bot never times out. Every fact comes from the trigger payload or the
merchant/customer/category data; nothing is invented. Quality is deliberately plain: the LLM path is the product.
"""
import re
from types import SimpleNamespace

PLACE = {"dentists": "clinic", "salons": "salon", "restaurants": "restaurant", "gyms": "gym", "pharmacies": "pharmacy"}
NEXT = {"dentists": "check-up", "salons": "next visit", "restaurants": "next visit", "gyms": "next session", "pharmacies": "next refill"}
NOUN = {"dentists": "patients", "salons": "clients", "restaurants": "guests", "gyms": "members", "pharmacies": "customers"}


# ------------------------------------------------------------------ tiny helpers
def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _pct(x) -> str:
    return f"{round(abs(x) * 100):g}"


def _readable(text) -> str:
    text = str(text or "").replace("_", " ").strip()
    return re.sub(r"(\d+)(day|days)\b", r"\1-\2", text)


def _window(w) -> str:
    m = re.fullmatch(r"(\d+)d", str(w or ""))
    return f"{m.group(1)} days" if m else _readable(w)


def _clock(iso) -> str | None:
    try:
        hh, mm = int(str(iso)[11:13]), int(str(iso)[14:16])
    except ValueError:
        return None
    h12 = hh % 12 or 12
    return f"{h12}:{mm:02d}{'am' if hh < 12 else 'pm'}" if mm else f"{h12}{'am' if hh < 12 else 'pm'}"


def _labels(options) -> list[str]:
    return [o.get("label") for o in options or [] if isinstance(o, dict) and o.get("label")]


def _numbered(labels: list[str]) -> str:
    return "; ".join(f"{i}) {label}" for i, label in enumerate(labels, 1))


def _pf(pct_fraction) -> str:
    return f"{round(pct_fraction * 100, 1):g}%"


# ------------------------------------------------------------------ builders: each returns (english, hinglish|None, cta)
def _generic(S):
    if S.customer:
        return (f"Hi {S.cname}, {S.biz} here. We'd love to see you again. Reply YES and we'll help you book.",
                f"Hi {S.cname}, {S.biz} se. Hum aapko dobara dekhna chahenge. YES reply kijiye, hum booking mein help karenge.",
                "binary_yes_no")
    if S.ctr_line and S.ctr_below:
        return (f"{S.hello} {S.ctr_line}. Want me to look at what is behind it and suggest one fix?",
                f"{S.hello} {S.ctr_line_h}. Kya main dekh kar ek fix suggest kar dun?", "binary_yes_no")
    if S.ctr_line:
        return (f"{S.hello} {S.ctr_line}. Want me to show you what is working so you can build on it?",
                f"{S.hello} {S.ctr_line_h}. Kya main dikha dun ki kya kaam kar raha hai taaki aap ise aage badha sakein?", "binary_yes_no")
    return (f"{S.hello} I have a quick update on your {S.place} listing. Want me to share it?",
            f"{S.hello} aapke {S.place} listing ka ek quick update hai. Kya main share kar dun?", "binary_yes_no")


def _research_digest(S):
    it = S.item
    if not it:
        return _generic(S)
    trial = f", trial of {it['trial_n']:,}" if _num(it.get("trial_n")) else ""
    head = f'"{it.get("title")}" ({it.get("source")}{trial})'
    return (f"{S.hello} {it.get('source')} has a new item: {head}. Want me to send a 2-line summary you can share with your {S.noun}?",
            f"{S.hello} {it.get('source')} mein ek naya item aaya hai: {head}. Kya main iska 2-line summary bhej dun jo aap apne {S.noun} ke saath share kar sakein?",
            "binary_yes_no")


def _regulation_change(S):
    it = S.item
    if not it:
        return _generic(S)
    deadline = f" Deadline: {S.p['deadline_iso']}." if S.p.get("deadline_iso") else ""
    return (f"{S.hello} compliance update ({it.get('source')}): {it.get('title')}.{deadline} Want me to send a short checklist of what changes for your {S.place}?",
            f"{S.hello} compliance update ({it.get('source')}): {it.get('title')}.{deadline} Kya main aapke {S.place} ke liye ek chhota checklist bhej dun?",
            "binary_yes_no")


def _cde_opportunity(S):
    it = S.item or {}
    if not it.get("title"):
        return _generic(S)
    when = f" on {str(it['date'])[:10]}" if it.get("date") else ""
    credits = f" — {S.p['credits']} CDE credits" if _num(S.p.get("credits")) else ""
    fee = f", {_readable(S.p['fee'])}" if S.p.get("fee") else ""
    return (f"{S.hello} {it['title']}{when} ({it.get('source')}){credits}{fee}. Want me to help you register?",
            f"{S.hello} {it['title']}{when} ({it.get('source')}){credits}{fee}. Kya main registration mein help kar dun?",
            "binary_yes_no")


def _perf(S, direction):
    d = S.p.get("delta_pct")
    if S.placeholder or not _num(d):
        return _generic(S)
    metric = _readable(S.p.get("metric") or "activity")
    days = re.fullmatch(r"(\d+)d", str(S.p.get("window") or ""))
    base = f" (vs a baseline of {S.p['vs_baseline']})" if _num(S.p.get("vs_baseline")) else ""
    baseh = f" (baseline {S.p['vs_baseline']} tha)" if _num(S.p.get("vs_baseline")) else ""
    win = f" over the last {_window(S.p['window'])}" if S.p.get("window") else ""
    winh = f" pichhle {days.group(1)} din mein" if days else ""
    if direction == "dip":
        return (f"{S.hello} your {metric} are down {_pct(d)}%{win}{base}. Want me to look into what changed and suggest one fix?",
                f"{S.hello} aapke {metric}{winh} {_pct(d)}% neeche hain{baseh}. Kya main dekh kar ek fix suggest kar dun?", "binary_yes_no")
    driver = f", likely thanks to your {_readable(S.p['likely_driver'])}" if S.p.get("likely_driver") else ""
    driverh = f", shayad aapke {_readable(S.p['likely_driver'])} ki wajah se" if S.p.get("likely_driver") else ""
    return (f"{S.hello} your {metric} are up {_pct(d)}%{win}{driver}. Want me to help you build on that this week?",
            f"{S.hello} aapke {metric}{winh} {_pct(d)}% upar hain{driverh}. Kya main is momentum ko aage badhane mein help kar dun?", "binary_yes_no")


def _seasonal_perf_dip(S):
    d = S.p.get("delta_pct")
    if not _num(d):
        return _generic(S)
    metric = _readable(S.p.get("metric") or "activity")
    note = "This looks like an expected seasonal dip, not a problem with your listing. " if S.p.get("is_expected_seasonal") else ""
    return (f"{S.hello} your {metric} dipped {_pct(d)}% over the last {_window(S.p.get('window'))}. {note}Want one idea to keep customers engaged meanwhile?",
            f"{S.hello} aapke {metric} {_pct(d)}% gire hain ({_window(S.p.get('window'))}). {'Ye expected seasonal dip lagta hai, listing ki problem nahi. ' if note else ''}Kya main customers ko engaged rakhne ka ek idea bhej dun?",
            "binary_yes_no")


def _festival_upcoming(S):
    f = S.p.get("festival")
    if S.placeholder or not f:
        return (f"{S.hello} a festival window is coming up. Want me to draft a festive post for your {S.place} listing?",
                f"{S.hello} ek festival aane wala hai. Kya main aapke {S.place} listing ke liye festive post draft kar dun?", "binary_yes_no")
    days = f" ({S.p['days_until']} days away)" if _num(S.p.get("days_until")) else ""
    daysh = f" ({S.p['days_until']} din baad)" if _num(S.p.get("days_until")) else ""
    return (f"{S.hello} {f} is on {S.p.get('date')}{days}. Want me to draft a festive post and offer idea for your {S.place}?",
            f"{S.hello} {f} {S.p.get('date')} ko hai{daysh}. Kya main aapke {S.place} ke liye festive post aur offer idea draft kar dun?", "binary_yes_no")


def _category_seasonal(S):
    def fmt(t):
        m = re.fullmatch(r"(.+?)_demand_([+-])(\d+)", str(t))
        return f"{m.group(1)} demand {'up' if m.group(2) == '+' else 'down'} {m.group(3)}" if m else _readable(t)
    trends = [fmt(t) for t in (S.p.get("trends") or [])[:2]]
    if not trends:
        return _generic(S)
    return (f"{S.hello} a seasonal demand shift is under way: {', '.join(trends)}. Want me to suggest what to stock or promote?",
            f"{S.hello} seasonal demand shift chal raha hai: {', '.join(trends)}. Kya main suggest kar dun ki kya stock ya promote karein?",
            "binary_yes_no")


def _ipl_match_today(S):
    if not S.p.get("match"):
        return _generic(S)
    clock = _clock(S.p.get("match_time_iso"))
    at = f" at {S.p['venue']}" if S.p.get("venue") else ""
    when = f" tonight, {clock}" if clock else " tonight"
    return (f"{S.hello} {S.p['match']}{at}{when}. Want me to draft a match-night post for your {S.place} using your current offers?",
            f"{S.hello} {S.p['match']}{at}{when}. Kya main aapke current offers ke saath ek match-night post draft kar dun?", "binary_yes_no")


def _competitor_opened(S):
    if S.placeholder or not S.p.get("competitor_name"):
        return (f"{S.hello} a new competitor has opened near your {S.place}. Want me to compare their listing with yours?",
                f"{S.hello} aapke {S.place} ke paas ek naya competitor khula hai. Kya main unki listing aapse compare kar dun?", "binary_yes_no")
    dist = f" {S.p['distance_km']:g} km away" if _num(S.p.get("distance_km")) else " nearby"
    disth = f" {S.p['distance_km']:g} km door" if _num(S.p.get("distance_km")) else " kaafi paas"
    on = f" on {S.p['opened_date']}" if S.p.get("opened_date") else ""
    onh = f" {S.p['opened_date']} ko" if S.p.get("opened_date") else ""
    offer = f", offering {S.p['their_offer']}" if S.p.get("their_offer") else ""
    offerh = f", offer: {S.p['their_offer']}" if S.p.get("their_offer") else ""
    return (f"{S.hello} a new competitor, {S.p['competitor_name']}, opened{dist}{on}{offer}. Want me to compare their listing with yours?",
            f"{S.hello} ek naya competitor, {S.p['competitor_name']},{onh} aapse{disth} khula hai{offerh}. Kya main unki listing aapse compare kar dun?", "binary_yes_no")


def _milestone_reached(S):
    now, goal = S.p.get("value_now"), S.p.get("milestone_value")
    if not (_num(now) and _num(goal)):
        return _generic(S)
    metric = _readable(S.p.get("metric") or "count")
    left = goal - now
    if left > 0:
        return (f"{S.hello} you are at {now:g} {metric}, just {left:g} away from {goal:g}. Want me to help you cross it this week?",
                f"{S.hello} aap {now:g} {metric} par hain, {goal:g} se sirf {left:g} door. Kya main is hafte ye cross karne mein help kar dun?",
                "binary_yes_no")
    return (f"{S.hello} you have reached {goal:g} {metric}. Want me to turn it into a post for your listing?",
            f"{S.hello} aap {goal:g} {metric} tak pahunch gaye. Kya main ise aapki listing ke liye post bana dun?", "binary_yes_no")


def _dormant(S):
    d = S.p.get("days_since_last_merchant_message")
    since = f"it has been {d:g} days since we last spoke" if _num(d) else "it has been a while since we last spoke"
    sinceh = f"hamari last baat ko {d:g} din ho gaye" if _num(d) else "kaafi time ho gaya hamari baat hue"
    return (f"{S.hello} {since}. Want a quick update on how your listing is doing?",
            f"{S.hello} {sinceh}. Kya main aapki listing ka ek quick update bhej dun?", "binary_yes_no")


ASKS = {"what_service_in_demand_this_week": ("Which service has been most in demand at {biz} this week?",
                                              "Is hafte {biz} mein sabse zyada kaunsi service chal rahi hai?")}


def _curious_ask(S):
    template = S.p.get("ask_template") if isinstance(S.p.get("ask_template"), str) else None
    en, hi = ASKS.get(template, ("What has been your busiest service this week?",
                                                 "Is hafte aapki sabse busy service kaunsi rahi?"))
    return (f"{S.hello} quick question: {en.format(biz=S.biz)} I'll turn your answer into a ready-to-post update for your listing.",
            f"{S.hello} ek quick sawal: {hi.format(biz=S.biz)} Aapke jawab se main aapki listing ke liye ready-to-post update bana dungi.",
            "open_ended")


def _renewal_due(S):
    days, plan, amt = S.p.get("days_remaining"), S.p.get("plan"), S.p.get("renewal_amount")
    if not _num(days):
        return _generic(S)
    cost = f" (renewal ₹{amt:,})" if _num(amt) else ""
    return (f"{S.hello} your {plan or ''} plan has {days:g} days left{cost}. Want me to renew it so your listing stays live?".replace("  ", " "),
            f"{S.hello} aapke {plan or ''} plan mein {days:g} din bache hain{cost}. Kya main renew kar dun taaki listing live rahe?".replace("  ", " "),
            "binary_yes_no")


def _review_theme(S):
    theme, occ, quote = S.p.get("theme"), S.p.get("occurrences_30d"), S.p.get("common_quote")
    if not (theme and _num(occ)):
        negs = [t for t in S.mer.get("review_themes") or [] if t.get("sentiment") == "neg"]
        if not negs:
            return _generic(S)
        theme, occ, quote = negs[0].get("theme"), negs[0].get("occurrences_30d"), negs[0].get("common_quote")
    q = f': "{quote}"' if quote else ""
    return (f"{S.hello} {occ:g} reviews in the last 30 days mention {_readable(theme)}{q}. Want me to draft a reply and one fix?",
            f"{S.hello} pichhle 30 din mein {occ:g} reviews mein {_readable(theme)} ka zikr hai{q}. Kya main reply aur ek fix draft kar dun?",
            "binary_yes_no")


def _gbp_unverified(S):
    up = S.p.get("estimated_uplift_pct")
    path = f" via {_readable(S.p['verification_path'])}" if S.p.get("verification_path") else ""
    est = f" is estimated to lift visibility by about {_pct(up)}%" if _num(up) else " can improve your visibility"
    pathh = f" {_readable(S.p['verification_path'])} ke zariye" if S.p.get("verification_path") else ""
    esth = (f" verify karne se visibility lagbhag {_pct(up)}% badh sakti hai (estimate)" if _num(up)
            else " verify karne se visibility badh sakti hai")
    return (f"{S.hello} your Google listing is still unverified. Verifying{path}{est}. Want me to walk you through it?",
            f"{S.hello} aapki Google listing abhi unverified hai.{pathh}{esth}. Kya main steps bata dun?",
            "binary_yes_no")


def _winback_eligible(S):
    d, n = S.p.get("days_since_expiry"), S.p.get("lapsed_customers_added_since_expiry")
    if not (_num(d) and _num(n)):
        return _generic(S)
    return (f"{S.hello} your plan expired {d:g} days ago and {n:g} more customers have gone quiet since then. Want me to help you reactivate?",
            f"{S.hello} aapka plan {d:g} din pehle expire hua aur tab se {n:g} aur customers quiet ho gaye. Kya main reactivate karne mein help kar dun?",
            "binary_yes_no")


def _supply_alert(S):
    mol, batches = S.p.get("molecule"), S.p.get("affected_batches")
    if not (mol and batches):
        return _generic(S)
    who = f" from {S.p['manufacturer']}" if S.p.get("manufacturer") else ""
    return (f"{S.hello} urgent: {mol} supply alert{who}, batches {', '.join(batches)}. Want me to draft a note for customers who may be affected?",
            f"{S.hello} urgent: {mol} supply alert{who}, batches {', '.join(batches)}. Kya main affected customers ke liye ek note draft kar dun?",
            "binary_yes_no")


def _active_planning(S):
    topic = _readable(S.p.get("intent_topic") or "your plan")
    return (f"{S.hello} great, I am putting together a first draft for {topic} based on your current offers. Reply YES and I will send it here.",
            f"{S.hello} badhiya, main aapke current offers ke basis par {topic} ka pehla draft bana rahi hoon. YES reply kijiye, main yahin bhej dungi.",
            "binary_yes_no")


def _recall_due(S):
    labels = _labels(S.p.get("available_slots"))
    service = _readable(S.p.get("service_due") or NEXT.get(S.slug, "next visit"))
    last = S.p.get("last_service_date") or S.rel.get("last_visit")
    seen = f" (last visit {last})" if last else ""
    if not labels:
        return (f"Hi {S.cname}, {S.biz} here. Your {service} is due{seen}. Reply YES and we will share available slots.",
                f"Hi {S.cname}, {S.biz} se. Aapka {service} due hai{seen}. YES reply kijiye, hum available slots bhej denge.", "binary_yes_no")
    reply = "Reply 1 or 2" if len(labels) > 1 else "Reply 1"
    return (f"Hi {S.cname}, {S.biz} here. Your {service} is due{seen}. Available slots: {_numbered(labels)}. {reply}, or tell us a time that works.",
            f"Hi {S.cname}, {S.biz} se. Aapka {service} due hai{seen}. Available slots: {_numbered(labels)}. {reply.replace(' or ', ' ya ')}, ya koi aur time bata dijiye.",
            "multi_choice_slot")


def _appointment_tomorrow(S):
    return (f"Hi {S.cname}, {S.biz} here. A reminder about your appointment tomorrow. Please reply YES to confirm.",
            f"Hi {S.cname}, {S.biz} se. Kal aapka appointment hai. Confirm karne ke liye YES reply kijiye.", "binary_yes_no")


def _lapsed(S, hard):
    last = S.rel.get("last_visit")
    seen = f" since your last visit on {last}" if last else ""
    seenh = f" (last visit {last})" if last else ""
    offer = f" ({S.active[0]})" if S.active else ""
    days = S.p.get("days_since_last_visit")
    if hard and _num(days):
        focus = f" We would love to help you get back to your {_readable(S.p['previous_focus'])} goal." if S.p.get("previous_focus") else ""
        return (f"Hi {S.cname}, {S.biz} here. It has been {days:g} days{seen.replace(' since your last visit on', ', last visit on')} — no judgment, it happens.{focus} Reply YES and we will set up an easy restart{offer}.",
                f"Hi {S.cname}, {S.biz} se. Aapko aaye {days:g} din ho gaye — koi baat nahi, aisa hota hai. YES reply kijiye, hum aasan restart set kar denge{offer}.",
                "binary_yes_no")
    return (f"Hi {S.cname}, {S.biz} here. It has been a while{seen} and we would love to see you again{offer}. Reply YES and we will set it up.",
            f"Hi {S.cname}, {S.biz} se. Kaafi time ho gaya{seenh} aur hum aapko dobara dekhna chahenge{offer}. YES reply kijiye, hum set kar denge.",
            "binary_yes_no")


def _chronic_refill(S):
    mols = S.p.get("molecule_list")
    if S.placeholder or not mols:
        last = S.rel.get("last_visit")
        seen = f" Your last visit was on {last}." if last else ""
        return (f"Hi {S.cname}, {S.biz} here. We wanted to check in.{seen} Reply YES if you would like us to set up your next one.",
                f"Hi {S.cname}, {S.biz} se. Hum check-in karna chahte the.{seen} Agla set up karna ho toh YES reply kijiye.", "binary_yes_no")
    date = str(S.p.get("stock_runs_out_iso") or "")[:10]
    around = f" around {date}" if date else ""
    aroundh = f" {date} ke aas-paas" if date else ""
    deliver = " for delivery to your saved address" if S.p.get("delivery_address_saved") else ""
    deliverh = " saved address par delivery ke saath" if S.p.get("delivery_address_saved") else ""
    return (f"Namaste {S.cname}, {S.biz} here. Your regular medicines ({', '.join(mols)}) are due for refill{around}. Reply CONFIRM and we will arrange it{deliver}.",
            f"Namaste {S.cname}, {S.biz} se. Aapki regular medicines ({', '.join(mols)}) ka refill{aroundh} due hai. CONFIRM reply kijiye, hum arrange kar denge{deliverh}.",
            "binary_confirm_cancel")


def _trial_followup(S):
    labels = _labels(S.p.get("next_session_options"))
    if not labels:
        return _generic(S)
    when = f" on {S.p['trial_date']}" if S.p.get("trial_date") else ""
    ask = f"Reply YES to book {labels[0]}." if len(labels) == 1 else "Reply with the number you prefer."
    askh = f"{labels[0]} book karne ke liye YES reply kijiye." if len(labels) == 1 else "Jo number suit kare wo reply kijiye."
    return (f"Hi {S.cname}, {S.biz} here. Thanks for trying us out{when}! Next session: {_numbered(labels)}. {ask}",
            f"Hi {S.cname}, {S.biz} se. Trial{when} ke liye shukriya! Agla session: {_numbered(labels)}. {askh}",
            "binary_yes_no" if len(labels) == 1 else "multi_choice_slot")


def _wedding_followup(S):
    date, days = S.p.get("wedding_date"), S.p.get("days_to_wedding")
    if not date:
        return _generic(S)
    away = f" ({days:g} days away)" if _num(days) else ""
    step = f" The {_readable(S.p['next_step_window_open'])} window is open." if S.p.get("next_step_window_open") else ""
    return (f"Hi {S.cname}, {S.biz} here. Your wedding on {date}{away} is coming up.{step} Reply YES and we will set up your next step.",
            f"Hi {S.cname}, {S.biz} se. Aapki shaadi {date}{away} ko hai.{step} YES reply kijiye, hum aapka agla step set kar denge.",
            "binary_yes_no")


BUILDERS = {
    "research_digest": _research_digest, "regulation_change": _regulation_change, "cde_opportunity": _cde_opportunity,
    "perf_dip": lambda S: _perf(S, "dip"), "perf_spike": lambda S: _perf(S, "spike"),
    "seasonal_perf_dip": _seasonal_perf_dip, "festival_upcoming": _festival_upcoming,
    "category_seasonal": _category_seasonal, "ipl_match_today": _ipl_match_today,
    "competitor_opened": _competitor_opened, "milestone_reached": _milestone_reached,
    "dormant_with_vera": _dormant, "curious_ask_due": _curious_ask, "renewal_due": _renewal_due,
    "review_theme_emerged": _review_theme, "gbp_unverified": _gbp_unverified, "winback_eligible": _winback_eligible,
    "supply_alert": _supply_alert, "active_planning_intent": _active_planning,
    "recall_due": _recall_due, "appointment_tomorrow": _appointment_tomorrow,
    "customer_lapsed_soft": lambda S: _lapsed(S, False), "customer_lapsed_hard": lambda S: _lapsed(S, True),
    "chronic_refill_due": _chronic_refill, "trial_followup": _trial_followup,
    "wedding_package_followup": _wedding_followup,
}


def build(category: dict, merchant: dict, trigger: dict, customer: dict | None, ctx: dict, name: str) -> dict:
    """Return {"body", "cta", "rationale"} built only from the given data."""
    slug = category.get("slug")
    slug = slug if isinstance(slug, str) else ""
    identity = merchant.get("identity") or {}
    perf, peer = merchant.get("performance") or {}, category.get("peer_stats") or {}
    ctr_line = ctr_line_h = ""
    ctr_below = False
    if _num(perf.get("ctr")) and _num(peer.get("avg_ctr")):
        ctr_line = f"your 30-day CTR is {_pf(perf['ctr'])} vs a peer average of {_pf(peer['avg_ctr'])}"
        ctr_line_h = f"aapka 30-day CTR {_pf(perf['ctr'])} hai, peer average {_pf(peer['avg_ctr'])} hai"
        ctr_below = perf["ctr"] < peer["avg_ctr"]
    S = SimpleNamespace(
        name=name, hello=f"{name}," if name.startswith("Dr.") else f"Hi {name},",
        biz=identity.get("name") or "your business", place=PLACE.get(slug, "business"), noun=NOUN.get(slug, "customers"),
        mer=merchant, cat=category, p=trigger.get("payload") or {}, placeholder=bool((trigger.get("payload") or {}).get("placeholder")),
        customer=customer, cname=str(((customer or {}).get("identity") or {}).get("name") or "there"),
        rel=(customer or {}).get("relationship") or {}, item=(ctx.get("category") or {}).get("digest_item"),
        active=[o.get("title") for o in merchant.get("offers") or [] if o.get("status") == "active" and o.get("title")],
        ctr_line=ctr_line, ctr_line_h=ctr_line_h, ctr_below=ctr_below, slug=slug,
    )
    kind = trigger.get("kind")
    kind = kind if isinstance(kind, str) else ""
    english, hinglish, cta = BUILDERS.get(kind, _generic)(S)
    body = hinglish if (hinglish and ctx.get("language_mode", "en") != "en") else english
    if any(bad in body for bad in ("None", "{", "}", "nan")):
        english, hinglish, cta = _generic(S)
        body = hinglish if (hinglish and ctx.get("language_mode", "en") != "en") else english
    return {"body": " ".join(body.split()), "cta": cta,
            "rationale": f"Deterministic fallback for {kind or 'trigger'}: built only from the trigger payload and merchant/customer data."}
