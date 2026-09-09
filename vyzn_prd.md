# VYZN (Netra) — Product Requirements Document (PRD)

> **Companion Documents:** [ROADMAP.md](file:///c:/Vyzn%20Ai/ROADMAP.md), [vyzn_tech_stack.md](file:///c:/Vyzn%20Ai/vyzn_tech_stack.md), [vyzn_style_guide.md](file:///c:/Vyzn%20Ai/vyzn_style_guide.md), [SCORING_SPEC.md](file:///c:/Vyzn%20Ai/SCORING_SPEC.md).

---

## 1. Problem Statement & Core Thesis

In India, small and medium businesses (kirana stores, retail shops, standalone warehouses, and small offices) have installed millions of CCTV cameras. However, owners receive virtually zero actionable value from them:
- **Continuous 24/7 Recording:** Storing hundreds of hours of raw video on local NVR hard drives is expensive and painful to search. Finding an incident requires manually scrubbing through hours of unindexed footage.
- **Naive Motion Alerts:** Standard camera motion sensors trigger dozens of times an hour from ceiling fans, moving shadows, headlights, insects on lenses, and street traffic.
- **The Fatigue Failure Mode:** Within 48 hours of installing a camera app, the business owner mutes notifications permanently. Once a notification channel is muted, the surveillance system is functionally dead.

**Core Product Thesis:**
The winning product does not provide "more surveillance." It provides **fewer, higher-confidence alerts delivered directly to WhatsApp**, turning existing dumb RTSP cameras into an intelligent after-hours watchdog that shop owners actually trust.

---

## 2. Target Personas

### 2.1 Primary Persona: The Owner-Operator
- **Profile:** Owns and operates a grocery/kirana store, clothing boutique, electronics shop, or small warehouse (2–8 cameras).
- **Behavior:** Spends the day on their feet attending to customers. Lives on WhatsApp; rarely opens dedicated third-party apps or sits at a desktop computer.
- **Pain Points:**
  - After-hours shop break-ins or rear shutter tampering.
  - Suspicious loitering near cash registers during closing hours.
  - Employee intrusion into restricted storage or inventory rooms.
  - Need to resolve customer/delivery disputes quickly ("Did the supplier drop 5 boxes at 3 PM yesterday?").

### 2.2 Secondary Persona: Local CCTV Installer Partner
- **Profile:** Small independent security technician servicing 20–50 retail clients across a district.
- **Motivation:** Looking to offer value-added monthly subscriptions (₹1,000–2,500/camera/mo) rather than one-time hardware installation with thin margins.
- **Pain Points:** Does not want to spend hours per customer fine-tuning motion sensitivity thresholds or answering angry calls about false alarms.

---

## 3. High-Signal Alert Types vs. Deprioritized Alerts

To prevent alert fatigue, the system enforces strict differentiation between high-value operational alerts and generic movement:

### High-Signal Alert Types (First-Class Priority)
1. **After-Hours Entry:** Human detection on any internal or entrance camera outside configured business operating hours (e.g. 21:30 to 08:30).
2. **Cash-Counter Loitering:** Human presence detected inside the configured cash drawer polygon for $> 15$ continuous seconds.
3. **Staff-Only Zone Intrusion:** Movement inside inventory backrooms, server closets, or safe locations during locked windows.
4. **Shutter / Restricted Door Tampering:** Sustained activity ($> 5$ seconds) around entrance shutters during night hours.
5. **Fast Incident Retrieval:** Searchable local/cloud clip index allowing the owner to view key events by date, time window, and object category in under 5 seconds.

### Explicitly Deprioritized (Zero-Push Policy)
- Generic daytime "Person Detected" in customer shopping corridors (logged to SQLite index only, zero push notifications).
- Passing vehicle headlights, cloud shadow shifts, or ceiling fan movement (eliminated by MOG2 downscaled gating + confidence floor).
- Animal detection (cats, dogs, rodents) unless sustained in a restricted zone.

---

## 4. India DPDP Act 2023 & 2025 Rules Compliance

AI video analytics falls explicitly under the scope of India's **Digital Personal Data Protection (DPDP) Act 2023**. Non-compliance carries severe statutory penalties (up to ₹250 crore). The system implements compliance as a built-in product capability:

1. **Mandatory Physical Signage Generation:**
   - The onboarding module auto-generates a printable, standardized bilingual notice (English + Hindi/Marathi) with QR code.
   - Text explicitly declares AI CCTV monitoring, purpose (security/theft prevention), data retention window, and contact info.
2. **Deterministic Retention Policy Engine (Default: 45 Days):**
   - The edge reaper daemon permanently shreds video clips older than 45 days.
   - 72-hour raw footage tier: Clips scoring $< 40$ are purged at 72 hours; clips scoring $40\text{--}69$ are compressed in place via FFmpeg H.264 CRF 28; clips scoring $\ge 70$ or starred by the user are preserved until the 45-day retention boundary.
3. **Data Principal Access & Erasure Workflow:**
   - A documented, single-click export script allows the owner to retrieve or scrub all footage from a specific camera and timestamp upon verified citizen request.
4. **Immutable Audit Trail:**
   - All clip exports, views, cloud synchronizations, and deletions are appended to an immutable SQLite audit log table (`audit_log`).

---

## 5. Functional Requirements by Phase

### Phase 1: Technical MVP (Single Edge Box, Multi-Camera, Local Only)
- **FR-1.1:** Concurrently ingest 2–5 RTSP streams over TCP with zero blocking on `.read()`.
- **FR-1.2:** Downscaled MOG2 motion pre-filter running at 360p/480p to drop non-motion frames instantly.
- **FR-1.3:** Centralized FIFO inference queue processed sequentially by a single YOLOv8n / RF-DETR ONNX instance.
- **FR-1.4:** 5-layer calibrated scoring engine with persistence tracking and hard confidence floors.
- **FR-1.5:** FFmpeg native circular buffer capturing pre-roll ($10\text{s}$) and grace period ($30\text{--}60\text{s}$) directly to fragmented MP4 (`fMP4`).
- **FR-1.6:** Local SQLite index in WAL mode recording event timestamps, object classes, confidence, and file paths.
- **FR-1.7:** Background reaper running every 10 minutes enforcing 72h tiered retention and 85% disk safety margin.
- **FR-1.8:** Instant Telegram bot alerts with attached 8-second MP4 clip and triage buttons ("Important", "False Alarm").

### Phase 2: Commercial Pilot (WhatsApp Alerts & Light Cloud)
- **FR-2.1:** WhatsApp Cloud API integration delivering rich media alert cards to owner phone numbers.
- **FR-2.2:** Web-based zone and schedule editor (FastAPI + HTMX) allowing owners to draw polygon zones on camera stills and define business hours.
- **FR-2.3:** Async cloud synchronization uploading confirmed incident clips ($\text{Score} \ge 70$) to Cloudflare R2.
- **FR-2.4:** Sub-minute alert latency from physical trigger to WhatsApp delivery.

### Phase 3: Paid Beta (Multi-Tenant SaaS)
- **FR-3.1:** Multi-tenant architecture with per-site data isolation (Supabase / PostgreSQL).
- **FR-3.2:** Migration to RF-DETR Nano (Apache 2.0) to eliminate AGPL copyleft liability.
- **FR-3.3:** Modern Next.js responsive web portal for multi-site facility managers.

---

## 6. Non-Functional Requirements

- **Reliability & Resilience:** System must auto-recover from camera disconnects, WiFi loss, and system reboots within 15 seconds without manual intervention.
- **Power Loss Safety:** All recorded video clips must use fragmented MP4 (`fMP4`) so that mid-recording power cuts do not corrupt the file.
- **Compute Efficiency:** Multi-camera edge pipeline (up to 5 streams) must consume $\le 4\text{ GB RAM}$ and run under $65^\circ\text{C}$ on typical quad-core laptop/mini-PC hardware.
- **Low Latency:** High-confidence alert notification must reach the owner's phone in $< 30\text{ seconds}$ on standard 4G/fiber connections.
- **Night/IR Robustness:** Dedicated IR grayscale confidence calibration to maintain $> 90\%$ recall on monochrome night footage without headlight false positives.

---

## 7. Out of Scope (Explicit Anti-Goals)

- **No Facial Recognition or Biometric Tracking:** Prohibited due to high regulatory burden, privacy infringement, and legal exposure under Indian law.
- **No Automatic License Plate Recognition (ALPR):** Unnecessary for retail SMBs; introduces unneeded model weight and calibration friction.
- **No Audio Surveillance / Eavesdropping:** Audio recording without consent violates the Indian Telegraph Act and IT Act. The system operates 100% video-only.
- **No 24/7 Human Security Guard Monitoring:** This is a software product delivering high-confidence intelligence, not a physical private security agency.
