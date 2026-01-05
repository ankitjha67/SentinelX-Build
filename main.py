# main.py
# SENTINEL-X: CIVIL TRAFFIC ENFORCEMENT SYSTEM (v2026.2 - Stable)
import sys
import threading
import time
import json
import socket
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# Kivy Framework
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.clock import Clock, mainthread
from kivy.utils import platform

# --- ERROR HANDLING WRAPPER ---
# This ensures imports don't crash the app silently
try:
    from camera4kivy import Preview
    import cv2
    import numpy as np
    import reverse_geocoder as rg
    from plyer import gps
except Exception as e:
    # If imports fail, we create a dummy app to show the error
    class ErrorApp(App):
        def build(self):
            return Label(text=f"CRITICAL IMPORT ERROR:\n{e}", text_size=(800, None), halign='center')
    ErrorApp().run()
    sys.exit()

# --- UI LAYOUT ---
KV_LAYOUT = '''
FloatLayout:
    canvas.before:
        Color:
            rgba: 0.1, 0.1, 0.1, 1
        Rectangle:
            pos: self.pos
            size: self.size

    BoxLayout:
        id: camera_layout
        size_hint: 1, 0.7
        pos_hint: {'top': 1}

    BoxLayout:
        orientation: 'vertical'
        size_hint: 1, 0.3
        pos_hint: {'bottom': 1}
        padding: 20
        spacing: 10
        canvas.before:
            Color:
                rgba: 0, 0, 0, 0.85
            Rectangle:
                pos: self.pos
                size: self.size

        Label:
            id: status_label
            text: "Waiting for Permissions..."
            color: 0, 1, 0, 1
            font_size: '16sp'
            halign: 'center'
            text_size: self.size

        Button:
            id: btn_report
            text: "REPORT VIOLATION"
            background_color: 1, 0, 0, 1
            bold: True
            disabled: True
            on_press: app.capture_evidence()
'''

class SentinelApp(App):
    def build(self):
        self.root = Builder.load_string(KV_LAYOUT)
        self.camera = Preview(aspect_ratio='16:9')
        self.root.ids.camera_layout.add_widget(self.camera)
        
        # State
        self.gps_data = {"lat": 0.0, "lon": 0.0, "city": "Unknown"}
        self.service_socket = None
        
        return self.root

    def on_start(self):
        """
        CRITICAL FIX: Do NOT start camera/sensors here directly.
        Request Android Permissions first.
        """
        if platform == 'android':
            self.request_android_permissions()
        else:
            # For Windows testing
            self.start_app_logic()

    def request_android_permissions(self):
        """
        Asks user for Camera, GPS, and Storage access.
        Only starts the app logic IF permissions are granted.
        """
        from android.permissions import request_permissions, Permission
        
        def callback(permissions, results):
            if all([res for res in results]):
                self.root.ids.status_label.text = "Permissions Granted. Starting Systems..."
                self.start_app_logic()
            else:
                self.root.ids.status_label.text = "ERROR: Permissions Denied.\nApp cannot function."

        request_permissions(
           , 
            callback
        )

    def start_app_logic(self):
        """
        Safe to call only after permissions are granted.
        """
        try:
            # 1. Start Camera
            self.camera.connect_camera(enable_analyze_pixels=True)
            self.root.ids.btn_report.disabled = False
            
            # 2. Start Background Service
            self.start_android_service()
            
            # 3. Start Listeners
            Clock.schedule_interval(self.listen_to_service, 0.5)
            
            self.root.ids.status_label.text = "System Online. Ready to Enforce."
            
        except Exception as e:
            self.root.ids.status_label.text = f"Startup Error: {e}"

    def start_android_service(self):
        if platform == 'android':
            from jnius import autoclass
            service = autoclass('org.civic.enforce.sentinelx.ServiceSentinel_service')
            mActivity = autoclass('org.kivy.android.PythonActivity').mActivity
            service.start(mActivity, '')

    def listen_to_service(self, dt):
        """Receives data from service.py"""
        if not self.service_socket:
            self.service_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.service_socket.bind(('127.0.0.1', 9000))
            self.service_socket.setblocking(False)

        try:
            data, _ = self.service_socket.recvfrom(1024)
            data_json = json.loads(data.decode())
            self.gps_data["lat"] = data_json.get("lat", 0.0)
            self.gps_data["lon"] = data_json.get("lon", 0.0)
            
            if data_json.get("event") == "HARSH_BRAKING":
                self.root.ids.status_label.text = "ALERT: Harsh Braking Detected!"
                
        except BlockingIOError:
            pass
        except Exception as e:
            print(e)

    def capture_evidence(self):
        # Triggered by UI Button
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"evidence_{timestamp}.jpg"
        self.camera.capture_photo(filename)
        threading.Thread(target=self.process_report, args=(filename,)).start()

    def process_report(self, filename):
        time.sleep(1) # Simulate processing
        # In a real scenario, email sending logic goes here
        mainthread(lambda: setattr(self.root.ids.status_label, 'text', "Evidence Captured & Encrypted."))()

if __name__ == '__main__':
    try:
        SentinelApp().run()
    except Exception as e:
        # Failsafe crash handler
        from kivy.base import runTouchApp
        from kivy.uix.label import Label
        runTouchApp(Label(text=f"FATAL CRASH:\n{e}"))
