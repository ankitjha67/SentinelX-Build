# main.py
# SENTINEL-X: CIVIL TRAFFIC ENFORCEMENT SYSTEM (v2026.3 - Fixed)
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
try:
    from camera4kivy import Preview
    import cv2
    import numpy as np
    # import reverse_geocoder as rg # Disabled for stability
    from plyer import gps
except Exception as e:
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
            text: "Initializing..."
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
        self.gps_data = {"lat": 0.0, "lon": 0.0, "city": "Unknown"}
        self.service_socket = None
        return self.root

    def on_start(self):
        if platform == 'android':
            self.request_android_permissions()
        else:
            self.start_app_logic()

    def request_android_permissions(self):
        from android.permissions import request_permissions, Permission
        
        def callback(permissions, results):
            if all([res for res in results]):
                self.root.ids.status_label.text = "Permissions Granted. Starting Systems..."
                self.start_app_logic()
            else:
                self.root.ids.status_label.text = "ERROR: Permissions Denied.\nApp cannot function."

        # --- FIX IS HERE: Added the list of permissions ---
        request_permissions(
           , 
            callback
        )

    def start_app_logic(self):
        try:
            self.camera.connect_camera(enable_analyze_pixels=True)
            self.root.ids.btn_report.disabled = False
            self.start_android_service()
            Clock.schedule_interval(self.listen_to_service, 0.5)
            self.root.ids.status_label.text = "System Online. Ready."
        except Exception as e:
            self.root.ids.status_label.text = f"Startup Error: {e}"

    def start_android_service(self):
        if platform == 'android':
            from jnius import autoclass
            # Ensure this package name matches buildozer.spec EXACTLY
            service = autoclass('org.civic.enforce.sentinelx.ServiceSentinel_service')
            mActivity = autoclass('org.kivy.android.PythonActivity').mActivity
            service.start(mActivity, '')

    def listen_to_service(self, dt):
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
        except:
            pass

    def capture_evidence(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"evidence_{timestamp}.jpg"
        self.camera.capture_photo(filename)
        threading.Thread(target=self.process_report, args=(filename,)).start()

    def process_report(self, filename):
        time.sleep(1)
        mainthread(lambda: setattr(self.root.ids.status_label, 'text', "Evidence Captured."))()

if __name__ == '__main__':
    try:
        SentinelApp().run()
    except Exception as e:
        pass
