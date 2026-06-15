# Sentinel-X -- Civic Enforcement System

AI-powered traffic violation reporting app for Android. Captures evidence, detects number plates via OCR, auto-routes reports to the correct Indian police authority, and protects the reporter under Good Samaritan Law (Section 134A, MVA 1988).

**Version:** 1.5.0
**Target:** Android 10+ (arm64-v8a)
**Stack:** Python 3.10 + Kivy + camera4kivy (CameraX) + OpenCV + ML Kit + Buildozer

---

## Features

### Core
- **Live Camera** -- CameraX preview with real-time frame analysis
- **Evidence Capture** -- Photo capture with GPS/timestamp watermark and SHA-256 hash sidecar
- **Dual Routing** -- Reports sent to BOTH location-based AND plate-based police authorities
- **Good Samaritan** -- Anonymous reporting with Section 134A legal protection in every email
- **7 MVA 2019 Offenses** -- Sections 183, 184, 194B, 194C, 194D, 194E
- **13 State Police Directories** -- DL, MH, KA, TN, UP, HR, KL, GJ, WB, TS, PB, RJ, GA

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

### UI/UX
- **Dark Theme** -- Custom design system (#0B0E17 background, cyan/green/amber/red accents)
- **Action Bar** -- SCAN (purple), CAPTURE (blue), SEND (green), CLEAR (slate)
- **HISTORY Button** -- Scrollable popup of last 10 reports, newest first
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

All 233 tests across 30 test suites must pass before building.

### Step 3: Install Buildozer

```bash
pip install --upgrade pip setuptools wheel
pip install "cython<3.0" buildozer
```

### Step 4: Build the APK

```bash
buildozer -v android debug
```

First build takes 15-25 minutes (downloads Android SDK, NDK, compiles OpenCV for ARM64). The APK will be at `bin/sentinelx-1.5.0-arm64-v8a-debug.apk`.

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
7. **HISTORY** to review past 10 reports

---

## Build via GitHub Actions

Every push triggers the CI pipeline automatically:

1. Fork this repo on GitHub
2. Push any commit -- the `build` workflow runs tests then builds the APK
3. Download the APK from the workflow's **Artifacts** section (retained 30 days)

---

## Project Structure

```
SentinelX-Build/
|-- camerax_provider/          <- Android CameraX bindings (cloned by setup.sh)
|   |-- gradle_options.py      <- p4a hook: injects CameraX + ML Kit gradle deps
|-- main.py                    <- App (~2700 lines, Phases 1-5)
|-- service.py                 <- Background GPS + accelerometer (UDP broadcast)
|-- buildozer.spec             <- Android build config (v1.5.0, API 33, NDK 25b)
|-- setup.sh                   <- One-time setup script
|-- tests/
|   |-- conftest.py
|   |-- test_sentinelx.py      <- 233 unit tests (30 test suites)
|-- .github/workflows/
|   |-- build.yml              <- CI: test -> build APK -> upload artifact
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

**Background service stops:**
- Settings > Apps > Sentinel-X > Battery > **Unrestricted**

**Email doesn't send:**
- plyer.email opens your email app (Gmail, etc). You tap Send manually.
- This is by design for legal compliance.

---

## License

MIT License
