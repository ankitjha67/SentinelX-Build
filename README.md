# Sentinel-X — Civic Enforcement System

AI-powered traffic violation reporting app for Android. Captures evidence, detects number plates, routes reports to the correct police authority, and protects the reporter under India's Good Samaritan Law (Section 134A).

**Target:** Android 10+ (arm64-v8a)
**Stack:** Python + Kivy + camera4kivy + OpenCV + Buildozer

---

## Features

- **Camera** — Live preview via CameraX, photo capture with evidence timestamping
- **Dashcam Recording** — Continuous JPEG capture in 2-minute segments with auto-pruning (ring buffer keeps ~10 min)
- **Camera Crash Recovery** — Watchdog detects stalls >5s and reconnects with exponential backoff
- **Night Vision** — CLAHE enhancement for low-light/fog number plate visibility
- **CV Assist** — Real-time contour detection for plate-like regions (dedicated worker thread with load-shedding)
- **Harsh Braking** — Background 10Hz accelerometer monitoring (G_dyn > 4.0 m/s² threshold)
- **Service Telemetry** — Main app consumes GPS/accelerometer from background service via UDP (port 17888)
- **Memory Safety** — Bounded frame ring buffer (30 frames max) prevents OOM on continuous use
- **Evidence Integrity** — SHA-256 hash sidecar files for tamper detection
- **Metadata Watermark** — GPS coordinates, timestamp, and plate burned onto evidence images
- **Report History** — Append-only JSON-lines log of all sent reports
- **Offline Queue** — Reports queued as JSON when offline, auto-retried when connectivity returns
- **Connectivity Detection** — Socket probe to 8.8.8.8:53 for network status
- **Queue Retry Daemon** — Background thread retries queued reports every 60s
- **ONNX Detector** — Optional ONNX model inference for number plate detection (drop `detector.onnx` into models/)
- **Speed Zones** — Haversine-based proximity checks for school/hospital/residential zones with speed limits
- **Subsystem Status** — Real-time health monitoring of all subsystems displayed in status bar
- **Harsh Brake Log** — JSON-lines event log with timestamps, G-force, GPS, and speed (5s debounce)
- **Dual Routing** — Reports sent to BOTH location-based AND plate-based police authorities
- **Offline Geocoding** — GPS to state/district without internet
- **Good Samaritan** — Anonymous reporting with §134A legal protection in every email
- **7 MVA 2019 Offenses** — §183, §184, §194B, §194C, §194D, §194E
- **13 State Police Directories** — DL, MH, KA, TN, UP, HR, KL, GJ, WB, TS, PB, RJ, GA
- **IRC:67-2022 Sign Groups** — Mandatory + Cautionary signs including EV Charging, Bus Lane

---

## Step-by-Step: Build and Install on Your Phone

### Prerequisites

| Tool | Install Command |
|------|----------------|
| Git | `sudo apt install git` (Linux) or [git-scm.com](https://git-scm.com) |
| Python 3.10+ | `sudo apt install python3 python3-pip` |
| Java 17 | `sudo apt install openjdk-17-jdk` |
| Android phone | arm64 device, Android 10+, USB debugging ON |
| USB cable | To install APK via `adb` |

### Step 1: Clone and Setup

```bash
git clone https://github.com/YOUR_USERNAME/SentinelX.git
cd SentinelX
bash setup.sh
```

The setup script clones `camerax_provider` (Android CameraX bindings required for the camera to work) and verifies all files are in place.

### Step 2: Run Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

All 142 tests must pass before building.

### Step 3: Install Buildozer

```bash
pip install --upgrade pip setuptools wheel
pip install "cython<3.0" buildozer
```

### Step 4: Build the APK

```bash
buildozer -v android debug
```

This takes **15-25 minutes** on first run (downloads Android SDK, NDK, compiles OpenCV for ARM64). Subsequent builds are faster.

The APK will be at `bin/sentinelx-1.0.0-arm64-v8a-debug.apk`.

### Step 5: Install on Your Phone

**Option A — USB cable:**
```bash
# Enable USB debugging on your phone:
# Settings → About Phone → tap Build Number 7 times → Developer Options → USB Debugging ON

adb install -r bin/*.apk
```

**Option B — Transfer file:**
Copy the `.apk` file to your phone via USB/cloud and tap to install. You'll need to allow "Install from unknown sources" in Settings.

### Step 6: First Launch — Grant Permissions

When Sentinel-X opens for the first time, grant ALL these permissions:

| Permission | What to Select | Why |
|------------|---------------|-----|
| Camera | **Allow** | Evidence capture |
| Location | **Allow all the time** | GPS for geocoding + background service |
| Storage | **Allow** | Save evidence photos |

Then go to **Settings → Apps → Sentinel-X → Battery → Unrestricted** so the background harsh-braking service doesn't get killed.

### Step 7: Use the App

1. Point camera at a vehicle committing a violation
2. Toggle **Night/Fog CLAHE** if it's dark (enhances plate visibility)
3. Enter the **Number Plate** (e.g. `MH12AB1234`)
4. Select the **Violation** from the dropdown
5. Tap **Capture** to save evidence photo
6. Tap **Send Report** — your email app opens with:
   - Pre-filled recipients (correct police authorities)
   - Full violation report with GPS, speed, G-force data
   - Good Samaritan §134A legal protection footer
   - Evidence photo attached
7. Tap **Send** in your email app

---

## Build via GitHub Actions (No Local Setup)

If you don't want to install anything locally:

1. Fork this repo on GitHub
2. Go to **Actions** tab → the `build` workflow runs automatically
3. Wait ~20 minutes
4. Download the APK from the workflow's **Artifacts** section
5. Transfer to phone and install

---

## Project Structure

```
SentinelX/
├── camerax_provider/          ← Android CameraX bindings (cloned by setup.sh)
│   └── gradle_options.py      ← p4a hook — camera won't work without this
├── main.py                    ← App (Phases 1-4: recording, integrity, offline, detection)
├── service.py                 ← Background GPS + accelerometer service (UDP broadcast)
├── buildozer.spec             ← Android build config
├── setup.sh                   ← One-time setup script
├── tests/
│   ├── conftest.py
│   └── test_sentinelx.py      ← 142 unit tests (23 test suites)
├── .github/workflows/
│   └── build.yml              ← CI: test → build APK
├── .gitignore
├── models/                    ← Drop a detector.onnx here (optional)
└── evidence/                  ← Captured photos (auto-created, gitignored)
```

---

## Architecture

### Phase 1 — Camera & Telemetry

```
Camera Frame Flow:
  camera4kivy ──► analyze_pixels_callback ──► FrameRingBuffer (30 frames max)
                         │                         │              │
                   watchdog.frame_received()       │              │
                                          FrameAnalysisWorker   DashcamRecorder
                                          (daemon thread)       (daemon thread)
                                          pops & analyzes       peeks & saves JPEG
                                          skips if behind       1 FPS, 2-min segments

Telemetry Flow:
  service.py (background) ──UDP:17888──► TelemetryReceiver ──► _poll_gps / _poll_accel
                                         (daemon thread)       (prefer telemetry,
                                                                fallback to direct sensors)

Crash Recovery:
  CameraWatchdog ──(no frame >5s)──► disconnect + reconnect (2s, 4s, 8s, 16s, 30s backoff)
```

### Phase 2 — Evidence Integrity

```
Capture Flow:
  capture_evidence() ──► export_to_png ──► CLAHE (if enabled)
                                              │
                                    EvidenceWatermark.apply()  (GPS + timestamp burned on image)
                                              │
                                    EvidenceHasher.write_hashfile()  (SHA-256 sidecar)

Report Flow:
  send_report() ──► plyer.email ──► ReportLog.append()  (JSONL history)
```

### Phase 3 — Offline Resilience

```
Online:
  send_report() ──► plyer.email ──► success ──► ReportLog.append()

Offline:
  send_report() ──► plyer.email ──► fails ──► OfflineReportQueue.enqueue()
                                                       │
  QueueRetryDaemon (60s interval) ──► ConnectivityChecker.is_online()?
       │ yes                                           │
       └──► load queued report ──► send ──► dequeue ──► ReportLog.append()
```

### Phase 4 — Detection & Monitoring

```
Speed Zone Check:
  _tick_ui() ──► SpeedZoneChecker.check(lat, lon, kmh)
                  └── haversine distance to registered zones
                  └── alert if within radius AND over limit

Subsystem Monitor:
  _tick_ui() ──► SubsystemStatus.update(cam, gps, dashcam, telemetry, queue)
                  └── summary() ──► status bar display

Harsh Brake Events:
  _poll_accel() ──► g_dyn > 4.0? ──► HarshBrakeLog.record() (5s debounce)

ONNX Detection (optional):
  ONNXDetector ──► loads models/detector.onnx ──► detect(bgr_image) ──► [(x,y,w,h,conf)]
```

### All Subsystems

| Phase | Subsystem | Class | Thread | Purpose |
|-------|-----------|-------|--------|---------|
| 1 | Frame Buffer | `FrameRingBuffer` | shared | Bounded deque, prevents OOM |
| 1 | Analysis | `FrameAnalysisWorker` | daemon | CV processing off main thread |
| 1 | Watchdog | `CameraWatchdog` | Kivy Clock | Detects camera stalls, auto-reconnects |
| 1 | Recording | `DashcamRecorder` | daemon | Continuous JPEG segments, auto-prune |
| 1 | Telemetry | `TelemetryReceiver` | daemon | Consumes service.py UDP broadcasts |
| 2 | Hashing | `EvidenceHasher` | main | SHA-256 tamper detection |
| 2 | Watermark | `EvidenceWatermark` | main | Burns GPS/timestamp onto images |
| 2 | Report Log | `ReportLog` | main | Append-only JSONL history |
| 3 | Queue | `OfflineReportQueue` | main | Stores reports as JSON files |
| 3 | Connectivity | `ConnectivityChecker` | daemon | Socket probe to 8.8.8.8:53 |
| 3 | Retry | `QueueRetryDaemon` | daemon | Auto-retries queued reports |
| 4 | ONNX | `ONNXDetector` | main | Optional plate detection model |
| 4 | Speed Zones | `SpeedZoneChecker` | main | Haversine proximity + speed limits |
| 4 | Status | `SubsystemStatus` | main | Health aggregator for all subsystems |
| 4 | Brake Log | `HarshBrakeLog` | main | JSONL event log with debounce |

---

## What Each Fix Does

| # | Problem | Fix |
|---|---------|-----|
| 1 | `opencv-python-headless` not a p4a recipe | Changed to `opencv` |
| 2 | `reverse_geocoder` needs scipy (no p4a recipe) | Changed to `reverse_geocode` (pure Python) |
| 3 | `texture.pixels` polling crashes on Android | Subclassed Preview with `analyze_pixels_callback` |
| 4 | Camera connects before permission granted | Moved to grant callback |
| 5 | `__file__` path read-only inside APK | Changed to `App.user_data_dir` |
| 6 | Camera never disconnected | Added `on_stop()` → `disconnect_camera()` |
| 7 | Missing `camerax_provider` + `gestures4kivy` + `p4a.hook` | Added all three |

---

## Troubleshooting

**Black camera screen:**
- Verify `camerax_provider/gradle_options.py` exists
- Verify `p4a.hook = camerax_provider/gradle_options.py` in buildozer.spec
- Run `buildozer appclean` then rebuild

**App crashes on launch:**
- Connect USB, run `adb logcat -s python:D` to see Python errors
- Common: `ModuleNotFoundError` means a requirement is wrong

**Background service stops after 10 min:**
- Settings → Apps → Sentinel-X → Battery → **Unrestricted**

**Email doesn't send:**
- plyer.email opens your email app (Gmail, etc). You tap Send manually.
- This is by design — no silent sending, for legal compliance.

---

## License

MIT License — see LICENSE for details.
