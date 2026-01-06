# -*- coding: utf-8 -*-
"""
Sentinel-X Background Worker (Android service)
- GPS + Accelerometer polling
- Harsh braking / dangerous driving physics:
  G_total = sqrt(x^2 + y^2 + z^2)
  G_dyn   = |G_total - 9.81|
  Trigger threshold: G_dyn > 4.0 m/s^2
- Sampling: 10Hz (0.1s)
- WakeLock via PyJnius
- Sends telemetry JSON to UI via UDP 127.0.0.1:17888
"""

import time
import json
import math  # REQUIRED (your audit instruction)
import socket
from kivy.utils import platform

try:
    from jnius import autoclass  # type: ignore
except Exception:
    autoclass = None

try:
    from plyer import accelerometer  # type: ignore
except Exception:
    accelerometer = None

UDP_HOST = "127.0.0.1"
UDP_PORT = 17888


def acquire_wakelock():
    if platform != "android" or autoclass is None:
        return None
    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")
        pm = service.getSystemService(Context.POWER_SERVICE)
        wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "SentinelX:WakeLock")
        wl.setReferenceCounted(False)
        wl.acquire()
        return wl
    except Exception:
        return None


def get_last_known_location():
    if platform != "android" or autoclass is None:
        return 0.0, 0.0, 0.0
    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        Context = autoclass("android.content.Context")
        LocationManager = autoclass("android.location.LocationManager")
        lm = service.getSystemService(Context.LOCATION_SERVICE)

        loc = lm.getLastKnownLocation(LocationManager.GPS_PROVIDER)
        if loc is None:
            loc = lm.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
        if loc is None:
            return 0.0, 0.0, 0.0

        lat = float(loc.getLatitude())
        lon = float(loc.getLongitude())
        try:
            speed = float(loc.getSpeed())  # m/s
        except Exception:
            speed = 0.0
        return lat, lon, speed
    except Exception:
        return 0.0, 0.0, 0.0


def read_accel_xyz():
    if accelerometer is None:
        return 0.0, 0.0, 9.81
    try:
        if not accelerometer.enabled:
            accelerometer.enable()
        x, y, z = accelerometer.acceleration  # type: ignore
        if x is None or y is None or z is None:
            return 0.0, 0.0, 9.81
        return float(x), float(y), float(z)
    except Exception:
        return 0.0, 0.0, 9.81


def main():
    _wl = acquire_wakelock()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    interval = 0.1  # 10Hz
    while True:
        try:
            lat, lon, speed_mps = get_last_known_location()
            x, y, z = read_accel_xyz()

            g_total = math.sqrt(x * x + y * y + z * z)
            g_dyn = abs(g_total - 9.81)

            payload = {
                "ts": time.time(),
                "lat": lat,
                "lon": lon,
                "speed_mps": speed_mps,
                "x": x,
                "y": y,
                "z": z,
                "g_total": g_total,
                "g_dyn": g_dyn,
                "harsh_brake": bool(g_dyn > 4.0),
            }
            sock.sendto(json.dumps(payload).encode("utf-8"), (UDP_HOST, UDP_PORT))
        except Exception:
            pass

        time.sleep(interval)


if __name__ == "__main__":
    main()
