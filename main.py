# -*- coding: utf-8 -*-
"""
Sentinel-X v1.0 -- Civic Enforcement (Android)
All 7 Android blockers FIXED. Python 3.10 compatible (no backslash in f-strings).
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
        "SPEEDING_183_LMV": {"label": "Speeding (LMV)", "section": "MVA 2019 -- Section 183", "penalty": "Rs.1,000"},
        "SPEEDING_183_HMV": {"label": "Speeding (HMV)", "section": "MVA 2019 -- Section 183", "penalty": "Rs.2,000"},
        "DANGEROUS_184":    {"label": "Dangerous Driving", "section": "MVA 2019 -- Section 184", "penalty": "Rs.1,000-Rs.5,000"},
        "SEATBELT_194B":    {"label": "No Safety Belt", "section": "MVA 2019 -- Section 194B", "penalty": "Rs.1,000"},
        "TRIPLE_194C":      {"label": "Triple Riding", "section": "MVA 2019 -- Section 194C", "penalty": "Rs.1,000 + Disq."},
        "HELMET_194D":      {"label": "No Helmet", "section": "MVA 2019 -- Section 194D", "penalty": "Rs.1,000 + Disq."},
        "EMERGENCY_194E":   {"label": "Blocking Emergency Vehicle", "section": "MVA 2019 -- Section 194E", "penalty": "Rs.10,000"},
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
    def __init__(self, app_dir):
        self.app_dir = app_dir
        self.model_path = os.path.join(app_dir, "models", "detector.onnx")
        self.model = None
        self._tried = False
        self.result = ""
        self._skip = 0

    def try_load_model(self):
        if self._tried:
            return
        self._tried = True
        if cv2 and os.path.isfile(self.model_path):
            try:
                self.model = cv2.dnn.readNetFromONNX(self.model_path)
            except Exception:
                self.model = None

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

    @staticmethod
    def find_plates(bgr):
        if cv2 is None:
            return []
        try:
            gray = cv2.bilateralFilter(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), 9, 75, 75)
            cnts, _ = cv2.findContours(cv2.Canny(gray, 60, 180), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            out = []
            for c in cnts:
                x, y, w, h = cv2.boundingRect(c)
                ar = w / max(h, 1)
                if w >= 60 and h >= 20 and 2.0 <= ar <= 6.5 and w * h >= 2000:
                    out.append((x, y, w, h, w * h))
            out.sort(key=lambda t: t[4], reverse=True)
            return [(x, y, w, h) for x, y, w, h, _ in out[:5]]
        except Exception:
            return []

    def analyze_frame(self, pixels, image_size, image_pos=None, scale=None, mirror=False):
        if cv2 is None or np is None:
            self.result = "CV: OpenCV unavailable"
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
            boxes = self.find_plates(bgr)
            self.result = "CV: Plate region(s): %d" % len(boxes) if boxes else "CV: No cues"
        except Exception as exc:
            self.result = "CV: %s" % type(exc).__name__


SentinelPreview = None
if Preview is not None:
    class _SentinelPreview(Preview):
        _analytics = None

        def analyze_pixels_callback(self, pixels, image_size, image_pos, scale, mirror):
            if self._analytics:
                self._analytics.analyze_frame(pixels, image_size, image_pos, scale, mirror)

    SentinelPreview = _SentinelPreview


KV = """
<RootUI>:
    orientation: "vertical"
    padding: dp(8)
    spacing: dp(6)

    BoxLayout:
        size_hint_y: None
        height: dp(44)
        Label:
            text: "Sentinel-X -- Civic Enforcement"
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
                text: "Night/Fog CLAHE"
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
                text: "Your Name"
                halign: "left"
                valign: "middle"
                text_size: self.size
            TextInput:
                id: in_name
                multiline: False
                hint_text: "Name (optional)"

            Label:
                text: "Contact"
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
                hint_text: "e.g. MH12AB1234"

            Label:
                text: "Violation"
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
                text: root.section_penalty
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
                on_text: root.on_sign_group(self.text)

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
                hint_text: "What happened?"
                multiline: True
                size_hint_y: None
                height: dp(100)

            Label:
                text: "Routing"
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
            text: "Capture"
            on_release: root.capture_evidence()
        Button:
            text: "Send Report"
            on_release: root.send_report()
        Button:
            text: "Clear"
            on_release: root.clear_form()
"""


class RootUI(BoxLayout):
    status_text = StringProperty("GPS: -- | Speed: -- | G: --")
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
        self._analytics = AnalyticsEngine(self._dir())
        Clock.schedule_once(self._boot, 0)

    def _dir(self):
        try:
            return os.path.dirname(os.path.abspath(__file__))
        except Exception:
            return "."

    def _evidence_dir(self):
        base = App.get_running_app().user_data_dir if platform == "android" else self._dir()
        d = os.path.join(base, "evidence")
        os.makedirs(d, exist_ok=True)
        return d

    def _boot(self, _dt):
        vals = []
        for k, v in TrafficLawDB.OFFENSES.items():
            vals.append("%s -- %s" % (k, v["label"]))
        self.ids.sp_offense.values = vals
        self.ids.sp_sign_group.values = list(TrafficLawDB.SIGN_GROUPS.keys())
        self._request_perms()
        self._start_udp()
        self._start_service()
        Clock.schedule_interval(self._tick_geo, 1.0)
        Clock.schedule_interval(self._tick_cv, 0.5)

    def _request_perms(self):
        if platform != "android" or request_permissions is None:
            self._setup_camera()
            return

        def _cb(perms, results):
            Clock.schedule_once(lambda dt: self._setup_camera(), 0.3)

        try:
            request_permissions([
                Permission.CAMERA,
                Permission.ACCESS_FINE_LOCATION,
                Permission.ACCESS_COARSE_LOCATION,
                Permission.WRITE_EXTERNAL_STORAGE,
            ], _cb)
        except Exception:
            Clock.schedule_once(lambda dt: self._setup_camera(), 1.0)

    def _setup_camera(self):
        self.ids.camera_box.clear_widgets()
        if SentinelPreview is None:
            self.ids.camera_box.add_widget(Label(text="Camera unavailable\n(camera4kivy not loaded)"))
            return
        try:
            self._preview = SentinelPreview()
            self._preview._analytics = self._analytics
            self.ids.camera_box.add_widget(self._preview)
            Clock.schedule_once(lambda dt: self._connect_cam(), 0.5)
        except Exception:
            self.ids.camera_box.add_widget(Label(text="Camera init failed"))

    def _connect_cam(self):
        if not self._preview:
            return
        try:
            kw = {"enable_analyze_pixels": True, "analyze_pixels_resolution": 640}
            if platform == "android":
                kw["enable_video"] = False
            self._preview.connect_camera(**kw)
            self._cam_ok = True
        except Exception:
            try:
                self._preview.connect_camera()
                self._cam_ok = True
            except Exception:
                pass

    def _tick_cv(self, _dt):
        pass

    def on_offense_selected(self, text):
        k = (text.split("--")[0] or "").strip()
        if k in TrafficLawDB.OFFENSES:
            o = TrafficLawDB.OFFENSES[k]
            self.section_penalty = "%s\nPenalty: %s" % (o["section"], o["penalty"])
        else:
            self.section_penalty = DASH

    def on_sign_group(self, g):
        self.ids.sp_sign.values = TrafficLawDB.SIGN_GROUPS.get(g, [])
        self.ids.sp_sign.text = "Select Sign"

    def clear_form(self):
        for w in ("in_name", "in_contact", "in_plate", "in_notes"):
            self.ids[w].text = ""
        self.ids.sp_offense.text = "Select Violation"
        self.ids.sp_sign_group.text = "Select Sign Group"
        self.ids.sp_sign.text = "Select Sign"
        self.section_penalty = DASH
        self.route_text = DASH
        self.evidence_path = ""

    def capture_evidence(self):
        if not self._preview or not self._cam_ok:
            self._popup("Camera not ready", "Wait for camera to connect.")
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        p = os.path.join(self._evidence_dir(), "evidence_%s.jpg" % ts)
        try:
            if hasattr(self._preview, "capture_photo"):
                self._preview.capture_photo(p, self._after_capture)
            else:
                self._preview.export_to_png(p)
                self._after_capture(p)
        except Exception:
            self._popup("Capture failed", "Could not save image.")

    def _after_capture(self, path):
        try:
            p = str(path[0]) if isinstance(path, (tuple, list)) and path else str(path)
            if not os.path.isfile(p):
                self._popup("Error", "File not saved.")
                return
            if self.ids.sw_clahe.active and cv2:
                try:
                    img = cv2.imread(p)
                    if img is not None:
                        cv2.imwrite(p, AnalyticsEngine.clahe(img))
                except Exception:
                    pass
            self.evidence_path = p
            self._popup("Saved", os.path.basename(p))
        except Exception:
            self._popup("Error", "Capture callback failed.")

    def _tick_geo(self, _dt):
        lat = float(self.latest_lat)
        lon = float(self.latest_lon)
        self.district, self.state_name = JurisdictionEngine.geo_detail(lat, lon)
        plate = self.ids.in_plate.text.strip()
        rt = JurisdictionEngine.route(lat, lon, plate)
        rcpts = ", ".join(rt["all"]) or DASH
        lc = rt["lc"] or DASH
        pc = rt["pc"] or DASH
        self.route_text = "Loc: %s | Plate: %s\nTo: %s" % (lc, pc, rcpts)
        kmh = self.latest_speed * 3.6
        cv = self._analytics.result if self.ids.sw_cv.active else ""
        self.status_text = "GPS: %.5f,%.5f | %s,%s | %.1fkm/h | G:%.2f | %s" % (
            lat, lon, self.district, self.state_name, kmh, self.latest_g, cv
        )

    def send_report(self):
        if plyer_email is None:
            self._popup("Unavailable", "Email not available.")
            return
        plate = self.ids.in_plate.text.strip()
        if not plate:
            self._popup("Missing", "Enter plate number.")
            return
        okey = (self.ids.sp_offense.text.split("--")[0] or "").strip()
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
        reporter_name = self.ids.in_name.text.strip() or DASH
        reporter_contact = self.ids.in_contact.text.strip() or DASH
        reporter_label = "ANONYMOUS" if anon else reporter_name
        sign_group_text = self.ids.sp_sign_group.text
        sign_text = self.ids.sp_sign.text
        notes_text = self.ids.in_notes.text.strip() or DASH
        loc_code = rt["lc"] or DASH
        plate_code = rt["pc"] or DASH

        lines = [
            "SENTINEL-X -- CIVIC ENFORCEMENT REPORT",
            "Time: %s" % now,
            "",
            "GPS: %.6f, %.6f" % (lat, lon),
            "Location: %s, %s" % (self.district, self.state_name),
            "Speed: %.1f km/h" % (self.latest_speed * 3.6),
            "G_dyn: %.2f m/s2" % self.latest_g,
            "",
            "Plate: %s" % plate,
            "Offense: %s -- %s" % (okey, o["label"]),
            "Section: %s" % o["section"],
            "Penalty: %s" % o["penalty"],
            "",
            "Sign: %s / %s" % (sign_group_text, sign_text),
            "",
            "Reporter: %s" % reporter_label,
        ]
        if not anon:
            lines.append("Contact: %s" % reporter_contact)
        lines += [
            "",
            "Notes: %s" % notes_text,
            "",
            "Routing: Loc=%s Plate=%s" % (loc_code, plate_code),
            "",
            TrafficLawDB.GOOD_SAMARITAN_FOOTER,
        ]
        subj = "[Sentinel-X] %s -- %s" % (plate, o["label"])
        body = "\n".join(lines)
        att = self.evidence_path if self.evidence_path and os.path.isfile(self.evidence_path) else None
        try:
            try:
                plyer_email.send(recipients=rt["all"], subject=subj, text=body, attachment=att)
            except TypeError:
                kw = {"recipients": rt["all"], "subject": subj, "text": body}
                if att:
                    kw["file_path"] = att
                plyer_email.send(**kw)
            self._popup("Ready", "Email composer opened.")
        except Exception as e:
            self._popup("Failed", str(e))

    def _start_service(self):
        if platform != "android":
            return
        try:
            from android import AndroidService
            AndroidService("Sentinel-X", "Telemetry running").start("")
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
                Clock.schedule_once(lambda dt, a=la, b=lo, c=sp, d=gd: self._telem(a, b, c, d), 0)
            except socket.timeout:
                continue
            except Exception:
                continue

    def _telem(self, lat, lon, spd, g):
        self.latest_lat = lat
        self.latest_lon = lon
        self.latest_speed = spd
        self.latest_g = g

    def _popup(self, t, m):
        Popup(title=t, content=Label(text=m, halign="left", valign="top"), size_hint=(.9, .5)).open()


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


if __name__ == "__main__":
    SentinelXApp().run()
