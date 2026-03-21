# -*- coding: utf-8 -*-
"""
Sentinel-X v1.4.0 -- Civic Enforcement (Android)
Phase 1: Continuous recording, crash recovery, threaded analysis, telemetry.
Phase 2: Evidence integrity — SHA-256 hashing, metadata watermark, report log.
Phase 3: Offline resilience — report queue, connectivity detection, auto-retry.
Phase 4: Enhanced detection — ONNX model loader, speed zones, subsystem status.
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
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.utils import platform

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


# ═════════════════════════════════════════════════════════════════════════
# GPS via pyjnius — directly calls Android LocationManager Java API
# This is far more reliable than plyer.gps
# ═════════════════════════════════════════════════════════════════════════
class AndroidGPS:
    """Direct access to Android LocationManager via pyjnius."""

    def __init__(self):
        self._lm = None
        self._available = False
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
        if self._reconnecting:
            self._reconnecting = False
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
        try:
            self._reconnect_cb()
        except Exception:
            pass


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
            if now - self._last_save_ts < self.FRAME_INTERVAL:
                time.sleep(0.05)
                continue
            # Rotate segment if needed
            if (self._current_segment_dir is None or
                    now - self._segment_start >= self.SEGMENT_DURATION):
                self._new_segment()
            self._save_frame(frame)
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

    def _save_frame(self, frame):
        if cv2 is None or np is None:
            return
        try:
            _ts, pixels, image_size = frame
            w, h = image_size
            arr = np.frombuffer(pixels, dtype=np.uint8).reshape((h, w, 4))
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            fname = "f_%s.jpg" % datetime.now().strftime("%H%M%S_%f")
            fpath = os.path.join(self._current_segment_dir, fname)
            cv2.imencode(
                ".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 70]
            )[1].tofile(fpath)
            self._frame_count += 1
        except Exception:
            pass


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
            with open(fpath, "w") as f:
                json.dumps(report_dict, default=str)  # validate first
                f.write(json.dumps(report_dict, default=str))
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
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(ConnectivityChecker.TIMEOUT)
            s.connect((ConnectivityChecker.PROBE_HOST, ConnectivityChecker.PROBE_PORT))
            s.close()
            return True
        except Exception:
            return False


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

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self):
        while self._running:
            time.sleep(self.RETRY_INTERVAL)
            if not self._running:
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

        def analyze_pixels_callback(self, pixels, image_size, image_pos, scale, mirror):
            if self._watchdog:
                self._watchdog.frame_received()
            if self._frame_buffer:
                self._frame_buffer.push(time.time(), bytes(pixels), image_size)
            elif self._analytics:
                self._analytics.analyze_frame(pixels, image_size)
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
                height: dp(30)
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

            # Evidence status
            Label:
                size_hint_y: None
                height: dp(24)
                text: root.evidence_status
                font_size: "10sp"
                color: (0.3, 0.8, 1, 1)
                halign: "left"
                text_size: self.size

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
    evidence_status = StringProperty("")
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
        Clock.schedule_once(self._boot, 0)

    def _get_evidence_folder(self):
        """Get a writable, user-visible evidence folder."""
        # Try shared Pictures/SentinelX first (visible in gallery)
        if platform == "android":
            try:
                Environment = autoclass("android.os.Environment")
                pic_dir = Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_PICTURES
                ).getAbsolutePath()
                d = os.path.join(pic_dir, "SentinelX")
                os.makedirs(d, exist_ok=True)
                # Test write
                test = os.path.join(d, ".test")
                with open(test, "w") as f:
                    f.write("ok")
                os.remove(test)
                return d
            except Exception:
                pass
        # Fallback: app private dir
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
        self._frame_buffer = FrameRingBuffer(max_frames=30)
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
                svc = autoclass("org.sentinelx.ServiceService")
                mActivity = autoclass(
                    "org.kivy.android.PythonActivity"
                ).mActivity
                svc.start(mActivity, "")
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
        # Polling loops
        Clock.schedule_interval(self._poll_gps, 1.0)
        Clock.schedule_interval(self._poll_accel, 0.1)
        Clock.schedule_interval(self._tick_ui, 1.0)

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
        if "g_dyn" in t:
            self.latest_g = t["g_dyn"]
        else:
            # Fallback to direct plyer
            if plyer_accel is None:
                return
            try:
                val = plyer_accel.acceleration
                if val and val[0] is not None:
                    x, y, z = float(val[0]), float(val[1]), float(val[2] or 9.81)
                    g_total = math.sqrt(x * x + y * y + z * z)
                    self.latest_g = abs(g_total - 9.81)
            except Exception:
                pass
        # Phase 4: Record harsh braking events (debounce 5s)
        now = time.time()
        if (self.latest_g > 4.0 and self._harsh_brake_log and
                now - self._last_harsh_brake_ts > 5.0):
            self._harsh_brake_log.record(
                self.latest_g, float(self.latest_lat),
                float(self.latest_lon), self.latest_speed * 3.6
            )
            self._last_harsh_brake_ts = now

    # ── Camera ───────────────────────────────────────────────────────────
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
        # Phase 1: Start watchdog after camera connects
        if self._cam_ok:
            if self._watchdog:
                self._watchdog.stop()
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
            result = self._preview.export_to_png(fpath)

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

                # Phase 2: Watermark evidence with metadata
                plate = self.ids.in_plate.text.strip()
                EvidenceWatermark.apply(
                    fpath, float(self.latest_lat), float(self.latest_lon),
                    ts, plate
                )
                # Phase 2: Hash evidence for tamper detection
                EvidenceHasher.write_hashfile(fpath)
                self.evidence_path = fpath
                self.evidence_status = "Evidence: %s" % fname
                self._popup("Saved!", "Photo saved to:\nSentinelX/%s" % fname)

                # Notify Android gallery about new file
                self._notify_gallery(fpath)
            else:
                self._popup("Failed", "File was not created.")
        except Exception as e:
            self._popup("Capture Error", str(e))

    def _notify_gallery(self, path):
        """Tell Android to scan the file so it shows in gallery."""
        if platform != "android" or autoclass is None:
            return
        try:
            Intent = autoclass("android.content.Intent")
            Uri = autoclass("android.net.Uri")
            File = autoclass("java.io.File")
            PythonActivity = autoclass("org.kivy.android.PythonActivity")

            intent = Intent(Intent.ACTION_MEDIA_SCANNER_SCAN_FILE)
            intent.setData(Uri.fromFile(File(path)))
            PythonActivity.mActivity.sendBroadcast(intent)
        except Exception:
            pass

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
        status_suffix = self._subsystem_status.summary() if self._subsystem_status else ""
        self.status_text = "%.4f,%.4f | %s | %.0fkm/h | G:%.1f | %s%s\n%s" % (
            lat, lon, self.state_name or DASH, kmh, self.latest_g, cv,
            zone_warn, status_suffix
        )

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
        self.evidence_status = ""

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

        # Phase 2: Build report record for logging
        report_record = {
            "plate": plate, "offense": okey, "section": o["section"],
            "lat": lat, "lon": lon, "speed_kmh": self.latest_speed * 3.6,
            "g_dyn": self.latest_g, "recipients": to, "subject": subj,
            "evidence": self.evidence_path,
            "evidence_hash": EvidenceHasher.hash_file(self.evidence_path) if self.evidence_path else "",
        }

        sent = False
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
                # Phase 3: Queue for offline retry
                if self._offline_queue:
                    report_record["body"] = body
                    self._offline_queue.enqueue(report_record)
                    self._popup("Queued", "No connection. Report queued for retry.")
                else:
                    self._popup("Failed", str(e))
                return
        if sent:
            # Phase 2: Log the sent report
            if self._report_log:
                report_record["status"] = "sent"
                self._report_log.append(report_record)
            self._popup("Ready", "Email app opened.")

    # ── Phase 3: Queued report sender callback ──────────────────────────
    def _send_queued_report(self, report):
        """Attempt to send a queued report. Returns True on success."""
        if plyer_email is None:
            return False
        try:
            to = report.get("recipients", [])
            subj = report.get("subject", "Sentinel-X Report")
            body = report.get("body", "")
            if not to or not body:
                return False
            plyer_email.send(recipient=to, subject=subj, text=body, create_chooser=False)
            # Log the sent report
            if self._report_log:
                report["status"] = "sent_from_queue"
                self._report_log.append(report)
            return True
        except Exception:
            return False

    def _popup(self, t, m):
        Popup(title=t, content=Label(text=m, halign="left", valign="top", text_size=(dp(250), None)),
              size_hint=(.82, .32)).open()


class SentinelXApp(App):
    def build(self):
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
        if plyer_accel:
            try:
                plyer_accel.disable()
            except Exception:
                pass


if __name__ == "__main__":
    SentinelXApp().run()
