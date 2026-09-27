# PROJECT GUIDE (Hinglish): kitna time, aapka manual kaam, aur har cheez ki samajh

> Ye file `E:\MAGICPIN` mein hai aur sirf **aapki samajh** ke liye hai. Ye submit nahi hogi.
> **"Material"** = challenge ki 5 files + 6 screenshots. **"Hamara plan"** = implementation choice jo material ki requirement poori karne ke liye hai.
> Jo material mein nahi hai wahan **Not specified** likha hai. Kuch bhi apni taraf se add nahi kiya.
> Ye file har step ke baad update hogi (section 9). Abhi tak koi build start nahi hua.

---

## 0. Hum kaise kaam karenge

1. Har step shuru karne se pehle main aapse puchunga. Aapke "haan" ke bina kuch nahi karunga.
2. Har step ke baad main section 9 mein likhunga: kya kiya, kyun, kaise check kiya, aur aap ise kaise explain karoge.
3. Material se bahar koi feature nahi. Agar kuch alag lage toh main pehle bata dunga, phir aap decide karoge.
4. Sirf `E:\MAGICPIN` ke andar kaam. Kuch delete karne se pehle puchunga.
5. Account banana, payment, API key daalna, aur portal par submit karna aapka kaam hai. Main ye nahi karunga.

---

## 1. Kitna time lagega

> Ye mera **rough andaaza** hai. Material mein time ka kuch nahi likha. **Deadline bhi Not specified hai.**

| Step | Kaam | Mera kaam ka time | Aapka wait ya kaam |
|---|---|---|---|
| 1 | Dataset samajhna (aadha ho chuka) | 20–30 min | Kuch nahi |
| 2 | 5 endpoints ka skeleton | 30–45 min | pip install ki permission |
| 3 | Composer (message likhne wala part) | 1.5–2.5 ghante | API key, 30 messages padhna |
| 4 | Validator aur fallback | 45–90 min | Kuch nahi |
| 5 | Reply engine | 1–1.5 ghante | Kuch nahi |
| 6 | Tick policy aur naye context ka use | 45–75 min | Kuch nahi |
| 7 | Simulator se test aur sudhaar | 1.5–3 ghante | Simulator ki API key |
| 8 | Deploy | 1–2 ghante | Hosting account, login, payment |
| 9 | Stress aur restart test | 45–75 min | Kuch nahi |
| 10 | README, submission.jsonl, bot.py | 30–45 min | README padhna |
| 11 | Submit | 15 min | Portal par submit |
| | **Total** | **lagbhag 9–15 ghante** | **1–2 din mein** |

**Teen milestone (aap kahin bhi ruk sakte ho):**
- **M1: chalta hua baseline** (Step 1–5 aur 8): lagbhag **5–9 ghante**. Endpoints, composer, validator, reply engine, deploy.
- **M2: quality** (Step 6–7): **+2–4 ghante**. Naya context use karna aur simulator par sudhaar.
- **M3: final** (Step 9–11): **+1.5–2 ghante**. Stress test, README, submit.

**Submit kab karein:** FAQ ke hisaab se multiple submissions allowed hain, **lekin har submission quality par judge hoti hai** aur "zyada submissions se weak logic nahi chhipta". Isliye best hai M2 ke baad submit karna. M1 sirf fallback hai agar deadline paas ho.

**Time kya badha sakta hai:**
- API key ya credits mein problem.
- Hosting account ya deploy mein atakna.
- LLM ka slow hona (limit 30s hai, simulator 15s use karta hai).
- Quality ke liye zyada rounds.
- Aapke approvals mein der.

**Cost:** API ka kharcha aapka hoga. Material mein compute reimbursement **Not specified** hai. Har full test run mein lagbhag kuch sau LLM calls jaayengi (mera andaaza). Same input par cache hone se dobara calls bachti hain.

---

## 2. Aapko manual kya karna hai

| # | Kaam | Kab chahiye | Details |
|---|---|---|---|
| M1 | **Deadline check karo** | Abhi | Live page `magicpin.com/vera/ai-challenge` par. Maine live page nahi kholi, aur screenshots mein deadline nahi dikhi. Isse decide hoga ki kitna polish time hai. |
| M2 | **LLM provider chuno, API key banao, credits daalo** | Step 3 se pehle | Material mein koi bhi LLM allowed hai (OpenAI, Anthropic, Google, DeepSeek, etc.). Key **chat mein paste mat karo**. Aap khud `E:\MAGICPIN\.env` mein daaloge. Main placeholder wali `.env.example` bana dunga. |
| M3 | **Simulator ki key** | Step 7 | `judge_simulator.py` ke config section mein `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`. Key aap daalo. `BOT_URL` aur `TEST_SCENARIO` main aapke haan ke baad set karunga. |
| M4 | **Hosting chuno, account banao, payment (agar lage), login** | Step 8 | Material: "Any cloud (AWS, GCP, Azure, Render, Fly, Railway, Replit) ya ngrok tunnel". Main deploy files aur step-by-step guide dunga. Account, payment aur login aapka kaam. |
| M5 | **Public URL kholke dekho** | Step 8 ke baad | Browser mein `https://<aapka-url>/v1/healthz` kholo. JSON dikhna chahiye. |
| M6 | **30 messages khud padho** | Step 3 aur 10 | Jo galat, banaya hua ya ajeeb lage batao. Main bhi check karunga. |
| M7 | **Ye guide aur code samajhna** | Poore project mein | FAQ: "final offer se pehle hum verify karenge ki kaam aapne khud kiya." AI tools allowed hain ya nahi, ye material mein **Not specified** hai. Isliye safe raasta: har file samjho, code khud chalao, aur bina meri madad ke explain kar paao. |
| M8 | **README review** | Step 10 | Main 1-page draft dunga. Aap padho aur apne words mein adjust karo, kyunki approach aap explain karoge. |
| M9 | **Portal par submit** | Step 11 | Website par form bharna, URL paste karna, submit karna. Exact form fields **Not specified**. Main form submit nahi karunga. |
| M10 | **Bot live rakhna** | Submit ke baad | Host on rahe, API credits khatam na ho, evaluation ke dauran redeploy nahi. Score bundle test ke **48 ghante ke andar** milta hai. |
| M11 | **Har step par haan ya ruko** | Har step | Aapke approval ke bina main aage nahi badhunga. |

**Mujhe aapse 3 decisions chahiye:** (1) deadline kya hai, (2) LLM provider aur model kaunsa, (3) hosting kahan. Pehle dono Step 3 se pehle chahiye, hosting Step 8 se pehle.

---

## 3. Main kya karunga, kya nahi

**Karunga:** code likhna, local server chalana, curl tests, simulator chalana, deploy files banana, README ka draft, `submission.jsonl` generate karna, aur ye guide update karna.

**Nahi karunga:** portal par submit, account banana, payment, chat mein API key maangna ya type karna, aur material se bahar features.

---

## 4. Project simple bhasha mein

```
  Judge (magicpin ka harness)  <-- HTTP / JSON -->  Hamara Bot (public URL par)
```

Bot ek **receptionist + copywriter** jaisa hai:

| Endpoint | Simple matlab |
|---|---|
| `POST /v1/context` | Judge files cabinet mein daalta hai (category, merchant, customer, trigger). Bot save karta hai. |
| `POST /v1/tick` | Har 5 min judge puchta hai "kisi ko message bhejna hai?". Bot messages ki list deta hai, ya khaali list. |
| `POST /v1/reply` | Merchant ka jawab aata hai. Bot bolta hai: `send` (jawab bhejo), `wait` (ruko), ya `end` (baat khatam). |
| `GET /v1/healthz` | "Bot zinda hai? Kitne contexts yaad hain?" |
| `GET /v1/metadata` | Team ka naam, model, approach. |

### Ek message ka safar (tick)
1. Judge bolta hai: "abhi ye triggers active hain".
2. Bot har trigger ke liye memory se merchant, category (aur customer agar ho) nikaalta hai.
3. Kuch missing hai toh **skip**. Kuch invent nahi karte.
4. **Signal selector:** trigger, merchant ke numbers aur category mein se **ek sabse strong fact** chunta hai.
5. LLM ko 4 contexts aur rules ka prompt jaata hai, aur wo message ka JSON deta hai.
6. **Validator:** ek hi CTA? language sahi? taboo words? har number context mein hai? Fail hua toh ek baar retry, phir fallback template.
7. Action list banti hai (max 20, dobara wahi suppression_key nahi).
8. Judge merchant ka role karke reply bhejta hai, jo `/v1/reply` par aata hai.

### Reply ka flow
Message aaya, phir is order mein check hota hai:
1. Auto-reply hai? (canned phrases, ya same text bar-bar)
2. "Stop" ya "not interested" ya gaali? Toh `end`.
3. Action ka intent hai ("ok let's do it")? Toh seedha action.
4. Off-topic (jaise GST)? Toh politely mana karke mission par wapas.
5. Baaki sab: LLM se agla jawab, ya `wait`.

---

## 5. Bot ke andar ke parts (hamara plan, badal sakta hai)

```
E:\MAGICPIN\
  bot.py             FastAPI app (uvicorn bot:app) + compose() function
  store.py           contexts aur conversations ki memory (versions ke saath)
  composer.py        compose(): 4 contexts -> message
  signals.py         sabse strong ek signal chunna
  validator.py       CTA, language, taboo, fabricated-number checks
  replies.py         auto-reply, intent, hostile, off-topic, language
  llm.py             LLM call (temperature 0) + cache
  templates.py       WhatsApp template name/params + fallback text
  tests/             hamare apne tests
  submission.jsonl   30 lines (baad mein)
  README.md          1 page (baad mein)
  dataset/ expanded/ examples/ *.md   <- material ka package
```

**`bot.py` ek hi file mein dono kaam kyun karega:** testing brief ka skeleton bolta hai `bot.py` mein FastAPI app (`uvicorn bot:app`). Main brief bolti hai `bot.py` mein `compose()` hona chahiye. Ek hi file mein dono rakhne se dono jagah ki requirement poori hoti hai.

### Har part material se kahan aata hai
| Hamara part | Material mein kahan |
|---|---|
| 4 contexts se message | main brief §4–5 |
| Trigger kind ke hisaab se alag prompt, validation, conversation state | main brief §13 (suggested approach) |
| Ek strongest signal chunna | website: Decision quality, "strong bots ek signal chunte hain" |
| Deterministic (temperature 0 aur cache) | main brief §7.1, website "deterministic compose" |
| Auto-reply detect | main brief §12.1, testing brief Phase 4 |
| Intent se seedha action | main brief §12.2 aur Pattern D |
| Kab rukna hai | main brief §12.5 (3 unanswered nudges) |
| Pehla message template se | main brief §5.1, testing brief §2.2 (`template_name`, `template_params`) |
| Khaali `actions` (restraint) | testing brief FAQ |
| suppression_key se dedup | main brief §4.3 |

---

## 6. Har step ka explanation

**Step 1: Dataset samajhna** (aadha ho chuka)
- **Kya:** expanded dataset dekhna, `examples/api-call-examples.md` aur `examples/case-studies.md` padhna, real field names note karna, saare trigger kinds ki list.
- **Kyun:** bot ko exact keys par kaam karna hai (simulator bhi `vocab_taboo` aur `owner_first_name` padhta hai). Galat key ka matlab data miss, matlab generic message.
- **Check:** 30 test pairs load hote hain, aur har pair ka merchant, trigger, customer file mil jaata hai.

**Step 2: Endpoints skeleton**
- **Kya:** FastAPI mein 5 endpoints aur teardown. Exact schemas, `/context` idempotent, 400 aur 409, `/healthz` mein counts. `/tick` abhi khaali.
- **Kyun:** testing brief §2. Warmup mein 255 contexts ka count check hota hai. healthz fail hone par -10.
- **Check:** curl se har endpoint. Pura dataset push. `/healthz` mein 5/50/200 dikhe.

**Step 3: Composer v1** (sabse bada kaam)
- **Kya:** trigger kind ke hisaab se prompt, ek strongest signal, LLM (temperature 0) se JSON message, input-hash par cache.
- **Kyun:** brief §13 (prompt aur routing), website (Decision quality), brief §7.1 (deterministic).
- **Check:** 30 pairs chalao aur har message haath se padho. Koi number context ke bahar? CTA last sentence mein? Language sahi?

**Step 4: Validator aur fallback**
- **Kya:** LLM ke baad checks. Fail hua toh ek retry, phir deterministic template.
- **Kyun:** brief §13 (post-LLM validation), §11 anti-patterns, FAQ ("hallucinated facts, generic templates, unstable responses reject"). Empty body par -2.
- **Check:** jaan-bujhkar galat outputs daalke dekhna ki validator pakadta hai.

**Step 5: Reply engine**
- **Kya:** auto-reply, intent to action, hostile ya opt-out, off-topic, language switch, 3 unanswered nudges ke baad ruk jao.
- **Kyun:** brief §12, testing brief Phase 4, simulator ke scenarios.
- **Check:** simulator ke 3 scenarios aur hamare apne 4-turn scripts.

**Step 6: Tick policy aur naya context**
- **Kya:** urgency se sort, expired skip, suppression dedupe, max 20 per tick, parallel LLM calls time budget ke saath, naye context ka use, missing merchant ya customer par skip.
- **Kyun:** testing brief §2.2, Phase 3, FAQ (restraint rewarded).
- **Check:** beech mein naya digest, performance aur customer push karke dekhna ki agla message badalta hai.

**Step 7: Simulator se test**
- **Kya:** `judge_simulator.py` config, `TEST_SCENARIO = "full_evaluation"`, sabse kamzor dimension par kaam.
- **Kyun:** testing brief §9 aur §12. Dhyan rahe: default `"all"` messages score nahi karta.
- **Check:** paanchon dimensions non-zero. Simulator sirf anchor hai, asli exam fresh scenarios ka hai.

**Step 8: Deploy**
- **Kya:** public URL par chalana, env vars, `/v1/metadata` bharna, simulator ko public URL par chalana.
- **Kyun:** testing brief §6 aur §12.
- **Aapka kaam:** M4 aur M5.

**Step 9: Stress aur restart test**
- **Kya:** 10 requests per second, 12 ticks naye contexts ke saath, restart ke baad state.
- **Kyun:** testing brief §5 (rate limits) aur "no restarts during test".

**Step 10: Deliverables**
- **Kya:** README (1 page), `submission.jsonl` (30 lines), `bot.py`, optional `conversation_handlers.py`.
- **Kyun:** main brief §7.
- **Aapka kaam:** M8.

**Step 11: Submit**
- **Kya:** aap portal par URL aur details submit karte ho. Bot live rehta hai.
- **Aapka kaam:** M9 aur M10.

---

## 7. Ab tak kya hua (`E:\MAGICPIN` ka status)

**Kiya gaya:**
- Package ki files copy kiye: 5 docs, `dataset/`, `examples/`, `judge_simulator.py`.
- `python dataset/generate_dataset.py --seed-dir dataset --out expanded` chalaya.
- Sirf data padha, koi code nahi likha. Aapka purana `Downloads\magicpin-ai-challenge\vera_bot` folder chhua nahi.

**Verify hua (khud check kiya):**
- Python 3.13.7 installed hai. pip packages abhi install nahi kiye.
- 5 categories, **50 merchants, 200 customers, 100 triggers**, aur `expanded/test_pairs.json` mein **30 pairs**. Har pair mein `test_id, trigger_id, merchant_id, customer_id`.
- **26 trigger kinds** hain (counts ke saath):
  - Merchant-facing: active_planning_intent 2, category_seasonal 1, cde_opportunity 1, competitor_opened 6, curious_ask_due 6, dormant_with_vera 6, festival_upcoming 6, gbp_unverified 1, ipl_match_today 1, milestone_reached 6, perf_dip 6, perf_spike 6, regulation_change 1, renewal_due 6, research_digest 6, review_theme_emerged 6, seasonal_perf_dip 1, supply_alert 1, winback_eligible 1.
  - Customer-facing: appointment_tomorrow 5, chronic_refill_due 6, customer_lapsed_hard 1, customer_lapsed_soft 5, recall_due 6, trial_followup 6, wedding_package_followup 1.
  - **Iska matlab:** brief mein sirf kuch examples the, par data mein 26 kinds hain. Judge naye triggers bhi bhejega, isliye router ko **saare kinds aur unknown kind bhi gracefully** handle karna hoga.
- **Field names (real data):**
  - Category: `slug, display_name, voice, offer_catalog, peer_stats, digest, patient_content_library, seasonal_beats, trend_signals, regulatory_authorities, professional_journals`.
  - `voice`: `tone, register, code_mix, vocab_allowed, vocab_taboo, salutation_examples, ...`. Taboo key **`vocab_taboo`** hai (testing brief ka `taboos` nahi). Simulator bhi `vocab_taboo` padhta hai, toh wo match karta hai.
  - Merchant: `merchant_id, category_slug, identity, subscription, performance, offers, conversation_history, customer_aggregate, signals, review_themes`. `review_themes` brief ke schema mein nahi tha, par data mein hai.
  - Merchant `identity`: `name, city, locality, place_id, verified, languages, owner_first_name, established_year`.
  - Customer: `customer_id, merchant_id, identity, relationship, state, preferences, consent`.
- Example: ek merchant Dr. Meera's Dental Clinic (Lajpat Nagar), languages `["en","hi"]`, `owner_first_name` "Meera", signals `["stale_posts:22d", "ctr_below_peer_median", "high_risk_adult_cohort", "engaged_in_last_48h"]`.

**Abhi verify nahi hua:** trigger ke top-level keys poore (sirf `kind` aur `scope` dekhe), examples files ka content, aur pip packages.

---

## 8. Explain karne layak 8 cheezein

Ye wo sawal hain jo aapse pooche ja sakte hain. Final answers Step 10 ke baad yahan pakke honge.

1. **Architecture kya hai?** 5 endpoints, ek memory store, composer, aur reply engine.
2. **Ek hi signal kyun chunte ho?** Website ka Decision quality: "strong bots har fact repeat nahi karte".
3. **Fabrication kaise rokte ho?** Facts sirf context se. Validator har number aur naam context se match karta hai. Fail hua toh fallback.
4. **Deterministic kaise?** Temperature 0, aur same input par cached output.
5. **Auto-reply kaise pakadte ho?** Canned phrases aur merchant ke level par repeat, kyunki simulator conversation id badalta rehta hai.
6. **Intent transition kaise?** Rules pehle, LLM baad mein. "Let's do it" par turant action.
7. **Judge naya context bheje toh?** Versioned store, aur agla message latest version se banta hai.
8. **Tradeoffs kya hue, aur kaunsa extra context help karta?** README ka sawal. Ye build ke baad honestly likhenge.

---

## 9. Progress log

> Detail ke liye `MAGICPIN_VERA_AI_STEPS_1_TO_6.md` dekho (wahi asli, updated document hai).

| Step | Status | Kya hua |
|---|---|---|
| 1 Dataset | Complete | Dataset expand, saare examples padhe, 30 pairs verify (12 checks) |
| 2 Endpoints | Complete | 5 endpoints + teardown, exact schemas (33 checks + simulator client). Metadata ke personal fields `.env` mein aapko bharne hain |
| 3 Composer | Implemented, offline verified | Groq to OpenRouter failover, compose() (38 checks). Live LLM check pending (keys) |
| 4 Validator + fallback | Complete (offline) | Validator, retry, deterministic fallback saare 100 triggers par (42 checks) |
| 5 Reply engine | Implemented, offline verified | Auto-reply, intent, hostile, off-topic (43 checks + simulator scenarios) |
| 6 Tick policy | Implemented, offline verified | Selection rules, naya context, time budget (60 checks) |
| Final audit (2026-09-27) | Done | 131 audit checks, 359 total, verdict GREEN. Detail: `MAGICPIN_VERA_AI_STEPS_1_TO_6.md` ka aakhri section |
| 7 Simulator test | Not started | Keys chahiye |
| 8 Deploy | Not started | |
| 9 Stress test | Not started | |
| 10 Deliverables | Not started | |
| 11 Submit | Not started | |
