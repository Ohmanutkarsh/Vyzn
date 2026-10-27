# VYZN AI — Edge-to-Cloud Intelligent Video Surveillance & Shoplifting Defense System

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen.svg)](#test-suite)
[![Notifications](https://img.shields.io/badge/alerts-Telegram%20Engine-2CA5E0.svg)](#telegram-alert-engine)
[![Deployment](https://img.shields.io/badge/deploy-Vercel%20Serverless-black.svg)](#cloud-and-vercel-deployment)

**VYZN** is an enterprise-grade AI-powered Video Management System (VMS) engineered for retail theft prevention, local edge surveillance, and sub-second incident alerting. It pairs local, zero-hardware edge intelligence with Supabase cloud user sync and instant Telegram incident triage.

---

## 🚀 Key Features

### 1. Zero-Hardware BYOD & Phone Camera Support
- **Mobile Camera Connect**: Turn any smartphone into an edge surveillance feed via WebRTC / RTSP / MJPEG.
- **ONVIF & Network Discovery**: Automatic local network scanning and probe configuration for IP cameras.
- **Synthetic Test Bench**: Built-in dynamic frame generator for continuous offline simulation and development.

### 2. Dual-Loop AI Motion Gating & Shoplifting Scoring
- **Stage 1 (MOG2 Background Subtractor)**: Ultra-fast motion pre-filter prevents thermal throttling and minimizes GPU/CPU usage during idle periods.
- **Stage 2 (YOLOv8 Object & Appearance Tracking)**: Deep-learning behavioral scoring evaluating dwell time, loitering, concealment gestures, cashier zone intrusions, and high-theft item interactions.
- **Calibrated Multi-Zone Engine**: Define cashier counters, high-theft aisles, entry/exit choke points, and exclusion zones with sub-pixel polygon coordinates.

### 3. Telegram Incident Engine & Instant Triage
- **Sub-Second Alerts**: Delivers MP4 video evidence clips, annotated detection keyframes, and threat assessments directly to store managers via Telegram bot.
- **Interactive Inline Actions**:
  - ⭐ **Star Clip**: Permanently preserves critical evidence against 72-hour storage reaper pruning.
  - ❌ **False Alarm**: Suppresses redundant pings, lowers camera sensitivity temporarily, and logs feedback for calibration.

### 4. Forensic Visual Appearance Search
- **Cross-Camera Re-Identification**: Search for suspects across multiple camera feeds by color histogram, bounding box size, and timestamp ranges.
- **One-Click Evidence Pack**: Generates tamper-evident timestamped evidence bundles with cryptographic hash signatures.

---

## 🏗️ Architecture

```mermaid
graph TD
    subgraph "Retail Store Edge Node (FastAPI :8000)"
        CAM[IP / Phone Cameras] --> SC[Stream Capture & Ring Buffer]
        SC --> MOG[MOG2 Motion Gate]
        MOG -->|Motion Detected| YOLO[YOLOv8 Tracker & Scoring]
        YOLO --> DB[(SQLite Local DB)]
        YOLO --> CW[Evidence Clip Writer]
        YOLO --> TG[Telegram Alert Bot]
    end

    subgraph "Cloud & Auth"
        DB -.->|User & Audit Sync| SUPA[Supabase Cloud Database]
        APP[Web Browser / Mobile] -->|HTTP / WS| VYZN[VYZN Dashboard Console :8000]
    end
```

---

## 📦 Project Structure

```
├── api/                     # Vercel Serverless Python entrypoints
│   ├── index.py             # Serverless FastAPI gateway for Dashboard
│   └── requirements.txt     # Lightweight cloud dependencies
├── config/                  # Zones, cameras, and store locations schema
├── frontend/dashboard/      # Modern v1.1 Web App (Auth, Overview, Cameras, Areas, Clips)
│   ├── index.html           # Auth entrypoint with session router
│   ├── overview.html        # Unified overview & activity stream
│   ├── cameras.html         # Camera grid and management
│   ├── areas.html           # Watch areas and tier configuration
│   └── clips.html           # 72-hour clips & forensic player
├── public/                  # Static assets & distribution build
├── static/                  # Shared frontend assets & web components
├── tests/                   # Automated unit & integration test suite
├── vyzn/                    # Core Edge VMS Engine
│   ├── ai/                  # YOLO detection, tracking, appearance vector extraction
│   ├── alerts/              # Telegram & alert dispatchers
│   ├── api/                 # Edge FastAPI endpoints & MJPEG generators
│   ├── capture/             # RTSP, ONVIF, Phone camera, and synthetic capture
│   ├── core/                # Configuration, SQLite WAL database, Supabase sync
│   ├── motion/              # MOG2 background subtraction gate
│   ├── recording/           # Rolling ring buffer & MP4 evidence clip writer
│   ├── scoring/             # Suspicion scoring, calibrator, zone matrix
│   └── storage/             # Automated disk quota & 72-hour retention reaper
├── run_edge.py              # Single-command Edge VMS runtime launcher
├── vercel.json              # Vercel routing manifest
└── requirements.txt         # Edge runtime dependencies
```

---

## ⚡ Quickstart

### 1. Local Edge VMS Runtime

```bash
# Clone the repository
git clone https://github.com/Ohmanutkarsh/Vyzn-2.git
cd Vyzn-2

# Install dependencies
pip install -r requirements.txt

# Launch Edge VMS with Web Console on port 8000
python run_edge.py --simulate 3 --api --port 8000
```
Open `http://localhost:8000` to access the VYZN dashboard.

### 2. Connect a Phone Camera

1. Navigate to the **Cameras** tab on the dashboard.
2. Click **+ Connect Phone Camera**.
3. Scan the generated QR code or open `http://<EDGE_IP>:8000/mobile-viewer` on your mobile device.
4. Allow camera permissions; the video stream will instantly register as a live feed.

---

## ☁️ Cloud & Vercel Deployment

VYZN includes pre-configured serverless handlers for instant deployment to Vercel:

1. Push to GitHub:
   ```bash
   git push origin main
   ```
2. Import repository into [Vercel](https://vercel.com).
3. Vercel automatically detects `vercel.json` and provisions:
   - Root auth & dashboard entry at `/`
   - Real-time cloud API endpoints under `/api/*`

---

---

## 🎬 Clip Lifecycle State Machine & Forensic Descriptions

VYZN implements an explicit, per-camera state machine (`ClipStateMachine`) resolving both mid-event fragmentation (**P1**) and idle false clips (**P2**) while generating rich, factual event descriptions (**P3**).

```
                  +----------------------------------------------+
                  |                     IDLE                     |
                  |       (Buffering 10s pre-roll ring)          |
                  +----------------------------------------------+
                                         |
                       Motion score >= START_THRESHOLD
                                         v
                  +----------------------------------------------+
                  |                  CANDIDATE                   |
                  |     (Must confirm within CONFIRM_WINDOW)     |
                  +----------------------------------------------+
                         /                                \
           Failed Confirmation                     Confirmed (or YOLO detection)
                        v                                  v
                  +------------+                  +------------------------------+
                  |    IDLE    |                  |          RECORDING           |
                  +------------+                  |   (Writing clip, PTS time)   |
                                                  +------------------------------+
                                                        ^                 |
                                          Activity resumes      No activity detected
                                                        |                 v
                                                  +------------------------------+
                                                  |           HANGOVER           |
                                                  | (10s post-roll quiet timer)  |
                                                  +------------------------------+
                                                                  |
                                                       Quiet for 10 full seconds
                                                                  v
                                                  +------------------------------+
                                                  |          FINALIZING          |
                                                  | - Atomic .tmp.mp4 rename     |
                                                  | - FFmpeg +faststart encode   |
                                                  | - Factual Forensic Summary   |
                                                  | - SQLite & Cloud Sync (R2)   |
                                                  | - Telegram alert (once)      |
                                                  +------------------------------+
                                                                  |
                                                                  v
                                                  +------------------------------+
                                                  |             IDLE             |
                                                  |  (90s debounce merge window) |
                                                  +------------------------------+
```

### Parameter Tuning Guide

| Problem / Symptom | Parameter to Adjust | Direction | Default |
| :--- | :--- | :--- | :--- |
| **Clips cut mid-event (P1)** | `post_roll_sec` (Hangover) | Increase (10s -> 15s) | `10.0` |
| **Clips cut mid-event (P1)** | `track_lost_tolerance_sec` | Increase (5s -> 8s) | `5.0` |
| **Clips cut while subject pauses** | `stationary_hold_max_sec` | Increase (60s -> 90s) | `60.0` |
| **Clips cut mid-event (P1)** | `continue_motion_threshold` | Decrease (0.003 -> 0.002) | `0.003` |
| **Too sensitive / false clips (P2)** | `start_motion_threshold` | Increase (0.010 -> 0.015) | `0.010` (1.0%) |
| **Single-frame blips trigger clips** | `confirm_frames` / `confirm_window` | Increase (3/5 -> 4/5) | `3` in `5` |
| **Short bursts recorded separately** | `merge_gap_sec` (Debounce) | Increase (90s -> 120s) | `90.0` |
| **Clips run too long** | `post_roll_sec` | Decrease (10s -> 6s) | `10.0` |
| **Clips exceed max segment** | `max_clip_duration_sec` | Adjust split size | `180.0` |

### Running the Offline Replay Harness

Run the 11-scenario automated verification test suite:
```bash
python -m pytest tests/test_clip_lifecycle_and_description.py -v
```

Replay and evaluate any custom MP4 footage before edge deployment:
```python
from vyzn.evaluation.replay_harness import ReplayHarness

harness = ReplayHarness(camera_id="cam_01", write_clips_to_disk=True)
clips = harness.replay_video_file("test_footage.mp4")

print(f"Generated {len(clips)} validated clips:")
for clip in clips:
    print(f"- [{clip.clip_id}] Duration: {clip.duration}s | Trigger: {clip.trigger_reason} | Close: {clip.close_reason}")
    print(f"  Summary: {clip.analysis.get('summary')}")
```

---

## 🧪 Test Suite

Run the full automated test suite verifying edge capture, behavioral scoring, Telegram alerts, and cloud synchronization:

```bash
python -m pytest tests/
```
**Results**: `97 passed, 0 failed (100% pass rate)`.


---

## 💳 Camera Quota & Manual UPI Billing System

VYZN Netra features a camera quota system designed for personal UPI payments with manual verification. Customers cannot add cameras without available quota slots. Top-ups are initiated from **Settings > Camera Plan**, paid via fixed-amount UPI QR codes, proof of payment is verified via a 12-digit UTR, and quota is credited **only** upon manual admin approval.

```mermaid
sequenceDiagram
    autonumber
    actor Customer
    participant UI as VYZN Web UI
    participant API as FastAPI Backend
    participant TG as Telegram Bot
    actor Admin as Store Owner / Admin

    Customer->>UI: Selects camera quantity in Settings > Camera Plan
    UI->>API: POST /billing/quota-orders {quantity}
    API-->>UI: Returns {order_code, amount, upi_link, fixed_amount_qr}
    Customer->>Customer: Scans QR / opens UPI app & pays fixed amount
    Customer->>UI: Submits 12-digit UTR reference
    UI->>API: POST /billing/quota-orders/{id}/submit-utr {utr}
    API->>TG: Instant alert with order code, tenant, amount, & UTR
    TG-->>Admin: "Match amount, UTR and order code in UPI app"
    Admin->>Admin: Verifies UTR in GPay / PhonePe / bank statement
    Admin->>API: POST /admin/billing/orders/{id}/approve (via /admin/billing)
    API->>API: Atomic transaction: lock row, set status=paid, add quota
    API-->>UI: Real-time update: "N cameras added to your quota"
    Customer->>UI: Adds new camera (Enforcement checks available quota > 0)
```

### 1. Setting Up UPI ID, Price, and Enforcement

Add the following environment variables to your `.env` file:

```env
# Personal UPI ID / VPA to receive payments directly to your bank account:
UPI_VPA=yourbusiness@okhdfcbank

# Payee name displayed in the customer's UPI app (Google Pay, PhonePe, Paytm):
UPI_PAYEE_NAME="VYZN Surveillance"

# Price per camera quota slot in paise (e.g. 249900 paise = ₹2,499.00):
CAMERA_PRICE_PAISE=249900

# Maximum cameras allowed in a single top-up order:
MAX_CAMERAS_PER_ORDER=20

# Order expiration window in minutes (unpaid orders expire automatically):
ORDER_EXPIRY_MINUTES=30

# Authorized admin user IDs or emails (comma-separated) for approval actions:
ADMIN_USER_IDS="admin@vyzn.ai,owner@vyzn.ai,usr_admin_001"

# Enable strict camera quota enforcement on camera creation:
# Defaults to false so existing local edge cameras and testing demos keep working.
BILLING_ENFORCEMENT=true
```

### 2. How to Approve Orders

1. **Customer Submits UTR**: Customer selects camera count in **Settings > Camera Plan**, scans the fixed-amount QR code, and enters the 12-digit UPI reference number (UTR).
2. **Instant Telegram Notification**: The system immediately dispatches a Telegram message to the store owner containing the order code (e.g. `VYZ-4821`), tenant, quantity, amount, and UTR.
3. **Verify in UPI App**: Look up the transaction in Google Pay, PhonePe, Paytm, or your bank statement. Match:
   - **Amount**: Exactly equals the order amount.
   - **UTR Reference**: Exactly matches the submitted 12-digit number.
   - **Order Code**: Present in the UPI transaction note (`tn=VYZ-XXXX`).
4. **Approve via Admin Console**:
   - Navigate to `/admin/billing` in your browser.
   - Click **Approve**. The order status updates to `paid` and the purchased quantity is atomically added to the tenant's quota.
   - If payment is invalid, click **Reject** and supply a reason. Rejection leaves quota untouched.
   - *Approving twice is strictly idempotent and will never credit quota twice.*

### 3. How to Swap in a Payment Gateway Later

Payment generation is completely decoupled behind the `PaymentProvider` interface in [`vyzn/billing/provider.py`](file:///vyzn/billing/provider.py). No database schemas, API routes, or enforcement paths depend on manual UPI logic.

To swap in a payment gateway (e.g., Razorpay, Stripe, Cashfree):

1. Open [`vyzn/billing/provider.py`](file:///vyzn/billing/provider.py) and create a new provider class implementing `PaymentProvider`:

```python
from vyzn.billing.provider import PaymentProvider

class RazorpayPaymentProvider(PaymentProvider):
    def __init__(self, key_id: str, key_secret: str):
        self.client = razorpay.Client(auth=(key_id, key_secret))

    def build_payment(self, order: dict) -> dict:
        rp_order = self.client.order.create({
            "amount": order["amount_paise"],
            "currency": "INR",
            "receipt": order["order_code"]
        })
        return {
            "gateway_order_id": rp_order["id"],
            "upi_link": f"https://checkout.razorpay.com/v1/checkout.js?order_id={rp_order['id']}",
            "qr": "" # Gateway modal handles QR
        }
```

2. In [`vyzn/billing/service.py`](file:///vyzn/billing/service.py), instantiate `BillingService` with your new provider:

```python
# From:
self.provider = payment_provider or ManualUpiProvider()

# To:
self.provider = payment_provider or RazorpayPaymentProvider(key_id=..., key_secret=...)
```

All quota tracking, partial index order deduplication, atomic row-locking enforcement, and admin audit logging remain 100% intact.

---

## 📄 License
Proprietary — All rights reserved © VYZN AI Inc.

