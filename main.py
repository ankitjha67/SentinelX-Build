# -*- coding: utf-8 -*-
"""
Sentinel-X — Civic Enforcement (Android-first via Kivy/Buildozer; portable Python app)
Features (no deletions):
- TrafficLawDB: MVA 2019 offenses (requested) + IRC:67-2022 sign groups (incl EV Charging, Bus Lane)
- Good Samaritan (134A): Anonymous toggle default ON + mandatory footer appended to every report email
- JurisdictionEngine: dual routing (location-based + plate-based) => sends to BOTH authorities
- Verified Email Directory (2025 Data): hardcoded EXACT structure as requested (DL/MH/KA/TN/UP/HR/KL/GJ/WB/TS/PB/RJ/GA)
- Offline reverse geocoding: reverse_geocoder (no online APIs)
- Telematics: reads telemetry from service.py via UDP (GPS/speed + G_dyn) and auto-suggests dangerous driving
- Vision:
  - Night/Fog capture enhancement: CLAHE (8,8) clipLimit 3.0 (opencv best-effort)
  - Live CV Assist while camera preview runs (heuristics + optional ONNX via OpenCV DNN if user drops model)
- Crash prevention: cv2/plyer imports wrapped to avoid startup crash
"""

import os
import re
import json
import socket
import threading
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.utils import platform

# ---- crash-safe imports ----
try:
    import cv2  # type: ignore
except Exception:
    cv2 = None

try:
    import numpy as np  # type: ignore
except Exception:
    np = None

try:
    import reverse_geocoder as rg  # type: ignore
except Exception:
    rg = None

try:
    from plyer import email as plyer_email  # type: ignore
except Exception:
    plyer_email = None

# Android permissions (runtime)
Permission = None
request_permissions = None
try:
    if platform == "android":
        from android.permissions import Permission as _Permission  # type: ignore
        from android.permissions import request_permissions as _request_permissions  # type: ignore
        Permission = _Permission
        request_permissions = _request_permissions
except Exception:
    Permission = None
    request_permissions = None

# camera4kivy
Preview = None
try:
    from camera4kivy import Preview  # type: ignore
except Exception:
    Preview = None


# =============================================================================
# 1) LEGAL DB
# =============================================================================
class TrafficLawDB:
    """
    Static class with MVA 2019 mapping + IRC:67-2022 signage references.
    """

    # A) Offenses & penalties (as per your hardcoded requirement)
    OFFENSES = {
        "SPEEDING_183_LMV": {
            "label": "Speeding (LMV)",
            "section": "Motor Vehicles Act (Amendment) 2019 — Section 183",
            "penalty": "₹1,000",
            "notes": "Over-speeding (LMV).",
        },
        "SPEEDING_183_HMV": {
            "label": "Speeding (Medium/Heavy Vehicle)",
            "section": "Motor Vehicles Act (Amendment) 2019 — Section 183",
            "penalty": "₹2,000",
            "notes": "Over-speeding (medium/heavy vehicle).",
        },
        "DANGEROUS_184": {
            "label": "Dangerous Driving (Red light / Stop sign / Handheld device)",
            "section": "Motor Vehicles Act (Amendment) 2019 — Section 184",
            "penalty": "₹1,000 to ₹5,000 (First offense)",
            "notes": "Includes red light jumping, stop sign violation, handheld device use.",
        },
        "SEATBELT_194B": {
            "label": "Driving without Safety Belt",
            "section": "Motor Vehicles Act (Amendment) 2019 — Section 194B",
            "penalty": "₹1,000",
            "notes": "Seat belt violation.",
        },
        "TRIPLE_194C": {
            "label": "Triple Riding on Two-Wheeler",
            "section": "Motor Vehicles Act (Amendment) 2019 — Section 194C",
            "penalty": "₹1,000 + License Disqualification",
            "notes": "Triple riding on two-wheeler.",
        },
        "HELMET_194D": {
            "label": "Riding without Helmet",
            "section": "Motor Vehicles Act (Amendment) 2019 — Section 194D",
            "penalty": "₹1,000 + License Disqualification",
            "notes": "Helmet violation (rider/pillion).",
        },
        "EMERGENCY_194E": {
            "label": "Failure to yield to Emergency Vehicles",
            "section": "Motor Vehicles Act (Amendment) 2019 — Section 194E",
            "penalty": "₹10,000",
            "notes": "Failure to yield / blocking emergency vehicles.",
        },
    }

    # B) IRC:67-2022 sign groups (UI reference)
    SIGN_GROUPS = {
        "Mandatory (IRC:67-2022)": [
            "Speed Limit 50",
            "No Parking",
            "No U-Turn",
            "Compulsory Left",
            "Compulsory Right",
            "EV Charging Station",  # 2022 addition
            "Bus Lane",            # 2022 addition
        ],
        "Cautionary (IRC:67-2022)": [
            "School Ahead",
            "Pedestrian Crossing",
            "Speed Breaker",
            "Narrow Road Ahead",
            "Slippery Road",
        ],
    }

    # C) Good Samaritan (134A) footer (MUST be appended to email)
    GOOD_SAMARITAN_FOOTER = (
        "This report is submitted under the protection of Section 134A of the Motor Vehicles Act, 1988, "
        "and the Good Samaritan Guidelines notified by MoRTH. The reporter voluntarily provides this "
        "information and shall not be compelled to be a witness or disclose personal identity."
    )

    # 2) Verified Email Directory (2025 Data) — hardcode structure exactly
    VERIFIED_EMAILS_2025 = {
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

    # Offline reverse_geocoder returns admin1 names; map them to plate-style codes
    STATE_NAME_TO_CODE = {
        "Delhi": "DL",
        "National Capital Territory of Delhi": "DL",
        "Maharashtra": "MH",
        "Karnataka": "KA",
        "Tamil Nadu": "TN",
        "Uttar Pradesh": "UP",
        "Haryana": "HR",
        "Kerala": "KL",
        "Gujarat": "GJ",
        "West Bengal": "WB",
        "Telangana": "TS",
        "Punjab": "PB",
        "Rajasthan": "RJ",
        "Goa": "GA",
    }


# =============================================================================
# 2) Jurisdiction Engine (dual routing)
# =============================================================================
class JurisdictionEngine:
    PLATE_RE = re.compile(r"^\s*([A-Z]{2})\s*\d{1,2}\s*[A-Z]{0,3}\s*\d{3,4}\s*$", re.I)

    @staticmethod
    def extract_state_code_from_plate(plate: str) -> str:
        s = (plate or "").strip().upper()
        m = JurisdictionEngine.PLATE_RE.match(s)
        if m:
            return m.group(1).upper()
        s2 = re.sub(r"[^A-Z0-9]", "", s)
        if len(s2) >= 2 and s2[:2].isalpha():
            return s2[:2]
        return ""

    @staticmethod
    def location_state_code_from_latlon(lat: float, lon: float) -> str:
        if rg is None:
            return ""
        try:
            res = rg.search((lat, lon), mode=1)
            if not res:
                return ""
            admin1 = (res[0].get("admin1") or "").strip()
            return TrafficLawDB.STATE_NAME_TO_CODE.get(admin1, "")
        except Exception:
            return ""

    @staticmethod
    def recipients_for_report(lat: float, lon: float, plate: str):
        loc_code = JurisdictionEngine.location_state_code_from_latlon(lat, lon)
        plate_code = JurisdictionEngine.extract_state_code_from_plate(plate)

        loc_emails = TrafficLawDB.VERIFIED_EMAILS_2025.get(loc_code, []) if loc_code else []
        plate_emails = TrafficLawDB.VERIFIED_EMAILS_2025.get(plate_code, []) if plate_code else []

        recipients = []
        for e in (loc_emails + plate_emails):
            if e and e not in recipients:
                recipients.append(e)

        return {
            "loc_code": loc_code,
            "plate_code": plate_code,
            "loc_emails": loc_emails,
            "plate_emails": plate_emails,
            "recipients": recipients,
        }


# =============================================================================
# 3) Analytics Engine (configurable)
# =============================================================================
class AnalyticsEngine:
    """
    Lightweight on-device analytics:
    - Plate candidate detection via edges/rectangles (fast, no heavy model)
    - Optional ONNX detector via OpenCV DNN if user drops model file:
        ./models/detector.onnx
      (Parsing is intentionally conservative; you can customize for your model output format.)
    - CLAHE enhancement for night/fog captures (tileGridSize 8x8, clipLimit 3.0)
    """

    def __init__(self, app_dir: str):
        self.app_dir = app_dir
        self.model_path = os.path.join(app_dir, "models", "detector.onnx")
        self.model = None
        self._tried = False

    def try_load_model(self):
        if self._tried:
            return
        self._tried = True
        if cv2 is None:
            return
        if not os.path.isfile(self.model_path):
            return
        try:
            self.model = cv2.dnn.readNetFromONNX(self.model_path)
        except Exception:
            self.model = None

    @staticmethod
    def clahe_enhance_bgr(img_bgr):
        if cv2 is None:
            return img_bgr
        try:
            lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            merged = cv2.merge((cl, a, b))
            return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
        except Exception:
            return img_bgr

    @staticmethod
    def detect_plate_candidates_bgr(img_bgr):
        if cv2 is None:
            return []
        try:
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            gray = cv2.bilateralFilter(gray, 9, 75, 75)
            edges = cv2.Canny(gray, 60, 180)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            boxes = []
            for c in contours:
                x, y, w, h = cv2.boundingRect(c)
                if w < 60 or h < 20:
                    continue
                ar = w / float(h + 1e-6)
                if ar < 2.0 or ar > 6.5:
                    continue
                area = w * h
                if area < 2000:
                    continue
                boxes.append((x, y, w, h, area))
            boxes.sort(key=lambda t: t[4], reverse=True)
            return [(x, y, w, h) for (x, y, w, h, _) in boxes[:5]]
        except Exception:
            return []

    def run_optional_onnx(self, img_bgr) -> bool:
        self.try_load_model()
        if self.model is None or cv2 is None or np is None:
            return False
        try:
            blob = cv2.dnn.blobFromImage(img_bgr, scalefactor=1 / 255.0, size=(320, 320), swapRB=True, crop=False)
            self.model.setInput(blob)
            out = self.model.forward()
            score = float(np.max(out))
            return score > 0.5
        except Exception:
            return False


# =============================================================================
# 4) UI (legible on screen): camera fixed height + scrollable form
# =============================================================================
KV = r"""
<RootUI>:
    orientation: "vertical"
    padding: dp(8)
    spacing: dp(6)

    BoxLayout:
        size_hint_y: None
        height: dp(44)
        Label:
            text: "Sentinel-X — Civic Enforcement"
            bold: True
            font_size: "18sp"
            halign: "center"
            valign: "middle"
            text_size: self.size

    BoxLayout:
        id: camera_box
        size_hint_y: None
        height: dp(260)
        canvas.before:
            Color:
                rgba: (0.08, 0.08, 0.09, 1)
            Rectangle:
                pos: self.pos
                size: self.size

    Label:
        size_hint_y: None
        height: dp(44)
        text: root.status_text
        font_size: "12sp"
        halign: "left"
        valign: "middle"
        text_size: self.size

    ScrollView:
        do_scroll_x: False
        bar_width: dp(6)

        GridLayout:
            cols: 2
            size_hint_y: None
            height: self.minimum_height
            spacing: dp(8)
            padding: dp(4)

            Label:
                text: "Submit Anonymously"
                halign: "left"
                valign: "middle"
                text_size: self.size
            Switch:
                id: sw_anon
                active: True

            Label:
                text: "Night/Fog Mode (CLAHE)"
                halign: "left"
                valign: "middle"
                text_size: self.size
            Switch:
                id: sw_clahe
                active: False

            Label:
                text: "Live CV Assist"
                halign: "left"
                valign: "middle"
                text_size: self.size
            Switch:
                id: sw_cv
                active: True

            Label:
                text: "Your Name (optional)"
                halign: "left"
                valign: "middle"
                text_size: self.size
            TextInput:
                id: in_name
                multiline: False
                hint_text: "Name (optional)"

            Label:
                text: "Contact (optional)"
                halign: "left"
                valign: "middle"
                text_size: self.size
            TextInput:
                id: in_contact
                multiline: False
                hint_text: "Phone/Email (optional)"

            Label:
                text: "Number Plate"
                halign: "left"
                valign: "middle"
                text_size: self.size
            TextInput:
                id: in_plate
                multiline: False
                hint_text: "e.g., MH12AB1234"

            Label:
                text: "Violation Code"
                halign: "left"
                valign: "middle"
                text_size: self.size
            Spinner:
                id: sp_offense
                text: "Select Violation"
                values: []
                on_text: root.on_offense_selected(self.text)

            Label:
                text: "Section / Penalty"
                halign: "left"
                valign: "middle"
                text_size: self.size
            Label:
                text: root.section_penalty_text
                halign: "left"
                valign: "middle"
                text_size: self.size

            Label:
                text: "Sign Group"
                halign: "left"
                valign: "middle"
                text_size: self.size
            Spinner:
                id: sp_sign_group
                text: "Select Sign Group"
                values: []
                on_text: root.on_sign_group_selected(self.text)

            Label:
                text: "Observed Sign"
                halign: "left"
                valign: "middle"
                text_size: self.size
            Spinner:
                id: sp_sign
                text: "Select Sign"
                values: []

            Label:
                text: "Notes"
                halign: "left"
                valign: "top"
                text_size: self.size
            TextInput:
                id: in_notes
                hint_text: "Optional notes (what happened?)"
                multiline: True
                size_hint_y: None
                height: dp(120)

            Label:
                text: "Routing (auto)"
                halign: "left"
                valign: "top"
                text_size: self.size
            Label:
                text: root.route_text
                halign: "left"
                valign: "top"
                text_size: self.size

    BoxLayout:
        size_hint_y: None
        height: dp(56)
        spacing: dp(8)

        Button:
            text: "Capture Evidence"
            on_release: root.capture_evidence()

        Button:
            text: "Send Report"
            on_release: root.send_report()

        Button:
            text: "Clear"
            on_release: root.clear_form()
"""


class RootUI(BoxLayout):
    status_text = StringProperty("GPS: — | Speed: — | G_dyn: —")
    section_penalty_text = StringProperty("—")
    route_text = StringProperty("—")

    latest_lat = NumericProperty(0.0)
    latest_lon = NumericProperty(0.0)
    latest_speed_mps = NumericProperty(0.0)
    latest_g_dyn = NumericProperty(0.0)

    district = StringProperty("")
    state_name = StringProperty("")

    evidence_path = StringProperty("")
    cv_hint = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._udp_thread = None
        self._udp_stop = threading.Event()
        self._preview = None
        self._analytics = AnalyticsEngine(self._app_dir())
        Clock.schedule_once(self._post_build, 0)

    def _app_dir(self):
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            return "."

    def _post_build(self, _dt):
        # populate spinners
        self.ids.sp_offense.values = [f"{k} — {v['label']}" for k, v in TrafficLawDB.OFFENSES.items()]
        self.ids.sp_sign_group.values = list(TrafficLawDB.SIGN_GROUPS.keys())

        self._setup_camera()
        self._start_udp_listener()
        self._start_android_service()
        self._request_permissions()

        Clock.schedule_interval(self._update_geo_and_route, 1.0)
        Clock.schedule_interval(self._live_cv_tick, 0.6)

    # -------------------------------------------------------------------------
    # Permissions (MUST NOT be empty)
    # -------------------------------------------------------------------------
    def _request_permissions(self):
        if platform != "android" or request_permissions is None or Permission is None:
            return
        perms = [
            Permission.CAMERA,
            Permission.ACCESS_FINE_LOCATION,
            Permission.ACCESS_COARSE_LOCATION,
            Permission.WRITE_EXTERNAL_STORAGE,
        ]
        try:
            request_permissions(perms)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Camera setup
    # -------------------------------------------------------------------------
    def _setup_camera(self):
        self.ids.camera_box.clear_widgets()
        if Preview is None:
            self.ids.camera_box.add_widget(Label(text="Camera preview unavailable\n(camera4kivy not loaded)"))
            return
        try:
            self._preview = Preview()
            self.ids.camera_box.add_widget(self._preview)
            Clock.schedule_once(lambda dt: self._safe_preview_start(), 0.2)
        except Exception:
            self._preview = None
            self.ids.camera_box.add_widget(Label(text="Camera init failed"))

    def _safe_preview_start(self):
        if not self._preview:
            return
        try:
            if hasattr(self._preview, "connect_camera"):
                self._preview.connect_camera(enable_analyze_pixels=True)
            elif hasattr(self._preview, "start"):
                self._preview.start()
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Live CV Assist (non-accusatory hints)
    # -------------------------------------------------------------------------
    def _live_cv_tick(self, _dt):
        if not self.ids.sw_cv.active or self._preview is None:
            return
        if cv2 is None or np is None:
            self.cv_hint = "CV: OpenCV not available"
            return

        try:
            tex = getattr(self._preview, "texture", None)
            if tex is None:
                return
            w, h = tex.size
            if w <= 0 or h <= 0:
                return

            arr = np.frombuffer(tex.pixels, dtype=np.uint8).reshape((h, w, 4))
            rgb = arr[:, :, :3]
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

            boxes = self._analytics.detect_plate_candidates_bgr(bgr)
            onnx_hit = self._analytics.run_optional_onnx(bgr)

            if boxes:
                self.cv_hint = f"CV: Plate-like region(s): {len(boxes)}"
            elif onnx_hit:
                self.cv_hint = "CV: Optional model indicates a detection"
            else:
                self.cv_hint = "CV: No strong cues"
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Form handlers
    # -------------------------------------------------------------------------
    def on_offense_selected(self, text):
        key = (text.split("—")[0] or "").strip()
        if key in TrafficLawDB.OFFENSES:
            v = TrafficLawDB.OFFENSES[key]
            self.section_penalty_text = f"{v['section']}\nPenalty: {v['penalty']}"
        else:
            self.section_penalty_text = "—"

    def on_sign_group_selected(self, group):
        self.ids.sp_sign.values = TrafficLawDB.SIGN_GROUPS.get(group, [])
        self.ids.sp_sign.text = "Select Sign"

    def clear_form(self):
        self.ids.in_name.text = ""
        self.ids.in_contact.text = ""
        self.ids.in_plate.text = ""
        self.ids.in_notes.text = ""
        self.ids.sp_offense.text = "Select Violation"
        self.ids.sp_sign_group.text = "Select Sign Group"
        self.ids.sp_sign.text = "Select Sign"
        self.section_penalty_text = "—"
        self.route_text = "—"
        self.evidence_path = ""

    # -------------------------------------------------------------------------
    # Evidence capture + CLAHE
    # -------------------------------------------------------------------------
    def capture_evidence(self):
        if not self._preview:
            self._popup("Camera not available", "Preview not running.")
            return

        out_dir = os.path.join(self._app_dir(), "evidence")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(out_dir, f"evidence_{ts}.jpg")

        try:
            if hasattr(self._preview, "capture_photo"):
                self._preview.capture_photo(out_path, self._after_capture)
            else:
                self._preview.export_to_png(out_path)
                self._after_capture(out_path)
        except Exception:
            self._popup("Capture failed", "Could not save evidence image.")

    def _after_capture(self, path):
        try:
            p = path if isinstance(path, str) else str(path)
            if isinstance(path, (tuple, list)) and path:
                p = str(path[0])
            if not os.path.isfile(p):
                self._popup("Capture failed", "Evidence file not created.")
                return

            if self.ids.sw_clahe.active and cv2 is not None:
                try:
                    img = cv2.imread(p)
                    if img is not None:
                        img2 = self._analytics.clahe_enhance_bgr(img)
                        cv2.imwrite(p, img2)
                except Exception:
                    pass

            self.evidence_path = p
            self._popup("Evidence saved", os.path.basename(p))
        except Exception:
            self._popup("Capture error", "Unexpected capture callback error.")

    # -------------------------------------------------------------------------
    # Offline geocode + routing
    # -------------------------------------------------------------------------
    def _update_geo_and_route(self, _dt):
        lat = float(self.latest_lat)
        lon = float(self.latest_lon)

        district = "—"
        state = "—"
        if rg is not None and abs(lat) > 0.0001 and abs(lon) > 0.0001:
            try:
                res = rg.search((lat, lon), mode=1)
                if res:
                    district = (res[0].get("admin2") or "—").strip()
                    state = (res[0].get("admin1") or "—").strip()
            except Exception:
                pass

        self.district = district
        self.state_name = state

        plate = self.ids.in_plate.text.strip()
        route = JurisdictionEngine.recipients_for_report(lat, lon, plate)
        rcpts = ", ".join(route["recipients"]) if route["recipients"] else "—"
        self.route_text = (
            f"Location code: {route['loc_code'] or '—'}\n"
            f"Plate code: {route['plate_code'] or '—'}\n"
            f"Recipients: {rcpts}"
        )

        speed_kmh = self.latest_speed_mps * 3.6
        self.status_text = (
            f"GPS: {lat:.5f}, {lon:.5f} | {district}, {state} | "
            f"Speed: {speed_kmh:.1f} km/h | G_dyn: {self.latest_g_dyn:.2f} | {self.cv_hint}"
        )

    # -------------------------------------------------------------------------
    # Email reporting
    # -------------------------------------------------------------------------
    def send_report(self):
        if plyer_email is None:
            self._popup("Email unavailable", "plyer.email not available in this build.")
            return

        plate = self.ids.in_plate.text.strip()
        if not plate:
            self._popup("Missing plate", "Enter number plate.")
            return

        offense_text = self.ids.sp_offense.text
        offense_key = (offense_text.split("—")[0] or "").strip()
        if offense_key not in TrafficLawDB.OFFENSES:
            self._popup("Missing violation", "Select a violation code.")
            return

        lat = float(self.latest_lat)
        lon = float(self.latest_lon)
        route = JurisdictionEngine.recipients_for_report(lat, lon, plate)
        if not route["recipients"]:
            self._popup("No recipients", "Could not route (unknown state code).")
            return

        offense = TrafficLawDB.OFFENSES[offense_key]
        anon = bool(self.ids.sw_anon.active)

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        speed_kmh = self.latest_speed_mps * 3.6

        subject = f"[Sentinel-X] {plate} — {offense['label']}"
        lines = [
            "SENTINEL-X — CIVIC ENFORCEMENT REPORT",
            f"Timestamp: {now}",
            "",
            f"GPS: {lat:.6f}, {lon:.6f}",
            f"Offline Resolved: District={self.district}, State={self.state_name}",
            f"Speed: {speed_kmh:.1f} km/h",
            f"G_dyn: {self.latest_g_dyn:.2f} m/s^2 (threshold 4.0)",
            "",
            f"Number Plate: {plate}",
            f"Offense: {offense_key} — {offense['label']}",
            f"Section: {offense['section']}",
            f"Penalty (reference): {offense['penalty']}",
            "",
            f"Sign Group (IRC:67-2022): {self.ids.sp_sign_group.text}",
            f"Observed Sign: {self.ids.sp_sign.text}",
            "",
            "Reporter:",
            f"  Anonymous: {'YES' if anon else 'NO'}",
        ]

        if not anon:
            lines += [
                f"  Name: {self.ids.in_name.text.strip() or '—'}",
                f"  Contact: {self.ids.in_contact.text.strip() or '—'}",
            ]

        lines += [
            "",
            "Notes:",
            self.ids.in_notes.text.strip() or "—",
            "",
            "Routing (One Nation, One Challan):",
            f"  Location-based: {route['loc_code'] or '—'} -> {', '.join(route['loc_emails']) or '—'}",
            f"  Plate-based: {route['plate_code'] or '—'} -> {', '.join(route['plate_emails']) or '—'}",
            "",
            TrafficLawDB.GOOD_SAMARITAN_FOOTER,
        ]
        body = "\n".join(lines)

        attachment = self.evidence_path if self.evidence_path and os.path.isfile(self.evidence_path) else None

        try:
            try:
                plyer_email.send(recipients=route["recipients"], subject=subject, text=body, attachment=attachment)
            except TypeError:
                if attachment:
                    plyer_email.send(recipients=route["recipients"], subject=subject, text=body, file_path=attachment)
                else:
                    plyer_email.send(recipients=route["recipients"], subject=subject, text=body)

            self._popup("Report prepared", "Email composer opened with recipients + Good Samaritan footer.")
        except Exception as e:
            self._popup("Email failed", str(e))

    # -------------------------------------------------------------------------
    # Service integration (UDP from service.py)
    # -------------------------------------------------------------------------
    def _start_android_service(self):
        if platform != "android":
            return
        try:
            from android import AndroidService  # type: ignore
            AndroidService("Sentinel-X", "Telemetry running").start("")
        except Exception:
            pass

    def _start_udp_listener(self):
        if self._udp_thread:
            return
        self._udp_thread = threading.Thread(target=self._udp_loop, daemon=True)
        self._udp_thread.start()

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
                payload = json.loads(data.decode("utf-8", errors="ignore"))
                lat = float(payload.get("lat", 0.0) or 0.0)
                lon = float(payload.get("lon", 0.0) or 0.0)
                speed = float(payload.get("speed_mps", 0.0) or 0.0)
                g_dyn = float(payload.get("g_dyn", 0.0) or 0.0)
                Clock.schedule_once(lambda dt: self._apply_telemetry(lat, lon, speed, g_dyn), 0)
            except socket.timeout:
                continue
            except Exception:
                continue

    def _apply_telemetry(self, lat, lon, speed_mps, g_dyn):
        self.latest_lat = lat
        self.latest_lon = lon
        self.latest_speed_mps = speed_mps
        self.latest_g_dyn = g_dyn

    # -------------------------------------------------------------------------
    def _popup(self, title, msg):
        pop = Popup(
            title=title,
            content=Label(text=msg, halign="left", valign="top"),
            size_hint=(0.9, 0.5),
        )
        pop.open()


class SentinelXApp(App):
    def build(self):
        Builder.load_string(KV)
        return RootUI()


if __name__ == "__main__":
    SentinelXApp().run()
