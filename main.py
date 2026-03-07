# -*- coding: utf-8 -*-
"""
Sentinel-X v1.0.3 -- Civic Enforcement (Android)
Fixes: capture via filepath_callback, GPS via plyer after perms, direct accelerometer.
"""

import os
import re
import json
import socket
import threading
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.utils import platform
import math

Window.softinput_mode = "below_target"

try:
    import cv2
except Exception:
    cv2 = None

try:
    import numpy as np
except Exception:
    np = None

rg = None
try:
    import reverse_geocode
    rg = reverse_geocode
except Exception:
    try:
        import reverse_geocoder as _rg
        rg = _rg
    except Exception:
        rg = None

try:
    from plyer import email as plyer_email
except Exception:
    plyer_email = None

plyer_gps = None
try:
    from plyer import gps as _gps
    plyer_gps = _gps
except Exception:
    pass

plyer_accel = None
try:
    from plyer import accelerometer as _acc
    plyer_accel = _acc
except Exception:
    pass

Permission = None
request_permissions = None
try:
    if platform == "android":
        from android.permissions import Permission as _P, request_permissions as _rp
        Permission, request_permissions = _P, _rp
except Exception:
    pass

Preview = None
try:
    from camera4kivy import Preview as _Preview
    Preview = _Preview
except Exception:
    pass

DASH = "--"


class TrafficLawDB:
    OFFENSES = {
        "SPEEDING_LMV": {"label": "Speeding (LMV)", "section": "MVA 2019 S.183", "penalty": "Rs.1,000"},
        "SPEEDING_HMV": {"label": "Speeding (HMV)", "section": "MVA 2019 S.183", "penalty": "Rs.2,000"},
        "DANGEROUS":    {"label": "Dangerous Driving", "section": "MVA 2019 S.184", "penalty": "Rs.1-5K"},
        "SEATBELT":     {"label": "No Safety Belt", "section": "MVA 2019 S.194B", "penalty": "Rs.1,000"},
        "TRIPLE":       {"label": "Triple Riding", "section": "MVA 2019 S.194C", "penalty": "Rs.1K+Disq"},
        "HELMET":       {"label": "No Helmet", "section": "MVA 2019 S.194D", "penalty": "Rs.1K+Disq"},
        "EMERGENCY":    {"label": "Block Emergency", "section": "MVA 2019 S.194E", "penalty": "Rs.10,000"},
    }
    SIGN_GROUPS = {
        "Mandatory (IRC:67-2022)": [
            "Speed Limit 50", "No Parking", "No U-Turn",
            "Compulsory Left", "Compulsory Right", "EV Charging Station", "Bus Lane",
        ],
        "Cautionary (IRC:67-2022)": [
            "School Ahead", "Pedestrian Crossing", "Speed Breaker",
            "Narrow Road Ahead", "Slippery Road",
        ],
    }
    GOOD_SAMARITAN_FOOTER = (
        "This report is submitted under the protection of Section 134A of the "
        "Motor Vehicles Act, 1988, and the Good Samaritan Guidelines notified by "
        "MoRTH. The reporter voluntarily provides this information and shall not "
        "be compelled to be a witness or disclose personal identity."
    )
    VERIFIED_EMAILS = {
        "DL": ["addlcp.tfchq@delhipolice.gov.in"],
        "MH": ["sp.hsp.hq@mahapolice.gov.in", "cp.mumbai.jtcp.traf@mahapolice.gov.in"],
        "KA": ["bangloretrafficpolice@gmail.com"],
        "TN": ["cctnstn@tn.gov.in"],
        "UP": ["traffic_dir@uppolice.gov.in"],
        "HR": ["igp.lo@hry.nic.in", "dcp.trafficggn@hry.nic.in"],
        "KL": ["sptrafficsz.pol@kerala.gov.in"],
        "GJ": ["dig-traffic-ahd@gujarat.gov.in"],
        "WB": ["dctp@kolkatatrafficpolice.gov.in"],
        "TS": ["addlcptraffic@hyd.tspolice.gov.in"],
        "PB": ["trafficpolicepunjab@gmail.com"],
        "RJ": ["adgp.traffic@rajpolice.gov.in"],
        "GA": ["sp_traffic@goapolice.gov.in"],
    }
    STATE_NAME_TO_CODE = {
        "Delhi": "DL", "National Capital Territory of Delhi": "DL",
        "Maharashtra": "MH", "Karnataka": "KA", "Tamil Nadu": "TN",
        "Uttar Pradesh": "UP", "Haryana": "HR", "Kerala": "KL",
        "Gujarat": "GJ", "West Bengal": "WB", "Telangana": "TS",
        "Punjab": "PB", "Rajasthan": "RJ", "Goa": "GA",
    }


class JurisdictionEngine:
    PLATE_RE = re.compile(r"^\s*([A-Z]{2})\s*\d{1,2}\s*[A-Z]{0,3}\s*\d{3,4}\s*$", re.I)

    @staticmethod
    def extract_state_code(plate):
        s = (plate or "").strip().upper()
        m = JurisdictionEngine.PLATE_RE.match(s)
        if m:
            return m.group(1)
        s2 = re.sub(r"[^A-Z0-9]", "", s)
        return s2[:2] if len(s2) >= 2 and s2[:2].isalpha() else ""

    @staticmethod
    def _resolve_state(lat, lon):
        if rg is None or (abs(lat) < 0.001 and abs(lon) < 0.001):
            return ""
        try:
            if hasattr(rg, "get"):
                return TrafficLawDB.STATE_NAME_TO_CODE.get(rg.get((lat, lon)).get("state", ""), "")
            if hasattr(rg, "search"):
                r = rg.search((lat, lon), mode=1)
                return TrafficLawDB.STATE_NAME_TO_CODE.get((r[0].get("admin1", "") if r else ""), "")
        except Exception:
            pass
        return ""

    @staticmethod
    def geo_detail(lat, lon):
        if rg is None or (abs(lat) < 0.001 and abs(lon) < 0.001):
            return DASH, DASH
        try:
            if hasattr(rg, "get"):
                r = rg.get((lat, lon))
                return r.get("city", DASH), r.get("state", DASH)
            if hasattr(rg, "search"):
                r = rg.search((lat, lon), mode=1)
                if r:
                    return r[0].get("admin2", DASH), r[0].get("admin1", DASH)
        except Exception:
            pass
        return DASH, DASH

    @staticmethod
    def route(lat, lon, plate):
        lc = JurisdictionEngine._resolve_state(lat, lon)
        pc = JurisdictionEngine.extract_state_code(plate)
        le = TrafficLawDB.VERIFIED_EMAILS.get(lc, []) if lc else []
        pe = TrafficLawDB.VERIFIED_EMAILS.get(pc, []) if pc else []
        seen, out = set(), []
        for e in le + pe:
            if e and e not in seen:
                seen.add(e)
                out.append(e)
        return {"lc": lc, "pc": pc, "le": le, "pe": pe, "all": out}


class AnalyticsEngine:
    def __init__(self):
        self.result = ""
        self._skip = 0

    @staticmethod
    def clahe(img):
        if cv2 is None:
            return img
        try:
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            cl = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(l)
            return cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2BGR)
        except Exception:
            return img

    def analyze_frame(self, pixels, image_size, image_pos=None, scale=None, mirror=False):
        if cv2 is None or np is None:
            self.result = "CV:off"
            return
        self._skip += 1
        if self._skip % 3 != 0:
            return
        try:
            w, h = image_size
            if w <= 0 or h <= 0:
                return
            arr = np.frombuffer(bytes(pixels), dtype=np.uint8).reshape((h, w, 4))
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            if w > 640:
                s = 640.0 / w
                bgr = cv2.resize(bgr, (640, int(h * s)))
            gray = cv2.bilateralFilter(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), 9, 75, 75)
            cnts, _ = cv2.findContours(cv2.Canny(gray, 60, 180), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            count = 0
            for c in cnts:
                x, y, cw, ch = cv2.boundingRect(c)
                ar = cw / max(ch, 1)
                if cw >= 60 and ch >= 20 and 2.0 <= ar <= 6.5 and cw * ch >= 2000:
                    count += 1
            self.result = "CV:%d" % count if count else "CV:--"
        except Exception:
            self.result = "CV:err"


SentinelPreview = None
if Preview is not None:
    class _SentinelPreview(Preview):
        _analytics = None
        def analyze_pixels_callback(self, pixels, image_size, image_pos, scale, mirror):
            if self._analytics:
                self._analytics.analyze_frame(pixels, image_size, image_pos, scale, mirror)
    SentinelPreview = _SentinelPreview


KV = """
#:import dp kivy.metrics.dp

<RootUI>:
    orientation: "vertical"
    padding: dp(10)
    spacing: dp(4)

    Label:
        text: "Sentinel-X"
        size_hint_y: None
        height: dp(36)
        bold: True
        font_size: "20sp"

    BoxLayout:
        id: camera_box
        size_hint_y: None
        height: dp(220)
        canvas.before:
            Color:
                rgba: (0.05, 0.05, 0.07, 1)
            Rectangle:
                pos: self.pos
                size: self.size

    Label:
        size_hint_y: None
        height: dp(28)
        text: root.status_text
        font_size: "10sp"
        color: (0.5, 0.8, 1, 1)
        halign: "left"
        text_size: self.size

    ScrollView:
        do_scroll_x: False
        BoxLayout:
            orientation: "vertical"
            size_hint_y: None
            height: self.minimum_height
            spacing: dp(2)

            BoxLayout:
                size_hint_y: None
                height: dp(40)
                Label:
                    text: "Anonymous"
                    size_hint_x: 0.5
                    font_size: "14sp"
                    halign: "left"
                    text_size: self.size
                Switch:
                    id: sw_anon
                    active: True
                    size_hint_x: 0.5

            BoxLayout:
                size_hint_y: None
                height: dp(40)
                Label:
                    text: "CLAHE Night"
                    size_hint_x: 0.5
                    font_size: "14sp"
                    halign: "left"
                    text_size: self.size
                Switch:
                    id: sw_clahe
                    active: False
                    size_hint_x: 0.5

            BoxLayout:
                size_hint_y: None
                height: dp(40)
                Label:
                    text: "CV Assist"
                    size_hint_x: 0.5
                    font_size: "14sp"
                    halign: "left"
                    text_size: self.size
                Switch:
                    id: sw_cv
                    active: True
                    size_hint_x: 0.5

            Widget:
                size_hint_y: None
                height: dp(1)
                canvas:
                    Color:
                        rgba: (0.25, 0.25, 0.25, 1)
                    Rectangle:
                        pos: self.pos
                        size: self.size

            BoxLayout:
                size_hint_y: None
                height: dp(42)
                spacing: dp(6)
                Label:
                    text: "Plate"
                    size_hint_x: 0.22
                    font_size: "14sp"
                    bold: True
                    halign: "left"
                    text_size: self.size
                TextInput:
                    id: in_plate
                    size_hint_x: 0.78
                    multiline: False
                    hint_text: "MH12AB1234"
                    font_size: "15sp"

            BoxLayout:
                size_hint_y: None
                height: dp(46)
                spacing: dp(6)
                Label:
                    text: "Offense"
                    size_hint_x: 0.22
                    font_size: "14sp"
                    bold: True
                    halign: "left"
                    text_size: self.size
                Spinner:
                    id: sp_offense
                    size_hint_x: 0.78
                    text: "Select"
                    values: []
                    font_size: "13sp"
                    on_text: root.on_offense_selected(self.text)

            Label:
                size_hint_y: None
                height: dp(32)
                text: root.section_penalty
                font_size: "12sp"
                color: (1, 0.8, 0.3, 1)
                halign: "left"
                text_size: self.size

            BoxLayout:
                size_hint_y: None
                height: dp(46)
                spacing: dp(6)
                Label:
                    text: "Sign"
                    size_hint_x: 0.22
                    font_size: "13sp"
                    halign: "left"
                    text_size: self.size
                Spinner:
                    id: sp_sign_group
                    size_hint_x: 0.39
                    text: "Group"
                    values: []
                    font_size: "11sp"
                    on_text: root.on_sign_group(self.text)
                Spinner:
                    id: sp_sign
                    size_hint_x: 0.39
                    text: "Sign"
                    values: []
                    font_size: "11sp"

            BoxLayout:
                size_hint_y: None
                height: dp(70)
                spacing: dp(6)
                Label:
                    text: "Notes"
                    size_hint_x: 0.22
                    font_size: "13sp"
                    halign: "left"
                    valign: "top"
                    text_size: self.size
                TextInput:
                    id: in_notes
                    size_hint_x: 0.78
                    hint_text: "Details"
                    multiline: True
                    font_size: "14sp"

            BoxLayout:
                size_hint_y: None
                height: dp(42)
                spacing: dp(6)
                Label:
                    text: "Route"
                    size_hint_x: 0.22
                    font_size: "13sp"
                    bold: True
                    halign: "left"
                    text_size: self.size
                Label:
                    text: root.route_text
                    size_hint_x: 0.78
                    font_size: "11sp"
                    halign: "left"
                    text_size: self.size
                    color: (0.4, 0.9, 0.4, 1)

    BoxLayout:
        size_hint_y: None
        height: dp(50)
        spacing: dp(8)
        Button:
            text: "Capture"
            font_size: "15sp"
            bold: True
            on_release: root.capture_evidence()
            background_color: (0.2, 0.6, 0.9, 1)
        Button:
            text: "Send Report"
            font_size: "15sp"
            bold: True
            on_release: root.send_report()
            background_color: (0.1, 0.7, 0.3, 1)
        Button:
            text: "Clear"
            font_size: "14sp"
            on_release: root.clear_form()
            background_color: (0.4, 0.4, 0.4, 1)
"""


class RootUI(BoxLayout):
    status_text = StringProperty("Waiting for GPS...")
    section_penalty = StringProperty(DASH)
    route_text = StringProperty(DASH)
    latest_lat = NumericProperty(0.0)
    latest_lon = NumericProperty(0.0)
    latest_speed = NumericProperty(0.0)
    latest_g = NumericProperty(0.0)
    district = StringProperty("")
    state_name = StringProperty("")
    evidence_path = StringProperty("")

    def __init__(self, **kw):
        super().__init__(**kw)
        self._preview = None
        self._cam_ok = False
        self._udp_stop = threading.Event()
        self._analytics = AnalyticsEngine()
        self._gps_started = False
        self._last_capture_path = ""
        Clock.schedule_once(self._boot, 0)

    def _evidence_dir(self):
        base = App.get_running_app().user_data_dir if platform == "android" else "."
        d = os.path.join(base, "evidence")
        os.makedirs(d, exist_ok=True)
        return d

    def _boot(self, _dt):
        vals = []
        for k, v in TrafficLawDB.OFFENSES.items():
            vals.append("%s: %s" % (k, v["label"]))
        self.ids.sp_offense.values = vals
        self.ids.sp_sign_group.values = list(TrafficLawDB.SIGN_GROUPS.keys())
        self._request_perms()
        self._start_udp()
        self._start_service()
        Clock.schedule_interval(self._tick, 1.0)
        Clock.schedule_interval(self._read_accel, 0.1)

    # ── Permissions then GPS + Camera ────────────────────────────────────
    def _request_perms(self):
        if platform != "android" or request_permissions is None:
            self._setup_camera()
            self._start_gps()
            return

        def _cb(perms, results):
            # Both camera and GPS start AFTER permissions granted
            Clock.schedule_once(lambda dt: self._after_perms(), 0.5)

        try:
            request_permissions([
                Permission.CAMERA,
                Permission.ACCESS_FINE_LOCATION,
                Permission.ACCESS_COARSE_LOCATION,
                Permission.WRITE_EXTERNAL_STORAGE,
            ], _cb)
        except Exception:
            Clock.schedule_once(lambda dt: self._after_perms(), 1.5)

    def _after_perms(self):
        self._setup_camera()
        self._start_gps()
        self._start_accel()

    # ── GPS via plyer ────────────────────────────────────────────────────
    def _start_gps(self):
        if self._gps_started or plyer_gps is None:
            return
        try:
            plyer_gps.configure(
                on_location=self._on_gps,
                on_status=lambda **kw: None,
            )
            plyer_gps.start(minTime=1000, minDistance=0)
            self._gps_started = True
        except Exception:
            pass

    def _on_gps(self, **kwargs):
        # This callback may run on a background thread
        lat = float(kwargs.get("lat", 0) or 0)
        lon = float(kwargs.get("lon", 0) or 0)
        speed = float(kwargs.get("speed", 0) or 0)
        if lat != 0 and lon != 0:
            Clock.schedule_once(lambda dt: self._apply_gps(lat, lon, speed), 0)

    def _apply_gps(self, lat, lon, speed):
        self.latest_lat = lat
        self.latest_lon = lon
        if speed > 0:
            self.latest_speed = speed

    # ── Accelerometer direct (not relying on service UDP) ────────────────
    def _start_accel(self):
        if plyer_accel is None:
            return
        try:
            plyer_accel.enable()
        except Exception:
            pass

    def _read_accel(self, _dt):
        if plyer_accel is None:
            return
        try:
            val = plyer_accel.acceleration
            if val and val[0] is not None:
                x, y, z = float(val[0]), float(val[1]), float(val[2] or 9.81)
                g_total = math.sqrt(x * x + y * y + z * z)
                g_dyn = abs(g_total - 9.81)
                self.latest_g = g_dyn
        except Exception:
            pass

    # ── Camera with filepath_callback ────────────────────────────────────
    def _setup_camera(self):
        self.ids.camera_box.clear_widgets()
        if SentinelPreview is None:
            self.ids.camera_box.add_widget(Label(text="No camera", font_size="14sp"))
            return
        try:
            self._preview = SentinelPreview()
            self._preview._analytics = self._analytics
            self.ids.camera_box.add_widget(self._preview)
            Clock.schedule_once(lambda dt: self._connect_cam(), 0.5)
        except Exception:
            self.ids.camera_box.add_widget(Label(text="Camera failed", font_size="14sp"))

    def _connect_cam(self):
        if not self._preview:
            return
        try:
            kw = {
                "enable_analyze_pixels": True,
                "analyze_pixels_resolution": 640,
                "filepath_callback": self._on_file_saved,
            }
            if platform == "android":
                kw["enable_video"] = False
            self._preview.connect_camera(**kw)
            self._cam_ok = True
        except Exception:
            try:
                self._preview.connect_camera(filepath_callback=self._on_file_saved)
                self._cam_ok = True
            except Exception:
                try:
                    self._preview.connect_camera()
                    self._cam_ok = True
                except Exception:
                    pass

    def _on_file_saved(self, file_path):
        """Called by camera4kivy when a photo is actually saved to disk."""
        p = str(file_path) if file_path else ""
        if p and os.path.isfile(p):
            if self.ids.sw_clahe.active and cv2:
                try:
                    img = cv2.imread(p)
                    if img is not None:
                        cv2.imwrite(p, AnalyticsEngine.clahe(img))
                except Exception:
                    pass
            self.evidence_path = p
            Clock.schedule_once(lambda dt: self._popup("Saved", os.path.basename(p)), 0)
        else:
            self._last_capture_path = p

    # ── Capture ──────────────────────────────────────────────────────────
    def capture_evidence(self):
        if not self._preview or not self._cam_ok:
            self._popup("Not ready", "Camera not connected.")
            return
        try:
            # camera4kivy capture_photo: saves to default location,
            # filepath_callback tells us where it went
            self._preview.capture_photo()
            self._popup("Capturing...", "Photo being saved.")
        except Exception:
            # Fallback: screenshot the preview widget
            try:
                edir = self._evidence_dir()
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                p = os.path.join(edir, "evidence_%s.png" % ts)
                self._preview.export_to_png(p)
                if os.path.isfile(p):
                    self.evidence_path = p
                    self._popup("Saved (screenshot)", os.path.basename(p))
                else:
                    self._popup("Failed", "Screenshot not saved.")
            except Exception as e2:
                self._popup("Failed", str(e2))

    # ── Form ─────────────────────────────────────────────────────────────
    def on_offense_selected(self, text):
        k = (text.split(":")[0] or "").strip()
        if k in TrafficLawDB.OFFENSES:
            o = TrafficLawDB.OFFENSES[k]
            self.section_penalty = "%s | %s" % (o["section"], o["penalty"])
        else:
            self.section_penalty = DASH

    def on_sign_group(self, g):
        self.ids.sp_sign.values = TrafficLawDB.SIGN_GROUPS.get(g, [])
        self.ids.sp_sign.text = "Sign"

    def clear_form(self):
        self.ids.in_plate.text = ""
        self.ids.in_notes.text = ""
        self.ids.sp_offense.text = "Select"
        self.ids.sp_sign_group.text = "Group"
        self.ids.sp_sign.text = "Sign"
        self.section_penalty = DASH
        self.route_text = DASH
        self.evidence_path = ""

    # ── Status + routing tick ────────────────────────────────────────────
    def _tick(self, _dt):
        lat = float(self.latest_lat)
        lon = float(self.latest_lon)
        self.district, self.state_name = JurisdictionEngine.geo_detail(lat, lon)
        plate = self.ids.in_plate.text.strip()
        rt = JurisdictionEngine.route(lat, lon, plate)
        rcpts = ", ".join(rt["all"]) or DASH
        lc = rt["lc"] or DASH
        pc = rt["pc"] or DASH
        self.route_text = "Loc:%s Plate:%s\n%s" % (lc, pc, rcpts)
        kmh = self.latest_speed * 3.6
        cv = self._analytics.result if self.ids.sw_cv.active else ""
        self.status_text = "%.4f,%.4f | %s | %.0fkm/h | G:%.1f | %s" % (
            lat, lon, self.state_name or DASH, kmh, self.latest_g, cv
        )

    # ── Email ────────────────────────────────────────────────────────────
    def send_report(self):
        if plyer_email is None:
            self._popup("Unavailable", "Email not available.")
            return
        plate = self.ids.in_plate.text.strip()
        if not plate:
            self._popup("Missing", "Enter plate number.")
            return
        okey = (self.ids.sp_offense.text.split(":")[0] or "").strip()
        if okey not in TrafficLawDB.OFFENSES:
            self._popup("Missing", "Select a violation.")
            return
        lat = float(self.latest_lat)
        lon = float(self.latest_lon)
        rt = JurisdictionEngine.route(lat, lon, plate)
        if not rt["all"]:
            self._popup("No route", "Unknown state code.")
            return

        o = TrafficLawDB.OFFENSES[okey]
        anon = bool(self.ids.sw_anon.active)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "SENTINEL-X CIVIC ENFORCEMENT REPORT",
            "Time: %s" % now, "",
            "GPS: %.6f, %.6f" % (lat, lon),
            "Location: %s, %s" % (self.district, self.state_name),
            "Speed: %.1f km/h" % (self.latest_speed * 3.6),
            "G_dyn: %.2f m/s2" % self.latest_g, "",
            "Plate: %s" % plate,
            "Offense: %s - %s" % (okey, o["label"]),
            "Section: %s" % o["section"],
            "Penalty: %s" % o["penalty"], "",
            "Sign: %s / %s" % (self.ids.sp_sign_group.text, self.ids.sp_sign.text), "",
            "Reporter: %s" % ("ANONYMOUS" if anon else "See contact"), "",
            "Notes: %s" % (self.ids.in_notes.text.strip() or DASH), "",
            "Routing: Loc=%s Plate=%s" % (rt["lc"] or DASH, rt["pc"] or DASH), "",
            TrafficLawDB.GOOD_SAMARITAN_FOOTER,
        ]
        subj = "[Sentinel-X] %s - %s" % (plate, o["label"])
        body = "\n".join(lines)
        to = rt["all"]

        sent = False
        # Android plyer: recipient (singular), create_chooser
        if not sent:
            try:
                plyer_email.send(recipient=to, subject=subj, text=body, create_chooser=True)
                sent = True
            except Exception:
                pass
        if not sent:
            try:
                plyer_email.send(recipients=to, subject=subj, text=body)
                sent = True
            except Exception:
                pass
        if not sent:
            try:
                plyer_email.send(recipient=";".join(to), subject=subj, text=body, create_chooser=True)
                sent = True
            except Exception as e:
                self._popup("Failed", str(e))
                return
        if sent:
            self._popup("Ready", "Email app opened.")

    # ── Service + UDP ────────────────────────────────────────────────────
    def _start_service(self):
        if platform != "android":
            return
        try:
            from android import AndroidService
            AndroidService("Sentinel-X", "Telemetry").start("")
        except Exception:
            pass

    def _start_udp(self):
        threading.Thread(target=self._udp_loop, daemon=True).start()

    def _udp_loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("127.0.0.1", 17888))
            s.settimeout(1.0)
        except Exception:
            return
        while not self._udp_stop.is_set():
            try:
                data, _ = s.recvfrom(4096)
                p = json.loads(data.decode("utf-8", errors="ignore"))
                la = float(p.get("lat", 0) or 0)
                lo = float(p.get("lon", 0) or 0)
                sp = float(p.get("speed_mps", 0) or 0)
                gd = float(p.get("g_dyn", 0) or 0)
                if la != 0 and lo != 0:
                    Clock.schedule_once(lambda dt, a=la, b=lo, c=sp, d=gd: self._telem(a, b, c, d), 0)
            except socket.timeout:
                continue
            except Exception:
                continue

    def _telem(self, lat, lon, spd, g):
        if lat and lon:
            self.latest_lat = lat
            self.latest_lon = lon
        if spd:
            self.latest_speed = spd
        if g:
            self.latest_g = g

    def _popup(self, t, m):
        Popup(title=t, content=Label(text=m, halign="left", valign="top", text_size=(dp(250), None)),
              size_hint=(.82, .32)).open()


class SentinelXApp(App):
    def build(self):
        Builder.load_string(KV)
        return RootUI()

    def on_stop(self):
        r = self.root
        if r and r._preview and r._cam_ok:
            try:
                r._preview.disconnect_camera()
            except Exception:
                pass
        if plyer_gps and r and r._gps_started:
            try:
                plyer_gps.stop()
            except Exception:
                pass
        if plyer_accel:
            try:
                plyer_accel.disable()
            except Exception:
                pass


if __name__ == "__main__":
    SentinelXApp().run()
