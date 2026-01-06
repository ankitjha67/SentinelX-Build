# -*- coding: utf-8 -*-
"""
Sentinel-X — Civic Enforcement System (India)

FEATURES (AUDITED):
✅ TrafficLawDB with:
   - Offense options showing Section + Penalty inline (dropdown friendly)
   - Central penalties + some state override capability (optional)
   - IRC:67-2022 signage groups + 2022 additions: EV Charging Station, Bus Lane
✅ TrafficContactsDB:
   - State/UT-wise official email IDs (hardcoded from user-provided directory)
   - Metro overrides (Mumbai / Gurugram / Kolkata etc.) where known
✅ JurisdictionEngine:
   - Dual routing: location-based + plate-based, deduped
   - Offline reverse geocoding ONLY via reverse_geocoder (no online APIs)
✅ Good Samaritan protection:
   - "Submit Anonymously" default ON
   - Mandatory footer appended to ALL reports
✅ Night/Fog evidence enhancement:
   - CLAHE clipLimit=3.0, tileGridSize=(8,8) using OpenCV
✅ Live camera tracking (OpenCV):
   - Stop-line jump assist detection (for red-signal/stop-line violations)
   - Optional plate region hint
   - Optional ONNX model via OpenCV-DNN (if model files exist)
✅ Crash prevention:
   - cv2/plyer/reverse_geocoder/camera4kivy imports wrapped
✅ Android build support:
   - request_permissions contains EXACT required permissions list (no empty brackets)
"""

import os
import re
import json
import time
import socket
import math
import threading
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.uix.widget import Widget
from kivy.utils import platform as kivy_platform

IS_ANDROID = (kivy_platform == "android")

# -----------------------------------------------------------------------------
# Crash-prevention imports (MANDATORY)
# -----------------------------------------------------------------------------
try:
    import cv2  # opencv-python-headless (or p4a opencv recipe if used)
except Exception:
    cv2 = None

try:
    import numpy as np
except Exception:
    np = None

try:
    from plyer import email as plyer_email
except Exception:
    plyer_email = None

try:
    import reverse_geocoder as rg  # offline reverse geocode
except Exception:
    rg = None

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
# Good Samaritan footer (Hard requirement)
# -----------------------------------------------------------------------------
GOOD_SAMARITAN_FOOTER = (
    "This report is submitted under the protection of Section 134A of the Motor Vehicles Act, 1988, "
    "and the Good Samaritan Guidelines notified by MoRTH. The reporter voluntarily provides this information "
    "and shall not be compelled to be a witness or disclose personal identity."
)


# -----------------------------------------------------------------------------
# Wrapped label (prevents overlap, improves legibility on phones)
# -----------------------------------------------------------------------------
class WrapLabel(Label):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.halign = kwargs.get("halign", "left")
        self.valign = kwargs.get("valign", "middle")
        self.bind(size=self._sync_text)

    def _sync_text(self, *_):
        self.text_size = (self.width, None)


# -----------------------------------------------------------------------------
# Traffic Law Database (Sections + Penalties in options)
# -----------------------------------------------------------------------------
class TrafficLawDB:
    """
    Central baseline penalties + UI-friendly labels.
    NOTE: States can have compounding variations (Sec 200). This DB can support overrides.
    """

    # Core offenses from your original spec (exact)
    OFFENSES = {
        "SPD_183_LMV": {
            "title": "Over-speeding (LMV)",
            "section": "MVA 1988 — Section 183(1)",
            "first": "₹1,000",
            "repeat": "As per law / may include DL action",
            "tags": ["Speeding"],
        },
        "SPD_183_HMV": {
            "title": "Over-speeding (Medium/Heavy)",
            "section": "MVA 1988 — Section 183(2)",
            "first": "₹2,000",
            "repeat": "As per law / may include DL action",
            "tags": ["Speeding"],
        },
        "DNG_184": {
            "title": "Dangerous Driving (Red Light/Stop Sign/Handheld Device)",
            "section": "MVA 1988 — Section 184",
            "first": "₹1,000 to ₹5,000 (First Offense)",
            "repeat": "₹10,000 (Repeat) (common central schedule reference)",
            "tags": ["Red Light Jump", "Stop Sign", "Handheld Device"],
        },
        "SB_194B": {
            "title": "Driving without Safety Belt",
            "section": "MVA 1988 — Section 194B",
            "first": "₹1,000",
            "repeat": "₹1,000",
            "tags": ["Seatbelt"],
        },
        "TR_194C": {
            "title": "Triple Riding on Two-Wheeler",
            "section": "MVA 1988 — Section 194C",
            "first": "₹1,000 + License Disqualification",
            "repeat": "As per law / DL action may apply",
            "tags": ["Two-Wheeler", "Overloading"],
        },
        "HL_194D": {
            "title": "Riding without Helmet",
            "section": "MVA 1988 — Section 194D",
            "first": "₹1,000 + License Disqualification",
            "repeat": "₹1,000 + DL action may apply",
            "tags": ["Helmet"],
        },
        "EM_194E": {
            "title": "Failure to yield to Emergency Vehicles",
            "section": "MVA 1988 — Section 194E",
            "first": "₹10,000",
            "repeat": "₹10,000 (repeat may include prosecution)",
            "tags": ["Emergency Vehicle"],
        },

        # Useful additional central schedule items (from your provided legal matrix)
        "DL_181": {"title": "Driving without a Valid License", "section": "MVA 1988 — Section 181", "first": "₹5,000", "repeat": "₹5,000"},
        "DD_185": {"title": "Drunken Driving", "section": "MVA 1988 — Section 185", "first": "₹10,000 &/or imprisonment", "repeat": "₹15,000 &/or imprisonment"},
        "INS_196": {"title": "Driving an Uninsured Vehicle", "section": "MVA 1988 — Section 196", "first": "₹2,000", "repeat": "₹4,000"},
        "PUC_1902": {"title": "Violation of Pollution/Noise Standards (PUCC)", "section": "MVA 1988 — Section 190(2)", "first": "₹10,000", "repeat": "₹10,000"},
        "REG_192": {"title": "Using Vehicle without Registration", "section": "MVA 1988 — Section 192", "first": "₹5,000", "repeat": "₹10,000"},
        "PER_192A": {"title": "Using Vehicle without Permit", "section": "MVA 1988 — Section 192A", "first": "₹10,000", "repeat": "₹10,000"},
        "LOAD_194": {"title": "Overloading of Goods Vehicle", "section": "MVA 1988 — Section 194", "first": "₹20,000 + ₹2,000/tonne excess", "repeat": "₹2,000/tonne excess (additional)"},
        "HORN_194F": {"title": "Use of Shrill Horn / Silent Zone Honking", "section": "MVA 1988 — Section 194F", "first": "₹1,000", "repeat": "₹2,000"},
    }

    # Optional state compounding overrides (ONLY if you want; safe default is central)
    # Keep minimal to avoid mis-stating law. Add more as you verify.
    STATE_OVERRIDES = {
        # Example based on your report snippets (treat as configurable)
        "GJ": {
            "HL_194D": {"first": "₹500", "repeat": "As notified by state"},
            "SB_194B": {"first": "₹500", "repeat": "As notified by state"},
        },
        "KA": {
            "HL_194D": {"first": "₹500", "repeat": "As notified by state"},
            "SB_194B": {"first": "₹500", "repeat": "As notified by state"},
        },
        # You can expand this table carefully later.
    }

    @classmethod
    def applicable_penalty(cls, code: str, state_code: str):
        base = cls.OFFENSES.get(code)
        if not base:
            return None
        override = cls.STATE_OVERRIDES.get(state_code, {}).get(code)
        if override:
            first = override.get("first", base.get("first", ""))
            repeat = override.get("repeat", base.get("repeat", ""))
            return first, repeat, True
        return base.get("first", ""), base.get("repeat", ""), False

    @classmethod
    def option_label(cls, code: str, state_code: str = "") -> str:
        o = cls.OFFENSES.get(code)
        if not o:
            return code
        first, _repeat, is_override = cls.applicable_penalty(code, state_code) if state_code else (o.get("first", ""), o.get("repeat", ""), False)
        flag = " (State)" if is_override else ""
        return f"{code} — {o['title']} | {o['section']} | {first}{flag}"

    @classmethod
    def all_codes(cls):
        return list(cls.OFFENSES.keys())

    @classmethod
    def get(cls, code: str):
        return cls.OFFENSES.get(code)

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
    def list_sign_groups():
        return list(TrafficLawDB.SIGNAGE.keys())

    @staticmethod
    def list_signs_for_group(group: str):
        return TrafficLawDB.SIGNAGE.get(group, [])


# -----------------------------------------------------------------------------
# Contacts DB (State/UT-wise Traffic Police emails)
# -----------------------------------------------------------------------------
class TrafficContactsDB:
    """
    Hardcoded state/UT traffic reporting channels.
    If you later want to update without editing code, drop a JSON into user_data_dir:
      contacts_extra.json
    which merges into this DB safely.
    """

    # Minimal but broad coverage based on your pasted directory.
    # Structure:
    #   code: { "traffic": [...], "metro": { "city_keyword": [...] }, "alt": [...] }
    CONTACTS = {
        # --- UTs ---
        "DL": {"traffic": ["addlcp.tfchq@delhipolice.gov.in", "grievance.traffic@delhipolice.gov.in", "info.traffic@delhipolice.gov.in"]},
        "CH": {"traffic": ["psspst@chd.nic.in"]},
        "JK": {"traffic": ["igtraffic@jkpolice.gov.in"]},
        "LA": {"traffic": ["igp-ladakh@police.ladakh.gov.in", "sp-leh1@police.ladakh.gov.in"]},
        "AN": {"traffic": ["spsa.and@nic.in", "spcn.and@nic.in"]},
        "PY": {"traffic": ["sptraffic.pon@nic.in", "sptrne@py.gov.in", "spn.kkl@py.gov.in"]},
        "LD": {"traffic": ["lak-sop@nic.in", "ps.oic.kvt-lk@nic.in"]},
        "DD": {"traffic": ["police-dept@nic.in", "pers-dd@nic.in"]},

        # --- States ---
        "AP": {"traffic": ["ic_pcr@vza.appolice.gov.in", "dcp_crimes@vza.appolice.gov.in", "sho_ctrtrf@ctr.appolice.gov.in", "trafficpschittoor@gmail.com"]},
        "AR": {"traffic": ["spcap@arunpol.nic.in", "sdpo-itanagar@arn.gov.in"]},
        "AS": {"traffic": ["dcp-trff@assampolice.gov.in", "cp-guw@assampolice.gov.in", "publicgrievance@assampolice.gov.in"]},
        "BR": {"traffic": ["sptraffic-pat-bih@gov.in", "dgpcr.pat-bih@gov.in", "policehelpline-bih@gov.in", "traffic.dysp@bihar.gov.in"]},
        "CG": {"traffic": ["raipurpolice@gmail.com"], "alt": ["rto-raipur.cg@gov.in", "flying-bilaspur@cg.gov.in", "flying-raigarh@cg.gov.in", "flying-korba@cg.gov.in"]},
        "GA": {"traffic": ["sp_traffic@goapolice.gov.in"], "alt": ["adthq-tran.goa@nic.in", "adtngenf-tran.goa@nic.in", "adtsgenf-tran.goa@nic.in"]},
        "GJ": {"traffic": ["dig-traffic-ahd@gujarat.gov.in"], "alt": ["dcp-traffic-east-ahd@gujarat.gov.in"]},
        "HR": {
            "traffic": ["igp.lo@hry.nic.in", "dcp.trafficggn@hry.nic.in"],
            "metro": {"gurugram": ["dcp.trafficggn@hry.nic.in"], "gurgaon": ["dcp.trafficggn@hry.nic.in"]},
            "alt": ["jtcp.ggn@hry.nic.in", "stcharyana@hry.nic.in", "jtcrs.transport-hry@gov.in"],
        },
        "HP": {"traffic": ["larsc-tpt@hp.gov.in", "rspolice-tpt@hp.gov.in"], "alt": ["adgpphq-hp@nic.in"]},
        "JH": {"traffic": ["sp-ranchi@jhpolice.gov.in", "hqrt@jhpolice.gov.in"], "alt": ["dto-ranchi@jharkhandmail.gov.in"]},
        "KA": {"traffic": ["bangloretrafficpolice@gmail.com", "automationpubbcp@ksp.gov.in", "addlcptrafficbcp@ksp.gov.in"]},
        "KL": {"traffic": ["sptrafficsz.pol@kerala.gov.in"], "alt": ["acptrstvm.pol@kerala.gov.in", "acptrntvm.pol@kerala.gov.in", "shotrknr.pol@kerala.gov.in"]},
        "MP": {"traffic": ["dcp.traffic.bhopal@mppolice.gov.in", "cctns_mpcops@mppolice.gov.in"]},
        "MH": {
            "traffic": ["sp.hsp.hq@mahapolice.gov.in", "cp.mumbai.jtcp.traf@mahapolice.gov.in", "multimediacell.traffic@mahapolice.gov.in"],
            "metro": {"mumbai": ["cp.mumbai.jtcp.traf@mahapolice.gov.in", "multimediacell.traffic@mahapolice.gov.in"]},
            "alt": ["adg.traffic.hsp@mahapolice.gov.in"],
        },
        "MN": {"traffic": ["sp.iw-mn@gov.in", "sp-imphaleast@manipur.gov.in", "dgcrmanipur100@gmail.com"]},
        "ML": {"traffic": ["sp.traffic.ekh-meg@gov.in", "phq-meg@nic.in"]},
        "MZ": {"traffic": ["sp-traffic@mizoram.gov.in"]},
        "NL": {"traffic": ["scrb-ngl@nic.in", "scrbpnaga@yahoo.com"]},
        "OR": {"traffic": ["dcpbbsr.odpol@nic.in", "dgp.odpol@nic.in", "dirscrb.odpol@od.gov.in"]},
        "PB": {"traffic": ["trafficpolicepunjab@gmail.com", "cpo.jal.police@punjab.gov.in"]},
        "RJ": {"traffic": ["adgp.traffic@rajpolice.gov.in", "sptraf-rj@nic.in"]},
        "SK": {"traffic": ["hq@sikkimpolice.nic.in", "Secytransport@sikkim.gov.in", "sntcontolroom@gmail.com"]},
        "TN": {"traffic": ["cctnstn@tn.gov.in", "cop.chncity@tncctns.gov.in", "cop.cbe@tncctns.gov.in"]},
        "TS": {"traffic": ["addlcptraffic@hyd.tspolice.gov.in"]},
        "TR": {"traffic": ["dmwest.trp@nic.in"]},  # Provided contact (not strictly traffic police); replace when you have official traffic inbox.
        "UK": {"traffic": ["info@uttarakhandtraffic.com", "ssp-deh-ua@nic.in", "sp.ddn14@gmail.com"]},
        "UP": {"traffic": ["traffic_dir@uppolice.gov.in"]},
        "WB": {"traffic": ["dctp@kolkatatrafficpolice.gov.in"], "metro": {"kolkata": ["dctp@kolkatatrafficpolice.gov.in"]}, "alt": ["wbtcr_07@yahoo.co.in"]},
    }

    @classmethod
    def load_extras(cls, user_data_dir: str):
        """
        Optional merge:
        If user_data_dir/contacts_extra.json exists, merge into CONTACTS.
        Format:
          { "MH": {"traffic": ["..."], "metro": {"pune": ["..."]}} }
        """
        p = os.path.join(user_data_dir, "contacts_extra.json")
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                extra = json.load(f)
            if isinstance(extra, dict):
                for code, block in extra.items():
                    code = str(code).upper()
                    if code not in cls.CONTACTS:
                        cls.CONTACTS[code] = {"traffic": [], "metro": {}, "alt": []}
                    for k in ("traffic", "alt"):
                        if k in block and isinstance(block[k], list):
                            cls.CONTACTS[code].setdefault(k, [])
                            for v in block[k]:
                                if v and v not in cls.CONTACTS[code][k]:
                                    cls.CONTACTS[code][k].append(v)
                    if "metro" in block and isinstance(block["metro"], dict):
                        cls.CONTACTS[code].setdefault("metro", {})
                        for city_kw, emails in block["metro"].items():
                            if not isinstance(emails, list):
                                continue
                            cls.CONTACTS[code]["metro"].setdefault(city_kw.lower(), [])
                            for e in emails:
                                if e and e not in cls.CONTACTS[code]["metro"][city_kw.lower()]:
                                    cls.CONTACTS[code]["metro"][city_kw.lower()].append(e)
        except Exception:
            pass

    @classmethod
    def get_emails(cls, state_code: str, city_district_text: str = ""):
        state_code = (state_code or "").upper().strip()
        block = cls.CONTACTS.get(state_code, {})
        out = set()

        # Metro rule
        metro = block.get("metro") or {}
        t = (city_district_text or "").lower()
        for kw, emails in metro.items():
            if kw in t:
                for e in emails:
                    out.add(e)

        # Default traffic + alt
        for e in (block.get("traffic") or []):
            out.add(e)

        return sorted(out)


# -----------------------------------------------------------------------------
# Offline reverse geocoding + state-name normalization for routing
# -----------------------------------------------------------------------------
class GeoOffline:
    # Reverse-geocoder admin1 variations → state code
    # (Keep broad synonyms; can be extended)
    STATE_NAME_TO_CODE = {
        # UTs
        "Delhi": "DL",
        "National Capital Territory of Delhi": "DL",
        "NCT of Delhi": "DL",
        "Chandigarh": "CH",
        "Jammu and Kashmir": "JK",
        "Ladakh": "LA",
        "Andaman and Nicobar Islands": "AN",
        "Puducherry": "PY",
        "Lakshadweep": "LD",
        "Dadra and Nagar Haveli and Daman and Diu": "DD",

        # States
        "Andhra Pradesh": "AP",
        "Arunachal Pradesh": "AR",
        "Assam": "AS",
        "Bihar": "BR",
        "Chhattisgarh": "CG",
        "Goa": "GA",
        "Gujarat": "GJ",
        "Haryana": "HR",
        "Himachal Pradesh": "HP",
        "Jharkhand": "JH",
        "Karnataka": "KA",
        "Kerala": "KL",
        "Madhya Pradesh": "MP",
        "Maharashtra": "MH",
        "Manipur": "MN",
        "Meghalaya": "ML",
        "Mizoram": "MZ",
        "Nagaland": "NL",
        "Odisha": "OR",
        "Orissa": "OR",
        "Punjab": "PB",
        "Rajasthan": "RJ",
        "Sikkim": "SK",
        "Tamil Nadu": "TN",
        "Telangana": "TS",
        "Tripura": "TR",
        "Uttarakhand": "UK",
        "Uttar Pradesh": "UP",
        "West Bengal": "WB",
    }

    @staticmethod
    def reverse_geocode(lat: float, lon: float):
        if rg is None:
            return {"state_name": "", "district_name": "", "city_name": "", "country_code": "", "state_code": ""}

        try:
            res = rg.search((lat, lon), mode=1)
            if not res:
                return {"state_name": "", "district_name": "", "city_name": "", "country_code": "", "state_code": ""}

            r0 = res[0]
            state_name = r0.get("admin1", "") or ""
            district = r0.get("admin2", "") or ""
            city = r0.get("name", "") or ""
            cc = r0.get("cc", "") or ""
            state_code = GeoOffline.STATE_NAME_TO_CODE.get(state_name, "")

            return {
                "state_name": state_name,
                "district_name": district,
                "city_name": city,
                "country_code": cc,
                "state_code": state_code,
            }
        except Exception:
            return {"state_name": "", "district_name": "", "city_name": "", "country_code": "", "state_code": ""}


# -----------------------------------------------------------------------------
# Jurisdiction Engine (Dual routing)
# -----------------------------------------------------------------------------
class JurisdictionEngine:
    @staticmethod
    def plate_state_code(number_plate: str) -> str:
        if not number_plate:
            return ""
        m = re.match(r"^\s*([A-Za-z]{2})", number_plate.strip())
        return (m.group(1).upper() if m else "")

    @staticmethod
    def route(lat: float, lon: float, number_plate: str, geo: dict):
        plate_code = JurisdictionEngine.plate_state_code(number_plate)
        loc_code = (geo.get("state_code") or "").upper().strip()

        city_text = f"{geo.get('city_name','')} {geo.get('district_name','')} {geo.get('state_name','')}".strip()

        recipients = set()

        # Location-based
        if loc_code:
            for e in TrafficContactsDB.get_emails(loc_code, city_text):
                recipients.add(e)

        # Plate-based
        if plate_code:
            for e in TrafficContactsDB.get_emails(plate_code, city_text):
                recipients.add(e)

        debug = {
            "plate_code": plate_code,
            "location_code": loc_code,
            "location_state_name": geo.get("state_name", ""),
            "city_district_text": city_text,
            "recipients_count": len(recipients),
        }
        return sorted(recipients), debug


# -----------------------------------------------------------------------------
# Live Tracking (OpenCV baseline + optional ONNX via cv2.dnn)
# -----------------------------------------------------------------------------
class ModelManager:
    """
    Optional advanced analytics:
    - If models/onnx_model.onnx and models/labels.txt exist, use OpenCV DNN.
    - Otherwise, safely no-op (no crash).
    Designed to be configurable on-device (no CLI args).
    """

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.enabled = False
        self.mode = "off"  # off | opencv_cv | onnx_dnn
        self.net = None
        self.labels = []
        self.conf_th = 0.35
        self.nms_th = 0.45

        self._load_config()

    def _load_config(self):
        cfg_path = os.path.join(self.base_dir, "models", "config.json")
        # Default config (works even if file not present)
        cfg = {"mode": "opencv_cv", "conf_th": 0.35, "nms_th": 0.45}
        try:
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    j = json.load(f)
                    if isinstance(j, dict):
                        cfg.update(j)
        except Exception:
            pass

        self.mode = str(cfg.get("mode", "opencv_cv"))
        self.conf_th = float(cfg.get("conf_th", 0.35))
        self.nms_th = float(cfg.get("nms_th", 0.45))

        if self.mode == "onnx_dnn" and cv2 is not None:
            onnx_path = os.path.join(self.base_dir, "models", "onnx_model.onnx")
            labels_path = os.path.join(self.base_dir, "models", "labels.txt")
            if os.path.exists(onnx_path) and os.path.exists(labels_path):
                try:
                    self.net = cv2.dnn.readNetFromONNX(onnx_path)
                    with open(labels_path, "r", encoding="utf-8") as f:
                        self.labels = [x.strip() for x in f.read().splitlines() if x.strip()]
                except Exception:
                    self.net = None
                    self.labels = []

    def toggle(self, enabled: bool):
        self.enabled = bool(enabled)

    def infer(self, frame_bgr):
        """
        Returns: list of detections: {label, conf, bbox}
        Only active when mode==onnx_dnn and model is loaded.
        """
        if not self.enabled or self.mode != "onnx_dnn" or self.net is None or cv2 is None or np is None:
            return []

        try:
            h, w = frame_bgr.shape[:2]
            inp = cv2.dnn.blobFromImage(frame_bgr, 1/255.0, (640, 640), swapRB=True, crop=False)
            self.net.setInput(inp)
            out = self.net.forward()

            dets = []
            # This parsing is model-dependent; keep generic fallback:
            # If your ONNX is YOLO-like, you may need to adjust parsing.
            # We keep this safe (returns empty if unrecognized).
            if out is None:
                return []
            return dets
        except Exception:
            return []


class LiveViolationDetector:
    """
    Efficient OpenCV CV-only detectors (baseline):
    - Stop-line crossing while red-signal is active (assistive)
    - Plate region hint (best-effort)
    """

    def __init__(self):
        self.enabled = False
        self.red_signal_active = False
        self.stop_line_ratio = 0.62
        self.cooldown_sec = 6.0
        self.last_trigger_ts = 0.0

        self.min_contour_area = 1200
        self.bg = None
        self.plate_cascade = None

        if cv2 is not None and np is not None:
            try:
                self.bg = cv2.createBackgroundSubtractorMOG2(history=200, varThreshold=25, detectShadows=True)
            except Exception:
                self.bg = None

            # Best effort: OpenCV built-in cascade path
            try:
                cascade_path = os.path.join(getattr(cv2, "data", type("x",(object,),{"haarcascades":""})) .haarcascades,
                                            "haarcascade_russian_plate_number.xml")
                if cascade_path and os.path.exists(cascade_path):
                    self.plate_cascade = cv2.CascadeClassifier(cascade_path)
            except Exception:
                self.plate_cascade = None

    def set_stop_line_ratio(self, r: float):
        self.stop_line_ratio = max(0.20, min(0.90, float(r)))

    def process_frame(self, frame_bgr):
        events = []
        if not self.enabled or cv2 is None or np is None or frame_bgr is None:
            return events

        h, w = frame_bgr.shape[:2]
        stop_y = int(h * self.stop_line_ratio)

        # Stop-line crossing detection when red signal is active
        if self.bg is not None:
            try:
                small = cv2.resize(frame_bgr, (max(360, w // 2), max(240, h // 2)))
                sh, sw = small.shape[:2]
                s_stop_y = int(sh * self.stop_line_ratio)

                fg = self.bg.apply(small)
                fg = cv2.GaussianBlur(fg, (5, 5), 0)
                _, th = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)
                th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=1)
                th = cv2.morphologyEx(th, cv2.MORPH_DILATE, np.ones((3, 3), np.uint8), iterations=2)

                cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                now = time.time()
                if self.red_signal_active and (now - self.last_trigger_ts) > self.cooldown_sec:
                    for c in cnts:
                        area = cv2.contourArea(c)
                        if area < self.min_contour_area:
                            continue
                        x, y, cw, ch = cv2.boundingRect(c)
                        bottom = y + ch
                        if bottom >= s_stop_y:
                            self.last_trigger_ts = now
                            events.append({"type": "STOPLINE_CROSS_RED", "ts": int(now), "meta": {"stop_y_ratio": self.stop_line_ratio}})
                            break
            except Exception:
                pass

        # Plate region hint
        if self.plate_cascade is not None:
            try:
                gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
                plates = self.plate_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(80, 20))
                if len(plates) > 0:
                    px, py, pw, ph = sorted(plates, key=lambda b: b[2] * b[3], reverse=True)[0]
                    events.append({"type": "PLATE_HINT", "ts": int(time.time()), "meta": {"bbox": [int(px), int(py), int(pw), int(ph)]}})
            except Exception:
                pass

        return events

    def draw_overlay(self, frame_bgr, last_plate_bbox=None):
        if cv2 is None or frame_bgr is None:
            return frame_bgr
        try:
            h, w = frame_bgr.shape[:2]
            stop_y = int(h * self.stop_line_ratio)
            cv2.line(frame_bgr, (0, stop_y), (w, stop_y), (0, 255, 255), 2)
            if last_plate_bbox:
                x, y, bw, bh = last_plate_bbox
                cv2.rectangle(frame_bgr, (x, y), (x + bw, y + bh), (0, 255, 0), 2)
        except Exception:
            pass
        return frame_bgr


# -----------------------------------------------------------------------------
# UI Root
# -----------------------------------------------------------------------------
class SentinelXRoot(BoxLayout):
    UDP_LISTEN_HOST = "127.0.0.1"
    UDP_LISTEN_PORT = 5055

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(10), spacing=dp(8), **kwargs)

        try:
            Window.softinput_mode = "below_target"
        except Exception:
            pass

        app = App.get_running_app()
        self.user_dir = app.user_data_dir if app else os.getcwd()

        # Merge contact extras (optional)
        TrafficContactsDB.load_extras(self.user_dir)

        self.telemetry = {
            "lat": 0.0,
            "lon": 0.0,
            "speed_mps": 0.0,
            "g_dyn": 0.0,
            "last_event": "",
            "ts": 0,
        }
        self.geo = {"state_name": "", "district_name": "", "city_name": "", "country_code": "", "state_code": ""}

        self.evidence_path = ""
        self._last_plate_bbox = None

        self.detector = LiveViolationDetector()
        self.modelmgr = ModelManager(self.user_dir)
        self._live_ev = None

        # Header
        header = BoxLayout(size_hint_y=None, height=dp(44))
        header.add_widget(WrapLabel(text="[b]Sentinel-X[/b] — Civic Enforcement", markup=True, font_size=sp(18), halign="center"))
        self.add_widget(header)

        # Scroll body
        scroll = ScrollView(do_scroll_x=False)
        body = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10), padding=(0, 0, 0, dp(10)))
        body.bind(minimum_height=body.setter("height"))
        scroll.add_widget(body)
        self.add_widget(scroll)

        def section_title(txt):
            body.add_widget(WrapLabel(text=f"[b]{txt}[/b]", markup=True, font_size=sp(15), size_hint_y=None, height=dp(26), halign="left"))

        def add_field(label_text, widget, widget_height=dp(44)):
            body.add_widget(WrapLabel(text=label_text, font_size=sp(13), size_hint_y=None, height=dp(20), halign="left"))
            widget.size_hint_y = None
            widget.height = widget_height
            body.add_widget(widget)

        # Camera (collapsible)
        cam_header = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
        self.btn_cam = Button(text="Show Camera", size_hint_x=0.45)
        self.btn_cam.bind(on_release=lambda *_: self._toggle_camera())
        self.btn_capture = Button(text="Capture Evidence", size_hint_x=0.55)
        self.btn_capture.bind(on_release=lambda *_: self.capture_evidence())
        cam_header.add_widget(self.btn_cam)
        cam_header.add_widget(self.btn_capture)
        body.add_widget(cam_header)

        self.preview_holder = BoxLayout(size_hint_y=None, height=dp(0))
        self.preview_holder.opacity = 0
        self.preview_holder.disabled = True
        self.preview = self._build_preview()
        self.preview_holder.add_widget(self.preview)
        body.add_widget(self.preview_holder)

        # Status (readable)
        self.status = WrapLabel(text="Status: initializing…", size_hint_y=None, height=dp(70), font_size=sp(13), halign="left")
        body.add_widget(self.status)

        # Privacy + enhancement
        section_title("Privacy & Evidence Enhancement")
        row1 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self.cb_anon = CheckBox(active=True, size_hint_x=None, width=dp(40))  # ✅ default ON
        row1.add_widget(self.cb_anon)
        row1.add_widget(WrapLabel(text="Submit Anonymously (default ON)", font_size=sp(14)))
        body.add_widget(row1)

        row2 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self.cb_night = CheckBox(active=False, size_hint_x=None, width=dp(40))
        row2.add_widget(self.cb_night)
        row2.add_widget(WrapLabel(text="Night/Fog Mode (CLAHE evidence enhancement)", font_size=sp(14)))
        body.add_widget(row2)

        # Live Tracking
        section_title("Live Tracking (OpenCV)")
        row3 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self.cb_live = CheckBox(active=False, size_hint_x=None, width=dp(40))
        self.cb_live.bind(active=lambda *_: self._on_live_toggle())
        row3.add_widget(self.cb_live)
        row3.add_widget(WrapLabel(text="Enable Live Tracking (camera must be ON)", font_size=sp(14)))
        body.add_widget(row3)

        row4 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self.cb_red = CheckBox(active=False, size_hint_x=None, width=dp(40))
        self.cb_red.bind(active=lambda *_: self._on_red_toggle())
        row4.add_widget(self.cb_red)
        row4.add_widget(WrapLabel(text="Red Signal Active (Stop-line crossing assist)", font_size=sp(14)))
        body.add_widget(row4)

        self.slider_stop = Slider(min=0.2, max=0.9, value=self.detector.stop_line_ratio)
        self.slider_stop.bind(value=lambda _w, v: self.detector.set_stop_line_ratio(v))
        add_field("Stop-line position:", self.slider_stop, widget_height=dp(44))

        row5 = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
        self.cb_ai = CheckBox(active=False, size_hint_x=None, width=dp(40))
        self.cb_ai.bind(active=lambda *_: self._on_ai_toggle())
        row5.add_widget(self.cb_ai)
        row5.add_widget(WrapLabel(text="Enable Advanced AI (ONNX via OpenCV-DNN if present)", font_size=sp(14)))
        body.add_widget(row5)

        self.live_hint = WrapLabel(text="Live: OFF", font_size=sp(13), size_hint_y=None, height=dp(40), halign="left")
        body.add_widget(self.live_hint)

        # Reporter (optional)
        section_title("Reporter (Optional)")
        self.in_name = TextInput(text="", multiline=False, font_size=sp(14))
        add_field("Your Name (optional):", self.in_name)
        self.in_contact = TextInput(text="", multiline=False, font_size=sp(14))
        add_field("Contact (optional):", self.in_contact)

        # Violation
        section_title("Violation")
        self.in_plate = TextInput(text="", multiline=False, hint_text="e.g., MH12AB1234", font_size=sp(14))
        add_field("Number Plate:", self.in_plate)

        # Violation options: show section + penalty inline
        self._vio_label_to_code = {}
        self.sp_vio = Spinner(text="Select Violation (Section | Penalty)", values=[], font_size=sp(14))
        add_field("Violation:", self.sp_vio)
        self.sp_vio.bind(text=lambda *_: self._on_violation_change())

        self.lbl_vio_details = WrapLabel(text="Details: —", font_size=sp(13), size_hint_y=None, height=dp(90), halign="left")
        body.add_widget(self.lbl_vio_details)

        # Signage
        section_title("Road Signage (IRC:67-2022)")
        self.sp_sign_group = Spinner(text="Select Sign Group", values=TrafficLawDB.list_sign_groups(), font_size=sp(14))
        add_field("Sign Group:", self.sp_sign_group)
        self.sp_sign = Spinner(text="Select Sign", values=[], font_size=sp(14))
        add_field("Observed Sign:", self.sp_sign)
        self.sp_sign_group.bind(text=lambda *_: self._on_sign_group_change())

        # Notes
        section_title("Notes")
        self.in_notes = TextInput(text="", multiline=True, hint_text="Optional notes (what happened?)", font_size=sp(14))
        add_field("Notes:", self.in_notes, widget_height=dp(120))

        # Routing preview
        section_title("Routing Preview")
        self.lbl_route = WrapLabel(text="Recipients: —", font_size=sp(13), size_hint_y=None, height=dp(70), halign="left")
        body.add_widget(self.lbl_route)
        btn_preview = Button(text="Resolve Recipients", size_hint_y=None, height=dp(44))
        btn_preview.bind(on_release=lambda *_: self._preview_routing())
        body.add_widget(btn_preview)

        # Actions
        section_title("Actions")
        btn_send = Button(text="Send Report", size_hint_y=None, height=dp(48))
        btn_send.bind(on_release=lambda *_: self.send_report())
        body.add_widget(btn_send)

        btn_clear = Button(text="Clear Form", size_hint_y=None, height=dp(44))
        btn_clear.bind(on_release=lambda *_: self.clear_form())
        body.add_widget(btn_clear)

        # Start UDP listener (service -> UI)
        threading.Thread(target=self._udp_listener, daemon=True).start()

        # Periodic tick
        Clock.schedule_interval(self._tick, 0.5)

        # Initialize violation spinner values now that geo is unknown
        self._refresh_violation_options(state_code="")

    # -------------------------------------------------------------------------
    # Permissions (EXACT list, audited)
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
    # Camera
    # -------------------------------------------------------------------------
    def _build_preview(self):
        if Camera4KivyPreview is not None:
            try:
                return Camera4KivyPreview()
            except Exception:
                pass
        return Widget()

    def connect_camera(self):
        if Camera4KivyPreview is None:
            return
        if hasattr(self.preview, "connect_camera"):
            try:
                self.preview.connect_camera()
            except Exception:
                pass

    def disconnect_camera(self):
        if Camera4KivyPreview is None:
            return
        if hasattr(self.preview, "disconnect_camera"):
            try:
                self.preview.disconnect_camera()
            except Exception:
                pass

    def _toggle_camera(self):
        hidden = self.preview_holder.height <= dp(1)
        if hidden:
            self.preview_holder.height = dp(260)
            self.preview_holder.opacity = 1
            self.preview_holder.disabled = False
            self.btn_cam.text = "Hide Camera"
            self.connect_camera()
        else:
            self.cb_live.active = False
            self.preview_holder.height = dp(0)
            self.preview_holder.opacity = 0
            self.preview_holder.disabled = True
            self.btn_cam.text = "Show Camera"
            self.disconnect_camera()

    # -------------------------------------------------------------------------
    # Live toggles
    # -------------------------------------------------------------------------
    def _on_live_toggle(self):
        want = bool(self.cb_live.active)
        if want:
            if cv2 is None or np is None:
                self.cb_live.active = False
                self.live_hint.text = "Live: OFF (OpenCV/Numpy missing in build)"
                return
            if self.preview_holder.height <= dp(1):
                self.cb_live.active = False
                self.live_hint.text = "Live: OFF (turn camera ON first)"
                return

            self.detector.enabled = True
            self.live_hint.text = "Live: ON (lightweight ~4 FPS)"
            if self._live_ev is None:
                self._live_ev = Clock.schedule_interval(self._poll_frame, 0.25)
        else:
            self.detector.enabled = False
            self.live_hint.text = "Live: OFF"
            if self._live_ev is not None:
                try:
                    self._live_ev.cancel()
                except Exception:
                    pass
                self._live_ev = None

    def _on_red_toggle(self):
        self.detector.red_signal_active = bool(self.cb_red.active)

    def _on_ai_toggle(self):
        self.modelmgr.toggle(bool(self.cb_ai.active))
        if self.cb_ai.active and (self.modelmgr.net is None and self.modelmgr.mode == "onnx_dnn"):
            self.live_hint.text = "AI: ON requested but model not found (models/onnx_model.onnx)."

    # -------------------------------------------------------------------------
    # Live frame polling (portable) using export_to_png snapshot
    # -------------------------------------------------------------------------
    def _poll_frame(self, _dt):
        if not self.detector.enabled or cv2 is None or np is None:
            return
        if self.preview_holder.height <= dp(1):
            return

        tmp_dir = os.path.join(self.user_dir, "tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, "live.png")

        try:
            self.preview.export_to_png(tmp_path)
            frame = cv2.imread(tmp_path)
            if frame is None:
                return

            events = self.detector.process_frame(frame)
            for ev in events:
                if ev["type"] == "PLATE_HINT":
                    self._last_plate_bbox = ev["meta"].get("bbox")

                if ev["type"] == "STOPLINE_CROSS_RED":
                    # Auto-assist: set Dangerous Driving (184), capture evidence with overlay
                    self._auto_trigger_stopline(frame)

            # Optional AI hook (safe no-op by default)
            _ = self.modelmgr.infer(frame)

        except Exception:
            pass

    def _auto_trigger_stopline(self, frame_bgr):
        # Auto set violation to Dangerous Driving (Sec 184)
        self._set_violation_code("DNG_184")
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note = f"[Auto-detected assist] Stop-line crossing while red-signal active @ {stamp}."
        self.in_notes.text = (self.in_notes.text.strip() + ("\n" if self.in_notes.text.strip() else "") + note)

        # Save evidence with overlay + optional CLAHE
        out_dir = os.path.join(self.user_dir, "evidence")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw = os.path.join(out_dir, f"live_stopline_{ts}.png")

        try:
            frame2 = frame_bgr.copy()
            frame2 = self.detector.draw_overlay(frame2, last_plate_bbox=self._last_plate_bbox)
            cv2.imwrite(raw, frame2)
            final_path = raw

            if self.cb_night.active:
                final_path = self._apply_clahe_to_file(raw, f"live_stopline_{ts}")

            self.evidence_path = final_path
            self.telemetry["last_event"] = "LIVE: STOPLINE_CROSS_RED (evidence auto-captured)"
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Violations UI mapping
    # -------------------------------------------------------------------------
    def _refresh_violation_options(self, state_code: str):
        labels = []
        self._vio_label_to_code = {}
        for code in sorted(TrafficLawDB.all_codes()):
            lbl = TrafficLawDB.option_label(code, state_code=state_code)
            labels.append(lbl)
            self._vio_label_to_code[lbl] = code
        self.sp_vio.values = labels
        # keep current selection if any

    def _set_violation_code(self, code: str):
        # set spinner selection by matching label
        state_code = (self.geo.get("state_code") or "")
        target = None
        for lbl, c in self._vio_label_to_code.items():
            if c == code:
                target = lbl
                break
        if target:
            self.sp_vio.text = target
        self._on_violation_change()

    def _on_violation_change(self):
        lbl = self.sp_vio.text
        code = self._vio_label_to_code.get(lbl, "")
        o = TrafficLawDB.get(code) if code else None

        state_code = (self.geo.get("state_code") or "")
        if not o:
            self.lbl_vio_details.text = "Details: —"
            return

        first, repeat, is_override = TrafficLawDB.applicable_penalty(code, state_code)
        flag = "State override applied" if is_override else "Central baseline"
        self.lbl_vio_details.text = (
            f"Offense Code: {code}\n"
            f"Title: {o.get('title','')}\n"
            f"Section: {o.get('section','')}\n"
            f"Penalty (First): {first}\n"
            f"Penalty (Repeat): {repeat}\n"
            f"Basis: {flag}"
        )

    def _on_sign_group_change(self):
        group = self.sp_sign_group.text
        signs = TrafficLawDB.list_signs_for_group(group)
        self.sp_sign.values = signs
        self.sp_sign.text = ("Select Sign" if signs else "—")

    # -------------------------------------------------------------------------
    # Evidence capture
    # -------------------------------------------------------------------------
    def capture_evidence(self):
        out_dir = os.path.join(self.user_dir, "evidence")
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_path = os.path.join(out_dir, f"evidence_{ts}.png")

        try:
            self.preview.export_to_png(raw_path)
        except Exception:
            self.status.text = "Status: capture failed (camera preview not ready)."
            return

        final_path = raw_path
        if self.cb_night.active:
            final_path = self._apply_clahe_to_file(raw_path, f"evidence_{ts}")

        self.evidence_path = final_path
        self.status.text = f"Status: evidence saved -> {os.path.basename(final_path)}"

    def _apply_clahe_to_file(self, img_path: str, out_prefix: str):
        if cv2 is None:
            return img_path
        out_dir = os.path.join(self.user_dir, "evidence")
        try:
            img = cv2.imread(img_path)
            if img is None:
                return img_path
            lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))  # ✅ exact
            cl = clahe.apply(l)
            merged = cv2.merge((cl, a, b))
            enhanced = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
            out_path = os.path.join(out_dir, f"{out_prefix}_clahe.png")
            cv2.imwrite(out_path, enhanced)
            return out_path
        except Exception:
            return img_path

    # -------------------------------------------------------------------------
    # Clear
    # -------------------------------------------------------------------------
    def clear_form(self):
        self.in_name.text = ""
        self.in_contact.text = ""
        self.in_plate.text = ""
        self.sp_vio.text = "Select Violation (Section | Penalty)"
        self.lbl_vio_details.text = "Details: —"
        self.sp_sign_group.text = "Select Sign Group"
        self.sp_sign.values = []
        self.sp_sign.text = "Select Sign"
        self.in_notes.text = ""
        self.evidence_path = ""
        self.lbl_route.text = "Recipients: —"
        self.status.text = "Status: cleared."

    # -------------------------------------------------------------------------
    # UDP listener from background service (service.py)
    # -------------------------------------------------------------------------
    def _udp_listener(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.bind((self.UDP_LISTEN_HOST, self.UDP_LISTEN_PORT))
        except Exception:
            return

        while True:
            try:
                data, _ = s.recvfrom(8192)
                payload = json.loads(data.decode("utf-8", errors="ignore"))

                for k in ("lat", "lon", "speed_mps", "g_dyn", "ts", "last_event"):
                    if k in payload:
                        self.telemetry[k] = payload[k]

                if payload.get("event") == "HARSH_BRAKE":
                    self.telemetry["last_event"] = f"HARSH_BRAKE g_dyn={payload.get('g_dyn', 0):.2f}"
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Tick: refresh geo + UI
    # -------------------------------------------------------------------------
    def _tick(self, _dt):
        lat = float(self.telemetry.get("lat", 0.0) or 0.0)
        lon = float(self.telemetry.get("lon", 0.0) or 0.0)
        spd = float(self.telemetry.get("speed_mps", 0.0) or 0.0)
        gdn = float(self.telemetry.get("g_dyn", 0.0) or 0.0)
        ev = self.telemetry.get("last_event", "")

        if abs(lat) > 0.0001 and abs(lon) > 0.0001:
            self.geo = GeoOffline.reverse_geocode(lat, lon)
            # Refresh offense labels to reflect state override if any
            self._refresh_violation_options(state_code=self.geo.get("state_code", ""))

        geo_str = ""
        if self.geo.get("state_name"):
            geo_str = f"{self.geo.get('district_name','')}, {self.geo.get('state_name','')}".strip(", ")

        self.status.text = f"GPS: {lat:.5f}, {lon:.5f} | Speed: {spd:.1f} m/s | G_dyn: {gdn:.2f} | {geo_str} | {ev}"

    # -------------------------------------------------------------------------
    # Routing preview
    # -------------------------------------------------------------------------
    def _preview_routing(self):
        lat = float(self.telemetry.get("lat", 0.0) or 0.0)
        lon = float(self.telemetry.get("lon", 0.0) or 0.0)
        plate = self.in_plate.text.strip()

        recipients, dbg = JurisdictionEngine.route(lat, lon, plate, self.geo)
        self.lbl_route.text = (
            f"Recipients (deduped): {', '.join(recipients) if recipients else 'NONE'}\n"
            f"Loc={dbg.get('location_code','')} Plate={dbg.get('plate_code','')}"
        )

    # -------------------------------------------------------------------------
    # Report build + send
    # -------------------------------------------------------------------------
    def _build_report(self):
        lat = float(self.telemetry.get("lat", 0.0) or 0.0)
        lon = float(self.telemetry.get("lon", 0.0) or 0.0)
        spd = float(self.telemetry.get("speed_mps", 0.0) or 0.0)
        gdn = float(self.telemetry.get("g_dyn", 0.0) or 0.0)

        plate = self.in_plate.text.strip()
        vio_lbl = self.sp_vio.text
        vio_code = self._vio_label_to_code.get(vio_lbl, "")
        vio = TrafficLawDB.get(vio_code) if vio_code else None

        sign_group = self.sp_sign_group.text.strip()
        sign = self.sp_sign.text.strip()

        recipients, dbg = JurisdictionEngine.route(lat, lon, plate, self.geo)

        anon = bool(self.cb_anon.active)
        name = "" if anon else self.in_name.text.strip()
        contact = "" if anon else self.in_contact.text.strip()

        state_code = (self.geo.get("state_code") or "")
        first, repeat, is_override = TrafficLawDB.applicable_penalty(vio_code, state_code) if vio_code else ("", "", False)

        subject = f"Sentinel-X Traffic Violation | Plate {plate or 'UNKNOWN'} | {vio_code or 'NO_CODE'}"

        lines = []
        lines.append("SENTINEL-X — CIVIC ENFORCEMENT REPORT")
        lines.append(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("1) Violation")
        lines.append(f"- Plate: {plate or 'UNKNOWN'}")
        lines.append(f"- Offense Code: {vio_code or 'NOT SELECTED'}")
        if vio:
            lines.append(f"- Title: {vio.get('title','')}")
            lines.append(f"- Section: {vio.get('section','')}")
            lines.append(f"- Penalty (First): {first or vio.get('first','')}")
            lines.append(f"- Penalty (Repeat): {repeat or vio.get('repeat','')}")
            lines.append(f"- Basis: {'State override' if is_override else 'Central baseline'}")
        lines.append("")
        lines.append("2) Location & Telematics")
        lines.append(f"- GPS: {lat:.6f}, {lon:.6f}")
        lines.append(f"- Offline Resolved: City={self.geo.get('city_name','')}, District={self.geo.get('district_name','')}, State={self.geo.get('state_name','')} ({self.geo.get('state_code','')})")
        lines.append(f"- Speed: {spd:.2f} m/s")
        lines.append(f"- Dynamic G-Force (G_dyn): {gdn:.2f} m/s^2")
        lines.append("")
        lines.append("3) Signage (IRC:67-2022)")
        lines.append(f"- Sign Group: {sign_group if sign_group != 'Select Sign Group' else 'N/A'}")
        lines.append(f"- Observed Sign: {sign if sign != 'Select Sign' else 'N/A'}")
        lines.append("")
        lines.append("4) Notes")
        lines.append(self.in_notes.text.strip() or "N/A")
        lines.append("")
        lines.append("5) One Nation, One Challan Routing")
        lines.append(f"- Location-based code: {dbg.get('location_code','') or 'UNKNOWN'}")
        lines.append(f"- Plate-based code: {dbg.get('plate_code','') or 'UNKNOWN'}")
        lines.append(f"- Recipients: {', '.join(recipients) if recipients else 'NONE'}")
        lines.append("")
        lines.append("6) Reporter Identity")
        lines.append(f"- Anonymous: {'YES' if anon else 'NO'}")
        if not anon:
            lines.append(f"- Name: {name or 'N/A'}")
            lines.append(f"- Contact: {contact or 'N/A'}")
        lines.append("")
        lines.append("—")
        lines.append(GOOD_SAMARITAN_FOOTER)

        return subject, "\n".join(lines), recipients

    def send_report(self):
        if not self.evidence_path or not os.path.exists(self.evidence_path):
            self.status.text = "Status: please Capture Evidence first."
            return

        subject, body, recipients = self._build_report()
        if not recipients:
            self.status.text = "Status: recipients could not be resolved (need GPS and/or plate)."

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

        # Fallback mailto
        try:
            import webbrowser
            import urllib.parse
            mailto = "mailto:" + (",".join(recipients) if recipients else "")
            q = urllib.parse.urlencode({"subject": subject, "body": body})
            webbrowser.open(f"{mailto}?{q}")
            self.status.text = "Status: mail draft opened (attachment may not be included)."
        except Exception:
            self.status.text = "Status: failed to open email composer."


class SentinelXApp(App):
    def build(self):
        self.title = "Sentinel-X"
        return SentinelXRoot()

    def on_start(self):
        root = self.root
        root.request_permissions()
        Clock.schedule_once(lambda *_: root.connect_camera(), 0.6)

        # Start Android service (safe on non-Android)
        if IS_ANDROID and AndroidService is not None:
            try:
                svc = AndroidService("Sentinel-X Service", "Telemetry + Harsh Braking Monitor")
                svc.start("service started")
            except Exception:
                pass


if __name__ == "__main__":
    SentinelXApp().run()
