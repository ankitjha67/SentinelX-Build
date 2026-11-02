# -*- coding: utf-8 -*-
"""Sentinel-X Background Service — GPS + Accelerometer at 10Hz via UDP."""

import time, json, math, socket
from kivy.utils import platform

try:
    from jnius import autoclass, PythonJavaClass, java_method
except Exception:
    autoclass = None
    PythonJavaClass = object
    java_method = None

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


if java_method is not None:
    class _AccelListener(PythonJavaClass):
        """SensorEventListener bound to the *service* context.

        plyer's accelerometer resolves PythonActivity.mActivity, which is None
        inside the service process, so it silently fell back to (0, 0, 9.81)
        and g_dyn was always 0. Registering directly with the service's
        SensorManager gives real readings.
        """
        __javainterfaces__ = ["android/hardware/SensorEventListener"]

        def __init__(self):
            super().__init__()
            self.values = None

        @java_method("(Landroid/hardware/SensorEvent;)V")
        def onSensorChanged(self, event):
            self.values = tuple(event.values[:3])

        @java_method("(Landroid/hardware/Sensor;I)V")
        def onAccuracyChanged(self, sensor, accuracy):
            pass
else:
    _AccelListener = None


def start_accel():
    """Register an accelerometer listener; returns it (or None off-device)."""
    if platform != "android" or autoclass is None or _AccelListener is None:
        return None
    try:
        svc = autoclass("org.kivy.android.PythonService").mService
        Context = autoclass("android.content.Context")
        Sensor = autoclass("android.hardware.Sensor")
        SensorManager = autoclass("android.hardware.SensorManager")
        sm = svc.getSystemService(Context.SENSOR_SERVICE)
        sensor = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        if sensor is None:
            return None
        listener = _AccelListener()
        sm.registerListener(listener, sensor, SensorManager.SENSOR_DELAY_GAME)
        return listener
    except Exception:
        return None


def read_accel(listener):
    """Returns (x, y, z, ok). ok is False when no live sensor reading exists."""
    vals = getattr(listener, "values", None) if listener is not None else None
    if not vals or None in vals:
        return 0.0, 0.0, 9.81, False
    return float(vals[0]), float(vals[1]), float(vals[2]), True


def main():
    _wl = acquire_wakelock()
    accel = start_accel()  # keep a reference so the listener isn't GC'd
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while True:
        try:
            lat, lon, spd = get_location()
            x, y, z, accel_ok = read_accel(accel)
            gt = math.sqrt(x*x + y*y + z*z)
            gd = abs(gt - 9.81)
            sock.sendto(json.dumps({
                "ts": time.time(), "lat": lat, "lon": lon, "speed_mps": spd,
                "x": x, "y": y, "z": z, "g_total": gt, "g_dyn": gd,
                "harsh_brake": accel_ok and gd > G_THRESHOLD,
                "accel_ok": accel_ok,
            }).encode(), (UDP_HOST, UDP_PORT))
        except Exception:
            pass
        time.sleep(0.1)


if __name__ == "__main__":
    main()
