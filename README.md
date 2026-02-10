🛡️ Sentinel-X: The Civic Enforcement System

Sentinel-X is an advanced, AI-powered traffic enforcement application designed to empower citizens under India's Good Samaritan Law. It transforms a standard Android smartphone into a sophisticated telematics and violation reporting device.

⚠️ Status: Active Development (v1.0)
🎯 Target OS: Android 10+ (API 26+)
🏗️ Build Method: Cloud-Native (GitHub Actions)

---

## 🌟 Key Features

### 1. 🧠 Intelligent Violation Detection

* **Night & Fog Vision**: Uses CLAHE (Contrast Limited Adaptive Histogram Equalization) to enhance visibility of number plates in low-light or poor weather conditions.
* **Harsh Braking Monitor**: A background service runs continuously (even when the app is closed), monitoring G-forces via accelerometer. If a deceleration > 4.0 m/s² is detected, it automatically flags a "Dangerous Driving" event with a visible red warning banner.
* **Live CV Assist**: Real-time computer vision analysis during camera preview to detect plate-like regions.

### 2. ⚖️ Automated Jurisdiction Routing

* **One Nation, One Challan Logic**: The app intelligently routes violation reports to two agencies simultaneously:
  1. **Local Police**: Based on your GPS location (e.g., if you are in Gurugram, it emails Gurugram Traffic Police).
  2. **Vehicle Registry**: Based on the number plate (e.g., if a DL plate is caught in HR, Delhi Police is also notified).
* **Offline Geocoding**: Uses reverse_geocoder with K-D Tree algorithm to determine the District and State without requiring an internet connection.

### 3. 🛡️ Good Samaritan Protection

* **Anonymity First**: By default, reports are submitted anonymously. The email body explicitly invokes Section 134A of the Motor Vehicles Act, 2019, protecting the reporter from being forced to be a witness.

### 4. 📊 Report History & Audit Trail

* **JSON-based History**: After successfully opening the email composer, a detailed JSON record is saved to `./reports/report_YYYYMMDD_HHMMSS.json` with all details: timestamp, GPS, plate, offense, recipients, evidence path, and anonymous flag.

### 5. ✅ Number Plate Validation

* **Real-time Validation**: As you type the plate number, the app validates it against common Indian plate patterns (e.g., `XX00XX0000` or `XX00X0000`) and shows hints if the format is incorrect.

---

## ⚙️ Email Architecture

**IMPORTANT**: This app uses the **device's native email composer** via Plyer's email facade. It does NOT send emails directly using SMTP.

### How Email Works:
1. When you tap "Send Report", the app prepares the email body with all violation details.
2. The app calls the Android system's email intent, which opens your default email app (Gmail, Outlook, etc.) with:
   - **Pre-filled recipients**: Automatically determined based on location and plate code
   - **Subject**: Report title with plate and violation
   - **Body**: Complete report with GPS, timestamp, offense details, and Good Samaritan footer
   - **Attachment**: Evidence photo (if captured)
3. **You review and send** the email from your email app.

**No SMTP credentials required** — the app simply opens your email composer. You maintain full control over what gets sent.

---

## 📲 Installation Guide

1. **Download**: Go to the **Actions** tab in this repository, click the latest successful workflow run, and download the SentinelX_Release zip file.
2. **Install**: Extract the `.apk` file and transfer it to your phone. Install it (you may need to enable "Install from Unknown Sources").
3. **Permissions**: Upon first launch, you must grant the following permissions for the background service to work:
   * **Camera**: For evidence capture.
   * **Location**: Select **"Allow all the time"**. (If you select "Only while using the app", the Harsh Braking monitor will fail when the screen turns off).
   * **Battery**: If the app stops after 10 minutes, go to Settings > Apps > SentinelX > Battery and select **"Unrestricted"**.

---

## 🏗️ How to Build (Windows Users)

You do not need to install anything on your computer. We use **GitHub Actions** to build the app in the cloud.

1. Fork/Clone this repository.
2. Ensure `main.py`, `service.py`, `buildozer.spec`, and `.github/workflows/build.yml` are present.
3. Navigate to the **Actions** tab.
4. Select the **Build SentinelX APK** workflow.
5. The build will start automatically on every push (every time you update code).
6. Wait approx. 15-20 minutes.
7. Download the **Artifact** from the workflow summary page.

---

## 🧩 Technical Architecture

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **UI Framework** | Kivy (Python) | Cross-platform touch interface. |
| **Camera** | Camera4Kivy | High-performance preview buffer access. |
| **Background Service** | PyJnius + Plyer | Persistent process for GPS/Accelerometer monitoring via Android service. |
| **Vision Enhancement** | OpenCV + CLAHE | Night/fog enhancement for better plate visibility. |
| **Geocoding** | reverse_geocoder | Offline K-D tree-based location lookup. |
| **Email** | Plyer email facade | Opens device email composer (no SMTP). |
| **Build System** | Buildozer + python-for-android | Packages Python code into Android APK. |

### Background Service Architecture

The background service (`service.py`) runs independently using Android's foreground service mechanism:
- **Telemetry Collection**: Polls GPS location and accelerometer at 10Hz (0.1s intervals)
- **Physics Calculation**: Computes `G_dyn = |sqrt(x² + y² + z²) - 9.81|`
- **UDP Communication**: Sends telemetry JSON to main app via localhost UDP (port 17888)
- **WakeLock**: Maintains partial wakelock to keep service running when screen is off

---

## 📜 Legal Disclaimer

This software is a tool for civic assistance under India's Good Samaritan Law (Motor Vehicles Act Section 134A). The developer assumes no liability for the accuracy of reports or legal consequences. Users are strictly advised **not to operate the application while driving**. Always adhere to local traffic laws.

---

## 🔧 Developer Notes

### Building the APK

The repository includes a complete `buildozer.spec` configuration:
- **Python packages**: kivy==2.2.1, camera4kivy, plyer, numpy, opencv (p4a recipe), reverse_geocoder
- **Android API**: Targets API 33 (Android 13) with minimum API 26 (Android 8)
- **Service**: Foreground service declared as `Telemetry:service.py:foreground`
- **Permissions**: Camera, GPS (fine/coarse), Internet, Storage (API 33+ uses READ_MEDIA_IMAGES), Foreground Service, WakeLock

### Code Quality & Security

- All crash-prone imports are wrapped in try/except
- Socket resources properly cleaned up with try/finally
- Background threads for blocking operations (geocoding, service communication)
- Lambda closures use default arguments to capture by value
- Camera lifecycle properly handled with on_pause/on_resume

---

## 🤝 Contributing

Contributions are welcome! Please ensure:
1. All existing features remain functional
2. Code follows the existing style and structure
3. Test on actual Android devices when possible
4. Update documentation for significant changes

---

**Version**: 1.0.0
**License**: See repository license file
**Support**: Open an issue on GitHub for bugs or feature requests

