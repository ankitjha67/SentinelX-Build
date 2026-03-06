# Sentinel-X — Civic Enforcement System

AI-powered traffic violation reporting app for Android. Captures evidence, detects number plates, routes reports to the correct police authority, and protects the reporter under India's Good Samaritan Law (Section 134A).

**Target:** Android 10+ (arm64-v8a)
**Stack:** Python + Kivy + camera4kivy + OpenCV + Buildozer

---

## Features

- **Camera** — Live preview via CameraX, photo capture with evidence timestamping
- **Night Vision** — CLAHE enhancement for low-light/fog number plate visibility
- **CV Assist** — Real-time contour detection for plate-like regions (worker thread)
- **Harsh Braking** — Background 10Hz accelerometer monitoring (G_dyn > 4.0 m/s² threshold)
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

All 69 tests must pass before building.

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
├── main.py                    ← App (all 7 fixes applied)
├── service.py                 ← Background GPS + accelerometer service
├── buildozer.spec             ← Android build config
├── setup.sh                   ← One-time setup script
├── tests/
│   ├── conftest.py
│   └── test_sentinelx.py      ← 69 unit tests
├── .github/workflows/
│   └── build.yml              ← CI: test → build APK
├── .gitignore
├── models/                    ← Drop a detector.onnx here (optional)
└── evidence/                  ← Captured photos (auto-created, gitignored)
```

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
