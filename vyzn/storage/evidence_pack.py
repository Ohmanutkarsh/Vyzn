"""
Evidence Pack generator for VYZN clips complying with Section 6.3 of the spec.
Creates VYZN-clip-NNN-YYYY-MM-DD.zip containing:
- clip-NNN.mp4: Original un-annotated video file
- summary.pdf: One-page PDF with facts, reasons, and SHA-256
- metadata.json: Machine-readable JSON export
- HASH.txt: SHA-256 checksum string
- README.txt: Section 63 BSA 2023 notice
"""

from __future__ import annotations
import os
import io
import json
import time
import zipfile
import hashlib
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import zoneinfo

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable


README_TEXT = (
    "This pack was produced by VYZN. VYZN does not certify evidence. In Indian courts, "
    "electronic records are presented with a certificate under Section 63 of the Bharatiya "
    "Sakshya Adhiniyam, 2023, which replaced Section 65B of the Evidence Act on 1 July 2024. "
    "The certificate carries the hash value of the file and is signed by the person in "
    "charge of the device and, where the law requires it, an expert. Ask a lawyer what your "
    "case needs. VYZN deletes its own copy 72 hours after the moment was recorded; the copy "
    "in this pack is yours to keep."
)


def generate_summary_pdf(clip: Dict[str, Any], site_name: str, sha256_hash: str) -> bytes:
    """
    Generates a disciplined, high-density, single-page A4 summary PDF.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    # Custom typographical hierarchy (ISA-101 / Calm aesthetic)
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#111827')
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#4B5563')
    )
    section_h_style = ParagraphStyle(
        'SectionHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=15,
        textColor=colors.HexColor('#1F2937'),
        spaceBefore=8,
        spaceAfter=4
    )
    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#374151')
    )
    mono_style = ParagraphStyle(
        'MonoText',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor('#111827')
    )
    badge_style = ParagraphStyle(
        'Badge',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#B45309') if clip.get('tier') == 'review' else colors.HexColor('#B91C1C')
    )

    elements = []

    # 1. Header Banner
    header_data = [
        [
            Paragraph(f"<b>VYZN</b> · Evidence Pack Summary", title_style),
            Paragraph(f"<b>{clip.get('tier', 'Alert').upper()}</b>", badge_style)
        ],
        [
            Paragraph(f"Site: <b>{site_name}</b> · Clip #{clip.get('number', 1):03d}", subtitle_style),
            Paragraph(f"Node Event ID: {clip.get('id', 'N/A')}", subtitle_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[380, 140])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E5E7EB'), spaceBefore=2, spaceAfter=8))

    # Timestamps in IST and UTC
    start_ms = clip.get('startMs', int(time.time() * 1000))
    end_ms = clip.get('endMs', start_ms + 15000)
    trigger_ms = clip.get('triggerMs', start_ms + 3000)

    try:
        ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    except Exception:
        ist_tz = timezone.utc

    start_dt_ist = datetime.fromtimestamp(start_ms / 1000.0, ist_tz)
    end_dt_ist = datetime.fromtimestamp(end_ms / 1000.0, ist_tz)
    trigger_dt_ist = datetime.fromtimestamp(trigger_ms / 1000.0, ist_tz)

    start_dt_utc = datetime.fromtimestamp(start_ms / 1000.0, timezone.utc)
    end_dt_utc = datetime.fromtimestamp(end_ms / 1000.0, timezone.utc)

    # 2. Key Facts Table
    cam_name = clip.get('cameraName') or clip.get('cameraId', 'Camera')
    area_name = clip.get('areaName') or "Whole camera view"
    duration_sec = clip.get('durationSec', round((end_ms - start_ms) / 1000.0, 1))

    facts_data = [
        [Paragraph("<b>Camera:</b>", body_style), Paragraph(cam_name, body_style),
         Paragraph("<b>Recorded (IST):</b>", body_style), Paragraph(start_dt_ist.strftime("%d %b %Y, %I:%M:%S %p"), body_style)],
        [Paragraph("<b>Watch Area:</b>", body_style), Paragraph(area_name, body_style),
         Paragraph("<b>Recorded (UTC):</b>", body_style), Paragraph(start_dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC"), body_style)],
        [Paragraph("<b>Trigger Moment:</b>", body_style), Paragraph(trigger_dt_ist.strftime("%I:%M:%S %p IST"), body_style),
         Paragraph("<b>Duration:</b>", body_style), Paragraph(f"{duration_sec} seconds", body_style)],
        [Paragraph("<b>Objects Detected:</b>", body_style), Paragraph(", ".join(o.get('cls', 'person').capitalize() for o in clip.get('objects', [])), body_style),
         Paragraph("<b>Clip Number:</b>", body_style), Paragraph(f"Clip {clip.get('number', 1)}", body_style)]
    ]
    facts_table = Table(facts_data, colWidths=[90, 170, 100, 160])
    facts_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#F3F4F6')),
    ]))
    elements.append(facts_table)
    elements.append(Spacer(1, 10))

    # 3. Why this clip was saved (Reasons checklist)
    elements.append(Paragraph("Why this clip was saved", section_h_style))
    reasons = clip.get('reasons', [])
    reasons_rows = []
    for r in reasons:
        code = r.get('code', 'movement')
        params = r.get('params', {})
        if code == 'entered_restricted_area':
            text = f"✓ Entered watch area: {params.get('area', area_name)}"
        elif code == 'stayed_in_area':
            text = f"✓ Stayed in watch area for {params.get('seconds', params.get('duration', 'extended'))} seconds ({params.get('area', area_name)})"
        elif code == 'outside_shop_hours':
            text = "✓ Movement detected outside scheduled shop hours"
        elif code == 'person_detected':
            conf_str = f" · {int(float(params.get('confidence', 0.85))*100)}% confidence" if 'confidence' in params else ""
            text = f"✓ Person detected in {params.get('area', area_name)}{conf_str}"
        elif code == 'movement':
            text = f"✓ Motion activity inside {params.get('area', area_name)}"
        else:
            text = f"✓ Incident condition: {code.replace('_', ' ')}"
        reasons_rows.append([Paragraph(text, body_style)])

    if not reasons_rows:
        reasons_rows.append([Paragraph("✓ Activity registered inside active watch area", body_style)])

    reasons_table = Table(reasons_rows, colWidths=[520])
    reasons_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(reasons_table)
    elements.append(Spacer(1, 10))

    # 4. Technical Details & Cryptographic Integrity
    elements.append(Paragraph("Technical specifications and cryptographic verification", section_h_style))
    detector = clip.get('detector', {})
    if isinstance(detector, str):
        det_str = detector
    elif isinstance(detector, dict):
        det_str = f"{detector.get('name', 'YOLOv8n-VYZN')} (v{detector.get('version', '8.0.196')})"
    else:
        det_str = "YOLOv8n-VYZN (v8.0.196)"

    tech_data = [
        [Paragraph("<b>Detector Engine:</b>", body_style), Paragraph(det_str, body_style)],
        [Paragraph("<b>Primary Media File:</b>", body_style), Paragraph(f"clip-{clip.get('number', 1):03d}.mp4", body_style)],
        [Paragraph("<b>SHA-256 Checksum:</b>", body_style), Paragraph(sha256_hash, mono_style)],
        [Paragraph("<b>Export Generated:</b>", body_style), Paragraph(f"{datetime.now(ist_tz).strftime('%d %b %Y, %I:%M:%S %p IST')} ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')})", body_style)],
    ]
    tech_table = Table(tech_data, colWidths=[130, 390])
    tech_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F9FAFB')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E5E7EB')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#F3F4F6')),
    ]))
    elements.append(tech_table)
    elements.append(Spacer(1, 14))

    # 5. Statutory Advisory (Verbatim Section 6.3)
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#D1D5DB'), spaceBefore=2, spaceAfter=8))
    notice_p = Paragraph(
        "<b>Notice:</b> This pack was produced by VYZN. VYZN does not certify evidence. In Indian courts, "
        "electronic records are presented with a certificate under Section 63 of the Bharatiya Sakshya Adhiniyam, 2023, "
        "which replaced Section 65B of the Evidence Act on 1 July 2024. The certificate carries the hash value of the "
        "file and is signed by the person in charge of the device and, where the law requires it, an expert. "
        "Ask a lawyer what your case needs. VYZN deletes its own copy 72 hours after the moment was recorded; "
        "the copy in this pack is yours to keep.",
        ParagraphStyle(
            'NoticeText',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=7.5,
            leading=10.5,
            textColor=colors.HexColor('#6B7280')
        )
    )
    elements.append(notice_p)

    doc.build(elements)
    return buffer.getvalue()


def create_evidence_pack_zip(
    clip: Dict[str, Any],
    site_name: str,
    raw_video_bytes: Optional[bytes] = None,
    thumb_bytes: Optional[bytes] = None
) -> tuple[str, bytes]:
    """
    Creates the complete Evidence Pack ZIP bundle.
    Returns (filename, zip_bytes).
    Filename format: VYZN-clip-NNN-YYYY-MM-DD.zip
    """
    clip_num = clip.get('clip_number') or clip.get('number', 1)
    start_ms = clip.get('started_at_ms') or clip.get('startMs') or int(time.time() * 1000)
    end_ms = clip.get('ended_at_ms') or clip.get('endMs') or (start_ms + 15000)
    trigger_ms = clip.get('trigger_ms') or clip.get('triggerMs') or (start_ms + 3000)
    camera_name = clip.get('camera_name') or clip.get('cameraName') or clip.get('camera_id') or "Camera"
    camera_id = clip.get('camera_id') or clip.get('cameraId', '')
    site_id = clip.get('site_id', '')

    date_str = datetime.fromtimestamp(start_ms / 1000.0, timezone.utc).strftime("%Y-%m-%d")
    zip_filename = f"VYZN-clip-{clip_num:03d}-{date_str}.zip"
    mp4_filename = f"clip-{clip_num:03d}.mp4"

    # Compute or verify SHA-256
    video_bytes = raw_video_bytes or b""
    if not video_bytes and clip.get('filePath') and os.path.exists(clip['filePath']):
        with open(clip['filePath'], "rb") as vf:
            video_bytes = vf.read()
    elif not video_bytes and clip.get('clip_path') and os.path.exists(clip['clip_path']):
        with open(clip['clip_path'], "rb") as vf:
            video_bytes = vf.read()

    if video_bytes:
        sha256_hash = hashlib.sha256(video_bytes).hexdigest()
    else:
        sha256_hash = clip.get('sha256') or "0000000000000000000000000000000000000000000000000000000000000000"

    # 1. Generate summary.pdf
    pdf_bytes = generate_summary_pdf(clip, site_name, sha256_hash)

    # 2. Metadata JSON
    metadata_dict = {
        "clip_number": clip_num,
        "clipNumber": clip_num,
        "eventId": clip.get('id'),
        "site_id": site_id,
        "site_name": site_name,
        "siteName": site_name,
        "camera_id": camera_id,
        "cameraId": camera_id,
        "camera_name": camera_name,
        "cameraName": camera_name,
        "watchArea": clip.get('areaName') or clip.get('watch_area_name'),
        "start_ms": start_ms,
        "startMs": start_ms,
        "end_ms": end_ms,
        "endMs": end_ms,
        "trigger_ms": trigger_ms,
        "triggerMs": trigger_ms,
        "trigger_time": datetime.fromtimestamp(trigger_ms / 1000.0, timezone.utc).isoformat(),
        "tier": clip.get('tier'),
        "status": clip.get('status'),
        "reasons": clip.get('reasons', []),
        "objects": clip.get('objects', []),
        "detector": clip.get('detector', {}),
        "videoFileName": mp4_filename,
        "sha256": sha256_hash,
        "fileSizeBytes": len(video_bytes),
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "statutoryFramework": "Section 63 of Bharatiya Sakshya Adhiniyam, 2023"
    }
    metadata_bytes = json.dumps(metadata_dict, indent=2).encode('utf-8')

    # 3. HASH.txt (SHA-256 and filename)
    hash_txt_bytes = f"{sha256_hash}  {mp4_filename}\n".encode('utf-8')

    # 4. README.txt
    readme_bytes = README_TEXT.encode('utf-8')

    # Build ZIP archive
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(mp4_filename, video_bytes)
        zf.writestr("summary.pdf", pdf_bytes)
        zf.writestr("metadata.json", metadata_bytes)
        zf.writestr("HASH.txt", hash_txt_bytes)
        zf.writestr("README.txt", readme_bytes)

    return zip_filename, zip_buffer.getvalue()


def generate_evidence_pack(
    clip: Dict[str, Any],
    site_name: str,
    video_bytes: Optional[bytes] = None,
    thumb_bytes: Optional[bytes] = None
) -> bytes:
    """Helper that returns just the zip bytes."""
    _, zip_data = create_evidence_pack_zip(clip, site_name, video_bytes, thumb_bytes)
    return zip_data
