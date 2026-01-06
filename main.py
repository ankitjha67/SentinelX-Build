# -*- coding: utf-8 -*-
"""
Sentinel-X — Civic Enforcement (Kivy + Plyer + camera4kivy)
Production-oriented single-file UI:
- Hardcoded legal DB (MVA 2019 + IRC:67-2022 references)
- Dual jurisdiction routing (location-based + plate-based)
- Offline reverse geocoding (reverse_geocoder)
- Evidence capture (camera4kivy)
- Night/Fog enhancement (CLAHE) before saving evidence (best-effort if OpenCV available)
- Optional Live CV Assist (best-effort plate-candidate detection + optional ONNX detector if user adds model)
- Background service telemetry via UDP (service.py) for G-dyn + speed + GPS
- Good Samaritan anonymity toggle default ON + mandatory legal footer in email
"""

import os
import re
import json
import time
import math
import socket
import threading
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.lang import Builder
from kivy.utils import platform
from kivy.properties import StringProperty, BooleanProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label

# ----------------------------
# Crash prevention imports
# ----------------------------
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

# Android permission helper (runtime permissions)
Permission = None
request_permissions = None
check_permission = None
try:
    if platform == "android":
        from android.permissions import Permission as _Permission  # type: ignore
        from android.permissions import request_permissions as _request_permissions  # type: ignore
        from android.permissions import check_permission as _check_permission  # type: ignore
        Permission = _Permission
        request_permissions = _request_permissions
        check_permission = _check_permission
except Exception:
    Permission = None
    request_permissions = None
    check_permission = None

# camera4kivy
Preview = None
try:
    from camera4kivy import Preview  # type: ignore
except Exception:
    Preview = None


# =============================================================================
# 1) Legal & Regulatory DB (hardcoded)
# =============================================================================
class TrafficLawDB:
    """
    Static database: Motor Vehicles (Amendment) Act 2019 + IRC:67-2022 sign groups.
    NOTE: This is a citizen reporting tool; final challan/compounding depends on state notifications.
    """

    # A) MVA 2019 — Offense codes -> sections + penalties (as requested)
    OFFENSES = {
        "SPEEDING_183_LMV": {
            "label": "Speeding (LMV)",
            "section": "MVA 1988 (Amended 2019) — Section 183",
            "penalty": "₹1,000 (LMV)",
            "notes": "Over-speeding for Light Motor Vehicle.",
        },
        "SPEEDING_183_HMV": {
            "label": "Speeding (Medium/Heavy Vehicle)",
            "section": "MVA 1988 (Amended 2019) — Section 183",
            "penalty": "₹2,000 (Medium/Heavy)",
            "notes": "Over-speeding for medium/heavy passenger or goods vehicle.",
        },
        "DANGEROUS_184": {
            "label": "Dangerous Driving (Red light / Stop sign / Handheld device)",
            "section": "MVA 1988 (Amended 2019) — Section 184",
            "penalty": "₹1,000 to ₹5,000 (First offense)",
            "notes": "Includes red light jumping, stop sign violation, handheld device use, etc.",
        },
        "SEATBELT_194B": {
            "label": "Driving without Safety Belt",
            "section": "MVA 1988 (Amended 2019) — Section 194B",
            "penalty": "₹1,000",
            "notes": "Seat belt violation.",
        },
        "TRIPLE_194C": {
            "label": "Triple Riding on Two-Wheeler",
            "section": "MVA 1988 (Amended 2019) — Section 194C",
            "penalty": "₹1,000 + License Disqualification",
            "notes": "Triple riding; states may apply suspension/disqualification rules.",
        },
        "HELMET_194D": {
            "label": "Riding without Helmet",
            "section": "MVA 1988 (Amended 2019) — Section 194D",
            "penalty": "₹1,000 + License Disqualification",
            "notes": "Helmet violation; suspension/disqualification per rules.",
        },
        "EMERGENCY_194E": {
            "label": "Failure to yield to Emergency Vehicles",
            "section": "MVA 1988 (Amended 2019) — Section 194E",
            "penalty": "₹10,000",
            "notes": "Blocking ambulance/fire/police emergency vehicles.",
        },
    }

    # B) IRC:67-2022 signage groups (UI reference)
    SIGN_GROUPS = {
        "Mandatory (IRC:67-2022)": [
            "Speed Limit 50",
            "No Parking",
            "No U-Turn",
            "Compulsory Left",
            "Compulsory Right",
            # 2022 additions
            "EV Charging Station",
            "Bus Lane",
        ],
        "Cautionary (IRC:67-2022)": [
            "School Ahead",
            "Pedestrian Crossing",
            "Speed Breaker",
            "Narrow Road Ahead",
            "Slippery Road",
        ],
    }

    # C) Good Samaritan Protection — Section 134A (as requested)
    GOOD_SAMARITAN_FOOTER = (
        "This report is submitted under the protection of Section 134A of the Motor Vehicles Act, 1988, "
        "and the Good Samaritan Guidelines notified by MoRTH. The reporter voluntarily provides this "
        "information and shall not be compelled to be a witness or disclose personal identity."
    )

    # =============================================================================
    # 2) Verified Email Directory (structure requested) — DO NOT CHANGE KEYS/FORMAT
    # =============================================================================
    VERIFIED_EMAILS_2025 = {
        "DL": ["addlcp.tfchq@delhipolice.gov.in"],
        "MH": ["sp.hsp.hq@mahapolice.gov.in", "cp.mumbai.jtcp.traf@mahapolice.gov.in"],  # includes Mumbai
        "KA": ["bangloretrafficpolice@gmail.com"],
        "TN": ["cctnstn@tn.gov.in"],
        "UP": ["traffic_dir@uppolice.gov.in"],
        "HR": ["igp.lo@hry.nic.in", "dcp.trafficggn@hry.nic.in"],  # includes Gurugram
        "KL": ["sptrafficsz.pol@kerala.gov.in"],
        "GJ": ["dig-traffic-ahd@gujarat.gov.in"],
        "WB": ["dctp@kolkatatrafficpolice.gov.in"],
        "TS": ["addlcptraffic@hyd.tspolice.gov.in"],
        "PB": ["trafficpolicepunjab@gmail.com"],
        "RJ": ["adgp.traffic@rajpolice.gov.in"],
        "GA": ["sp_traffic@goapolice.gov.in"],
    }

    # State name -> code mapping (for offline reverse_geocoder admin1)
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
# 2) JurisdictionEngine (One Nation, One Challan — dual routing)
# =============================================================================
class JurisdictionEngine:
    PLATE_RE = re.compile(r"^\s*([A-Z]{2})\s*\d{1,2}\s*[A-Z]{0,3}\s*\d{3,4}\s*$", re.I)

    @staticmethod
    def normalize_plate(raw: str) -> str:
        s = (raw or "").upper()
        s = re.sub(r"[^A-Z0-9]", "", s)
        return s

    @staticmethod
    def extract_state_code_from_plate(raw: str) -> str:
        s = (raw or "").strip().upper()
        m = JurisdictionEngine.PLATE_RE.match(s)
        if m:
            return m.group(1).upper()
        # fallback: first 2 letters in normalized plate
        n = JurisdictionEngine.normalize_plate(raw)
        if len(n) >= 2 and n[:2].isalpha():
            return n[:2]
        return ""

    @staticmethod
    def location_state_code_from_latlon(lat: float, lon: float) -> str:
        if rg is None:
            return ""
        try:
            res = rg.search((lat, lon), mode=1)  # offline KD-tree lookup
            if not res:
                return ""
            admin1 = (res[0].get("admin1") or "").strip()
            return TrafficLawDB.STATE_NAME_TO_CODE.get(admin1, "")
        except Exception:
            return ""

    @staticmethod
    def recipients_for_report(lat: float, lon: float, plate_raw: str):
        loc_code = JurisdictionEngine.location_state_code_from_latlon(lat, lon)
        plate_code = JurisdictionEngine.extract_state_code_from_plate(plate_raw)

        loc_emails = TrafficLawDB.VERIFIED_EMAILS_2025.get(loc_code, []) if loc_code else []
        plate_emails = TrafficLawDB.VERIFIED_EMAILS_2025.get(plate_code, []) if plate_code else []

        # dual-route union (dedupe)
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
# 3) AnalyticsEngine (lightweight, configurable)
# =============================================================================
class AnalyticsEngine:
    """
    "Advanced analytics models easily configurable":
    - Built-in lightweight CV heuristics (plate candidate detection)
    - Optional ONNX model via OpenCV DNN if user provides file (no internet required)
      Place model at: <app_dir>/models/detector.onnx  (example)
    """

    def __init__(self, app_dir: str):
        self.app_dir = app_dir
        self.model_path = os.path.join(app_dir, "models", "detector.onnx")
        self.model = None
        self.model_loaded = False

    def try_load_model(self):
        if self.model_loaded:
            return
        self.model_loaded = True
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
            limg = cv2.merge((cl, a, b))
            out = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
            return out
        except Exception:
            return img_bgr

    @staticmethod
    def detect_plate_candidates_bgr(img_bgr):
        """
        Very lightweight heuristic: find rectangular, high-edge-density regions.
        Returns list of (x, y, w, h) sorted by area desc (top few only).
        """
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

    def run_optional_onnx(self, img_bgr):
        """
        Optional: If user provides an ONNX detector, run it here.
        Return a simple boolean for "object detected" without hard assumptions.
        """
        self.try_load_model()
        if self.model is None or cv2 is None:
            return False
        try:
            blob = cv2.dnn.blobFromImage(img_bgr, scalefactor=1 / 255.0, size=(320, 320), swapRB=True, crop=False)
            self.model.setInput(blob)
            out = self.model.forward()
            # Since detector formats vary, we keep it conservative: any non-trivial activation counts as "something"
            # You can customize parsing per your model.
            score = float(np.max(out)) if np is not None else 0.0
            return score > 0.5
        except Exception:
            return False


# =============================================================================
# UI + Service Telemetry Listener
# =============================================================================
KV = r"""
<RootUI>:
    orientation: "vertical"
    padding: dp(8)
    spacing: dp(6)

    BoxLayout:
        id: header
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
            id: camera_fallback
            text: "Camera preview unavailable\\n(camera4kivy not loaded)"
            halign: "center"
            valign: "middle"
            text_size: self.size

    BoxLayout:
        size_hint_y: None
        height: dp(44)
        spacing: dp(8)
        Label:
            id: status_line
            text: root.status_text
            font_size: "12sp"
            halign: "left"
            valign: "middle"
            text_size: self.size

    ScrollView:
        do_scroll_x: False
        bar_width: dp(6)

        GridLayout:
            id: form
            cols: 2
            size_hint_y: None
            height: self.minimum_height
            row_default_height: dp(44)
            row_force_default: False
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
                id: lab_section
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
                valign: "middle"
                text_size: self.size
            Label:
                id: lab_route
                text: root.route_text
                halign: "left"
                valign: "middle"
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
    state_code = StringProperty("")

    offense_key = StringProperty("")
    evidence_path = StringProperty("")
    cv_hint = StringProperty("")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._udp_thread = None
        self._udp_stop = threading.Event()
        self._analytics = AnalyticsEngine(app_dir=self._get_app_dir())
        self._cv_clock_ev = None
        self._preview = None

        Clock.schedule_once(self._post_build, 0)

    def _get_app_dir(self) -> str:
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            return "."

    def _post_build(self, _dt):
        # populate spinners
        offense_items = []
        for k, v in TrafficLawDB.OFFENSES.items():
            offense_items.append(f"{k} — {v['label']}")
        self.ids.sp_offense.values = offense_items

        self.ids.sp_sign_group.values = list(TrafficLawDB.SIGN_GROUPS.keys())

        # Start camera if available
        self._setup_camera_preview()

        # Start telemetry listener from service
        self._start_udp_listener()

        # Start Android background service
        self._start_background_service()

        # Permissions
        self._request_runtime_permissions()

        # Update geocode periodically (best effort)
        Clock.schedule_interval(self._update_geocode_and_routing, 1.0)

    # -------------------------------------------------------------------------
    # Permissions (MUST NOT BE EMPTY BRACKETS)
    # -------------------------------------------------------------------------
    def _request_runtime_permissions(self):
        if platform != "android" or request_permissions is None or Permission is None:
            return

        # MUST contain this exact list (non-empty):
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
    # Camera Setup + Live CV Assist
    # -------------------------------------------------------------------------
    def _setup_camera_preview(self):
        box = self.ids.camera_box
        box.clear_widgets()

        if Preview is None:
            # fallback label
            box.add_widget(self.ids.camera_fallback)
            return

        try:
            self._preview = Preview()
            self._preview.size_hint = (1, 1)
            box.add_widget(self._preview)
            # Best practice with camera4kivy: connect on_start
            Clock.schedule_once(lambda dt: self._safe_preview_start(), 0.2)

            # Live CV Assist loop
            self._cv_clock_ev = Clock.schedule_interval(self._live_cv_tick, 0.6)
        except Exception:
            box.add_widget(self.ids.camera_fallback)
            self._preview = None

    def _safe_preview_start(self):
        if not self._preview:
            return
        try:
            # camera4kivy uses "connect_camera" in many versions
            if hasattr(self._preview, "connect_camera"):
                self._preview.connect_camera(enable_analyze_pixels=True)
            elif hasattr(self._preview, "start"):
                self._preview.start()
        except Exception:
            pass

    def _live_cv_tick(self, _dt):
        # Only if enabled
        if not self.ids.sw_cv.active:
            return
        if self._preview is None:
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

            # texture.pixels is RGBA bytes in many cases
            buf = tex.pixels
            arr = np.frombuffer(buf, dtype=np.uint8)
            arr = arr.reshape((h, w, 4))
            rgb = arr[:, :, :3]
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

            # low-light assist only affects captured evidence by design; here we only hint
            boxes = self._analytics.detect_plate_candidates_bgr(bgr)

            # Optional ONNX
            onnx_hit = self._analytics.run_optional_onnx(bgr)

            if boxes:
                self.cv_hint = f"CV: Plate-like region(s) detected: {len(boxes)}"
            elif onnx_hit:
                self.cv_hint = "CV: Optional model detected an object"
            else:
                self.cv_hint = "CV: No strong cues"

        except Exception:
            # never crash UI
            return

    # -------------------------------------------------------------------------
    # Evidence Capture + CLAHE
    # -------------------------------------------------------------------------
    def capture_evidence(self):
        # Create evidence directory
        ev_dir = os.path.join(self._get_app_dir(), "evidence")
        os.makedirs(ev_dir, exist_ok=True)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join(ev_dir, f"evidence_{ts}.jpg")

        if self._preview is None:
            self._popup("Camera not available", "Camera preview is not running.")
            return

        # Try camera4kivy native capture if available
        try:
            if hasattr(self._preview, "capture_photo"):
                self._preview.capture_photo(out_path, self._after_capture)
                return
        except Exception:
            pass

        # fallback: export widget snapshot (may not include camera pixels on some devices)
        try:
            self._preview.export_to_png(out_path)
            self._after_capture(out_path)
        except Exception:
            self._popup("Capture failed", "Could not capture evidence image.")

    def _after_capture(self, path):
        try:
            p = path if isinstance(path, str) else str(path)
            if not os.path.isfile(p):
                # some camera4kivy versions call callback with (path, *args)
                if isinstance(path, (tuple, list)) and path:
                    p = str(path[0])
            if not os.path.isfile(p):
                self._popup("Capture failed", "Evidence file was not created.")
                return

            # Night/Fog Mode (CLAHE) before saving
            if self.ids.sw_clahe.active and cv2 is not None:
                try:
                    img = cv2.imread(p)
                    if img is not None:
                        img2 = self._analytics.clahe_enhance_bgr(img)
                        cv2.imwrite(p, img2)
                except Exception:
                    pass

            self.evidence_path = p
            self._popup("Evidence saved", f"Saved: {os.path.basename(p)}")

        except Exception:
            self._popup("Capture error", "Unexpected capture callback error.")

    # -------------------------------------------------------------------------
    # Form logic
    # -------------------------------------------------------------------------
    def on_offense_selected(self, spinner_text: str):
        # spinner item looks like: "KEY — label"
        key = (spinner_text.split("—")[0] or "").strip()
        if key in TrafficLawDB.OFFENSES:
            self.offense_key = key
            v = TrafficLawDB.OFFENSES[key]
            self.section_penalty_text = f"{v['section']}\nPenalty: {v['penalty']}"
        else:
            self.offense_key = ""
            self.section_penalty_text = "—"

    def on_sign_group_selected(self, group: str):
        signs = TrafficLawDB.SIGN_GROUPS.get(group, [])
        self.ids.sp_sign.values = signs
        if signs:
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
        self.offense_key = ""
        self.evidence_path = ""

    # -------------------------------------------------------------------------
    # Routing + reverse geocode
    # -------------------------------------------------------------------------
    def _update_geocode_and_routing(self, _dt):
        lat = float(self.latest_lat)
        lon = float(self.latest_lon)

        # offline reverse geocode
        district = ""
        state = ""
        code = ""
        if rg is not None and abs(lat) > 0.0001 and abs(lon) > 0.0001:
            try:
                res = rg.search((lat, lon), mode=1)
                if res:
                    district = (res[0].get("admin2") or "").strip()
                    state = (res[0].get("admin1") or "").strip()
                    code = TrafficLawDB.STATE_NAME_TO_CODE.get(state, "")
            except Exception:
                pass

        self.district = district
        self.state_name = state
        self.state_code = code

        plate_raw = self.ids.in_plate.text
        route = JurisdictionEngine.recipients_for_report(lat, lon, plate_raw)

        loc = route["loc_code"] or "—"
        pl = route["plate_code"] or "—"
        rcpts = route["recipients"] or []
        rcpt_text = ", ".join(rcpts) if rcpts else "—"

        self.route_text = f"Location: {loc} | Plate: {pl}\nRecipients: {rcpt_text}"

        # Update status line
        speed_kmh = self.latest_speed_mps * 3.6
        self.status_text = (
            f"GPS: {lat:.5f}, {lon:.5f} | {district or '—'}, {state or '—'} | "
            f"Speed: {speed_kmh:.1f} km/h | G_dyn: {self.latest_g_dyn:.2f} | {self.cv_hint}"
        )

    # -------------------------------------------------------------------------
    # Email reporting
    # -------------------------------------------------------------------------
    def send_report(self):
        if plyer_email is None:
            self._popup("Email unavailable", "plyer.email is not available on this build/device.")
            return

        lat = float(self.latest_lat)
        lon = float(self.latest_lon)

        plate = self.ids.in_plate.text.strip()
        if not plate:
            self._popup("Missing number plate", "Please enter the number plate.")
            return

        if not self.offense_key or self.offense_key not in TrafficLawDB.OFFENSES:
            self._popup("Missing violation", "Please select a violation code.")
            return

        route = JurisdictionEngine.recipients_for_report(lat, lon, plate)
        recipients = route["recipients"]
        if not recipients:
            self._popup(
                "No recipients",
                "Could not determine recipients (state code not mapped). You can still file via local portal.",
            )
            return

        offense = TrafficLawDB.OFFENSES[self.offense_key]
        anon = self.ids.sw_anon.active

        reporter_name = self.ids.in_name.text.strip() if not anon else ""
        reporter_contact = self.ids.in_contact.text.strip() if not anon else ""

        sign_group = self.ids.sp_sign_group.text if "Select" not in self.ids.sp_sign_group.text else ""
        sign = self.ids.sp_sign.text if "Select" not in self.ids.sp_sign.text else ""

        notes = self.ids.in_notes.text.strip()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        speed_kmh = self.latest_speed_mps * 3.6

        subject = f"[Sentinel-X] Traffic Violation Report — {plate} — {offense['label']}"

        body_lines = [
            "SENTINEL-X — CIVIC ENFORCEMENT REPORT",
            f"Timestamp: {now}",
            "",
            f"Location (GPS): {lat:.6f}, {lon:.6f}",
            f"Resolved (Offline): District={self.district or '—'}, State={self.state_name or '—'}",
            f"Speed (GPS): {speed_kmh:.1f} km/h",
            f"G_dyn (telemetry): {self.latest_g_dyn:.2f} m/s^2 (threshold 4.0 for dangerous driving alert)",
            "",
            f"Number Plate: {plate}",
            f"Offense Code: {self.offense_key}",
            f"Section: {offense['section']}",
            f"Penalty (reference): {offense['penalty']}",
            f"Details: {offense.get('notes','')}",
            "",
            f"Sign Group (IRC:67-2022): {sign_group or '—'}",
            f"Observed Sign: {sign or '—'}",
            "",
            "Reporter:",
            f"  Anonymous: {'YES' if anon else 'NO'}",
        ]

        if not anon:
            body_lines += [
                f"  Name: {reporter_name or '—'}",
                f"  Contact: {reporter_contact or '—'}",
            ]

        body_lines += [
            "",
            "Notes:",
            notes or "—",
            "",
            "Routing (One Nation, One Challan):",
            f"  Location-based code: {route['loc_code'] or '—'} -> {', '.join(route['loc_emails']) or '—'}",
            f"  Plate-based code: {route['plate_code'] or '—'} -> {', '.join(route['plate_emails']) or '—'}",
            "",
            TrafficLawDB.GOOD_SAMARITAN_FOOTER,
        ]

        body = "\n".join(body_lines)

        # Attach evidence best-effort (plyer API differs across versions)
        attachment = self.evidence_path if self.evidence_path and os.path.isfile(self.evidence_path) else None

        try:
            # Try common signatures safely
            try:
                plyer_email.send(
                    recipients=recipients,
                    subject=subject,
                    text=body,
                    attachment=attachment,
                )
            except TypeError:
                # older plyer
                if attachment:
                    plyer_email.send(recipients=recipients, subject=subject, text=body, file_path=attachment)
                else:
                    plyer_email.send(recipients=recipients, subject=subject, text=body)
            self._popup("Report prepared", "Email composer opened with recipients + Good Samaritan footer.")
        except Exception as e:
            self._popup("Email failed", f"Could not open email composer.\n{e}")

    # -------------------------------------------------------------------------
    # Service integration (UDP)
    # -------------------------------------------------------------------------
    def _start_background_service(self):
        if platform != "android":
            return
        try:
            from android import AndroidService  # type: ignore
            service = AndroidService("Sentinel-X", "Telemetry running (GPS + G-force)")
            service.start("")  # argument optional
        except Exception:
            # never crash
            return

    def _start_udp_listener(self):
        if self._udp_thread is not None:
            return
        self._udp_thread = threading.Thread(target=self._udp_loop, daemon=True)
        self._udp_thread.start()

    def _udp_loop(self):
        """
        Receives telemetry JSON from service.py on UDP localhost:17888.
        Payload example:
        {"lat":..., "lon":..., "speed_mps":..., "g_dyn":..., "ts":...}
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind(("127.0.0.1", 17888))
            s.settimeout(1.0)
        except Exception:
            return

        while not self._udp_stop.is_set():
            try:
                data, _addr = s.recvfrom(4096)
                if not data:
                    continue
                try:
                    payload = json.loads(data.decode("utf-8", errors="ignore"))
                except Exception:
                    continue

                lat = float(payload.get("lat", 0.0) or 0.0)
                lon = float(payload.get("lon", 0.0) or 0.0)
                speed = float(payload.get("speed_mps", 0.0) or 0.0)
                g_dyn = float(payload.get("g_dyn", 0.0) or 0.0)

                # Push into UI thread
                Clock.schedule_once(lambda dt, a=lat, o=lon, sp=speed, g=g_dyn: self._apply_telemetry(a, o, sp, g), 0)

            except socket.timeout:
                continue
            except Exception:
                continue

    def _apply_telemetry(self, lat, lon, speed_mps, g_dyn):
        self.latest_lat = lat
        self.latest_lon = lon
        self.latest_speed_mps = speed_mps
        self.latest_g_dyn = g_dyn

        # Simple auto-suggestion (non-binding): if harsh braking threshold exceeded, suggest dangerous driving
        if g_dyn > 4.0 and (self.ids.sp_offense.text.startswith("Select") or not self.offense_key):
            # Auto-select dangerous driving
            dd_key = "DANGEROUS_184"
            v = TrafficLawDB.OFFENSES[dd_key]
            self.offense_key = dd_key
            self.section_penalty_text = f"{v['section']}\nPenalty: {v['penalty']}"
            # Update spinner text if present in values
            for item in self.ids.sp_offense.values:
                if item.startswith(dd_key + " "):
                    self.ids.sp_offense.text = item
                    break

    # -------------------------------------------------------------------------
    # UI helpers
    # -------------------------------------------------------------------------
    def _popup(self, title: str, msg: str):
        content = Label(text=msg, halign="left", valign="top")
        content.text_size = (dp(360), None)
        pop = Popup(title=title, content=content, size_hint=(0.9, 0.5))
        pop.open()


class SentinelXApp(App):
    def build(self):
        Builder.load_string(KV)
        return RootUI()


if __name__ == "__main__":
    SentinelXApp().run()
