[app]
title = Sentinel-X
package.name = sentinelx
package.domain = org.sentinelx
source.dir = .
source.include_exts = py,png,jpg,kv,json,txt,onnx

version = 1.0.2
orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icon.png

requirements = python3,kivy,camera4kivy,gestures4kivy,plyer,numpy,android,opencv,reverse_geocode

services = service:service.py

p4a.hook = camerax_provider/gradle_options.py

android.api = 33
android.minapi = 26
android.sdk = 33
android.ndk = 25b
android.sdk_build_tools = 33.0.2
android.accept_sdk_license = True

# Added ACCESS_BACKGROUND_LOCATION for GPS to work when screen off
android.permissions = CAMERA,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,ACCESS_BACKGROUND_LOCATION,INTERNET,WRITE_EXTERNAL_STORAGE,FOREGROUND_SERVICE,WAKE_LOCK

android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 0
