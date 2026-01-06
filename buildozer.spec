[app]
title = Sentinel-X
package.name = sentinelx
package.domain = org.sentinelx
source.dir = .
source.include_exts = py,png,jpg,kv,json,txt,onnx

version = 1.0.0
orientation = portrait
fullscreen = 0

requirements = python3,kivy==2.2.1,camera4kivy,plyer,numpy,android,requests,opencv-python-headless,reverse_geocoder

services = service:service.py

android.api = 33
android.minapi = 26
android.sdk = 33
android.ndk = 25b

# pin build-tools
android.sdk_build_tools = 33.0.2
android.accept_sdk_license = True

android.permissions = CAMERA,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,INTERNET,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE,WAKE_LOCK

android.archs = arm64-v8a,armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 0
