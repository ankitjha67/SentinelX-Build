🛡️ Sentinel-X: The Civic Enforcement System
Sentinel-X is an advanced, AI-powered traffic enforcement application designed to empower citizens under India's Good Samaritan Law. It transforms a standard Android smartphone into a sophisticated telematics and violation reporting device.
⚠️ Status: Active Development (v1.0)
🎯 Target OS: Android 10+
🏗️ Build Method: Cloud-Native (GitHub Actions)
🌟 Key Features
1. 🧠 Intelligent Violation Detection
•	Night & Fog Vision: Uses CLAHE (Contrast Limited Adaptive Histogram Equalization) to enhance visibility of number plates in low-light or poor weather conditions.
•	Harsh Braking Monitor: A background service runs continuously (even when the app is closed), monitoring G-forces. If a deceleration > 4.0 m/s² is detected, it automatically flags a "Dangerous Driving" event.
2. ⚖️ Automated Jurisdiction Routing
•	One Nation, One Challan Logic: The app intelligently routes violation reports to two agencies simultaneously:
1.	Local Police: Based on your GPS location (e.g., if you are in Gurugram, it emails Gurugram Traffic Police).
2.	Vehicle Registry: Based on the number plate (e.g., if a DL plate is caught in HR, Delhi Police is also notified).
•	Offline Geocoding: Uses a K-D Tree algorithm to determine the District and State without requiring an internet connection.
3. 🛡️ Good Samaritan Protection
•	Anonymity First: By default, reports are submitted anonymously. The email body explicitly invokes Section 134A of the Motor Vehicles Act, 2019, protecting the reporter from being forced to be a witness.
________________________________________
⚙️ Setup & Configuration (CRITICAL STEP)
Before building the app, you must add your sender credentials. The app sends emails on your behalf to the police.
1.	Open main.py in your repository.
2.	Search for the send_email function (around line 250).
3.	Locate these variables:
Python
sender_email = "your_app_email@gmail.com"
sender_password = "your_app_password"
4.	Update them:
o	Email: Use a dedicated Gmail address for this app (recommended).
o	Password: Do NOT use your login password. Go to your(https://myaccount.google.com/apppasswords) and generate a 16-character App Password. Paste that here.
________________________________________
📲 Installation Guide
1.	Download: Go to the Actions tab in this repository, click the latest successful workflow run, and download the SentinelX_Release zip file.
2.	Install: Extract the .apk file and transfer it to your phone.
3.	Permissions: Upon first launch, you must grant the following permissions for the background service to work:
o	Camera: For evidence capture.
o	Location: Select "Allow all the time". (If you select "Only while using the app", the Harsh Braking monitor will fail when the screen turns off).
o	Battery: If the app stops after 10 minutes, go to Settings > Apps > SentinelX > Battery and select "Unrestricted".
________________________________________
🏗️ How to Build (Windows Users)
You do not need to install anything on your computer. We use GitHub Actions to build the app in the cloud.
1.	Fork/Clone this repository.
2.	Ensure main.py, service.py, buildozer.spec, and .github/workflows/build.yml are present.
3.	Navigate to the Actions tab.
4.	Select the Build SentinelX APK workflow.
5.	The build will start automatically on every push (every time you update code).
6.	Wait approx. 15-20 minutes.
7.	Download the Artifact from the workflow summary page.
________________________________________
🧩 Technical Architecture
Component	Technology	Purpose
UI Framework	Kivy (Python)	Cross-platform touch interface.
Camera	Camera4Kivy	High-performance preview buffer access.
Background Service	PyJnius + Plyer	Persistent process for GPS/Accelerometer monitoring.
Logic Core	SQLite	Local database for tracking repeat offenders.
Compiler	Buildozer	Packages Python code into Android APK.
________________________________________
📜 Legal Disclaimer
This software is a tool for civic assistance. The developer assumes no liability for the accuracy of reports or legal consequences. Users are strictly advised not to operate the application while driving. Always adhere to local traffic laws.

