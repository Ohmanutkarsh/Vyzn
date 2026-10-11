# VYZN Scoring System v2.0 & Calibration Specification

## Overview
VYZN Scoring System v2.0 recalibrates CCTV event evaluation across five distinct architectural levels (Levels 1–5) and thirteen analytical layers (Layers 0–12). It eliminates over-scoring and false-positive fatigue while preserving hard security invariants.

All configuration parameters, weights, and thresholds reside strictly in [`config/scoring.json`](config/scoring.json) (versioned `2.0`), with support for per-camera bias and parameter overrides.

---

## 1. Mathematical Score Composition

For every candidate event at time $t$:

$$
\begin{aligned}
\text{positives}(t) &= L_1 + L_2 + L_3 + L_5 + L_6 + L_{11} + L_{12} \\
\text{adjust}(t)    &= L_{4\text{\_pen}} + L_{7\text{\_pen}} + L_{10\text{\_adj}} + \min(0, \text{camera\_bias}) \\
\text{raw}_3(t)     &= \max(0, \text{positives}(t) + \text{adjust}(t)) \\
S_3(t)              &= \text{raw}_3(t) \times M_8 \times R_9 \\
D_4(t)              &= \text{Level 4 Forensic Clip Evidence Modifiers} \in [0, 37] \\
S_{\text{live}}(t)  &= \text{clamp}(S_3(t) + D_4(t), 0, 100) \\
S_{\text{final}}    &= \max_{t} \left( \text{3-second Moving Average}(S_{\text{live}}) \right)
\end{aligned}
$$

### Caps & Floors Order of Execution
1. **Caps:** If an event is unconfirmed ($< 3$ real detection hits) OR is motion-only with no object class:
   $$S_{\text{final}} = \min(S_{\text{final}}, 29)$$
2. **Floors:** Applied **only to confirmed events** (hits $\ge 5$, mean confidence $\ge 0.45$, reliability $R_9 \ge 0.80$, duration $\ge 3$s) or unexplained motion in restricted zones after hours:
   - **Person after hours OR active restricted zone:** $\text{floor} = \max(\text{alert\_threshold}, 70)$
   - **Vehicle after hours:** $\text{floor} = 55$; **Vehicle restricted after hours:** $\text{floor} = 70$
   - **Animal after hours:** $\text{floor} = 30$
   - **Unexplained motion (restricted after hours, $\ge 10$s):** $\text{floor} = 30$
   - **Ordinary business hours events:** **NO floor** (floors never lift business-hours events into Alert/Review).
   $$S_{\text{final}} = \max(S_{\text{final}}, \text{threat\_floor})$$
3. **Rounding:** Round half-up, clamp to integer $[0, 100]$, map to target tier.

---

## 2. Target Tiers & Retention Lifecycle

| Tier | Score Range | UI Severity Label | Action / Governance | Retention Policy |
| :--- | :--- | :--- | :--- | :--- |
| **ALERT** | $70 \le s \le 100$ | **Critical** ($\ge 85$)<br>**High** ($70-84$) | Immediate Telegram alert + browser sound + priority index. Cooldown: 60s, max 6 alerts/cam/hr (bypass if $\ge 85$). | Kept permanently saved (`expires_at = null`). Never auto-deleted. |
| **REVIEW** | $30 \le s < 70$ | **Medium** ($50-69$)<br>**Notable** ($30-49$) | Saved for operator review. No immediate Telegram alarm. | Kept permanently saved (`expires_at = null`). Never auto-deleted. |
| **LOW** | $s < 30$ | **Low** ($< 30$) | Filtered background traffic. Indexed in database. | Auto-deleted after **72 hours** from creation (`expires_at = created_at + 72h`). R2 objects + DB status pruned. |

> **Pinned / Starred Protection:** Any clip with `is_pinned = 1` or `starred = 1` is **permanently exempt** from the 72-hour reaper and FIFO rotation.

---

## 3. Layer Breakdown Reference

- **Layer 0 (Hard Gate & Threat Floors):** Timezone-aware schedule (Asia/Kolkata default). $\pm 15$ min shoulder windows and authorized service windows (e.g., cleaning 06:00–07:00) are neutral (no penalty, no floor).
- **Layer 1 (Motion Extent, $0..10$):** $L_1 = \text{round}(10 \times (1 - \exp(-\text{motion\_ratio} / 0.03)))$. Smoothed over last 2.0s.
- **Layer 2 (Detection Confidence, $0..15$):** $L_2 = \text{round}(15 \times \text{clamp}((c_{\text{mean}} - 0.35) / 0.50, 0, 1))$.
- **Layer 3 (Object Base Weight):** Person: $20$, Vehicle: $14$, Animal: $5$, Carried Item: $3$, Unclassified: $0$.
- **Layer 4 (Nuisance Penalties):** Daytime non-restricted penalties: Person $-12$, Vehicle $-12$, Animal $-4$. Pure motion: $-35$ (relaxed to $-15$ in restricted after hours $\ge 10$s).
- **Layer 5 (Loitering / Dwell, $0..20$):** $0.4 \times \max(0, \text{dwell\_sec} - 10) \times \text{context\_factor}$ (context factor: $0.5$ business hours, $1.0$ after hours). Grace period: $10$s. Evaluated only for persons; $0$ in staff-expected zones during business hours.
- **Layer 6 (Zone Proximity, $0..15$):** Restricted polygon weight $15$, watch area $6$. Foot position inside polygon $\ge 2$s. When `staff_expected` is true during business hours: $L_6 = 0$.
- **Layer 7 (Velocity Penalty):** Fast transit ($> 0.6$ frame/sec): $-10$; moderate ($> 0.4$): $-5$. Suppressed in restricted zones or after hours.
- **Layer 8 (Multi-frame Multiplier $M_8$):** Hits: $1 \to 0.30$, $2 \to 0.55$, $3 \to 0.80$, $4 \to 0.92$, $\ge 5 \to 1.00$.
- **Layer 9 (Detection Reliability $R_9$, $0.5..1.0$):** Product of aspect-ratio checks, bbox height $< 6\%$ ($\times 0.70$), confidence $\sigma > 0.20$ ($\times 0.85$), $\ge 3$ ID switches in 5s ($\times 0.75$), and centroid teleport $> 30\%$ ($\times 0.75$).
- **Layer 10 (Routine Activity Baseline, $-15..+8$):** 28-day historical bucket frequency $p$: $p \ge 0.70 \to -15$; $0.40 \le p < 0.70 \to -8$; $p < 0.10 \to +8$ (requires $\ge 14$ days history). Cold start $< 7$ days: $0$.
- **Layer 11 (Behavioral Pattern, $0..+10$):** Repeated passes ($\ge 3$ in 5 min): $+5$; Approaching restricted zone: $+5$.
- **Layer 12 (Unattended Object, $0..+20$):** Carried item stationary without person within $2\times$ bbox width: $\ge 30$s $\to +10$, $\ge 60$s $\to +20$.
- **Level 4 ($D_4$ Forensic Modifiers, $0..37$):** Person present $+5$, multiple people $+8$, outside business hours $+10$, IR night $+4$, loitering $\ge 30$s $+6$, active duration $\ge 45$s $+4$. (Loitering and duration exempted for staff-expected zones in business hours).

---

## 4. Before / After Calibration Comparison (13 Acceptance Scenarios)

| # | Scenario Description | Old Score (v1) | New Score (v2) | Target Score & Tier | Calibration Status |
| :- | :--- | :--- | :--- | :--- | :--- |
| **1** | Customer walks through, business hours, 25s, conf 0.7, no dwell | $72$ (Alert) | **28** (Low) | $\sim 26 \ (\pm 5) \to$ **LOW** | **PASSED** |
| **2** | Customer lingers 40s near a shelf | $85$ (Alert) | **40** (Review) | $\sim 42 \ (\pm 5) \to$ **REVIEW** | **PASSED** |
| **3** | Staff at counter 5 min (staff-expected, learned baseline) | $95$ (Alert) | **28** (Low) | $< 30 \to$ **LOW** | **PASSED** |
| **3b** | Staff at counter 5 min (cold start, 0 history) | $95$ (Alert) | **43** (Review) | $< 45 \to$ **REVIEW** | **PASSED** |
| **4** | Vehicle passes through ROI 3s, daytime | $60$ (Review) | **9** (Low) | $< 20 \to$ **LOW** | **PASSED** |
| **5** | Dog walks through, daytime | $45$ (Review) | **12** (Low) | $< 20 \to$ **LOW** | **PASSED** |
| **6** | Confirmed person after hours in open area | $85$ (Alert) | **70** (Alert) | $70-75 \to$ **ALERT** (floor) | **PASSED** |
| **7** | Person after hours in cash counter polygon, 60s dwell | $100$ (Alert) | **100** (Alert) | $90-100 \to$ **ALERT / Critical** | **PASSED** |
| **8** | Single-frame person at IR night (glare artifact) | $70$ (Alert) | **26** (Low) | $\le 29 \to$ **LOW** | **PASSED** |
| **9** | Pure motion, no object, business hours (fan/curtain) | $20$ (Low) | **0** (Low) | $< 10 \to$ **LOW** | **PASSED** |
| **10** | Unexplained motion restricted after hours, 15s | $15$ (Low) | **30** (Review) | $\mathbf{30} \to$ **REVIEW** (floor) | **PASSED** |
| **11** | Backpack left alone 90s, business hours | $25$ (Low) | **40** (Review) | $35-55 \to$ **REVIEW** | **PASSED** |
| **12** | Person inside restricted storeroom during business hours | $85$ (Alert) | **70** (Alert) | $\ge 70 \to$ **ALERT** | **PASSED** |
| **13** | Cleaner inside authorized 06:00-07:00 window | $85$ (Alert) | **43** (Review) | $30-45 \to$ **REVIEW** (no alert) | **PASSED** |

---

## 5. Tuning Guide (`config/scoring.json`)

To adjust sensitivity for individual cameras or fleet-wide:

1. **Alert Volume High (>5% of clips):**
   - Increase `"tiers": { "alert_threshold": 75 }` (or set `"camera_biases": { "cam_id": -5 }`).
   - Increase `"layer5_loitering": { "grace_period_sec": 15.0 }`.
2. **Missing Slow / Subtle Intrusions:**
   - Lower `"motion_gate": { "min_motion_ratio": 0.008 }`.
   - Relax `"layer0": { "confirmed_min_hits": 4 }`.
3. **High Background Motion (Trees, Reflections):**
   - Tune `"motion_gate": { "min_contour_area_ratio": 0.0025 }` on the target camera.
   - Adjust `"layer4_nuisance_penalties": { "unclassified": -40 }`.
4. **Replay & Validation:**
   - Run replay evaluation: `python tools/score_replay.py --db data/clips/index.db`
   - Test rescoring without DB modification: `python tools/score_replay.py --db data/clips/index.db --rescore`
