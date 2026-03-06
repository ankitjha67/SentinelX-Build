# -*- coding: utf-8 -*-
"""Sentinel-X Background Service — GPS + Accelerometer at 10Hz via UDP."""

import time, json, math, socket
from kivy.utils import platform

try:
    from jnius import autoclass
except Exception:
    autoclass = None
try:
    from plyer import accelerometer
except Exception:
    accelerometer = None

UDP_HOST, UDP_PORT, G_THRESHOLD = "127.0.0.1", 17888, 4.0


def acquire_wakelock():
    if platform != "android" or autoclass is None:
        return None
    try:
        svc = autoclass("org.kivy.android.PythonService").mService
        pm = svc.getSystemService(autoclass("android.content.Context").POWER_SERVICE)
        wl = pm.newWakeLock(autoclass("android.os.PowerManager").PARTIAL_WAKE_LOCK, "SentinelX:WL")
        wl.setReferenceCounted(False); wl.acquire()
        return wl
    except Exception:
        return None


def get_location():
    if platform != "android" or autoclass is None:
        return 0.0, 0.0, 0.0
    try:
        svc = autoclass("org.kivy.android.PythonService").mService
        lm = svc.getSystemService(autoclass("android.content.Context").LOCATION_SERVICE)
        loc = lm.getLastKnownLocation(autoclass("android.location.LocationManager").GPS_PROVIDER)
        if loc is None:
            loc = lm.getLastKnownLocation(autoclass("android.location.LocationManager").NETWORK_PROVIDER)
        if loc is None:
            return 0.0, 0.0, 0.0
        return float(loc.getLatitude()), float(loc.getLongitude()), float(loc.getSpeed())
    except Exception:
        return 0.0, 0.0, 0.0


def read_accel():
    if accelerometer is None:
        return 0.0, 0.0, 9.81
    try:
        if not accelerometer.enabled:
            accelerometer.enable()
        x, y, z = accelerometer.acceleration
        return (float(x or 0), float(y or 0), float(z or 9.81))
    except Exception:
        return 0.0, 0.0, 9.81


def main():
    _wl = acquire_wakelock()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        try:
            lat, lon, spd = get_location()
            x, y, z = read_accel()
            gt = math.sqrt(x*x + y*y + z*z)
            gd = abs(gt - 9.81)
            sock.sendto(json.dumps({
                "ts": time.time(), "lat": lat, "lon": lon, "speed_mps": spd,
                "x": x, "y": y, "z": z, "g_total": gt, "g_dyn": gd,
                "harsh_brake": gd > G_THRESHOLD,
            }).encode(), (UDP_HOST, UDP_PORT))
        except Exception:
            pass
        time.sleep(0.1)


if __name__ == "__main__":
    main()
