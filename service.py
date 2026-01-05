# service.py
import time
import json
import socket
import math
from plyer import gps, accelerometer
from kivy.utils import platform

class SentinelService:
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server_address = ('127.0.0.1', 9000)
        self.location = {"lat": 0.0, "lon": 0.0}
        self.harsh_threshold = 4.0 # m/s^2 (Standard for dangerous driving)

    def start(self):
        # Configure GPS
        try:
            gps.configure(on_location=self.on_location)
            gps.start(minTime=1000, minDistance=1)
            accelerometer.enable()
        except:
            pass # Handle desktop testing

        # Infinite Loop
        while True:
            self.tick()
            time.sleep(0.5)

    def on_location(self, **kwargs):
        self.location["lat"] = kwargs.get('lat', 0.0)
        self.location["lon"] = kwargs.get('lon', 0.0)

    def tick(self):
        # 1. Check Accelerometer for Harsh Braking
        event = None
        try:
            val = accelerometer.acceleration
            if val:
                x, y, z = val
                total_force = math.sqrt(x**2 + y**2 + z**2)
                dynamic_force = abs(total_force - 9.81) # Subtract Gravity
                
                if dynamic_force > self.harsh_threshold:
                    event = "HARSH_BRAKING"
        except:
            pass

        # 2. Package Data
        payload = {
            "lat": self.location["lat"],
            "lon": self.location["lon"],
            "event": event
        }

        # 3. Send to UI
        self.sock.sendto(json.dumps(payload).encode(), self.server_address)

if __name__ == '__main__':
    from jnius import autoclass
    # Prevent Android from killing this process
    PythonService = autoclass('org.kivy.android.PythonService')
    PythonService.mService.setAutoRestartService(True)
    
    service = SentinelService()
    service.start()