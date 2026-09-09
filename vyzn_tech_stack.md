# VYZN (Netra) — Tech Stack Specification

> **Companion Documents:** [ROADMAP.md](file:///c:/Vyzn%20Ai/ROADMAP.md), [vyzn_prd.md](file:///c:/Vyzn%20Ai/vyzn_prd.md), [SCORING_SPEC.md](file:///c:/Vyzn%20Ai/SCORING_SPEC.md).

---

## 1. Guiding Engineering Philosophy

1. **Python End-to-End First:** Proven CV and backend logic in Python before introducing polyglot overhead or separate JS frontend frameworks.
2. **Interface Isolation:** Hardware interfaces, inference engines, and alert dispatchers must be decoupled behind clean Python abstract base classes (`ABC`).
3. **Zero RAM Video Buffering:** Never buffer raw uncompressed 1080p frames in Python heaps. Offload video encoding and buffering to native FFmpeg C subprocesses.
4. **Staged Complexity:** Each technology tier is unlocked only after the prior phase exit criteria are validated in the field.

---

## 2. Staged Technology Stack

```
+-------------------------------------------------------------------------------------------------+
|                                     STAGED ARCHITECTURE TIERS                                   |
+-------------------------------------------------------------------------------------------------+
| Phase 1: Edge MVP (College Demo)                                                                |
| - Capture: OpenCV VideoCapture (forced TCP + 5s timeout)                                        |
| - Motion Gate: OpenCV MOG2 Subtractor (360p downscaled)                                         |
| - Inference: YOLOv8n via Model Interface (Abstracted for zero lock-in)                         |
| - Tracking: 100-line Pure NumPy IoU Tracker (30-frame coasting)                                 |
| - Recording: FFmpeg subprocess piping directly to Fragmented MP4 (fMP4)                         |
| - Storage: SQLite in WAL mode with Single-Writer Queue pattern                                  |
| - Alerts: Telegram Bot with inline keyboard triage ("Important" / "False Alarm")               |
| - Review UI: Streamlit local clip inspector                                                     |
+-------------------------------------------------------------------------------------------------+
                                                |
                                                v
+-------------------------------------------------------------------------------------------------+
| Phase 2: Commercial Pilot (Indian SMBs)                                                         |
| - Alerts: Meta WhatsApp Cloud API (Interactive Message Templates + Quick Replies)              |
| - Configuration: FastAPI + HTMX / Tailwind (polygon zone editor + business hours)               |
| - Cloud Sync: Cloudflare R2 (S3-compatible, zero-egress fees) via aioboto3                      |
| - Metadata Sync: SQLite edge-to-cloud batch sync                                                |
+-------------------------------------------------------------------------------------------------+
                                                |
                                                v
+-------------------------------------------------------------------------------------------------+
| Phase 3: Commercial SaaS Hardening                                                              |
| - Inference Migration: RF-DETR Nano (Apache 2.0) on ONNX Runtime                                |
| - Cloud Database: PostgreSQL (Supabase managed instance with Row-Level Security)                 |
| - Auth: Supabase Auth / Clerk (OAuth2 + Magic Links)                                            |
| - Web Portal: Next.js 14 (App Router) + Tailwind CSS + Lucide Icons                             |
| - Compliance: Automated DPDP retention & audit trail daemon                                     |
+-------------------------------------------------------------------------------------------------+
```

---

## 3. Detailed Component Choices & Implementation Specifications

### 3.1 Stream Capture Engine
- **Library:** `opencv-python-headless` (avoids GUI/X11 dependencies on headless boxes).
- **Transport Configuration:**
  ```python
  import os
  # Enforce TCP transport and 5-second socket timeout across all FFmpeg decoders
  os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000"
  ```
- **Concurrency Pattern:**
  - One dedicated daemon thread per RTSP camera.
  - Thread decodes frames at 3–5 fps (drops interleaved frames to save CPU).
  - Pushes downscaled NumPy arrays (`640x360`) to an in-memory queue (`queue.Queue(maxsize=15)`).
  - Watchdog tracks `time.monotonic() - last_frame_time`. If $> 8.0\text{ seconds}$, thread releases `cap`, applies exponential backoff ($1\text{s}, 2\text{s}, 4\text{s} \dots \max 30\text{s}$), and reconnects.

### 3.2 Motion Gating Engine
- **Algorithm:** `cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=16, detectShadows=False)`.
- **Optimization:**
  - Shadows disabled (`detectShadows=False`) to avoid 3x grayscale post-processing penalty.
  - Operates exclusively on downscaled grayscale frames ($360\text{p}$).
  - Computes `non_zero_pixels / total_pixels`. If $< 0.005$ ($< 0.5\%$ frame change), frame is discarded immediately. Zero inference cost incurred.

### 3.3 Inference Engine & Licensing Strategy
- **The AGPL-3.0 Copyleft Trap:**
  - Ultralytics YOLOv8 and YOLO11 are licensed under AGPL-3.0.
  - In a networked client/server architecture (FastAPI webhook, WhatsApp alert bot, cloud dashboard), providing network interaction to end users triggers the AGPL-3.0 network copyleft clause, requiring the entire proprietary backend and frontend to be released open-source.
- **The Solution: Model Abstraction Layer:**
  ```python
  from abc import ABC, abstractmethod
  from dataclasses import dataclass
  from typing import List

  @dataclass
  class Detection:
      box: List[float]  # [x1, y1, x2, y2]
      confidence: float
      class_id: int
      label: str

  class BaseDetector(ABC):
      @abstractmethod
      def detect(self, frame) -> List[Detection]:
          pass
  ```
- **Roadmap Transition:**
  - *Phase 1 (Academic Demo / Internal Lab):* Use `UltralyticsDetector` with `yolov8n.pt`. Permissible for non-commercial private prototyping.
  - *Phase 2/3 (Commercial Deployment):* Swap backend to **RF-DETR Nano** or **YOLO-NAS ONNX** under **Apache 2.0 / MIT license**, with zero modifications to application logic.

### 3.4 Tracking Engine
- **Choice:** Pure NumPy Lightweight IoU Tracker (`IouTracker`).
- **Rationale:** Centroid tracking fails on shop corridors during customer-shelf occlusion. DeepSort/ByteTrack with re-ID features require too much edge GPU compute. A 100-line IoU tracker with a 30-frame coasting window provides robust identity preservation and persistence counting ($L_5$ score) at $< 0.5\text{ ms}$ CPU overhead.

### 3.5 Video Recording & Pre-Roll Buffer
- **Subprocess Pipe:** FFmpeg via `subprocess.Popen`.
- **Format:** Fragmented MP4 (`fMP4`).
  ```bash
  ffmpeg -y -rtsp_transport tcp -i rtsp://camera_stream \
    -c:v copy -an \
    -f mp4 -movflags +frag_keyframe+empty_moov+default_base_moof \
    /data/clips/raw/cam_01/2026-09-09/event_101/clip_001.mp4
  ```
- **Crash Proofing:** Traditional MP4 writes the index header (`moov` atom) upon file close. A sudden power cut leaves the video completely corrupt. Fragmented MP4 writes self-contained movie fragments (`moof` + `mdat`) every keyframe ($1\text{--}2\text{ seconds}$). In the event of a power outage, 100% of recorded footage up to the final second is preserved.

### 3.6 Storage & Concurrency
- **Database:** SQLite 3.
- **Connection Pragmas:**
  ```sql
  PRAGMA journal_mode = WAL;
  PRAGMA synchronous = NORMAL;
  PRAGMA busy_timeout = 5000;
  PRAGMA temp_store = MEMORY;
  ```
- **Single-Writer Queue Pattern:**
  - All database write operations are serialized through a dedicated Python `Queue` and written by a single background worker thread.
  - Prevents `sqlite3.OperationalError: database is locked` on Windows systems where file locking across multiple processes can collide.

### 3.7 Alert Notification Engine
- **Adapter Interface (`AlertProvider`):**
  - `TelegramAlertProvider`: Dispatches alerts via Telegram Bot API using asynchronous HTTP (`httpx`). Sends 8s video clip with inline buttons:
    - `[✅ Important / Star]`
    - `[❌ False Alarm]`
  - `WhatsAppAlertProvider`: Integrates with Meta Cloud API using pre-approved interactive templates for Indian shopkeeper phone numbers.

### 3.8 Cloud Object Storage
- **Provider:** Cloudflare R2 (S3-compatible API).
- **Reasoning:** Zero-egress charges. At 50–100 clips per camera/month, standard AWS S3 egress bills become unpredictable; Cloudflare R2 guarantees that reviewing clips from the mobile app incurs \$0 in egress costs.

---

## 4. Explicit Avoid-for-Now List

The following technologies are strictly deferred to Phase 4 (Scale with Customer Demand):
1. **Kubernetes / Docker Swarm:** A single multi-threaded systemd service (or Windows service) handles up to 8 cameras on one machine with near-zero overhead.
2. **ASIC Hardware Encoding Detection (QSV/NVENC probing):** Software H.264 / stream copy (`-c:v copy`) consumes negligible CPU. Driver hell must be avoided.
3. **TimescaleDB / Partitioned Tables:** SQLite handles tens of thousands of event rows per year without degradation.
4. **APM Tracing (Datadog, Highlight.io):** Adds unnecessary memory footprint and network overhead on edge devices.
5. **Complex React/Next.js Dashboards in Phase 1:** Streamlit and HTMX provide immediate UI with zero build toolchain complexity.
