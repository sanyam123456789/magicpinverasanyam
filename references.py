"""Known example messages from the challenge material.

USED ONLY BY THE VALIDATOR as a similarity guard: examples/case-studies.md says the judge runs a similarity
check against these texts and penalises near-duplicates ("Your wording must be your own"). These strings are
never sent to the LLM and never used as templates.
"""

REFERENCE_BODIES = [
    # case-studies.md 1 (also brief Appendix A, engagement-design worked example, api-call-examples 2.2)
    "Dr. Meera, JIDA's Oct issue landed. One item relevant to your high-risk adult patients — 2,100-patient trial "
    "showed 3-month fluoride recall cuts caries recurrence 38% better than 6-month. Worth a look (2-min abstract). "
    "Want me to pull it + draft a patient-ed WhatsApp you can share? — JIDA Oct 2026 p.14",
    # case-studies.md 2 / brief Appendix B / engagement-design worked example 2 / api-call-examples 2.9
    "Hi Priya, Dr. Meera's clinic here 🦷 It's been 5 months since your last visit — your 6-month cleaning recall is "
    "due. Apke liye 2 slots ready hain: Wed 5 Nov, 6pm ya Thu 6 Nov, 5pm. ₹299 cleaning + complimentary fluoride. "
    "Reply 1 for Wed, 2 for Thu, or tell us a time that works.",
    "Hi Priya, Dr. Meera's clinic here 🦷 It's been 5 months since your last visit — your 6-month cleaning recall is "
    "due. Apke liye 2 slots ready hain: Wed 6 Nov, 6pm ya Thu 7 Nov, 5pm. ₹299 cleaning + complimentary fluoride. "
    "Reply 1 for Wed, 2 for Thu, or tell us a time that works.",
    # case-studies.md 3
    "Hi Kavya 💍 Lakshmi from Studio11 Kapra here. 196 days to your wedding — perfect window to start the 30-day "
    "skin-prep program before serious bridal bookings roll in. ₹2,499 covers 4 sessions + a take-home kit. Want me to "
    "block your preferred Saturday 4pm slot for the first session next week?",
    # case-studies.md 4
    "Hi Lakshmi! Quick check — what service has been most asked-for this week at Studio11? I'll turn the answer into "
    "a Google post + a 4-line WhatsApp reply you can use when customers ask about pricing. Takes 5 min.",
    # case-studies.md 5
    "Quick heads-up Suresh — DC vs MI at Arun Jaitley tonight, 7:30pm. Important: Saturday IPL matches usually shift "
    "-12% restaurant covers (people watch at home). Skip the match-night promo today; instead push your BOGO pizza "
    "(already active) as a delivery-only Saturday special. Want me to draft the Swiggy banner + an Insta story? Live "
    "in 10 min.",
    # case-studies.md 6
    "Suresh, here's a starter version — you can edit: Mylari Corporate Thali — for offices in Indiranagar - 10 thalis "
    "@ ₹125 each (₹25 off retail) + free delivery - 25 thalis @ ₹115 each + 2 free filter coffees - 50+: ₹105 each + "
    "1 free dosa platter - WhatsApp the day-before by 5pm; we deliver between 12:30-1pm 3 offices in Indiranagar are "
    "in your delivery radius (Embassy Tech, RMZ Eco, Sigma Soft). Want me to draft a 3-line WhatsApp to send their "
    "facilities managers?",
    # case-studies.md 7
    "Karthik, your views are down 30% this week — but I want to flag this is the normal April-June acquisition lull "
    "(every metro gym sees -25 to -35% in this window). Action: skip ad spend now, save it for Sept-Oct when "
    "conversion is 2x. For now, focus retention on your 245 members. Want me to draft a \"summer attendance "
    "challenge\" to keep them through the dip?",
    # case-studies.md 8
    "Hi Rashmi 👋 Karthik from PowerHouse here. It's been about 8 weeks — happens to most members at some point, no "
    "judgment. We've added a Tue/Thu evening HIIT class that fits weight-loss goals well (45 min, 6:30pm). Want me to "
    "hold a free trial spot for you next Tue, 30 Apr? Reply YES — no commitment, no auto-charge.",
    # case-studies.md 9
    "Ramesh, urgent: voluntary recall on 2 atorvastatin batches (AT2024-1102, AT2024-1108) by Mfr Z — sub-potency, no "
    "safety risk, but customers should be informed for replacement. Pulled your repeat-Rx list: 22 of your chronic-Rx "
    "customers were dispensed these batches in last 90 days. Want me to draft their WhatsApp note + the "
    "replacement-pickup workflow?",
    # case-studies.md 10
    "Namaste — Apollo Health Plus Malviya Nagar yahan. Sharma ji ki 3 monthly medicines (metformin, atorvastatin, "
    "telmisartan) 28 April ko khatam hongi. Same dose, same brand pack ready hai. Senior discount 15% applied — total "
    "₹1,420 (₹240 saved). Free home delivery to saved address by 5pm tomorrow. Reply CONFIRM to dispatch, or call "
    "9876543210 if any change in dosage.",
    # brief §9 Pattern C
    "Quick nudge: your dashboard shows 6,777 missed searches in Sector 14 for makeup services — people are looking "
    "but not finding you. Want me to show how your listing would appear?",
    # api-call-examples 2.4, 2.7, 4.1, 4.2, 4.3 reply bodies (also guarded for the reply engine)
    "Sending the abstract now (PDF, 2 pages). Patient-ed draft below — you can copy-paste or I'll schedule a Google post",
    "I'll have to leave GST filing to your CA — that's outside what I can help with directly. Coming back to the JIDA "
    "piece — want me to draft the patient post first, or send the abstract?",
    "Looks like an auto-reply 😊 When the owner sees this, just reply 'Yes' for the webinar invite.",
    "Great. Drafting your patient WhatsApp now — 90 seconds. I'll also pre-fill the GBP post for tomorrow 10am. Reply "
    "CONFIRM to send the WhatsApp draft to your patient list (40 high-risk adult patients).",
    "Apologies — I won't message again. If anything changes, you can always restart with 'Hi Vera'. 🙏",
]
