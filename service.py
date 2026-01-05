# -*- coding: utf-8 -*-
"""
Sentinel-X Background Service (Android)

Responsibilities:
- Sensor polling (GPS + Accelerometer) using PyJnius
- Harsh braking algorithm @ ~10Hz:
    G_total = sqrt(x^2 + y^2 + z^2)
    G_dyn = |G_total - 9.81|
    Trigger if G_dyn > 4.0 m/s^2
- UDP socket communication to UI (localhost:5055)
- Persistence: acquire WakeLock + run as Foreground Service (notification)
"""

import json
import time
import socket
import threading
import math  # AUDIT REQUIREMENT: math is imported for sqrt

UDP_HOST = "127.0.0.1"
UDP_PORT = 5055

G_STANDARD = 9.81
G_DYN_THRESHOLD = 4.0
SAMPLE_INTERVAL_SEC = 0.1  # 10Hz

telemetry = {
    "lat": 0.0,
    "lon": 0.0,
    "speed_mps": 0.0,
    "g_dyn": 0.0,
    "ts": 0,
    "last_event": "",
}

_last_harsh_trigger_ts = 0.0
_running = True


def _udp_send(payload: dict):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(json.dumps(payload).encode("utf-8"), (UDP_HOST, UDP_PORT))
        s.close()
    except Exception:
        pass


def _start_android_foreground_and_wakelock():
    """
    Foreground service + WakeLock so Android doesn't kill it when screen is off.
    Uses PyJnius and PythonService context.
    """
    try:
        from jnius import autoclass, cast
        from android.runnable import run_on_ui_thread

        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        context = service.getApplicationContext()

        Context = autoclass("android.content.Context")
        PowerManager = autoclass("android.os.PowerManager")

        # WakeLock (PARTIAL)
        pm = cast("android.os.PowerManager", context.getSystemService(Context.POWER_SERVICE))
        wl = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "SentinelX:WakeLock")
        wl.setReferenceCounted(False)
        wl.acquire()

        # Foreground notification
        BuildVersion = autoclass("android.os.Build$VERSION")
        BuildVersionCodes = autoclass("android.os.Build$VERSION_CODES")
        NotificationManager = autoclass("android.app.NotificationManager")
        Notification = autoclass("android.app.Notification")
        NotificationChannel = autoclass("android.app.NotificationChannel")
        NotificationBuilder = autoclass("android.app.Notification$Builder")

        channel_id = "sentinelx_service"
        nm = cast("android.app.NotificationManager", context.getSystemService(Context.NOTIFICATION_SERVICE))

        if BuildVersion.SDK_INT >= BuildVersionCodes.O:
            channel = NotificationChannel(channel_id, "Sentinel-X Service", NotificationManager.IMPORTANCE_LOW)
            nm.createNotificationChannel(channel)

        @run_on_ui_thread
        def _start_fg():
            if BuildVersion.SDK_INT >= BuildVersionCodes.O:
                builder = NotificationBuilder(context, channel_id)
            else:
                builder = NotificationBuilder(context)
            builder.setContentTitle("Sentinel-X running")
            builder.setContentText("Monitoring sensors (GPS + accelerometer)")
            builder.setSmallIcon(17301620)  # android.R.drawable.ic_menu_mylocation (numeric fallback)
            notif = builder.build()
            service.startForeground(1, notif)

        _start_fg()
        return wl

    except Exception:
        return None


def _register_sensors_and_location():
    """
    Registers:
    - Accelerometer listener
    - GPS location updates via LocationManager

    Updates global telemetry dict; emits HARSH_BRAKE events over UDP.
    """
    try:
        from jnius import autoclass, cast, PythonJavaClass, java_method

        PythonService = autoclass("org.kivy.android.PythonService")
        service = PythonService.mService
        context = service.getApplicationContext()

        # --- Accelerometer ---
        SensorManager = autoclass("android.hardware.SensorManager")
        Sensor = autoclass("android.hardware.Sensor")
        Context = autoclass("android.content.Context")

        sm = cast("android.hardware.SensorManager", context.getSystemService(Context.SENSOR_SERVICE))
        accel = sm.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)

        class AccelListener(PythonJavaClass):
            __javainterfaces__ = ["android/hardware/SensorEventListener"]
            __javacontext__ = "app"

            def __init__(self):
                super().__init__()
                self._last_sample = 0.0

            @java_method("(Landroid/hardware/SensorEvent;)V")
            def onSensorChanged(self, event):
                global _last_harsh_trigger_ts
                try:
                    now = time.time()
                    if now - self._last_sample < SAMPLE_INTERVAL_SEC:
                        return
                    self._last_sample = now

                    vals = event.values
                    x = float(vals[0])
                    y = float(vals[1])
                    z = float(vals[2])

                    g_total = math.sqrt((x * x) + (y * y) + (z * z))
                    g_dyn = abs(g_total - G_STANDARD)

                    telemetry["g_dyn"] = g_dyn
                    telemetry["ts"] = int(now)

                    if g_dyn > G_DYN_THRESHOLD and (now - _last_harsh_trigger_ts) > 3.0:
                        _last_harsh_trigger_ts = now
                        payload = {
                            "event": "HARSH_BRAKE",
                            "g_dyn": g_dyn,
                            "ts": int(now),
                        }
                        _udp_send(payload)
                except Exception:
                    pass

            @java_method("(Landroid/hardware/Sensor;I)V")
            def onAccuracyChanged(self, sensor, accuracy):
                return

        accel_listener = AccelListener()
        # SENSOR_DELAY_GAME is typically fast; we throttle to 10Hz ourselves
        sm.registerListener(accel_listener, accel, SensorManager.SENSOR_DELAY_GAME)

        # --- GPS Location ---
        LocationManager = autoclass("android.location.LocationManager")
        Criteria = autoclass("android.location.Criteria")

        class LocListener(PythonJavaClass):
            __javainterfaces__ = ["android/location/LocationListener"]
            __javacontext__ = "app"

            @java_method("(Landroid/location/Location;)V")
            def onLocationChanged(self, location):
                try:
                    telemetry["lat"] = float(location.getLatitude())
                    telemetry["lon"] = float(location.getLongitude())
                    telemetry["speed_mps"] = float(location.getSpeed() or 0.0)
                    telemetry["ts"] = int(time.time())
                except Exception:
                    pass

            @java_method("(Ljava/lang/String;)V")
            def onProviderDisabled(self, provider):
                return

            @java_method("(Ljava/lang/String;)V")
            def onProviderEnabled(self, provider):
                return

            @java_method("(Ljava/lang/String;ILandroid/os/Bundle;)V")
            def onStatusChanged(self, provider, status, extras):
                return

        lm = cast("android.location.LocationManager", context.getSystemService(Context.LOCATION_SERVICE))
        loc_listener = LocListener()

        # Prefer GPS provider; fallback to best provider
        provider = LocationManager.GPS_PROVIDER
        if not lm.isProviderEnabled(provider):
            criteria = Criteria()
            provider = lm.getBestProvider(criteria, True)

        # minTime=1000ms, minDistance=0m (UI gets ~1Hz; accel is 10Hz)
        if provider:
            lm.requestLocationUpdates(provider, 1000, 0, loc_listener)

        return True

    except Exception:
        return False


def _telemetry_broadcaster_loop():
    """
    Sends periodic telemetry updates to UI (1Hz).
    """
    while _running:
        try:
            payload = dict(telemetry)
            _udp_send(payload)
        except Exception:
            pass
        time.sleep(1.0)


def main():
    wl = _start_android_foreground_and_wakelock()
    ok = _register_sensors_and_location()

    # Start broadcaster loop
    t = threading.Thread(target=_telemetry_broadcaster_loop, daemon=True)
    t.start()

    # Keep service alive
    while True:
        time.sleep(2.0)


if __name__ == "__main__":
    main()
