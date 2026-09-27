# Magicpin VERA AI Challenge — Steps 1 to 6

> **Ye document kya hai:** ek technical execution diary, Hinglish mein. Isme sirf wahi likha hai jo challenge ke material mein confirm hua hai ya jo humne actually implement/verify kiya hai.
> **Material** = `challenge-brief.md`, `challenge-testing-brief.md`, `engagement-design.md`, `engagement-research.md`, `judge_simulator.py`, `examples/api-call-examples.md`, `examples/case-studies.md`, dataset, aur website ke 6 screenshots.
> **Labels:** `[CONFIRMED]` = material mein likha hai. `[RECOMMENDED]` = material ne suggest kiya ya humari implementation choice. `[OPTIONAL]` = zaroori nahi. `Not specified in the provided material` = material mein nahi hai, hum assume nahi karte.
> **Last updated:** 2026-09-27, after the **Final Audit Before Step 7** (aakhri section). Offline verification: 359 checks pass (`python tests/run_all.py`). **Live verification with a real LLM abhi bhi pending hai** (API keys `.env` mein nahi hain).

---

## 1. Challenge Overview

**Kya banana hai:** magicpin ke merchant assistant **Vera** jaisa ek chatbot server, jo WhatsApp par merchants (aur merchant ke customers) ko message likhta hai. Ek AI judge us bot ko score karta hai. Sabko same base dataset milta hai.

**Bot ko 4 context milte hain:** `category` (business type ka knowledge), `merchant` (us dukaan ka data), `trigger` (abhi message kyun), aur optional `customer`. In se ek message banta hai: `compose(category, merchant, trigger, customer?) -> {body, cta, send_as, suppression_key, rationale}`.

**Bot ke 5 HTTP endpoints (public URL par):** `POST /v1/context`, `POST /v1/tick`, `POST /v1/reply`, `GET /v1/healthz`, `GET /v1/metadata`. Judge inhe call karta hai.

**Judge ka flow:** Warmup (base dataset push) → 60 simulated minutes ka test window (har 5 min ek tick) → beech mein naya context inject (digest, performance, triggers, customers) → top 10 bots ka replay test (auto-reply, intent transition, hostile/off-topic) → score report.

**Scoring:** har message 0–10 par 5 dimensions (total 50): Specificity, Category fit, Merchant fit, Decision quality (brief mein "Trigger relevance"), Engagement compulsion. Phase 3 adaptation bonus max +5 per dimension, Phase 4 replay max +30, operational penalties max -20.

**Humari deadline:** aapne bataya "kal 3pm tak". Official material mein deadline **Not specified in the provided material** (brief §14 sirf placeholder hai).

---

## 2. Confirmed Requirements

Type: **M** = mandatory, **R** = recommended, **O** = optional.

### A. Submission aur logistics
| ID | Requirement | Source | Type |
|---|---|---|---|
| R01 | Ek public bot URL, jis par saare endpoints `https://<host>/v1/*` par mile | testing brief §2, §6; website | M |
| R02 | Submit ke baad bot live aur reachable rahe | website FAQ | M |
| R03 | Portal par final entry submit karni hai (details). Exact form fields **Not specified** | website | M |
| R04 | README.md, 1 page max: approach, tradeoffs, kaunsa extra context help karta. Website "can explain" bolti hai | brief §7.3; website | R |
| R05 | `submission.jsonl`, 30 lines, har test pair ke liye. Website is par chup hai | brief §7.2 | R |
| R06 | `bot.py` jisme `compose()` ho | brief §7.1 | R |
| R07 | `conversation_handlers.py` ka `respond()` | brief §7.4 ("tiebreaker, not a requirement") | O |
| R08 | Sirf solo applications | website FAQ | M |

### B. Endpoints
| ID | Requirement | Source | Type |
|---|---|---|---|
| R10 | `POST /v1/context`: envelope `{scope, context_id, version, payload, delivered_at}`. Nayi ya zyada version replace kare. Response `200 {accepted, ack_id, stored_at}`. **Same ya purani version par `409 {accepted:false, reason:"stale_version", current_version}`**. Galat scope par `400 {accepted:false, reason:"invalid_scope", details}` | testing brief §2.1; api-call-examples 1.3–1.6 | M |
| R11 | Context payload 500 KB tak accept ho | testing brief §5 | M |
| R12 | `GET /v1/healthz` → `{status, uptime_seconds, contexts_loaded:{category,merchant,customer,trigger}}`. Counts wahi hone chahiye jo judge ne push kiye | testing brief §2.4, §4; examples 1.7 | M |
| R13 | `GET /v1/metadata` → `team_name, team_members, model, approach, contact_email, version, submitted_at` | testing brief §2.5 | M |
| R14 | `POST /v1/tick` `{now, available_triggers}` → `{"actions":[...]}`. Khaali list allowed. Har action mein `conversation_id, merchant_id, customer_id, send_as, trigger_id, template_name, template_params, body, cta, suppression_key, rationale` | testing brief §2.2; examples 2.2 | M |
| R15 | Ek tick mein max 20 actions. Ek `(merchant, conversation)` ka sirf ek action per tick. `conversation_id` naya unique hona chahiye | testing brief §2.2, §5, FAQ | M |
| R16 | `POST /v1/reply` → `{action:"send", body, cta, rationale}` ya `{action:"wait", wait_seconds, rationale}` ya `{action:"end", rationale}` | testing brief §2.3 | M |
| R17 | Response time: hard limit 30s. `api-call-examples.md` ki table mein tick/reply 10s, context 5s, healthz/metadata 2s. Simulator 15s use karta hai | testing brief §2.3, §5; examples summary table | M |
| R18 | Bot stateful ho: contexts aur conversations test khatam hone tak yaad rahein, restart nahi | testing brief §2.1, §12 | M |
| R19 | `POST /v1/teardown` par saara state wipe (judge optional bhejta hai) | testing brief §11 | R |
| R20 | Judge se 10 requests/sec tak | testing brief §5 | M |

### C. Message composition
| ID | Requirement | Source | Type |
|---|---|---|---|
| R21 | `compose(category, merchant, trigger, customer?)` → `body, cta, send_as, suppression_key, rationale` | brief §5, §7.1 | M |
| R22 | Same input par same output (temperature 0). Call 30s se kam | brief §7.1; website | M |
| R23 | **Fabrication nahi**: data mein jo nahi hai (offer, research, competitor, number) wo message mein nahi | brief §5.8, §11; FAQ; simulator penalty -2 | M |
| R24 | **Specificity**: message ek verifiable fact (number, date, headline, source) par anchor ho | brief §5.5, §8 | M |
| R25 | **Category fit**: voice, vocabulary, taboo words se bachna | brief §5.6, §8; category `voice` | M |
| R26 | **Merchant fit**: us merchant ke numbers, offers, history, owner name | brief §8; case-studies | M |
| R27 | **Language**: merchant ki language match. Hindi-English mix theek aur preferred. Customer ke liye `language_pref` | brief §5.7; testing FAQ | M |
| R28 | **Trigger relevance / "why now"** clearly | brief §8 | M |
| R29 | **Decision quality**: ek sabse strong signal chunna, har fact repeat nahi | website | M |
| R30 | **Engagement compulsion**: ek strong reason to reply, low-effort next step, levers (brief §10) | brief §8, §10; website | M |
| R31 | **Ek primary CTA**. Action triggers par binary, pure-info par CTA nahi. Booking flow mein multi-choice slots allowed. CTA last sentence mein | brief §5.3, §11 | M |
| R32 | `send_as`: `vera` (merchant-facing), `merchant_on_behalf` (customer-facing) | brief §5, App. B | M |
| R33 | Pehla outbound WhatsApp template se: `template_name` + `template_params` | brief §5.1; testing brief §2.2 | M |
| R34 | **Body mein koi URL nahi.** Brief "allowed" bolti hai, par examples F.4 mein URL par hard fail aur -3 penalty hai, isliye strictest reading follow karte hain | examples F.4 vs brief §5.4 | M |
| R35 | Lambi preamble nahi, pehle message ke baad dobara introduction nahi | brief §11 | M |
| R36 | Anti-repetition: same conversation mein wahi body dobara nahi (-2 per repeat) | testing brief §10; examples F.5 | M |
| R37 | `suppression_key` trigger se aaye, aur same key dobara na bheje | brief §4.3 | M |
| R38 | `rationale` chhota ho aur asli output se match kare | testing FAQ; case-studies pattern 9 | M |
| R39 | Customer-facing: merchant ka real offer aur real slots, customer ka naam, language, preferred time | brief App. B; case-studies | M |
| R40 | **Case-study ka text copy nahi.** Judge similarity check chalata hai aur near-duplicates penalise karta hai | case-studies.md (last section) | M |

### D. Multi-turn (`/v1/reply`)
| ID | Requirement | Source | Type |
|---|---|---|---|
| R41 | Auto-reply pehchaano aur gracefully exit karo | brief §12.1; testing Phase 4 | M |
| R42 | Intent transition: "let's do it" par turant action, naya qualifying sawal nahi | brief §12.2, Pattern D; testing Phase 4 | M |
| R43 | Hostile ya opt-out par exit. Off-topic (jaise GST) par politely mana karke mission par wapas | testing Phase 4; examples 2.6, 2.7, 4.3 | M |
| R44 | Kab rukna hai: not-interested ya 3 unanswered nudges ke baad | brief §12.5 | R |
| R45 | Har turn par language detect (English ↔ Hindi switch) | brief §12.4 | R |
| R46 | Merchant time maange toh `wait` | testing §2.3 example | R |
| R47 | `end` ke baad us `conversation_id` par koi message nahi. Hostile par merchant ke triggers 30 din suppress | examples 2.6, 4.3 | M |

### E. Adaptation aur operations
| ID | Requirement | Source | Type |
|---|---|---|---|
| R48 | Judge ka naya context (digest, performance, triggers, customers) agle sends mein use ho, bina hallucinate kiye | testing Phase 3; brief §8 | M |
| R49 | Restraint: kuch worth na ho toh `actions: []`. Spam par penalty | testing FAQ | M |
| R50 | Koi bhi context kabhi bhi aa sakta hai (naya merchant beech mein bhi) | testing FAQ | M |
| R51 | Kabhi crash ya malformed JSON nahi. `send` par empty body nahi (-2) | testing §10 | M |

### F. Privacy aur ethics
| ID | Requirement | Source | Type |
|---|---|---|---|
| R52 | Payload sirf LLM APIs ko jaaye, kisi non-LLM external API ko nahi | testing §11 | M |
| R53 | Test ke baad context persist nahi | testing §11 | R |
| R54 | Real magicpin ya Google data scrape nahi, magicpin ban ke koi external test nahi | brief §15 | M |

### G. Material mein NAHI hai (Not specified in the provided material)
- Official deadline, evaluation ka exact date/time.
- Demo video, screenshots, ya repository (GitHub) ki requirement.
- Portal form ke exact fields.
- Hosting ki koi requirement, sirf public URL.
- Prizes, compute reimbursement, next round ka exact format.
- Kaunse LLM allowed hain ki koi list: sirf "OpenAI, Anthropic, Google, DeepSeek, etc." likha hai. Groq aur OpenRouter simulator ke providers mein hain.
- Consent ke basis par message rokne ka rule.
- `wait_seconds` ki limit.

---

## 3. Mandatory vs Optional Requirements

**Mandatory:** R01–R03, R08, R10–R18, R20–R43, R47–R52, R54.
**Recommended:** R04, R05, R06, R19, R44, R45, R46, R53.
**Optional:** R07 (`conversation_handlers.py`). **Humara decision:** Steps 1–6 mein skip. Asli multi-turn `/v1/reply` endpoint se hota hai, aur `ConversationState` ka type material mein defined nahi hai. Step 10 mein dobara decide karenge.

### Material ke andar ke conflicts aur humara decision
| # | Conflict | Kya follow karein aur kyun |
|---|---|---|
| C1 | Brief §7: `bot.py` + `submission.jsonl` + README. Testing brief aur website: public URL + README | **URL.** Website live flow hai, testing brief technical contract. `bot.py` aur `submission.jsonl` backup ke liye banayenge |
| C2 | 5th dimension: brief:316 "Trigger relevance"; website "Decision quality"; **simulator ka prompt-text "TRIGGER RELEVANCE" (judge_simulator.py:465) hai par uska JSON key/label `decision_quality` (:126, :487)** | Dono ko satisfy karte hain: ek best signal chuno **aur** "abhi kyun" saaf likho. (Meri pehli summary ne likha tha "simulator bhi Decision quality bolta hai": wo adhura tha, audit mein sudhaara) |
| C3 | Team size: brief "solo ya pairs" (placeholder), FAQ "Solo only" | **FAQ** |
| C4 | Testing brief §2.1: "same version dobara = no-op", 409 sirf "higher version" par. Example 1.5: **same version dobara push par 409** | **Example 1.5**, kyunki wo exact request/response dikhata hai aur testing brief ka skeleton bhi `>=` use karta hai |
| C5 | Timeout: 30s (testing brief) vs 10s tick/reply, 5s context, 2s healthz (examples table). Simulator 15s | **Strictest: 10s** ke andar design karenge. 30s hard limit hai |
| C6 | URL in body: brief §5.4 aur FAQ "allowed jab value ho", examples F.4 "hard fail, -3" | **Koi URL nahi** |
| C7 | Trigger ka merchant: brief §6 `payload.merchant_id`, testing brief, examples aur **asli data** top-level `merchant_id` | **Top-level** (data mein 100/100). Defensive fallback payload par bhi |
| C8 | Auto-reply: Example 2.5 (pehli baar `wait` 14400) vs Example 4.1 (pehli baar `send`, doosri `wait` 86400, teesri `end`) | **Example 4.1** (replay test ka "Good bot response") |
| C9 | Hostile: Phase 4 "abuse ke baad off-topic, on-mission raho" vs Example 4.3 aur simulator "hostile par `end`" | **Explicit stop/opt-out par `end`. Sirf abuse par calm reply aur mission par wapas** (Example 2.7 jaisa off-topic decline) |
| C10 | `curl` example raw category JSON post karta hai, contract envelope maangta hai | **Envelope** |
| C11 | Deterministic chahiye, par LLM temperature 0 par bhi 100% deterministic nahi | Input-hash **cache** se same output |
| C12 | Opt-out ke baad: Example 2.6 "suppressing this conversation_id" (api-call-examples.md:320) vs Example 4.3 "Suppressing all triggers for this merchant for 30 days" (:529) | Plain opt-out = sirf woh conversation. Opt-out **aur** hostile = merchant suppress (audit mein sudhaara) |
| C13 | FAQ (testing brief:536): "only one action per (merchant_id, conversation_id) pair per tick" vs hamara pehle wala "ek merchant ka ek hi action per tick" | **FAQ (spec).** Hamara rule spec se zyada strict tha aur expected messages daba sakta tha; hata diya (audit) |
| C14 | Placeholder triggers: sirf `dataset/generate_dataset.py:225-240` mein hain ("5 of each kind"), kisi brief ya example mein unka expected handling nahi | **Not specified.** Sirf merchant/customer/category ke facts use, kuch invent nahi |

---

## 4. Step 1

### Objective
Coding shuru karne se pehle challenge ki asli requirements aur asli data ka structure confirm karna, taaki koi mandatory cheez miss na ho aur koi cheez guess na karni pade.

### What we need to do
1. Saari files aur screenshots padhna (5 docs, 6 screenshots, simulator).
2. `examples/api-call-examples.md` aur `examples/case-studies.md` padhna. Ye pehle nahi padhi thi.
3. Dataset expand karna aur uska real structure dekhna (field names, trigger kinds, placeholder triggers).
4. Requirements ki list aur conflicts banana (section 2 aur 3).

### Implementation (jo kiya gaya)
- Package `E:\MAGICPIN` mein copy kiya. `python dataset/generate_dataset.py --seed-dir dataset --out expanded` chalaya.
- `tests/verify_step1_dataset.py` likha (repeatable check).

### Files/changes
- Naya: `tests/verify_step1_dataset.py`, `expanded/` (generator ka output), yeh document.
- Package ki original files (`dataset/`, `examples/`, briefs, `judge_simulator.py`) me koi badlav nahi.

### Verification (asli result)
`python tests/verify_step1_dataset.py` → **ALL CHECKS PASSED**: 5 categories, 50 merchants, 200 customers, 100 triggers, 30 pairs. Har pair ka merchant, trigger, customer aur category mil gaya. Digest ke saare references resolve hote hain.

### Data se mile important facts
1. **Trigger structure:** har trigger ke top-level par `id, scope, kind, source, merchant_id, customer_id, payload, urgency, suppression_key, expires_at`. `merchant_id` payload ke andar kabhi nahi.
2. **26 trigger kinds** hain, jo brief ke examples se zyada hain (jaise `supply_alert`, `cde_opportunity`, `winback_eligible`, `gbp_unverified`, `renewal_due`, `trial_followup`). Judge naye kinds bhi bhej sakta hai, isliye unknown kind ko gracefully handle karna hoga.
3. **30 canonical pairs mein se 13 ke trigger `placeholder`** hain (`{"placeholder": true, "metric_or_topic": <kind>}`): T03, T04, T08, T10, T12, T14, T15, T17, T19, T23, T25, T27, T29. Inme trigger ka koi detail nahi hai, toh message merchant/category/customer data se banana hoga, bina kuch invent kiye.
4. **9 pairs customer-facing** hain: T03, T04, T07, T08, T13, T14, T15, T28, T29.
5. **Placeholder wale customer records mein `services_received` khaali** hai aur consent aksar sirf `["promotional_offers"]`. 200 mein se 186 customers ka consent yehi hai. Isliye consent par message rokna practical nahi, aur material mein aisa rule bhi nahi hai. Hum consent prompt ko dete hain, block nahi karte.
6. **Merchant languages:** saare 50 merchants ki `languages` mein `hi` hai. Customer `language_pref` ki values: `en` 78, `hi-en mix` 61, `hi` 52, `english` 5, `ta-en mix` 2, `te-en mix` 1, `kn-en mix` 1.
7. **Category size** ~6–7 KB, toh poora category prompt mein aa sakta hai. Digest items mein `id, kind, title, source, summary, actionable` (aur kabhi `trial_n`, `patient_segment`, `credits`, `date`).
8. **Voice ke keys:** `tone, register, code_mix, vocab_allowed, vocab_taboo, salutation_examples, tone_examples`. Taboo ka key `vocab_taboo` hai (testing brief ke `taboos` se alag). Simulator bhi `vocab_taboo` padhta hai.
9. **Merchant ke extra fields** jo brief ke schema mein nahi the: `review_themes`, `identity.owner_first_name`, `identity.established_year`, `performance.leads`, `subscription.renewed_at`. 42 merchants ki `conversation_history` khaali hai.
10. **Kuch triggers ki category mismatch hai** (jaise T08: dentist merchant par `chronic_refill_due`). Bot ko wahan trigger ko blindly follow nahi karna, aur kuch invent bhi nahi karna.
11. **Trigger dates:** kai triggers ki `expires_at` April–June 2026 hai, aur `judge_simulator.py` tick mein `datetime.utcnow()` (asli aaj ki date) bhejta hai. Agar hum expiry par filter karte, toh simulator ke saath ek bhi message nahi jaata. **Isliye `expires_at` par filter nahi karenge.** Judge ka `available_triggers` hint pehle se "active right now" list hai.
12. **Simulator ki limits:** warmup mein sirf 5 merchants push hote hain, customers nahi. Toh bot ko missing merchant ya customer par gracefully skip karna hoga.

### Completion criteria
- [x] Saara material padha, requirements ki list aur conflicts likhe.
- [x] Dataset expand aur verify.
- [x] Real field names aur trigger kinds confirm.
- [x] Verification script pass.

**Status: Step 1 COMPLETE.**

---

## 5. Step 2

### Objective
Judge jin 5 endpoints ko call karta hai (aur ek optional `/v1/teardown`), unka exact schema, status codes aur idempotency implement karna. Sab se pehle ye isliye, kyunki warmup mein `contexts_loaded` count check hota hai aur healthz fail hone par -10 penalty hai.

### What we need to do
- `POST /v1/context`: envelope validate karna, version rules (same ya purani version par 409, nayi par replace), galat input par 400.
- `GET /v1/healthz`, `GET /v1/metadata`, `POST /v1/teardown`.
- `/v1/tick` aur `/v1/reply` ka valid-shape skeleton (asli logic Steps 5 aur 6 mein).
- State thread-safe aur in-memory.

### Implementation
- `store.py`: `Store` class (RLock ke saath). `put_context()` sirf **strictly higher** version accept karta hai (Example 1.5: same version par bhi 409). Replace atomic hai.
- `bot.py`: FastAPI app. `/v1/context` request body ko khud parse karta hai (Pydantic ka default 422 nahi, spec wala 400 `{accepted:false, reason, details}`). `ack_id = ack_<context_id>_v<version>` (Examples ke jaisa), `stored_at` ISO UTC milliseconds ke saath.
- `config.py`: chhota `.env` loader (extra dependency nahi). Environment variable hamesha `.env` se upar.
- `/v1/metadata`: `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL` `.env` se. **Abhi `TO_BE_SET` hain, kyunki ye info aapse chahiye, humne invent nahi ki.** `model` field LLM config se banta hai, `approach` ek fixed sach-sach description hai.
- `requirements.txt`, `.env.example` (sirf placeholders), `.gitignore` (`.env` shamil).

### Files/changes
Naye: `store.py`, `bot.py`, `config.py`, `requirements.txt`, `.env.example`, `.gitignore`, `tests/verify_step2_endpoints.py`.

### Verification (asli result)
`python tests/verify_step2_endpoints.py` (asli uvicorn server spawn karta hai): **33 checks PASS**.
- Healthz fresh bot par sab zero (Example 1.1); 255 base contexts ke baad `5/50/200/0` (Example 1.7); 100 triggers ke baad `trigger: 100`.
- v1 accept, same v1 dobara par exact body `{"accepted":false,"reason":"stale_version","current_version":1}` (409), v2 replace, v1 dobara par 409 `current_version 2`, replace se duplicate nahi banta.
- 5 tarah ka galat input (galat scope, non-JSON, payload missing, string version, JSON array) sab 400, koi 500 nahi. ~480 KB payload accept.
- Latency: healthz 18 ms, metadata 13 ms, context 16 ms (limit 2s/2s/5s). Server log mein koi Traceback nahi.
- Extra evidence: official `judge_simulator.py` ka apna `BotClient` hamare server ke against chalaya: healthz, metadata, 10/10 warmup pushes accepted, tick aur reply valid.

### Completion criteria
- [x] Saare endpoints exact schema par, 400/409/200 sahi.
- [x] Idempotent aur thread-safe.
- [x] Judge ka apna client kaam karta hai.
- [ ] `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL` **aapko `.env` mein bharna hai** (submission se pehle).

**Status: Step 2 COMPLETE** (metadata ke personal fields aapke input par pending).

---

## 6. Step 3

### Objective
`compose(category, merchant, trigger, customer?)` banana, jo challenge ka core hai (brief §5, §7.1). LLM: pehle Groq, fail hone par automatic OpenRouter.

### What we need to do
- Trigger kind ke hisaab se guidance, ek strongest signal, sirf context ke facts, sahi language aur voice.
- LLM failover jo "quickly" dusre provider par jaye.
- Deterministic output (temperature 0 + cache).

### Implementation
- `llm.py`: Groq (primary) aur OpenRouter (fallback), dono OpenAI-compatible chat endpoints. Error, timeout ya 429 par **turant** dusre provider par jata hai. Fail hua provider chhote cooldown par (429 par `retry-after`, 5xx par 20s, galat key/model par 300s). **Total time ek shared budget mein hai**: pehle provider ko bacha hua time ka max 60%, taaki slow Groq ke baad OpenRouter ko asli time mile. Keys sirf `.env` ya environment se aati hain, kabhi log nahi hoti. OpenRouter ke saath magicpin ka `HTTP-Referer` nahi bheja (impersonation rule R54).
- `prompts.py`: versioned `SYSTEM_PROMPT` (**ab 18 rules**, version `composer_v2`: grounding, ek signal, why-now, ek ask, voice/taboo, language, no filler/URL, names, offers, sources, who speaks, levers, placeholder triggers, time, length, originality, **conflicts, no internal jargon**) aur **26 trigger kinds ke liye guidance**. Case-study ke text ko example ki tarah prompt mein **nahi** daala (R40).
- `composer.py`:
  - `build_context()`: category (voice, peer stats, offers, seasonal, trends), merchant, trigger, customer. **Digest sirf tab** jab trigger digest-type ho, aur wahan bhi sirf wo ek item jo `top_item_id` / `digest_item_id` se resolve hota hai ("ek signal" rule).
  - `derive_facts()`: arithmetic **code mein**: CTR vs peer, views/calls vs peer, 7-day changes, lapsed share, `delta_pct -0.5` ko `-50%`, milestone ka remaining.
  - `language_spec()`: customer ho toh `language_pref`; merchant ho toh `languages` mein `hi` hone par category ka `voice.code_mix`.
  - `addressee()`: dentists ke liye "Dr. <owner_first_name>". Owner name na ho toh business ka naam as-is (audit fix: pehle "Dr. Dr. ..." ban sakta tha).
  - Cache key = poore inputs ka SHA-256, isliye naya context version aate hi fresh message (adaptation automatic).
  - `_normalize_cta()` (audit): `cta` label body se consistent rakhta hai (judge dono dekhta hai).
  - `send_as`, `suppression_key` trigger se.
- `bot.py` mein `from composer import compose` (brief §7.1).

### Files/changes
`llm.py`, `prompts.py`, `composer.py`, `tests/verify_step3_composer.py`, `tests/live_compose_30_pairs.py` (purani, ab `live_audit_30_pairs.py` isse aage hai).
**Optional helpers:** `python llm.py --check` (keys aur model names test), `python llm.py --models groq`.

### Verification (asli result)
`python tests/verify_step3_composer.py`: **38 checks PASS** (offline, LLM mocked): 30 pairs ke prompt (sabse bada ~10.3k chars), digest resolve, derived facts, no case-study wording, `compose()` 5 fields, determinism (1 LLM call), cache invalidation, failover (Groq 429/timeout par OpenRouter, cooldown, dono fail par `LLMUnavailable`, non-JSON par retry) aur **shared time budget** (do slow providers = total timeout, 2x nahi).

**Live LLM verification: PENDING** (keys nahi hain).

**Status: Step 3 IMPLEMENTED + offline verified. Live verification pending.**

---

## 7. Step 4

### Objective
LLM ke output par guard lagana (material: "hallucinated facts, generic templates, unstable responses" reject; empty `send` = -2).

### Implementation
- `validator.py`. **Hard** (bhejne layak nahi): URL (examples F.4, -3), category `vocab_taboo`, **ungrounded numbers**, multiple asks, reference message ki copy, pichhle message ka repeat, bahut chhota body, **internal jargon** (snake_case field names, `payload`, `placeholder`...: judge_simulator.py:477, -1). **Soft** (retry, phir bhi rahe toh rakhte hain): CTA ask antim 3 sentences mein nahi (audit mein relax kiya), language mismatch, preamble, bahut lamba.
  - Number grounding: context ka har number (IDs hata ke), fractions percentage mein (`0.5` to `50`). Chhote counts (12 tak), clock/date ke ank, "10 minutes / 90 seconds" jaise effort durations ki chhoot.
  - **Copy guard (audit mein badla):** word-order ratio >= **0.65** (pehle 0.55) **ya** 6-gram containment >= **35%**. Wajah: jin pairs ke facts case study jaise hi hain (T28 slots/price/naam), unka ratio bina copy kiye ~0.47 tak jaata hai; asli plagiarism verbatim runs se pakda jata hai.
- `references.py`: case-study aur example bodies, **sirf similarity guard ke liye** (LLM ko kabhi nahi bheje).
- `fallback.py`: 26 kinds ke liye deterministic message (English/Hinglish), sirf payload aur merchant/customer data se. Audit mein `kind`, `slug`, `ask_template` galat type hone par bhi crash nahi karta.
- `composer.compose_detailed()`: LLM draft, validate, hard issue par ek retry (feedback ke saath), phir best valid draft ya fallback. Total LLM budget 7s. LLM outage ka result cache nahi hota.

### Verification (asli result)
`python tests/verify_step4_validator.py`: **42 checks PASS**: har rule ka bad-example test, similarity guard (verbatim, near-copy pakde; honest paraphrase nahi), **fallback saare 100 triggers par hard-rule-clean** (jargon ke saath), retry/fallback/budget/outage flow.

**Status: Step 4 COMPLETE (offline).** Invented **names** validator nahi pakadta (prompt + live-audit heuristic par nirbhar; guard matrix mein explain).

---

## 8. Step 5

### Objective
`/v1/reply`: auto-reply, intent-to-action, hostile, off-topic, wait, end.

### Implementation (`replies.py`), decision order aur source
1. Conversation pehle se `end`: kuch nahi (Example 2.6).
2. Explicit opt-out ("stop messaging me"): `end`. **Sirf woh conversation** (Example 2.6). Agar message **hostile bhi** ho: merchant proactive sends se suppress (Example 4.3: "Suppressing all triggers for this merchant for 30 days").
3. Plain decline ("no thanks"): `end`.
4. Sirf abuse: ek calm reply, doosri baar `end` (+ suppress).
5. **Auto-reply:** pehli baar chhota `send`, doosri baar `wait` 86400, teesri baar `end` (Example 4.1). Count **merchant level** par (simulator har turn conversation_id badalta hai). Exit **conversation-level** hai: merchant ke doosre triggers rukte nahi.
6. Customer ne offered slot chuna: booking confirmation.
7. **Commitment** ("let's do it", "yes", "mujhe judna hai"): ACTION reply, koi qualifying sawal nahi. "Yes, but what does it cost?" jaise **sawal wale** messages ab commitment nahi maane jaate (audit fix).
8. Off-topic (GST, tax, loan): polite decline + wapas topic par (Example 2.7).
9. "busy / later / kal": `wait` (1800 ya 86400). Ye bhi sirf us conversation ke liye, merchant-wide gate nahi.
10. Baaki: LLM answer.

### Verification (asli result)
`python tests/verify_step5_replies.py`: **43 checks PASS**, jisme judge simulator ke apne teeno scenarios (auto-reply, intent, hostile) live server par, ek hi merchant par ek ke baad ek.

**Status: Step 5 IMPLEMENTED + offline verified. Live LLM reply quality pending.**

---

## 9. Step 6

### Objective
`/v1/tick`: kaunse proactive messages abhi jaayein, aur naya context sahi use ho.

### Implementation (`tick.py`), source ke saath
- Sirf `available_triggers` (testing brief:82). Trigger ya `(merchant, customer, suppression_key)` dobara nahi (brief:125). Missing merchant/category/customer par skip, kuch invent nahi (testing brief:302).
- **Max 20 actions**, urgency desc (testing brief:333; engagement-design:93).
- **Ek merchant ke kai triggers ek hi tick mein**, har ek apne conversation mein. FAQ (testing brief:536) sirf "ek (merchant_id, conversation_id) pair ka ek action" rokta hai. *(Audit fix: pehle hum "ek merchant ka ek action per tick" karte the, jo spec se zyada strict tha.)*
- **Kaunse merchant/customer skip hote hain:** sirf **hostile merchant** (Example 4.3) aur wo **customer jisne STOP kaha**. *(Audit fix: "3 unanswered nudges" aur "wait ke dauran" wale tick-gates hata diye: brief:432-437 conversation ke andar follow-ups ke baare mein hai, aur bot silence par follow-up bhejta hi nahi, toh wo rule construction se poora hota hai.)*
- `expires_at` par filter **nahi**: judge ka `available_triggers` pehle se "active right now" (testing brief:82) aur simulator asli UTC clock bhejta hai (judge_simulator.py:424-427).
- Parallel compose (6 workers), tick budget 8s. Jo draft budget mein nahi bana wo background mein cache mein jata hai.
- Naye context ke liye alag code nahi: `compose()` latest version padhta hai, cache key poore context ka hash.

### Verification (asli result)
`python tests/verify_step6_tick.py`: **60 checks PASS**:
- 30 canonical triggers: pehle tick mein 20 (cap), doosre mein baaki 10, teesre mein 0; **saare 30 pairs ko message, koi repeat nahi**. Dr. Meera aur Mylari ke 3–4 triggers sab gaye.
- Odd input, missing context, unknown kind, hostile merchant, opted-out customer, same key dedupe, category-level shared key (do merchants, dono ko message).
- Adaptation: naya digest item, updated performance (aur cache invalidate), mid-test naya customer, bilkul naya merchant.
- Time budget: slow LLM par tick budget par 6 actions, baaki 2 background se agle tick mein 0.00s mein.
- **Simulator-style run** (seed data, real clock, 5-5 ke batch, har trigger sirf ek baar listed): **har merchant-scope trigger ko message mila**.

**Status: Step 6 IMPLEMENTED + offline verified. Live LLM latency/quality pending.**

---

## 10. Requirements Traceability Matrix

Status: **VERIFIED** = offline tests se prove. **PENDING-LIVE** = implement hai, asli LLM output/latency keys ke baad. **LATER** = Steps 7+. **YOU** = aapka manual kaam.

| ID | Requirement | Step | Implementation | Verification | Status |
|---|---|---|---|---|---|
| R01 | Public URL, saare endpoints | 8 | Deploy | Public URL par simulator | LATER |
| R02 | Submit ke baad live | 8/11 | Always-on host | Manual | LATER |
| R03 | Portal par submit | 11 | Aap | n/a | YOU |
| R04 | README 1 page | 10 | Draft | Aap review | LATER |
| R05 | `submission.jsonl` 30 lines | 10 | `out/live_audit_30_pairs.jsonl` isi pairs ka output | Step 10 | LATER |
| R06 | `bot.py` mein `compose()` | 3 | re-export | verify_step3/6 | VERIFIED |
| R07 | `conversation_handlers.py` (optional) | 5 | Nahi banaya | n/a | SKIPPED |
| R10 | `/v1/context` semantics | 2 | `bot.py`, `store.py` | verify_step2 + audit_contract_replay (Examples 1.3-1.7) | VERIFIED |
| R11 | 500 KB payload | 2 | Koi limit nahi | ~480 KB accepted | VERIFIED |
| R12 | `/v1/healthz` counts | 2 | `store.counts()` | 5/50/200/0 | VERIFIED |
| R13 | `/v1/metadata` | 2 | `.env` se | 7 fields exact | PARTIAL: 4 fields `TO_BE_SET` (YOU) |
| R14 | Tick shape, 11 fields | 6 | `tick.py` | verify_step6 + audit (exact key set) | VERIFIED |
| R15 | Cap 20; ek (merchant, conversation) ka ek action; unique conv id | 6 | `_select`, `conv_<trigger_id>` | verify_step6 (20/10/0), audit | VERIFIED |
| R16 | `/v1/reply` send/wait/end | 5 | `replies.py` | exact key sets, 11 scenarios x 2 modes | VERIFIED |
| R17 | Latency (30s hard, 10s table) | 2/5/6 | tick 8s, compose 6s, reply 6.5s | mocked slow LLM; no-LLM server calls <70 ms | VERIFIED offline; PENDING-LIVE |
| R18 | Stateful in-memory | 2 | `Store` | tests | VERIFIED (restart par state jaata hai) |
| R19 | `/v1/teardown` | 2 | `bot.py` | wipes all | VERIFIED |
| R20 | 10 req/s | 2/6/9 | thread-safe, 100 worker threads | store concurrency | LATER (Step 9) |
| R21 | `compose()` 5 fields | 3 | `composer.compose` | verify_step3 | VERIFIED |
| R22 | Deterministic | 3 | temp 0, seed, cache | cache test; live probe in live_audit | VERIFIED offline; PENDING-LIVE |
| R23 | Fabrication nahi | 3/4 | prompt rules 1, 13, 17; numbers guard; grounded fallback | 360-run fuzz, crafted cases, 100 fallbacks | VERIFIED (numbers); names/offer titles PENDING-LIVE |
| R24-R30 | Specificity, category/merchant fit, why-now, decision quality, engagement | 3 | prompt + per-kind guidance + derived facts | prompt content audit (7 dimension checks, 30 pairs) | VERIFIED (structure); PENDING-LIVE (quality) |
| R25 | Taboo words | 4 | hard guard | bad/good tests | VERIFIED |
| R27 | Language | 3/4/5 | `language_spec`, validator, `reply_language` | modes, mismatch detect | VERIFIED (mode); PENDING-LIVE |
| R31 | Ek CTA | 3/4 | rule 4, guards, cta normalize | unit + 14 good messages clean | VERIFIED |
| R32 | `send_as` | 3 | `build_context` | 9 customer pairs | VERIFIED |
| R33 | Template name/params | 6 | `_template` | naming test | VERIFIED |
| R34 | Koi URL nahi | 4 | hard guard | unit + simulator-style run | VERIFIED |
| R35 | No preamble | 3/4 | soft guard | unit | VERIFIED |
| R36 | Anti-repetition | 4/5/6 | validator + reply variants + sent-sets | unit + flows | VERIFIED |
| R37 | Suppression key | 6 | `sent_keys` scoped `(merchant, customer, key)` | re-tick, shared key | VERIFIED |
| R38 | Rationale | 3 | LLM rationale (default agar khaali) | present in all | VERIFIED (present); PENDING-LIVE (matches) |
| R39 | Customer-facing real slots | 3/6 | prompt + fallback slot labels | Example 2.9 replay | VERIFIED (structure); PENDING-LIVE |
| R40 | Case-study copy nahi | 3/4 | guard 0.65/35% + no examples in prompt | 14 good messages worst ratio 0.455, containment 0.02 | VERIFIED |
| R41 | Auto-reply | 5 | classify + merchant-level count | Example 4.1 replay, simulator | VERIFIED |
| R42 | Intent transition | 5 | ACTION mode | Example 4.2 replay, simulator | VERIFIED |
| R43 | Hostile/off-topic | 5 | opt-out/calm/decline | Examples 2.6, 2.7, 4.3 replay | VERIFIED |
| R44 | Kab rukna hai | 5/6 | decline, auto-reply exit, hostile; koi silence follow-up nahi | flows | VERIFIED |
| R45 | Language per turn | 5 | `reply_language` | mode tests | VERIFIED (mode); PENDING-LIVE |
| R46 | `wait` | 5 | WAIT_RE, 1800/86400 | flows | VERIFIED |
| R47 | `end` ke baad silence | 5 | `conv["ended"]` | flows | VERIFIED |
| R48 | Naya context use | 6 | latest version + hash key | digest/perf/customer/merchant tests | VERIFIED |
| R49 | Restraint | 6 | skips (missing ctx, dupes, hostile) | tests | VERIFIED |
| R50 | Koi bhi context kabhi bhi | 2/6 | store, tick | mid-test tests | VERIFIED |
| R51 | Kabhi malformed nahi | 2/5/6 | exception wrappers, fallback | fuzz + shape checks | VERIFIED |
| R52 | Payload sirf LLM ko | all | sirf `llm.py` bahar call karta hai | code grep | VERIFIED |
| R53 | Test ke baad persist nahi | 2 | teardown | test | VERIFIED |
| R54 | Scrape/impersonation nahi | all | sirf diya hua dataset | review | VERIFIED |
| R55 | Internal jargon nahi (simulator -1) | 4 | hard guard + prompt rule 18 | unit + 100 fallbacks | VERIFIED |

### Final cross-check
- Steps 1–6 ke scope ke saare mandatory items VERIFIED (offline) hain.
- Jo asli LLM par depend karte hain (R17, R22, R23 names, R24-R30, R38, R39, R45) implement hain aur structure verify hua, par **live verification PENDING**.
- Steps 7+ ke items: R01, R02, R04, R05, R20. Aapke: R03, R13 ke personal fields.
- **Koi requirement missed nahi mila.**

---

## 11. Verification Checklist

**Ek command se poori offline suite (8 scripts):**
```
python tests/run_all.py
```
Abhi result: **ALL STEPS PASS: 359 checks** (Step 1: 12, Step 2: 33, Step 3: 38, Step 4: 42, Step 5: 43, Step 6: 60, Audit endpoint contract: 49, Audit context/guards/replies/tick: 82).

**Live verification (keys ke baad)** ka exact procedure: neeche "Final Audit Before Step 7" mein.

---

## 12. Mistakes / Risks to Avoid

1. **Live output abhi dekha nahi.** Prompt aur validator offline tested hain, par asli LLM ka quality aur hallucination rate keys ke baad hi pata chalega.
2. **Model names stale ho sakte hain** (defaults verify nahi hue). `python llm.py --check`.
3. **Free-tier rate limits.** Dono providers 429 dein toh bot deterministic fallback par aata hai (safe, par plain).
4. **Validator sirf numbers ground karta hai.** Invented **naam** aur non-numeric claims prompt par nirbhar hain (live audit ki heuristics + aapka padhna).
5. **Regional language** (`ta/te/kn/mr` preference) plain English jaati hai.
6. **Similarity aur Hindi-marker heuristics** live outputs par dekhni hain.
7. **State in-memory hai:** process restart ya sleeping host par contexts chale jaate hain. Hosting mein **ek hi worker/process** aur always-on zaroori (multiple workers ka state alag hoga).
8. **Metadata placeholders (`TO_BE_SET`)** submit se pehle bharne hain.
9. **`expires_at` jaan-bujhkar ignore.**
10. **Simulator par overfit mat karo.** FAQ: "Your score depends on how your bot handles [fresh scenarios], not on how it does on the 30 pairs."
11. **Case-study ke invented numbers** (jaise "Saturday IPL -12% covers") data mein nahi hain; hum wo kabhi nahi likhte.
12. **Kya NA karein:** `.env`/keys commit ya chat mein; case-study text copy; `expires_at` filter wapas; merchant-wide suppression ko plain opt-out/auto-reply/wait par lagana; tick mein "ek merchant ka ek action" wapas lagana; patch scripts mein backslash (`\\b` jaise regex) bina dhyaan ke.

### Scope check
- **Material se required:** endpoints, composer, validator, fallback, reply engine, tick rules.
- **Optional/helper:** `llm.py --check/--models`, live audit scripts, `run_all.py`, customer slot booking, `lifespan` thread limit, `_normalize_cta`.
- **Jaan-bujhkar skip:** `conversation_handlers.py`, disk persistence, consent-based blocking (186/200 customers ka consent sirf `promotional_offers` hai, aur material mein rule nahi).

---

## 13. Step 1–6 Completion Status

| Step | Implemented | Offline-verified | Live-verified (real LLM) |
|---|---|---|---|
| 1 Dataset samajhna | Yes | Yes (12) | n/a |
| 2 Endpoints | Yes | Yes (33 + contract audit 49) | n/a |
| 3 Composer | Yes | Yes (38) | **Pending (keys)** |
| 4 Validator + fallback | Yes | Yes (42) | **Pending (keys)** |
| 5 Reply engine | Yes | Yes (43 + audit scenarios) | **Pending (keys)** |
| 6 Tick policy | Yes | Yes (60 + audit) | **Pending (keys)** |
| Final audit | Done 2026-09-27 | Yes (131 audit checks) | live audit prepared, not run |

**Step 6 ke baad aage badhne se pehle ye sach hona chahiye:**
- [x] `python tests/run_all.py`: ALL STEPS PASS (359).
- [ ] `.env` mein dono keys, `python llm.py --check` OK.
- [ ] `python tests/live_audit_30_pairs.py` chalaya, `out/live_audit_report.md` aur 30 messages khud padhe.
- [ ] `.env` mein `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL` bhare.

---

## 14. What Remains for Later Steps

- **Step 7:** `judge_simulator.py` ka LLM config (aapki key), `TEST_SCENARIO = "full_evaluation"` (default `"all"` messages score nahi karta).
- **Step 8:** Public URL par deploy: always-on, **ek worker**, `.env` variables host par, `/v1/metadata` ke sahi values.
- **Step 9:** 10 req/s stress test, restart ke baad state, LLM quota.
- **Step 10:** README (1 page), `submission.jsonl` (30 lines), optional `conversation_handlers.py` ka decision.
- **Step 11:** Portal par submit (aap), bot live rakhna, evaluation ke dauran redeploy nahi.
- **Deadline:** aapne "kal 3pm" bataya (ab: aaj 2026-09-27 15:00). Official material mein **Not specified**.

---

## Final Audit Before Step 7

**Audit date:** 2026-09-27 (IST). **Scope:** Steps 1–6 ko challenge pack ke saamne dobara check kiya: 5 docs (line numbers ke saath), `examples/`, `judge_simulator.py`, `generate_dataset.py`, aur website ke 6 screenshots (chhote text zoom karke). Pichhli summary ko sach nahi maana; jahan wo galat ya adhoori thi wahan sudhaara.

**Kya chalaya:** `tests/audit_contract_replay.py` (HTTP contract + `api-call-examples.md` ke Examples 1.1–4.3 ka replay: 49 PASS, 3 AMBIGUOUS, 0 FAIL), `tests/audit_context_and_guards.py` (82 checks: context/fuzz, prompt alignment, guard matrix, replies, tick), aur poori suite (359 checks).

### 1. Verified requirements (audit ne re-check kiye)
- **Endpoints:** GET/POST methods (405 wrong method par), exact request/response key sets, status codes 200/400/409, ack_id aur `stored_at` (ms + Z) format, healthz counts 0 phir 5/50/200/0, metadata 7 fields, tick ke 11 fields (exact set), reply ke teeno action shapes (exact keys), teardown, timeouts (healthz/metadata <2s, context <5s, tick/reply <10s), healthz x3 retry, state persistence, UTF-8 (₹, emoji, Devanagari) + ~480 KB payload.
- **Examples ka replay:** 1.1–1.7, 2.1–2.9, 4.1 (send, wait 86400, end, end), 4.2, 4.3, F.2 (6 required fields), F.4 (no URL).
- **Context:** 100 prompts mein doosre merchant/customer ka koi id nahi; 13 placeholder pairs grounded; **360-run fuzz** (fields delete/null/empty) mein koi exception nahi aur har run mein non-empty message; tick over mutated contexts mein koi exception nahi; unknown trigger ids, missing customer, missing category skip; fresh digest injection prompt tak pahunchta hai.
- **Composer:** prompt 7 cheezon ko cover karta hai (5 dimensions + 2 penalties: fabricated -2, jargon -1); 30 pairs ke prompts mein owner name, kind, language, derived facts.
- **Guards:** 14 hand-written **good** messages (asli data se) par **0 hard aur 0 soft** issue, worst case-study similarity ratio 0.455 / containment 0.02.
- **Replies:** 11 scenarios x (LLM mocked, LLM absent): normal, acceptance, Hinglish acceptance, rejection, intent, hostile (stop), hostile (abuse only), off-topic, wait 1800/86400, empty, auto-reply x4, end, customer (slot/question/stop): sab `send`/`wait`/`end` ke exact shape mein.
- **Tick:** 20 cap, urgency order, repeated ticks, **saare 30 canonical pairs ko message**, 13 placeholder pairs, expired triggers bhejte hain, deterministic.

### 2. Critical discrepancy table

| Requirement | Source | Current Implementation | Status | Required Fix |
|---|---|---|---|---|
| Same-version `/v1/context` | testing brief:51 ("no-op"), :60-62 (409 "higher version"), :399-400 (skeleton `>=`); Example 1.5 (api-call-examples.md:124-131) same version to 409 `{"accepted":false,"reason":"stale_version","current_version":1}`; website: "Re-posting the same version is a no-op." | `store.put_context`: `version <= current` par 409 exact body, state unchanged; higher version replace | **MATCHES** the only exact example; text vs example wording conflict documented (C4) | None |
| Tick/reply latency | Hard 30 s: testing brief:148, 331, 337, 476-477, 500-501; brief:278; website "Max response timeout: 30 seconds". Soft table: api-call-examples.md:607-613 (tick/reply 10 s, context 5 s, healthz/metadata 2 s). Simulator: 15 s tick/reply (judge_simulator.py:424-434) | tick budget 8 s, compose 6 s, reply 6.5 s, shared LLM deadline across providers | **OK for both** (measured no-LLM: healthz 18 ms, tick <70 ms) | Live latency measure (live audit check 13) |
| `expires_at` semantics | brief:126, engagement-design:95 ("after which the trigger is stale"), testing brief:82 (`available_triggers` = "active right now"), :257; simulator sends `datetime.utcnow()` (judge_simulator.py:424-427) vs dataset expiries 2026-04-26 to 2026-12-15 (placeholders 2026-06-30) | No filter by `expires_at` | **OK**: koi source bot ko filter karne ko nahi kehta; filter lagate toh simulator ke saath 0 messages | None |
| URL penalty/rule | brief:219 ("allowed when they add clear value"); website FAQ "links only when they add real value"; api-call-examples.md:564-570 (F.4 hard fail, -3 per URL); dataset mein koi URL nahi | Kabhi URL nahi (hard guard + prompt) | **OK** (strictest reading, zero cost) | None |
| Case-study similarity | examples/case-studies.md:336, 338 (judge similarity check; "wording must be your own") | Prompt mein koi example nahi; guard ratio 0.65 / 6-gram 35% | **OK, threshold FIXED** (0.55 se 0.65) | Done |
| Placeholder triggers | Sirf dataset/generate_dataset.py:225-240 ("5 of each kind"); kisi brief/example mein handling nahi | Kind + merchant/customer/category facts, koi invented detail nahi (13/30 pairs) | **Not specified in the provided material** | None (risk noted) |
| Exact five judging dimensions | brief:311-317: Specificity, Category fit, Merchant fit, **Trigger relevance**, Engagement compulsion. Website: **Decision quality**, Specificity, Category fit, Merchant fit, Engagement compulsion. Simulator: prompt-text "TRIGGER RELEVANCE" (:465) par key `decision_quality` (:126, :487) | Prompt rules 2-3: ek best signal + saaf why-now (dono ko satisfy) | **Meri pehli summary adhoori thi** (simulator ka prompt bhi Trigger relevance kehta hai) | Doc corrected (C2); code change nahi |
| Metadata required fields | testing brief:159-172; api-call-examples.md:34-53; simulator sirf `team_name`, `model` print karta hai (:638) | 7 fields, values `.env` se | Schema **OK**; 4 values `TO_BE_SET` | **YOU:** `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL`, `SUBMITTED_AT` |
| Submission requirements | brief:265-297 (bot.py, `submission.jsonl` 30 lines, README <=1 page, optional handlers), :481; testing brief:350, 504; website: "Submit one public base URL", README "can explain approach, model choice, and tradeoffs", "Share your details and keep your bot live" | `bot.py` + `compose()` done | **PENDING** (Steps 8/10/11) | Later steps |
| Tick action limit | testing brief:333 (20 per tick), :536 (one per (merchant_id, conversation_id)); website "Tick cap 20 actions per tick" | 20 cap. **Pehle** ek merchant ka ek action per tick bhi lagta tha | **FIXED:** extra rule spec se zyada strict tha | Done |
| Public URL requirements | testing brief:343-350, 497; website "Submit one public base URL", "The submitted public URL must expose all required endpoints" | Abhi deploy nahi | **PENDING** (Step 8) | Deploy: always-on, ek worker |

### 3. Discrepancies found aur fixes (sab material se backed)
1. **Tick "ek merchant ka ek action per tick"** spec se zyada strict (FAQ testing brief:536) aur canonical pairs ko daba sakta tha (brief:261). **Hataya.** Simulator-style run mein ab har merchant-scope trigger ko message milta hai.
2. **Tick "3 unanswered nudges / wait" gates**: brief:432-437 conversation ke follow-ups ke baare mein hai; bot silence par follow-up bhejta hi nahi. **Hataye.** (Mylari ka 4th trigger pehle roka jaata tha.)
3. **Opt-out scope**: Example 2.6 conversation-level, Example 4.3 merchant-level (hostile). **Sudhaara:** plain opt-out = conversation; opt-out + hostile = merchant suppress. Auto-reply exit aur `wait` bhi conversation-level.
4. **Internal jargon** (judge_simulator.py:477, -1) ka koi guard nahi tha. **Jod diya** (hard guard + prompt rule 18).
5. **Copy-guard ratio** 0.55 same-fact messages (T28 ~0.47) ke liye tight tha. **0.65** kiya (verbatim runs 35% wahi rakhe).
6. **CTA-placement soft rule** "ask first, payoff last" (case study 4, 44/50) ko galat flag karta tha. **Antim 3 sentences** tak relax kiya.
7. **"Yes, but what does it cost?"** commitment maana jaata tha. **Sawal wale accept** ab normal reply.
8. **Robustness:** `addressee()` bina owner name "Dr. Dr. ..." bana sakta tha; galat type (`kind`, `slug`, `ask_template`) par TypeError. **Dono theek.**
9. **`cta` label body se mismatch** ho sakta tha (judge dono dekhta hai). `_normalize_cta` jod diya.
10. **Meri pehli summary**: dimension-4 ke baare mein adhoori. Doc mein corrected.
11. **Tool-layer bug (mera process):** patch scripts mein `\\b` regex ka backspace character ban gaya (2 jagah). Pakda, theek kiya, aur ab control-byte scan bhi kiya.

### 4. Guard classification (Section 4 of the audit)

| Guard | Classification | Source | Bad example | Good example | Note |
|---|---|---|---|---|---|
| URL / web address | REQUIRED | examples F.4 (-3) | caught | passes | Data mein koi URL nahi |
| Category taboo words | STRONGLY RECOMMENDED | brief:220-221; simulator:509 | caught | passes | |
| Fabricated numbers | REQUIRED | brief:224; case-studies:316; simulator:475 (-2) | caught | passes | Arithmetic code mein hota hai |
| Fabricated names | STRONGLY RECOMMENDED (**gated nahi**) | simulator:475 | n/a | n/a | Name check achhe messages ko galat reject karta (log, platforms). Prompt + live-audit heuristic + aapka padhna |
| Fabricated offers | STRONGLY RECOMMENDED (**aanshik**) | brief:224 | caught (unknown ₹ amount) | passes | Offer *titles* prompt par nirbhar |
| Multiple asks | STRONGLY RECOMMENDED | brief:220-222; website "one clear CTA" | caught | passes | 3+ sawal ya 3+ "reply"; slot list allowed |
| Buried CTA (soft) | OPTIONAL | brief:423 | caught | passes | Audit mein relax |
| Language mismatch (soft) | STRONGLY RECOMMENDED | brief:225, 427 | caught | passes | |
| Preamble (soft) | OPTIONAL | brief:424-425 | caught | passes | |
| Repeat of previous message | REQUIRED | testing brief:480; F.5 (-2) | caught | passes | |
| Case-study copy | REQUIRED | case-studies:336, 338 | caught | passes | 14 good messages worst 0.455 |
| Internal jargon | STRONGLY RECOMMENDED | simulator:477 (-1) | caught | passes | Audit mein naya |
| Empty / too short | REQUIRED | testing brief:479 (-2) | caught | passes | |
| Too long (soft) | **UNNECESSARY** (soft rakha) | F.3 (no cap) | caught | passes | Sirf ek extra retry ka kharcha |
| Malformed LLM output, timeout, LLM failure, retry, fallback | REQUIRED | testing brief:470-481, 148 | tested | tested | non-JSON, JSON bina body, no provider, slow provider sab valid message par khatam |

### 5. Remaining risks
1. **Live LLM abhi test nahi hua** (sabse bada). Quality, hallucination rate, latency, invented names/offers.
2. **Model names** verify nahi hue.
3. **13/30 placeholder pairs**: LLM ko trigger ka detail nahi milta.
4. **Replay scenarios** (top 10 only): agar judge Phase 4 mein wahi trigger dobara list kare jo hum Phase 2 mein bhej chuke (Example 4.1 mein `trg_022_cde_webinar_dentists`, jo T06 bhi hai), toh dedupe ki wajah se tick khaali aayega. Judge ka exact behaviour material mein nahi hai; (`/v1/teardown` ya fresh instance par theek). Abhi koi fix nahi, sirf documented.
5. **Same-version** aur **pehli auto-reply** (Example 2.5 wait 14400 vs 4.1 send) source-level ambiguities: hum exact examples (1.5, 4.1) follow karte hain.
6. **Regional language** customers ko English.
7. **Hosting:** ek worker, always-on; state in-memory.
8. **10 req/s** stress test abhi baaki (Step 9).
9. FAQ: score "fresh scenarios" par depend karta hai, isliye 30 messages ka review sirf ek sample hai.

### 6. Live-test procedure (exact)
1. `.env.example` ko `.env` naam se copy karo. `GROQ_API_KEY`, `OPENROUTER_API_KEY` khud bharo (chat mein paste nahi). `TEAM_NAME`, `TEAM_MEMBERS`, `CONTACT_EMAIL` bhi.
2. `python llm.py --check`: dono "OK" chahiye. Fail par `python llm.py --models groq` (ya `openrouter`) se sahi model naam dekho, `.env` mein `GROQ_MODEL` / `OPENROUTER_MODEL` set karo, phir dobara `--check`.
3. `python tests/live_audit_30_pairs.py`: 30 asli messages, har ek par 14 checks, LLM-auditor ka doosra opinion, **failover drill** (Groq ki key jaan-bujhkar galat karke OpenRouter jawab de; dono galat karke fallback), aur determinism probe.
4. `out/live_audit_report.md` kholo: har `REVIEW` message padho; `source` `llm:groq` dikhna chahiye (fallback nahi). Saare 30 bodies khud padho.
5. Pass ka matlab: checks 1-12 mein koi real invented name/number/offer/urgency nahi, check 13 mein sab <= 8s, check 14 (drills) OK, `fallback` kam.
6. Tab hi `python tests/run_all.py` phir ek baar, aur Step 7 (simulator) par jao.
`out/live_audit_report.md` jo abhi maujood hai wo **bina keys ka plumbing run** hai (upar likha hai "NOT A LIVE RESULT").

### 7. Final Step 1–6 status
**GREEN — Steps 1–6 are ready for live validation** (upar ke fixes lagne ke baad; har issue material se backed aur tested). Live validation ke prerequisites (defects nahi): aapki API keys, `.env` mein team details, aur model names ka `llm.py --check`.

---

## OpenRouter Model Bake-off

> **Status:** sirf evidence. **Production configuration badli nahi gayi.** Sirf ek naya test script (`tests/bakeoff_openrouter_models.py`) aur uske outputs (`out/bakeoff/`) bane. Koi model "winner" nahi hai; final production choice evidence dekhne ke baad user karega.
> **Run:** 2026-09-27, ~04:18 IST. Full data: `out/bakeoff/bakeoff_report.md` (metrics + har call + har message), `bakeoff_raw.jsonl`, `bakeoff_summary.json`, `pricing.json`.

### Kyun kiya
Live audit (30 pairs, Groq -> OpenRouter Llama-3.3-70B) mein 0 messages Groq se bane, 29 OpenRouter se, latency p50 8.55 s / max 19.93 s, aur 21/30 messages English aaye jabki Hinglish chahiye tha (material: `challenge-testing-brief.md:541`, `challenge-brief.md:222`, `:425`). User ka decision: Groq band, OpenRouter primary, key limit $100. Candidate models ko ek jaisi shart par compare karna tha.

### Exact models aur IDs
`python llm.py --models openrouter` ne 458 IDs diye. Test hue (exact IDs, guess nahi):

| Model | Exact ID | Upstream provider (response se) | Listed price USD / 1M tokens (in / out) |
|---|---|---|---|
| Claude Haiku 4.5 | `anthropic/claude-haiku-4.5` | Amazon Bedrock | 1.0 / 5.0 |
| GPT-4.1 Mini | `openai/gpt-4.1-mini` | OpenAI | 0.4 / 1.6 |
| Gemini Flash Lite (current text model) | `google/gemini-3.5-flash-lite` | Google | 0.3 / 2.5 |

Catalog mein maujood par **test nahi hue:** `google/gemini-2.5-flash-lite`, `google/gemini-3.1-flash-lite`, `google/gemini-3.1-flash-lite-preview`. `:batch` variants async hain, real-time bot ke liye nahi liye.
Pricing source: OpenRouter ka apna public list (`GET /api/v1/models`, field `pricing`), run ke time fetch (2026-09-26T22:48:27Z). Kuch bhi yaad se nahi liya.

### Test pairs (8)
| Pair | Trigger kind | Kyun chuna |
|---|---|---|
| T01 | active_planning_intent (Mylari, restaurant) | Merchant ne pucha "what would it look like": fabrication ka trap. Data mein sirf "Weekday Lunch Thali @ ₹149" hai, delivery offer nahi |
| T07 | chronic_refill_due (customer, `hi` pref) | Customer-facing, Roman-Hindi |
| T09 | competitor_opened (Dr. Meera) | Real payload, dentist voice ("Dr." prefix) |
| T13 | customer_lapsed_hard (gym customer, `en`) | Customer-facing English, real offer |
| T19 | festival_upcoming (**placeholder**, gym) | Festival ka naam data mein nahi: invented-event trap |
| T24 | perf_dip (Dr. Bharat) | Derived numbers (50%, 4 vs 12, views -22%) |
| T29 | recall_due (**placeholder**, customer) | Slot data nahi: invented-availability trap |
| T30 | regulation_change (Dr. Meera) | Digest item, source citation |

### Methodology
- **Same** prompt (`composer.build_messages`, production), same request body (temperature 0, max_tokens 450, seed 7 = `llm._post`), same validator (`validator.validate`) aur same `tests/audit_lib.py` checks. Sirf model id alag.
- Calls seedhe OpenRouter par, `llm.chat()` ke bina: koi cooldown, retry ya fallback nahi. Yani **first draft** ka raw behaviour. (Production ka retry/fallback yahan nahi naapa gaya.)
- Rounds: **S1** aur **S2** = sequential (models har pair par interleave), **P** = ek parallel burst (8 pairs, 6 workers, tick jaisa). Har model ke 24 calls, total 72.
- Latency statistics **sirf HTTP 200 calls** par. Error replies (jaise 402) model latency nahi hain, alag report hue.
- Grounding: script ke heuristics (advisory) + **maine S1 ke saare 24 messages haath se padhe** (ek reviewer, native-speaker review nahi) aur data files se claims verify kiye. LLM-auditor use nahi hua (kisi ek candidate ko judge banana biased hota).
- Cost: listed price x measured tokens; account meter se cross-check.

### Critical finding: OpenRouter account par purchased credits = 0
- 72 mein se **21 calls HTTP 402** se fail hue (Haiku 8, GPT-4.1 Mini 6, Gemini 7): "This request would exceed your available credits given your current in-flight requests". Teeno models par, isliye ye model ki galti nahi.
- `GET /api/v1/credits`: `total_credits: 0`, `total_usage: 0.1233`. `GET /api/v1/key`: `is_free_tier: true`, `limit: 100` (ye **key ka spending cap** hai, balance nahi).
- 402 sequential round (sirf 1 request in-flight) mein bhi aaye, aur intermittent the (kuch calls ke baad phir chal gaye), yani parallel load ki wajah nahi.
- Asar: production mein bhi intermittent 402 aa sakte hain (fallback message jayega). **Blocker hai:** user ko OpenRouter dashboard mein credits check/add karne honge (payment assistant nahi kar sakta). API ka number hi yahan evidence hai; dashboard final source hai.
- Isi wajah se S2 aur P rounds adhoore hain: usable calls Haiku 16, GPT-4.1 Mini 18, Gemini 17 (of 24). **S1 round poora clean hai (24/24).** Parallel-burst latency sirf 3/5/4 samples par tiki hai, isliye tail-latency ka verdict incomplete hai.

### Results
**A. Balanced subset: S1 only (8 pairs, sequential, koi account error nahi)**

| Metric | Haiku 4.5 | GPT-4.1 Mini | Gemini 3.5 Flash Lite |
|---|---:|---:|---:|
| Latency avg / p50 / max (s) | 4.99 / 4.89 / 5.75 | 2.95 / 2.81 / 4.27 | 2.70 / 2.50 / 4.79 |
| Malformed / API errors | 0 / 0 | 0 / 0 | 0 / 0 |
| First draft hard-rejected by validator | 1/8 | 0/8 | 1/8 |
| Not Hinglish as instructed (validator soft flag, of 6 msgs needing Hindi mix) | 5 | 2 | 1 |
| Avg Hindi markers per message | 1.88 | 8.25 | 5.5 |
| Ungrounded numbers (guard) | 1/8 | 0/8 | 1/8 |
| Clear invented content (manual, of 8) | 2 (T01, T19) | 2 (T01, T29) | 3 (T01, T19, T24) |
| Borderline claims (manual, of 8) | 3 (T07, T13, T24) | 2 (T09, T24) | 1 (T09) |
| Messages with 2+ question marks | 1/8 | 1/8 | 0/8 |
| Raw ISO dates in body (2026-04-01 style) | 1/8 | 2/8 | 3/8 |
| URL / taboo | 0 / 0 | 0 / 0 | 0 / 0 |
| Case-study similarity max ratio (containment, rejected) | 0.234 (0.0, 0) | 0.273 (0.0, 0) | 0.301 (0.0, 0) |
| Avg words | 48 | 52 | 41 |

**B. Saare rounds (sirf HTTP 200 calls; n = 16 / 18 / 17)**

| Metric | Haiku 4.5 | GPT-4.1 Mini | Gemini 3.5 Flash Lite |
|---|---:|---:|---:|
| Latency avg / p50 / p95 / max (s) | 6.15 / 5.77 / 9.70 / 9.70 | 4.14 / 4.10 / 6.87 / 6.87 | 3.91 / 4.25 / 6.06 / 6.06 |
| Sequential avg / max (n=13 each) | 5.52 / 6.86 | 3.46 / 4.96 | 3.32 / 4.79 |
| Parallel burst avg / max (n = 3 / 5 / 4) | 8.88 / 9.70 | 5.91 / 6.87 | 5.84 / 6.06 |
| Successful calls over 6 s (production compose budget) / over 10 s | 7 / 0 | 3 / 0 | 1 / 0 |
| Client timeouts (45 s) / 429 | 0 / 0 | 0 / 0 | 0 / 0 |
| HTTP 402 (account credits, not a model failure) | 8 | 6 | 7 |
| Same body on repeat (S1 vs S2, temperature 0) | 5/5 | 0/5 | 5/5 |
| Reasoning tokens | 0 | 0 | 0 |

### Raw observations per pair (S1, manual review, data se verify)
| Pair | Haiku 4.5 | GPT-4.1 Mini | Gemini 3.5 Flash Lite |
|---|---|---|---|
| T01 | English. Invented: 10% discount, 20+ thalis, ₹3000 min, free delivery above ₹3000, menu items. Guard ne sirf ₹3000 pakda | English. Invented: min 20 plates, menu items, "delivery and setup at office locations". Guard ne kuch nahi pakda | Hinglish. Invented: "min 10 packs", "Free Delivery (> ₹500)" (data mein delivery offer hai hi nahi), on-time delivery promise. Guard ne kuch nahi pakda |
| T07 | Theek, Roman-Hindi ("refill ready hai" halka claim) | Theek, natural, sender ka naam nahi | Theek, date "28-04-2026" robotic |
| T09 | English, "Doc" salutation, 18 calls data se match | Natural Hinglish; "Lajpat Nagar" merchant ki locality hai, par sentence competitor ki location jaisa padhta hai | Awkward code-switch, ask dhundhla ("patient patience review") |
| T13 | Theek; "weekday evening slot ready" halka availability claim | Theek, seedha | Theek, concise, merchant ka naam |
| T19 (placeholder) | **"Diwali" invent kiya** (data mein naam nahi) | Safe: festival ka naam nahi liya | **"in 14 days" invent kiya** (guard ne pakda) |
| T24 | English, "Doc", 2 sawal, "views aa rahe hain par convert nahi" data ke khilaf (views -22%) | Natural Hinglish, numbers sahi (50%, 4 vs 12, -22%) | "direct calling button" invented feature, jargon ("calls metric", "7d") |
| T29 (placeholder) | Safe par generic (merchant ka naam nahi) | **Slots invent kiye** (Morning/Afternoon/Evening) | Safe, koi slot list nahi; raw ISO date |
| T30 | Facts sahi (1.5 -> 1.0 mSv, E-speed/RVG), English, "Doc" | Facts + source sahi, natural Hinglish, lamba (~75 words) | Facts sahi, English |

### Failure analysis (jahan evidence hai)
- **402:** upar (account credits = 0, free tier). Model se related nahi.
- **Guard ne pakde:** Haiku T01 (₹3000), Gemini T19 (14). Production mein ye retry trigger karte.
- **Guard ne NAHI pakde (teeno models mein):** T01 ke invented package terms, GPT ke T29 slots, Gemini ke T24 feature, Haiku ka T19 "Diwali". Yani ye prompt/guard-level gaps hain, sirf model badalne se nahi jayenge.
- **Haiku ki slowness:** upstream Amazon Bedrock dikha; kisi provider-routing test se cause verify nahi hua. Parallel burst mein avg 8.88 s, production compose budget (6 s) se upar.
- **GPT-4.1 Mini repeatability:** temperature 0 par bhi 0/5 same. Production cache same process mein isse chhupata hai, restart ke baad nahi.
- **Language:** Haiku ne Hinglish-mode ke 6 mein se 5 messages English mein diye; validator ka retry yahan measure nahi hua (bake-off first draft hi naapta hai).

### Cost
- Listed price x measured tokens (avg ~2.6-2.9k input, ~0.15-0.2k output per call): Haiku ~$0.0040 / call, GPT-4.1 Mini ~$0.0013, Gemini ~$0.0012. Arithmetic se per 1,000 calls: ~$3.96 / ~$1.28 / ~$1.22.
- Is bake-off ki computed cost: $0.0634 / $0.0229 / $0.0207 = $0.1070. Account meter ka delta (settle hone ke baad): $0.1005, yani computed se ~6% kam. Pricing verified, par upstream provider ka asli rate alag ho sakta hai.
- Budget: key limit $100 hai par purchased credits 0 (upar dekho).

### Unresolved issues
1. **OpenRouter credits 0 / free tier**: production blocker jab tak user credits add na kare.
2. S2 aur P rounds adhoore (402); tail latency under burst ka pura data nahi. Credits theek hone par missing cells re-run karne honge (script `--regen` se report bina paid calls ke dobara ban jati hai).
3. T01 (draft mein invented terms), T29 (invented slots), T19 (invented festival naam/timing) ke liye prompt/guard fixes baaki hain; teeno models fail hue.
4. Raw ISO dates ("2026-04-01") robotic hain; natural date formatting baaki.
5. Sample chhota hai (8 pairs, S1 mein 8 messages/model); Hinglish naturalness ek reviewer ne judge kiya, native-speaker review nahi.
6. Production ke retry/fallback ke saath end-to-end quality nahi naapi gayi.

### Production configuration options (koi final pick nahi)
| Option | Kya dikhta hai (evidence) | Trade-off |
|---|---|---|
| **A:** GPT-4.1 Mini primary -> Gemini 3.5 Flash Lite fallback | Hinglish sabse zyada follow (avg 8.25 markers, 2 flags), sequential avg 2.95 s, ~$0.0013/call, "Dr." salutation sahi | T29 mein slots invent kiye; repeat par same output nahi (0/5); 2/8 ISO dates |
| **B:** Gemini 3.5 Flash Lite primary -> GPT-4.1 Mini fallback | Sabse tez aur sasta (2.70 s, ~$0.0012), sabse chhota message (41 words), repeat 5/5, Hinglish flag 1/8 | S1 mein 3 clear invented claims (T01, T19 "14 days", T24 feature); code-switching kabhi awkward; 3/8 ISO dates |
| **C:** Haiku 4.5 kisi bhi role mein | T30 jaise factual/regulatory message mein strong, repeat 5/5, T29 safe | Sabse slow (parallel avg 8.88 s, 6 s budget se upar), Hinglish 5/6 miss, "Doc" salutation, ~3x cost, T01/T19 invented |

Dono A aur B ke saath T01/T29-type gaps ke liye prompt/guard fixes zaroori rahenge. Final choice user ke confirmation ke baad.
