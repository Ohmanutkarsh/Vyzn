# VYZN Video Surveillance, Segmentation, and Storage Standards (MANDATORY RULES)

These rules are permanent project law and MUST be followed strictly at all times without exception.

## 1. Frame Rate & Visual Stream Quality
- All camera streams and video recordings must run at a smooth frame rate of at least 15 FPS (never decimate to choppy 1–4 FPS).
- Video resolution must be at least 480p (minimum 854x480 for 16:9 or 640x480 for 4:3), never degraded to low-res 360p.
- Stream rendering and recording must deliver crisp, fluid, professional CCTV video.

## 2. Event State Machine Clip Segmentation
- Configured strictly in `config/config.json` under `"clip"`:
  - `score_interval_seconds`: 3.0
  - `active_score_threshold`: 30
  - `quiet_gap_seconds`: 90.0
  - `pre_roll_seconds`: 10.0
  - `post_roll_seconds`: 10.0
  - `min_active_ticks`: 1
  - `max_clip_seconds`: 600.0
  - `preview_seconds`: 6.0
- **Scoring**:
  - One score every 3 seconds of video time (a "tick") using frame PTS (video time), never wall-clock time.
  - Scores aggregate the whole 3s window (MOG2 on every frame, YOLO on sample frames inside window). Never score a single snapshot frame.
- **State Machine**:
  - IDLE -> ACTIVE when a tick scores >= 30.
  - While ACTIVE, any tick >= 30 updates last_active and resets quiet timer.
  - CLOSE when ticks stay < 30 for MORE than 90s (quiet duration > 90s, i.e. 31 consecutive low ticks).
  - Dead footage trimming: Final clip = `[first_active_window_start - 10s, last_active_window_end + 10s]`. The 90s quiet window is only the decision delay; no clip ends with dead footage.
  - Pre-roll and post-roll snap OUTWARD to segment boundaries (>= 10s, never less).
  - Gaps < 90s stay inside the same clip; never split on a single low tick.
  - Max duration split: at lowest-score tick if 600s reached, mark next clip "continued".
  - Stream drop: close clip immediately, do not count outage as quiet time.
  - Alerts: Fire 70+ alert at event start, not at clip close.

## 3. False Alarm & Nuisance Suppression (Fans, Hair, Background Noise)
- **Ceiling Fans & Hair Motion**:
  - Spinning fans, waving hair, fluttering curtains, and stationary oscillations must NEVER start a recording or keep a recording open.
  - MOG2 includes stationary periodic oscillation detection (tracks centroid displacement; static spatial spread < 0.018 suppresses motion ratio).
  - Raw motion without a confirmed person/vehicle is HARD CAPPED at score 20 (strictly below threshold 30).
  - Unconfirmed detections (`is_confirmed = False`) are HARD CAPPED at score 20.
  - Loitering/dwell time (`l5`) and extended forensic modifiers (`d4`) require `is_confirmed = True`; they NEVER accumulate on hair, fan, or unconfirmed detections.
  - Stationary tracked persons are protected from background absorption via tracked bounding box injection.

## 4. Single Continuous Daily Footage (Up to 24 Hours)
- In `<storage_dir>/full_footage/<camera_id>/<date_str>/`:
  - Full footage recorded without clipping must be ONE CONTINUOUS WHOLE VIDEO FILE per camera per day: `footage_<date_str>.mp4`.
  - It must NOT be chopped into 60-second tiny chunks.
  - It records continuously whenever the camera is on, up to 24 hours per file.
  - Daily rollover cleanly finalizes that day's file and opens the new day's file.

## 5. Clean User Clips Directory (No Clutter, Videos Only)
- In `<storage_dir>/clips/<camera_id>/<date_str>/`:
  - Must contain ONLY `.mp4` video clips arranged by date.
  - Absolutely NO thumbnails, NO poster images, NO keyframe JPEGs, NO preview MP4 files inside the user's `clips` folders.
  - All companion preview assets (`poster.jpg`, `thumb.jpg`, `preview.mp4`, `keyframe_*.jpg`) must be stored in internal cache: `<storage_dir>/.cache/previews/<camera_id>/<date_str>/<event_id>/`.
  - Clips must never be deleted when a camera is removed; historical clips remain accessible.

## 6. Zero GitHub Pushes
- Never push changes to GitHub (`git push` is strictly forbidden).
