# VYZN (Netra) — Commercial Execution Plan & Unit Economics

> **Companion Documents:** [ROADMAP.md](file:///c:/Vyzn%20Ai/ROADMAP.md), [vyzn_prd.md](file:///c:/Vyzn%20Ai/vyzn_prd.md), [vyzn_tech_stack.md](file:///c:/Vyzn%20Ai/vyzn_tech_stack.md), [SCORING_SPEC.md](file:///c:/Vyzn%20Ai/SCORING_SPEC.md).

---

## 1. Market Opportunity & Competitive Reality

### The Macro Landscape
- **India CCTV Camera Market:** \$2.4 Billion (2026).
- **India Video Surveillance as a Service (VSaaS):** \$187 Million in 2026, projected to reach **\$409 Million by 2031** (14% CAGR).
- **Market Shift:** Indian SMBs (kiranas, retail shops, warehouses, small offices) are refusing to rip out functional hardware. Instead, they demand a plug-and-play **intelligence layer** added to the IP/RTSP cameras they already own.

### Incumbent Pricing & Competitive Anchors
- Direct AI-on-existing-cameras competitors charge **₹1,000 to ₹2,500 / camera / month**.
- Pilot pricing in the market starts at **₹999 first month**, transitioning to ₹2,399–₹7,999 / instance / month.
- Traditional human-monitored CCTV services run **₹3,000 to ₹15,000 / month** for 4–8 cameras.
- **The Strategic Trap:** Undercutting incumbents on price alone is suicide for a small team. Indian SMBs do not cancel services because ₹1,000 is too high; they cancel because false-alert spam makes them mute the app. We compete on **alert precision and zero fatigue**, not race-to-the-bottom pricing.

---

## 2. Unit Economics & Cost Breakdown

Target price point: **₹1,200 per camera / month** (Billed quarterly or annually).

### Per-Camera Monthly Cost Model:
| Cost Item | Monthly Cost (INR) | Operational Notes |
| :--- | :--- | :--- |
| **Edge Compute Electricity** | ₹150 – ₹250 | Shared existing PC or ₹15W low-power edge box. |
| **Cloud Object Storage (Cloudflare R2)** | ₹15 – ₹30 | ~100 high-confidence clips/mo (approx. 5 GB) with \$0 egress. |
| **WhatsApp Cloud API Notification** | ₹60 – ₹120 | Meta utility message template costs (~₹0.40–₹0.80 per alert). |
| **Cloud Webhook / Database Infra** | ₹40 – ₹75 | Multi-tenant FastAPI + Supabase amortized across sites. |
| **Total Direct COGS** | **₹265 – ₹475** | **Gross Margin: 60% – 78%** |

> [!CRITICAL]
> **The Real Unit Economics Killer: Field Support Time**  
> Cloud infrastructure is cheap; manual technician time is expensive. If setting up zones and motion thresholds for a single shop takes 4 hours of on-site tuning, margins collapse. The software must auto-calibrate daylight baselines and provide a 5-minute self-serve onboarding flow.

---

## 3. Go-To-Market & Distribution Strategy

### The Local CCTV Installer Channel (Key Moat)
Attempting cold door-to-door direct sales as software engineers is slow and friction-heavy. 
- **The Partner:** Independent local CCTV technicians and installers in Tier-2/3 cities (e.g. Nagpur, Pune, Nashik).
- **The Value Proposition for Installers:**
  - Installers currently make one-time hardware margins (10–15%) and struggle with recurring revenue.
  - VYZN provides them with a **30% recurring monthly revenue share** (₹350/camera/month) for as long as their client remains active.
  - The installer handles physical wiring and camera placement; VYZN handles the AI pipeline and WhatsApp alerting.

---

## 4. Comprehensive Risk Register & Mitigations

| Risk | Impact | Root Cause | Engineering / Product Mitigation |
| :--- | :--- | :--- | :--- |
| **False-Alert Fatigue** | **Fatal.** User mutes WhatsApp; churns within 14 days. | Wind, shadows, headlights, routine business traffic. | Layer 0 Schedule/Zone filter + Layer 4 Nuisance penalty (-35 pts) + Hard 70-pt threshold. |
| **YOLO AGPL-3.0 License** | Legal liability; forced open-sourcing of proprietary cloud code. | Using Ultralytics YOLO in network SaaS. | Abstract detector interface; migrate to **RF-DETR Nano (Apache 2.0)** prior to commercial billing. |
| **Night / Monochrome IR Accuracy** | Missed break-ins during the highest-risk hours. | RGB-trained models degrade on IR cameras. | Dedicated night calibration: drop confidence threshold to 0.25 on IR streams; test on real night test clips in Phase 0. |
| **Edge Power Outages** | Video corruption; lost evidence. | Common power cuts in Indian Tier-2/3 markets. | FFmpeg Fragmented MP4 (`fMP4`) container; crash-safe writes every 2 seconds. |
| **India DPDP Act Liability** | Fines up to ₹250 Cr for unauthorized biometric or camera data misuse. | Processing footage of public/employees without notice. | Automated 45-day retention purge; printable bilingual QR notice posters; audit trail logging. |
| **Camera Hardware Diversity** | RTSP stream freezes, frame drops, connection timeouts. | Inconsistent firmware across cheap Chinese IP cameras. | Dedicated capture threads, TCP enforcement, and 8-second watchdog reconnect daemon. |

---

## 5. Phase Exit Criteria ("What Worth It Looks Like")

- **Exit Phase 0:** At least 3–5 independent shopkeepers verify that false alerts are their number-one frustration, and 1 owner agrees to a free 1-week pilot.
- **Exit Phase 1 (College Demo):** Edge engine runs autonomously for 7 continuous days across 2–5 streams without crashing, OOM, or thermal throttling; grading panel demo executed flawlessly.
- **Exit Phase 2 (Commercial Pilot):** Deployed across 3–5 active retail businesses for 30 days. WhatsApp alert open rate $> 80\%$, false-alarm reports $< 2$ per camera per week, and at least 2 owners refuse to let you disconnect the hardware.
- **Exit Phase 3 (Commercial Launch):** First 10 paying accounts at ₹1,000–1,500/camera/month; DPDP compliance engine active; RF-DETR running on zero AGPL copyleft liability.
