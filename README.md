# Sentinel-X -- Civic Enforcement System

AI-powered traffic violation reporting app for Android. Captures evidence, detects number plates via OCR, auto-routes reports to the correct Indian police authority, and protects the reporter under Good Samaritan Law (Section 134A, MVA 1988).

**Version:** 1.6.0
**Target:** Android 10+ (arm64-v8a)
**Stack:** Python 3.10 + Kivy + camera4kivy (CameraX) + OpenCV + ML Kit + Play Core + Buildozer
**Build toolchain:** python-for-android pinned to `v2024.01.21` (numpy 1.22.3, classic
setup.py build — newer p4a ships numpy 2.x which fails to cross-compile on NDK r25b)

---

## Features

### Core
- **Live Camera** -- CameraX preview with real-time frame analysis
- **Evidence Capture** -- Photo capture with GPS/timestamp watermark and SHA-256 hash sidecar
- **Dual Routing** -- Reports sent to BOTH location-based AND plate-based police authorities
- **Good Samaritan** -- Anonymous reporting with Section 134A legal protection in every email
- **7 MVA 2019 Offenses** -- Sections 183, 184, 194B, 194C, 194D, 194E
- **All 36 States & UTs** -- Police email directory verified against official sites (`civic.CivicDirectory`, source URL per state); states with no published email point to their official alternative channel

### Phase 1 -- Recording & Resilience
- **Dashcam Recording** -- Continuous JPEG capture in 2-minute segments with 5-segment ring buffer (~10 min)
- **Camera Crash Recovery** -- Watchdog detects stalls >5s, reconnects with exponential backoff (2s to 30s cap)
- **Memory Safety** -- Bounded frame ring buffer (20 frames max) prevents OOM
- **Service Telemetry** -- Background 10Hz GPS + accelerometer via UDP (port 17888)

### Phase 2 -- Evidence Integrity
- **SHA-256 Hashing** -- Tamper-detection sidecar files for every captured image
- **Metadata Watermark** -- GPS coordinates, timestamp, and plate number burned onto evidence
- **Report History** -- Append-only JSON-lines log of all sent reports

### Phase 3 -- Offline Resilience
- **Offline Queue** -- Reports queued as JSON files when connectivity fails
- **Connectivity Detection** -- Socket probe to 8.8.8.8:53
- **Auto-Retry Daemon** -- Background thread retries queued reports every 60s with responsive shutdown

### Phase 4 -- Detection & Monitoring
- **ONNX Detector** -- Optional ONNX model inference (drop `detector.onnx` into models/)
- **Speed Zones** -- Haversine proximity checks for school/hospital/residential zones
- **Subsystem Status** -- Real-time health monitoring across all subsystems
- **Harsh Brake Log** -- JSON-lines event log with 5s debounce, G-force, GPS, speed
- **Night Vision** -- CLAHE enhancement for low-light/fog plate visibility

### Phase 5 -- Automatic Plate OCR
- **ML Kit Text Recognition** -- On-device OCR via Google ML Kit (Android) with Tesseract desktop fallback
- **Full-Resolution Scanning** -- OCR runs on the full-res camera frame (not downscaled)
- **SCAN Button** -- On-demand full-frame OCR with visual feedback
- **Auto-Fill** -- Detected plates auto-populate the plate field (only when empty or previously auto-set)
- **Capture-Time OCR** -- Additional OCR pass on saved evidence images
- **Jurisdiction Routing** -- Plate state code auto-suggests correct police email recipients
- **Anti-Fabrication** -- OpenCV fallback counts character regions only, never generates placeholder text
- **Smart Regex** -- Indian plate pattern `([A-Z]{2})\s*(\d{1,2})\s*([A-Z]{0,3})\s*(\d{3,4})` rejects signage fragments

### Phase 6 -- Citizen Empowerment (`civic.py`)
- **Multi-channel reporting** -- Share to X/Twitter (auto-tags state traffic-police handles) and WhatsApp via deep links
- **Vehicle lookup** -- Plate -> RC / insurance / PUC / owner via a configurable `SENTINELX_VAHAN_URL` endpoint (degrades gracefully; never fabricates)
- **Road-hazard reporting** -- 8 municipal categories (potholes, signals, signage, waterlogging, footpath encroachment, ramps, streetlights, manholes) -> email + CPGRAMS fallback
- **SOS / Emergency** -- Dial 112/108, live-location SMS, Good Samaritan (Section 134A) accident flow
- **Duplicate guard** -- Warns on near-duplicate reports (same plate+offense, <150 m, <10 min)
- **Privacy face-blur** -- Opt-in blur of bystander faces on evidence (off by default -- a rider's head can itself be helmet/phone evidence)
- **Localisation** -- English / Hindi runtime translation for key strings
- **Violation hotspots** -- Local density map from the report log
- **Offline India geocoder** -- Pure-Python `IndiaGeocoder` (state-anchor + haversine) resolves GPS->state with no scipy/numpy on device

### App Updates (OTA + Play)
- **GitHub OTA** (sideloaded) -- Each successful `main` build publishes a GitHub Release with `sentinelx.apk` + `update.json`. The app auto-detects a higher versionCode on launch, downloads via Android DownloadManager, and prompts a one-tap install.
- **Play In-App Updates** (Play installs) -- Java helper (`java_src/.../InAppUpdate.java`) drives the Play Core FLEXIBLE flow: background download + auto-install.
- **Auto-routing** -- App detects its install source (`getInstallerPackageName`) and uses Play updates on Play installs, GitHub OTA otherwise -- no double prompts.

### Phase 7 -- Accuracy, Evidence & Safety
- **Multi-frame plate voting** -- Live auto-fill needs the same plate in 2 of the last 5 reads; a one-frame misread never reaches the form
- **Plate overlay + chips** -- Detected plate outlined on the preview (amber = seen once, green = confirmed); when several plates are in view, tap a chip to pick
- **Bharat-series plates** -- `22 BH 1234 AA` format recognised (routes by location)
- **City-level routing** -- Inside 22 major cities the report goes to that city's traffic wing (e.g. Pune vs Mumbai, Cyberabad vs Hyderabad), else the state list
- **Official WhatsApp channels** -- MORE > "WhatsApp traffic police" sends the original photo + report to the force's published number (Goa, Tripura, Delhi)
- **Directory OTA** -- CI publishes `directory.json` with each release; the app validates and applies it, so address changes need no new APK
- **Privacy-safe sharing** -- X/WhatsApp shares get a copy with faces and bystander plates blurred; the offender's plate and the original evidence are untouched. (Face cascade is bundled in `assets/` -- p4a's OpenCV ships without `cv2.data`, so face blur previously did nothing on Android)
- **Signed evidence proof** -- Every capture writes `<photo>.proof.json`: SHA-256, UTC time, GPS fix with accuracy and satellite fix time, device -- signed with an EC P-256 key held in the Android Keystore. Verify:
  ```python
  import json, base64
  from cryptography.hazmat.primitives.serialization import load_der_public_key
  from cryptography.hazmat.primitives import hashes
  from cryptography.hazmat.primitives.asymmetric import ec
  p = json.load(open("SentinelX_....png.proof.json"))
  load_der_public_key(base64.b64decode(p["public_key_b64"])).verify(
      base64.b64decode(p["signature_b64"]), p["payload"].encode(), ec.ECDSA(hashes.SHA256()))
  ```
- **15 s video clips** -- MORE > "Save last 15 s" writes the dashcam's rolling 4 fps buffer as an MJPEG AVI to `Movies/SentinelX`
- **Crash SOS** -- Crash-level G-force shortly after moving at >= 15 km/h opens a 15 s cancellable countdown, then a pre-filled SMS to your emergency contact (or the 112 dialer)
- **Follow-up reminders** -- Reports older than 7 days prompt an escalation; a CPGRAMS complaint draft is copied to the clipboard
- **6 UI languages** -- English, Hindi, Marathi, Tamil, Kannada, Bengali, rendered with the phone's Noto fonts + HarfBuzz script shaping (MORE > Language)

### Phase 8 -- Reports That Lead to Challans
- **Unedited originals** -- CAPTURE keeps the camera image untouched (hashed, signed, attached, shared with police apps); night enhancement, face blur and the watermark go on a separate `_annotated.jpg` (Delhi's Traffic Prahari rejects edited evidence)
- **Pre-send quality check** -- Warns before SEND about a missing/blurry photo, a stale or imprecise GPS fix, or an invalid plate -- the usual reasons police apps reject reports
- **Live GPS** -- Requests live GPS + network fixes; previously only Android's last-known location was read, which on test was 5 days (8 km) stale
- **Official police apps** -- "Report in official police app" hands the original photo to Traffic Prahari (Delhi), BTP ASTraM (Bengaluru) or the Mumbai Traffic Police app (package ids verified on Google Play)
- **City civic channels** -- Road hazards go to the city's own grievance app / helpline / website (MCD 311, MyBMC, Sahaaya 2.0, Namma Chennai, GHMC, KMC, PMC CARE, AMC CCRS, Jaipur, Patna) with email as fallback
- **Automatic night mode** -- Dark photos get CLAHE enhancement on the annotated copy without touching the switch
- **Battery / heat care** -- Dashcam + live OCR pause below 15% battery (not charging) or above 44 C, resuming with hysteresis
- **Hands-free flag** -- Double-press a volume key to save the last 15 s clip with no screen interaction
- **Accident help** -- SOS shows the cashless-treatment entitlement (Rs 1.5 lakh / 7 days), a nearest-hospital map, and a Rah-Veer (Rs 25,000 Good Samaritan award) helper that records signed accident/hospital timestamps and drafts the application
- **RTI + PDF evidence pack** -- RTI Act s.6(1) request draft for any report; one-file PDF with the summary, original photo and signed proof (`Download/SentinelX`)
- **Stable APK signing in CI** -- CI re-signs the APK with the keystore in the `ANDROID_DEBUG_KEYSTORE_B64` repository secret (alias `androiddebugkey`), so every build can update the previous one; without it Gradle signs with a fresh throwaway key and OTA updates fail

### UI/UX
- **Dark Theme** -- Custom design system (#0B0E17 background, cyan/green/amber/red accents)
- **Action Bar** -- SCAN (purple), CAPTURE (blue), SEND (green), CLEAR (slate)
- **Header** -- MORE (citizen tools menu) + HISTORY (last 10 reports)
- **Landscape capture** -- `orientation = all`; rotate to landscape to frame wide plates
- **Context-Aware Popups** -- Green for success, red for errors, amber for warnings, cyan for info
- **Styled Widgets** -- Custom Card, StyledInput, StyledSpinner, ActionBtn, ToggleRow, SectionLabel

---

## Step-by-Step: Build and Install

### Prerequisites

| Tool | Install Command |
|------|----------------|
| Git | `sudo apt install git` (Linux) or [git-scm.com](https://git-scm.com) |
| Python 3.10+ | `sudo apt install python3 python3-pip` |
| Java 17 | `sudo apt install openjdk-17-jdk` |
| Android phone | arm64 device, Android 10+, USB debugging ON |

### Step 1: Clone and Setup

```bash
git clone https://github.com/ankitjha67/SentinelX-Build.git
cd SentinelX-Build
bash setup.sh
```

### Step 2: Run Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

All 287 tests must pass before building.

### Step 3: Install Buildozer

```bash
pip install --upgrade pip setuptools wheel
pip install "cython<3.0" buildozer
```

### Step 4: Build the APK

```bash
buildozer -v android debug
```

First build takes 15-25 minutes (downloads Android SDK, NDK, compiles OpenCV for ARM64). The APK will be at `bin/sentinelx-1.6.0-arm64-v8a-debug.apk`.

### Step 5: Install on Your Phone

**Option A -- USB:**
```bash
adb install -r bin/*.apk
```

**Option B -- Transfer:** Copy the `.apk` to your phone and tap to install (allow "Install from unknown sources").

### Step 6: Grant Permissions

| Permission | Select | Why |
|------------|--------|-----|
| Camera | Allow | Evidence capture + OCR |
| Location | Allow all the time | GPS geocoding + background service |
| Storage | Allow | Save evidence photos |

Then: Settings > Apps > Sentinel-X > Battery > **Unrestricted**

### Step 7: Use the App

1. Point camera at a vehicle committing a violation
2. **SCAN** to read the number plate via OCR (or type it manually)
3. Select the **Violation** from the dropdown
4. Toggle **Night/Fog CLAHE** if conditions are poor
5. **CAPTURE** to save the evidence photo (watermarked + hashed)
6. **SEND** -- email app opens with pre-filled recipients, violation report, evidence attachment, and Good Samaritan footer
7. **MORE** -- citizen tools (share to X/WhatsApp, vehicle lookup, hazard report, SOS, hotspots, privacy blur, language, check for updates)
8. **HISTORY** -- review past 10 reports

---

## Build & Distribute via GitHub Actions

Every push runs the CI pipeline: **test -> build APK**.

1. Fork this repo on GitHub
2. Push any commit -- the `build` workflow runs the 287 tests, then builds the APK
3. Download the APK from the run's **Artifacts** section (retained 30 days)

**OTA releases (main only):** a successful build on `main` also publishes a
**GitHub Release** with `sentinelx.apk` + `update.json` (marked latest). Installed
apps poll `releases/latest/download/update.json`, compare the `version_code`, and
prompt a one-tap update. The build number is injected as the Android versionCode,
so every `main` build is a higher version that devices detect automatically.

---

## Project Structure

```
SentinelX-Build/
|-- camerax_provider/          <- Android CameraX bindings (cloned by setup.sh)
|   |-- gradle_options.py      <- p4a hook: CameraX + ML Kit + Play Core deps, add-source
|-- java_src/
|   |-- org/sentinelx/InAppUpdate.java   <- Play In-App Updates helper
|-- main.py                    <- App UI + subsystems (Phases 1-6, ~3200 lines)
|-- civic.py                   <- Phase 6 logic (Kivy-free, unit-tested)
|-- service.py                 <- Background GPS + accelerometer (UDP broadcast)
|-- buildozer.spec             <- Android build config (v1.6.0, API 33, NDK 25b, p4a v2024.01.21)
|-- setup.sh                   <- One-time setup script
|-- tests/
|   |-- conftest.py
|   |-- test_sentinelx.py      <- 287 unit tests
|-- .github/workflows/
|   |-- build.yml              <- CI: test -> build APK -> upload artifact -> publish OTA (main)
|-- models/                    <- Drop a detector.onnx here (optional)
|-- evidence/                  <- Captured photos (auto-created, gitignored)
```

---

## Architecture

### Frame & OCR Pipeline

```
Camera Frame Flow:
  camera4kivy --> analyze_pixels_callback --> FrameRingBuffer (20 frames)
                       |                           |              |
                 watchdog.frame_received()         |              |
                                          FrameAnalysisWorker   DashcamRecorder
                                          (daemon thread)       (daemon thread)
                                          pops & analyzes       peeks & saves JPEG
                                          skips if behind       1 FPS, 2-min segments

OCR Flow:
  FrameAnalysisWorker --> PlateOCR.process_frame(full_res_frame)
       |                       |
       |                  ML Kit / Tesseract engine
       |                       |
       |                  clean_plate_text() --> Indian plate regex (best-of-multiple)
       |                       |
       |                  suggest_routing() --> JurisdictionEngine
       |                       |
       v                       v
  UI: ocr_suggest_text    UI: plate auto-fill (if field empty)

SCAN Button:
  scan_now() --> background thread --> PlateOCR.process_image(full_res_frame)
                                           |
                                    bypasses throttle, returns (plate, confidence)
                                           |
                                    _apply_ocr_result() on UI thread
```

### Telemetry & Recovery

```
Telemetry:
  service.py (background) --UDP:17888--> TelemetryReceiver --> _poll_gps / _poll_accel
                                         (daemon thread)       (prefer telemetry, fallback direct)

Crash Recovery:
  CameraWatchdog --(no frame >5s)--> disconnect + reconnect (2s, 4s, 8s, 16s, 30s cap)
```

### Evidence & Reporting

```
Capture:
  capture_evidence() --> export_to_png --> CLAHE (if enabled)
                                              |
                                    EvidenceWatermark.apply() (GPS + timestamp + plate)
                                              |
                                    EvidenceHasher.write_hashfile() (SHA-256 sidecar)
                                              |
                                    PlateOCR.process_image() (capture-time OCR)

Online Send:
  send_report() --> plyer.email --> ReportLog.append()

Offline:
  send_report() --> fails --> OfflineReportQueue.enqueue()
                                       |
  QueueRetryDaemon (60s) --> ConnectivityChecker.is_online()?
       | yes                           |
       --> load --> send --> dequeue --> ReportLog.append()
```

### Subsystem Table

| Phase | Subsystem | Class | Thread | Purpose |
|-------|-----------|-------|--------|---------|
| 1 | Frame Buffer | `FrameRingBuffer` | shared | Bounded deque, prevents OOM |
| 1 | Analysis | `FrameAnalysisWorker` | daemon | CV + OCR processing off main thread |
| 1 | Watchdog | `CameraWatchdog` | Kivy Clock | Detects camera stalls, auto-reconnects |
| 1 | Recording | `DashcamRecorder` | daemon | Continuous JPEG segments, auto-prune |
| 1 | Telemetry | `TelemetryReceiver` | daemon | Consumes service.py UDP broadcasts |
| 2 | Hashing | `EvidenceHasher` | main | SHA-256 tamper detection |
| 2 | Watermark | `EvidenceWatermark` | main | Burns GPS/timestamp onto images |
| 2 | Report Log | `ReportLog` | main | Append-only JSONL history |
| 3 | Queue | `OfflineReportQueue` | main | Stores reports as JSON files |
| 3 | Connectivity | `ConnectivityChecker` | main | Socket probe to 8.8.8.8:53 |
| 3 | Retry | `QueueRetryDaemon` | daemon | Auto-retries queued reports |
| 4 | ONNX | `ONNXDetector` | main | Optional plate detection model |
| 4 | Speed Zones | `SpeedZoneChecker` | main | Haversine proximity + speed limits |
| 4 | Status | `SubsystemStatus` | main | Health aggregator for all subsystems |
| 4 | Brake Log | `HarshBrakeLog` | main | JSONL event log with debounce |
| 5 | Plate OCR | `PlateOCR` | worker | ML Kit / Tesseract engine abstraction |
| 5 | Jurisdiction | `JurisdictionEngine` | main | Plate state code to police email routing |
| 6 | Geocoder | `IndiaGeocoder` | main | Offline GPS->state (no scipy/numpy) |
| 6 | Channels | `ReportChannels` / `CivicDirectory` | main | X/Twitter + WhatsApp share links |
| 6 | Vehicle | `VehicleLookup` | worker | RC/insurance/PUC via configurable endpoint |
| 6 | Hazards | `HazardReport` | main | Municipal/CPGRAMS hazard routing |
| 6 | Safety | `Emergency` | main | SOS dial, location SMS, Good Samaritan |
| 6 | Anti-spam | `DuplicateGuard` | main | Near-duplicate report detection |
| 6 | i18n | `I18N` | main | English/Hindi runtime translation |
| 6 | Privacy | `PrivacyBlur` | main | Opt-in face blur on evidence |
| 6 | Updates | `UpdateManifest` + `InAppUpdate.java` | worker | GitHub OTA + Play In-App Updates |

---

## Troubleshooting

**Black camera screen:**
- Verify `camerax_provider/gradle_options.py` exists
- Verify `p4a.hook = camerax_provider/gradle_options.py` in buildozer.spec
- Run `buildozer appclean` then rebuild

**App crashes on launch:**
- Connect USB, run `adb logcat -s python:D` to see Python errors

**OCR not detecting plates:**
- Ensure ML Kit deps are in `camerax_provider/gradle_options.py` (text-recognition:16.0.1)
- Try the SCAN button for on-demand full-frame OCR
- Hold the camera steady with the plate clearly visible

**Build fails compiling numpy/scipy (ninja/meson C++ errors):**
- Keep `p4a.branch = v2024.01.21` in buildozer.spec. Newer p4a ships numpy 2.x
  whose meson build fails on NDK r25b's clang. The pinned release uses numpy 1.22.3
  (classic setup.py).
- Do **not** add `reverse_geocode`/`reverse_geocoder`/`scipy` to requirements --
  they pull scipy, which cannot cross-compile. The bundled `IndiaGeocoder` replaces them.

**Background service / telemetry stops:**
- Settings > Apps > Sentinel-X > Battery > **Unrestricted**

**Vehicle lookup says "no provider configured":**
- Set `SENTINELX_VAHAN_URL` to an endpoint accepting `?plate=` and returning JSON.

**Updates not appearing:**
- OTA releases publish only from the `main` branch. The installed APK must itself
  contain the update-checker (v1.6.0+). Sideloaded = one-tap install prompt;
  fully silent updates require Play Store / MDM / root (Android security).

**Email doesn't send:**
- plyer.email opens your email app (Gmail, etc). You tap Send manually.
- This is by design for legal compliance.

---

## License

MIT License
