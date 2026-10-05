<USER_REQUEST>
always question each step and took the best one after research

# VYZN — UI and user-flow specification (v1.1)

For the Google Antigravity agent. Read `AGENTS.md` (and `GEMINI.md` if the repo has one) first, then this file in full before planning.
Owner: Utkarsh (founder). Written 29 Sep 2026. Supersedes v1.

**Goal:** replace the current console at localhost:8000 with a calm, truthful, mobile-first product UI. Detection and backend behaviour stay. The front end, its screens and its data contracts change.

---

## 0. Ground rules for the agent

1. Plan before building. Work one phase at a time (section 9). For each phase, produce the implementation-plan artifact and wait for my approval.
2. Inspect the repo first and follow its existing stack. Do not switch front-end frameworks or rewrite the backend unless the plan explains why and I approve.
3. Every number, badge, bar and status on screen must come from real data (section 7). If there is no data source, do not draw it.
4. After each phase, run the app, open it with the browser tool at 390 px and 1440 px wide, screenshot every screen in light and dark themes, and fix what you see before reporting done.
5. Where this spec is silent, choose the simpler option and note it in the walkthrough. Do not invent features.
6. Destructive actions need my approval: deleting rows or files, clearing the test database, dropping tables, removing legacy code that other modules import. Show the exact command, back up first, then wait.
7. Never print, log or display camera passwords, bot tokens, one-time codes or session tokens. Not in URLs on screen, not in the console, not in screenshots.
8. All user-facing text comes from the i18n files. No hard-coded strings in components.

---

## 1. Product truth

**What VYZN does.** It turns 72 hours of CCTV footage into a short list of moments that matter, and sends alerts to Telegram. Where footage is processed and stored (on the shop's hardware or in the cloud) is a deployment fact, not a design claim: see open decision D3. Any UI copy about storage location must be driven by a config value, never hard-coded.

**Primary user.** A small shop owner in India (this build: Maharashtra). Not technical. Checks a phone between customers. Reads English, Hindi or Marathi. Has an existing CCTV system (commonly Hikvision, CP Plus or Dahua) or a spare phone to use as a camera.

**Secondary user.** An evaluator or investor who opens the product and decides in five minutes whether it is real. Anything fake, even in a demo, costs trust.

**The job.** "Tell me when something that matters happens at my shop, show me the few seconds that prove it, and leave me alone the rest of the time."

**Design principles**

1. **Quiet by default.** The interface is neutral grey. Colour appears only when something is abnormal or needs action (the logic of ISA-101 high-performance HMI, used in industrial control rooms).
2. **Truth over theatre.** Real data or nothing. No decorative gauges, no invented statistics.
3. **Video is the hero.** Chrome recedes. Thumbnails and live frames are the most colourful things on screen.
4. **Two visible tiers, and most events stay silent.** Roughly 5% of events alert, 15% are saved for review, 80% are not surfaced at all (the priority distribution used in alarm-management guidance such as EEMUA 191 and ISA-18.2). This is a target for tuning, not a UI element.
5. **Plain words.** Written for a shop owner, not an engineer.
6. **Time is the spine.** The 72-hour retention rule is not a footnote. It is the signature element of the product (section 6.6, the Ribbon).

**The one memorable thing:** the 72-hour Ribbon. Everything else stays disciplined and quiet.

---

## 2. What is wrong with the current console (from the screenshots)

| # | What the screen shows now | Why it hurts | Replace with |
|---|---|---|---|
| 1 | Header packed with CPU, RAM, disk, AI FPS, "FAR 100%", offline buffer | Developer telemetry in the owner's header. "FAR 100%" is unexplained | One status pill in the header. Real telemetry moves to Settings → System health |
| 2 | Marketing hero inside the console: "500+ Indian Retailers", "0.8s Avg Telegram Alert Time", "₹0/mo", badges, WhatsApp and Trial buttons, named testimonials | Unverified claims inside a product UI destroy trust. Named testimonials that are not real are a legal risk | Remove all of it from the app. Marketing lives on a separate website later, with evidence |
| 3 | "Guest Mode / Not signed in" | No authentication | Auth flow, section 6.1 |
| 4 | "Live Threat Index 100/100" and every incident "Tier 4 Critical 100/100" | A scale where everything is maximum carries no information | Two visible tiers (Alert, Review) plus plain-language reasons. Keep the numeric score internal |
| 5 | Threat Incident Stream (right panel) duplicates the Clips gallery | Same content twice, unclear which is the source | Flags on Overview (unreviewed clips) and Clips as the archive. One data source |
| 6 | Dates like "Jan 5, 1970"; mixed formats ("Sep 11" vs "Sep 11, 2026"); "12:00:00 UTC" | A null/zero timestamp bug and inconsistent formatting. The shop is in IST | One formatter, Asia/Kolkata, section 5.7. Null timestamp shows "Time unknown" and logs an error |
| 7 | Timeline with seven evenly spaced red markers | Looks synthetic | The Ribbon, built only from real clip timestamps |
| 8 | Geofence modal: empty camera field, placeholder "Snapshot: cam_corridor", clipped dropdown, "Threat weight 25", "Vertex count", raw X/Y, "Commit Zone to Pipeline" | Engineer language, no real frame, broken layout | Full page "Watch areas" using the latest real frame, plain wording |
| 9 | Left rail with Live, Clips, Search, Add Cam, Layout (struck-through icon), Zones | Overlapping items, unclear icons | Five destinations: Overview, Clips, Areas, Cameras, Settings. Search becomes a filter bar inside Clips |
| 10 | Cyan and violet gradients on near-black, all-caps labels, pills everywhere | Colour used for decoration, so it cannot signal anything | Neutral base, colour reserved for state (section 5) |
| 11 | "Section 65B Certified" | Section 65B was replaced by Section 63 of the Bharatiya Sakshya Adhiniyam on 1 July 2024, and the certificate needs a hash value plus signatures. Software cannot "certify" evidence itself | Remove the claim. Offer an Evidence pack (section 6.3) |
| 12 | "Star / Protected" on incidents | Conflicts with the mandatory 72-hour deletion | Remove. Offer Download evidence pack before expiry (open decision D1) |
| 13 | Every clip is the same person, all critical | Developer test data | Clear the database (with my approval, rule 6). Demo data only through a labelled Demo mode (section 7.4) |
| 14 | "Edge AI Upload Cap: 2.0 Mbps (Zero Cloud Choke)", "4.0 FPS", "DIRECT-SHOW", "LIVE WEBCAM" badges on the live tile | Marketing phrases and driver names on the video | Camera name, and a Live badge only while frames are arriving |
| 15 | 1×1 / 2×2 / 3×3 grid switcher with one camera and an empty dashed tile | Empty tiles advertise nothing | One live camera at a time on Overview (founder's requirement), camera picker beneath |

---

## 3. Founder's mandatory requirements and where they live

| Requirement | Screen |
|---|---|
| Login: email auth → user login → mobile number → Telegram authentication using the mobile number → Dashboard | 6.1 |
| Dashboard immediately shows important flags/events, camera status, live camera view, connected cameras | 6.2 |
| A flag is created when something important happens, and the user can click it to investigate the footage | 6.2, 6.3 |
| Live camera: choose a camera, watch its current live feed, reachable directly from the first page | 6.2 |
| Second page: only important clips, each with camera, date, time, event type, short preview, importance, detected object | 6.3 |
| The UI makes clear why each clip was created (reasons list plus importance) | 6.3 |
| Third page: select the relevant area of the camera view; everything else is ignored (road, cars, passers-by) | 6.4 |
| Add cameras by IP address or local server | 6.5 |
| Footage and clips are kept for 72 hours (mandatory), then deleted automatically | 6.6 |

Full flow:

```
Email ──► Code (= login) ──► Mobile number ──► Telegram link ──► Test alert
                                                                     │
                                                                     ▼
                                                                 OVERVIEW
                          ┌──────────────┬────────────────┬──────────┴───────┐
                          ▼              ▼                ▼                  ▼
                     Flags (open     Live camera      Cameras ──► Add camera ──► Watch area
                     the clip)       (select one)                                 (draw the shop,
                          │                                                        ignore the road)
                          ▼
                    Important clips ──► Clip detail ──► Download evidence pack
                          │
                          ▼
              72-hour retention ──► automatic deletion (logged)
```

---

## 4. Information architecture and vocabulary

**Routes**

```
/login             email
/login/code        6-digit code (this is the login)
/setup/phone       mobile number         (first run only)
/setup/telegram    link Telegram         (first run only)
/overview          dashboard
/clips             important clips
/clips/:id         clip detail (drawer on desktop, full screen on mobile)
/areas             watch areas, camera picker
/areas/:cameraId   draw and edit areas
/cameras           list
/cameras/new       add-camera wizard
/cameras/:id/edit  change name or connection
/settings          account, telegram, shop hours, language, storage and retention, system health
```

**Navigation.** Desktop: left rail, 72 px, icon with label beneath. Mobile: bottom tab bar with Overview, Clips, Areas, Cameras, More (More opens Settings, theme, language, sign out).

**Vocabulary.** Use these words everywhere, in this spelling, in every language file.

| Use | Meaning | Never use |
|---|---|---|
| Flag | A clip that needs the owner's attention and has not been reviewed | Incident, threat, event stream |
| Clip | A saved short video of an important moment | Recording (that is raw footage) |
| Watch area | The part of a camera's view VYZN analyses | Geofence, zone, ROI, polygon, vertex |
| Alert | High importance. Sent to Telegram | Tier 4, critical |
| Review | Medium importance. Saved, not pushed | Tier 2, warning |
| Not an issue | The owner says this flag was wrong | False positive |
| Evidence pack | Export for legal or insurance use | Certified evidence |
| Camera | A connected video source | Stream, device, node |
| Deletes in 41 h | Time left before automatic deletion | Purge, TTL, expired |
| Shop hours | When the shop is open | Schedule mode |

---

## 5. Design system

### 5.1 Concept

"Instrument panel, not casino." Neutral graphite surfaces, thin borders, no glow, no gradients. The camera image and the Ribbon carry the colour. State colour (red, amber, green) appears only when there is a state to report, and reviewed items fade back to grey.

**Plan reviewed against generic defaults before writing this spec.** Rejected: warm cream with a serif and terracotta accent (wrong for a video-first, alarm-driven product); near-black with a neon accent (this is what the current console does); broadsheet hairlines with zero radius; identical rounded cards with the same soft shadow; template chrome (all-caps eyebrows, middle-dot meta strings, spaced-dash labels, arrows on buttons, monospace for ordinary labels). What remains: neutral graphite, one blue for "you can act", three state colours, and one signature element.

### 5.2 Colour tokens

Both themes from the same token names. Follow the system setting by default, with a manual toggle in Settings. The video letterbox is always `--video-bg`, in both themes, because footage reads best on a dark surround. Values below are starting points. **Verify every text/background pair against WCAG 2.2 AA (4.5:1 for body text, 3:1 for large text and UI outlines) with a contrast checker and adjust before shipping.**

```css
:root[data-theme="dark"] {
  --bg-canvas:#14171A;   --bg-surface:#1B1F23;  --bg-raised:#23282D;
  --border:#2E353B;      --border-strong:#3B444B;
  --text-1:#E8EBED;      --text-2:#A6AFB6;      --text-3:#8A939A;
  --action:#2F6FD6;      --action-hover:#3A7BE6; --action-text:#7DB2FF; --on-action:#FFFFFF;
  --action-tint:#182B49;
  --alert:#F0575D;       --alert-bg:#2E1A1C;    --alert-border:#6B2A2E;
  --review:#E5A33B;      --review-bg:#2B2314;   --review-border:#5C4517;
  --ok:#52B788;          --ok-bg:#16261E;
  --video-bg:#0E1113;
  --scrim:rgba(10,12,14,.62);   /* dims the ignored part of a camera view */
  --focus:#7DB2FF;
}
:root[data-theme="light"] {
  --bg-canvas:#F1F3F4;   --bg-surface:#FFFFFF;  --bg-raised:#F7F8F9;
  --border:#D9DEE2;      --border-strong:#BFC6CC;
  --text-1:#14171A;      --text-2:#4B555C;      --text-3:#5D6770;
  --action:#2F6FD6;      --action-hover:#2560C0; --action-text:#2358B0; --on-action:#FFFFFF;
  --action-tint:#E6EFFC;
  --alert:#C62F38;       --alert-bg:#FCECEC;    --alert-border:#F0B9BC;
  --review:#9A6200;      --review-bg:#FFF4DD;   --review-border:#EBCB8A;
  --ok:#186B47;          --ok-bg:#E6F4EC;
  --video-bg:#0E1113;
  --scrim:rgba(20,23,26,.55);
  --focus:#2358B0;
}
```

**Colour rules**

- Normal state is grey. A healthy camera shows a small neutral dot and the word "Online". Never a bright green bar.
- Red means Alert. Amber means Review, and also "camera offline" (a blind spot is advisory; it turns red after 30 minutes offline).
- Blue means "you can act here" (buttons, links, selected items, the outline of a watch area).
- Green appears only as a short confirmation (saved, Telegram connected, test alert delivered).
- Reviewed and Not-an-issue items drop to grey. Colour is for things still waiting.
- No pure black or pure white backgrounds. No gradients, glows or neon.
- Colour never carries meaning alone. Every state also has an icon shape and a text label.
- **Quiet-day test:** a screenshot of Overview on a day with no flags and all cameras online contains no red, amber or green pixels outside the video.

### 5.3 Tier encoding

| Tier | Icon (Lucide) | Label | Colour | Telegram push |
|---|---|---|---|---|
| Alert | `triangle-alert` (filled triangle) | Alert | `--alert` | Yes |
| Review | `eye` in a diamond | Review | `--review` | No |
| Reviewed | `check` | Reviewed | `--text-3` | No |
| Not an issue | `circle-slash` | Not an issue | `--text-3` | No |

### 5.4 Typography

- **Family:** IBM Plex Sans for all UI text, with IBM Plex Sans Devanagari as the Hindi/Marathi companion. Use IBM Plex Mono only for IP addresses and SHA-256 hashes.
- Self-host. Bundle the fonts from npm (`@fontsource/ibm-plex-sans`, `@fontsource/ibm-plex-sans-devanagari`, `@fontsource/ibm-plex-mono`); the product must work on a shop network with no internet dependency for fonts. Subset Latin and Devanagari, `font-display: swap`, preload Latin 400, 500 and 600.
- **Scale:** 12 / 14 / 16 / 20 / 28 px. Page title 20/600, section heading 16/600, body 14 (desktop) or 16 (mobile), caption 12, sign-in headings 28/600. Weights 400, 500, 600 only.
- Sentence case everywhere. No all-caps labels, no letter-spaced eyebrows above headings.
- Times and counts use tabular numerals: `font-variant-numeric: tabular-nums`.
- Line length under 75 characters. Line height 1.5 for body, 1.25 for headings. Devanagari gets +0.1 line height.
- Wordmark: "VYZN" in Plex Sans 600, +0.02em tracking, no logo symbol in v1. Favicon: a white "V" on a `--action` rounded square.

### 5.5 Shape, spacing, elevation

- 4 px spacing base: 4, 8, 12, 16, 24, 32, 48.
- Radius: video frames 4 px, controls 6 px, panels 8 px, chips fully round. Do not put one radius on everything.
- Depth comes from surface colour steps and 1 px borders. No drop shadows in dark theme. In light theme, one very soft shadow on drawers only.
- Desktop max content width 1440 px. Mobile base width 360 px, 16 px gutters.
- Touch targets at least 44 × 44 px on mobile.
- Breakpoints: 0–767 mobile, 768–1023 tablet (bottom tab bar, two columns), 1024+ desktop (left rail).

### 5.6 Motion

- Allowed: state-change transitions of 120–180 ms; skeleton loaders; the live dot (one soft pulse every 2 s, only while frames are arriving); a single 600 ms highlight when a new flag arrives; drawer open/close.
- Not allowed: entrance animations on page load, hover lift on every card, animated gradients, scanning-line effects, count-up numbers.
- Respect `prefers-reduced-motion`: replace movement with instant state changes.

### 5.7 Time and language

- Store UTC epoch milliseconds. Render in the shop timezone (default `Asia/Kolkata`) with a 12-hour clock and lower-case am/pm.
- One `formatWhen()` helper: under 1 hour "12 min ago"; same day "Today, 9:34 pm"; previous day "Yesterday, 3:50 am"; older "Sun 27 Sep, 9:57 pm". Exact time with seconds on hover or in detail views. One `formatLeft()` helper for time left: "41 h", "5 h 20 min", "12 min".
- A null, zero or pre-2020 timestamp renders "Time unknown" and writes a console error. Never render 1970.
- All strings live in i18n files from day one. Ship English first. Hindi and Marathi files are added in Phase 8. Leave room for longer Devanagari strings in buttons (no fixed-width buttons).

### 5.8 Icons and imagery

- Lucide icons, 1.5 px stroke, 20 px default. No emoji as icons in the web UI (emoji are fine inside Telegram messages).
- No stock photos, no illustrations of cameras or shields. Empty states use a small line icon and one sentence.
- Video and image frames: 4 px radius, 1 px inner border, no glow.

### 5.9 Accessibility floor

WCAG 2.2 AA. Visible keyboard focus (2 px `--focus` outline, 2 px offset). Full keyboard operation of the clip player and area editor. Labels on every input. Live regions announce new flags. Works at 200% zoom.

### 5.10 Component inventory

Build these once in Phase 1, with every state (default, hover, focus, active, disabled, loading, error) shown on a dev-only `/_design` page.

| Component | Notes |
|---|---|
| Button | Primary (blue fill), secondary (border), quiet (text), danger (red text on tint, used only for delete). 40 px desktop, 44 px mobile |
| Field, Select, Segmented | Label above, helper text below, error text replaces helper text with an icon |
| StatusDot + label | Neutral, amber, red. Never colour alone |
| TierBadge | Icon plus word, from 5.3 |
| CameraTile | 16:9 thumbnail, name, status line, area summary |
| FlagRow | Thumbnail 96×54, tier badge, headline, camera and time, two actions |
| ClipCard | Section 6.3 |
| Player | Live and clip modes share one shell. Skeleton, playing, stalled, offline states |
| Drawer / Sheet | Right drawer (desktop), full-screen sheet (mobile) with focus trap and Esc to close |
| Toast | Bottom-left desktop, above tab bar on mobile. Supports an Undo action for 10 s |
| Ribbon | Section 6.6 |
| AreaEditor | Section 6.4 |
| Stepper | Setup only: "Step 2 of 3" with labels. The one place numbered markers are correct, because the content is a sequence |
| EmptyState | 20 px line icon, one sentence, one button |
| Skeleton | Matches the final layout of each component; no spinners over video |

---

## 6. Screens

### 6.0 App shell

```
Desktop (1024 px and wider)
┌──────┬───────────────────────────────────────────────────────────┐
│ VYZN │ Overview                       ● All 3 cameras online   UK │
│      ├───────────────────────────────────────────────────────────┤
│ Over │                                                           │
│ Clip │                        page content                       │
│ Area │                                                           │
│ Cams │                                                           │
│ Sett │                                                           │
└──────┴───────────────────────────────────────────────────────────┘

Mobile (390 px)
┌──────────────────────────┐
│ Overview     ● 3 online  │
├──────────────────────────┤
│                          │
│        page content      │
│                          │
├──────────────────────────┤
│ Over  Clips Areas Cams ⋯ │
└──────────────────────────┘
```

**Header status pill.** One pill, computed from real data, first match wins. Clicking it opens a popover listing each camera with its last-seen time, and Telegram status.

| Priority | Condition | Text | Style |
|---|---|---|---|
| 1 | Telegram not linked or bot blocked | Alerts are off. Connect Telegram | Amber, triangle icon |
| 2 | Any camera offline for more than 30 min | 1 camera offline | Red, triangle icon |
| 3 | Any camera offline | 1 of 3 cameras offline | Amber, diamond icon |
| 4 | No cameras added | No cameras yet | Neutral |
| 5 | Otherwise | All 3 cameras online | Neutral dot |

**Account menu.** Initials in a 32 px circle: Settings, Theme (System, Light, Dark), Sign out.

**Camera offline notice on Telegram.** When a camera has been offline for 10 minutes, send one plain message ("Shop entrance went offline at 9:12 pm") and one when it returns. A blind camera is a risk the owner should hear about.

---

### 6.1 Sign-in and setup

This is the founder's mandatory first page. Email proves who the owner is and is the login. The mobile number is then linked to a Telegram account, which becomes the alert channel.

```
Email ──► 6-digit code ──► Mobile number ──► Open Telegram ──► Share number ──► Connected ──► Overview
 (S1)        (S2)             (S3)               (S4, on the same screen)                      
```

Returning users skip the steps already done:

| After the code is accepted | Go to |
|---|---|
| No mobile number saved | `/setup/phone` |
| Mobile number saved, Telegram not linked | `/setup/telegram` |
| Both done | `/overview` |

**Layout.** No sidebar, no header status pill. A 400 px column centred on `--bg-canvas`, wordmark at top-left of the page, nothing else competing. No marketing copy, no hero image. One quiet line under the card: "VYZN keeps footage and clips for 72 hours, then deletes them." (This is a fixed product rule, so it is always true.) Setup screens show the Stepper: "Step 2 of 3", labels Email, Mobile number, Telegram, with Email shown as done.

**S1 `/login`**

```
 VYZN

   Sign in to VYZN
   We'll email you a 6-digit code. No password needed.

   Email
   [ name@shop.in                     ]
   [ Send code ]

   VYZN keeps footage and clips for 72 hours, then deletes them.
```

- Autofocus the email field. `type="email"`, `autocomplete="email"`, `inputmode="email"`.
- Error (invalid): "Enter a valid email address, like name@shop.in."
- Same screen for new and returning owners. Do not reveal whether an account exists.

**S2 `/login/code`**

```
   Check your email
   We sent a 6-digit code to n••••@gmail.com. It works for 10 minutes.

   6-digit code
   [ 4  8  1  0  9  2 ]
   Send a new code in 24 s          Use a different email
```

- One real `<input autocomplete="one-time-code" inputmode="numeric" maxlength="6">` styled as six cells, so paste and autofill work. Submit automatically on the sixth digit.
- Wrong code: "That code isn't right. Check the newest email, or send a new code."
- Expired: "That code has expired. Send a new code."
- Too many tries (5): "Too many tries. Wait 15 minutes, then send a new code."
- Resend is disabled for 30 s with a visible countdown.
- If the repo uses Supabase Auth, use email OTP (`signInWithOtp` / `verifyOtp`). Otherwise implement the same behaviour. Session in an httpOnly cookie.

**S3 `/setup/phone`**

```
   Step 2 of 3
   Add your mobile number
   VYZN uses this number to connect your Telegram account, where your alerts arrive. VYZN does not send SMS to it.

   Mobile number
   [ +91 ▾ ] [ 98765 43210        ]
   [ Continue ]
```

- Default country +91. For +91: exactly 10 digits, first digit 6 to 9. Store as E.164.
- Error: "Enter a 10-digit mobile number starting with 6, 7, 8 or 9."

**S4 `/setup/telegram`**

```
   Step 3 of 3
   Connect Telegram
   Alerts arrive in Telegram. Connect the account that uses +91 98••• ••210.

   1  Open VYZN on Telegram          [ Open Telegram ]      ┌────┐
   2  Tap Start, then tap Share my number                     │ QR │  (desktop only)
   3  Come back here. This page updates by itself.            └────┘

   Waiting for Telegram…                                   Get a new link
```

States:

| State | What shows |
|---|---|
| Waiting | The three steps and "Waiting for Telegram…" (polite live region). Poll every 2 s or use SSE, for up to 10 min |
| Connected | Green check and "Telegram connected." Below: **Send a test alert** (secondary) and **Go to Overview** (primary) |
| Test sent | "Test alert delivered in 1.2 s. Check Telegram." The number is the measured delivery time |
| Number mismatch | "The number shared in Telegram doesn't match +91 98••• ••210. Share the number of this Telegram account, or change your mobile number." Buttons: Try again, Change number |
| Link expired | "This link has expired. Get a new link." |
| Bot blocked or Telegram down | "We couldn't reach Telegram. Try again in a minute." |

On mobile hide the QR; the button opens the Telegram app directly. Desktop shows both. The QR encodes the same deep link.

**How the Telegram link works (backend contract).** Telegram does not give a website the user's phone number when they log in. The reliable method is to make the bot ask for the number with a contact-sharing button (`request_contact`, which only works in private chats) and compare it to the number typed on the website.

1. `POST /api/telegram/link {phoneE164}` creates a token: 128-bit random, single use, expires in 10 minutes, stored hashed, bound to the signed-in user. Returns `https://t.me/<TELEGRAM_BOT_USERNAME>?start=<token>`.
2. The bot receives `/start <token>`, validates it, remembers `chat_id` for that pending link, and replies with a reply keyboard containing one button, "Share my number", with `request_contact: true`, `one_time_keyboard: true`, `resize_keyboard: true`.
3. The bot receives the contact message. Accept it only if `contact.user_id == message.from.id` (otherwise someone forwarded another person's contact) and the normalised `contact.phone_number` (Telegram may omit the "+") equals the phone on the VYZN account.
4. On success: store `chat_id`, `telegram_user_id`, optional `@username`, `linked_at`. Remove the keyboard. Reply "Connected. VYZN alerts will arrive here."
5. The website receives the event (SSE or polling) and moves to Connected.
6. `POST /api/telegram/test` sends a message that says it is a test (no fake clip, no fake thumbnail), records the send time and Telegram's response time, and returns `latencyMs`.
7. If Telegram returns 403 (user blocked the bot) or the user sends `/stop`, set the link to `blocked` and show the header pill priority 1.
8. Rate-limit token creation (5 per hour per user). Never reveal whether a phone number is registered to a different account.

Whether Telegram can be skipped on first run is open decision D4. The default in this spec: it cannot, because alerts are the product.

---

### 6.2 Overview (first page after sign-in)

The founder's rule: the first main page immediately shows important flags, the live camera, camera status and connected cameras. Reading order and tab order start with Flags, then Live, then Cameras, then the Ribbon.

```
Desktop 1440 px
┌──────┬───────────────────────────────────────────┬────────────────────┐
│ VYZN │ Overview                  ● All 3 cameras online            UK │
│      ├───────────────────────────────────────────┬────────────────────┤
│ Over │ Live camera   [Shop entrance ▾]           │ Flags · 2 waiting  │
│ Clip │ ┌───────────────────────────────────────┐ │ ┌────────────────┐ │
│ Area │ │ ● Live                        ⛶  ⬒  │ │ │▲ Alert  9:34 pm│ │
│ Cams │ │                                       │ │ │[img] Person    │ │
│ Sett │ │            video 16:9                 │ │ │stayed 63 s at  │ │
│      │ │       (watch area outlined)           │ │ │Cash counter    │ │
│      │ └───────────────────────────────────────┘ │ │[Open][Not an   │ │
│      │ Cameras                                   │ │        issue]  │ │
│      │ [Shop entrance ●] [Counter ●] [Godown ◆]  │ ├────────────────┤ │
│      │                                           │ │◆ Review 8:02 pm│ │
│      ├───────────────────────────────────────────┴─┤ ...            │ │
│      │ Last 72 hours                               │ See all in Clips│
│      │ ▏  ▏▏   ▏      ▎      ▏   ▏▏      ▎   now   │                │
│      │ 72 h ago        48 h        24 h            │                │
└──────┴─────────────────────────────────────────────┴────────────────┘

Mobile 390 px, top to bottom
  Flags (up to 3, then "See all in Clips")
  Live camera (16:9) + camera chips
  Last 72 hours (Ribbon)
  Cameras (list)
```

Column widths (desktop): flags column fixed 360 px, main column fluid, 24 px gap. The Ribbon spans the full content width under both columns.

**Flags panel**

- A flag is a clip with status `unreviewed`. Order: Alert first, then Review, newest first within each. Show up to 5 on desktop, 3 on mobile. Footer link: "See all 7 in Clips".
- Each row (FlagRow): thumbnail with duration, tier badge (icon and word), headline (section 6.3 headline table), camera and area, `formatWhen`, and two actions: **Open** (primary) and **Not an issue** (quiet). Clicking anywhere else on the row also opens the clip.
- **Open** opens Clip detail as a drawer (desktop) or full screen (mobile), with the player starting 3 seconds before the trigger moment.
- Opening a flag does not mark it reviewed. The owner does that in the drawer ("Mark as reviewed") so that nothing disappears by accident.
- New flag arrives (SSE): it slides into the top of the list with a single 600 ms highlight, and an `aria-live="polite"` region announces "New alert: Person stayed 63 seconds at Cash counter". No sound in v1.
- Expiry warning: if any unreviewed flag has under 12 hours left, show one line above the footer, amber, with clock icon: "2 flags will be deleted in the next 12 hours. Download an evidence pack to keep a copy."
- Empty state (all quiet): "Nothing needs your attention." If the pipeline exposes a daily count, add the truthful second line "VYZN checked 1,240 moments in the last 24 hours and saved 3 clips." Show that line only if `stats.moments_checked_24h` exists (section 7.1). No illustration.
- No cameras yet: hide the panel and show the guided empty state below.

**Live camera**

- Header row: "Live camera" and a camera select (segmented control up to 4 cameras, dropdown beyond that).
- Player (16:9, `--video-bg` letterbox). Only the selected camera streams; use the camera's sub-stream for the tile and the main stream in full screen. Other camera tiles use a snapshot that refreshes every 15 s.
- Overlay, top-left: camera name and Live badge (dot and the word "Live"). Overlay, top-right: full screen, save a picture. A "Show watch areas" toggle outlines the camera's watch areas in `--action` (dim outside, as in 6.4). No FPS, driver or bitrate text on the video.

| State | What shows |
|---|---|
| Connecting | Skeleton in the player frame, text "Connecting…" |
| Live | Video, Live badge with soft pulse (only while frames arrive) |
| Stalled (no frame for 5 s) | Last frame dimmed, badge changes to "Reconnecting…" |
| Offline (no frame for 15 s or more) | Last stored picture dimmed, banner "Offline since 9:12 pm", buttons **Try again** and **Why is it offline?** (opens troubleshooting list) |
| No cameras | Guided empty state |

**Cameras strip.** One CameraTile per camera: latest picture, name, status line ("Online" or "Offline since 9:12 pm"), and a watch-area summary ("Watching 2 areas" or "Watching the whole view"). A camera with no area shows the hint "Choose the area to watch to get fewer false flags" as a link to `/areas/:id`. Selecting a tile switches the live player. On mobile this is a vertical list, and the live player sits above it.

**Guided empty state (no cameras).**

```
   Add your first camera
   Connect a CCTV camera, a recorder, or a spare phone.
   [ Add a camera ]
```

The rest of Overview (Ribbon, Flags) is hidden until a camera exists, so no empty bars are drawn.

---

### 6.3 Clips and clip detail

The second page shows only important clips. It never shows raw footage.

```
72 h of footage ─► AI analysis ─► important moments ─► short clips ─► this page
```

```
Desktop
┌─────────────────────────────────────────────────────────────────────┐
│ Important clips                          12 clips in the last 72 h   │
│ Camera [All ▾]  Importance [All|Alert|Review]  Status [Unreviewed ▾] │
│ What [All ▾]    When [Last 72 h ▾]                       Clear filters│
├─────────────────────────────────────────────────────────────────────┤
│ Ribbon (drag to choose a time range)                                 │
├─────────────────────────────────────────────────────────────────────┤
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                  │
│ │ClipCard  │ │ClipCard  │ │ClipCard  │ │ClipCard  │   4 columns      │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘   (3 tablet,     │
│                                                        1 mobile)     │
└─────────────────────────────────────────────────────────────────────┘
```

**Filters (this replaces the old Search page).** Camera; Importance (All, Alert, Review); Status (All, Unreviewed, Reviewed, Not an issue), default Unreviewed; What (detected object: only classes the detector really outputs, for example Person, Vehicle); When (Last 6 h, Last 24 h, Last 72 h, or a range drawn on the Ribbon). Filters live in the URL query string so a filtered view can be shared or reloaded. On mobile the filters collapse into one "Filters" button that opens a sheet. There is no free-text search and no clothing-colour filter in v1 (decision D6).

**ClipCard**

```
┌────────────────────────────┐
│ [▲ Alert]             0:24 │   tier badge top-left, duration bottom-right
│                            │
│    thumbnail (16:9)        │   on hover or focus (desktop): 3-second muted
│                            │   looping preview; on mobile: still + play
├────────────────────────────┤   button, preview loads on tap
│ Person stayed 63 seconds   │   headline (event type in plain words)
│ Shop entrance · Cash counter│  camera · watch area
│ Today, 9:34 pm             │   formatWhen
│ Deletes in 41 h            │   formatLeft, text-3, clock icon
└────────────────────────────┘
```

- Reviewed and Not-an-issue cards show the grey status icon and word instead of the tier colour.
- The whole card is one button (opens the drawer). Keep the tab order simple: one stop per card.
- Show at most one reason line on the card. The full reasons list is in the drawer.

**Headline table.** The front end builds headlines from `clip.reasons[0]` (the primary reason, chosen by the backend) using i18n templates. Do not compose headlines from other fields.

| Reason code | Headline template | Source of truth |
|---|---|---|
| `entered_restricted_area` | Person entered {area} | Watch area with response "alert", entry event |
| `stayed_in_area` | Person stayed {duration} in {area} | Dwell time at or above the area's minimum stay |
| `outside_shop_hours` | Movement outside shop hours | Shop hours from Settings |
| `person_detected` | Person in {area} | Detector class person, confidence at or above threshold |
| `movement` | Movement in {area} | Motion gate inside the watch area |

If the pipeline produces an event type not in this table, list it in the plan and ask me before inventing a headline.

**Clip detail.** Right drawer 560 px on desktop, full-screen sheet on mobile. URL `/clips/:id`; Esc or back closes it.

```
┌──────────────────────────────────────────────┐
│ Clip 23                     ‹ ›         ✕    │
├──────────────────────────────────────────────┤
│ ┌──────────────────────────────────────────┐ │
│ │               player 16:9                │ │
│ └──────────────────────────────────────────┘ │
│  ▶  0:03 ─────●───────────── 0:24   1×  ⛶   │
│  [ ] Show what VYZN saw                      │
│                                              │
│ ▲ Alert                                      │
│ Why this clip was saved                      │
│  ✓ Person detected · 88% sure                │
│  ✓ Movement in Cash counter                  │
│  ✓ Stayed 63 seconds                         │
│                                              │
│ Camera        Shop entrance                  │
│ Watch area    Cash counter                   │
│ When          Sun 27 Sep, 9:34:12 pm         │
│ Length        24 s                           │
│ Detected      Person                         │
│ Deletes       Tue 29 Sep, 9:34 pm (in 41 h)  │
│                                              │
│ ▸ Technical details                          │
├──────────────────────────────────────────────┤
│ [ Mark as reviewed ] [ Not an issue ]        │
│ [ Send to my Telegram ] [ Evidence pack ]    │
└──────────────────────────────────────────────┘
```

- **Player.** Starts 3 s before the trigger. The scrubber has a small marker at the trigger moment. Speeds 0.5×, 1×, 2×. Frame step with `,` and `.` when paused. "Show what VYZN saw" draws the detection box and the watch-area outline over the video (off by default). The clip file is un-annotated; the overlay is drawn in the UI from stored boxes.
- **Why this clip was saved.** The importance line (icon, word, colour) then a checklist. One line per entry in `clip.reasons`, each with a check icon, a plain-language sentence, and the real measurement where one exists ("88% sure", "63 seconds"). This directly answers the founder's "make it clear why a clip was created".
- **Facts.** Definition list. Exact time with seconds here (not on the card). Delete time shown as date and time and `formatLeft`.
- **Technical details** (collapsed by default). Detector name and version, per-object confidence, the internal score, first and last frame times in UTC, file size, SHA-256 (Plex Mono, selectable, with a Copy button). This is where evaluators can see the system is real; owners never need it.
- **Actions.**
  - **Mark as reviewed** (primary). Moves the clip out of Flags. Toast: "Marked as reviewed. Undo" (10 s).
  - **Not an issue.** Opens a small popover: "What was it?" with four buttons (It was me or my staff, A customer, Light, shadow or reflection, Something else) and Skip. Store the answer as `feedback.reason`. Toast with Undo.
  - **Send to my Telegram.** Sends the clip link and thumbnail to the linked chat. Result toast: "Sent to Telegram."
  - **Evidence pack.** Downloads a ZIP (below).
- **Navigation.** Previous and next arrows step through the currently filtered list. Keyboard: `j` and `k` next and previous clip, `Space` play or pause, `r` reviewed, `n` not an issue, `Esc` close.
- **Expired while open.** If the clip is deleted while the drawer is open: replace the player with "This clip was deleted after 72 hours." and disable actions.

**Evidence pack** (`VYZN-clip-023-2026-09-27.zip`)

| File | Contents |
|---|---|
| `clip-023.mp4` | The original clip, un-annotated |
| `summary.pdf` | One page: shop name, camera, times in IST and UTC, reasons, detector name and version, file name, SHA-256, time generated |
| `metadata.json` | Same facts, machine-readable |
| `HASH.txt` | SHA-256 of the clip file |
| `README.txt` | What the pack is and is not (below) |

`README.txt` text: "This pack was produced by VYZN. VYZN does not certify evidence. In Indian courts, electronic records are presented with a certificate under Section 63 of the Bharatiya Sakshya Adhiniyam, 2023, which replaced Section 65B of the Evidence Act on 1 July 2024. The certificate carries the hash value of the file and is signed by the person in charge of the device and, where the law requires it, an expert. Ask a lawyer what your case needs. VYZN deletes its own copy 72 hours after the moment was recorded; the copy in this pack is yours to keep."

The button label and the download name say "Evidence pack" only. Never "certified", "court-ready" or "legally admissible".

**States**

| State | Copy |
|---|---|
| No clips yet | "No clips yet. VYZN saves a clip when something happens inside a watch area." Button: Choose the area to watch |
| Filters match nothing | "No clips match these filters." Button: Clear filters |
| Loading | Card skeletons in the final grid layout |
| Error | "Couldn't load clips. Check your connection and try again." Button: Try again |

---

### 6.4 Watch areas

The third page. The owner chooses the part of the camera's view that matters. Everything outside is ignored: no analysis, no clips, no alerts.

The founder's example (Marathi, translated): "My shop is inside the camera's view, but the camera also sees the road. I'll select only the shop, and motion anywhere else won't be looked at." The design must make this obvious at a glance: **bright means watched, dimmed means ignored.**

**`/areas` (picker).** A list of cameras, each a CameraTile with "Watching 2 areas" or "Watching the whole view", and an **Edit areas** button. One camera: skip the picker and go straight to its editor.

**`/areas/:cameraId` (editor)**

```
Desktop
┌──────────────────────────────────────────────┬──────────────────────────┐
│ Shop entrance · Watch areas         [Update picture]                     │
├──────────────────────────────────────────────┼──────────────────────────┤
│ ┌──────────────────────────────────────────┐ │ Areas on this camera     │
│ │░░░░░░░░░░░░░░ dimmed = ignored ░░░░░░░░░░░│ │ ▲ Cash counter    ⋯      │
│ │░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│ │ ◆ Shop floor      ⋯      │
│ │░░░░┌──────────────────────┐░░░░░░░░░░░░░░░│ │ [ + Add area ]           │
│ │░░░░│ Cash counter         │░░░░░░░░░░░░░░░│ │                          │
│ │░░░░│  bright = watched    │░░░░░░░░░░░░░░░│ │ Cash counter             │
│ │░░░░└──────────────────────┘░░░░░░░░░░░░░░░│ │ Name [ Cash counter    ] │
│ │░░░░░░░░░ road, cars, people passing ░░░░░░│ │ When someone is here     │
│ └──────────────────────────────────────────┘ │  (•) Send me an alert    │
│ Draw: [Rectangle] [Free shape]   Undo   Clear│  ( ) Save a clip to review│
│ Picture from 9:41 pm                         │ Only flag if they stay   │
│                                              │  [Right away|10 s|30 s|60 s]│
│                                              │ Watch this area          │
│                                              │  [All the time|Outside    │
│                                              │   shop hours]            │
│                                              │ [ Save areas ]           │
└──────────────────────────────────────────────┴──────────────────────────┘
```

On mobile the picture is full width and the panel becomes a bottom sheet with a drag handle.

**Semantics (write these into the UI text)**

- A camera with no areas: VYZN watches the whole view. Show at the top: "Watching the whole view. Draw an area to ignore everything else."
- A camera with one or more areas: VYZN watches only inside them. Everything else is ignored.
- Changes apply to new footage from the moment of saving. Clips already saved are not changed. Say so under the Save button.
- Maximum 5 areas per camera.

**Drawing**

- Uses the latest real frame from the camera (the snapshot endpoint). **Update picture** takes a fresh one. If the camera is offline, show the last stored picture with "Picture from 9:12 pm. The camera is offline." and allow editing. If no picture has ever been captured: empty state "Connect the camera to draw its areas."
- Default tool is **Rectangle** (drag). **Free shape** adds a point per tap or click; finish by tapping the first point or pressing Enter; minimum 3 points.
- Drag a corner or point to reshape. Drag the midpoint of an edge to add a point. Drag inside the shape to move it. Delete removes the selected point when more than 3 remain. Esc cancels drawing. Undo and Clear are always visible.
- Touch: handles have a 44 px hit area with a 12 px visible dot. No pinch zoom in v1.
- Keyboard: Tab to a handle, arrow keys move it by 1% of the frame width or height (Shift: 5%).
- Rendering: the dim layer is the full frame minus every area (SVG even-odd path) filled with `--scrim`. Each area has a 2 px `--action` outline and a name label in a small chip at its top-left. The selected area's handles are white with a `--action` ring.
- Show a legend under the picture: "Bright: watched. Dimmed: ignored."

**Properties per area (plain words)**

| Field | Control | Maps to |
|---|---|---|
| Name | Text field, default "Area 1" (offer: Shop floor, Cash counter, Door, Godown) | `name` |
| When someone is here | Radio: Send me an alert / Save a clip to review | `response`: `alert` / `review` |
| Only flag if they stay | Segmented: Right away, 10 s, 30 s, 60 s | `minStaySeconds`: 0, 10, 30, 60 |
| Watch this area | Segmented: All the time, Outside shop hours | `schedule`: `always` / `outside_shop_hours`. If shop hours are not set, the second option is disabled with the link "Set shop hours" |

Removed on purpose: threat weight, vertex count, X/Y readout, "Commit Zone to Pipeline". The internal score weighting is derived from `response` by the backend.

**After saving.** Toast: "Areas saved. Applies to new footage." If the backend counts ignored events, show on the picker card: "Since you set this area, 136 moments outside it were ignored." Show that line only if the count is real (section 7.1).

**Backend notes for the agent** (confirm against the current pipeline and tell me where it differs):

- Store polygons as normalised coordinates (0 to 1) of the full frame, independent of stream resolution, versioned per camera.
- Apply the mask before detection: mask the motion-gating step and run the detector only on the bounding box of the areas, to save CPU.
- Decide "inside an area" from the bottom-centre point of the person's box (where they stand), not the box centre.
- Log a count of moments dropped because they were outside every area (feeds the line above).

---

### 6.5 Cameras and the add-camera wizard

**`/cameras`.** A grid of CameraTiles (list on mobile) and a primary **Add camera** button. Each tile: latest picture, name, status ("Online" or "Offline since 9:12 pm"), source line ("IP camera · 192.168.1.64" with the address in Plex Mono), video facts measured from the stream ("1920×1080 · 15 fps"), and watch-area summary. Menu (⋯): Rename, Edit connection, Choose watch areas, Remove.

**Remove camera** is destructive: confirm dialog with the text "Remove Shop entrance? Its saved footage and clips will be deleted now." and a red **Remove and delete** button. This is the one place a user can delete data early; log it in the deletion log with reason "camera removed".

**`/cameras/new`.** A three-step page, not a modal.

```
Step 1: How is the camera connected?
┌──────────────────────────────────────────────────────────┐
│ IP camera or recorder                                     │
│ CCTV camera, DVR or NVR. You know its IP address.         │
├──────────────────────────────────────────────────────────┤
│ Find on my network                                        │
│ VYZN looks for cameras and recorders on your shop's       │
│ network (the local server). Works when this computer is   │
│ on the same Wi-Fi or network as the cameras.              │
├──────────────────────────────────────────────────────────┤
│ Phone or webcam                                           │
│ Use a spare phone, or this computer's webcam, as a camera.│
└──────────────────────────────────────────────────────────┘
```

**Step 2, by path**

*IP camera or recorder (by IP address)*

| Field | Notes |
|---|---|
| IP address | Plex Mono, validates IPv4 |
| Port | Default 554 |
| Username, Password | Password field with show/hide. Never echoed back after saving |
| Brand | Hikvision, CP Plus, Dahua, Other. Builds the stream path from Appendix C |
| Channel | Shown for recorders (1 to 32), default 1 |
| Advanced: paste a full stream address | Replaces the fields above. Accepts `rtsp://` and `http(s)://` |

Show a live preview of the address being built with the password masked ("rtsp://admin:••••@192.168.1.64:554/…").

*Find on my network (local server)*

ONVIF discovery. Show a scanning state ("Looking for cameras on your network…"), then a list of found devices: brand and model if reported, IP address, and a **Select** button. Then ask for username and password. If nothing is found after 15 s: "No cameras found. Check that this computer is on the same network as your cameras, or add one by IP address." with both actions. Include the phrase for owners who run a stream server or recorder: the Advanced paste-address option above covers it.

*Phone or webcam*

Two choices. **Phone:** three plain steps (install the free "IP Webcam" app on Android or "DroidCam" on iOS or Android; connect the phone to the shop Wi-Fi and tap Start server; paste the address shown on the phone, for example `http://192.168.1.15:8080/video`), one field for the address. **This computer's webcam:** a single button, shown only when a webcam is detected; helper text "Good for trying VYZN. Use a CCTV camera for the shop."

**Test connection.** Every path ends with **Test connection**. It fetches a real frame and reads the stream properties.

| Result | What shows |
|---|---|
| Success | The captured picture, "We can see the picture", measured size and frame rate, and a **Continue** button |
| Wrong username or password (401) | "The camera rejected the username or password. Check them and try again." |
| Cannot reach the address (timeout) | "Couldn't reach 192.168.1.64. Check that the camera is on and on the same network as this computer." |
| Port closed or refused | "The camera didn't answer on port 554. Check the port, or try 8554." |
| Wrong path or channel (404) | "The camera answered, but not for this channel. Try a different channel or brand." |
| Stream opens but no picture (codec) | "The camera's video format isn't supported. In the camera settings, switch the stream to H.264." (Add H.265 only if the pipeline decodes it.) |

Errors state what happened and what to do next, never "Failed" alone.

**Step 3, name it.** Name (default "Camera 1"; suggestions: Shop entrance, Cash counter, Godown, Back door). Save. Success screen:

```
   Shop entrance is connected.
   Now choose the part of the picture VYZN should watch.
   [ Choose the area to watch ]        Add another camera
```

The primary button goes to `/areas/:id`. This is the founder's flow: camera added, then area selection.

**Security rules.** Encrypt camera credentials at rest. Never send the password back to the browser. Never log full stream addresses with credentials. Only the server talks to the camera; the browser never receives the camera's RTSP address.

---

### 6.6 The 72-hour rule and the Ribbon

The founder's rule: footage and clips are kept for 72 hours, then deleted automatically. It is mandatory and not configurable. The UI makes the rule visible in four places and never hides it in a footnote.

**The rule, precisely**

- `expires_at = recorded_at + 72 h`, where `recorded_at` is when the moment happened, not when the clip was generated. Raw footage segments and the clips cut from them expire on the same clock.
- A cleanup job runs at least every 15 minutes. It hard-deletes video files and thumbnails for everything past `expires_at`, and removes the database pointers to them.
- For every deletion, keep a metadata-only record in a deletion log (clip number, camera, time of the moment, tier, review status, time deleted, reason `retention` or `camera removed`). No video, no thumbnails, no faces in the log.
- There is no Star, Protect or Keep. The way to keep a clip is to download an Evidence pack before it expires (decision D1).
- Test: freeze time, insert footage at 71 h 50 min and 72 h 10 min old, run the job, assert that only the older item is gone and the log has one entry. Also assert that nothing older than 72 h 15 min exists in storage after a run.

**Where the rule shows in the UI**

1. The Ribbon on Overview and Clips (below).
2. "Deletes in 41 h" on every ClipCard and in the drawer.
3. The expiry line in the Flags panel when unreviewed flags have under 12 h left.
4. Settings → Storage and retention (6.7).

**The Ribbon** is the product's signature element and the only expressive component. It is the last 72 hours as a single horizontal strip. Time flows left to right; the left edge is where footage is deleted, the right edge is now.

```
 Last 72 hours                                        2 alerts · 5 to review
 ┌ ─ ─ ─ ┐
 ┆deleting┆  ▏      ▎▎     ▏          ▎               ▏   ▏▏      ▎    ▏
 ┆ soon  ┆━━━━━━━━━━━━━━━━━━━━━━━━━━┅┅┅┅┅━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 └ ─ ─ ─ ┘
 72 h ago          Sat          Sun ▏          Mon           Tue          Now
                                                gap: Godown camera offline
```

| Part | Meaning | Data |
|---|---|---|
| Track | Footage exists for this period (filled `--bg-raised` with 1 px border) | Recording coverage segments |
| Gap | No footage (dotted outline, no fill). Tooltip: "No footage from 2:10 am to 2:40 am. Godown camera was offline." | Gaps between coverage segments, joined to camera offline periods |
| Tick, Alert | 2 px wide, full height, `--alert`, small filled triangle above | Clips with tier alert and status unreviewed |
| Tick, Review | 2 px wide, 60% height, `--review`, small diamond above | Clips with tier review and status unreviewed |
| Tick, done | 1 px wide, 40% height, `--text-3` | Reviewed and Not-an-issue clips |
| Deleting soon | Leftmost 6 h: dashed top border and the label "Deleting soon" | Fixed from the 72 h rule |
| Axis | "72 h ago", "48 h", "24 h", "Now" plus day names at each midnight in IST | Computed |
| Summary (top-right) | "2 alerts · 5 to review" counts of unreviewed by tier | Clips |

Behaviour:

- Position: `x = (t − (now − 72 h)) / 72 h × width`. Recompute every 60 s in one step (do not animate a continuous crawl).
- Clusters: ticks closer than 6 px merge into one tick with a small count; its tier is the highest inside it. Click or Enter on a cluster opens the first clip in the group and the drawer shows "1 of 4 nearby" with previous and next.
- Hover or focus a tick: tooltip with `formatWhen`, headline and thumbnail. On mobile, tap shows the same as a small card with **Open clip**.
- On Clips, the Ribbon is also a filter: drag across it to choose a time range. A chip shows the range ("Sat 6 pm to Sun 2 am") with a clear button. The grid filters to that range.
- Camera scope: follows the camera filter on Clips; shows all cameras on Overview.
- New install: the track starts where recording started. Everything to its left is drawn as "Not recorded" with a light hatch, and the summary reads "VYZN has been watching for 2 h 10 min." Do not draw a full 72-hour bar that did not happen.
- No clips in 72 h: track only, summary "No clips in the last 72 hours."
- Height 64 px desktop, 56 px mobile including axis labels. Tick hit areas are 44 px wide on mobile via transparent padding.
- Accessibility: the strip has `role="group"` with an `aria-label` such as "Last 72 hours. 2 alerts and 5 clips to review." Ticks are buttons in a roving-tabindex list, Left and Right arrows move between them. The Clips grid is the complete accessible equivalent.
- Reduced motion: no highlight animation; a new tick just appears.

---

### 6.7 Settings

Desktop: two columns (section list, content). Mobile: a list of sections that each open a page.

| Section | Contents |
|---|---|
| Account | Email (read only). Mobile number, with **Change** (re-runs the Telegram link, because the number and the Telegram account must match). Sign out |
| Telegram | Status ("Connected", with `@handle` if known), **Send a test alert**, **Reconnect**, **Disconnect**. Last test result ("Delivered in 1.2 s at 9:41 pm") |
| Shop | Shop name, timezone (default Asia/Kolkata), shop hours per weekday (open and close, or Closed). Used by "Outside shop hours" watch areas and headlines |
| Appearance | Theme: System, Light, Dark. Language: English (Hindi and Marathi appear here when shipped in Phase 8; do not show disabled placeholders) |
| Storage and retention | Read-only statement: "VYZN keeps footage and clips for 72 hours, then deletes them. This can't be changed." Real figures: storage used, oldest item kept, last cleanup ("9:30 pm, removed 14 clips, 1.8 GB"), next cleanup. Deletion log (last 50 entries, metadata only). If the cleanup job has not run for over 1 hour: amber notice "Cleanup hasn't run since 8:15 pm" and an amber dot on the Settings icon |
| System health | For the technically curious and for evaluators. Real values only: CPU, memory, disk free, per-camera detection rate (frames per second actually processed), offline buffer size, detector name and version, app version, uptime, last heartbeat from each camera. The developer telemetry that used to crowd the header lives here, labelled in plain words |
| Privacy | Short plain-language text: what VYZN records, how long it keeps it (72 h), who can see it (the signed-in owner). A reminder to put up a sign that says CCTV is in operation. A link to the privacy notice (placeholder route until the founder supplies the text) |
| Demo mode | Present only in non-production builds (`VYZN_DEMO=1`). Section 7.4 |

---

## 7. Data and truth rules

### 7.1 Every element and where its data comes from

| UI element | Source | If the source is missing |
|---|---|---|
| Camera Online / Offline | Time since the last decoded frame: online if under 15 s | Show "Not seen yet" (neutral) |
| Live badge | Frames actually arriving in the player | Show Connecting, Reconnecting or Offline |
| Header status pill | Camera states and Telegram link state | Never draw a green "all good" if any input is unknown; show "Checking…" |
| Flags | Clips where `status = unreviewed` | Empty state |
| Tier and reasons | `clip.tier` and `clip.reasons` from the backend | Do not compute tiers in the front end |
| "Checked 1,240 moments" line | `stats.moments_checked_24h` | Omit the line |
| "136 moments outside it were ignored" | Counter of moments dropped by the area mask | Omit the line |
| Ribbon track and gaps | Recording coverage segments | Draw nothing |
| Ribbon ticks | Clip timestamps | Draw nothing |
| "Deletes in 41 h" | `clip.expiresAtMs − now` | Hide the line |
| Video size and fps on camera tile | Measured from the stream | Hide the line |
| Telegram "Delivered in 1.2 s" | Measured send-to-response time | Hide the number |
| Storage figures, cleanup times | Storage scan and deletion log | Show "Unknown" and log an error |
| Detector confidence ("88% sure") | Detector output | Omit the percentage |
| Storage location wording | `STORAGE_MODE` config (`local` or `cloud`) | Say nothing about location |

Forbidden without a data source: any percentage, count, speed, uptime or rating; any customer name or number; any legal or certification claim; any "Live" text on a non-live image.

### 7.2 Data contracts (adapt names to the repo)

```ts
type Tier = 'alert' | 'review';
type ClipStatus = 'unreviewed' | 'reviewed' | 'not_an_issue';

interface Shop {
  id: string; name: string;
  timezone: string;                                   // IANA, default 'Asia/Kolkata'
  hours: Record<0|1|2|3|4|5|6, { open: string; close: string } | null>; // 'HH:mm', null = closed
}

interface User {
  id: string; email: string; phoneE164: string | null;
  telegram: { status: 'not_linked'|'pending'|'linked'|'blocked'; handle?: string; linkedAtMs?: number };
}

interface Camera {
  id: string; name: string;
  source: { kind: 'ip'|'onvif'|'phone'|'webcam'; host?: string; port?: number;
            brand?: 'hikvision'|'cpplus'|'dahua'|'other'; channel?: number; hasCredentials: boolean };
  status: 'online'|'offline'|'unknown';
  lastFrameAtMs: number | null; offlineSinceMs: number | null;
  video: { width: number; height: number; fps: number } | null;
  areaCount: number; snapshotUrl: string | null;
}

interface WatchArea {
  id: string; cameraId: string; name: string;
  polygon: [number, number][];                         // normalised 0..1, at least 3 points
  response: 'alert' | 'review';
  minStaySeconds: 0 | 10 | 30 | 60;
  schedule: 'always' | 'outside_shop_hours';
  version: number;
}

interface ClipReason {
  code: 'person_detected'|'movement'|'entered_restricted_area'|'stayed_in_area'|'outside_shop_hours';
  params?: Record<string, number | string>;            // e.g. { seconds: 63, confidence: 0.88, area: 'Cash counter' }
}

interface Clip {
  id: string; number: number;                          // sequential per shop: "Clip 23"
  cameraId: string; areaId: string | null;
  startMs: number; endMs: number; triggerMs: number;
  tier: Tier; status: ClipStatus;
  reasons: ClipReason[];                               // reasons[0] is the primary reason
  objects: { cls: string; confidence: number }[];
  thumbnailUrl: string; previewUrl: string; videoUrl: string;
  boxes?: unknown;                                     // stored detection boxes for the "what VYZN saw" overlay
  sha256: string; detector: { name: string; version: string };
  expiresAtMs: number;
  reviewedAtMs?: number; feedback?: { reason: 'staff'|'customer'|'light'|'other' };
}

interface DeletionLogEntry {
  clipNumber: number | null; cameraId: string; momentAtMs: number;
  tier: Tier | null; status: ClipStatus | null;
  deletedAtMs: number; reason: 'retention' | 'camera_removed';
}
```

### 7.3 Suggested endpoints and events

```
POST /api/auth/email/start          { email }
POST /api/auth/email/verify         { email, code }
POST /api/auth/signout
GET  /api/me
POST /api/me/phone                  { phoneE164 }
POST /api/telegram/link             -> { deepLink, expiresAtMs }
GET  /api/telegram/status
POST /api/telegram/test             -> { deliveredAtMs, latencyMs }
GET|POST|PATCH|DELETE /api/cameras
POST /api/cameras/test              -> { ok, snapshotUrl, width, height, fps } | { ok:false, reason }
POST /api/cameras/discover          -> ONVIF results
GET  /api/cameras/:id/snapshot
GET  /api/cameras/:id/live          (signalling for the chosen live method, see D2)
GET|PUT /api/cameras/:id/areas      (PUT replaces the set; carries versions)
GET  /api/clips?camera=&tier=&status=&object=&from=&to=&cursor=
GET  /api/clips/:id
PATCH /api/clips/:id                { status, feedback }
POST /api/clips/:id/telegram
GET  /api/clips/:id/evidence-pack
GET  /api/ribbon?from=&to=&camera=  -> { coverage, clips, gaps }
GET  /api/retention                 -> { hours:72, oldestMs, storageBytes, lastRunMs, nextRunMs, log }
GET  /api/health
GET  /api/stream                    SSE: flag.created, clip.updated, camera.status, telegram.linked
```

### 7.4 Demo mode and cleaning the test data

- The database currently holds developer test data (one face, all "critical", dates in 1970). **Ask me before clearing it (rule 6).** Back it up, write `scripts/clear_test_data.*`, show me the command and the row counts it will remove, and wait.
- Demo mode is off by default and exists only in non-production builds (`VYZN_DEMO=1`). It uses a separate database and a fixed set of sample footage with varied, realistic events (not the developer's face). While on, a persistent amber banner reads "Demo data. These clips are not real." and it cannot be hidden. The banner also appears in every screenshot taken for the walkthrough.
- The demo generator creates timestamps relative to now, so the Ribbon always spans the last 72 hours, and it must pass through the same API as real data.

### 7.5 Delete from the current UI

Marketing hero and badges, the four proof statistics, testimonials and the three footer cards, WhatsApp and Free Trial buttons, Guest Mode block, Live Threat Index and its scale, CPU/RAM/disk/FPS/FAR/offline-buffer header strip, "Zero Cloud Choke" upload-cap chip, DIRECT-SHOW and LIVE WEBCAM badges, the 1×1/2×2/3×3 grid switcher, the Threat Incident Stream panel, the Star/Protected filter, garment-colour filter, raw X/Y readout, vertex count, threat weight field, "Commit Zone to Pipeline" wording, Historical scrub with evenly spaced markers. List anything you delete in the walkthrough under "Removed".

---

## 8. Quality gates (definition of done for every phase)

**Responsive.** Test 360, 390, 768, 1024, 1440 px. No horizontal scroll. Wide content (tables, hashes) scrolls inside its own container. Text at 200% zoom stays usable.

**Performance.** Overview on a mid-range Android phone over 4G: usable in under 3 s, initial JavaScript under 250 KB gzipped, video and thumbnails lazy-loaded. Only one live stream at a time on Overview. Thumbnails served as WebP or AVIF at the size they are shown.

**Accessibility.** Contrast checked for every token pair in both themes and the results pasted into the walkthrough. Every interactive element reachable and operable by keyboard. Focus never lost when a drawer opens or closes. Live regions for new flags, save confirmations and errors. No information by colour alone.

**Errors and empties.** Every screen has designed loading, empty, error and offline states with the copy in Appendix A. Errors say what happened and what to do next.

**Security and privacy.** No third-party analytics or trackers. Camera credentials encrypted at rest. Session cookie httpOnly, secure, SameSite. Media URLs are signed and expire. Rate limits on code and link requests. Nothing about a camera's address or credentials reaches the browser.

**Tests.** Unit tests for `formatWhen`, `formatLeft`, tier and headline mapping, polygon normalisation, retention job. Playwright end-to-end test for the full flow: email, code, phone, Telegram link (with a mocked bot), add camera (against a test RTSP source), draw area, receive a demo flag, open the clip, mark reviewed. Playwright screenshots at 390 and 1440 in both themes stored in the walkthrough artifact.

**Grep gates (must return nothing in the UI source and i18n files):** the words listed in Appendix D.

---

## 9. Phases

Work one phase at a time. For each: implementation plan first, my approval, build, run, screenshots, walkthrough.

| Phase | Build | Done when |
|---|---|---|
| 0. Audit and plan | Read the repo. Report stack, routes, DB schema, how detection produces events, how live video is served today, what data each element in section 7.1 has and what is missing. Propose the cleanup script (do not run it). List decisions D1 to D8 with your recommendation | I have approved a written gap analysis. No UI code changed |
| 1. Foundation | Tokens, both themes, fonts, app shell, navigation, `formatWhen` and `formatLeft`, i18n scaffold, component inventory (5.10) on a dev-only `/_design` page | `/_design` shows every component in every state in both themes at 390 and 1440. Contrast table passes |
| 2. Sign-in and setup | Sections 6.1 S1 to S4, sessions, Telegram bot link protocol, test alert | Full flow works end to end on a real phone with a real bot. Number-mismatch and expired-link cases tested |
| 3. Cameras and live view | Section 6.5 wizard and list, connection test, live player and states from 6.2, Overview shell with camera picker and cameras strip | A real RTSP camera and a phone camera both add, test, and play live. Every error row in the test table is reproducible |
| 4. Watch areas | Section 6.4 editor, storage, pipeline masking | Drawing a shop area over a camera that also sees a road makes movement on the road produce no clips; movement in the area does. Shown with a recording |
| 5. Flags and clips | Sections 6.2 Flags panel, 6.3 Clips page, drawer, actions, Evidence pack, Telegram alert format (Appendix B) | A real event creates a clip, a flag, and a Telegram alert; the drawer shows the true reasons; the pack downloads and its SHA-256 matches the file |
| 6. Ribbon and retention | Section 6.6 Ribbon on Overview and Clips, cleanup job, deletion log, expiry cues, Settings → Storage and retention | Retention test passes with frozen time. Ribbon matches the Clips grid exactly. New-install and gap states verified |
| 7. Settings and health | Section 6.7 remaining sections, System health with real telemetry, Demo mode, camera-offline Telegram notices | Header has no telemetry. Demo banner cannot be hidden. Offline notice arrives on Telegram at 10 min |
| 8. Language, install and polish | Hindi and Marathi files, Devanagari layout check, PWA manifest and icons so the owner can add VYZN to the phone home screen, final accessibility and performance pass | Screens verified in all three languages at 390 px. Lighthouse accessibility 95+ on every route |

---

## 10. Open decisions

Ask me about these in Phase 0 with your recommendation. Do not assume.

| # | Decision | Recommendation in this spec |
|---|---|---|
| D1 | Star/Protect versus the 72-hour rule | Remove Star. Offer Evidence pack download before expiry |
| D2 | How live video reaches the browser (browsers cannot play RTSP) | Inspect what the repo does today. If nothing suitable, propose a relay such as go2rtc or MediaMTX serving WebRTC with an HLS fallback, and a snapshot fallback if both fail |
| D3 | Where footage is processed and stored (shop hardware or cloud) | Unknown to this spec. The UI says nothing about location until `STORAGE_MODE` is set |
| D4 | Can Telegram be skipped on first run? | No. If it is later disconnected, show the header warning rather than locking the owner out |
| D5 | Watching raw footage around a clip | Yes, inside the clip drawer only: "Watch 2 minutes before and after" from stored footage. No general footage browser in v1 |
| D6 | Clothing-colour attribute | Keep in data, hide from the UI in v1 |
| D7 | Telegram bot | One shared VYZN bot. I will supply the bot token and username as `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_USERNAME` |
| D8 | More than one user per shop (staff) | Not in v1. One owner account per shop |

**Not in v1 (do not build):** multi-camera grid view, ignore-areas cut-outs, staff accounts, WhatsApp alerts, billing screens, sound alerts, general footage browsing, map or floor plan, analytics dashboards.

---

## Appendix A. Copy deck (English)

Sentence case. Plain verbs. Same action, same name everywhere.

| Where | Text |
|---|---|
| Sign-in title | Sign in to VYZN |
| Sign-in helper | We'll email you a 6-digit code. No password needed. |
| Code sent | We sent a 6-digit code to {email}. It works for 10 minutes. |
| Resend | Send a new code in {n} s / Send a new code |
| Phone title | Add your mobile number |
| Telegram title | Connect Telegram |
| Telegram waiting | Waiting for Telegram… |
| Telegram connected | Telegram connected. |
| Test alert result | Test alert delivered in {n} s. Check Telegram. |
| Flags title | Flags · {n} waiting |
| Flags empty | Nothing needs your attention. |
| Live offline | Offline since {time} |
| Clips empty | No clips yet. VYZN saves a clip when something happens inside a watch area. |
| Clips no match | No clips match these filters. |
| Drawer reasons heading | Why this clip was saved |
| Mark reviewed toast | Marked as reviewed. Undo |
| Not an issue toast | Marked as not an issue. Undo |
| Areas whole view | Watching the whole view. Draw an area to ignore everything else. |
| Areas legend | Bright: watched. Dimmed: ignored. |
| Areas saved | Areas saved. Applies to new footage. |
| Camera test success | We can see the picture. |
| Retention statement | VYZN keeps footage and clips for 72 hours, then deletes them. |
| Retention cannot change | This can't be changed. |
| Deleted clip (drawer) | This clip was deleted after 72 hours. |
| Generic error | Something went wrong. Try again. If it keeps happening, check Settings → System health. |
| Offline browser | You're offline. Showing what was last loaded. |

---

## Appendix B. Telegram messages

Emoji are fine here. Plain text plus inline buttons. Keep every message under 5 lines.

Alert:

```
🚨 Alert · Shop entrance
Person stayed 63 seconds in Cash counter
Today, 9:34 pm
[ Open clip ]  [ Not an issue ]
```

Attach the clip thumbnail as the photo. "Open clip" is a URL button to `/clips/:id`. "Not an issue" is a callback button that sets `status = not_an_issue` and edits the message to "Marked as not an issue."

Camera offline: `⚠️ Shop entrance went offline at 9:12 pm.` Back online: `Shop entrance is back online.`

Test alert: `This is a test from VYZN. Your alerts will arrive here.`

Review-tier clips are never pushed.

---

## Appendix C. Stream address templates

Verify with the connection test; models vary.

| Brand | Main stream | Sub-stream |
|---|---|---|
| Hikvision | `rtsp://user:pass@IP:554/Streaming/Channels/101` | `.../Streaming/Channels/102` |
| Hikvision recorder, channel N | `.../Streaming/Channels/N01` (channel 2 is `201`) | `.../Streaming/Channels/N02` |
| Dahua and CP Plus | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` | `...&subtype=1` |
| Other | Owner pastes the full address | |
| Android IP Webcam | `http://PHONE_IP:8080/video` | |

Use the sub-stream for live tiles and thumbnails, the main stream for detection quality and clip cutting (or the sub-stream if CPU is the limit; state the choice in the plan).

---

## Appendix D. Words that must not appear in the UI or i18n files

Tier 4, Tier 2, Critical, Threat Index, Threat weight, Geofence, Zone (as a noun for watch areas), Vertex, Polygon, ROI, Pipeline, Commit, False positive, Incident stream, Certified, Court-ready, Section 65B, Guest Mode, Zero Cloud, Cloud Choke, Sovereign, 500+, DIRECT-SHOW, FAR.

---

## Appendix E. Notes for the founder (not for the UI)

- **Evidence law.** Section 63 of the Bharatiya Sakshya Adhiniyam, 2023 replaced Section 65B of the Evidence Act from 1 July 2024. VYZN prepares the file, hash and summary; it does not certify. Have a lawyer review the Evidence pack wording before you sell it.
- **DPDP Rules.** The Digital Personal Data Protection Rules, 2025 were notified on 13 November 2025. Most duties for businesses that handle personal data (notice, security safeguards, breach reporting, retention and erasure) apply from 13 May 2027. The Rules also expect processing logs to be kept for a minimum period (a year is the figure commonly cited), which is why the deletion log stores metadata only and never video. Check the exact retention and notice obligations for a CCTV product with a lawyer before you launch commercially.
- **Signage.** Ask each shop owner to display a notice that CCTV is in operation. The Privacy page in Settings carries a reminder.
- **Claims.** Do not put "500+ retailers", response-time figures or testimonials on the marketing site until you have real customers and measurements. The product can show a measured "Delivered in 1.2 s" per alert once it is real.

---
End of specification.
</USER_REQUEST>
<ADDITIONAL_METADATA>
The current local time is: 2026-09-29T23:42:47+05:30.
</ADDITIONAL_METADATA>