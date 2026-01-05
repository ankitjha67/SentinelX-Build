[app]
# (str) Title of your application
title = SentinelX
# (str) Package name
package.name = sentinelx
# (str) Package domain (needed for android/ios packaging)
package.domain = org.civic.enforce

# (str) Source code where the main.py live
source.dir =.
# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,tflite

# (str) Application versioning (method 1)
version = 1.0

# (list) Application requirements
# reverse_geocoder requires C compilation, handled by GitHub Actions
# Core requirements
requirements = python3,kivy==2.2.1,camera4kivy,plyer,numpy,android,requests,opencv-python-headless

# (str) Supported orientation (one of landscape, portrait or all)
orientation = portrait

# (list) Permissions
android.permissions = CAMERA,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,INTERNET,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE,WAKE_LOCK

# (list) Services to declare
# NAME:PATH_TO_FILE
android.services = sentinel_service:service.py

# (int) Target Android API, should be as high as possible.
android.api = 33
android.minapi = 24

# (list) The Android Archs to build for, currently defaults to armeabi-v7a
android.archs = arm64-v8a

[buildozer]
# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

warn_on_root = 1


