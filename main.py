# -*- coding: utf-8 -*-
"""
Sentinel-X v1.6.0 -- Civic Enforcement (Android)
Phase 1: Continuous recording, crash recovery, threaded analysis, telemetry.
Phase 2: Evidence integrity — SHA-256 hashing, metadata watermark, report log.
Phase 3: Offline resilience — report queue, connectivity detection, auto-retry.
Phase 4: Enhanced detection — ONNX model loader, speed zones, subsystem status.
Phase 5: Automatic plate OCR — ML Kit text recognition, auto-fill, jurisdiction routing.
Phase 6: Citizen tools (X/WhatsApp, vehicle lookup, hazards, SOS, i18n, privacy)
         + over-the-air updates (GitHub OTA for sideloaded, Play In-App Updates).
Offline GPS->state via the bundled pure-Python IndiaGeocoder (no scipy on device).
"""

import os
import re
import json
import socket
import threading
import time
import math
import hashlib
import shutil
import collections
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.utils import platform
from kivy.graphics import Color, RoundedRectangle, Rectangle, Line

Window.softinput_mode = "below_target"

try:
    import cv2
except Exception:
    cv2 = None

try:
    import numpy as np
except Exception:
    np = None


class IndiaGeocoder:
    """Pure-Python offline reverse geocoder for Indian states.

    Uses nearest state-centroid by great-circle distance — no numpy/scipy.
    This is the on-device path: reverse_geocode / reverse_geocoder both import
    scipy (cKDTree), which cannot cross-compile for Android via python-for-android,
    so they are excluded from the APK and this fallback is used instead.
    """

    # (lat, lon, full state name) — major-city anchors per state. Multiple anchors
    # for large/border states sharpen nearest-anchor accuracy (e.g. Bengaluru sits
    # near the Tamil Nadu border, so Karnataka needs a southern anchor).
    _CENTROIDS = [
        # Directory states (routed to police email)
        (28.61, 77.21, "Delhi"),
        (29.06, 76.09, "Haryana"), (28.90, 76.61, "Haryana"),
        (28.4595, 77.0266, "Haryana"), (28.4089, 77.3178, "Haryana"),  # Gurugram, Faridabad (NCR)
        (19.08, 72.88, "Maharashtra"), (18.52, 73.86, "Maharashtra"), (21.15, 79.09, "Maharashtra"),
        (12.97, 77.59, "Karnataka"), (15.36, 75.12, "Karnataka"), (12.30, 76.65, "Karnataka"),
        (13.08, 80.27, "Tamil Nadu"), (11.02, 76.96, "Tamil Nadu"), (9.92, 78.12, "Tamil Nadu"),
        (26.85, 80.95, "Uttar Pradesh"), (25.32, 82.97, "Uttar Pradesh"), (27.18, 78.01, "Uttar Pradesh"),
        (9.93, 76.27, "Kerala"), (8.52, 76.94, "Kerala"), (11.25, 75.78, "Kerala"),
        (23.02, 72.57, "Gujarat"), (21.17, 72.83, "Gujarat"), (22.31, 73.18, "Gujarat"),
        (22.57, 88.36, "West Bengal"), (23.25, 87.85, "West Bengal"),
        (17.39, 78.49, "Telangana"), (18.00, 79.59, "Telangana"),
        (30.90, 75.85, "Punjab"), (31.63, 74.87, "Punjab"), (31.33, 75.58, "Punjab"),
        (26.91, 75.79, "Rajasthan"), (26.45, 74.64, "Rajasthan"), (24.58, 73.71, "Rajasthan"),
        (15.49, 73.83, "Goa"),
        # Neighbouring states (no email directory, but sharpen nearest-state accuracy)
        (23.25, 77.41, "Madhya Pradesh"), (22.72, 75.86, "Madhya Pradesh"),
        (25.59, 85.14, "Bihar"),
        (16.51, 80.65, "Andhra Pradesh"), (17.69, 83.22, "Andhra Pradesh"),
        (20.30, 85.82, "Odisha"),
        (26.14, 91.74, "Assam"),
        (23.36, 85.33, "Jharkhand"),
        (21.25, 81.63, "Chhattisgarh"),
        (30.32, 78.03, "Uttarakhand"),
        (31.10, 77.17, "Himachal Pradesh"),
        (34.08, 74.80, "Jammu and Kashmir"), (32.73, 74.86, "Jammu and Kashmir"),
        # Remaining states/UTs (capital + a second anchor for large ones), so
        # GPS anywhere in India resolves to the right jurisdiction.
        (23.18, 79.95, "Madhya Pradesh"),                      # Jabalpur
        (26.80, 84.50, "Bihar"),
        (22.80, 86.18, "Jharkhand"),                           # Jamshedpur
        (19.31, 84.79, "Odisha"),                              # Berhampur
        (27.48, 94.91, "Assam"),                               # Dibrugarh
        (19.08, 82.03, "Chhattisgarh"),                        # Jagdalpur
        (29.96, 78.16, "Uttarakhand"),                         # Haridwar
        (32.22, 76.32, "Himachal Pradesh"),                    # Dharamshala
        (14.47, 78.82, "Andhra Pradesh"), (13.63, 79.42, "Andhra Pradesh"),  # Kadapa, Tirupati
        (30.73, 76.78, "Chandigarh"),
        (34.15, 77.58, "Ladakh"),
        (27.33, 88.61, "Sikkim"),
        (25.57, 91.88, "Meghalaya"),
        (23.83, 91.28, "Tripura"),
        (24.82, 93.94, "Manipur"),
        (23.73, 92.72, "Mizoram"),
        (25.67, 94.11, "Nagaland"),
        (27.08, 93.61, "Arunachal Pradesh"),
        (11.94, 79.81, "Puducherry"),
        (11.62, 92.73, "Andaman and Nicobar Islands"),
        (10.57, 72.64, "Lakshadweep"),
        (20.27, 73.02, "Dadra and Nagar Haveli and Daman and Diu"),
        (20.40, 72.83, "Dadra and Nagar Haveli and Daman and Diu"),
    ]

    @staticmethod
    def _haversine(la1, lo1, la2, lo2):
        r = 6371.0
        p1, p2 = math.radians(la1), math.radians(la2)
        dp = math.radians(la2 - la1)
        dl = math.radians(lo2 - lo1)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(min(1.0, math.sqrt(a)))

    def get(self, coordinate):
        lat, lon = coordinate
        # Reject points clearly outside the Indian bounding box
        if not (6.0 <= lat <= 37.5 and 68.0 <= lon <= 97.5):
            return {"city": "", "state": ""}
        best_name, best_d = "", float("inf")
        for cla, clo, name in self._CENTROIDS:
            d = self._haversine(lat, lon, cla, clo)
            if d < best_d:
                best_d, best_name = d, name
        return {"city": "", "state": best_name}


rg = None
try:
    import reverse_geocode
    rg = reverse_geocode
except Exception:
    try:
        import reverse_geocoder as _rg
        rg = _rg
    except Exception:
        # On Android (and anywhere scipy is unavailable) use the bundled geocoder
        rg = IndiaGeocoder()

# Phase 6 — citizen-empowerment logic (pure Python, Kivy-free, unit-tested)
from civic import (
    CivicDirectory, ReportChannels, VehicleLookup, DuplicateGuard, I18N,
    HazardReport, Emergency, ViolationHeatmap, PrivacyBlur, UpdateManifest,
    FollowUp,
)

try:
    from plyer import email as plyer_email
except Exception:
    plyer_email = None

plyer_accel = None
try:
    from plyer import accelerometer as _acc
    plyer_accel = _acc
except Exception:
    pass

Permission = None
request_permissions = None
autoclass = None
try:
    if platform == "android":
        from android.permissions import Permission as _P, request_permissions as _rp
        Permission, request_permissions = _P, _rp
        from jnius import autoclass as _ac
        autoclass = _ac
except Exception:
    pass

Preview = None
try:
    from camera4kivy import Preview as _Preview
    Preview = _Preview
except Exception:
    pass

DASH = "--"
APP_VERSION = "1.6.0"  # keep in sync with buildozer.spec


# ═════════════════════════════════════════════════════════════════════════
# GPS via pyjnius — directly calls Android LocationManager Java API
# This is far more reliable than plyer.gps
# ═════════════════════════════════════════════════════════════════════════
class AndroidGPS:
    """Direct access to Android LocationManager via pyjnius."""

    def __init__(self):
        self._lm = None
        self._available = False
        # Details of the last fix for evidence proofs: accuracy (m), fix time
        # (ms since epoch, from the GNSS/network fix rather than the phone
        # clock) and provider.
        self.last_fix = {}
        if platform == "android" and autoclass is not None:
            try:
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                activity = PythonActivity.mActivity
                Context = autoclass("android.content.Context")
                self._lm = activity.getSystemService(Context.LOCATION_SERVICE)
                self._available = True
            except Exception:
                self._available = False

    def get_location(self):
        """Returns (lat, lon, speed) from last known GPS or network location."""
        if not self._available or self._lm is None:
            return 0.0, 0.0, 0.0
        try:
            LocationManager = autoclass("android.location.LocationManager")
            # Try GPS first, then network
            loc = None
            for provider in [LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER]:
                try:
                    loc = self._lm.getLastKnownLocation(provider)
                    if loc is not None:
                        break
                except Exception:
                    continue
            if loc is None:
                return 0.0, 0.0, 0.0
            lat = float(loc.getLatitude())
            lon = float(loc.getLongitude())
            speed = 0.0
            try:
                if loc.hasSpeed():
                    speed = float(loc.getSpeed())
            except Exception:
                pass
            try:
                self.last_fix = {
                    "accuracy_m": float(loc.getAccuracy()) if loc.hasAccuracy() else None,
                    "fix_time_ms": int(loc.getTime()),
                    "provider": str(loc.getProvider()),
                }
            except Exception:
                pass
            return lat, lon, speed
        except Exception:
            return 0.0, 0.0, 0.0


# ═════════════════════════════════════════════════════════════════════════
# DATA
# ═════════════════════════════════════════════════════════════════════════
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
    # Police email directory (36 states/UTs, each verified on an official
    # page; sources in civic.CivicDirectory.SOURCES). Kept in civic.py so the
    # app and the unit tests share one copy.
    VERIFIED_EMAILS = CivicDirectory.EMAILS
    STATE_NAME_TO_CODE = CivicDirectory.STATE_NAME_TO_CODE
    CODE_ALIASES = CivicDirectory.CODE_ALIASES


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
        pc = TrafficLawDB.CODE_ALIASES.get(pc, pc)
        # Inside a major city, the city's traffic wing handles the road.
        city = CivicDirectory.city_for(lat, lon) if lc else None
        if city:
            le = city["emails"]
        else:
            le = TrafficLawDB.VERIFIED_EMAILS.get(lc, []) if lc else []
        pe = TrafficLawDB.VERIFIED_EMAILS.get(pc, []) if pc else []
        seen, out = set(), []
        for e in le + pe:
            if e and e not in seen:
                seen.add(e)
                out.append(e)
        return {"lc": lc, "pc": pc, "le": le, "pe": pe, "all": out,
                "city": city["name"] if city else ""}


class AnalyticsEngine:
    def __init__(self):
        self.result = ""
        self._skip = 0
        self._plate_ocr = None
        self.ocr_plate = ""
        self.ocr_confidence = 0.0

    def set_plate_ocr(self, ocr):
        """Attach a PlateOCR instance for automatic plate recognition."""
        self._plate_ocr = ocr

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
            return
        self._skip += 1
        if self._skip % 3 != 0:
            return
        try:
            w, h = image_size
            if w <= 0 or h <= 0:
                return
            arr = np.frombuffer(bytes(pixels), dtype=np.uint8).reshape((h, w, 4))
            bgr_full = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            # CV contour pass runs on a 640-capped copy for speed/stability.
            bgr = bgr_full
            if w > 640:
                s = 640.0 / w
                bgr = cv2.resize(bgr_full, (640, int(h * s)))
            gray = cv2.bilateralFilter(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), 9, 75, 75)
            cnts, _ = cv2.findContours(cv2.Canny(gray, 60, 180), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            count = 0
            for c in cnts:
                x, y, cw, ch = cv2.boundingRect(c)
                ar = cw / max(ch, 1)
                if cw >= 60 and ch >= 20 and 2.0 <= ar <= 6.5 and cw * ch >= 2000:
                    count += 1
            self.result = "CV:%d" % count if count else "CV:--"
            # Phase 5: Run OCR on the FULL-resolution frame every cadence.
            # The engine locates text itself, so this works even when contour
            # detection finds no plate-like rectangle. process_frame applies
            # its own wall-clock throttle so this stays cheap.
            if self._plate_ocr is not None:
                try:
                    plate, conf = self._plate_ocr.process_frame(bgr_full)
                    if conf > 0.5:
                        self.ocr_plate = plate
                        self.ocr_confidence = conf
                except Exception:
                    pass
        except Exception:
            self.result = "CV:err"


# ═════════════════════════════════════════════════════════════════════════
# Phase 5 — Automatic Plate OCR (ML Kit on Android, Tesseract on desktop)
# ═════════════════════════════════════════════════════════════════════════
class PlateOCR:
    """Automatic number plate recognition.

    Engines (auto-selected): Google ML Kit on-device text recognition on
    Android; pytesseract on desktop for development. The pipeline reads the
    full frame first (ML Kit locates text itself), then refines with cropped
    plate candidates, normalizes to the Indian plate format, and suggests
    jurisdiction routing.
    """

    # Final number block requires 3-4 digits: real Indian plates always have
    # 3-4, and this rejects fragment noise from surrounding signage text
    # (e.g. "LIMIT 50" must not be mis-read as a plate).
    INDIAN_PLATE_RE = re.compile(
        r"([A-Z]{2})\s*(\d{1,2})\s*([A-Z]{0,3})\s*(\d{3,4})", re.I
    )
    # Confidence thresholds
    CONF_HIGH = 0.85   # Strong regex match with all groups
    CONF_MEDIUM = 0.6  # Partial match
    CONF_LOW = 0.35    # Alphanumeric fallback
    # Valid RTO state/UT codes. A regex hit on any other two letters (e.g.
    # "AB 1234" from the second line of a two-line plate) is demoted below
    # the auto-fill threshold.
    STATE_CODES = frozenset(
        "AN AP AR AS BR CG CH DD DL DN GA GJ HP HR JH JK KA KL LA LD MH ML MN "
        "MP MZ NL OD OR PB PY RJ SK TN TR TS UK UP WB".split()
    )
    # Bharat-series (BH) plates carry no state: "22 BH 1234 AA"
    # (registration year, BH, 4-digit number, 1-2 letters).
    BH_PLATE_RE = re.compile(r"(\d{2})\s*BH\s*(\d{4})\s*([A-Z]{1,2})\b", re.I)
    # Wall-clock throttle so heavy OCR runs at most a couple times per second
    SCAN_INTERVAL = 0.6    # actively searching
    HOLD_INTERVAL = 1.5    # re-confirm interval after a confirmed read
    # Live auto-fill needs the same plate in VOTES_NEEDED of the last
    # VOTE_WINDOW reads, so a one-frame misread (e.g. "4" read as "Z")
    # never reaches the form. SCAN/CAPTURE reads stay single-shot.
    VOTES_NEEDED = 2
    VOTE_WINDOW = 5
    BOX_TTL = 1.5          # seconds a plate box stays drawn on the preview

    def __init__(self):
        self._engine = None        # "mlkit" | "tesseract" | None
        self._recognizer = None    # ML Kit client
        self._jc = {}              # Java classes cached for worker threads
        self._tess = None          # pytesseract module
        self._last_plate = ""
        self._last_confidence = 0.0
        self._last_attempt = 0.0
        self._region_found = False
        self._votes = collections.deque(maxlen=self.VOTE_WINDOW)
        self._box = None           # (x, y, w, h, frame_w, frame_h, ts, confirmed)
        self._lock = threading.Lock()
        self._init_engines()

    def _init_engines(self):
        """Pick the best available OCR engine for this platform."""
        if self._init_mlkit():
            self._engine = "mlkit"
            return
        if self._init_tesseract():
            self._engine = "tesseract"
            return

    def _init_mlkit(self):
        """Initialize Google ML Kit TextRecognizer on Android."""
        if platform != "android" or autoclass is None:
            return False
        try:
            TextRecognition = autoclass(
                "com.google.mlkit.vision.text.TextRecognition"
            )
            LatinOptions = autoclass(
                "com.google.mlkit.vision.text.latin.TextRecognizerOptions"
            )
            # pyjnius cannot reach a nested class (Builder) as an attribute, so use
            # the static DEFAULT_OPTIONS field; fall back to the $-qualified Builder.
            try:
                options = LatinOptions.DEFAULT_OPTIONS
            except Exception:
                Builder = autoclass(
                    "com.google.mlkit.vision.text.latin.TextRecognizerOptions$Builder"
                )
                options = Builder().build()
            self._recognizer = TextRecognition.getClient(options)
            # Resolve every class _ocr_mlkit needs NOW, on the main thread.
            # OCR runs on worker threads, where pyjnius' autoclass() falls back
            # to the system class loader and cannot see the APK's bundled ML
            # Kit / GMS classes (ClassNotFoundException for InputImage), which
            # silently turned every OCR attempt into "".
            self._jc = {
                "Bitmap": autoclass("android.graphics.Bitmap"),
                "BitmapConfig": autoclass("android.graphics.Bitmap$Config"),
                "InputImage": autoclass("com.google.mlkit.vision.common.InputImage"),
                "Tasks": autoclass("com.google.android.gms.tasks.Tasks"),
                "TimeUnit": autoclass("java.util.concurrent.TimeUnit"),
                "ByteBuffer": autoclass("java.nio.ByteBuffer"),
                # Never called directly, but pyjnius wraps returned objects
                # by class name; pre-registering them here keeps that lookup
                # off the worker thread's class loader.
                "Task": autoclass("com.google.android.gms.tasks.Task"),
                "Text": autoclass("com.google.mlkit.vision.text.Text"),
                "TextBlock": autoclass("com.google.mlkit.vision.text.Text$TextBlock"),
                "TextLine": autoclass("com.google.mlkit.vision.text.Text$Line"),
            }
            return self._recognizer is not None
        except Exception:
            return False

    def _init_tesseract(self):
        """Initialize pytesseract on desktop if installed (dev/testing)."""
        try:
            import pytesseract
            # Probe the tesseract binary; raises if not on PATH.
            pytesseract.get_tesseract_version()
            self._tess = pytesseract
            return True
        except Exception:
            return False

    @property
    def available(self):
        return self._engine is not None

    @property
    def engine_name(self):
        return {"mlkit": "ML Kit", "tesseract": "Tesseract"}.get(
            self._engine, "none"
        )

    @property
    def last_plate(self):
        with self._lock:
            return self._last_plate

    @property
    def last_confidence(self):
        with self._lock:
            return self._last_confidence

    @property
    def region_found(self):
        """True when a plate-like region with characters was seen but no
        readable text could be extracted (e.g. no OCR engine, too blurry)."""
        with self._lock:
            return self._region_found

    @property
    def candidates(self):
        """Distinct plates from recent live reads, most frequent first."""
        with self._lock:
            votes = list(self._votes)
        return sorted(set(votes), key=lambda p: (-votes.count(p), votes[::-1].index(p)))

    def box(self):
        """Recent plate box for the preview overlay, or None when stale."""
        with self._lock:
            b = self._box
        if b is None or time.time() - b[6] > self.BOX_TTL:
            return None
        return b

    def reset(self):
        """Clear last detection state."""
        with self._lock:
            self._last_plate = ""
            self._last_confidence = 0.0
            self._last_attempt = 0.0
            self._region_found = False
            self._votes.clear()
            self._box = None

    # ── Plate candidate cropping ─────────────────────────────────────────
    @staticmethod
    def crop_plate_candidates(bgr):
        """Find and crop plate-like regions from a BGR image.

        Returns list of (cropped_bgr, (x, y, w, h)) sorted by area descending.
        """
        if cv2 is None or np is None:
            return []
        candidates = []
        try:
            gray = cv2.bilateralFilter(
                cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY), 9, 75, 75
            )
            edges = cv2.Canny(gray, 60, 180)
            cnts, _ = cv2.findContours(
                edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            h_img, w_img = bgr.shape[:2]
            for c in cnts:
                x, y, cw, ch = cv2.boundingRect(c)
                ar = cw / max(ch, 1)
                if cw >= 60 and ch >= 20 and 2.0 <= ar <= 6.5 and cw * ch >= 2000:
                    pad = 6
                    x1, y1 = max(0, x - pad), max(0, y - pad)
                    x2, y2 = min(w_img, x + cw + pad), min(h_img, y + ch + pad)
                    crop = bgr[y1:y2, x1:x2]
                    if crop.size > 0:
                        candidates.append((crop, (x, y, cw, ch)))
            candidates.sort(key=lambda c: c[1][2] * c[1][3], reverse=True)
        except Exception:
            pass
        return candidates[:5]

    # ── Colour enhancement for OCR engines ───────────────────────────────
    @staticmethod
    def enhance_for_ocr(bgr):
        """Upscale + contrast-enhance a colour image for OCR.

        Text recognizers are trained on natural images, so this keeps colour
        (no binarization), upscales small crops so glyphs are large enough,
        boosts local contrast, and applies a mild unsharp mask.
        """
        if cv2 is None or np is None:
            return bgr
        try:
            h, w = bgr.shape[:2]
            if h == 0 or w == 0:
                return bgr
            # Upscale so character height is comfortably readable
            if h < 180:
                scale = min(180.0 / h, 4.0)
                bgr = cv2.resize(
                    bgr, (max(1, int(w * scale)), max(1, int(h * scale))),
                    interpolation=cv2.INTER_CUBIC,
                )
            lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
            l_ch, a_ch, b_ch = cv2.split(lab)
            l_ch = cv2.createCLAHE(
                clipLimit=2.0, tileGridSize=(8, 8)
            ).apply(l_ch)
            bgr = cv2.cvtColor(cv2.merge((l_ch, a_ch, b_ch)), cv2.COLOR_LAB2BGR)
            blur = cv2.GaussianBlur(bgr, (0, 0), 1.0)
            bgr = cv2.addWeighted(bgr, 1.5, blur, -0.5, 0)
            return bgr
        except Exception:
            return bgr

    # ── Binarized preprocessing (for char-region detection only) ─────────
    @staticmethod
    def preprocess_plate(crop):
        """Binarize a plate crop for character-region counting."""
        if cv2 is None or np is None:
            return crop
        try:
            h, w = crop.shape[:2]
            if h == 0 or w == 0:
                return crop
            target_h = 64
            scale = target_h / h
            resized = cv2.resize(crop, (max(1, int(w * scale)), target_h))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
            enhanced = clahe.apply(gray)
            _, thresh = cv2.threshold(
                enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )
            return thresh
        except Exception:
            return crop

    # ── Text cleanup ─────────────────────────────────────────────────────
    @staticmethod
    def clean_plate_text(raw):
        """Extract the best Indian plate match from raw OCR text.

        Returns (plate_string, confidence). Scans ALL candidate matches and
        prefers the one with a series block (highest confidence).
        Indian format: SS DD AAA DDDD  (state, district, series, number)
        """
        if not raw:
            return "", 0.0
        text = raw.upper().strip()
        text = re.sub(r"[^A-Z0-9\s]", "", text)
        text = re.sub(r"\s+", " ", text).strip()

        best_plate, best_conf = "", 0.0
        # Also try the text with spaces removed: ML Kit returns two-line
        # plates as "DL 3C\nAB 1234", where the series is split across the
        # break and the spaced form only matches the bogus "AB1234".
        for cand in (text, text.replace(" ", "")):
            for m in PlateOCR.INDIAN_PLATE_RE.finditer(cand):
                state = m.group(1).upper()
                dist = m.group(2)
                series = m.group(3).upper()
                num = m.group(4)
                plate = "%s%s%s%s" % (state, dist, series, num)
                conf = PlateOCR.CONF_HIGH if series else PlateOCR.CONF_MEDIUM
                if state not in PlateOCR.STATE_CODES:
                    conf -= 0.25
                # Current plates always print a 4-digit number; a 3-digit
                # block usually means a digit was misread as a letter and
                # absorbed into the series ("EV4011" -> "EVZ011").
                if len(num) == 3:
                    conf -= 0.05
                if conf > best_conf:
                    best_plate, best_conf = plate, conf
        for cand in (text, text.replace(" ", "")):
            for m in PlateOCR.BH_PLATE_RE.finditer(cand):
                plate = "%sBH%s%s" % (m.group(1), m.group(2), m.group(3).upper())
                if PlateOCR.CONF_HIGH > best_conf:
                    best_plate, best_conf = plate, PlateOCR.CONF_HIGH
        if best_plate:
            return best_plate, best_conf

        # Fallback: contiguous alphanumeric run starting with two letters
        cleaned = re.sub(r"[^A-Z0-9]", "", text)
        if len(cleaned) >= 6 and cleaned[:2].isalpha():
            return cleaned, PlateOCR.CONF_LOW
        return "", 0.0

    # ── ML Kit OCR (Android) ─────────────────────────────────────────────
    def _ocr_mlkit(self, bgr):
        """Run Google ML Kit text recognition on a BGR image.

        Must run on a background thread — ML Kit's Tasks.await raises if
        called on the Android main thread. Returns (raw text, lines) where
        lines is [(line_text, (x, y, w, h)), ...] in image pixels.
        """
        if self._recognizer is None or not self._jc:
            return "", []
        try:
            jc = self._jc  # resolved on the main thread in _init_mlkit
            Bitmap, BitmapConfig = jc["Bitmap"], jc["BitmapConfig"]
            InputImage, Tasks = jc["InputImage"], jc["Tasks"]
            TimeUnit, ByteBuffer = jc["TimeUnit"], jc["ByteBuffer"]

            h, w = bgr.shape[:2]
            rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
            bitmap = Bitmap.createBitmap(w, h, BitmapConfig.ARGB_8888)
            buf = ByteBuffer.wrap(rgba.tobytes())
            bitmap.copyPixelsFromBuffer(buf)

            image = InputImage.fromBitmap(bitmap, 0)
            task = self._recognizer.process(image)
            # 5-second timeout overload prevents indefinite blocking.
            tasks_await = getattr(Tasks, "await")
            result = tasks_await(task, 5, TimeUnit.SECONDS)
            raw = result.getText() if result else ""
            lines = []
            try:
                blocks = result.getTextBlocks()
                for bi in range(blocks.size()):
                    lns = blocks.get(bi).getLines()
                    for li in range(lns.size()):
                        ln = lns.get(li)
                        r = ln.getBoundingBox()
                        if r is not None:
                            lines.append((ln.getText() or "",
                                          (r.left, r.top, r.width(), r.height())))
            except Exception:
                lines = []
            bitmap.recycle()
            return raw or "", lines
        except Exception:
            return "", []

    # ── Tesseract OCR (desktop / dev) ────────────────────────────────────
    def _ocr_tesseract(self, bgr):
        """Run pytesseract on a BGR image. Returns (raw text, [])."""
        if self._tess is None or cv2 is None:
            return "", []
        try:
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            # PSM 6/11 work well for plates; restrict charset.
            cfg = ("--oem 1 --psm 6 -c "
                   "tessedit_char_whitelist="
                   "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
            return self._tess.image_to_string(rgb, config=cfg) or "", []
        except Exception:
            return "", []

    def _ocr(self, bgr):
        """Dispatch to the active OCR engine. Returns (raw, lines)."""
        if self._engine == "mlkit":
            return self._ocr_mlkit(bgr)
        if self._engine == "tesseract":
            return self._ocr_tesseract(bgr)
        return "", []

    @staticmethod
    def plate_box(plate, lines, scale=1.0, offset=(0, 0)):
        """Union box of the OCR lines that make up `plate` (two-line plates
        span two lines), mapped back by 1/scale + offset. None if unmatched."""
        boxes = []
        for text, (x, y, w, h) in lines:
            t = re.sub(r"[^A-Z0-9]", "", (text or "").upper())
            if len(t) >= 3 and (t in plate or plate in t):
                boxes.append((x, y, x + w, y + h))
        if not boxes:
            return None
        x1 = min(b[0] for b in boxes) / scale + offset[0]
        y1 = min(b[1] for b in boxes) / scale + offset[1]
        x2 = max(b[2] for b in boxes) / scale + offset[0]
        y2 = max(b[3] for b in boxes) / scale + offset[1]
        return (x1, y1, x2 - x1, y2 - y1)

    # ── OpenCV character-region detector (signal only, NOT text OCR) ──────
    @staticmethod
    def _detect_char_regions(crop_bgr):
        """Count character-like contours in a preprocessed plate crop.

        Used only to tell the user a plate is visible but not yet readable;
        it can never produce text.
        """
        if cv2 is None or np is None:
            return 0
        try:
            preprocessed = PlateOCR.preprocess_plate(crop_bgr)
            if len(preprocessed.shape) == 3:
                gray = cv2.cvtColor(preprocessed, cv2.COLOR_BGR2GRAY)
            else:
                gray = preprocessed
            if np.mean(gray) > 127:
                gray = cv2.bitwise_not(gray)
            cnts, _ = cv2.findContours(
                gray, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            h_img, w_img = gray.shape[:2]
            count = 0
            for c in cnts:
                x, y, cw, ch = cv2.boundingRect(c)
                if (ch > h_img * 0.3 and cw > 3 and cw < w_img * 0.25
                        and 0.15 < (cw / max(ch, 1)) < 1.2):
                    count += 1
            return count
        except Exception:
            return 0

    # ── Core read: full-frame first, then crop refinement ────────────────
    def _read_best(self, bgr):
        """Read the best plate from an image.

        Returns (plate, conf, chars, box); box is (x, y, w, h) in `bgr`
        pixels or None.
        """
        best_plate, best_conf, chars_seen, best_box = "", 0.0, 0, None
        if self._engine is not None:
            # 1. Full-frame OCR — the engine locates text itself, which is
            #    far more robust than relying on contour cropping.
            enh = self.enhance_for_ocr(bgr)
            raw, lines = self._ocr(enh)
            if raw:
                plate, conf = self.clean_plate_text(raw)
                if conf > best_conf:
                    best_plate, best_conf = plate, conf
                    best_box = self.plate_box(
                        plate, lines, enh.shape[1] / float(bgr.shape[1]))
            # 2. Cropped-candidate refinement when the full frame was weak.
            if best_conf < self.CONF_HIGH:
                for crop, (cx, cy, _cw, _ch) in self.crop_plate_candidates(bgr):
                    enh = self.enhance_for_ocr(crop)
                    raw, lines = self._ocr(enh)
                    if raw:
                        plate, conf = self.clean_plate_text(raw)
                        if conf > best_conf:
                            best_plate, best_conf = plate, conf
                            pad = 6  # crop_plate_candidates pads by 6px
                            best_box = self.plate_box(
                                plate, lines, enh.shape[1] / float(crop.shape[1]),
                                (max(0, cx - pad), max(0, cy - pad)))
                            if conf >= self.CONF_HIGH:
                                break
                    if best_conf < self.CONF_MEDIUM:
                        chars_seen = max(
                            chars_seen, self._detect_char_regions(crop)
                        )
        else:
            # No OCR engine: only report whether a plate region is visible.
            for crop, _bbox in self.crop_plate_candidates(bgr):
                chars_seen = max(chars_seen, self._detect_char_regions(crop))
        return best_plate, best_conf, chars_seen, best_box

    # ── Live pipeline (throttled, called from the analysis worker) ───────
    def process_frame(self, bgr):
        """Throttled live OCR with multi-frame voting.

        Returns (plate, confidence) of the last *confirmed* plate.
        """
        now = time.time()
        with self._lock:
            interval = (self.HOLD_INTERVAL if self._last_confidence > 0.5
                        else self.SCAN_INTERVAL)
            if now - self._last_attempt < interval:
                return self._last_plate, self._last_confidence
            self._last_attempt = now

        plate, conf, chars, box = self._read_best(bgr)

        with self._lock:
            self._region_found = chars >= 4
            if conf > 0.5:
                self._votes.append(plate)
                confirmed = self._votes.count(plate) >= self.VOTES_NEEDED
                if confirmed:
                    self._last_plate = plate
                    self._last_confidence = conf
                if box is not None:
                    h, w = bgr.shape[:2]
                    self._box = box + (w, h, now, confirmed)
            return self._last_plate, self._last_confidence

    # ── Forced pipeline (capture / on-demand scan; bg thread) ────────────
    def process_image(self, bgr):
        """Force a fresh full read, bypassing throttle. Returns (plate, conf)."""
        plate, conf, chars, _box = self._read_best(bgr)
        with self._lock:
            self._region_found = chars >= 4
            if conf > 0.5:
                self._last_plate = plate
                self._last_confidence = conf
                self._last_attempt = time.time()
        return plate, conf

    def suggest_routing(self, plate, lat=0.0, lon=0.0):
        """Given an OCR-detected plate, suggest jurisdiction email routing.

        Returns dict with state_code, emails, and confidence.
        """
        if not plate:
            return {"plate": "", "state_code": "", "emails": [],
                    "confidence": 0.0, "source": "ocr"}
        rt = JurisdictionEngine.route(lat, lon, plate)
        return {
            "plate": plate,
            "state_code": rt["pc"],
            "emails": rt["all"],
            "confidence": self._last_confidence,
            "source": "ocr",
        }


# ═════════════════════════════════════════════════════════════════════════
# Phase 1 — Memory-bounded ring buffer
# ═════════════════════════════════════════════════════════════════════════
class FrameRingBuffer:
    """Thread-safe fixed-capacity ring buffer for camera frames.

    Prevents OOM by dropping oldest frames when full.
    """

    def __init__(self, max_frames=30):
        self._buf = collections.deque(maxlen=max_frames)
        self._lock = threading.Lock()
        self._dropped = 0

    def push(self, timestamp, pixels, image_size):
        with self._lock:
            if len(self._buf) == self._buf.maxlen:
                self._dropped += 1
            self._buf.append((timestamp, pixels, image_size))

    def pop(self):
        with self._lock:
            if self._buf:
                return self._buf.popleft()
            return None

    def latest(self):
        with self._lock:
            if self._buf:
                return self._buf[-1]
            return None

    @property
    def dropped_count(self):
        with self._lock:
            return self._dropped

    def __len__(self):
        with self._lock:
            return len(self._buf)


# ═════════════════════════════════════════════════════════════════════════
# Phase 1 — Threaded frame analysis worker
# ═════════════════════════════════════════════════════════════════════════
class FrameAnalysisWorker:
    """Daemon thread that pops frames from a FrameRingBuffer and analyzes.

    Skips to the latest frame when falling behind (load-shedding).
    """

    def __init__(self, frame_buffer, analytics):
        self._buffer = frame_buffer
        self._analytics = analytics
        self._running = False
        self._thread = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self):
        while self._running:
            frame = self._buffer.pop()
            if frame is None:
                time.sleep(0.05)
                continue
            # Skip to latest if behind
            latest = self._buffer.latest()
            if latest is not None:
                frame = latest
                # Drain intermediate frames
                while self._buffer.pop() is not None:
                    pass
            _ts, pixels, image_size = frame
            try:
                self._analytics.analyze_frame(pixels, image_size)
            except Exception:
                pass


# ═════════════════════════════════════════════════════════════════════════
# Phase 1 — Camera crash recovery watchdog
# ═════════════════════════════════════════════════════════════════════════
class CameraWatchdog:
    """Detects camera stalls and reconnects with exponential backoff."""

    def __init__(self, reconnect_cb):
        self._last_frame_ts = time.time()
        self._reconnect_cb = reconnect_cb
        self._backoff = 2.0
        self._max_backoff = 30.0
        self._reconnecting = False
        self._check_event = None

    def start(self):
        self._check_event = Clock.schedule_interval(self._check, 3.0)

    def stop(self):
        if self._check_event:
            self._check_event.cancel()
            self._check_event = None

    def frame_received(self):
        self._last_frame_ts = time.time()
        self._backoff = 2.0

    def _check(self, _dt):
        if self._reconnecting:
            return
        elapsed = time.time() - self._last_frame_ts
        if elapsed > 5.0:
            self._reconnecting = True
            Clock.schedule_once(lambda dt: self._do_reconnect(), self._backoff)
            self._backoff = min(self._backoff * 2, self._max_backoff)

    def _do_reconnect(self):
        # Frames may have resumed during the backoff delay; don't bounce a
        # healthy camera.
        if time.time() - self._last_frame_ts > 5.0:
            try:
                self._reconnect_cb()
            except Exception:
                pass
        # Re-arm: give the new connection a fresh 5s grace window, and let
        # _check schedule another (backed-off) attempt if frames still don't
        # arrive. Without this a failed reconnect left _reconnecting stuck True
        # and the watchdog never retried again.
        self._last_frame_ts = time.time()
        self._reconnecting = False


# ═════════════════════════════════════════════════════════════════════════
# Phase 1 — Dashcam-style continuous recorder
# ═════════════════════════════════════════════════════════════════════════
class DashcamRecorder:
    """Saves JPEG frames in time-stamped segment directories.

    Maintains a ring of N segments and auto-deletes the oldest.
    """

    SEGMENT_DURATION = 120   # seconds per segment
    MAX_SEGMENTS = 5         # keep at most 5 segments (~10 min)
    FRAME_INTERVAL = 1.0     # save 1 frame per second
    CLIP_FPS = 4             # in-memory ring for "save last N s" clips
    CLIP_SECONDS = 15

    def __init__(self, frame_buffer, base_dir):
        self._buffer = frame_buffer
        self._base_dir = base_dir
        self._running = False
        self._thread = None
        self._current_segment_dir = None
        self._segment_start = 0
        self._last_save_ts = 0
        self._recording = False
        self._frame_count = 0
        # (timestamp, JPEG bytes) for the last CLIP_SECONDS at CLIP_FPS
        self._clip = collections.deque(maxlen=self.CLIP_FPS * self.CLIP_SECONDS)
        self._clip_lock = threading.Lock()
        self._last_clip_ts = 0

    def start(self):
        self._running = True
        self._recording = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._recording = False
        if self._thread:
            self._thread.join(timeout=3.0)

    @property
    def recording(self):
        return self._recording

    @recording.setter
    def recording(self, val):
        self._recording = bool(val)

    @property
    def frame_count(self):
        return self._frame_count

    def _run(self):
        while self._running:
            if not self._recording:
                time.sleep(0.5)
                continue
            frame = self._buffer.latest()
            if frame is None:
                time.sleep(0.1)
                continue
            now = time.time()
            if now - self._last_clip_ts < 1.0 / self.CLIP_FPS:
                time.sleep(0.03)
                continue
            self._last_clip_ts = now
            jpeg = self._encode(frame)
            if jpeg is None:
                continue
            with self._clip_lock:
                self._clip.append((now, jpeg))
            if now - self._last_save_ts < self.FRAME_INTERVAL:
                continue
            # Rotate segment if needed
            if (self._current_segment_dir is None or
                    now - self._segment_start >= self.SEGMENT_DURATION):
                self._new_segment()
            self._save_frame(jpeg)
            self._last_save_ts = now

    def _new_segment(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dashcam_dir = os.path.join(self._base_dir, "dashcam")
        seg_dir = os.path.join(dashcam_dir, "seg_%s" % ts)
        os.makedirs(seg_dir, exist_ok=True)
        self._current_segment_dir = seg_dir
        self._segment_start = time.time()
        self._prune_old_segments()

    def _prune_old_segments(self):
        dashcam_dir = os.path.join(self._base_dir, "dashcam")
        try:
            segments = sorted(os.listdir(dashcam_dir))
            while len(segments) > self.MAX_SEGMENTS:
                oldest = segments.pop(0)
                shutil.rmtree(
                    os.path.join(dashcam_dir, oldest), ignore_errors=True
                )
        except Exception:
            pass

    @staticmethod
    def _encode(frame):
        """RGBA ring-buffer frame -> JPEG ndarray (or None)."""
        if cv2 is None or np is None:
            return None
        try:
            _ts, pixels, image_size = frame
            w, h = image_size
            arr = np.frombuffer(pixels, dtype=np.uint8).reshape((h, w, 4))
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
            return buf if ok else None
        except Exception:
            return None

    def _save_frame(self, jpeg):
        try:
            fname = "f_%s.jpg" % datetime.now().strftime("%H%M%S_%f")
            jpeg.tofile(os.path.join(self._current_segment_dir, fname))
            self._frame_count += 1
        except Exception:
            pass

    def save_clip(self, out_path):
        """Write the last CLIP_SECONDS as a Motion-JPEG AVI (OpenCV's built-in
        writer, no ffmpeg needed). Returns (path, frame_count) or ("", 0)."""
        if cv2 is None:
            return "", 0
        with self._clip_lock:
            frames = list(self._clip)
        if len(frames) < 2:
            return "", 0
        try:
            first = cv2.imdecode(frames[0][1], cv2.IMREAD_COLOR)
            h, w = first.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            vw = cv2.VideoWriter(out_path, fourcc, float(self.CLIP_FPS), (w, h))
            if not vw.isOpened():
                return "", 0
            n = 0
            for _ts, jpeg in frames:
                img = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)
                if img is not None and img.shape[:2] == (h, w):
                    vw.write(img)
                    n += 1
            vw.release()
            return (out_path, n) if n else ("", 0)
        except Exception:
            return "", 0


# ═════════════════════════════════════════════════════════════════════════
# Phase 1 — Telemetry receiver (consume service.py UDP broadcasts)
# ═════════════════════════════════════════════════════════════════════════
class TelemetryReceiver:
    """Listens on UDP for telemetry packets from the background service."""

    def __init__(self, host="0.0.0.0", port=17888):
        self._host = host
        self._port = port
        self._sock = None
        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        self._latest = {}

    def start(self):
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((self._host, self._port))
            self._sock.settimeout(1.0)
        except Exception:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self):
        while self._running:
            try:
                data, _addr = self._sock.recvfrom(4096)
                pkt = json.loads(data.decode("utf-8"))
                with self._lock:
                    self._latest = pkt
            except socket.timeout:
                continue
            except Exception:
                continue

    @property
    def latest(self):
        with self._lock:
            return dict(self._latest)


# ═════════════════════════════════════════════════════════════════════════
# Phase 2 — Evidence integrity: SHA-256 hashing
# ═════════════════════════════════════════════════════════════════════════
class EvidenceHasher:
    """Computes SHA-256 of evidence files for tamper detection."""

    @staticmethod
    def hash_file(filepath):
        """Return hex SHA-256 digest of a file."""
        h = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""

    @staticmethod
    def hash_bytes(data):
        """Return hex SHA-256 digest of raw bytes."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def write_hashfile(filepath):
        """Write a .sha256 sidecar file next to the evidence file."""
        digest = EvidenceHasher.hash_file(filepath)
        if digest:
            hpath = filepath + ".sha256"
            try:
                with open(hpath, "w") as f:
                    f.write("%s  %s\n" % (digest, os.path.basename(filepath)))
                return hpath
            except Exception:
                pass
        return ""

    @staticmethod
    def verify(filepath):
        """Verify a file against its .sha256 sidecar. Returns True/False/None."""
        hpath = filepath + ".sha256"
        if not os.path.isfile(hpath):
            return None
        try:
            with open(hpath, "r") as f:
                stored = f.read().strip().split()[0]
            return EvidenceHasher.hash_file(filepath) == stored
        except Exception:
            return None


class EvidenceProof:
    """Signed provenance record (<image>.proof.json) for an evidence photo.

    The payload (file SHA-256, capture time, GPS fix with accuracy and the
    fix's own satellite/network timestamp, device, app version) is signed
    with an EC P-256 key generated inside the Android Keystore. The private
    key never leaves the secure hardware, so a matching signature shows the
    record was produced on this device and not edited afterwards. Verify
    with the embedded public key (SHA256withECDSA over the payload bytes).
    """

    ALIAS = "sentinelx_evidence_v1"
    ALGORITHM = "SHA256withECDSA"

    @staticmethod
    def build_payload(path, digest, lat, lon, fix, device="", app_version=""):
        fix = fix or {}
        return {
            "file": os.path.basename(path),
            "sha256": digest,
            "captured_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "lat": round(float(lat), 6), "lon": round(float(lon), 6),
            "gps_accuracy_m": fix.get("accuracy_m"),
            "gps_fix_time_ms": fix.get("fix_time_ms"),
            "gps_provider": fix.get("provider"),
            "device": device, "app_version": app_version,
        }

    @staticmethod
    def _key():
        """(private key, public key bytes), creating the key on first use."""
        KeyStore = autoclass("java.security.KeyStore")
        ks = KeyStore.getInstance("AndroidKeyStore")
        ks.load(None, None)
        if not ks.containsAlias(EvidenceProof.ALIAS):
            KPG = autoclass("java.security.KeyPairGenerator")
            Props = autoclass("android.security.keystore.KeyProperties")
            Spec = autoclass("android.security.keystore.KeyGenParameterSpec$Builder")
            kpg = KPG.getInstance("EC", "AndroidKeyStore")
            # setDigests is Java varargs: pass the value itself. A Python
            # list gets wrapped into String[][] and aborts the JVM
            # (ArrayStoreException surfaced as a JNI abort, not catchable).
            spec = Spec(EvidenceProof.ALIAS, Props.PURPOSE_SIGN) \
                .setDigests(Props.DIGEST_SHA256).build()
            kpg.initialize(spec)
            kpg.generateKeyPair()
        from jnius import cast
        priv = cast("java.security.PrivateKey", ks.getKey(EvidenceProof.ALIAS, None))
        pub = bytes(ks.getCertificate(EvidenceProof.ALIAS).getPublicKey().getEncoded())
        return priv, pub

    @staticmethod
    def write(path, payload):
        """Sign `payload` and write <path>.proof.json. Returns the proof path,
        or "" off-device / on failure (the photo itself is unaffected)."""
        if platform != "android" or autoclass is None:
            return ""
        try:
            import base64
            body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
            priv, pub = EvidenceProof._key()
            sig = autoclass("java.security.Signature").getInstance(EvidenceProof.ALGORITHM)
            sig.initSign(priv)
            sig.update(body.encode("utf-8"))
            signature = bytes(sig.sign())
            proof = {
                "payload": body,
                "algorithm": EvidenceProof.ALGORITHM,
                "signature_b64": base64.b64encode(signature).decode("ascii"),
                "public_key_b64": base64.b64encode(pub).decode("ascii"),
                "key_store": "AndroidKeyStore",
            }
            ppath = path + ".proof.json"
            with open(ppath, "w") as f:
                json.dump(proof, f, indent=1)
            return ppath
        except Exception:
            return ""


# ═════════════════════════════════════════════════════════════════════════
# Phase 2 — Evidence metadata watermark
# ═════════════════════════════════════════════════════════════════════════
class EvidenceWatermark:
    """Embeds GPS/timestamp metadata onto evidence images."""

    @staticmethod
    def apply(filepath, lat, lon, timestamp_str, plate=""):
        """Burn metadata text onto the bottom of an image."""
        if cv2 is None or np is None:
            return False
        try:
            img = cv2.imread(filepath)
            if img is None:
                return False
            h, w = img.shape[:2]
            line1 = "%s | %.5f,%.5f" % (timestamp_str, lat, lon)
            line2 = "Plate: %s | Sentinel-X" % plate if plate else "Sentinel-X"
            # Semi-transparent overlay bar at bottom
            overlay = img.copy()
            bar_h = max(40, int(h * 0.06))
            cv2.rectangle(overlay, (0, h - bar_h), (w, h), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)
            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = max(0.35, w / 1800.0)
            thick = max(1, int(scale * 2))
            cv2.putText(img, line1, (8, h - bar_h + int(bar_h * 0.45)),
                        font, scale, (255, 255, 255), thick)
            cv2.putText(img, line2, (8, h - int(bar_h * 0.1)),
                        font, scale * 0.85, (200, 200, 200), thick)
            cv2.imwrite(filepath, img)
            return True
        except Exception:
            return False


# ═════════════════════════════════════════════════════════════════════════
# Phase 2 — Report history log
# ═════════════════════════════════════════════════════════════════════════
class ReportLog:
    """Append-only JSON-lines log of sent reports."""

    def __init__(self, log_dir):
        self._log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._path = os.path.join(log_dir, "report_log.jsonl")

    def append(self, report_dict):
        """Append a report entry with timestamp."""
        entry = dict(report_dict)
        entry["logged_at"] = datetime.now().isoformat()
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            return True
        except Exception:
            return False

    def read_all(self):
        """Read all log entries."""
        entries = []
        try:
            with open(self._path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return entries

    @property
    def count(self):
        """Number of logged reports."""
        return len(self.read_all())

    @property
    def path(self):
        return self._path


# ═════════════════════════════════════════════════════════════════════════
# Phase 3 — Offline report queue
# ═════════════════════════════════════════════════════════════════════════
class OfflineReportQueue:
    """Stores unsent reports as JSON files for later delivery."""

    def __init__(self, queue_dir):
        self._dir = queue_dir
        os.makedirs(queue_dir, exist_ok=True)

    def enqueue(self, report_dict):
        """Save a report to the queue directory."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        fpath = os.path.join(self._dir, "report_%s.json" % ts)
        try:
            payload = json.dumps(report_dict, default=str)
            with open(fpath, "w") as f:
                f.write(payload)
            return fpath
        except Exception:
            return ""

    def pending(self):
        """List pending report file paths, oldest first."""
        try:
            files = sorted(f for f in os.listdir(self._dir) if f.endswith(".json"))
            return [os.path.join(self._dir, f) for f in files]
        except Exception:
            return []

    def dequeue(self, fpath):
        """Remove a report from the queue after successful send."""
        try:
            os.remove(fpath)
            return True
        except Exception:
            return False

    def load(self, fpath):
        """Load a queued report."""
        try:
            with open(fpath, "r") as f:
                return json.loads(f.read())
        except Exception:
            return None

    @property
    def count(self):
        return len(self.pending())


# ═════════════════════════════════════════════════════════════════════════
# Phase 3 — Network connectivity detector
# ═════════════════════════════════════════════════════════════════════════
class ConnectivityChecker:
    """Checks network availability via socket probe."""

    PROBE_HOST = "8.8.8.8"
    PROBE_PORT = 53
    TIMEOUT = 3.0

    @staticmethod
    def is_online():
        """Returns True if device can reach the internet."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(ConnectivityChecker.TIMEOUT)
        try:
            s.connect((ConnectivityChecker.PROBE_HOST, ConnectivityChecker.PROBE_PORT))
            return True
        except Exception:
            return False
        finally:
            s.close()


# ═════════════════════════════════════════════════════════════════════════
# Phase 3 — Offline queue auto-retry daemon
# ═════════════════════════════════════════════════════════════════════════
class QueueRetryDaemon:
    """Background thread that retries queued reports when connectivity returns."""

    RETRY_INTERVAL = 60.0  # check every 60 seconds

    def __init__(self, queue, send_callback):
        self._queue = queue
        self._send_cb = send_callback
        self._running = False
        self._thread = None
        self._stop_evt = threading.Event()

    def start(self):
        self._running = True
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self):
        while self._running:
            # Event.wait returns immediately when stop() sets the event,
            # so shutdown is not delayed by the retry interval.
            if self._stop_evt.wait(self.RETRY_INTERVAL):
                break
            if not ConnectivityChecker.is_online():
                continue
            for fpath in self._queue.pending():
                report = self._queue.load(fpath)
                if report is None:
                    continue
                try:
                    if self._send_cb(report):
                        self._queue.dequeue(fpath)
                except Exception:
                    pass


# ═════════════════════════════════════════════════════════════════════════
# Phase 4 — ONNX model loader for plate detection
# ═════════════════════════════════════════════════════════════════════════
class ONNXDetector:
    """Optional ONNX model inference for number plate detection."""

    def __init__(self, model_dir):
        self._session = None
        self._available = False
        self._model_path = ""
        self._load(model_dir)

    def _load(self, model_dir):
        try:
            import onnxruntime as ort
        except ImportError:
            return
        # Look for detector.onnx
        mpath = os.path.join(model_dir, "detector.onnx")
        if not os.path.isfile(mpath):
            return
        try:
            self._session = ort.InferenceSession(mpath)
            self._model_path = mpath
            self._available = True
        except Exception:
            pass

    @property
    def available(self):
        return self._available

    @property
    def model_path(self):
        return self._model_path

    def detect(self, bgr_image):
        """Run detection on a BGR image. Returns list of (x, y, w, h, conf)."""
        if not self._available or self._session is None:
            return []
        if cv2 is None or np is None:
            return []
        try:
            inp = self._session.get_inputs()[0]
            name = inp.name
            shape = inp.shape  # e.g. [1, 3, 640, 640]
            h, w = shape[2], shape[3]
            resized = cv2.resize(bgr_image, (w, h))
            blob = resized.astype(np.float32).transpose(2, 0, 1)[np.newaxis] / 255.0
            results = self._session.run(None, {name: blob})
            detections = []
            if results and len(results) > 0:
                for det in results[0]:
                    if len(det) >= 5 and det[4] > 0.5:
                        detections.append(tuple(float(v) for v in det[:5]))
            return detections
        except Exception:
            return []


# ═════════════════════════════════════════════════════════════════════════
# Phase 4 — Speed zone awareness
# ═════════════════════════════════════════════════════════════════════════
class SpeedZoneChecker:
    """Detects if current location is near a speed-sensitive zone."""

    # Known zone types with default speed limits (km/h)
    ZONES = {
        "school": {"limit_kmh": 25, "radius_m": 200},
        "hospital": {"limit_kmh": 25, "radius_m": 150},
        "residential": {"limit_kmh": 30, "radius_m": 300},
    }

    def __init__(self):
        self._custom_zones = []  # list of (lat, lon, zone_type, label)

    def add_zone(self, lat, lon, zone_type, label=""):
        """Register a speed-sensitive zone."""
        if zone_type in self.ZONES:
            self._custom_zones.append((lat, lon, zone_type, label))

    def check(self, lat, lon, speed_kmh):
        """Check if speed exceeds limit for any nearby zone.

        Returns list of (zone_type, label, limit_kmh, distance_m) violations.
        """
        violations = []
        for zlat, zlon, ztype, zlabel in self._custom_zones:
            dist = self._haversine(lat, lon, zlat, zlon)
            zone_info = self.ZONES[ztype]
            if dist <= zone_info["radius_m"] and speed_kmh > zone_info["limit_kmh"]:
                violations.append((ztype, zlabel, zone_info["limit_kmh"], dist))
        return violations

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """Haversine distance in meters."""
        R = 6371000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = (math.sin(dphi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @property
    def zone_count(self):
        return len(self._custom_zones)


# ═════════════════════════════════════════════════════════════════════════
# Phase 4 — Subsystem status aggregator
# ═════════════════════════════════════════════════════════════════════════
class SubsystemStatus:
    """Tracks health of all subsystems for UI display."""

    def __init__(self):
        self._status = {}

    def update(self, name, healthy, detail=""):
        self._status[name] = {"healthy": healthy, "detail": detail,
                              "ts": time.time()}

    def get(self, name):
        return self._status.get(name, {"healthy": False, "detail": "unknown",
                                       "ts": 0})

    def all_healthy(self):
        return all(s["healthy"] for s in self._status.values())

    def summary(self):
        """One-line status string for UI."""
        parts = []
        for name, info in sorted(self._status.items()):
            icon = "OK" if info["healthy"] else "ERR"
            parts.append("%s:%s" % (name, icon))
        return " | ".join(parts)

    @property
    def subsystems(self):
        return dict(self._status)


# ═════════════════════════════════════════════════════════════════════════
# Phase 4 — Harsh braking event log
# ═════════════════════════════════════════════════════════════════════════
class HarshBrakeLog:
    """Records harsh braking events with timestamps and location."""

    def __init__(self, log_dir):
        self._dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._path = os.path.join(log_dir, "harsh_brake_log.jsonl")
        self._events = []

    def record(self, g_dyn, lat, lon, speed_kmh):
        """Record a harsh braking event."""
        event = {
            "ts": datetime.now().isoformat(),
            "g_dyn": round(g_dyn, 3),
            "lat": lat, "lon": lon,
            "speed_kmh": round(speed_kmh, 1),
        }
        self._events.append(event)
        try:
            with open(self._path, "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass
        return event

    def recent(self, n=10):
        """Return last N events."""
        return self._events[-n:]

    @property
    def count(self):
        return len(self._events)

    @property
    def path(self):
        return self._path


SentinelPreview = None
if Preview is not None:
    class _SentinelPreview(Preview):
        _analytics = None
        _frame_buffer = None
        _watchdog = None

        def __init__(self, **kw):
            super().__init__(**kw)
            # camera4kivy recomputes the view only in on_size. When layout
            # moves the widget without resizing it, the camera image stayed
            # at the old position (drawn below the box, over the form).
            inner = getattr(self, "preview", None)
            if inner is not None and hasattr(inner, "on_size"):
                inner.bind(pos=lambda w, _p: w.on_size(w, w.size))

        def analyze_pixels_callback(self, pixels, image_size, image_pos, scale, mirror):
            if self._watchdog:
                self._watchdog.frame_received()
            # "is not None": FrameRingBuffer defines __len__, so an empty buffer
            # is falsy and a plain truth test would never push the first frame.
            if self._frame_buffer is not None:
                self._frame_buffer.push(time.time(), bytes(pixels), image_size)
            elif self._analytics:
                self._analytics.analyze_frame(pixels, image_size)

        _plate_ocr = None

        def canvas_instructions_callback(self, texture, tex_size, tex_pos):
            """Outline the detected plate on the live preview (runs inside
            the preview's canvas each frame). Amber = seen once, green =
            confirmed by voting and used for auto-fill."""
            b = self._plate_ocr.box() if self._plate_ocr else None
            if not b:
                return
            x, y, w, h, fw, fh, _ts, confirmed = b
            sx, sy = tex_size[0] / float(fw), tex_size[1] / float(fh)
            Color(*((0, 0.9, 0.46, 1) if confirmed else (1, 0.84, 0.25, 1)))
            # Analysis pixels are top-down; Kivy's y axis points up.
            Line(rectangle=(tex_pos[0] + x * sx, tex_pos[1] + (fh - y - h) * sy,
                            w * sx, h * sy), width=dp(1.6))
    SentinelPreview = _SentinelPreview


KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp
#:import C kivy.utils.get_color_from_hex
#:import I18N civic.I18N

# ─── Color Palette ───────────────────────────────────────────────────────
# bg_primary:     #0B0E17   deep space navy
# bg_card:        #141929   card surfaces
# bg_card_alt:    #1A2035   elevated card
# accent_cyan:    #00E5FF   primary accent
# accent_green:   #00E676   success / send
# accent_amber:   #FFD740   warning / penalty
# accent_red:     #FF5252   error / alert
# text_primary:   #E8EAF0   main text
# text_secondary: #8892A8   muted text
# border:         #253050   subtle borders

# ─── Reusable Card Widget ────────────────────────────────────────────────
<Card@BoxLayout>:
    orientation: "vertical"
    size_hint_y: None
    # Fit content exactly; hand-tuned heights drifted from the children and
    # either overflowed (Settings) or left a gap above the title.
    height: self.minimum_height
    padding: dp(12), dp(8)
    spacing: dp(4)
    canvas.before:
        Color:
            rgba: C("#141929")
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]
        Color:
            rgba: C("#253050")
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(12))
            width: 0.8

# ─── Styled Toggle Row ──────────────────────────────────────────────────
<ToggleRow@BoxLayout>:
    size_hint_y: None
    height: dp(36)
    padding: dp(4), 0

# ─── Section Header Label ───────────────────────────────────────────────
# Translated text: render with the current language's Noto font + script
<TrLabel@Label>:
    font_name: app.ui_font
    font_script_name: app.ui_script

<SectionLabel@Label>:
    font_name: app.ui_font
    font_script_name: app.ui_script
    size_hint_y: None
    height: dp(22)
    font_size: "11sp"
    bold: True
    color: C("#00E5FF")
    halign: "left"
    valign: "middle"
    text_size: self.size

# ─── Styled Text Input ──────────────────────────────────────────────────
# The fill uses TextInput's own background (flat image + tint) and the border
# goes in canvas.after. Drawing them in canvas.before appends AFTER the base
# TextInput instructions, which tinted the typed text with the border colour
# and painted the fill over the cursor.
<StyledInput@TextInput>:
    background_normal: ""
    background_active: ""
    background_color: C("#1A2035")
    foreground_color: C("#E8EAF0")
    cursor_color: C("#00E5FF")
    hint_text_color: (0.45, 0.5, 0.6, 0.7)
    padding: [dp(10), dp(8)]
    canvas.after:
        Color:
            rgba: C("#253050") if not self.focus else C("#00E5FF")
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(8))
            width: 1.2 if self.focus else 0.7

# ─── Styled Spinner ─────────────────────────────────────────────────────
<StyledSpinner@Spinner>:
    background_color: (0, 0, 0, 0)
    color: C("#E8EAF0")
    option_cls: "SpinnerOption"
    canvas.before:
        Color:
            rgba: C("#1A2035")
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(8)]
        Color:
            rgba: C("#253050")
        Line:
            rounded_rectangle: (self.x, self.y, self.width, self.height, dp(8))
            width: 0.7

# ─── Action Button ──────────────────────────────────────────────────────
<ActionBtn@Button>:
    font_name: app.ui_font
    font_script_name: app.ui_script
    background_normal: ""
    background_down: ""
    background_color: (0, 0, 0, 0)
    color: C("#E8EAF0")
    bold: True
    font_size: "14sp"
    size_hint_y: None
    height: dp(48)
    _bg: [0.2, 0.6, 0.9, 1]
    canvas.before:
        Color:
            rgba: self._bg if self.state == "normal" else [self._bg[0]*0.7, self._bg[1]*0.7, self._bg[2]*0.7, 1]
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]

# ═════════════════════════════════════════════════════════════════════════
# ROOT LAYOUT
# ═════════════════════════════════════════════════════════════════════════
<RootUI>:
    orientation: "vertical"
    padding: 0
    spacing: 0
    canvas.before:
        Color:
            rgba: C("#0B0E17")
        Rectangle:
            pos: self.pos
            size: self.size

    # ── Header Bar ───────────────────────────────────────────────────────
    BoxLayout:
        size_hint_y: None
        height: dp(48)
        padding: dp(14), dp(8)
        canvas.before:
            Color:
                rgba: C("#0D1120")
            Rectangle:
                pos: self.pos
                size: self.size
            # Bottom accent line
            Color:
                rgba: C("#00E5FF")
            Rectangle:
                pos: self.pos
                size: (self.width, dp(1.5))
        Label:
            text: "SENTINEL-X"
            font_size: "18sp"
            bold: True
            color: C("#00E5FF")
            halign: "left"
            valign: "middle"
            text_size: self.size
            size_hint_x: 0.40
        Button:
            text: I18N.tr("MORE", app.lang)
            font_name: app.ui_font
            font_script_name: app.ui_script
            size_hint_x: 0.30
            font_size: "11sp"
            bold: True
            color: C("#FFD740")
            background_normal: ""
            background_down: ""
            background_color: (0, 0, 0, 0)
            on_release: root.show_more_menu()
            canvas.before:
                Color:
                    rgba: C("#1A2035")
                RoundedRectangle:
                    pos: (self.x + dp(4), self.y + dp(4))
                    size: (self.width - dp(8), self.height - dp(8))
                    radius: [dp(8)]
        Button:
            text: I18N.tr("HISTORY", app.lang)
            font_name: app.ui_font
            font_script_name: app.ui_script
            size_hint_x: 0.30
            font_size: "11sp"
            bold: True
            color: C("#00E5FF")
            background_normal: ""
            background_down: ""
            background_color: (0, 0, 0, 0)
            on_release: root.show_history()
            canvas.before:
                Color:
                    rgba: C("#1A2035")
                RoundedRectangle:
                    pos: (self.x + dp(4), self.y + dp(4))
                    size: (self.width - dp(8), self.height - dp(8))
                    radius: [dp(8)]
                Color:
                    rgba: C("#253050")
                Line:
                    rounded_rectangle: (self.x + dp(4), self.y + dp(4), self.width - dp(8), self.height - dp(8), dp(8))
                    width: 0.8

    # ── Camera Viewport ──────────────────────────────────────────────────
    BoxLayout:
        id: camera_box
        size_hint_y: None
        # Exactly fits the full-width 4:3 landscape preview (plates are wide);
        # capped when the phone itself is rotated so header + status + action
        # bar (148dp) still leave a scrollable strip of the form visible.
        height: min((self.width - dp(20)) * 0.75 + dp(12), max(root.height * 0.45, root.height - dp(300)))
        padding: dp(10), dp(6)
        canvas.before:
            Color:
                rgba: C("#050810")
            Rectangle:
                pos: self.pos
                size: self.size
            # Subtle inner border
            Color:
                rgba: C("#1A2035")
            Line:
                rectangle: (self.x + dp(9), self.y + dp(5), self.width - dp(18), self.height - dp(10))
                width: 0.8

    # ── Telemetry Strip ──────────────────────────────────────────────────
    BoxLayout:
        size_hint_y: None
        height: dp(38)
        padding: dp(12), dp(2)
        canvas.before:
            Color:
                rgba: C("#0D1120")
            Rectangle:
                pos: self.pos
                size: self.size
        Label:
            text: root.status_text
            font_size: "9sp"
            color: C("#5A8CC8")
            halign: "left"
            valign: "middle"
            text_size: self.size
            markup: True
            size_hint_x: 0.68
        Label:
            text: root.alert_text
            font_size: "10sp"
            bold: True
            color: C("#FF5252")
            halign: "right"
            valign: "middle"
            text_size: self.size
            size_hint_x: 0.32

    # ── Scrollable Content ───────────────────────────────────────────────
    ScrollView:
        do_scroll_x: False
        bar_color: C("#00E5FF")
        bar_inactive_color: C("#253050")
        bar_width: dp(3)

        BoxLayout:
            orientation: "vertical"
            size_hint_y: None
            height: self.minimum_height
            padding: dp(10), dp(6)
            spacing: dp(8)

            # ── OCR Detection Card ───────────────────────────────────────
            Card:
                Label:
                    id: lbl_ocr_suggest
                    size_hint_y: None
                    height: dp(16) if not root.ocr_suggest_text else dp(32)
                    text: root.ocr_suggest_text if root.ocr_suggest_text else I18N.tr("Plate OCR: standby", app.lang)
                    font_name: "Roboto" if root.ocr_suggest_text else app.ui_font
                    font_script_name: "Zyyy" if root.ocr_suggest_text else app.ui_script
                    font_size: "11sp"
                    color: C("#00E676") if root.ocr_suggest_text else C("#4A5270")
                    halign: "left"
                    valign: "middle"
                    text_size: self.size
                # Candidate chips: shown when several plates were read
                # recently; tap one to put it in the Plate field.
                BoxLayout:
                    id: ocr_chips
                    size_hint_y: None
                    height: dp(34) if self.children else 0
                    spacing: dp(6)

            # ── Settings Card ────────────────────────────────────────────
            Card:

                SectionLabel:
                    text: I18N.tr("SETTINGS", app.lang)

                ToggleRow:
                    TrLabel:
                        text: I18N.tr("Anonymous Reporter", app.lang)
                        font_size: "13sp"
                        color: C("#C8CDDA")
                        halign: "left"
                        valign: "middle"
                        text_size: self.size
                        size_hint_x: 0.65
                    Switch:
                        id: sw_anon
                        active: True
                        size_hint_x: 0.35

                ToggleRow:
                    TrLabel:
                        text: I18N.tr("Night Mode", app.lang)
                        font_size: "13sp"
                        color: C("#C8CDDA")
                        halign: "left"
                        valign: "middle"
                        text_size: self.size
                        size_hint_x: 0.65
                    Switch:
                        id: sw_clahe
                        active: False
                        size_hint_x: 0.35

                ToggleRow:
                    TrLabel:
                        text: I18N.tr("CV Assist", app.lang)
                        font_size: "13sp"
                        color: C("#C8CDDA")
                        halign: "left"
                        valign: "middle"
                        text_size: self.size
                        size_hint_x: 0.65
                    Switch:
                        id: sw_cv
                        active: True
                        size_hint_x: 0.35

                ToggleRow:
                    TrLabel:
                        text: I18N.tr("Plate OCR", app.lang)
                        font_size: "13sp"
                        color: C("#C8CDDA")
                        halign: "left"
                        valign: "middle"
                        text_size: self.size
                        size_hint_x: 0.65
                    Switch:
                        id: sw_ocr
                        active: True
                        size_hint_x: 0.35

            # ── Report Form Card ─────────────────────────────────────────
            Card:

                SectionLabel:
                    text: I18N.tr("VIOLATION REPORT", app.lang)

                # Plate input
                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(8)
                    TrLabel:
                        text: I18N.tr("Plate", app.lang)
                        size_hint_x: 0.18
                        font_size: "13sp"
                        bold: True
                        color: C("#00E5FF")
                        halign: "left"
                        valign: "middle"
                        text_size: self.size
                    StyledInput:
                        id: in_plate
                        size_hint_x: 0.82
                        multiline: False
                        hint_text: "MH12AB1234"
                        font_size: "15sp"

                # Offense spinner
                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(8)
                    TrLabel:
                        text: I18N.tr("Offense", app.lang)
                        size_hint_x: 0.18
                        font_size: "13sp"
                        bold: True
                        color: C("#00E5FF")
                        halign: "left"
                        valign: "middle"
                        text_size: self.size
                    StyledSpinner:
                        id: sp_offense
                        size_hint_x: 0.82
                        text: "Select violation..."
                        values: []
                        font_size: "12sp"
                        on_text: root.on_offense_selected(self.text)

                # Section + Penalty display
                Label:
                    size_hint_y: None
                    height: dp(26)
                    text: root.section_penalty
                    font_size: "11sp"
                    color: C("#FFD740")
                    halign: "left"
                    valign: "middle"
                    text_size: self.size
                    padding: dp(4), 0

                # Sign selectors
                BoxLayout:
                    size_hint_y: None
                    height: dp(40)
                    spacing: dp(6)
                    TrLabel:
                        text: I18N.tr("Sign", app.lang)
                        size_hint_x: 0.18
                        font_size: "13sp"
                        color: C("#8892A8")
                        halign: "left"
                        valign: "middle"
                        text_size: self.size
                    StyledSpinner:
                        id: sp_sign_group
                        size_hint_x: 0.41
                        text: "Group"
                        values: []
                        font_size: "11sp"
                        on_text: root.on_sign_group(self.text)
                    StyledSpinner:
                        id: sp_sign
                        size_hint_x: 0.41
                        text: "Sign"
                        values: []
                        font_size: "11sp"

                # Notes
                BoxLayout:
                    size_hint_y: None
                    height: dp(62)
                    spacing: dp(8)
                    TrLabel:
                        text: I18N.tr("Notes", app.lang)
                        size_hint_x: 0.18
                        font_size: "13sp"
                        color: C("#8892A8")
                        halign: "left"
                        valign: "top"
                        text_size: self.size
                    StyledInput:
                        id: in_notes
                        size_hint_x: 0.82
                        hint_text: "Additional details..."
                        multiline: True
                        font_size: "13sp"

                # Evidence status
                Label:
                    size_hint_y: None
                    height: dp(20)
                    text: root.evidence_status
                    font_size: "10sp"
                    color: C("#00E5FF")
                    halign: "left"
                    valign: "middle"
                    text_size: self.size
                    padding: dp(4), 0

            # ── Routing Card ─────────────────────────────────────────────
            Card:

                SectionLabel:
                    text: I18N.tr("JURISDICTION ROUTING", app.lang)

                Label:
                    size_hint_y: None
                    height: dp(32)
                    text: root.route_text
                    font_size: "11sp"
                    color: C("#00E676")
                    halign: "left"
                    valign: "middle"
                    text_size: self.size
                    markup: True

            # Bottom spacer for scroll
            Widget:
                size_hint_y: None
                height: dp(4)

    # ── Action Bar ───────────────────────────────────────────────────────
    BoxLayout:
        size_hint_y: None
        height: dp(62)
        padding: dp(10), dp(7)
        spacing: dp(8)
        canvas.before:
            Color:
                rgba: C("#0D1120")
            Rectangle:
                pos: self.pos
                size: self.size
            # Top accent line
            Color:
                rgba: C("#1A2035")
            Rectangle:
                pos: (self.x, self.top - dp(1))
                size: (self.width, dp(1))

        ActionBtn:
            text: I18N.tr("SCAN", app.lang)
            _bg: C("#7C3AED")
            on_release: root.scan_now()

        ActionBtn:
            text: I18N.tr("CAPTURE", app.lang)
            _bg: C("#0078D4")
            on_release: root.capture_evidence()

        ActionBtn:
            text: I18N.tr("SEND", app.lang)
            _bg: C("#00C853")
            on_release: root.send_report()

        ActionBtn:
            text: I18N.tr("CLEAR", app.lang)
            _bg: C("#37474F")
            on_release: root.clear_form()
"""


class RootUI(BoxLayout):
    status_text = StringProperty("Waiting for GPS...")
    section_penalty = StringProperty(DASH)
    route_text = StringProperty(DASH)
    evidence_status = StringProperty("")
    ocr_suggest_text = StringProperty("")
    alert_text = StringProperty("")
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
        self._analytics = AnalyticsEngine()
        self._gps = None
        self._frame_buffer = None
        self._analysis_worker = None
        self._watchdog = None
        self._dashcam = None
        self._telemetry = None
        self._service_cls = None  # p4a ServiceService class, for stop()
        # Phase 2
        self._report_log = None
        # Phase 3
        self._offline_queue = None
        self._queue_retry = None
        # Phase 4
        self._onnx = None
        self._speed_zones = SpeedZoneChecker()
        self._subsystem_status = SubsystemStatus()
        self._harsh_brake_log = None
        self._last_harsh_brake_ts = 0
        # Phase 5
        self._plate_ocr = None
        self._ocr_accepted_plate = ""
        # Phase 6 — citizen features
        self._privacy_blur = False
        self._dup_ack = False
        self._evidence_uri = None  # MediaStore copy of the last capture
        Clock.schedule_once(self._boot, 0)

    def _get_evidence_folder(self):
        """App-private working folder for evidence, logs, queue and dashcam.

        Shared Pictures/ can't be written with plain file I/O under scoped
        storage (targetSdk 33), and logs/queue JSON don't belong in a media
        folder anyway. Captured photos are additionally published to the
        gallery via MediaStore (see _publish_to_gallery).
        """
        try:
            base = App.get_running_app().user_data_dir
        except Exception:
            base = "."
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

    def _request_perms(self):
        if platform != "android" or request_permissions is None:
            self._after_perms()
            return

        def _cb(perms, results):
            Clock.schedule_once(lambda dt: self._after_perms(), 0.5)

        try:
            request_permissions([
                Permission.CAMERA,
                Permission.ACCESS_FINE_LOCATION,
                Permission.ACCESS_COARSE_LOCATION,
                Permission.WRITE_EXTERNAL_STORAGE,
                Permission.READ_EXTERNAL_STORAGE,
            ], _cb)
        except Exception:
            Clock.schedule_once(lambda dt: self._after_perms(), 1.5)

    def _after_perms(self):
        """Called AFTER permissions granted. Start everything here."""
        self._setup_camera()
        # GPS via direct Android API
        self._gps = AndroidGPS()
        # Accelerometer
        if plyer_accel:
            try:
                plyer_accel.enable()
            except Exception:
                pass
        # Phase 1: Frame buffer + threaded analysis
        self._frame_buffer = FrameRingBuffer(max_frames=20)
        self._analysis_worker = FrameAnalysisWorker(
            self._frame_buffer, self._analytics
        )
        if self._preview:
            self._preview._frame_buffer = self._frame_buffer
        self._analysis_worker.start()
        # Phase 1: Dashcam recorder
        edir = self._get_evidence_folder()
        self._dashcam = DashcamRecorder(self._frame_buffer, edir)
        self._dashcam.start()
        # Phase 1: Telemetry receiver (service.py UDP)
        self._telemetry = TelemetryReceiver()
        self._telemetry.start()
        # Phase 1: Start background service on Android
        if platform == "android" and autoclass is not None:
            try:
                mActivity = autoclass("org.kivy.android.PythonActivity").mActivity
                # Derive the service class from the real package name. buildozer
                # builds it as "<package.domain>.<package.name>.ServiceService"
                # (here org.sentinelx.sentinelx.ServiceService), so hardcoding
                # "org.sentinelx.ServiceService" silently fails to start it.
                pkg = mActivity.getPackageName()
                svc = None
                for cls in (pkg + ".ServiceService", "org.sentinelx.ServiceService"):
                    try:
                        svc = autoclass(cls)
                        break
                    except Exception:
                        continue
                if svc is not None:
                    svc.start(mActivity, "")
                    self._service_cls = svc
            except Exception:
                pass
        # Phase 2: Report log
        self._report_log = ReportLog(edir)
        # Phase 3: Offline queue + retry daemon
        queue_dir = os.path.join(edir, "queue")
        self._offline_queue = OfflineReportQueue(queue_dir)
        self._queue_retry = QueueRetryDaemon(
            self._offline_queue, self._send_queued_report
        )
        self._queue_retry.start()
        # Phase 4: ONNX detector (optional)
        try:
            base = App.get_running_app().user_data_dir
        except Exception:
            base = "."
        models_dir = os.path.join(base, "models")
        self._onnx = ONNXDetector(models_dir)
        # Phase 4: Harsh braking event log
        self._harsh_brake_log = HarshBrakeLog(edir)
        # Phase 5: Plate OCR
        self._plate_ocr = PlateOCR()
        self._analytics.set_plate_ocr(self._plate_ocr)
        if self._preview is not None:
            self._preview._plate_ocr = self._plate_ocr
        # Phase 6: load VAHAN (Masters India) credentials from vahan.json if present
        self._load_vahan_config()
        # Police directory: apply the last downloaded copy, then refresh it
        self._load_directory_updates()
        # Polling loops
        Clock.schedule_interval(self._poll_gps, 1.0)
        Clock.schedule_interval(self._poll_accel, 0.1)
        Clock.schedule_interval(self._tick_ui, 1.0)
        # Phase 6: silent update check shortly after launch (Play or GitHub OTA)
        Clock.schedule_once(lambda _dt: self._auto_update_check(False), 4.0)
        # Remind about week-old reports that may need escalation
        Clock.schedule_once(lambda _dt: self._check_followups(), 8.0)

    def _load_directory_updates(self):
        """Apply the cached police directory, then fetch the latest one
        published with the newest release (validated before use)."""
        try:
            path = os.path.join(App.get_running_app().user_data_dir, "directory.json")
        except Exception:
            return
        try:
            if os.path.isfile(path):
                with open(path, "r") as f:
                    CivicDirectory.apply_overrides(json.load(f))
        except Exception:
            pass

        def fetch():
            try:
                import urllib.request
                with urllib.request.urlopen(CivicDirectory.DIRECTORY_URL, timeout=10) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                if CivicDirectory.apply_overrides(data):
                    tmp = path + ".tmp"
                    with open(tmp, "w") as f:
                        json.dump(data, f)
                    os.replace(tmp, path)
            except Exception:
                pass  # offline / no release yet: keep the built-in copy
        threading.Thread(target=fetch, daemon=True).start()

    def _load_vahan_config(self):
        """Load Masters India VAHAN credentials from <data dir>/vahan.json."""
        try:
            base = App.get_running_app().user_data_dir
        except Exception:
            base = "."
        for path in (os.path.join(base, "vahan.json"), "vahan.json"):
            try:
                if os.path.isfile(path):
                    with open(path, "r") as f:
                        cfg = json.load(f)
                    VehicleLookup.set_credentials(
                        jwt=cfg.get("jwt"), subid=cfg.get("subid"),
                        productid=cfg.get("productid"), mode=cfg.get("mode"),
                        url=cfg.get("url"))
                    if cfg.get("endpoint"):
                        VehicleLookup.set_endpoint(cfg.get("endpoint"))
                    break
            except Exception:
                pass

    # ── GPS polling (prefer service telemetry, fallback to pyjnius) ─────
    def _poll_gps(self, _dt):
        t = self._telemetry.latest if self._telemetry else {}
        if t.get("lat", 0) != 0 and t.get("lon", 0) != 0:
            self.latest_lat = t["lat"]
            self.latest_lon = t["lon"]
            if t.get("speed_mps", 0) > 0:
                self.latest_speed = t["speed_mps"]
            return
        # Fallback to direct GPS
        if self._gps is None:
            return
        lat, lon, speed = self._gps.get_location()
        if lat != 0 and lon != 0:
            self.latest_lat = lat
            self.latest_lon = lon
        if speed > 0:
            self.latest_speed = speed

    # ── Accelerometer polling (prefer service telemetry) ──────────────
    def _poll_accel(self, _dt):
        t = self._telemetry.latest if self._telemetry else {}
        # Only trust the service's g_dyn when it reports a live sensor; older
        # service builds sent a constant (0, 0, 9.81) fallback (g_dyn == 0).
        if t.get("accel_ok") and "g_dyn" in t:
            self.latest_g = t["g_dyn"]
        else:
            # Fallback to direct plyer
            if plyer_accel is None:
                return
            try:
                val = plyer_accel.acceleration
                if val and None not in val[:3]:
                    x, y, z = float(val[0]), float(val[1]), float(val[2])
                    g_total = math.sqrt(x * x + y * y + z * z)
                    self.latest_g = abs(g_total - 9.81)
            except Exception:
                pass
        self._check_crash()
        # Phase 4: Record harsh braking events (debounce 5s)
        now = time.time()
        if (self.latest_g > 4.0 and self._harsh_brake_log and
                now - self._last_harsh_brake_ts > 5.0):
            self._harsh_brake_log.record(
                self.latest_g, float(self.latest_lat),
                float(self.latest_lon), self.latest_speed * 3.6
            )
            self._last_harsh_brake_ts = now
            # On-screen alert, auto-clears after 4s
            self.alert_text = "HARSH BRAKE %.1f" % self.latest_g
            def _clear_alert(dt, ts=now):
                if self._last_harsh_brake_ts == ts:
                    self.alert_text = ""
            Clock.schedule_once(_clear_alert, 4.0)

    # ── Camera ───────────────────────────────────────────────────────────
    def _setup_camera(self):
        self.ids.camera_box.clear_widgets()
        if SentinelPreview is None:
            self.ids.camera_box.add_widget(Label(
                text="Camera unavailable", font_size="13sp",
                color=(0.35, 0.4, 0.52, 1),
            ))
            return
        try:
            # Landscape 4:3 view across the full width: a portrait preview in a
            # wide box was a narrow strip with black bars, too small to frame
            # a whole number plate.
            self._preview = SentinelPreview(aspect_ratio="4:3",
                                            orientation="landscape")
            self._preview._analytics = self._analytics
            self.ids.camera_box.add_widget(self._preview)
            Clock.schedule_once(lambda dt: self._connect_cam(), 0.5)
        except Exception:
            self.ids.camera_box.add_widget(Label(
                text="Camera initialization failed", font_size="13sp",
                color=(1, 0.32, 0.32, 1),
            ))

    def _connect_cam(self):
        if not self._preview:
            return
        try:
            kw = {"enable_analyze_pixels": True, "analyze_pixels_resolution": 800}
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
        # Phase 1: Start watchdog after camera connects
        # Reuse the existing watchdog across reconnects so its exponential
        # backoff state survives (a fresh one would always restart at 2s).
        if self._cam_ok and self._watchdog is None:
            self._watchdog = CameraWatchdog(self._reconnect_camera)
            self._preview._watchdog = self._watchdog
            self._watchdog.start()

    def _reconnect_camera(self):
        """Called by CameraWatchdog to recover from stalls."""
        if not self._preview:
            return
        try:
            self._preview.disconnect_camera()
        except Exception:
            pass
        Clock.schedule_once(lambda dt: self._connect_cam(), 0.5)

    # ── Capture: export_to_png (always works) ────────────────────────────
    def capture_evidence(self):
        if not self._preview or not self._cam_ok:
            self._popup("Not ready", "Camera not connected.")
            return

        edir = self._get_evidence_folder()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = "SentinelX_%s.png" % ts
        fpath = os.path.join(edir, fname)

        try:
            # export_to_png grabs current frame from the preview texture
            self._preview.export_to_png(fpath)

            if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
                # Apply CLAHE if enabled
                if self.ids.sw_clahe.active and cv2:
                    try:
                        img = cv2.imread(fpath)
                        if img is not None:
                            enhanced = AnalyticsEngine.clahe(img)
                            cv2.imwrite(fpath, enhanced)
                    except Exception:
                        pass

                # Phase 6: Optional privacy blur of bystander faces (opt-in via
                # MORE menu; off by default because a rider's head can itself be
                # evidence of a helmet/phone violation).
                if getattr(self, "_privacy_blur", False) and cv2:
                    try:
                        img = cv2.imread(fpath)
                        if img is not None:
                            cv2.imwrite(fpath, PrivacyBlur.blur_faces(img))
                    except Exception:
                        pass

                # Phase 2: Watermark evidence with metadata
                plate = self.ids.in_plate.text.strip()
                EvidenceWatermark.apply(
                    fpath, float(self.latest_lat), float(self.latest_lon),
                    ts, plate
                )
                # Phase 2: Hash evidence for tamper detection
                EvidenceHasher.write_hashfile(fpath)
                # Signed provenance record (hardware-backed key)
                self._write_proof(fpath)
                self.evidence_path = fpath
                self.evidence_status = "Evidence: %s" % fname
                # Publish a byte-identical copy to the gallery (MediaStore);
                # its content:// URI is also what SEND attaches to the email.
                self._evidence_uri = self._publish_to_gallery(fpath)
                where = ("Pictures/SentinelX/%s" % fname if self._evidence_uri
                         else fname)
                self._popup("Saved!", "Photo saved to:\n%s" % where)
                # Auto-dismiss evidence notification after 5 seconds
                _fname = fname  # capture for closure
                def _dismiss(dt, fn=_fname):
                    if self.evidence_status.endswith(fn):
                        self.evidence_status = ""
                Clock.schedule_once(_dismiss, 5.0)

                # Phase 5: OCR the full-resolution evidence and auto-fill the
                # plate if the user has not entered one. Runs on a background
                # thread (ML Kit must not block the UI thread).
                if (not self.ids.in_plate.text.strip()
                        and self._plate_ocr and self._plate_ocr.available):
                    threading.Thread(
                        target=self._ocr_image_worker,
                        args=(fpath, False), daemon=True,
                    ).start()
            else:
                self._popup("Failed", "File was not created.")
        except Exception as e:
            self._popup("Capture Error", str(e))

    # ── On-demand full-resolution scan ───────────────────────────────────
    def scan_now(self):
        """Capture a full-resolution frame and OCR it on demand."""
        if not self._preview or not self._cam_ok:
            self._popup("Not ready", "Camera not connected.")
            return
        if not self._plate_ocr or not self._plate_ocr.available:
            self._popup(
                "OCR unavailable",
                "No text recognition engine on this device.\n"
                "Enter the plate manually.",
            )
            return
        self.ocr_suggest_text = "OCR: scanning (full-res)..."
        try:
            tmp = os.path.join(self._get_evidence_folder(), ".scan_tmp.png")
            self._preview.export_to_png(tmp)
        except Exception as e:
            self._popup("Scan failed", str(e))
            return
        threading.Thread(
            target=self._ocr_image_worker, args=(tmp, True), daemon=True
        ).start()

    def _ocr_image_worker(self, path, announce):
        """Background OCR of a saved image; applies result on the UI thread."""
        plate, conf = "", 0.0
        try:
            if cv2 is not None and os.path.isfile(path):
                img = cv2.imread(path)
                if img is not None:
                    plate, conf = self._plate_ocr.process_image(img)
        except Exception:
            pass
        if announce:
            try:
                if path.endswith(".scan_tmp.png"):
                    os.remove(path)
            except Exception:
                pass
        Clock.schedule_once(
            lambda dt: self._apply_ocr_result(plate, conf, announce)
        )

    def _apply_ocr_result(self, plate, conf, announce):
        """Apply an OCR result: auto-fill plate + show routing (UI thread)."""
        if plate and conf > 0.5:
            self.ids.in_plate.text = plate
            self._ocr_accepted_plate = plate
            if self._analytics:
                self._analytics.ocr_plate = plate
                self._analytics.ocr_confidence = conf
            lat, lon = float(self.latest_lat), float(self.latest_lon)
            sug = self._plate_ocr.suggest_routing(plate, lat, lon)
            emails = sug.get("emails", [])
            state = sug.get("state_code", "") or "?"
            self.ocr_suggest_text = "OCR: %s [%s] %.0f%%%s" % (
                plate, state, conf * 100,
                (" -> " + ", ".join(emails[:2])) if emails else " (no route)",
            )
            if announce:
                self._popup(
                    "Plate Read",
                    "Detected: %s\nState: %s\nConfidence: %.0f%%" % (
                        plate, state, conf * 100),
                )
        elif announce:
            self.ocr_suggest_text = "OCR: no readable plate"
            self._popup(
                "Scan",
                "No readable plate found.\nMove closer and hold steady.",
            )

    def _write_proof(self, path):
        """Sign a provenance record for a captured photo (see EvidenceProof)."""
        fix = {}
        if self._gps is not None:
            self._gps.get_location()  # refresh accuracy / fix time
            fix = self._gps.last_fix
        device = ""
        if platform == "android" and autoclass is not None:
            try:
                Build = autoclass("android.os.Build")
                device = "%s %s" % (Build.MANUFACTURER, Build.MODEL)
            except Exception:
                pass
        payload = EvidenceProof.build_payload(
            path, EvidenceHasher.hash_file(path), self.latest_lat,
            self.latest_lon, fix, device, APP_VERSION)
        return EvidenceProof.write(path, payload)

    def _publish_to_gallery(self, path, folder="Pictures/SentinelX",
                            mime="image/png"):
        """Copy an evidence file into a shared folder via MediaStore.

        Returns the content:// Uri (Java object), or None off-device / on
        failure. Bytes are copied verbatim so the .sha256 sidecar still
        matches the gallery copy.
        """
        if platform != "android" or autoclass is None:
            return None
        out = None
        try:
            Media = autoclass("android.provider.MediaStore$Video$Media"
                              if mime.startswith("video/")
                              else "android.provider.MediaStore$Images$Media")
            Cols = autoclass("android.provider.MediaStore$MediaColumns")
            ContentValues = autoclass("android.content.ContentValues")
            Version = autoclass("android.os.Build$VERSION")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            cr = act.getContentResolver()
            cv = ContentValues()
            cv.put(Cols.DISPLAY_NAME, os.path.basename(path))
            cv.put(Cols.MIME_TYPE, mime)
            if Version.SDK_INT >= 29:
                cv.put(Cols.RELATIVE_PATH, folder)
            uri = cr.insert(Media.EXTERNAL_CONTENT_URI, cv)
            if uri is None:
                return None
            with open(path, "rb") as f:
                data = f.read()
            out = cr.openOutputStream(uri)
            out.write(data)
            return uri
        except Exception:
            return None
        finally:
            if out is not None:
                try:
                    out.close()
                except Exception:
                    pass

    def _send_email(self, to, subject, body, stream_uri=None):
        """Open an email composer pre-filled with recipients/subject/body.

        ACTION_SEND + a mailto: selector limits the chooser to email apps
        (plyer's text/plain share listed every app on the phone) while still
        allowing the evidence photo to be attached via EXTRA_STREAM.
        Returns True if a composer was launched.
        """
        if platform == "android" and autoclass is not None:
            try:
                from jnius import cast
                Intent = autoclass("android.content.Intent")
                Uri = autoclass("android.net.Uri")
                act = autoclass("org.kivy.android.PythonActivity").mActivity
                String = autoclass("java.lang.String")

                def chars(s):
                    # Bare str resolves to the wrong putExtra overload and
                    # mail apps then show an empty subject/body.
                    return cast("java.lang.CharSequence", String(s))

                i = Intent(Intent.ACTION_SEND)
                i.setSelector(Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:")))
                if to:
                    i.putExtra(Intent.EXTRA_EMAIL, list(to))
                i.putExtra(Intent.EXTRA_SUBJECT, chars(subject))
                i.putExtra(Intent.EXTRA_TEXT, chars(body))
                if stream_uri is not None:
                    ClipData = autoclass("android.content.ClipData")
                    i.putExtra(Intent.EXTRA_STREAM,
                               cast("android.os.Parcelable", stream_uri))
                    # ClipData carries the read grant through the chooser.
                    i.setClipData(ClipData.newRawUri("", stream_uri))
                    i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                chooser = Intent.createChooser(i, chars("Send report with:"))
                chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                act.startActivity(chooser)
                return True
            except Exception:
                pass
        if plyer_email is None:
            return False
        try:
            plyer_email.send(recipient=",".join(to) if to else None,
                             subject=subject, text=body, create_chooser=True)
            return True
        except Exception:
            return False

    # ── UI update ────────────────────────────────────────────────────────
    def _tick_ui(self, _dt):
        lat = float(self.latest_lat)
        lon = float(self.latest_lon)
        self.district, self.state_name = JurisdictionEngine.geo_detail(lat, lon)
        plate = self.ids.in_plate.text.strip()
        rt = JurisdictionEngine.route(lat, lon, plate)
        rcpts = ", ".join(rt["all"]) or DASH
        lc = rt["lc"] or DASH
        pc = rt["pc"] or DASH
        if rt.get("city"):
            lc = "%s (%s)" % (lc, rt["city"])
        self.route_text = "Loc:%s Plate:%s\n%s" % (lc, pc, rcpts)
        kmh = self.latest_speed * 3.6
        cv = self._analytics.result if self.ids.sw_cv.active else ""
        # Phase 4: Subsystem status updates
        if self._subsystem_status:
            self._subsystem_status.update("cam", self._cam_ok)
            self._subsystem_status.update("gps", lat != 0 or lon != 0)
            self._subsystem_status.update(
                "dashcam", bool(self._dashcam and self._dashcam.recording)
            )
            self._subsystem_status.update(
                "telemetry", bool(self._telemetry and self._telemetry.latest)
            )
            if self._offline_queue:
                qc = self._offline_queue.count
                self._subsystem_status.update(
                    "queue", qc == 0, "%d pending" % qc if qc else ""
                )
        # Phase 4: Speed zone check
        zone_warn = ""
        if self._speed_zones and kmh > 0:
            violations = self._speed_zones.check(lat, lon, kmh)
            if violations:
                zone_warn = " ZONE:%s@%dkm/h" % (
                    violations[0][0], violations[0][2]
                )
        # Phase 5: OCR auto-fill and routing suggestion
        ocr_active = self.ids.sw_ocr.active if hasattr(self.ids, "sw_ocr") else False
        if ocr_active and self._plate_ocr and self._analytics:
            ocr_plate = self._analytics.ocr_plate
            ocr_conf = self._analytics.ocr_confidence
            if ocr_plate and ocr_conf > 0.5:
                current_plate = self.ids.in_plate.text.strip()
                if not current_plate or current_plate == self._ocr_accepted_plate:
                    self.ids.in_plate.text = ocr_plate
                    self._ocr_accepted_plate = ocr_plate
                suggestion = self._plate_ocr.suggest_routing(
                    ocr_plate, lat, lon
                )
                emails = suggestion.get("emails", [])
                state = suggestion.get("state_code", "")
                if emails:
                    self.ocr_suggest_text = (
                        "OCR: %s [%s] %.0f%% -> %s"
                        % (ocr_plate, state, ocr_conf * 100,
                           ", ".join(emails[:2]))
                    )
                else:
                    self.ocr_suggest_text = (
                        "OCR: %s [%s] %.0f%% (no route)"
                        % (ocr_plate, state, ocr_conf * 100)
                    )
            elif not self.ocr_suggest_text.startswith("OCR: scanning (full"):
                # Don't clobber an in-flight on-demand scan message.
                if not self._plate_ocr.available:
                    self.ocr_suggest_text = (
                        "OCR: no engine - tap SCAN or enter plate manually"
                    )
                elif self._plate_ocr.region_found:
                    self.ocr_suggest_text = (
                        "OCR: plate in view - move closer / hold steady"
                    )
                else:
                    self.ocr_suggest_text = "OCR: scanning (%s)..." % (
                        self._plate_ocr.engine_name
                    )
        else:
            self.ocr_suggest_text = ""

        self._update_ocr_chips(ocr_active)

        # Phase 5: Update subsystem status for OCR
        if self._subsystem_status and self._plate_ocr:
            self._subsystem_status.update(
                "ocr", self._plate_ocr.available or not ocr_active,
                "plate:%s" % self._analytics.ocr_plate if self._analytics.ocr_plate else ""
            )

        status_suffix = self._subsystem_status.summary() if self._subsystem_status else ""
        # "You:" makes clear this is the phone's own speed, not a target's.
        self.status_text = "%.4f,%.4f | %s | You:%.0fkm/h | G:%.1f | %s%s\n%s" % (
            lat, lon, self.state_name or DASH, kmh, self.latest_g, cv,
            zone_warn, status_suffix
        )

    def _update_ocr_chips(self, ocr_active):
        """Show up to 3 recently read plates as tap targets when more than
        one plate is in view (e.g. a car behind the offender)."""
        cands = []
        if ocr_active and self._plate_ocr is not None:
            cands = self._plate_ocr.candidates[:3]
        if len(cands) < 2:
            cands = []
        if cands == getattr(self, "_chip_cache", []):
            return
        self._chip_cache = cands
        box = self.ids.ocr_chips
        box.clear_widgets()
        from kivy.uix.button import Button
        for p in cands:
            b = Button(text=p, font_size="12sp", bold=True,
                       color=(0.9, 0.93, 0.97, 1), background_normal="",
                       background_down="", background_color=(0.16, 0.2, 0.33, 1))
            b.bind(on_release=lambda _b, plate=p: self._pick_plate(plate))
            box.add_widget(b)

    def _pick_plate(self, plate):
        self.ids.in_plate.text = plate
        self._ocr_accepted_plate = plate

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
        self.ids.sp_offense.text = "Select violation..."
        self.ids.sp_sign_group.text = "Group"
        self.ids.sp_sign.text = "Sign"
        self.section_penalty = DASH
        self.route_text = DASH
        self.evidence_path = ""
        self._evidence_uri = None
        self.evidence_status = ""
        # Phase 5: Reset OCR state
        self._ocr_accepted_plate = ""
        self.ocr_suggest_text = ""
        if self._plate_ocr:
            self._plate_ocr.reset()
        if self._analytics:
            self._analytics.ocr_plate = ""
            self._analytics.ocr_confidence = 0.0

    def _location_text(self):
        """'District, State' without empty parts (the offline geocoder only
        resolves the state, which used to render as ', Haryana')."""
        parts = [p for p in (self.district, self.state_name) if p and p != DASH]
        return ", ".join(parts) or DASH

    def _sign_text(self):
        """Selected sign, or DASH while the spinners still show placeholders."""
        g, sg = self.ids.sp_sign_group.text, self.ids.sp_sign.text
        if g in TrafficLawDB.SIGN_GROUPS and sg != "Sign":
            return "%s / %s" % (g, sg)
        return DASH

    # ── Email ────────────────────────────────────────────────────────────
    def send_report(self):
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
            # Say why and where else to report, instead of a bare dead end:
            # a few states publish no police email at all.
            alts = [CivicDirectory.NO_EMAIL[c] for c in (rt["lc"], rt["pc"])
                    if c in CivicDirectory.NO_EMAIL]
            if alts:
                self._popup(
                    "No route",
                    "This state publishes no official police email.\n\n"
                    "Report via: %s\n\nOr: MORE > Share to X, or CPGRAMS (%s)."
                    % (alts[0], CivicDirectory.CPGRAMS_PORTAL), tall=True)
            else:
                self._popup("No route", "Unknown state code.")
            return

        # Phase 6: warn on near-duplicate (same plate+offense, close in time/space)
        if not getattr(self, "_dup_ack", False) and self._report_log:
            try:
                entries = self._report_log.read_all()
            except Exception:
                entries = []
            if DuplicateGuard.is_duplicate(entries, plate, okey, lat, lon):
                self._dup_ack = True
                self._popup(
                    "Duplicate",
                    "A matching report for %s was just filed nearby.\n"
                    "Tap SEND again to submit anyway." % plate,
                )
                return
        self._dup_ack = False

        o = TrafficLawDB.OFFENSES[okey]
        anon = bool(self.ids.sw_anon.active)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "SENTINEL-X CIVIC ENFORCEMENT REPORT",
            "Time: %s" % now, "",
            "GPS: %.6f, %.6f" % (lat, lon),
            # No speed/G-force here: those come from the reporter's own phone
            # (GPS + accelerometer), not the offending vehicle, and would read
            # as a measured speed of the reported car.
            "Location: %s" % self._location_text(), "",
            "Plate: %s" % plate,
            "Offense: %s - %s" % (okey, o["label"]),
            "Section: %s" % o["section"],
            "Penalty: %s" % o["penalty"], "",
        ]
        if okey.startswith("SPEEDING"):
            lines += [
                "Vehicle speed: not measured. Speeding is reported from the "
                "reporter's observation; please verify with speed-camera / "
                "ITMS records for this time and location.", "",
            ]
        lines += [
            "Sign: %s" % self._sign_text(), "",
            "Reporter: %s" % ("ANONYMOUS" if anon else "See contact"), "",
            "Notes: %s" % (self.ids.in_notes.text.strip() or DASH), "",
            "Routing: Loc=%s%s Plate=%s" % (
                rt["lc"] or DASH,
                " (%s)" % rt["city"] if rt.get("city") else "",
                rt["pc"] or DASH), "",
            TrafficLawDB.GOOD_SAMARITAN_FOOTER,
        ]
        subj = "[Sentinel-X] %s - %s" % (plate, o["label"])
        body = "\n".join(lines)
        to = rt["all"]

        # Phase 2: Build report record for logging
        report_record = {
            "plate": plate, "offense": okey, "section": o["section"],
            "lat": lat, "lon": lon,
            # The reporter's own motion at send time (local log only; never
            # put in the email).
            "reporter_speed_kmh": self.latest_speed * 3.6,
            "reporter_g_dyn": self.latest_g, "recipients": to, "subject": subj,
            "ts": time.time(),  # for duplicate detection
            "evidence": self.evidence_path,
            "evidence_hash": EvidenceHasher.hash_file(self.evidence_path) if self.evidence_path else "",
        }

        if self._send_email(to, subj, body, getattr(self, "_evidence_uri", None)):
            # Phase 2: Log the report (composer opened with it pre-filled)
            if self._report_log:
                report_record["status"] = "sent"
                self._report_log.append(report_record)
            self._popup("Ready", "Email app opened." + (
                "\nEvidence photo attached." if getattr(self, "_evidence_uri", None)
                else ""))
        elif self._offline_queue:
            # Phase 3: Queue for retry when no composer could be launched
            report_record["body"] = body
            self._offline_queue.enqueue(report_record)
            self._popup("Queued", "Could not open an email app.\nReport queued for retry.")
        else:
            self._popup("Failed", "No email app available.")

    # ── Phase 3: Queued report sender callback ──────────────────────────
    def _send_queued_report(self, report):
        """Attempt to send a queued report. Returns True on success."""
        try:
            to = report.get("recipients", [])
            subj = report.get("subject", "Sentinel-X Report")
            body = report.get("body", "")
            if not to or not body:
                return False
            if not self._send_email(to, subj, body):
                return False
            # Log the sent report
            if self._report_log:
                report["status"] = "sent_from_queue"
                self._report_log.append(report)
            return True
        except Exception:
            return False

    # ── Report history viewer ────────────────────────────────────────────
    def show_history(self):
        """Show the last 10 sent reports from the report log."""
        entries = self._report_log.read_all() if self._report_log else []
        if not entries:
            self._popup("History", "No reports sent yet.")
            return
        lines = []
        for e in entries[-10:][::-1]:
            ts = (e.get("logged_at", "") or "")[:16].replace("T", " ")
            lines.append("%s\n  %s | %s | %s" % (
                ts or DASH,
                e.get("plate", DASH) or DASH,
                e.get("offense", DASH) or DASH,
                e.get("status", DASH) or DASH,
            ))
        title = "%s (%d/%d)" % (I18N.tr("History"), min(len(entries), 10), len(entries))
        self._popup(title, "\n\n".join(lines), tall=True)

    # ═════════════════════════════════════════════════════════════════════
    # Phase 6 — citizen features (menu + handlers)
    # ═════════════════════════════════════════════════════════════════════
    @staticmethod
    def _tr_font(text):
        """(translated text, font kwargs). Text that still contains Latin
        letters (plates, emails, untranslated strings) keeps the Latin font,
        because the Indic Noto fonts have no Latin glyphs."""
        t = I18N.tr(text)
        if I18N.LANG == "en" or I18N.has_latin(t):
            return t, {"font_name": "Roboto", "font_script_name": "Zyyy"}
        font, script = I18N.font_for()
        return t, {"font_name": font, "font_script_name": script}

    def _menu_button(self, text, cb):
        from kivy.uix.button import Button
        text, fkw = self._tr_font(text)
        b = Button(
            text=text, size_hint_y=None, height=dp(46), font_size="14sp", **fkw,
            bold=True, color=(0.9, 0.93, 0.97, 1),
            background_normal="", background_down="",
            background_color=(0.10, 0.12, 0.20, 1),
        )
        b.bind(on_release=lambda *_: cb())
        return b

    def _dismiss_button(self, text, cb):
        """A visually distinct Close/OK button for popups."""
        from kivy.uix.button import Button
        text, fkw = self._tr_font(text)
        b = Button(
            text=text, size_hint_y=None, height=dp(48), font_size="15sp", **fkw,
            bold=True, color=(1, 1, 1, 1),
            background_normal="", background_down="",
            background_color=(0.22, 0.26, 0.34, 1),
        )
        b.bind(on_release=lambda *_: cb())
        return b

    def show_more_menu(self):
        from kivy.uix.scrollview import ScrollView
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8),
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        blur_lbl = "%s: %s" % (I18N.tr("Privacy blur (faces)"),
                               I18N.tr("ON" if self._privacy_blur else "OFF"))
        lang_lbl = "%s: %s" % (I18N.tr("Language"), I18N.LANGS[I18N.LANG][0])
        items = [
            ("Share to X / Twitter", self.share_twitter),
            ("Share to WhatsApp", self.share_whatsapp),
            ("WhatsApp traffic police (official no.)", self.whatsapp_police),
            ("Vehicle lookup (RC/Insurance/PUC)", self.vehicle_lookup),
            ("Report a road hazard", self.report_hazard),
            ("SOS / Emergency", self.show_sos),
            ("Save last 15 s as video clip", self.save_clip),
            ("Emergency contact (crash SOS)", self.edit_emergency_contact),
            ("Violation hotspots", self.show_hotspots),
            ("Check for app updates", lambda: self._auto_update_check(True)),
            (blur_lbl, self.toggle_privacy_blur),
            (lang_lbl, self.toggle_language),
        ]
        for text, cb in items:
            box.add_widget(self._menu_button(text, cb))
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(box)
        container = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(6))
        container.add_widget(scroll)
        container.add_widget(self._dismiss_button("Close", self._close_menu))
        self._menu_popup = Popup(
            title=self._tr_font("More - Citizen Tools")[0], content=container,
            size_hint=(0.9, 0.85), title_size="15sp",
            title_color=(1, 0.84, 0.25, 1), separator_color=(1, 0.84, 0.25, 1),
            background_color=(0.08, 0.09, 0.15, 0.96),
        )
        mtitle, mkw = self._tr_font("More - Citizen Tools")
        self._style_title(self._menu_popup, mtitle, mkw)
        self._menu_popup.open()

    def _close_menu(self):
        if getattr(self, "_menu_popup", None):
            try:
                self._menu_popup.dismiss()
            except Exception:
                pass

    # ── context helpers ──────────────────────────────────────────────────
    def _ctx(self):
        plate = self.ids.in_plate.text.strip()
        okey = (self.ids.sp_offense.text.split(":")[0] or "").strip()
        label = TrafficLawDB.OFFENSES.get(okey, {}).get("label", "")
        loc = self._location_text()
        sc = JurisdictionEngine.extract_state_code(plate) or \
            JurisdictionEngine._resolve_state(float(self.latest_lat), float(self.latest_lon))
        return plate, label, loc, sc

    def _open_url(self, url):
        """Open a URL via an Android intent, else the desktop browser."""
        if platform == "android" and autoclass is not None:
            try:
                Intent = autoclass("android.content.Intent")
                Uri = autoclass("android.net.Uri")
                act = autoclass("org.kivy.android.PythonActivity").mActivity
                i = Intent(Intent.ACTION_VIEW, Uri.parse(url))
                i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                act.startActivity(i)
                return True
            except Exception:
                return False
        try:
            import webbrowser
            return webbrowser.open(url)
        except Exception:
            return False

    def _android_intent(self, action, uri, extras=None):
        if platform != "android" or autoclass is None:
            return False
        try:
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            i = Intent(action, Uri.parse(uri))
            for k, v in (extras or {}).items():
                i.putExtra(k, v)
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            act.startActivity(i)
            return True
        except Exception:
            return False

    # ── share channels ───────────────────────────────────────────────────
    def _share_to_app(self, package, text, uri=None, jid=None):
        """ACTION_SEND to one app (None = system chooser), optionally with an
        image and a WhatsApp chat id. Returns True if an activity started."""
        if platform != "android" or autoclass is None:
            return False
        try:
            from jnius import cast
            Intent = autoclass("android.content.Intent")
            String = autoclass("java.lang.String")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            i = Intent(Intent.ACTION_SEND)
            i.putExtra(Intent.EXTRA_TEXT, cast("java.lang.CharSequence", String(text)))
            if uri is not None:
                i.setType("image/*")
                i.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
                i.setClipData(autoclass("android.content.ClipData").newRawUri("", uri))
                i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            else:
                i.setType("text/plain")
            if jid:
                i.putExtra("jid", jid)  # opens that WhatsApp chat directly
            if package:
                i.setPackage(package)
            else:
                i = Intent.createChooser(
                    i, cast("java.lang.CharSequence", String("Share with:")))
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            act.startActivity(i)
            return True
        except Exception:
            return False

    def _make_share_copy(self, path, plate):
        """Privacy-safe JPEG copy for public sharing: faces and every
        plate-like region except the reported vehicle's plate are blurred.
        The original evidence file is never modified. Runs off the UI thread
        (uses ML Kit to locate the reported plate). Returns the copy path."""
        img = cv2.imread(path) if cv2 is not None else None
        if img is None:
            return ""
        keep = None
        if self._plate_ocr is not None and self._plate_ocr.available:
            try:
                _raw, lines = self._plate_ocr._ocr(img)
                keep = PlateOCR.plate_box(re.sub(r"[^A-Z0-9]", "", plate.upper()), lines)
            except Exception:
                keep = None
        boxes = []
        cascade = PrivacyBlur._face_cascade()
        if cascade is not None:
            try:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                boxes += [tuple(int(v) for v in b) for b in
                          cascade.detectMultiScale(gray, 1.1, 5, minSize=(24, 24))]
            except Exception:
                pass
        for _crop, b in PlateOCR.crop_plate_candidates(img):
            if keep is None or not PrivacyBlur.overlaps(b, keep):
                boxes.append(b)
        img = PrivacyBlur.blur_regions(img, boxes)
        out = os.path.splitext(path)[0] + "_share.jpg"
        cv2.imwrite(out, img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return out

    def _share_public(self, package, text, fallback_url, label):
        """Share text + a blurred copy of the evidence (if any) to a public
        app; falls back to the chooser, then to the web intent URL."""
        if not self.evidence_path or cv2 is None:
            if not self._open_url(fallback_url):
                self._popup("Unavailable", "Could not open %s." % label)
            return
        plate = self.ids.in_plate.text.strip()
        src = self.evidence_path
        self.ocr_suggest_text = "Preparing a privacy-safe copy..."

        def work():
            try:
                copy = self._make_share_copy(src, plate)
            except Exception:
                copy = ""

            def done(_dt):
                self.ocr_suggest_text = ""
                uri = self._publish_to_gallery(copy, "Pictures/SentinelX/Shared",
                                               "image/jpeg") if copy else None
                if not (self._share_to_app(package, text, uri)
                        or self._share_to_app(None, text, uri)
                        or self._open_url(fallback_url)):
                    self._popup("Unavailable", "Could not open %s." % label)
            Clock.schedule_once(done, 0)
        threading.Thread(target=work, daemon=True).start()

    def share_twitter(self):
        self._close_menu()
        plate, label, loc, sc = self._ctx()
        if not plate:
            self._popup("Missing", "Enter or scan a plate first.")
            return
        text = ReportChannels.compose(plate, label, loc, sc)
        self._share_public("com.twitter.android", text,
                           ReportChannels.twitter_url(text), "X/Twitter")

    def share_whatsapp(self):
        self._close_menu()
        plate, label, loc, sc = self._ctx()
        if not plate:
            self._popup("Missing", "Enter or scan a plate first.")
            return
        text = ReportChannels.compose(plate, label, loc, sc)
        self._share_public("com.whatsapp", text,
                           ReportChannels.whatsapp_url(text), "WhatsApp")

    def whatsapp_police(self):
        """Send the report and the ORIGINAL evidence photo to the official
        traffic-police WhatsApp number for this location (or plate state)."""
        self._close_menu()
        plate, label, loc, sc = self._ctx()
        if not plate:
            self._popup("Missing", "Enter or scan a plate first.")
            return
        lc = JurisdictionEngine._resolve_state(float(self.latest_lat),
                                               float(self.latest_lon))
        code = next((c for c in (lc, sc) if c in CivicDirectory.WHATSAPP), "")
        if not code:
            have = ", ".join(sorted(CivicDirectory.WHATSAPP))
            self._popup("WhatsApp", "No official traffic-police WhatsApp number is "
                        "published for this state.\n\nAvailable for: %s.\nUse SEND "
                        "(email) instead." % have, tall=True)
            return
        num = CivicDirectory.WHATSAPP[code][0]
        text = "Traffic violation: %s - %s at %s. GPS %s (via Sentinel-X)" % (
            plate, label or "violation", loc,
            Emergency.maps_link(float(self.latest_lat), float(self.latest_lon)))
        if not self._share_to_app("com.whatsapp", text, self._evidence_uri,
                                  jid=num + "@s.whatsapp.net"):
            self._open_url(ReportChannels.whatsapp_url(text, num))

    # ── vehicle lookup ───────────────────────────────────────────────────
    def vehicle_lookup(self):
        self._close_menu()
        plate = self.ids.in_plate.text.strip()
        if not plate:
            self._popup("Missing", "Enter or scan a plate first.")
            return
        if not VehicleLookup.available():
            self._popup(
                "Lookup",
                "No vehicle-data provider configured.\n\n"
                "Masters India VAHAN: drop a 'vahan.json' in the app folder with\n"
                '{"jwt": "JWT <your-token>", "subid": "<your-subid>"}\n'
                "(get these from your Masters India account), or set the\n"
                "SENTINELX_MI_JWT / SENTINELX_MI_SUBID env vars.",
                tall=True,
            )
            return
        self._popup("Lookup", "Querying VAHAN records for %s..." % plate)
        threading.Thread(target=self._vehicle_lookup_worker,
                         args=(plate,), daemon=True).start()

    def _vehicle_lookup_worker(self, plate):
        res = VehicleLookup.lookup(plate)

        def show(_dt):
            if not res.get("ok"):
                self._popup("Lookup failed", res.get("error", "unknown error"))
                return
            rows = [
                ("Plate", res.get("plate")),
                ("Owner", res.get("owner")),
                ("Model", res.get("model")),
                ("Class", res.get("vclass")),
                ("RC status", res.get("rc_status")),
                ("Registered", res.get("registered")),
                ("RTO", res.get("registered_at")),
                ("Insurance upto", res.get("insurance")),
                ("Insurer", res.get("insurer")),
                ("PUC upto", res.get("puc")),
                ("Fitness upto", res.get("fitness")),
                ("Financer", res.get("financer")),
            ]
            lines = ["%s: %s" % (k, v) for k, v in rows if v]
            bl = (res.get("blacklist") or "").strip()
            if bl:
                lines.insert(0, "⚠ BLACKLIST: %s" % bl)
            self._popup("Vehicle %s" % plate, "\n".join(lines) or "No fields returned.",
                        tall=True)
        Clock.schedule_once(show, 0)

    # ── road-hazard reporting (municipal) ────────────────────────────────
    def report_hazard(self):
        self._close_menu()
        from kivy.uix.scrollview import ScrollView
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8),
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        for cat in HazardReport.CATEGORIES:
            box.add_widget(self._menu_button(cat, lambda c=cat: self._send_hazard(c)))
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(box)
        container = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(6))
        container.add_widget(scroll)
        container.add_widget(self._dismiss_button("Close", self._close_menu))
        self._menu_popup = Popup(
            title="Report a hazard", content=container, size_hint=(0.9, 0.85),
            title_size="15sp", title_color=(1, 0.84, 0.25, 1),
            separator_color=(1, 0.84, 0.25, 1),
            background_color=(0.08, 0.09, 0.15, 0.96),
        )
        self._menu_popup.open()

    def _send_hazard(self, category):
        self._close_menu()
        lat, lon = float(self.latest_lat), float(self.latest_lon)
        loc = self._location_text()
        notes = self.ids.in_notes.text.strip()
        subj = HazardReport.subject(category, loc)
        body = HazardReport.body(category, lat, lon, loc, notes)
        if not self._send_email([], subj, body):
            # Fall back to the national grievance portal
            self._open_url(HazardReport.CPGRAMS_PORTAL)
        self._popup("Hazard", "Hazard report prepared:\n%s" % category)

    # ── SOS / emergency ──────────────────────────────────────────────────
    def show_sos(self):
        self._close_menu()
        box = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8),
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        lat, lon = float(self.latest_lat), float(self.latest_lon)
        actions = [
            ("Call 112 (Emergency)", lambda: self._dial(CivicDirectory.EMERGENCY)),
            ("Call 108 (Ambulance)", lambda: self._dial(CivicDirectory.AMBULANCE)),
            ("Report accident (Good Samaritan)", self._good_samaritan),
            ("Share my location (SMS)", lambda: self._sos_sms(lat, lon)),
        ]
        for text, cb in actions:
            box.add_widget(self._menu_button(text, cb))
        box.add_widget(self._dismiss_button("Close", self._close_menu))
        self._menu_popup = Popup(
            title="SOS / Emergency", content=box, size_hint=(0.9, 0.62),
            title_size="15sp", title_color=(1, 0.32, 0.32, 1),
            separator_color=(1, 0.32, 0.32, 1),
            background_color=(0.08, 0.09, 0.15, 0.96),
        )
        self._menu_popup.open()

    def _dial(self, number):
        # Intent action constants are plain strings, so no autoclass on desktop.
        self._close_menu()
        if not self._android_intent("android.intent.action.DIAL", "tel:" + str(number)):
            self._popup("Dial", "Call %s" % number)

    def _sos_sms(self, lat, lon):
        self._close_menu()
        text = Emergency.sos_text(lat, lon)
        if not self._android_intent("android.intent.action.SENDTO", "smsto:",
                                    {"sms_body": text}):
            self._popup("SOS", text)

    def _good_samaritan(self):
        self._close_menu()
        lat, lon = float(self.latest_lat), float(self.latest_lon)
        self._popup(
            "Good Samaritan",
            "Reporting an accident under Sec.134A protection.\n\n%s\n\n"
            "Use SOS to call 112/108." % Emergency.good_samaritan_text(lat, lon),
            tall=True,
        )

    # ── hotspots, privacy, language ──────────────────────────────────────
    def show_hotspots(self):
        self._close_menu()
        entries = self._report_log.read_all() if self._report_log else []
        spots = ViolationHeatmap.hotspots(entries)
        if not spots:
            self._popup("Hotspots", "Not enough reports yet to map hotspots.")
            return
        lines = ["%d report(s) near %.3f, %.3f" % (s["count"], s["lat"], s["lon"])
                 for s in spots]
        self._popup("Violation hotspots", "\n\n".join(lines), tall=True)

    def toggle_privacy_blur(self):
        self._privacy_blur = not self._privacy_blur
        self._close_menu()
        self._popup("Privacy", "Face blur on capture: %s"
                    % ("ON" if self._privacy_blur else "OFF"))

    def toggle_language(self):
        """Cycle English -> Hindi -> Marathi -> Tamil -> Kannada -> Bengali."""
        App.get_running_app().set_language(I18N.next_lang())
        self._save_settings({"lang": I18N.LANG})
        self._close_menu()
        self.show_more_menu()  # reopen so the menu itself shows the change

    # ═════════════════════════════════════════════════════════════════════
    # Over-the-air auto-update (detect -> download -> one-tap install)
    # ═════════════════════════════════════════════════════════════════════
    def _installed_from_play(self):
        """True if this app was installed from the Google Play Store."""
        if platform != "android" or autoclass is None:
            return False
        try:
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            installer = act.getPackageManager().getInstallerPackageName(
                act.getPackageName())
            return installer in ("com.android.vending",
                                 "com.google.android.feedback")
        except Exception:
            return False

    def _auto_update_check(self, announce=False):
        """Use Play In-App Updates on Play installs; GitHub OTA otherwise."""
        self._close_menu()
        if self._installed_from_play():
            self._play_in_app_update()
            if announce:
                self._popup("Updates", "Checking Google Play for updates...")
        else:
            self.check_for_updates(announce)

    def _play_in_app_update(self):
        """Trigger the Play In-App Updates flexible flow via the Java helper."""
        if platform != "android" or autoclass is None:
            return
        try:
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            autoclass("org.sentinelx.InAppUpdate").start(act)
        except Exception:
            # Helper/Play Core unavailable -> fall back to GitHub OTA
            self.check_for_updates(False)

    def _current_version_code(self):
        """Installed app versionCode via PackageManager (0 off-device)."""
        if platform != "android" or autoclass is None:
            return 0
        try:
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            pi = act.getPackageManager().getPackageInfo(act.getPackageName(), 0)
            return int(pi.versionCode)
        except Exception:
            return 0

    def check_for_updates(self, announce=False):
        """Fetch the published manifest and compare with the installed build."""
        self._close_menu()
        threading.Thread(target=self._check_updates_worker,
                         args=(announce,), daemon=True).start()

    def _check_updates_worker(self, announce):
        man = None
        err = ""
        try:
            import urllib.request
            import json as _json
            with urllib.request.urlopen(UpdateManifest.DEFAULT_URL, timeout=8) as r:
                man = UpdateManifest.parse(_json.loads(r.read().decode("utf-8", "replace")))
            if man is None:
                err = "Malformed update manifest."
        except Exception as e:
            # 404 == no release published yet; other == network/parse failure
            err = "No published release found yet." if "404" in str(e) \
                else "Couldn't reach the update server."
        cur = self._current_version_code()

        def show(_dt):
            if UpdateManifest.is_newer(cur, man):
                self._prompt_update(man)
            elif not announce:
                return  # silent startup check: say nothing unless asked
            elif man is not None:
                self._popup("Up to date",
                            "You're on the latest version (build %d)." % cur)
            else:
                self._popup("Update check failed",
                            "%s\n\nOTA releases are published from the main branch; "
                            "make sure a release exists and you're online." % err)
        Clock.schedule_once(show, 0)

    def _prompt_update(self, man):
        from kivy.uix.button import Button
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        box.add_widget(Label(
            text="Version %s is available.\n\n%s" % (
                man.get("version", "?"), man.get("notes", "") or "Tap Update to install."),
            halign="left", valign="top", text_size=(dp(250), None),
            font_size="13sp", color=(0.82, 0.84, 0.88, 1),
        ))
        btn = Button(
            text="Update now", size_hint_y=None, height=dp(46), bold=True,
            color=(1, 1, 1, 1), background_normal="", background_down="",
            background_color=(0, 0.78, 0.33, 1),
        )
        btn.bind(on_release=lambda *_: (self._update_popup.dismiss(),
                                        self._download_and_install(man.get("url", ""))))
        box.add_widget(btn)
        box.add_widget(self._dismiss_button(
            "Later", lambda: self._update_popup.dismiss()))
        self._update_popup = Popup(
            title="Update available", content=box, size_hint=(0.86, 0.5),
            title_size="15sp", title_color=(0, 0.78, 0.33, 1),
            separator_color=(0, 0.78, 0.33, 1),
            background_color=(0.08, 0.09, 0.15, 0.96),
        )
        self._update_popup.open()

    def _download_and_install(self, url):
        if not url:
            return
        if platform != "android" or autoclass is None:
            self._open_url(url)  # desktop / fallback
            return
        try:
            Uri = autoclass("android.net.Uri")
            Request = autoclass("android.app.DownloadManager$Request")
            Environment = autoclass("android.os.Environment")
            Context = autoclass("android.content.Context")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            req = Request(Uri.parse(url))
            req.setTitle("Sentinel-X update")
            req.setMimeType("application/vnd.android.package-archive")
            req.setNotificationVisibility(
                Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            req.setDestinationInExternalFilesDir(
                act, Environment.DIRECTORY_DOWNLOADS, "sentinelx-update.apk")
            self._dl_dm = act.getSystemService(Context.DOWNLOAD_SERVICE)
            self._dl_id = self._dl_dm.enqueue(req)
            self._dl_tries = 0
            self._popup("Updating", "Downloading the new version...")
            Clock.schedule_interval(self._poll_download, 1.5)
        except Exception:
            # Fall back to opening the APK URL in the browser
            self._open_url(url)

    def _poll_download(self, _dt):
        try:
            uri = self._dl_dm.getUriForDownloadedFile(self._dl_id)
            if uri is not None:
                self._install_apk(uri)
                return False
        except Exception:
            return False
        self._dl_tries = getattr(self, "_dl_tries", 0) + 1
        if self._dl_tries > 180:  # ~4.5 min cap
            self._popup("Update", "Download is taking long. Check notifications.")
            return False
        return True

    def _install_apk(self, uri):
        try:
            Intent = autoclass("android.content.Intent")
            act = autoclass("org.kivy.android.PythonActivity").mActivity
            i = Intent(Intent.ACTION_VIEW)
            i.setDataAndType(uri, "application/vnd.android.package-archive")
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            act.startActivity(i)
        except Exception:
            self._popup("Update", "Downloaded. Open it from notifications to install.")

    # ═════════════════════════════════════════════════════════════════════
    # Settings, crash SOS, follow-ups, video clip
    # ═════════════════════════════════════════════════════════════════════
    def _settings_path(self):
        try:
            return os.path.join(App.get_running_app().user_data_dir, "settings.json")
        except Exception:
            return "settings.json"

    def _settings(self):
        try:
            with open(self._settings_path(), "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_settings(self, data):
        try:
            cur = self._settings()
            cur.update(data)
            with open(self._settings_path(), "w") as f:
                json.dump(cur, f)
        except Exception:
            pass

    def edit_emergency_contact(self):
        self._close_menu()
        from kivy.uix.textinput import TextInput
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        box.add_widget(Label(
            text="Phone number to alert if a crash is detected while driving.\n"
                 "Sentinel-X opens a pre-filled SMS with your location after a "
                 "%d s countdown you can cancel." % Emergency.SOS_COUNTDOWN_S,
            halign="left", valign="top", text_size=(dp(250), None),
            font_size="13sp", color=(0.82, 0.84, 0.88, 1)))
        ti = TextInput(text=self._settings().get("emergency_contact", ""),
                       multiline=False, input_filter=lambda t, _u: "".join(
                           c for c in t if c.isdigit() or c == "+"),
                       size_hint_y=None, height=dp(44), font_size="16sp",
                       hint_text="+91XXXXXXXXXX")
        box.add_widget(ti)

        def save():
            self._save_settings({"emergency_contact": ti.text.strip()})
            pop.dismiss()
            self._popup("Saved", "Emergency contact: %s" % (ti.text.strip() or "none"))
        box.add_widget(self._dismiss_button("Save", save))
        pop = Popup(title="Emergency contact", content=box, size_hint=(0.88, 0.55),
                    title_size="15sp", title_color=(1, 0.32, 0.32, 1),
                    separator_color=(1, 0.32, 0.32, 1),
                    background_color=(0.08, 0.09, 0.15, 0.96))
        pop.open()

    def _check_crash(self):
        """Crash = crash-level g while recently moving at vehicle speed."""
        now = time.time()
        if self.latest_speed * 3.6 >= Emergency.CRASH_MIN_SPEED_KMH:
            self._last_moving_ts = now
        if (getattr(self, "_crash_popup", None) is None
                and now - getattr(self, "_last_crash_ts", 0) > 60
                and Emergency.is_crash(self.latest_g,
                                       getattr(self, "_last_moving_ts", 0), now)):
            self._last_crash_ts = now
            self._start_crash_countdown()

    def _start_crash_countdown(self):
        from kivy.uix.button import Button
        self._crash_left = Emergency.SOS_COUNTDOWN_S
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        lbl = Label(text="", halign="center", valign="middle", font_size="16sp",
                    color=(1, 1, 1, 1), text_size=(dp(250), None))
        box.add_widget(lbl)
        ok = Button(text="I'M OK - CANCEL", size_hint_y=None, height=dp(56),
                    bold=True, font_size="16sp", background_normal="",
                    background_color=(0, 0.6, 0.3, 1))
        call = self._dismiss_button("Call 112 now", lambda: self._crash_finish(dial=True))
        box.add_widget(ok)
        box.add_widget(call)
        self._crash_popup = Popup(
            title="Possible crash detected", content=box, size_hint=(0.9, 0.55),
            auto_dismiss=False, title_size="16sp", title_color=(1, 0.32, 0.32, 1),
            separator_color=(1, 0.32, 0.32, 1),
            background_color=(0.12, 0.04, 0.05, 0.97))

        def tick(_dt):
            if self._crash_popup is None:
                return False
            if self._crash_left <= 0:
                self._crash_finish(dial=False)
                return False
            contact = self._settings().get("emergency_contact", "")
            lbl.text = ("Sending SOS %s in %d s" % (
                "to " + contact if contact else "(calling 112)", self._crash_left))
            self._crash_left -= 1
            return True
        ok.bind(on_release=lambda *_: self._crash_cancel())
        tick(0)
        self._crash_event = Clock.schedule_interval(tick, 1.0)
        self._crash_popup.open()

    def _crash_cancel(self):
        if getattr(self, "_crash_event", None):
            self._crash_event.cancel()
        if self._crash_popup is not None:
            self._crash_popup.dismiss()
        self._crash_popup = None

    def _crash_finish(self, dial):
        self._crash_cancel()
        lat, lon = float(self.latest_lat), float(self.latest_lon)
        contact = self._settings().get("emergency_contact", "")
        if contact and not dial:
            # Pre-filled SMS: the user taps send (no SEND_SMS permission).
            if self._android_intent("android.intent.action.SENDTO", "smsto:" + contact,
                                    {"sms_body": Emergency.crash_text(lat, lon)}):
                return
        self._dial(CivicDirectory.EMERGENCY)

    def _check_followups(self):
        entries = self._report_log.read_all() if self._report_log else []
        done = set(self._settings().get("followups_done", []))
        due = FollowUp.due(entries, done)
        if not due:
            return
        shown = due[:FollowUp.MAX_SHOWN]
        lines = ["%s - %s (sent %s)" % (
            e.get("plate", "?"), e.get("offense", "?"),
            time.strftime("%d %b", time.localtime(float(e.get("ts", 0)))))
            for e in shown]
        box = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        box.add_widget(Label(
            text="No action seen yet on %d report(s) older than %d days:\n\n%s\n\n"
                 "Escalate on CPGRAMS (national grievance portal)? A complaint "
                 "draft is copied for you to paste." % (len(due), FollowUp.DAYS,
                                                        "\n".join(lines)),
            halign="left", valign="top", text_size=(dp(250), None),
            font_size="13sp", color=(0.82, 0.84, 0.88, 1)))

        def mark(entries_):
            keys = done | {FollowUp.key(e) for e in entries_}
            self._save_settings({"followups_done": sorted(keys)})

        def escalate():
            try:
                from kivy.core.clipboard import Clipboard
                Clipboard.copy("\n\n---\n\n".join(FollowUp.draft(e) for e in shown))
            except Exception:
                pass
            mark(shown)
            pop.dismiss()
            self._open_url(CivicDirectory.CPGRAMS_PORTAL)

        def dismiss():
            mark(shown)
            pop.dismiss()
        box.add_widget(self._dismiss_button("Escalate (copy draft)", escalate))
        box.add_widget(self._dismiss_button("Dismiss", dismiss))
        pop = Popup(title="Follow up on reports", content=box, size_hint=(0.9, 0.7),
                    title_size="15sp", title_color=(1, 0.84, 0.25, 1),
                    separator_color=(1, 0.84, 0.25, 1),
                    background_color=(0.08, 0.09, 0.15, 0.96))
        pop.open()

    def save_clip(self):
        """Save the dashcam's last 15 s as a video in Movies/SentinelX."""
        self._close_menu()
        if self._dashcam is None:
            self._popup("Clip", "Dashcam is not running.")
            return
        out = os.path.join(self._get_evidence_folder(),
                           "SentinelX_clip_%s.avi" % datetime.now().strftime("%Y%m%d_%H%M%S"))

        def work():
            path, n = self._dashcam.save_clip(out)

            def done(_dt):
                if not path:
                    self._popup("Clip", "Not enough recent footage yet.")
                    return
                EvidenceHasher.write_hashfile(path)
                uri = self._publish_to_gallery(path, "Movies/SentinelX", "video/x-msvideo")
                self._popup("Saved!", "Video clip saved (%d frames, %.0f s):\n%s" % (
                    n, n / float(DashcamRecorder.CLIP_FPS),
                    "Movies/SentinelX/" + os.path.basename(path) if uri
                    else os.path.basename(path)))
            Clock.schedule_once(done, 0)
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _style_title(popup, title, fkw):
        """Popup only exposes title_font; also set the HarfBuzz script on its
        internal title label so Indic titles shape correctly."""
        popup.title_font = fkw["font_name"]
        for w in popup.walk(restrict=True):
            if isinstance(w, Label) and w.text == title:
                w.font_script_name = fkw["font_script_name"]

    def _popup(self, t, m, tall=False):
        # Determine accent color based on popup type
        if t in ("Saved!", "Ready"):
            accent = (0, 0.78, 0.33, 1)       # green
        elif t in ("Failed", "Capture Error", "No route"):
            accent = (1, 0.32, 0.32, 1)        # red
        elif t in ("Queued",):
            accent = (1, 0.84, 0.25, 1)        # amber
        else:
            accent = (0, 0.9, 1, 1)            # cyan

        t, tkw = self._tr_font(t)
        m, mkw = self._tr_font(m)
        content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        lbl = Label(
            text=m, halign="left", valign="top",
            text_size=(dp(240), None), font_size="13sp",
            color=(0.82, 0.84, 0.88, 1), **mkw
        )
        if tall:
            from kivy.uix.scrollview import ScrollView
            lbl.size_hint_y = None
            lbl.bind(texture_size=lambda inst, sz: setattr(inst, "height", sz[1]))
            scroll = ScrollView(do_scroll_x=False)
            scroll.add_widget(lbl)
            content.add_widget(scroll)
        else:
            content.add_widget(lbl)

        okbtn = self._dismiss_button("OK", lambda: None)
        content.add_widget(okbtn)

        p = Popup(
            title=t, content=content,
            size_hint=(0.88, 0.66) if tall else (0.82, 0.36),
            title_size="15sp",
            title_color=accent,
            separator_color=accent,
            background_color=(0.08, 0.09, 0.15, 0.95),
        )
        okbtn.bind(on_release=lambda *_: p.dismiss())
        self._style_title(p, t, tkw)
        p.open()


class SentinelXApp(App):
    # Current UI language and the font/script to render it (bound in KV)
    lang = StringProperty("en")
    ui_font = StringProperty("Roboto")
    ui_script = StringProperty("Zyyy")

    def set_language(self, lang):
        I18N.set_lang(lang)
        self.ui_font, self.ui_script = I18N.font_for()
        self.lang = I18N.LANG

    def build(self):
        try:
            with open(os.path.join(self.user_data_dir, "settings.json")) as f:
                self.set_language(json.load(f).get("lang", "en"))
        except Exception:
            self.set_language("en")
        Window.clearcolor = (0.043, 0.055, 0.09, 1)  # #0B0E17
        Builder.load_string(KV)
        return RootUI()

    def on_stop(self):
        r = self.root
        if r:
            # Phase 1: Stop subsystems
            if r._watchdog:
                try:
                    r._watchdog.stop()
                except Exception:
                    pass
            if r._analysis_worker:
                try:
                    r._analysis_worker.stop()
                except Exception:
                    pass
            if r._dashcam:
                try:
                    r._dashcam.stop()
                except Exception:
                    pass
            if r._telemetry:
                try:
                    r._telemetry.stop()
                except Exception:
                    pass
            # Phase 3: Stop queue retry daemon
            if r._queue_retry:
                try:
                    r._queue_retry.stop()
                except Exception:
                    pass
            if r._preview and r._cam_ok:
                try:
                    r._preview.disconnect_camera()
                except Exception:
                    pass
            # Stop the telemetry service: it holds a partial wakelock and
            # would otherwise keep polling GPS after the app has exited.
            if r._service_cls is not None:
                try:
                    act = autoclass("org.kivy.android.PythonActivity").mActivity
                    r._service_cls.stop(act)
                except Exception:
                    pass
        if plyer_accel:
            try:
                plyer_accel.disable()
            except Exception:
                pass


if __name__ == "__main__":
    SentinelXApp().run()
