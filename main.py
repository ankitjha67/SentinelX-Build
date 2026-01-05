# -*- coding: utf-8 -*-
"""
Sentinel-X (Android / Kivy) — Civic Enforcement System (India)

- Camera Preview (camera4kivy preferred; safe fallback)
- Offline reverse-geocoding (reverse_geocoder; NO online APIs)
- Evidence capture + optional Night/Fog enhancement (CLAHE via opencv-python-headless)
- One Nation, One Challan routing: location-based + registration-based recipients
- Good Samaritan anonymity toggle ON by default + mandatory legal footer on every report
- Background service telemetry receive (UDP localhost) from service.py
"""

import os
import re
import json
import time
import socket
import threading
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.utils import platform as kivy_platform

IS_ANDROID = (kivy_platform == "android")

# -----------------------------------------------------------------------------
# Crash-prevention imports (MANDATORY per spec)
# -----------------------------------------------------------------------------
try:
    import cv2  # opencv-python-headless
except Exception:
    cv2 = None

try:
    from plyer import email as plyer_email
except Exception:
    plyer_email = None

try:
    import reverse_geocoder as rg  # offline
except Exception:
    rg = None

# Camera preview (preferred)
try:
    from camera4kivy import Preview as Camera4KivyPreview
except Exception:
    Camera4KivyPreview = None

# Android-only helpers
if IS_ANDROID:
    try:
        from android.permissions import request_permissions as android_request_permissions
    except Exception:
        android_request_permissions = None

    try:
        from android import AndroidService
    except Exception:
        AndroidService = None
else:
    android_request_permissions = None
    AndroidService = None

# -----------------------------------------------------------------------------
# Legal Footer (Hard requirement)
# -----------------------------------------------------------------------------
GOOD_SAMARITAN_FOOTER = (
    "This report is submitted under the protection of Section 134A of the Motor Vehicles Act, 1988, "
    "and the Good Samaritan Guidelines notified by MoRTH. The reporter voluntarily provides this information "
    "and shall not be compelled to be a witness or disclose personal identity."
)

# -----------------------------------------------------------------------------
# 1) Hardcoded Legal & Regulatory DB
# -----------------------------------------------------------------------------
class TrafficLawDB:
    """
    Static hardcoded mapping aligned to user-provided spec for:
    - Motor Vehicles (Amendment) Act, 2019 penalties (as provided)
    - IRC:67-2022 sign taxonomy (UI reference + new 2022 additions)
    """
    VIOLATIONS = {
        "SPD_183_LMV": {
            "name": "Speeding (LMV)",
            "section": "Motor Vehicles Act, 1988 — Section 183",
            "penalty": "₹1,000",
            "notes": "Light Motor Vehicle (LMV).",
        },
        "SPD_183_MHV": {
            "name": "Speeding (Medium/Heavy Vehicle)",
            "section": "Motor Vehicles Act, 1988 — Section 183",
            "penalty": "₹2,000",
            "notes": "Medium/Heavy Vehicle.",
        },
        "DNG_184": {
            "name": "Dangerous Driving",
            "section": "Motor Vehicles Act, 1988 — Section 184",
            "penalty": "₹1,000 to ₹5,000 (First Offense)",
            "notes": "Includes: Red Light Jumping, Stop Sign Violation, Use of Handheld Device.",
        },
        "SB_194B": {
            "name": "Driving without Safety Belt",
            "section": "Motor Vehicles Act, 1988 — Section 194B",
            "penalty": "₹1,000",
            "notes": "Safety belt violation.",
        },
        "TR_194C": {
            "name": "Triple Riding on Two-Wheeler",
            "section": "Motor Vehicles Act, 1988 — Section 194C",
            "penalty": "₹1,000 + License Disqualification",
            "notes": "Triple riding prohibited.",
        },
        "HL_194D": {
            "name": "Riding without Helmet",
            "section": "Motor Vehicles Act, 1988 — Section 194D",
            "penalty": "₹1,000 + License Disqualification",
            "notes": "Helmet mandatory on two-wheeler.",
        },
        "EM_194E": {
            "name": "Failure to yield to Emergency Vehicles",
            "section": "Motor Vehicles Act, 1988 — Section 194E",
            "penalty": "₹10,000",
            "notes": "Must yield to ambulance/fire/police vehicles.",
        },
    }

    # IRC:67-2022 sign taxonomy (UI reference)
    SIGNAGE = {
        "Mandatory (IRC:67-2022)": [
            "Speed Limit 50",
            "No Parking",
            "No U-Turn",
            "Compulsory Ahead Only",
        ],
        "Cautionary (IRC:67-2022)": [
            "School Ahead",
            "Pedestrian Crossing",
            "Road Narrows",
            "Speed Breaker",
        ],
        "New Additions (IRC:67-2022, 2022 updates)": [
            "EV Charging Station",
            "Bus Lane",
        ],
    }

    @staticmethod
    def list_violation_codes():
        return list(TrafficLawDB.VIOLATIONS.keys())

    @staticmethod
    def get_violation(code: str):
        return TrafficLawDB.VIOLATIONS.get(code)

    @staticmethod
    def list_sign_groups():
        return list(TrafficLawDB.SIGNAGE.keys())

    @staticmethod
    def list_signs_for_group(group: str):
        return TrafficLawDB.SIGNAGE.get(group, [])


# -----------------------------------------------------------------------------
# 2) Jurisdiction Engine (Dual Routing)
# -----------------------------------------------------------------------------
class JurisdictionEngine:
    """
    One Nation, One Challan logic:
    - Location-Based Authority: derived from offline reverse geocoding (lat/lon -> state/district)
    - Registration-Based Authority: derived from number plate prefix (e.g., MH)
    Sends to BOTH simultaneously (deduped).
    """

    # (B) Verified Email Directory (2025 Data) — HARDCODE EXACTLY AS PROVIDED
    EMAIL_DIRECTORY_2025 = {
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

    # Reverse geocoder commonly returns admin1 as state-equivalent; map name -> state code
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

    @staticmethod
    def _plate_state_code(number_plate: str) -> str:
        if not number_plate:
            return ""
        m = re.match(r"^\s*([A-Za-z]{2})", number_plate.strip())
        return (m.group(1).upper() if m else "")

    @staticmethod
    def reverse_geocode_offline(lat: float, lon: float):
        """
        Returns dict with keys: state_name, district_name, city_name (best effort), country_code
        Uses reverse_geocoder (offline). NO online APIs.
        """
        if rg is None:
            return {"state_name": "", "district_name": "", "city_name": "", "country_code": ""}

        try:
            res = rg.search((lat, lon), mode=1)  # mode=1 is faster KD-tree in many builds
            if not res:
                return {"state_name": "", "district_name": "", "city_name": "", "country_code": ""}

            r0 = res[0]
            # reverse_geocoder typical keys: name, admin1, admin2, cc
            return {
                "state_name": r0.get("admin1", "") or "",
                "district_name": r0.get("admin2", "") or "",
                "city_name": r0.get("name", "") or "",
                "country_code": r0.get("cc", "") or "",
            }
        except Exception:
            return {"state_name": "", "district_name": "", "city_name": "", "country_code": ""}

    @classmethod
    def route_recipients(cls, lat: float, lon: float, number_plate: str):
        """
        Returns (recipients_list, debug_dict)
        """
        plate_code = cls._plate_state_code(number_plate)

        geo = cls.reverse_geocode_offline(lat, lon)
        state_name = geo.get("state_name", "")
        district = (geo.get("district_name", "") or "").strip()
        city = (geo.get("city_name", "") or "").strip()

        location_code = cls.STATE_NAME_TO_CODE.get(state_name, "")

        recipients = set()

        # Location-based authority
        if location_code and location_code in cls.EMAIL_DIRECTORY_2025:
            # Special locality targeting (best effort):
            # - Gurugram: include dcp.trafficggn if location indicates Gurugram/Gurgaon
            # - Mumbai: include Mumbai address if location indicates Mumbai
            loc_emails = cls.EMAIL_DIRECTORY_2025[location_code]

            if location_code == "HR":
                # If Gurugram/Gurgaon in city or district, keep both already in list
                # Else keep only state HQ (igp.lo@hry.nic.in)
                if not (("gurugram" in (city + " " + district).lower()) or ("gurgaon" in (city + " " + district).lower())):
                    loc_emails = ["igp.lo@hry.nic.in"]

            if location_code == "MH":
                # If not Mumbai region, keep only state HQ
                if "mumbai" not in (city + " " + district).lower():
                    loc_emails = ["sp.hsp.hq@mahapolice.gov.in"]

            for e in loc_emails:
                recipients.add(e)

        # Registration-based authority
        if plate_code and plate_code in cls.EMAIL_DIRECTORY_2025:
            for e in cls.EMAIL_DIRECTORY_2025[plate_code]:
                recipients.add(e)

        debug = {
            "plate_code": plate_code,
            "location_state_name": state_name,
            "location_code": location_code,
            "district": district,
            "city": city,
            "recipients_count": len(recipients),
        }
        return sorted(recipients), debug


# -----------------------------------------------------------------------------
# 3) UI Root
# -----------------------------------------------------------------------------
class SentinelXRoot(BoxLayout):
    UDP_LISTEN_HOST = "127.0.0.1"
    UDP_LISTEN_PORT = 5055

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)

        self.telemetry = {
            "lat": 0.0,
            "lon": 0.0,
            "speed_mps": 0.0,
            "g_dyn": 0.0,
            "last_event": "",
            "ts": 0,
        }
        self.evidence_path = ""
        self.last_geo = {"state_name": "", "district_name": "", "city_name": "", "country_code": ""}

        # Header
        header = BoxLayout(size_hint_y=None, height=46, padding=8)
        header.add_widget(Label(text="[b]Sentinel-X[/b] — Civic Enforcement", markup=True, halign="left", valign="middle"))
        self.add_widget(header)

        # Camera / Preview area
        self.preview = self._build_preview()
        self.add_widget(self.preview)

        # Status bar
        self.status = Label(text="Status: initializing…", size_hint_y=None, height=34)
        self.add_widget(self.status)

        # Form area in scroll
        scroll = ScrollView()
        form_wrap = BoxLayout(orientation="vertical", size_hint_y=None, padding=8, spacing=8)
        form_wrap.bind(minimum_height=form_wrap.setter("height"))

        # Toggles row
        toggles = GridLayout(cols=2, size_hint_y=None, height=44, spacing=8)

        # Anonymity toggle (default ON)
        anon_box = BoxLayout(orientation="horizontal", spacing=8)
        self.anon_cb = CheckBox(active=True)
        anon_box.add_widget(self.anon_cb)
        anon_box.add_widget(Label(text="Submit Anonymously (default ON)"))
        toggles.add_widget(anon_box)

        # Night/Fog Mode toggle
        nf_box = BoxLayout(orientation="horizontal", spacing=8)
        self.night_cb = CheckBox(active=False)
        nf_box.add_widget(self.night_cb)
        nf_box.add_widget(Label(text="Night/Fog Mode (CLAHE)"))
        toggles.add_widget(nf_box)

        form_wrap.add_widget(toggles)

        # Inputs grid
        grid = GridLayout(cols=2, spacing=8, size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))

        def add_row(lbl, widget, h=40):
            grid.add_widget(Label(text=lbl, size_hint_y=None, height=h))
            widget.size_hint_y = None
            widget.height = h
            grid.add_widget(widget)

        self.name_in = TextInput(text="", multiline=False)
        add_row("Your Name (optional):", self.name_in)

        self.contact_in = TextInput(text="", multiline=False)
        add_row("Contact (optional):", self.contact_in)

        self.plate_in = TextInput(text="", multiline=False, hint_text="e.g., MH12AB1234")
        add_row("Number Plate:", self.plate_in)

        self.violation_sp = Spinner(
            text="Select Violation Code",
            values=TrafficLawDB.list_violation_codes(),
        )
        add_row("Violation Code:", self.violation_sp)

        self.violation_info = Label(text="Section / Penalty: —", size_hint_y=None, height=54)
        grid.add_widget(Label(text="Details:", size_hint_y=None, height=54))
        grid.add_widget(self.violation_info)

        # Signage group + sign
        self.sign_group_sp = Spinner(
            text="Select Sign Group",
            values=TrafficLawDB.list_sign_groups(),
        )
        add_row("Sign Group:", self.sign_group_sp)

        self.sign_sp = Spinner(text="Select Sign", values=[])
        add_row("Observed Sign:", self.sign_sp)

        self.notes_in = TextInput(text="", multiline=True, hint_text="Optional notes (what happened?)")
        self.notes_in.size_hint_y = None
        self.notes_in.height = 90
        grid.add_widget(Label(text="Notes:", size_hint_y=None, height=90))
        grid.add_widget(self.notes_in)

        form_wrap.add_widget(grid)

        # Buttons
        btn_row = GridLayout(cols=3, size_hint_y=None, height=48, spacing=8)

        cap_btn = Button(text="Capture Evidence")
        cap_btn.bind(on_release=lambda *_: self.capture_evidence())
        btn_row.add_widget(cap_btn)

        send_btn = Button(text="Send Report")
        send_btn.bind(on_release=lambda *_: self.send_report())
        btn_row.add_widget(send_btn)

        clr_btn = Button(text="Clear")
        clr_btn.bind(on_release=lambda *_: self.clear_form())
        btn_row.add_widget(clr_btn)

        form_wrap.add_widget(btn_row)

        scroll.add_widget(form_wrap)
        self.add_widget(scroll)

        # Bind spinners
        self.violation_sp.bind(text=self._on_violation_change)
        self.sign_group_sp.bind(text=self._on_sign_group_change)

        # Start UDP listener in background
        self._udp_thread = threading.Thread(target=self._udp_listener, daemon=True)
        self._udp_thread.start()

        Clock.schedule_interval(self._ui_tick, 0.5)

    def _build_preview(self):
        # Use camera4kivy Preview if available; else placeholder widget.
        if Camera4KivyPreview is not None:
            try:
                pv = Camera4KivyPreview()
                # connect camera after permissions in app.on_start
                return pv
            except Exception:
                pass
        return Widget()

    # -------------------------------------------------------------------------
    # Permissions (Audit: must not be empty and must contain this exact list)
    # -------------------------------------------------------------------------
    def request_permissions(self):
        permissions = [
            "android.permission.CAMERA",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.INTERNET",
            "android.permission.WRITE_EXTERNAL_STORAGE",
            "android.permission.FOREGROUND_SERVICE",
            "android.permission.WAKE_LOCK",
        ]
        if IS_ANDROID and android_request_permissions is not None:
            try:
                android_request_permissions(permissions)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Camera control (best effort)
    # -------------------------------------------------------------------------
    def connect_camera(self):
        if Camera4KivyPreview is None:
            return
        if hasattr(self.preview, "connect_camera"):
            try:
                self.preview.connect_camera()
            except Exception:
                pass

    def capture_evidence(self):
        # Evidence path (inside app user_data_dir)
        app = App.get_running_app()
        out_dir = os.path.join(app.user_data_dir, "evidence")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_path = os.path.join(out_dir, f"evidence_{ts}.png")

        # Export camera widget view to image (robust across camera widgets)
        try:
            self.preview.export_to_png(raw_path)
        except Exception:
            self.status.text = "Status: capture failed (camera preview not ready)."
            return

        # Optional CLAHE enhancement for night/fog
        final_path = raw_path
        if self.night_cb.active and cv2 is not None:
            try:
                img = cv2.imread(raw_path)
                if img is not None:
                    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
                    l, a, b = cv2.split(lab)
                    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                    cl = clahe.apply(l)
                    merged = cv2.merge((cl, a, b))
                    enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
                    enh_path = os.path.join(out_dir, f"evidence_{ts}_clahe.png")
                    cv2.imwrite(enh_path, enhanced)
                    final_path = enh_path
            except Exception:
                # If enhancement fails, keep raw
                final_path = raw_path

        self.evidence_path = final_path
        self.status.text = f"Status: evidence saved -> {os.path.basename(final_path)}"

    # -------------------------------------------------------------------------
    # Form helpers
    # -------------------------------------------------------------------------
    def _on_violation_change(self, *_):
        code = self.violation_sp.text
        v = TrafficLawDB.get_violation(code)
        if not v:
            self.violation_info.text = "Section / Penalty: —"
            return
        self.violation_info.text = f"{v['section']}\nPenalty: {v['penalty']}"

    def _on_sign_group_change(self, *_):
        group = self.sign_group_sp.text
        signs = TrafficLawDB.list_signs_for_group(group)
        self.sign_sp.values = signs
        self.sign_sp.text = ("Select Sign" if signs else "—")

    def clear_form(self):
        self.name_in.text = ""
        self.contact_in.text = ""
        self.plate_in.text = ""
        self.violation_sp.text = "Select Violation Code"
        self.sign_group_sp.text = "Select Sign Group"
        self.sign_sp.values = []
        self.sign_sp.text = "Select Sign"
        self.notes_in.text = ""
        self.evidence_path = ""
        self.status.text = "Status: cleared."

    # -------------------------------------------------------------------------
    # UDP telemetry receiver from service.py
    # -------------------------------------------------------------------------
    def _udp_listener(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((self.UDP_LISTEN_HOST, self.UDP_LISTEN_PORT))
        except Exception:
            return

        while True:
            try:
                data, _addr = s.recvfrom(8192)
                payload = json.loads(data.decode("utf-8", errors="ignore"))
                # Update shared telemetry
                for k in self.telemetry.keys():
                    if k in payload:
                        self.telemetry[k] = payload[k]
                # Events
                if payload.get("event") == "HARSH_BRAKE":
                    self.telemetry["last_event"] = f"HARSH_BRAKE g_dyn={payload.get('g_dyn', 0):.2f}"
            except Exception:
                pass

    def _ui_tick(self, _dt):
        lat = float(self.telemetry.get("lat", 0.0) or 0.0)
        lon = float(self.telemetry.get("lon", 0.0) or 0.0)
        spd = float(self.telemetry.get("speed_mps", 0.0) or 0.0)
        gdn = float(self.telemetry.get("g_dyn", 0.0) or 0.0)
        ev = self.telemetry.get("last_event", "")

        # Offline geocode (best effort, not too frequent)
        if (abs(lat) > 0.0001 and abs(lon) > 0.0001):
            self.last_geo = JurisdictionEngine.reverse_geocode_offline(lat, lon)

        geo_str = ""
        if self.last_geo.get("state_name"):
            geo_str = f"{self.last_geo.get('district_name','')}, {self.last_geo.get('state_name','')}".strip(", ")

        self.status.text = (
            f"GPS: {lat:.5f}, {lon:.5f} | Speed: {spd:.1f} m/s | G_dyn: {gdn:.2f} | {geo_str} | {ev}"
        )

    # -------------------------------------------------------------------------
    # Report building + Email sending
    # -------------------------------------------------------------------------
    def _build_report(self):
        lat = float(self.telemetry.get("lat", 0.0) or 0.0)
        lon = float(self.telemetry.get("lon", 0.0) or 0.0)
        spd = float(self.telemetry.get("speed_mps", 0.0) or 0.0)
        gdn = float(self.telemetry.get("g_dyn", 0.0) or 0.0)

        plate = self.plate_in.text.strip()
        vio_code = self.violation_sp.text.strip()
        vio = TrafficLawDB.get_violation(vio_code) if vio_code else None

        sign_group = self.sign_group_sp.text.strip()
        sign = self.sign_sp.text.strip()

        geo = self.last_geo or {"state_name": "", "district_name": "", "city_name": ""}

        # Dual routing
        recipients, debug = JurisdictionEngine.route_recipients(lat, lon, plate)

        anon = bool(self.anon_cb.active)
        reporter_name = ("" if anon else self.name_in.text.strip())
        reporter_contact = ("" if anon else self.contact_in.text.strip())

        subject = f"Sentinel-X Traffic Violation Report | Plate {plate or 'UNKNOWN'} | {vio_code or 'NO_CODE'}"

        lines = []
        lines.append("SENTINEL-X — CIVIC ENFORCEMENT REPORT")
        lines.append(f"Timestamp (Local): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("1) Violation")
        lines.append(f"- Number Plate: {plate or 'UNKNOWN'}")
        lines.append(f"- Offense Code: {vio_code or 'NOT SELECTED'}")
        if vio:
            lines.append(f"- Section: {vio.get('section','')}")
            lines.append(f"- Penalty (as per app DB): {vio.get('penalty','')}")
            if vio.get("notes"):
                lines.append(f"- Includes/Notes: {vio.get('notes')}")
        lines.append("")
        lines.append("2) Location & Telematics")
        lines.append(f"- GPS: {lat:.6f}, {lon:.6f}")
        lines.append(f"- Offline Resolved: District={geo.get('district_name','')}, State={geo.get('state_name','')}, City={geo.get('city_name','')}")
        lines.append(f"- Speed (approx): {spd:.2f} m/s")
        lines.append(f"- Dynamic G-Force (G_dyn): {gdn:.2f} m/s^2")
        lines.append("")
        lines.append("3) Road Signage Reference (IRC:67-2022)")
        lines.append(f"- Sign Group: {sign_group if sign_group and sign_group != 'Select Sign Group' else 'N/A'}")
        lines.append(f"- Observed Sign: {sign if sign and sign != 'Select Sign' else 'N/A'}")
        lines.append("")
        lines.append("4) Notes (Reporter)")
        notes = self.notes_in.text.strip() or "N/A"
        lines.append(notes)
        lines.append("")
        lines.append("5) Routing (One Nation, One Challan)")
        lines.append(f"- Registration-based (plate code): {debug.get('plate_code','') or 'UNKNOWN'}")
        lines.append(f"- Location-based (state code): {debug.get('location_code','') or 'UNKNOWN'} (state_name={debug.get('location_state_name','')})")
        lines.append(f"- Recipients (deduped): {', '.join(recipients) if recipients else 'NONE'}")
        lines.append("")
        lines.append("6) Reporter Identity")
        lines.append(f"- Submitted Anonymously: {'YES' if anon else 'NO'}")
        if not anon:
            lines.append(f"- Name: {reporter_name or 'N/A'}")
            lines.append(f"- Contact: {reporter_contact or 'N/A'}")
        lines.append("")
        lines.append("—")
        lines.append(GOOD_SAMARITAN_FOOTER)

        body = "\n".join(lines)
        return subject, body, recipients

    def send_report(self):
        if not self.evidence_path or not os.path.exists(self.evidence_path):
            self.status.text = "Status: please Capture Evidence first."
            return

        subject, body, recipients = self._build_report()
        if not recipients:
            # Still allow user to compose; but warn
            self.status.text = "Status: recipients could not be resolved (missing GPS/plate/state)."
            # Continue: user might manually forward

        # Use Plyer email composer (Android-friendly)
        if plyer_email is not None:
            try:
                plyer_email.send(
                    recipient=",".join(recipients) if recipients else "",
                    subject=subject,
                    text=body,
                    create_chooser=True,
                    file_path=[self.evidence_path],
                )
                self.status.text = "Status: email composer opened (attach + send)."
                return
            except Exception:
                pass

        # Fallback: cannot attach; still open a mail draft
        try:
            import webbrowser
            import urllib.parse
            mailto = "mailto:" + (",".join(recipients) if recipients else "")
            q = urllib.parse.urlencode({"subject": subject, "body": body})
            webbrowser.open(f"{mailto}?{q}")
            self.status.text = "Status: mail draft opened (attachment not supported in fallback)."
        except Exception:
            self.status.text = "Status: failed to open email composer."


# -----------------------------------------------------------------------------
# 4) App
# -----------------------------------------------------------------------------
class SentinelXApp(App):
    def build(self):
        self.title = "Sentinel-X"
        self.root_widget = SentinelXRoot()
        return self.root_widget

    def on_start(self):
        # Permissions
        self.root_widget.request_permissions()

        # Camera connect (best effort)
        Clock.schedule_once(lambda *_: self.root_widget.connect_camera(), 0.5)

        # Start background service (Android only)
        if IS_ANDROID and AndroidService is not None:
            try:
                svc = AndroidService("Sentinel-X Service", "Telemetry + Harsh Braking Monitor")
                svc.start("service started")
            except Exception:
                pass


if __name__ == "__main__":
    SentinelXApp().run()
