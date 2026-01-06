# -*- coding: utf-8 -*-
"""
Sentinel-X Background Worker (Android service)
Responsibilities:
- Sensor polling: GPS + Accelerometer
- Harsh braking algorithm (10Hz):
  G_total = sqrt(x^2 + y^2 + z^2)
  G_dyn   = |G_total - 9.81|
  Trigger alert if G_dyn > 4.0 m/s^2
- Socket (UDP) communication to UI (main.py) at 127.0.0.1:17888
- Persistence: WakeLock via PyJnius to reduce kill when screen off
"""

import time
import json
import math  # REQUIRED for sqrt in g-force formula
import socket

from kivy.utils import platform

# Crash-safe imports
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
    """
    Acquire PARTIAL_WAKE_LOCK to keep CPU running while screen is off.
    """
    if platform != "android" or autoclass is None:
        return None
    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService

        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")
        pm = service.getSystemService(Context.POWER_SERVICE)

        tag = "SentinelX:TelemetryWakeLock"
        wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, tag)
        wl.setReferenceCounted(False)
        wl.acquire()
        return wl
    except Exception:
        return None


def get_last_known_location():
    """
    Best-effort GPS using Android LocationManager.getLastKnownLocation (no online API).
    Returns (lat, lon, speed_mps) where speed_mps may be 0 if unavailable.
    """
    if platform != "android" or autoclass is None:
        return 0.0, 0.0, 0.0

    try:
        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService

        Context = autoclass("android.content.Context")
        LocationManager = autoclass("android.location.LocationManager")
        lm = service.getSystemService(Context.LOCATION_SERVICE)

        # Try GPS provider first, then network
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
    """
    Returns accelerometer (x,y,z) in m/s^2 (best-effort via plyer).
    """
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
    wl = acquire_wakelock()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # 10Hz sampling
    interval = 0.1

    while True:
        try:
            lat, lon, speed_mps = get_last_known_location()

            x, y, z = read_accel_xyz()

            # Physics as specified:
            # G_total = sqrt(x^2 + y^2 + z^2)
            # G_dyn = |G_total - 9.81|
            g_total = math.sqrt((x * x) + (y * y) + (z * z))
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
            # never die; service should keep running
            pass

        time.sleep(interval)


if __name__ == "__main__":
    main()
