[app]
title = Sentinel-X
package.name = sentinelx
package.domain = org.sentinelx
source.dir = .
source.include_exts = py,png,jpg,kv,json,txt,onnx

version = 1.0.0
orientation = portrait
fullscreen = 0

# Modeled on https://github.com/Android-for-Python/c4k_opencv_example
# FIX #1: opencv (p4a recipe), NOT opencv-python-headless
# FIX #2: reverse_geocode (pure Python), NOT reverse_geocoder (needs scipy)
# FIX #7: gestures4kivy is REQUIRED by camera4kivy
requirements = python3,kivy,camera4kivy,gestures4kivy,plyer,numpy,android,opencv,reverse_geocode

services = service:service.py

# FIX #7: CRITICAL — without this line camera shows black screen on Android
p4a.hook = camerax_provider/gradle_options.py

android.api = 33
android.minapi = 26
android.sdk = 33
android.ndk = 25b
android.sdk_build_tools = 33.0.2
android.accept_sdk_license = True

android.permissions = CAMERA,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,INTERNET,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE,WAKE_LOCK

# opencv p4a recipe only compiles 64-bit
android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 0
