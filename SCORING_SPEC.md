# VYZN (Netra) — 5-Layer Scoring Engine Specification

> **Status:** Fully Calibrated Specification  
> **Target Alert Threshold:** $\text{Score} \ge 70$ (with Layer 0 Schedule/Zone Gating)

---

## 1. Mathematical Architecture

Every candidate event detected by the motion and AI pipeline is evaluated against a 5-layer heuristic scoring formula that maps observations into a normalized integer score $[0, 100]$.

$$\text{FinalScore} = \text{Clip}_{[0, 100]}\left( \mathcal{F}(L_1, L_2, L_3, L_4, L_5) \right)$$

An alert notification is dispatched if and only if:
$$\text{FinalScore} \ge 70 \quad \land \quad \text{Gate}_{L0}(\text{Timestamp}, \text{CameraID}, \text{BoundingBox}) == \text{PASS}$$

---

## 2. Detailed Layer Definitions

### Layer 0: Schedule & Spatial Zone Hard Gate ($\text{Gate}_{L0}$)
Prevents alert fatigue during regular retail business hours.

$$\text{Gate}_{L0} = \begin{cases} 
\text{PASS} & \text{if } \text{Time} \in \text{AfterHoursWindow} \\
\text{PASS} & \text{if } \text{Time} \in \text{BusinessHours} \land \text{Box} \cap \text{RestrictedZonePolygon} \neq \emptyset \\
\text{FAIL (Suppress Push)} & \text{if } \text{Time} \in \text{BusinessHours} \land \text{Box} \subset \text{PublicArea}
\end{cases}$$

- **Suppressed Events:** Still recorded and indexed in local SQLite for historical dispute review ("show me 3 PM yesterday"), but **never trigger mobile push alerts**.

---

### Layer 1: Motion Extent ($L_1 \in [0, 20]$ Points)
Measures the physical proportion of the camera frame exhibiting active pixel changes from downscaled MOG2.

$$R_{\text{motion}} = \frac{\text{Count}(\text{Foreground Pixels})}{\text{Total Frame Pixels}}$$

$$L_1 = \min\left(20, \text{round}(R_{\text{motion}} \times 200)\right)$$

*Example:*
- $1\%$ frame motion ($R=0.01$) $\to 0.01 \times 200 = 2\text{ pts}$
- $5\%$ frame motion ($R=0.05$) $\to 0.05 \times 200 = 10\text{ pts}$
- $\ge 10\%$ frame motion ($R \ge 0.10$) $\to 20\text{ pts}$ (capped)

---

### Layer 2: Classification Confidence ($L_2 \in [0, 30]$ Points)
Scales the raw confidence output $c \in [0.0, 1.0]$ of the object detector.

$$L_2 = \text{round}(c \times 30)$$

*Day vs. Night IR Calibration:*
- **Daytime (Color):** Minimum detection confidence threshold $c_{\text{min}} = 0.35$.
- **Night / Monochrome IR:** Minimum detection confidence threshold $c_{\text{min}} = 0.25$ (compensates for lack of chromatic features in IR footage).
- If $c < c_{\text{min}}$, the detection is classified as `unclassified_motion`.

---

### Layer 3: Object-Type Base Weight ($L_3 \in [0, 40]$ Points)
Categorical threat weighting based on detected class:

| Detected Class | Base Points ($L_3$) | Rationale |
| :--- | :--- | :--- |
| **Person** | $40\text{ pts}$ | Primary security risk (burglary, theft, trespass). |
| **Vehicle** | $35\text{ pts}$ | Deliveries, after-hours vehicles at loading shutter. |
| **Animal** | $15\text{ pts}$ | Stray cats/dogs; rare security concern. |
| **Unclassified Motion** | $0\text{ pts}$ | Movement without clear object identification. |

---

### Layer 4: Nuisance Penalty vs. Valid Floor ($L_4$)
Separates legitimate physical objects from environmental noise (wind, curtains, headlight flickers).

$$\text{Subtotal}_{123} = L_1 + L_2 + L_3$$

- **Condition A (Unclassified Motion):** Apply nuisance penalty:
  $$\text{Subtotal}_{1234} = \max(0, \text{Subtotal}_{123} - 35)$$
- **Condition B (Valid Detected Object with $c \ge c_{\text{min}}$):** Apply hard floor:
  $$\text{Subtotal}_{1234} = \max(50, \text{Subtotal}_{123})$$

*Crucial Design Rule:* Any validated person or vehicle detection can never drop below $50\text{ pts}$.

---

### Layer 5: Persistence Bonus ($L_5 \in [0, 15]$ Points)
Rewards continuous physical tracks over single-frame sensor glitches or passing insect flickers.

Using the IoU Tracker, calculate tracked duration $T$ in seconds:

$$L_5 = \min\left(15, \text{round}(T \times 3)\right)$$

- 1 second continuous track: $+3\text{ pts}$
- 3 seconds continuous track: $+9\text{ pts}$
- $\ge 5$ seconds continuous track: $+15\text{ pts}$ (maximum bonus)

---

## 3. Worked Evaluation Scenarios

### Scenario A: After-Hours Intruding Person
- Time: 02:15 AM (After-hours $\to$ Pass $\text{Gate}_{L0}$)
- Motion Extent: $8\%$ of frame ($L_1 = 16\text{ pts}$)
- Object: Person ($L_3 = 40\text{ pts}$)
- Confidence: $0.85$ ($L_2 = 0.85 \times 30 = 26\text{ pts}$)
- Valid Floor: $\max(50, 16 + 26 + 40 = 82) = 82\text{ pts}$
- Persistence: Tracked for $4.5\text{s}$ ($L_5 = 14\text{ pts}$)
- **Total Score:** $82 + 14 = 96\text{ pts}$
- **Outcome: Immediate WhatsApp/Telegram Alert Dispatched** ($\ge 70$).

### Scenario B: Wind Blowing Shutter / Headlight Reflection
- Time: 01:30 AM
- Motion Extent: $4\%$ of frame ($L_1 = 8\text{ pts}$)
- Object: Unclassified ($L_3 = 0\text{ pts}$)
- Confidence: $0.0$ ($L_2 = 0\text{ pts}$)
- Nuisance Penalty: $\max(0, 8 - 35) = 0\text{ pts}$
- Persistence: $0.5\text{s}$ ($L_5 = 1\text{ pt}$)
- **Total Score:** $1\text{ pt}$
- **Outcome: Silently Discarded** ($< 40$, purged at 72h).

### Scenario C: Customer Shopping During Normal Hours
- Time: 03:00 PM (Business Hours)
- Location: General Aisles (Public zone $\to$ Fails $\text{Gate}_{L0}$)
- Score: $90\text{ pts}$
- **Outcome: Saved to Local Index for Dispute Search; Alert Suppressed** (Zero fatigue).

### Scenario D: Loitering at Cash Counter During Closing Hours
- Time: 09:45 PM (Closing Window)
- Location: Inside Cash Counter Polygon ($\text{Gate}_{L0}$ PASS)
- Object: Person, tracked $> 15\text{s}$ ($L_5 = 15$)
- Score: $95\text{ pts}$
- **Outcome: High-Priority Alert Dispatched**.

---

## 4. Reference Python Implementation

```python
from dataclasses import dataclass
from typing import Optional

@dataclass
class DetectionCandidate:
    object_type: str        # 'person', 'vehicle', 'animal', 'unclassified'
    confidence: float       # 0.0 to 1.0
    motion_ratio: float     # 0.0 to 1.0
    track_duration_sec: float
    is_after_hours: bool
    is_in_restricted_zone: bool
    is_night_ir: bool = False

def calculate_event_score(candidate: DetectionCandidate) -> tuple[int, bool]:
    """
    Computes 5-layer event score and returns (score, should_alert).
    """
    # Layer 0: Hard Gate
    if not candidate.is_after_hours and not candidate.is_in_restricted_zone:
        gate_l0_passed = False
    else:
        gate_l0_passed = True

    # Calibration for Night IR
    conf_min = 0.25 if candidate.is_night_ir else 0.35
    is_valid_detection = (
        candidate.object_type in ['person', 'vehicle', 'animal'] and
        candidate.confidence >= conf_min
    )

    # Layer 1: Motion Extent (0-20)
    l1 = min(20, round(candidate.motion_ratio * 200))

    # Layer 2: Confidence (0-30)
    l2 = min(30, round(candidate.confidence * 30))

    # Layer 3: Object Type Weight (0-40)
    weights = {'person': 40, 'vehicle': 35, 'animal': 15, 'unclassified': 0}
    l3 = weights.get(candidate.object_type if is_valid_detection else 'unclassified', 0)

    subtotal_123 = l1 + l2 + l3

    # Layer 4: Nuisance Penalty vs Hard Floor
    if is_valid_detection:
        subtotal_1234 = max(50, subtotal_123)
    else:
        subtotal_1234 = max(0, subtotal_123 - 35)

    # Layer 5: Persistence Bonus (0-15)
    l5 = min(15, round(candidate.track_duration_sec * 3))

    final_score = min(100, max(0, subtotal_1234 + l5))
    should_alert = (final_score >= 70) and gate_l0_passed

    return final_score, should_alert
```
