[app]
title = Sentinel-X
package.name = sentinelx
package.domain = org.sentinelx
version = 0.3.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt,onnx

requirements = python3,kivy==2.2.1,camera4kivy,plyer,numpy,android,requests,opencv-python-headless,reverse_geocoder

orientation = portrait
fullscreen = 0

android.api = 33
android.minapi = 24
android.ndk = 25b
android.sdk = 33
android.archs = arm64-v8a,armeabi-v7a

# Prevent CI trying to install build-tools 36.x (AIDL missing / license prompts)
android.accept_sdk_license = True
android.sdk_build_tools = 33.0.2

# Permissions (exact as required)
android.permissions = CAMERA,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,INTERNET,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE,WAKE_LOCK

# Background service
services = service:service.py

android.enable_androidx = True
android.private_storage = True

log_level = 2
