# -*- coding: utf-8 -*-
"""
Sentinel-X — Phase 6 citizen-empowerment logic (pure Python, no Kivy).

Kept Kivy/Android-free so it can be unit-tested directly and imported by main.py.
Android-only side effects (dialing, SMS, intents) live in main.py; this module
holds the testable building blocks: extra reporting channels, vehicle lookup
parsing, duplicate detection, localisation, hazard routing, local heatmap, and
privacy-blur helpers.
"""

import os
import re
import math
import time

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None
try:
    import numpy as np  # type: ignore
except Exception:
    np = None


# ─────────────────────────────────────────────────────────────────────────
# Directories: action-oriented reporting channels + emergency numbers
# ─────────────────────────────────────────────────────────────────────────
class CivicDirectory:
    """Extra reporting channels and helplines for citizen reports."""

    # Verified, widely-used traffic-police X/Twitter handles. Tagging these is
    # the channel that most reliably gets action in Indian cities. Best-effort;
    # empty entries simply omit a handle from the post.
    TWITTER = {
        "DL": ["@dtptraffic"],
        "MH": ["@MTPHereToHelp"],
        "KA": ["@blrcitytraffic"],
        "TS": ["@HYDTP"],
        "WB": ["@KolkataTraffic"],
        "TN": [],
        "UP": [],
        "HR": [],
        "KL": [],
        "GJ": [],
        "PB": [],
        "RJ": ["@jaipur_police"],
        "GA": ["@Goapolice"],
    }

    # National emergency / helpline numbers
    EMERGENCY = "112"        # unified emergency
    AMBULANCE = "108"        # ambulance
    ROAD_ACCIDENT = "1073"   # road accident / highway help
    WOMEN = "1091"           # women's helpline

    @staticmethod
    def handles(state_code):
        return list(CivicDirectory.TWITTER.get((state_code or "").upper(), []))


# ─────────────────────────────────────────────────────────────────────────
# Multi-channel report composition (X/Twitter, WhatsApp)
# ─────────────────────────────────────────────────────────────────────────
class ReportChannels:
    """Builds share text and deep-link URLs for X/Twitter and WhatsApp."""

    @staticmethod
    def compose(plate, offense_label, location, state_code):
        parts = ["Traffic violation reported via Sentinel-X:"]
        parts.append("Vehicle %s" % (plate or "?"))
        if offense_label:
            parts.append("- %s" % offense_label)
        if location:
            parts.append("at %s" % location)
        text = " ".join(parts).rstrip(".") + "."
        handles = CivicDirectory.handles(state_code)
        if handles:
            text += " " + " ".join(handles)
        text += " #RoadSafety"
        return text

    @staticmethod
    def _quote(text):
        from urllib.parse import quote
        return quote(text or "")

    @staticmethod
    def twitter_url(text):
        return "https://twitter.com/intent/tweet?text=" + ReportChannels._quote(text)

    @staticmethod
    def whatsapp_url(text, number=""):
        num = re.sub(r"[^0-9]", "", number or "")
        q = ReportChannels._quote(text)
        return "https://wa.me/%s?text=%s" % (num, q) if num else "https://wa.me/?text=" + q


# ─────────────────────────────────────────────────────────────────────────
# Optional VAHAN-style vehicle lookup (RC / insurance / PUC / challans)
# ─────────────────────────────────────────────────────────────────────────
class VehicleLookup:
    """Look up vehicle details from a plate via a configurable HTTP endpoint.

    There is no official free public VAHAN API, so the provider URL is read
    from the SENTINELX_VAHAN_URL env var (or set_endpoint()). The endpoint must
    accept a ``plate`` query parameter and return JSON. Degrades gracefully when
    unset or offline — it never fabricates data.
    """

    ENDPOINT = os.environ.get("SENTINELX_VAHAN_URL", "")

    @classmethod
    def set_endpoint(cls, url):
        cls.ENDPOINT = url or ""

    @classmethod
    def available(cls):
        return bool(cls.ENDPOINT)

    @staticmethod
    def normalize_plate(plate):
        return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())

    @classmethod
    def lookup(cls, plate):
        p = cls.normalize_plate(plate)
        if not p:
            return {"ok": False, "error": "empty plate"}
        if not cls.ENDPOINT:
            return {"ok": False, "error": "no provider configured"}
        try:
            import urllib.request
            import json as _json
            sep = "&" if "?" in cls.ENDPOINT else "?"
            url = cls.ENDPOINT + sep + "plate=" + p
            with urllib.request.urlopen(url, timeout=8) as r:
                data = _json.loads(r.read().decode("utf-8", "replace"))
            return cls.parse(data)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def parse(data):
        if not isinstance(data, dict):
            return {"ok": False, "error": "bad response"}

        def g(*keys):
            for k in keys:
                v = data.get(k)
                if v:
                    return str(v)
            return ""

        return {
            "ok": True,
            "owner": g("owner", "owner_name", "ownerName"),
            "model": g("model", "maker_model", "vehicle", "makerModel"),
            "rc_status": g("rc_status", "status", "rcStatus"),
            "insurance": g("insurance", "insurance_upto", "insuranceUpto", "insurance_validity"),
            "puc": g("puc", "puc_upto", "pucUpto", "pucc_upto"),
            "registered": g("registration_date", "reg_date", "registrationDate"),
        }


# ─────────────────────────────────────────────────────────────────────────
# Duplicate / spam guard
# ─────────────────────────────────────────────────────────────────────────
def haversine_m(la1, lo1, la2, lo2):
    """Great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = math.radians(la1), math.radians(la2)
    dp = math.radians(la2 - la1)
    dl = math.radians(lo2 - lo1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


class DuplicateGuard:
    """Flags a near-duplicate of an existing report (same plate + offense,
    close in time and space) to deter accidental/spam re-submission."""

    WINDOW_SEC = 600.0   # 10 minutes
    RADIUS_M = 150.0

    @staticmethod
    def is_duplicate(entries, plate, offense, lat, lon, now_ts=None):
        now_ts = time.time() if now_ts is None else now_ts
        p = (plate or "").upper().strip()
        for e in reversed(entries or []):
            if (e.get("plate", "").upper().strip() != p
                    or e.get("offense", "") != offense):
                continue
            ts = e.get("ts")
            if ts is None:
                continue
            if now_ts - float(ts) > DuplicateGuard.WINDOW_SEC:
                break
            d = haversine_m(lat, lon, float(e.get("lat", 0.0)), float(e.get("lon", 0.0)))
            if d <= DuplicateGuard.RADIUS_M:
                return True
        return False


# ─────────────────────────────────────────────────────────────────────────
# Localisation (English + Hindi for key strings)
# ─────────────────────────────────────────────────────────────────────────
class I18N:
    """Minimal runtime translation for Python-set strings (popups, labels)."""

    LANG = "en"
    SUPPORTED = ("en", "hi")
    STRINGS = {
        "hi": {
            "Plate": "नंबर प्लेट",
            "Offense": "अपराध",
            "Notes": "टिप्पणी",
            "SCAN": "स्कैन",
            "CAPTURE": "कैप्चर",
            "SEND": "भेजें",
            "CLEAR": "साफ़ करें",
            "Missing": "अधूरा",
            "Enter plate number.": "नंबर प्लेट दर्ज करें।",
            "Select a violation.": "उल्लंघन चुनें।",
            "Ready": "तैयार",
            "Email app opened.": "ईमेल ऐप खुल गया।",
            "Duplicate": "डुप्लिकेट",
            "Saved!": "सहेजा गया!",
            "No route": "कोई मार्ग नहीं",
        },
    }

    @classmethod
    def set_lang(cls, lang):
        cls.LANG = lang if lang in cls.SUPPORTED else "en"

    @classmethod
    def tr(cls, s):
        if cls.LANG == "en":
            return s
        return cls.STRINGS.get(cls.LANG, {}).get(s, s)


# ─────────────────────────────────────────────────────────────────────────
# Road-hazard / municipal reporting categories
# ─────────────────────────────────────────────────────────────────────────
class HazardReport:
    """Non-traffic civic hazards routed to municipal/PWD grievance channels.

    Email targets vary by city and are best configured per deployment; the
    national CPGRAMS grievance portal is provided as a universal fallback.
    """

    CATEGORIES = [
        "Pothole / damaged road",
        "Broken / missing traffic signal",
        "Missing / damaged signage",
        "Waterlogging / flooding",
        "Footpath encroachment",
        "Blocked accessibility ramp",
        "Broken streetlight",
        "Open manhole / hazard",
    ]

    CPGRAMS_PORTAL = "https://pgportal.gov.in/"

    @staticmethod
    def subject(category, location):
        return "[Civic Hazard] %s at %s" % (category, location or "reported location")

    @staticmethod
    def body(category, lat, lon, location, notes=""):
        lines = [
            "CIVIC HAZARD REPORT (via Sentinel-X)",
            "Category: %s" % category,
            "Location: %s" % (location or "-"),
            "GPS: %.6f, %.6f" % (lat, lon),
            "Map: https://maps.google.com/?q=%.6f,%.6f" % (lat, lon),
        ]
        if notes:
            lines.append("Notes: %s" % notes)
        lines.append("")
        lines.append("Submitted by a citizen for prompt resolution.")
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# Emergency / Good-Samaritan text helpers (dialing/SMS done in main.py)
# ─────────────────────────────────────────────────────────────────────────
class Emergency:
    CRASH_G = 12.0   # crash-level |a - g| in m/s^2 (well above harsh-brake)

    @staticmethod
    def maps_link(lat, lon):
        return "https://maps.google.com/?q=%.6f,%.6f" % (lat, lon)

    @staticmethod
    def sos_text(lat, lon):
        return ("SOS - I need help. Live location: %s (sent via Sentinel-X)"
                % Emergency.maps_link(lat, lon))

    @staticmethod
    def good_samaritan_text(lat, lon):
        return ("Accident reported. Location: %s. Reporting under Good Samaritan "
                "protection (MVA Sec.134A). Please dispatch help."
                % Emergency.maps_link(lat, lon))


# ─────────────────────────────────────────────────────────────────────────
# Local violation heatmap (offline; true crowdsourcing needs a backend)
# ─────────────────────────────────────────────────────────────────────────
class ViolationHeatmap:
    """Aggregates this device's report log into a coarse density grid."""

    CELL = 0.01  # ~1.1 km cells

    @staticmethod
    def hotspots(entries, top=5):
        from collections import Counter
        c = Counter()
        for e in entries or []:
            la, lo = e.get("lat"), e.get("lon")
            if la is None or lo is None:
                continue
            key = (round(float(la) / ViolationHeatmap.CELL),
                   round(float(lo) / ViolationHeatmap.CELL))
            c[key] += 1
        out = []
        for (gy, gx), n in c.most_common(top):
            out.append({
                "lat": gy * ViolationHeatmap.CELL,
                "lon": gx * ViolationHeatmap.CELL,
                "count": n,
            })
        return out


# ─────────────────────────────────────────────────────────────────────────
# Privacy: blur bystander faces and non-target plate-like regions
# ─────────────────────────────────────────────────────────────────────────
class PrivacyBlur:
    """Blur faces (and optionally other plates) in evidence before sharing."""

    @staticmethod
    def _face_cascade():
        if cv2 is None:
            return None
        try:
            base = getattr(getattr(cv2, "data", None), "haarcascades", None)
            if not base:
                return None
            casc = cv2.CascadeClassifier(base + "haarcascade_frontalface_default.xml")
            return None if casc.empty() else casc
        except Exception:
            return None

    @staticmethod
    def _blur_region(img, x, y, w, h):
        H, W = img.shape[:2]
        x, y = max(0, int(x)), max(0, int(y))
        w, h = min(int(w), W - x), min(int(h), H - y)
        if w <= 0 or h <= 0:
            return img
        roi = img[y:y + h, x:x + w]
        if roi.size == 0:
            return img
        k = max(15, (w // 3) | 1)
        img[y:y + h, x:x + w] = cv2.GaussianBlur(roi, (k, k), 0)
        return img

    @staticmethod
    def blur_faces(bgr):
        """Blur detected faces. Returns the image (unchanged if cv2/cascade absent)."""
        if cv2 is None or np is None or bgr is None:
            return bgr
        casc = PrivacyBlur._face_cascade()
        if casc is None:
            return bgr
        try:
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            for (x, y, w, h) in casc.detectMultiScale(gray, 1.1, 5, minSize=(24, 24)):
                bgr = PrivacyBlur._blur_region(bgr, x, y, w, h)
        except Exception:
            pass
        return bgr


# ─────────────────────────────────────────────────────────────────────────
# Over-the-air update manifest (pure logic; network/install live in main.py)
# ─────────────────────────────────────────────────────────────────────────
class UpdateManifest:
    """Parses the update.json published by CI and decides if an update applies.

    Fully silent forced updates are not possible for sideloaded Android apps
    (only Play Store / MDM / root can do that), so the app uses this to detect a
    newer build, then auto-downloads and prompts the user for a one-tap install.
    """

    # Stable URL of the latest published manifest (GitHub Releases "latest").
    DEFAULT_URL = (
        "https://github.com/ankitjha67/SentinelX-Build/releases/latest/download/update.json"
    )

    @staticmethod
    def parse(data):
        if not isinstance(data, dict):
            return None
        try:
            return {
                "version": str(data.get("version", "")),
                "version_code": int(data.get("version_code") or 0),
                "url": str(data.get("url", "")),
                "notes": str(data.get("notes", "")),
                "sha256": str(data.get("sha256", "")),
            }
        except Exception:
            return None

    @staticmethod
    def is_newer(current_code, manifest):
        """True only when the manifest has a strictly higher code and a URL."""
        if not manifest:
            return False
        try:
            return (int(manifest.get("version_code", 0)) > int(current_code or 0)
                    and bool(manifest.get("url")))
        except Exception:
            return False
