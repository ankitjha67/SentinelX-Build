[app]
title = Sentinel-X
package.name = sentinelx
package.domain = org.sentinelx
version = 0.1.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,txt

# Requirements (per spec)
requirements = python3,kivy==2.2.1,camera4kivy,plyer,numpy,android,requests,opencv-python-headless,reverse_geocoder

orientation = portrait
fullscreen = 0

# Android target (per spec)
android.api = 33
android.minapi = 24
android.ndk = 25b
android.sdk = 33
android.archs = arm64-v8a,armeabi-v7a

# Permissions (per spec)
android.permissions = CAMERA,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,INTERNET,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE,WAKE_LOCK

# Background service
services = service:service.py

# Helpful defaults
android.enable_androidx = True
android.private_storage = True

# (Optional) Reduce build noise
log_level = 2
