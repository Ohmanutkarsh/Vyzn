# VYZN (Netra) — Style Guide & Brand Manual

> **Companion Documents:** [ROADMAP.md](file:///c:/Vyzn%20Ai/ROADMAP.md), [vyzn_prd.md](file:///c:/Vyzn%20Ai/vyzn_prd.md), [vyzn_tech_stack.md](file:///c:/Vyzn%20Ai/vyzn_tech_stack.md).

---

## 1. Naming & Identity Clearance

- **Primary Working Title:** `VYZN`
- **Recommended Production Alternate:** `NETRA` (नेत्र — Sanskrit/Hindi for *Vision / The Watchful Eye*)
- **Risk Assessment:**
  - "Vyzn" has existing registrations in Switzerland (construction software) and the UK (retail).
  - Before commercial multi-site rollout in Phase 3, conduct a formal Indian Trademark search under **Class 9 (Computer Software)** and **Class 42 (SaaS / Cloud Services)**.
  - *Netra* provides immediate cultural trust, pronunciation clarity across Indian states, and zero confusion for local SMB owners.

---

## 2. Brand Positioning

### Core Product Promise
> **"The camera system that only bothers you when something actually happened."**

### Outcome-Driven Communication
Never describe infrastructure in customer-facing communication. Shopkeepers buy peace of mind and time savings:

| Engineering Concept | What NOT to Say | What to Say to the Owner |
| :--- | :--- | :--- |
| **Motion Gating + MOG2** | "Advanced background subtraction matrix" | "Ignores ceiling fans, curtains, and passing traffic." |
| **Pre-Roll Ring Buffer** | "Circular 10-second FIFO frame queue" | "The video clip starts 10 seconds *before* the door opens, so you catch the whole story." |
| **Clean MP4 Pipeline** | "Unannotated fragmented MP4 container" | "Clean, courtroom-ready video with no messy green boxes burned in." |
| **Zero-Egress Object Store**| "Cloudflare R2 multi-region S3 bucket" | "Watch incident replays as many times as you need with zero data bills." |

---

## 3. Voice & Tone Principles

1. **Calm, Plain, and Specific:**
   - Write like a trusted, competent local technician standing beside the shopkeeper.
   - Ban hyperbole: Never use phrases like *"AI-POWERED SURVEILLANCE REVOLUTION"* or *"NEXT-GEN MILITARY SECURITY"*.
2. **Reassuring, Never Alarmist:**
   - Red flashing banners and siren emojis train users to mute notifications. Save urgency strictly for confirmed after-hours intruders.
3. **Numbers Over Adjectives:**
   - *"3 alerts this week, down from 45"* beats *"Much smarter than other cameras."*
4. **Natural Bilingual / Hinglish Support:**
   - WhatsApp copy must feel natural to Indian retailers. Use conversational English with familiar Hindi/Hinglish terms where appropriate.

### Alert Copy Benchmarks

- **Recommended WhatsApp Alert (Calm, Informative):**
  > 🚪 **Back Shutter — 11:42 PM**  
  > Person detected near the shutter.  
  > *[Watch 8s Clip]*  
  > `[ ✅ Star Clip ]` `[ ❌ False Alarm ]`

- **Recommended Hinglish Alert (Local Kirana):**
  > 🏪 **Cash Counter — 10:15 PM**  
  > Counter ke paas movement detect hui hai.  
  > *[8-second clip dekhein]*

- **Forbidden Copy (Causes Panic & Muting):**
  > 🚨🚨 **CRITICAL RED ALERT!! INTRUDER WARNING!! IMMEDIATE ACTION REQUIRED!!** 🚨🚨

---

## 4. Visual Identity & Color System

Avoid the anxious red-and-black aesthetic common in generic security apps. The palette communicates calm stability, high fidelity, and restraint:

```
+-------------------+-------------------+-------------------+-------------------+
|    Deep Teal      |    Mint Tint      |    Warm Cream     |    Deep Charcoal  |
|    (Trust / Calm) |  (Secondary UI)   |   (Background)    |     (Body Text)   |
|     #0F6E56       |     #5DCAA5       |     #F1EFE8       |       #2C2C2A     |
+-------------------+-------------------+-------------------+-------------------+
|                   |                   |                   |                   |
|                   |  High-Alert Amber |   Emergency Red   |                   |
|                   | (Verified Event)  | (Fire/Disaster)   |                   |
|                   |     #BA7517       |     #D9381E       |                   |
+-------------------+-------------------+-------------------+-------------------+
```

### Color Rules:
- **Primary Deep Teal (`#0F6E56`):** Navigation headers, active status badges, primary action buttons.
- **Warm Cream (`#F1EFE8`):** Clean, non-glaring background for web and mobile dashboards.
- **Deep Charcoal (`#2C2C2A`):** High-contrast, easy-reading typography.
- **Amber (`#BA7517`):** High-confidence security alerts ($\text{Score} \ge 70$).
- **Red (`#D9381E`):** Reserved strictly for life-safety states (smoke/fire indicators). Never used for routine motion.

---

## 5. UI Design Principles for Indian SMBs

1. **The Clip is the UI:**
   - A busy shop owner glances at their screen between customers. Never show a text table when a 3-second looping thumbnail communicates the event instantly.
2. **Mobile & WhatsApp First:**
   - 95% of interactions will occur inside WhatsApp. The web dashboard is an occasional reference tool, not the primary user journey.
3. **Large Touch Targets:**
   - Minimum button height: $48\text{px}$ with generous spacing for single-thumb operation.
4. **Prominent Value Counter:**
   - Prominently display the metric that justifies the product:  
     **"This week: 4 verified alerts delivered. 128 false motions filtered."**
5. **Strict by Default:**
   - New camera installs must default to high sensitivity thresholds for alert suppression. It is far better for an owner to ask to loosen alerts than to mute a noisy system during week one.
