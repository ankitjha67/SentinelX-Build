[app]
title = Sentinel-X
package.name = sentinelx
package.domain = org.sentinelx
source.dir = .
source.include_exts = py,png,jpg,kv,json,txt,onnx

version = 1.5.0
# 'all' lets the phone rotate to landscape for capturing wide number plates while
# keeping the portrait form usable. p4a's activity sets a broad configChanges, so
# rotating does not restart the app or the camera.
orientation = all
fullscreen = 0

icon.filename = %(source.dir)s/icon.png

# NOTE: reverse_geocode / reverse_geocoder are intentionally excluded — they import
# scipy (cKDTree), which cannot cross-compile for Android. main.py falls back to the
# bundled pure-Python IndiaGeocoder for on-device GPS->state routing.
requirements = python3,kivy,camera4kivy,gestures4kivy,plyer,numpy,android,opencv,pyjnius

services = service:service.py

p4a.hook = camerax_provider/gradle_options.py

# Pin python-for-android to the v2024.01.21 release. Buildozer clones its own p4a
# (default branch = master), so a pip pin has no effect — this is the real lever.
# That release's numpy recipe is 1.22.3, built via classic setup.py (no meson/ninja),
# which cross-compiles cleanly on NDK r25b. Newer p4a ships numpy 2.x (meson) that
# fails to build under NDK r25b's clang.
p4a.fork = kivy
p4a.branch = v2024.01.21

android.api = 33
android.minapi = 26
android.sdk = 33
android.ndk = 25b
android.sdk_build_tools = 33.0.2
android.accept_sdk_license = True

android.permissions = CAMERA,ACCESS_FINE_LOCATION,ACCESS_COARSE_LOCATION,ACCESS_BACKGROUND_LOCATION,INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,FOREGROUND_SERVICE,WAKE_LOCK,REQUEST_INSTALL_PACKAGES

android.archs = arm64-v8a

[buildozer]
log_level = 2
warn_on_root = 0
