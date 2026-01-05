# main.py
# SENTINEL-X: CIVIL TRAFFIC ENFORCEMENT SYSTEM (v2026.1)
# ---------------------------------------------------------
import os
import sys
import time
import json
import sqlite3
import socket
import threading
import smtplib
import platform
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders

# Kivy UI Framework
from kivy.app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.spinner import Spinner
from kivy.uix.image import Image
from kivy.clock import Clock, mainthread
from kivy.graphics.texture import Texture
from kivy.utils import platform as kivy_platform

# Hardware & AI Libraries
from camera4kivy import Preview
import cv2
import numpy as np
import reverse_geocoder as rg # OFFLINE Geocoding (No Internet Needed)

# ---------------------------------------------------------
# MODULE 1: JURISDICTION INTELLIGENCE (THE BRAIN)
# Based on the 2026 Strategic Traffic Report
# ---------------------------------------------------------
class JurisdictionEngine:
    def __init__(self):
        # Mapped from the "Digital Surveillance and Civic Enforcement" Report
        self.CONTACTS = {
            # --- NORTHERN REGION ---
            "DL": {"hq": "addlcp.tfchq@delhipolice.gov.in", "name": "Delhi"},
            "HR": {"hq": "igp.lo@hry.nic.in", "gurugram": "dcp.trafficggn@hry.nic.in", "name": "Haryana"},
            "PB": {"hq": "trafficpolicepunjab@gmail.com", "ludhiana": "cp.ldh.police@punjab.gov.in", "name": "Punjab"},
            "HP": {"hq": "adgpphq-hp@nic.in", "shimla": "police.shimla-hp@nic.in", "name": "Himachal"},
            "UK": {"hq": "info@uttarakhandtraffic.com", "dehradun": "ssp.ddn14@gmail.com", "name": "Uttarakhand"},
            
            # --- WESTERN REGION ---
            "MH": {"hq": "adg.traffic.hsp@mahapolice.gov.in", "mumbai": "multimediacell.traffic@mahapolice.gov.in", "name": "Maharashtra"},
            "GJ": {"hq": "info@gandhinagarpolice.com", "ahmedabad": "dcp-traffic-east-ahd@gujarat.gov.in", "name": "Gujarat"},
            "RJ": {"hq": "adgp.traffic@rajpolice.gov.in", "jaipur": "sptraf-rj@nic.in", "name": "Rajasthan"},
            "GA": {"hq": "adthq-tran.goa@nic.in", "name": "Goa"},

            # --- SOUTHERN REGION ---
            "KA": {"hq": "cpblr@ksp.gov.in", "bengaluru": "bangloretrafficpolice@gmail.com", "name": "Karnataka"},
            "TN": {"hq": "cctnstn@tn.gov.in", "chennai": "cop.chncity@tncctns.gov.in", "name": "Tamil Nadu"},
            "TS": {"hq": "addlcptraffic@hyd.tspolice.gov.in", "hyderabad": "insp-echallantrf-hyd@tspolice.gov.in", "name": "Telangana"},
            "KL": {"hq": "sptrafficsz.pol@kerala.gov.in", "trivandrum": "acptrstvm.pol@kerala.gov.in", "name": "Kerala"},
            "AP": {"hq": "dgp@appolice.gov.in", "vijayawada": "dcp_crimes@vza.appolice.gov.in", "name": "Andhra Pradesh"},

            # --- EASTERN REGION ---
            "WB": {"hq": "wbtcr_07@yahoo.co.in", "kolkata": "dctp@kolkatatrafficpolice.gov.in", "name": "West Bengal"},
            "OD": {"hq": "dgp.odpol@nic.in", "bhubaneswar": "dcpbbsr.odpol@nic.in", "name": "Odisha"},
            "BR": {"hq": "dgpcr.pat-bih@gov.in", "patna": "sptraffic-pat-bih@gov.in", "name": "Bihar"},
            "JH": {"hq": "hqrt@jhpolice.gov.in", "ranchi": "ssp-ranchi@jhpolice.gov.in", "name": "Jharkhand"},
        }

    def resolve_emails(self, gps_state_code, gps_district, vehicle_plate):
        """
        Routing Logic:
        1. Notify LOCAL Police (Where violation happened)
        2. Notify HOME Police (Where vehicle is registered)
        """
        recipients = set()
        
        # 1. Local Jurisdiction
        if gps_state_code in self.CONTACTS:
            state_data = self.CONTACTS[gps_state_code]
            # Try to match district-specific email
            found_city = False
            for key in state_data:
                if key in gps_district.lower():
                    recipients.add(state_data[key])
                    found_city = True
            if not found_city:
                recipients.add(state_data["hq"])

        # 2. Vehicle Home Jurisdiction
        reg_code = vehicle_plate[:2].upper()
        if reg_code in self.CONTACTS and reg_code!= gps_state_code:
            recipients.add(self.CONTACTS[reg_code]["hq"])

        return list(recipients)

# ---------------------------------------------------------
# MODULE 2: REPEAT OFFENDER TRACKING (SQLite)
# ---------------------------------------------------------
class OffenderDB:
    def __init__(self):
        self.conn = sqlite3.connect('traffic_history.db', check_same_thread=False)
        self.create_table()

    def create_table(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS violations (
                plate TEXT PRIMARY KEY,
                count INTEGER,
                last_violation TEXT,
                risk_score INTEGER
            )
        ''')
        self.conn.commit()

    def log_offense(self, plate, violation_type):
        cursor = self.conn.cursor()
        cursor.execute("SELECT count, risk_score FROM violations WHERE plate=?", (plate,))
        row = cursor.fetchone()

        if row:
            new_count = row + 1
            new_score = row[1] + self.get_violation_weight(violation_type)
            cursor.execute("UPDATE violations SET count=?, last_violation=?, risk_score=? WHERE plate=?",
                           (new_count, violation_type, new_score, plate))
            status = f"REPEAT OFFENDER (Level {new_count})"
        else:
            new_score = self.get_violation_weight(violation_type)
            cursor.execute("INSERT INTO violations VALUES (?,?,?,?)",
                           (plate, 1, violation_type, new_score))
            status = "FIRST OFFENSE"
        
        self.conn.commit()
        return status, new_score

    def get_violation_weight(self, v_type):
        weights = {
            "Red Light Jump": 5, "Over Speeding": 3, "Drunk Driving": 10,
            "No Helmet": 1, "Harsh Braking": 2, "Wrong Side": 5
        }
        return weights.get(v_type, 1)

# ---------------------------------------------------------
# MODULE 3: VISION & ANALYTICS (NIGHT/WEATHER MODE)
# ---------------------------------------------------------
class VisionCore:
    def enhance_image(self, frame):
        """
        Uses CLAHE (Contrast Limited Adaptive Histogram Equalization)
        to see plates in fog, rain, or low light.
        """
        try:
            # Convert to LAB color space
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            
            # Apply CLAHE to L-channel (Lightness)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            cl = clahe.apply(l)
            
            # Merge and convert back
            limg = cv2.merge((cl, a, b))
            final = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            return final
        except Exception:
            return frame # Fail-safe

# ---------------------------------------------------------
# MODULE 4: THE USER INTERFACE (KIVY)
# ---------------------------------------------------------
KV_LAYOUT = '''
FloatLayout:
    canvas.before:
        Color:
            rgba: 0.1, 0.1, 0.1, 1
        Rectangle:
            pos: self.pos
            size: self.size

    # Camera Preview Layer
    BoxLayout:
        id: camera_layout
        size_hint: 1, 0.7
        pos_hint: {'top': 1}

    # HUD Overlay
    BoxLayout:
        orientation: 'vertical'
        size_hint: 1, 0.3
        pos_hint: {'bottom': 1}
        padding: 10
        spacing: 10
        canvas.before:
            Color:
                rgba: 0, 0, 0, 0.8
            Rectangle:
                pos: self.pos
                size: self.size

        Label:
            id: gps_label
            text: "Initializing GPS & Sensors..."
            color: 0, 1, 1, 1
            font_size: '14sp'
            size_hint_y: 0.2

        GridLayout:
            cols: 2
            size_hint_y: 0.3
            Label:
                text: "Violation Type:"
            Spinner:
                id: violation_spinner
                text: "Select Violation"
                values:
                background_color: 0.2, 0.2, 0.2, 1

        Button:
            text: "REPORT VIOLATION (Good Samaritan Mode)"
            background_color: 1, 0, 0, 1
            bold: True
            size_hint_y: 0.3
            on_press: app.capture_and_report()

        Label:
            id: status_label
            text: "System Ready"
            font_size: '12sp'
            size_hint_y: 0.2
'''

class SentinelApp(App):
    def build(self):
        self.root = Builder.load_string(KV_LAYOUT)
        
        # Init Engines
        self.jurisdiction = JurisdictionEngine()
        self.db = OffenderDB()
        self.vision = VisionCore()
        
        # Init Camera
        self.camera = Preview(aspect_ratio='16:9')
        self.root.ids.camera_layout.add_widget(self.camera)
        
        # State Variables
        self.current_location = {"lat": 0.0, "lon": 0.0, "state": "Unknown", "district": "Unknown"}
        self.bg_service_socket = None
        
        # Start Background Service Listener
        Clock.schedule_interval(self.listen_to_service, 0.5)
        
        return self.root

    def on_start(self):
        self.camera.connect_camera(enable_analyze_pixels=True)
        self.start_android_service()

    def start_android_service(self):
        if kivy_platform == 'android':
            from jnius import autoclass
            service = autoclass('org.test.sentinel.ServiceSentinel_service')
            mActivity = autoclass('org.kivy.android.PythonActivity').mActivity
            argument = ''
            service.start(mActivity, argument)
            self.root.ids.status_label.text = "Background Service Started"

    def listen_to_service(self, dt):
        """
        Receives GPS and Harsh Braking data from service.py via UDP
        """
        if not self.bg_service_socket:
            self.bg_service_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.bg_service_socket.bind(('127.0.0.1', 9000))
            self.bg_service_socket.setblocking(False)

        try:
            data, _ = self.bg_service_socket.recvfrom(1024)
            data_json = json.loads(data.decode())
            
            # Update GPS
            self.current_location["lat"] = data_json.get('lat', 0.0)
            self.current_location["lon"] = data_json.get('lon', 0.0)
            
            # Offline Reverse Geocoding
            results = rg.search((self.current_location["lat"], self.current_location["lon"]))
            if results:
                self.current_location["state"] = results['admin1'] # e.g. "Haryana"
                self.current_location["district"] = results['admin2'] # e.g. "Gurugram"

            # Check for Harsh Braking Event
            if data_json.get('event') == 'HARSH_BRAKING':
                self.root.ids.status_label.text = "ALERT: Harsh Braking Detected!"
                # Auto-select dangerous driving
                self.root.ids.violation_spinner.text = "Dangerous Driving"

            # Update UI
            self.root.ids.gps_label.text = f"GPS: {self.current_location['lat']:.4f}, {self.current_location['lon']:.4f}\n{self.current_location['district']}, {self.current_location['state']}"

        except BlockingIOError:
            pass
        except Exception as e:
            print(f"Service Error: {e}")

    def capture_and_report(self):
        # 1. Capture Evidence
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"evidence_{timestamp}.jpg"
        
        # Note: In C4K, capture is async. We simulate the file path here.
        self.camera.capture_photo(filename)
        
        # 2. Run Logic in Thread
        threading.Thread(target=self.process_report, args=(filename,)).start()

    def process_report(self, filepath):
        # Wait for file write
        time.sleep(1.5)
        
        # 1. Image Enhancement
        img = cv2.imread(filepath)
        if img is None: return
        enhanced_img = self.vision.enhance_image(img)
        cv2.imwrite(filepath, enhanced_img)
        
        # 2. Simulated ANPR (In prod, use TFLite here)
        # We assume plate is read as:
        plate_number = "HR26DQ1234" 
        
        # 3. Violation Logic
        v_type = self.root.ids.violation_spinner.text
        if v_type == "Select Violation": v_type = "Traffic Violation"
        
        status, risk = self.db.log_offense(plate_number, v_type)
        
        # 4. Map State Names to Codes for Routing
        state_map = {"Haryana": "HR", "Delhi": "DL", "Punjab": "PB", "Maharashtra": "MH"}
        gps_state_code = state_map.get(self.current_location["state"], "DL")
        
        recipients = self.jurisdiction.resolve_emails(
            gps_state_code, 
            self.current_location["district"], 
            plate_number
        )
        
        # 5. Send Email
        self.send_email(recipients, filepath, plate_number, v_type, status)
        
        # 6. Update UI
        mainthread(lambda: setattr(self.root.ids.status_label, 'text', f"Reported: {plate_number} ({status})"))()

    def send_email(self, recipients, attachment_path, plate, violation, history):
        # Good Samaritan Law: Don't send user details
        sender_email = "your_app_email@gmail.com"
        sender_pass = "your_app_password"
        
        msg = MIMEMultipart()
        msg = f"PUBLIC REPORT: {violation} - {plate}"
        msg['From'] = sender_email
        msg = ", ".join(recipients)
        
        body = f"""
        OFFICIAL TRAFFIC VIOLATION REPORT (System Generated)
        ----------------------------------------------------
        Violation: {violation}
        Vehicle: {plate}
        Offender History: {history}
        
        Location: {self.current_location['lat']}, {self.current_location['lon']}
        Jurisdiction: {self.current_location['district']}, {self.current_location['state']}
        
        Legal Note:
        The reporter is a Good Samaritan under Section 134A of the MV Act, 2019.
        They have chosen to remain anonymous and cannot be compelled to be a witness.
        """
        msg.attach(MIMEText(body, 'plain'))
        
        with open(attachment_path, "rb") as f:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f'attachment; filename="{attachment_path}"')
            msg.attach(part)
            
        try:
            s = smtplib.SMTP('smtp.gmail.com', 587)
            s.starttls()
            s.login(sender_email, sender_pass)
            s.send_message(msg)
            s.quit()
            print("Email Sent")
        except Exception as e:
            print(f"Email Failed: {e}")

if __name__ == '__main__':
    SentinelApp().run()