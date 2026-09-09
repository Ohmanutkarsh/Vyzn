# VYZN (Netra) — Commercial Execution Plan & Unit Economics

> **Companion Documents:** [ROADMAP.md](file:///c:/Vyzn%20Ai/ROADMAP.md), [vyzn_prd.md](file:///c:/Vyzn%20Ai/vyzn_prd.md), [vyzn_tech_stack.md](file:///c:/Vyzn%20Ai/vyzn_tech_stack.md), [SCORING_SPEC.md](file:///c:/Vyzn%20Ai/SCORING_SPEC.md).

---

## 1. Market Opportunity & Named Competitive Landscape

### The Macro Landscape
- **India CCTV Camera Market:** \$2.4 Billion (2026).
- **India Video Surveillance as a Service (VSaaS):** \$187 Million in 2026, projected to reach **\$409 Million by 2031** (14% CAGR).
- **Market Shift:** Indian SMBs (kiranas, retail shops, warehouses, small offices) are refusing to rip out functional hardware. Instead, they demand a plug-and-play **intelligence layer** added to the IP/RTSP cameras they already own.

### Named Competitor Matrix & One-Line Differentiation
Investors will ask *"Who else does this?"* in the first five minutes. Here is the direct competitive breakdown:

| Competitor | Target Customer | Pricing Model | Feature Set & UX | VYZN Differentiation |
| :--- | :--- | :--- | :--- | :--- |
| **Staqu Technologies (JARVIS)** | Large Enterprise, Police/Govt, Malls, QSR chains | Enterprise contract (₹1,500–₹3,000/cam/mo + setup) | Heavy facial recognition, optical character recognition, thermal cameras, complex web console. | **Zero-bloat WhatsApp-first:** Staqu sells enterprise compliance suites that require IT teams; VYZN delivers zero-fatigue WhatsApp alerts to single-store shopkeepers with zero training. |
| **Wobot.ai** | QSR chains, Hospitality, Cloud Kitchens | SaaS tier (\$15–\$35 / cam / mo ≈ ₹1,200–₹2,900) | Food safety checklist auditing, hygiene detection, employee SOP tracking on desktop web. | **Security-focused & Mobile-native:** Wobot sells kitchen hygiene audits to corporate brand managers; VYZN prevents after-hours burglary and cash-counter theft directly on the owner's phone. |
| **Vehant Technologies** | Smart Cities, Traffic, Govt Infrastructure | Capital hardware sales + expensive proprietary appliances | Traffic violation detection, vehicle speed tracking, license plate recognition (ALPR). | **Commodity Hardware & Software-Only:** Vehant locks clients into expensive proprietary edge boxes; VYZN runs on any repurposed mini-PC/laptop on existing cheap RTSP cameras. |
| **CP PLUS / Hikvision (Native AcuSense / AI NVR)** | General Commercial & Residential | Hardware replacement (₹3,500–₹8,000 per camera upfront) | Built-in NVR motion tagging, proprietary mobile apps (Hik-Connect, gCMOB). | **No Hardware Rip-and-Replace + Alert Trust:** Incumbent camera apps trigger dozens of false alarms daily and are permanently muted; VYZN layers 5-tier filtering and WhatsApp delivery over existing gear. |

---

## 2. Customer Traction & Market Validation Scorecard

This scorecard serves as the investor validation gate. The product does not proceed to commercial rollout without verified customer proof:

### Phase 0 Discovery Scorecard (Nagpur & Maharashtra Retail Hubs)
```
[Validation Status: Active Pipeline]
Target Persona: Standalone retail shopkeepers, hardware merchants, pharmacy owners, warehouse operators.

+-----------------------------------------------------------------------+-----------+
| Metric                                                                | Value     |
+-----------------------------------------------------------------------+-----------+
| Target Shopkeepers Interviewed                                        | 15        |
| Confirmed unprompted: "I never check my CCTV footage because it's     |           |
| painful, and motion alerts are muted due to false alarms"             | [ _ / 15] |
| Willingness to install a 14-day free pilot edge box on existing RTSP  | [ _ / 15] |
| Stated acceptable price point (₹1,000 – ₹1,500 / camera / month)      | [ _ / 15] |
+-----------------------------------------------------------------------+-----------+
```

### Phase 2 Pilot Cohort Tracking Table
| Site ID | Business Type | Cameras | Weekly Alerts Delivered | Weekly False Alarms Reported | Owner Retention ("Upset if removed?") |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Site 01** | Kirana / Grocery | 4 | *Pending* | *Pending* | *Pending* |
| **Site 02** | Electronics Store | 3 | *Pending* | *Pending* | *Pending* |
| **Site 03** | Logistics Warehouse | 6 | *Pending* | *Pending* | *Pending* |
| **Site 04** | Pharmacy / Chemist | 2 | *Pending* | *Pending* | *Pending* |
| **Site 05** | Hardware Merchant | 4 | *Pending* | *Pending* | *Pending* |

---

## 3. Unit Economics, CAC & Payback Model

**Anchor Price:** **₹1,200 per camera / month** (Billed quarterly: ₹14,400/camera/year).  
**Average Deployment:** 4 cameras per commercial site = **₹4,800 / site / month** (\$58/mo).

### 3.1 Monthly Per-Site Cost of Goods Sold (COGS — 4 Cameras)
| Expense Category | Monthly Cost (INR) | Unit Basis |
| :--- | :--- | :--- |
| **Cloudflare R2 Storage** | ₹80 | ~400 high-confidence 8s fMP4 clips (~4 GB) with \$0 egress. |
| **WhatsApp Cloud API Alerts** | ₹200 | ~250 utility template alerts + quick reply interactions. |
| **Cloud Webhook / Database Infra** | ₹120 | Supabase PostgreSQL + FastAPI instance amortized across sites. |
| **Local Edge Electricity (Pass-through)** | ₹0 | Paid directly by the shopkeeper (runs on shop power). |
| **Total Monthly COGS** | **₹400** | **Direct Gross Margin: 91.6%** |

### 3.2 Customer Acquisition Cost (CAC) & Payback Analysis
We employ two acquisition channels: Direct Outbound vs. Local CCTV Installer Revenue-Share.

| Financial Metric | Direct Outbound Channel | Local CCTV Installer Partner Channel |
| :--- | :--- | :--- |
| **Channel Mechanism** | Direct founder sales & setup in local commercial areas | Local CCTV technicians offer VYZN as a value-add to clients |
| **Partner Revenue Share** | None | **30% ongoing monthly share** (₹1,440 / site / mo) |
| **Upfront Acquisition Cost (CAC)** | **₹3,200** (Time, travel, physical onboarding) | **₹1,000** (Technician onboarding incentive + demo rig) |
| **Net Monthly Revenue to VYZN** | ₹4,800 - ₹400 = **₹4,400** | ₹4,800 - ₹400 (COGS) - ₹1,440 (Partner) = **₹2,960** |
| **Payback Period** | **0.72 months (~22 days)** | **0.34 months (~10 days)** |
| **Projected Customer Lifetime** | 14 months (based on Indian SMB CCTV contracts) | 18 months (higher stickiness via trusted technician) |
| **Lifetime Value (LTV)** | 14 × ₹4,400 = **₹61,600** | 18 × ₹2,960 = **₹53,280** |
| **LTV : CAC Ratio** | **19.2 : 1** | **53.2 : 1** |

---

## 4. Team Narrative: Execution Velocity vs. Risk Mitigation

Investors scrutinize two-person college teams as either an elite execution engine or a severe "bus factor" vulnerability. Here is the operational framework:

```
+------------------------------------------------------------------------------------+
|                             TWO-PERSON EXECUTION MATRIX                            |
+------------------------------------------------------------------------------------+
| Person A: Edge Systems & Computer Vision Lead                                      |
| - Domain: RTSP multi-threading, MOG2 decimation, ONNX/RF-DETR inference,           |
|   NumPy IoU tracking, FFmpeg fMP4 circular recording, SQLite WAL queue.            |
| - Milestone: Autonomous 7-day edge execution on 2-5 streams without crash/leak.    |
+------------------------------------------------------------------------------------+
                                          |
                        [IMMUTABLE CONTRACT: SQLITE SCHEMA & API]
                                          |
+------------------------------------------------------------------------------------+
| Person B: Cloud Infrastructure, Alerting & Front-End Lead                          |
| - Domain: FastAPI async webhook, Meta WhatsApp Cloud API adapter, Telegram triage, |
|   Cloudflare R2 sync, remote telemetry ping, Streamlit/HTMX portals.               |
| - Milestone: Sub-30s alert delivery pipeline and remote site observability.        |
+------------------------------------------------------------------------------------+
```

### Why This Team Wins (The Execution Advantage)
1. **Zero Overhead & Rapid Sprints:** No bureaucratic review cycles. Architecture moves from spec to running code in 3-day iterations.
2. **Deep Native Systems Competence:** Unlike competitors who build thin wrappers around expensive proprietary cloud APIs (e.g. AWS Rekognition), the team builds on native FFmpeg, OpenCV, and local ONNX runtimes, keeping COGS $< 10\%$.
3. **Zero Bus-Factor Dependency:** The SQLite WAL event table and the FastAPI webhook payload are agreed upon upfront as frozen contracts. Person A and Person B develop, test, and mock their subsystems entirely in isolation.

---

## 5. Comprehensive Risk Register (Updated)

| Risk | Impact | Root Cause | Engineering & Operational Mitigation |
| :--- | :--- | :--- | :--- |
| **WhatsApp Cloud API Approval Delays** | **Critical Schedule Blocker** (1–3 week delay) | Meta Business verification and WhatsApp Business Account (WABA) registration require business documentation (GSTIN/firm registration). | **Immediate Day 1 Initiation:** Start Meta developer setup during Phase 0; maintain **Telegram Bot Adapter** for zero-friction internal testing and college demo without blocking code execution. |
| **False-Alert Fatigue** | **Fatal.** User mutes WhatsApp; churns within 14 days. | Environmental noise (wind, shadows, headlights, street traffic). | Layer 0 Schedule/Zone filter + Layer 4 Nuisance penalty (-35 pts) + Hard 70-pt threshold. |
| **YOLO AGPL-3.0 License Poison Pill** | Legal liability; forced open-sourcing of proprietary cloud code. | Ultralytics AGPL-3.0 triggered over network SaaS. | Abstract detector interface (`DetectorInterface`); migrate to **RF-DETR Nano (Apache 2.0)** prior to commercial billing. |
| **Night / Monochrome IR Accuracy** | Missed break-ins during the highest-risk hours. | RGB-trained models degrade on monochrome IR sensors. | Dedicated night calibration: drop confidence threshold to 0.25 on IR streams; validate on real night test clips in Phase 0. |
| **Edge Power Outages** | Video corruption; lost evidence. | Power cuts in Indian Tier-2/3 commercial zones. | FFmpeg Fragmented MP4 (`fMP4`) container; crash-safe writes every 2 seconds. |
| **Field Support Overhead** | Profit margins collapse if technician spends 4 hours per install. | Diverse camera heights and lighting conditions. | Self-calibrating background subtractor + remote polygon zone updates via Cloudflare Tunnel. |
| **India DPDP Act Liability** | Statutory fines up to ₹250 Cr for surveillance non-compliance. | Processing footage of public/employees without notice. | Automated 45-day retention purge; printable bilingual QR notice posters; immutable audit trail logging. |
