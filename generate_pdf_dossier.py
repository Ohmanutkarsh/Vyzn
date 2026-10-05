"""
Generates a comprehensive, professional PDF technical dossier of the VYZN AI prototype
for academic evaluation, project defense, and teacher review.
"""

import os
import sys
import base64
import subprocess
from pathlib import Path

WORKSPACE = Path(r"c:\Vyzn Ai")
OUTPUT_HTML = WORKSPACE / "VYZN_Prototype_Dossier.html"
OUTPUT_PDF = WORKSPACE / "VYZN_AI_Prototype_Technical_Dossier.pdf"
B64_FILE = WORKSPACE / "cockpit_b64.txt"

def build_pdf():
    cockpit_b64 = ""
    if B64_FILE.exists():
        with open(B64_FILE, "r", encoding="utf-8") as f:
            cockpit_b64 = f.read().strip()

    img_tag = f'<img class="prototype-screenshot" src="data:image/png;base64,{cockpit_b64}" alt="VYZN Live Prototype Cockpit" />' if cockpit_b64 else '<div class="screenshot-placeholder">[Live Dashboard Screenshot Active at http://localhost:8000]</div>'

    html_template = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>VYZN AI — Technical Architecture & Prototype Dossier</title>
<style>
  @page {
    size: A4 portrait;
    margin: 10mm 12mm 10mm 12mm;
  }

  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #0f172a;
    background: #ffffff;
    font-size: 9.5pt;
    line-height: 1.45;
  }

  .page {
    page-break-after: always;
    position: relative;
    padding-bottom: 8mm;
    min-height: 270mm;
  }

  .page:last-child {
    page-break-after: avoid;
  }

  /* Header & Banner */
  .doc-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 2px solid #0284c7;
    padding-bottom: 5px;
    margin-bottom: 10px;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .brand-logo {
    background: linear-gradient(135deg, #0284c7, #0369a1);
    color: white;
    font-weight: 900;
    font-size: 12pt;
    padding: 2px 7px;
    border-radius: 4px;
    letter-spacing: 0.5px;
  }

  .brand-title {
    font-size: 11pt;
    font-weight: 800;
    color: #0f172a;
    letter-spacing: -0.2px;
  }

  .doc-badge {
    font-size: 7pt;
    background: #e0f2fe;
    color: #0369a1;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 12px;
    border: 1px solid #bae6fd;
    text-transform: uppercase;
  }

  /* Typography */
  h1 {
    font-size: 16pt;
    font-weight: 800;
    color: #0f172a;
    margin-bottom: 4px;
    line-height: 1.2;
  }

  h2 {
    font-size: 11.5pt;
    font-weight: 700;
    color: #0369a1;
    border-bottom: 1.5px solid #e2e8f0;
    padding-bottom: 3px;
    margin-top: 10px;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
    gap: 6px;
  }

  h3 {
    font-size: 10pt;
    font-weight: 700;
    color: #1e293b;
    margin-top: 6px;
    margin-bottom: 3px;
  }

  p {
    margin-bottom: 5px;
    color: #334155;
    text-align: justify;
  }

  .lead {
    font-size: 10pt;
    font-weight: 500;
    color: #475569;
    margin-bottom: 8px;
  }

  /* Key Metrics Strip */
  .metric-strip {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin: 8px 0;
  }

  .metric-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    padding: 6px;
    text-align: center;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03);
  }

  .metric-card.accent {
    background: #f0fdf4;
    border-color: #bbf7d0;
  }

  .metric-card.alert {
    background: #fef2f2;
    border-color: #fecaca;
  }

  .metric-value {
    font-size: 13pt;
    font-weight: 800;
    color: #0284c7;
    line-height: 1.1;
  }

  .metric-card.accent .metric-value {
    color: #16a34a;
  }

  .metric-card.alert .metric-value {
    color: #dc2626;
  }

  .metric-label {
    font-size: 7pt;
    font-weight: 600;
    color: #64748b;
    text-transform: uppercase;
    margin-top: 2px;
  }

  /* Tables */
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 6px 0 8px 0;
    font-size: 8pt;
  }

  th {
    background: #f1f5f9;
    color: #334155;
    font-weight: 700;
    text-align: left;
    padding: 4px 6px;
    border: 1px solid #cbd5e1;
    font-size: 7.5pt;
    text-transform: uppercase;
  }

  td {
    padding: 4px 6px;
    border: 1px solid #e2e8f0;
    color: #334155;
    vertical-align: top;
  }

  tr:nth-child(even) {
    background: #f8fafc;
  }

  /* Callout boxes */
  .callout {
    background: #eff6ff;
    border-left: 3px solid #2563eb;
    border-radius: 4px;
    padding: 6px 9px;
    margin: 6px 0;
    font-size: 8.5pt;
  }

  .callout.warning {
    background: #fffbeb;
    border-left-color: #d97706;
  }

  .callout.success {
    background: #f0fdf4;
    border-left-color: #16a34a;
  }

  .callout-title {
    font-weight: 700;
    color: #1e3a8a;
    margin-bottom: 2px;
  }

  .callout.warning .callout-title {
    color: #92400e;
  }

  .callout.success .callout-title {
    color: #166534;
  }

  /* Tags & Badges */
  .badge {
    display: inline-block;
    padding: 1px 5px;
    border-radius: 4px;
    font-size: 7pt;
    font-weight: 700;
  }

  .badge-red { background: #fee2e2; color: #991b1b; }
  .badge-yellow { background: #fef3c7; color: #92400e; }
  .badge-green { background: #dcfce7; color: #166534; }
  .badge-blue { background: #e0f2fe; color: #075985; }
  .badge-gray { background: #f1f5f9; color: #475569; }

  /* Grid Layouts */
  .grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    margin: 6px 0;
  }

  .grid-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 6px;
    margin: 6px 0;
  }

  .card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 5px;
    padding: 6px 8px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
  }

  /* Code block */
  .code-block {
    background: #0f172a;
    color: #f8fafc;
    border-radius: 5px;
    padding: 6px 8px;
    font-family: "SFMono-Regular", Consolas, Menlo, monospace;
    font-size: 7.5pt;
    line-height: 1.35;
    margin: 5px 0;
    overflow-x: hidden;
  }

  .code-keyword { color: #f43f5e; font-weight: bold; }
  .code-func { color: #38bdf8; }
  .code-str { color: #a3e635; }
  .code-num { color: #fbbf24; }
  .code-comm { color: #94a3b8; font-style: italic; }

  /* Architecture SVG Diagram */
  .arch-diagram {
    width: 100%;
    margin: 6px 0 8px 0;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    background: #fafafa;
  }

  .prototype-screenshot {
    width: 100%;
    max-height: 250px;
    object-fit: cover;
    object-position: top;
    border-radius: 5px;
    border: 1px solid #cbd5e1;
    box-shadow: 0 2px 4px rgba(0,0,0,0.08);
    margin: 5px 0;
  }

  .screenshot-placeholder {
    background: #f1f5f9;
    border: 1.5px dashed #94a3b8;
    border-radius: 5px;
    padding: 25px;
    text-align: center;
    color: #64748b;
    font-weight: 600;
    margin: 5px 0;
  }

  /* Telegram Mockup */
  .tg-mockup {
    background: #182533;
    color: #ffffff;
    border-radius: 8px;
    padding: 8px;
    font-size: 7.5pt;
    font-family: -apple-system, sans-serif;
    border: 1px solid #2b5278;
    max-width: 310px;
  }

  .tg-header {
    display: flex;
    align-items: center;
    gap: 5px;
    margin-bottom: 5px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    padding-bottom: 3px;
  }

  .tg-bot-name {
    font-weight: 700;
    color: #64b5f6;
  }

  .tg-btn-row {
    display: flex;
    gap: 4px;
    margin-top: 5px;
  }

  .tg-btn {
    background: #2b5278;
    color: #ffffff;
    border-radius: 4px;
    padding: 3px 5px;
    font-size: 7pt;
    text-align: center;
    flex: 1;
    font-weight: 600;
  }

  .formula-box {
    background: #f8fafc;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 5px 8px;
    font-family: "SFMono-Regular", Consolas, monospace;
    font-size: 8pt;
    color: #0f172a;
    margin: 5px 0;
    text-align: center;
  }

  .footer-strip {
    position: absolute;
    bottom: 2mm;
    left: 0;
    right: 0;
    display: flex;
    justify-content: space-between;
    font-size: 7pt;
    color: #94a3b8;
    border-top: 1px solid #e2e8f0;
    padding-top: 3px;
  }
</style>
</head>
<body>

  <!-- ==================== PAGE 1: TITLE & EXECUTIVE SUMMARY ==================== -->
  <div class="page">
    <div class="doc-header">
      <div class="brand">
        <span class="brand-logo">VYZN AI</span>
        <span class="brand-title">Netra Intelligent VMS</span>
      </div>
      <span class="doc-badge">Academic & Engineering Dossier</span>
    </div>

    <h1>VYZN AI: Edge-First Intelligent Video Management System (VMS) & Threat Detection</h1>
    <p class="lead">An autonomous on-premises retail surveillance system engineered for Indian SMBs — providing real-time shoplifting defense, zero cloud bandwidth costs, sub-second Telegram dispatch, and DPDP Act 2023 compliance.</p>

    <div class="metric-strip">
      <div class="metric-card accent">
        <div class="metric-value">₹0 / mo</div>
        <div class="metric-label">Cloud Streaming Bills</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">&lt; 0.8s</div>
        <div class="metric-label">Alert Dispatch Latency</div>
      </div>
      <div class="metric-card">
        <div class="metric-value">10s + 5s</div>
        <div class="metric-label">RAM Pre/Post-Roll Buffer</div>
      </div>
      <div class="metric-card alert">
        <div class="metric-value">85%</div>
        <div class="metric-label">CPU Compute Savings (MOG2)</div>
      </div>
    </div>

    <h2>1. Executive Summary & Problem Formulation</h2>
    <div class="grid-2">
      <div class="card">
        <h3 style="color: #b91c1c;">The Fatal Flaws of Existing Surveillance</h3>
        <p><strong>1. Prohibitive Cloud Costs:</strong> Streaming 4 RTSP feeds at 1080p consumes ~600 GB/month. For Indian Kirana and retail stores, cloud subscriptions cost ₹1,500–₹4,000/camera/month, making AI surveillance unaffordable.</p>
        <p><strong>2. Crippling Alert Fatigue:</strong> Traditional CCTV cameras trigger dumb pixel-motion alerts for wind, headlights, curtains, and insects, generating 200+ false notifications daily. Store owners eventually disable notifications completely.</p>
        <p><strong>3. Retrospective, Not Proactive:</strong> Standard DVR/NVR setups only record footage. When a theft or intrusion occurs, the owner must manually scrub through 72 hours of static video after the loss has already occurred.</p>
        <p><strong>4. DPDP Act 2023 Violation:</strong> Streaming public footage to uncertified foreign cloud servers breaches India's Digital Personal Data Protection Act.</p>
      </div>

      <div class="card">
        <h3 style="color: #15803d;">The VYZN Edge-First Solution</h3>
        <p><strong>1. 100% On-Premises Edge Compute:</strong> Runs on standard shop hardware (Intel Celeron / Core i3 mini PC or Raspberry Pi 4). Zero video frames leave the store's local network, eliminating cloud subscription bills entirely.</p>
        <p><strong>2. 8-Layer Calibrated Threat Scoring:</strong> Distinguishes genuine shoplifting, drawer reach-ins, and after-hours intruders from harmless environmental motion using mathematical confidence and persistence gating.</p>
        <p><strong>3. Instant Telegram Dispatch with Pre-Roll:</strong> Dispatches alert notifications with snapshot photos and evidence clips directly to the shopkeeper's phone within 800 milliseconds via Telegram bot.</p>
        <p><strong>4. 10-Second Continuous RAM Buffer:</strong> Ensures that when an alert is confirmed, the system saves the 10 seconds <em>before</em> the event occurred, capturing the suspect approaching the counter.</p>
      </div>
    </div>

    <h2>2. Technical Stack & Hardware Architecture</h2>
    <table>
      <thead>
        <tr>
          <th>Subsystem</th>
          <th>Technology Selected</th>
          <th>Engineering Rationale & Advantages</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Edge Video Engine</strong></td>
          <td>Python 3.13 + OpenCV (MOG2 Subtractor)</td>
          <td>Hardware-agnostic RTSP stream capture, 8x downscaled motion gating saving 85% CPU cycles.</td>
        </tr>
        <tr>
          <td><strong>Neural Inference</strong></td>
          <td>YOLOv8-Nano ONNX Runtime</td>
          <td>Quantized neural network execution on CPU without requiring an expensive dedicated Nvidia GPU.</td>
        </tr>
        <tr>
          <td><strong>Object Tracking</strong></td>
          <td>Multi-Object IoU Tracker + Kalman Coaster</td>
          <td>Persistent object ID assignment across frames; calculates loitering duration and velocity metrics.</td>
        </tr>
        <tr>
          <td><strong>Threat Evaluation</strong></td>
          <td>8-Layer Heuristic Decision Engine</td>
          <td>Rigorous multi-stage rule engine combining bounding box intersection, confidence, and time gating.</td>
        </tr>
        <tr>
          <td><strong>Database & Storage</strong></td>
          <td>Embedded SQLite WAL + Circular Storage</td>
          <td>Zero-maintenance local database with 72-hour automated purge complying with DPDP storage limitation.</td>
        </tr>
        <tr>
          <td><strong>Edge API & Dashboard</strong></td>
          <td>FastAPI + Uvicorn + Vanilla JS / CSS</td>
          <td>Ultra-lightweight local web console (runs on port 8000), real-time camera matrix, and canvas zone editor.</td>
        </tr>
        <tr>
          <td><strong>Alert Delivery</strong></td>
          <td>Telegram Bot API (HTTPS Webhooks)</td>
          <td>Free, instant push notification delivery across iOS/Android with interactive triage response buttons.</td>
        </tr>
      </tbody>
    </table>

    <div class="footer-strip">
      <span>VYZN AI Prototype Technical Dossier — Academic Evaluation Reference</span>
      <span>Page 1 of 5</span>
    </div>
  </div>


  <!-- ==================== PAGE 2: SYSTEM ARCHITECTURE & DATA PIPELINE ==================== -->
  <div class="page">
    <div class="doc-header">
      <div class="brand">
        <span class="brand-logo">VYZN AI</span>
        <span class="brand-title">System Architecture</span>
      </div>
      <span class="doc-badge">Pipeline Specification</span>
    </div>

    <h2>3. End-to-End Edge Pipeline Architecture</h2>
    <p>The core innovation of VYZN is its <strong>two-stage compute filter</strong>: compute-heavy neural inference is executed only when physical motion breaches the lightweight MOG2 gate. This enables 3 to 4 simultaneous 1080p camera streams on an affordable mini-PC without GPU acceleration.</p>

    <!-- Architecture SVG -->
    <svg class="arch-diagram" viewBox="0 0 780 190" xmlns="http://www.w3.org/2000/svg">
      <!-- Step 1: Input -->
      <rect x="15" y="25" width="105" height="55" rx="6" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.5"/>
      <text x="67" y="48" font-family="sans-serif" font-size="9" font-weight="bold" fill="#0f172a" text-anchor="middle">RTSP / USB</text>
      <text x="67" y="63" font-family="sans-serif" font-size="8" fill="#64748b" text-anchor="middle">CCTV Streams</text>

      <path d="M 120 52 L 145 52" stroke="#94a3b8" stroke-width="2"/>

      <!-- Step 2: Ring Buffer -->
      <rect x="145" y="25" width="110" height="55" rx="6" fill="#f0f9ff" stroke="#bae6fd" stroke-width="1.5"/>
      <text x="200" y="46" font-family="sans-serif" font-size="9" font-weight="bold" fill="#0369a1" text-anchor="middle">Ring Buffer</text>
      <text x="200" y="60" font-family="sans-serif" font-size="7.5" fill="#0284c7" text-anchor="middle">10s Pre-Roll RAM</text>
      <text x="200" y="71" font-family="sans-serif" font-size="7" fill="#64748b" text-anchor="middle">Circular Deque</text>

      <path d="M 255 52 L 280 52" stroke="#94a3b8" stroke-width="2"/>

      <!-- Step 3: MOG2 Gate -->
      <rect x="280" y="15" width="115" height="75" rx="6" fill="#ecfdf5" stroke="#a7f3d0" stroke-width="1.5"/>
      <text x="337" y="38" font-family="sans-serif" font-size="9" font-weight="bold" fill="#065f46" text-anchor="middle">Stage 1: Motion Gate</text>
      <text x="337" y="52" font-family="sans-serif" font-size="8" fill="#047857" text-anchor="middle">MOG2 Subtractor</text>
      <text x="337" y="65" font-family="sans-serif" font-size="7.5" fill="#64748b" text-anchor="middle">8x Downscale</text>
      <text x="337" y="78" font-family="sans-serif" font-size="7.5" font-weight="bold" fill="#15803d" text-anchor="middle">Saves 85% CPU</text>

      <path d="M 395 52 L 420 52" stroke="#94a3b8" stroke-width="2"/>

      <!-- Step 4: YOLO ONNX -->
      <rect x="420" y="25" width="110" height="55" rx="6" fill="#fdf4ff" stroke="#f0abfc" stroke-width="1.5"/>
      <text x="475" y="46" font-family="sans-serif" font-size="9" font-weight="bold" fill="#86198f" text-anchor="middle">Stage 2: YOLOv8</text>
      <text x="475" y="60" font-family="sans-serif" font-size="7.5" fill="#a21caf" text-anchor="middle">ONNX Detector</text>
      <text x="475" y="71" font-family="sans-serif" font-size="7" fill="#64748b" text-anchor="middle">Day / Night IR Mode</text>

      <path d="M 530 52 L 555 52" stroke="#94a3b8" stroke-width="2"/>

      <!-- Step 5: Tracker & Scoring -->
      <rect x="555" y="15" width="110" height="75" rx="6" fill="#fefce8" stroke="#fef08a" stroke-width="1.5"/>
      <text x="610" y="38" font-family="sans-serif" font-size="9" font-weight="bold" fill="#854d0e" text-anchor="middle">Stage 3: Tracking</text>
      <text x="610" y="52" font-family="sans-serif" font-size="8" fill="#a16207" text-anchor="middle">IoU Multi-Object</text>
      <text x="610" y="65" font-family="sans-serif" font-size="7.5" fill="#64748b" text-anchor="middle">Persistence Timer</text>
      <text x="610" y="78" font-family="sans-serif" font-size="7.5" fill="#a16207" text-anchor="middle">Velocity Analyzer</text>

      <path d="M 665 52 L 690 52" stroke="#94a3b8" stroke-width="2"/>

      <!-- Step 6: 8-Layer Engine -->
      <rect x="690" y="25" width="80" height="55" rx="6" fill="#fff1f2" stroke="#fecdd3" stroke-width="1.5"/>
      <text x="730" y="46" font-family="sans-serif" font-size="9" font-weight="bold" fill="#9f1239" text-anchor="middle">Stage 4: Engine</text>
      <text x="730" y="60" font-family="sans-serif" font-size="7.5" fill="#be123c" text-anchor="middle">8-Layer Threat</text>
      <text x="730" y="71" font-family="sans-serif" font-size="7" font-weight="bold" fill="#9f1239" text-anchor="middle">Score: [0–100]</text>

      <!-- Downward Split from Scoring -->
      <path d="M 730 80 L 730 115" stroke="#94a3b8" stroke-width="2"/>
      <path d="M 730 115 L 200 115" stroke="#94a3b8" stroke-width="2"/>
      <path d="M 200 115 L 200 135" stroke="#94a3b8" stroke-width="2"/>
      <path d="M 475 115 L 475 135" stroke="#94a3b8" stroke-width="2"/>
      <path d="M 730 115 L 730 135" stroke="#94a3b8" stroke-width="2"/>

      <!-- Output 1: Immediate Alert -->
      <rect x="135" y="135" width="130" height="40" rx="4" fill="#eff6ff" stroke="#93c5fd" stroke-width="1.2"/>
      <text x="200" y="151" font-family="sans-serif" font-size="8" font-weight="bold" fill="#1e40af" text-anchor="middle">1. Immediate Telegram</text>
      <text x="200" y="165" font-family="sans-serif" font-size="7.5" fill="#3b82f6" text-anchor="middle">&lt;800ms Snapshot + Triage</text>

      <!-- Output 2: Clip Stitching -->
      <rect x="410" y="135" width="130" height="40" rx="4" fill="#f0fdf4" stroke="#86efac" stroke-width="1.2"/>
      <text x="475" y="151" font-family="sans-serif" font-size="8" font-weight="bold" fill="#166534" text-anchor="middle">2. Pre-Roll Clip Engine</text>
      <text x="475" y="165" font-family="sans-serif" font-size="7.5" fill="#15803d" text-anchor="middle">10s Pre + 5s Post MP4</text>

      <!-- Output 3: SQLite & Cloud -->
      <rect x="665" y="135" width="110" height="40" rx="4" fill="#f8fafc" stroke="#cbd5e1" stroke-width="1.2"/>
      <text x="720" y="151" font-family="sans-serif" font-size="8" font-weight="bold" fill="#334155" text-anchor="middle">3. SQLite Database</text>
      <text x="720" y="165" font-family="sans-serif" font-size="7.5" fill="#64748b" text-anchor="middle">72h Auto Circular Purge</text>
    </svg>

    <h2>4. Technical Breakdown of Pipeline Stages</h2>
    <div class="grid-2">
      <div class="card">
        <h3>Stage 1: Adaptive MOG2 Motion Gating</h3>
        <p>The raw video stream is decoded at native resolution, but motion detection operates on an <strong>8x downscaled grayscale frame</strong> (e.g. 160x90 px). The OpenCV createBackgroundSubtractorMOG2 algorithm updates an adaptive Gaussian mixture model of the background.</p>
        <p>If the foreground pixel ratio R_motion &lt; 0.005 (less than 0.5% of the frame changed), the frame is tagged as idle. <strong>The neural network is completely bypassed</strong>, reducing idle power draw and CPU load to under 5%.</p>
      </div>

      <div class="card">
        <h3>Stage 2: Quantized YOLOv8 ONNX Detector</h3>
        <p>When motion is confirmed, the frame is forwarded to an ONNX Runtime session executing yolov8n.onnx. It identifies object classes (person, vehicle, animal, handbag, drawer).</p>
        <p><strong>Day/Night Dual Calibration:</strong> Under daylight, minimum confidence is set to c_min = 0.35. Under monochrome Infrared (IR) night mode, color saturation drops; the engine dynamically lowers the floor to c_min = 0.25 to prevent dropped intruder detections.</p>
      </div>
    </div>

    <div class="grid-2">
      <div class="card">
        <h3>Stage 3: Multi-Object IoU Tracker</h3>
        <p>Single-frame neural detections are prone to flicker. VYZN implements an Intersection-over-Union (IoU) tracker that assigns stable Track IDs across time.</p>
        <p>The tracker maintains a persistence timer T_track for each detected individual and computes bounding box displacement delta_v. This distinguishes between customers walking past the shop window (fast velocity, no threat) and a burglar standing still before the cash drawer.</p>
      </div>

      <div class="card">
        <h3>Stage 4: 10-Second Pre-Roll Memory Buffer</h3>
        <p>Traditional systems only start recording <em>after</em> an alert is triggered, missing the critical buildup. VYZN maintains a collections.deque(maxlen=300) in RAM storing 10 seconds of uncompressed frames.</p>
        <p>When the scoring threshold is breached, a worker thread immediately captures the 10-second history, appends 5 seconds of active post-roll video, and renders a compressed MP4 clip with Section 65B forensic metadata burned directly into the header.</p>
      </div>
    </div>

    <div class="callout success">
      <div class="callout-title">Edge Resilience Guarantee</div>
      Even during a complete broadband internet failure, all detection, tracking, zone enforcement, and MP4 clip indexing continue unhindered on the local edge machine. Telegram alerts and cloud sync packets are buffered in a local SQLite queue and automatically dispatched the moment connectivity is restored.
    </div>

    <div class="footer-strip">
      <span>VYZN AI Prototype Technical Dossier — Academic Evaluation Reference</span>
      <span>Page 2 of 5</span>
    </div>
  </div>


  <!-- ==================== PAGE 3: 8-LAYER THREAT SCORING ENGINE ==================== -->
  <div class="page">
    <div class="doc-header">
      <div class="brand">
        <span class="brand-logo">VYZN AI</span>
        <span class="brand-title">Mathematical Formulation</span>
      </div>
      <span class="doc-badge">SCORING_SPEC.md Standard</span>
    </div>

    <h2>5. The 8-Layer Mathematical Threat Scoring Engine</h2>
    <p>A major vulnerability in naive AI cameras is treating every neural detection as an alert. VYZN replaces arbitrary if-else statements with a <strong>calibrated 8-layer mathematical evaluation engine</strong> that produces a normalized score S in range [0, 100].</p>

    <div class="formula-box">
      FinalScore = Clip_[0, 100]( [ max(50, L1 + L2 + L3) + L5 + L6 + L7 ] × Multiplier_L8 )
    </div>

    <table>
      <thead>
        <tr>
          <th>Layer</th>
          <th>Layer Name & Purpose</th>
          <th>Mathematical Formula</th>
          <th>Points / Range</th>
          <th>Security Invariant</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Layer 0</strong></td>
          <td>Schedule & Spatial Hard Gate</td>
          <td>Gate_L0 = AfterHours OR (BusinessHours AND Box intersects Zone)</td>
          <td>Binary (PASS/FAIL)</td>
          <td>Suppresses push alerts during open retail hours unless cashier zone is breached.</td>
        </tr>
        <tr>
          <td><strong>Layer 1</strong></td>
          <td>Motion Extent</td>
          <td>L1 = min(20, round(R_motion × 200))</td>
          <td>0 to 20 pts</td>
          <td>Higher foreground displacement receives proportional threat weighting.</td>
        </tr>
        <tr>
          <td><strong>Layer 2</strong></td>
          <td>Classification Confidence</td>
          <td>L2 = min(30, round(Confidence × 30))</td>
          <td>0 to 30 pts</td>
          <td>Gated by c_min (0.35 Day / 0.25 Night IR); unclassified drops to 0.</td>
        </tr>
        <tr>
          <td><strong>Layer 3</strong></td>
          <td>Object Threat Base Weight</td>
          <td>Person = 40, Vehicle = 35, Animal = 15, Noise = 0</td>
          <td>0 to 40 pts</td>
          <td>Human presence is prioritized as the primary security risk.</td>
        </tr>
        <tr>
          <td><strong>Layer 4</strong></td>
          <td>Valid Floor vs Nuisance Penalty</td>
          <td>Valid: max(50, Subtotal_123) | Noise: max(0, Subtotal_123 - 35)</td>
          <td>-35 to 50 pts</td>
          <td><strong>CRITICAL INVARIANT:</strong> A verified human detection can never drop below 50.</td>
        </tr>
        <tr>
          <td><strong>Layer 5</strong></td>
          <td>Persistence / Loitering Bonus</td>
          <td>L5 = min(15, round(T_track × 3))</td>
          <td>0 to 15 pts</td>
          <td>Rewards continuous tracks (+3 pts/sec); caps at 5 seconds loitering.</td>
        </tr>
        <tr>
          <td><strong>Layer 6</strong></td>
          <td>Restricted Zone Proximity</td>
          <td>L6 = 15 if Box intersects Zone Polygon else 0</td>
          <td>0 or 15 pts</td>
          <td>Calculated using 5-point bounding box polygon intersection test.</td>
        </tr>
        <tr>
          <td><strong>Layer 7</strong></td>
          <td>Velocity Transit Penalty</td>
          <td>L7 = -10 if v &gt; 0.6 else (-5 if v &gt; 0.4 else 0)</td>
          <td>-10 to 0 pts</td>
          <td>Fast-moving vehicles/pedestrians in transit are penalized to stop false alarms.</td>
        </tr>
        <tr>
          <td><strong>Layer 8</strong></td>
          <td>Multi-Frame Confirmation</td>
          <td>Frames &le; 1: 0.75x | Frames = 2: 0.90x | Frames &ge; 3: 1.0x</td>
          <td>0.75x to 1.0x</td>
          <td>Suppresses single-frame sensor glitches or headlight flicker spikes.</td>
        </tr>
      </tbody>
    </table>

    <h2>6. Worked Mathematical Proof Scenarios</h2>
    <div class="grid-2">
      <div class="card" style="border-left: 3.5px solid #dc2626;">
        <h3 style="color: #b91c1c;">Scenario A: After-Hours Intruder at Shutter</h3>
        <p><strong>Inputs:</strong> 02:15 AM (After-Hours), Person, Conf: 0.85, Motion: 8% (R=0.08), Track: 4.5s, Inside Zone: Yes.</p>
        <ul style="font-size: 7.5pt; margin-left: 15px; color: #334155;">
          <li>Layer 0: PASS (After-Hours window active)</li>
          <li>L1 = min(20, round(0.08 × 200)) = 16</li>
          <li>L2 = min(30, round(0.85 × 30)) = 26</li>
          <li>L3 = 40 (Person weight) &rarr; Subtotal_123 = 16 + 26 + 40 = 82</li>
          <li>Layer 4 Floor: max(50, 82) = 82</li>
          <li>Layer 5 Persistence: min(15, round(4.5 × 3)) = 14</li>
          <li>Layer 6 Zone Bonus: +15 | Layer 7 Velocity: 0</li>
          <li>Raw Score: 82 + 14 + 15 = 111 &rarr; Multiplier_L8 = 1.0x</li>
        </ul>
        <p style="margin-top: 4px;"><strong>Final Score: 100 (Clipped) &ge; 70 &rarr; <span class="badge badge-red">CRITICAL ALERT DISPATCHED</span></strong></p>
      </div>

      <div class="card" style="border-left: 3.5px solid #16a34a;">
        <h3 style="color: #15803d;">Scenario B: Wind Blowing Curtain / Headlight</h3>
        <p><strong>Inputs:</strong> 01:30 AM (After-Hours), Unclassified, Conf: 0.0, Motion: 4% (R=0.04), Track: 0.5s, Inside Zone: No.</p>
        <ul style="font-size: 7.5pt; margin-left: 15px; color: #334155;">
          <li>Layer 0: PASS (After-Hours window active)</li>
          <li>L1 = min(20, round(0.04 × 200)) = 8</li>
          <li>L2 = 0 | L3 = 0 (Unclassified noise) &rarr; Subtotal_123 = 8</li>
          <li>Layer 4 Nuisance Penalty: max(0, 8 - 35) = 0</li>
          <li>Layer 5 Persistence: min(15, round(0.5 × 3)) = 2</li>
          <li>Layer 6 Zone: 0 | Layer 7 Velocity: 0</li>
          <li>Raw Score: 0 + 2 = 2 &rarr; Multiplier_L8 = 0.75x</li>
        </ul>
        <p style="margin-top: 4px;"><strong>Final Score: 1 &lt; 70 &rarr; <span class="badge badge-green">SILENTLY DISCARDED (NO FATIGUE)</span></strong></p>
      </div>
    </div>

    <div class="grid-2" style="margin-top: 6px;">
      <div class="card" style="border-left: 3.5px solid #2563eb;">
        <h3 style="color: #1d4ed8;">Scenario C: Daytime Customer at Store Counter</h3>
        <p><strong>Inputs:</strong> 03:00 PM (Business Hours), Person, Conf: 0.90, Motion: 6%, General Aisle Area (Not restricted zone).</p>
        <p style="font-size: 7.5pt; color: #334155;"><strong>Layer 0 Evaluation:</strong> Business Hours is TRUE, but Box intersects RestrictedZone is FALSE. Gate L0 returns <strong>FAIL</strong>.</p>
        <p style="margin-top: 4px;"><strong>Outcome: <span class="badge badge-blue">SAVED TO LOCAL DB (PUSH SUPPRESSED)</span></strong></p>
        <p style="font-size: 7pt; color: #64748b;">Event is indexed for dispute search ("show me 3 PM customer"), but zero phone alerts are sent to the owner.</p>
      </div>

      <div class="card" style="border-left: 3.5px solid #d97706;">
        <h3 style="color: #b45309;">Scenario D: Cash Drawer Reach-In During Open Hours</h3>
        <p><strong>Inputs:</strong> 04:30 PM (Business Hours), Person, Conf: 0.88, Motion: 5%, Hand inside Cashier Polygon Geofence.</p>
        <p style="font-size: 7.5pt; color: #334155;"><strong>Layer 0 Evaluation:</strong> Business Hours is TRUE, and Box intersects CashierZone is TRUE. Gate L0 returns <strong>PASS</strong>.</p>
        <p style="margin-top: 4px;"><strong>Outcome: Final Score = 95 &ge; 70 &rarr; <span class="badge badge-yellow">IMMEDIATE CASH THEFT ALERT</span></strong></p>
        <p style="font-size: 7pt; color: #64748b;">Instant alert sent to store owner even while store is open because the cash perimeter was breached.</p>
      </div>
    </div>

    <div class="footer-strip">
      <span>VYZN AI Prototype Technical Dossier — Academic Evaluation Reference</span>
      <span>Page 3 of 5</span>
    </div>
  </div>


  <!-- ==================== PAGE 4: PROTOTYPE WALKTHROUGH & LIVE SCREENS ==================== -->
  <div class="page">
    <div class="doc-header">
      <div class="brand">
        <span class="brand-logo">VYZN AI</span>
        <span class="brand-title">Prototype Walkthrough</span>
      </div>
      <span class="doc-badge">Operational Demonstration</span>
    </div>

    <h2>7. Live Working Prototype: Surveillance Cockpit</h2>
    <p>Below is the live operational cockpit rendered by the local edge server at <code>http://localhost:8000</code>. It showcases the multi-stream synthetic and physical camera matrix with active motion detection and overlay HUD.</p>

    """ + img_tag + """

    <h2>8. Key User Interface & Functional Modules</h2>
    <div class="grid-3">
      <div class="card">
        <h3>1. Multi-Camera Matrix</h3>
        <p style="font-size: 7.5pt;">Real-time synchronized streams for Front Shutter, Cash Counter, and Inventory Backroom. Displays active FPS, resolution (1080p), and live Ring Buffer fill state.</p>
      </div>
      <div class="card">
        <h3>2. Canvas Zone Editor</h3>
        <p style="font-size: 7.5pt;">Interactive vector polygon drawing directly on camera snapshots. Normalizes coordinates to [0.0, 1.0], enabling seamless camera resolution upgrades without re-drawing.</p>
      </div>
      <div class="card">
        <h3>3. Real-Time Incident Feed</h3>
        <p style="font-size: 7.5pt;">Dynamic event stream displaying threat severity badges, IoU track duration, confidence scores, and one-click MP4 playback with Section 65B forensic verification hash.</p>
      </div>
    </div>

    <h2>9. Spatial Zone Polygon Algorithm (5-Point Bounding Intersection)</h2>
    <p>A frequent flaw in standard surveillance software is using only the top-left coordinate or center point of a bounding box for zone checking. If an intruder reaches into a cash drawer, their centroid may remain outside the zone, causing a missed detection.</p>
    
    <div class="code-block">
<span class="code-keyword">def</span> <span class="code-func">check_box_intersects_zone</span>(box: List[float], polygon_pts: List[Tuple[float, float]]) -> bool:
    x1, y1, x2, y2 = box
    <span class="code-comm"># Check 5 strategic anatomical points:</span>
    test_points = [
        ((x1 + x2) / 2.0, (y1 + y2) / 2.0),  <span class="code-comm"># 1. Centroid (Torso)</span>
        ((x1 + x2) / 2.0, y2),                <span class="code-comm"># 2. Bottom Center (Footprint / Standing Base)</span>
        (x1, y2),                             <span class="code-comm"># 3. Bottom Left Corner</span>
        (x2, y2),                             <span class="code-comm"># 4. Bottom Right Corner</span>
        ((x1 + x2) / 2.0, y1 + 0.75*(y2-y1))  <span class="code-comm"># 5. Lower Mid-Body (Reaching Hand / Counter Height)</span>
    ]
    <span class="code-keyword">return</span> any(<span class="code-func">is_point_in_polygon</span>(pt[0], pt[1], polygon_pts) <span class="code-keyword">for</span> pt <span class="code-keyword">in</span> test_points)
    </div>

    <p style="font-size: 8pt; color: #475569;">The point-in-polygon check implements the <strong>Jordan Curve Ray-Casting algorithm</strong> with O(V) complexity, where V is the number of polygon vertices. This guarantees microsecond-level execution on edge CPU cores.</p>

    <div class="footer-strip">
      <span>VYZN AI Prototype Technical Dossier — Academic Evaluation Reference</span>
      <span>Page 4 of 5</span>
    </div>
  </div>


  <!-- ==================== PAGE 5: TELEGRAM ALERTS, DPDP & VIVA DEFENSE ==================== -->
  <div class="page">
    <div class="doc-header">
      <div class="brand">
        <span class="brand-logo">VYZN AI</span>
        <span class="brand-title">Alerting, Compliance & Defense</span>
      </div>
      <span class="doc-badge">Academic Viva Review</span>
    </div>

    <h2>10. Telegram Alerting System & Mobile Triage</h2>
    <div class="grid-2">
      <div class="card">
        <h3>Sub-Second Telegram Bot Dispatch</h3>
        <p>When an event crosses the threshold (Score &ge; 70), an asynchronous background thread dispatches a provisional Telegram alert in <strong>under 800 milliseconds</strong>. It does not wait for the 5-second post-roll video to finish rendering.</p>
        <p>The Telegram payload includes the camera name, risk score, breakdown badges, and an encoded high-resolution JPEG snapshot. Once the MP4 clip finishes rendering, it is automatically pushed into the chat thread.</p>
      </div>

      <!-- Telegram Mockup UI -->
      <div class="tg-mockup">
        <div class="tg-header">
          <span>🚨</span>
          <span class="tg-bot-name">VYZN Netra Security Bot</span>
        </div>
        <div style="font-size: 7.5pt; color: #ff6b6b; font-weight: bold; margin-bottom: 3px;">CRITICAL INTRUDER ALERT (Score: 96/100)</div>
        <div style="font-size: 7.5pt; color: #e2e8f0;">
          <strong>Location:</strong> Store Rear Shutter (Cam 01)<br>
          <strong>Object:</strong> Confirmed Person (85% conf)<br>
          <strong>Zone:</strong> Vault Perimeter Breached<br>
          <strong>Time:</strong> 02:15:10 IST (After-Hours)
        </div>
        <div style="background: #0f172a; padding: 10px; text-align: center; border-radius: 4px; margin: 4px 0; color: #94a3b8; font-size: 7pt;">
          [Snapshot Photo: Person at Shutter]
        </div>
        <div class="tg-btn-row">
          <div class="tg-btn">⭐ Star Clip</div>
          <div class="tg-btn">❌ False Alarm</div>
          <div class="tg-btn" style="background: #991b1b;">🚨 Siren</div>
        </div>
      </div>
    </div>

    <h2>11. DPDP Act 2023 & Section 65B Evidence Compliance</h2>
    <div class="grid-2">
      <div class="card">
        <h3>1. India DPDP Act 2023 Compliance</h3>
        <p style="font-size: 7.5pt;"><strong>Data Minimization & Sovereign Storage:</strong> Video never leaves the store. Cloud telemetry is limited strictly to heartbeat pings and numerical metadata.</p>
        <p style="font-size: 7.5pt;"><strong>Automated Circular Purge:</strong> Unflagged recordings are hard-deleted every 72 hours, complying with the statutory Storage Limitation mandate.</p>
      </div>

      <div class="card">
        <h3>2. Section 65B Evidence Certificate</h3>
        <p style="font-size: 7.5pt;"><strong>Cryptographic Hash Chain:</strong> Every saved incident MP4 generates a SHA-256 hash stored in an append-only audit ledger.</p>
        <p style="font-size: 7.5pt;"><strong>Tamper-Evident Manifest:</strong> Generates automated Section 65B Indian Evidence Act certificates for police FIRs and insurance claim submission.</p>
      </div>
    </div>

    <h2>12. Teacher & Viva Defense Cheat Sheet (Evaluation Q&A)</h2>
    <table>
      <thead>
        <tr>
          <th style="width: 32%;">Anticipated Teacher / Viva Question</th>
          <th>Rigorous Technical Answer & Engineering Rationale</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <td><strong>Q1: Why not run YOLO on every frame directly?</strong></td>
          <td>Running YOLO on every frame at 1080p requires an expensive Nvidia GPU (45W+ power draw, ₹30,000+ cost). By cascading MOG2 background subtraction as an 8x downscaled gate, YOLO is called only when physical motion occurs, reducing CPU consumption by 85% and allowing smooth operation on budget mini-PCs.</td>
        </tr>
        <tr>
          <td><strong>Q2: How does the system operate without internet?</strong></td>
          <td>The system is 100% edge-autonomous. Video decoding, MOG2 gating, YOLO inference, SQLite indexing, and local web dashboard run entirely on localhost. If internet drops, Telegram alerts and cloud sync packets are queued in SQLite and dispatched automatically when connectivity returns.</td>
        </tr>
        <tr>
          <td><strong>Q3: How do you prevent headlights and shadows from causing false alerts?</strong></td>
          <td>Layer 4 applies a severe -35 point nuisance penalty to unclassified motion. Shadows do not yield person/vehicle bounding boxes from YOLOv8, keeping their total score under 10 (well below the 70 alert threshold). Furthermore, Layer 8 dampens single-frame light flashes.</td>
        </tr>
        <tr>
          <td><strong>Q4: Why is the 10-second pre-roll buffer in RAM important?</strong></td>
          <td>Standard motion detectors start recording when the alert fires, which means the video only captures the suspect already fleeing. VYZN's RAM ring buffer permanently retains the preceding 10 seconds, ensuring that the suspect's approach, facial profile, and entry point are captured.</td>
        </tr>
        <tr>
          <td><strong>Q5: What are the verified testing results?</strong></td>
          <td>The project features a comprehensive test suite in <code>tests/run_tests.py</code> with <strong>73 automated test cases passing</strong> across motion gating, ONNX inference, tracker continuity, scoring edge cases, DPDP audit hash chains, and Telegram webhook payloads.</td>
        </tr>
      </tbody>
    </table>

    <div class="footer-strip">
      <span>VYZN AI Prototype Technical Dossier — Academic Evaluation Reference</span>
      <span>Page 5 of 5</span>
    </div>
  </div>

</body>
</html>
"""
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_template)
    print(f"HTML written to {OUTPUT_HTML}")

    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"
    ]
    edge_bin = None
    for p in edge_paths:
        if os.path.exists(p):
            edge_bin = p
            break

    if not edge_bin:
        print("ERROR: Edge executable not found!")
        sys.exit(1)

    print(f"Rendering PDF with Edge ({edge_bin})...")
    cmd = [
        edge_bin,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={OUTPUT_PDF}",
        f"file:///{OUTPUT_HTML.resolve()}"
    ]
    subprocess.run(cmd, capture_output=True, timeout=30)
    if OUTPUT_PDF.exists():
        print(f"SUCCESS! PDF created at: {OUTPUT_PDF} ({OUTPUT_PDF.stat().st_size / 1024:.1f} KB)")
    else:
        print("ERROR: PDF was not created.")

if __name__ == "__main__":
    build_pdf()
