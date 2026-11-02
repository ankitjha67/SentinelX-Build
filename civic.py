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
    """Police reporting channels per state/UT, keyed by RTO registration code.

    Every email below was seen on an official government page (Nov 2026),
    recorded in SOURCES. Where a state publishes no traffic-specific inbox,
    the closest official channel is used and labelled in the comment. Some
    official channels are Gmail addresses (e.g. Goa's Traffic Sentinel
    scheme); they are included only because an official page lists them.
    States with no published email at all are in NO_EMAIL, never guessed.
    """

    EMAILS = {
        # ── States with a traffic-branch address ─────────────────────────
        "DL": ["grievance.traffic@delhipolice.gov.in"],               # Delhi Traffic Police grievances
        "MH": ["cp.mumbai.jtcp.traf@mahapolice.gov.in",               # Jt CP Traffic, Mumbai
               "adg.traffic.hsp@mahapolice.gov.in"],                  # ADGP Traffic (Highway Police), statewide
        "KA": ["automationpubbcp@ksp.gov.in"],                        # Bengaluru TP citizen violation inbox
        "UP": ["dirtraffic@nic.in"],                                  # UP Traffic Directorate (traffic/challan complaints)
        "HR": ["sp.traffic@hry.nic.in",                               # SP Traffic, Haryana
               "dcp.trafficggn@hry.nic.in"],                          # DCP Traffic, Gurugram
        "KL": ["sptrafficsz.pol@kerala.gov.in",                       # SP Traffic, South Zone
               "sptrafficnz.pol@kerala.gov.in"],                      # SP Traffic, North Zone
        "GJ": ["dcp-traffic-ahd@gujarat.gov.in",                      # DCP Traffic, Ahmedabad
               "dgp-stb-br@gujarat.gov.in"],                          # IGP State Traffic Branch
        "WB": ["dctp@kolkatatrafficpolice.gov.in"],                   # DC Traffic, Kolkata
        "TS": ["jtcp-trf-hyd@tspolice.gov.in",                        # Jt CP Traffic, Hyderabad
               "jtcp-cyb@tspolice.gov.in"],                           # Jt CP Traffic, Cyberabad
        "PB": ["igp.traffic.police@punjab.gov.in",                    # IGP Traffic, Punjab
               "tfcwing.police@punjab.gov.in"],                       # Punjab Police Traffic Wing
        "RJ": ["adgp.traffic@rajpolice.gov.in"],                      # ADGP Traffic, Rajasthan
        "GA": ["sptrafficgoa@gmail.com"],                             # Goa Traffic Sentinel scheme (official)
        "MP": ["dcp.traffic.bhopal@mppolice.gov.in",                  # DCP Traffic, Bhopal
               "dcp.traffic.indore@mppolice.gov.in"],                 # DCP Traffic, Indore
        "UK": ["sptrfdad.ukp@uttarakhandpolice.uk.gov.in"],           # SP Traffic, Dehradun
        "CH": ["psspst@chd.nic.in"],                                  # SSP Security & Traffic, Chandigarh
        "JK": ["igtraffic@jkpolice.gov.in"],                          # IGP Traffic, J&K
        "LA": ["sp-traffic@police.ladakh.gov.in"],                    # Traffic Police, Leh
        "BR": ["adgtraffic-bih@gov.in",                               # ADG Traffic, Bihar
               "sptraffic-bih@gov.in"],                               # SP Traffic, Patna
        "JH": ["sptraffic-ranchi@jhpolice.gov.in"],                   # SP Traffic, Ranchi
        "OD": ["dcp-traffic.odpol@od.gov.in"],                        # DCP Traffic, Bhubaneswar-Cuttack
        "TR": ["traffic@tripurapolice.nic.in"],                       # Tripura Traffic Police
        "PY": ["ssptraffic@py.gov.in"],                               # SSP Traffic, Puducherry
        # ── No traffic inbox published: nearest official police channel ──
        "AP": ["cp@vza.appolice.gov.in",                              # Commissioner, Vijayawada
               "cp@vspc.appolice.gov.in"],                            # Commissioner, Visakhapatnam
        "AS": ["jcp-guw@assampolice.gov.in"],                         # Joint CP, Guwahati
        "HP": ["dgp-hp@nic.in"],                                      # DGP office, HP
        "SK": ["pcr@sikkimpolice.nic.in"],                            # Police Control Room, Sikkim
        "ML": ["phq-meg@nic.in"],                                     # Police HQ, Meghalaya
        "AR": ["cc-polita-arn@nic.in"],                               # Police HQ control room, Itanagar
        "MN": ["dgcrmanipur100@gmail.com"],                           # DG Control Room, Imphal (official)
        "NL": ["scrb-ngl@nic.in"],                                    # Police HQ, Kohima
        "LD": ["lak-sop@nic.in"],                                     # SP Lakshadweep
        "DD": ["sp-daman-dd@nic.in",                                  # SP Daman
               "sp-sil-dnh@nic.in"],                                  # SP Dadra & Nagar Haveli
    }

    # City traffic offices that differ from the state default. Inside a
    # city's radius the report goes to that city's traffic wing instead of
    # the state list (e.g. Pune vs Mumbai, Cyberabad vs Hyderabad).
    # (name, state, lat, lon, radius_km, emails, official source)
    CITIES = [
        ("Mumbai", "MH", 19.0760, 72.8777, 25, ["cp.mumbai.jtcp.traf@mahapolice.gov.in",
                                              "multimediacell.traffic@mahapolice.gov.in"],
         "https://trafficpolicemumbai.maharashtra.gov.in/en/contact-us/"),
        ("Pune", "MH", 18.5204, 73.8567, 20, ["dcptraffic.pune@nic.in"],
         "https://punepolice.gov.in/about-us/senior-officers"),
        ("Bengaluru", "KA", 12.9716, 77.5946, 25, ["automationpubbcp@ksp.gov.in"],
         "https://btp.karnataka.gov.in/105/contactless-enforcement/en"),
        ("Hyderabad", "TS", 17.3850, 78.4867, 10, ["jtcp-trf-hyd@tspolice.gov.in"],
         "https://www.hyderabadpolice.gov.in/Important_Contacts.html"),
        ("Cyberabad", "TS", 17.4483, 78.3915, 15, ["jtcp-cyb@tspolice.gov.in"],
         "https://cyberabadpolice.gov.in/Preview?page_id=54"),
        ("Ahmedabad", "GJ", 23.0225, 72.5714, 20, ["dcp-traffic-ahd@gujarat.gov.in",
                                                 "adcp-traffic-ahd@gujarat.gov.in"],
         "https://police.gujarat.gov.in/upload/IPS_Civil_List-2026_Web18022026.pdf"),
        ("Surat", "GJ", 21.1702, 72.8311, 18, ["dcp-traffic-sur@gujarat.gov.in"],
         "https://police.gujarat.gov.in/upload/IPS_Civil_List-2026_Web18022026.pdf"),
        ("Rajkot", "GJ", 22.3039, 70.8022, 15, ["dcp-trf-raj@gujarat.gov.in"],
         "https://police.gujarat.gov.in/upload/IPS_Civil_List-2026_Web18022026.pdf"),
        ("Bhopal", "MP", 23.2599, 77.4126, 18, ["dcp.traffic.bhopal@mppolice.gov.in"],
         "https://bhopal.mppolice.gov.in/contact/"),
        ("Indore", "MP", 22.7196, 75.8577, 18, ["dcp.traffic.indore@mppolice.gov.in"],
         "https://indore.mppolice.gov.in/contact/"),
        ("Gurugram", "HR", 28.4595, 77.0266, 15, ["dcp.trafficggn@hry.nic.in"],
         "https://haryanapolice.gov.in/static/TelephoneDirectory_cpggn.aspx"),
        ("Kochi", "KL", 9.9312, 76.2673, 15, ["dcpekm.pol@kerala.gov.in"],
         "https://kochicity.keralapolice.gov.in/contacts"),
        ("Thiruvananthapuram", "KL", 8.5241, 76.9366, 12, ["dcptvclo.pol@kerala.gov.in"],
         "https://tvmcity.keralapolice.gov.in/contacts"),
        ("Patna", "BR", 25.5941, 85.1376, 15, ["sptraffic-bih@gov.in"],
         "https://police.bihar.gov.in/En/Traffic.aspx"),
        ("Ranchi", "JH", 23.3441, 85.3096, 15, ["sptraffic-ranchi@jhpolice.gov.in"],
         "https://www.jhpolice.gov.in/imp-contacts"),
        ("Bhubaneswar-Cuttack", "OD", 20.3700, 85.8500, 22, ["dcp-traffic.odpol@od.gov.in"],
         "https://bhubaneswarcuttackpolice.gov.in/important-contact-number"),
        ("Dehradun", "UK", 30.3165, 78.0322, 12, ["sptrfdad.ukp@uttarakhandpolice.uk.gov.in"],
         "https://dehraduntrafficpolice.uk.gov.in/WebInformationManager"),
        ("Kolkata", "WB", 22.5726, 88.3639, 15, ["dctp@kolkatatrafficpolice.gov.in"],
         "https://www.kolkatatrafficpolice.gov.in/"),
        ("Vijayawada", "AP", 16.5062, 80.6480, 15, ["cp@vza.appolice.gov.in"],
         "https://ntr.ap.gov.in/about-district/whos-who/"),
        ("Visakhapatnam", "AP", 17.6868, 83.2185, 18, ["cp@vspc.appolice.gov.in"],
         "https://negd.gov.in/isl/Directory/statedata/716"),
        ("Guwahati", "AS", 26.1445, 91.7362, 15, ["jcp-guw@assampolice.gov.in"],
         "https://police.assam.gov.in/contact-us"),
        ("Jaipur", "RJ", 26.9124, 75.7873, 18, ["cp.jaipur@rajpolice.gov.in"],
         "https://police.rajasthan.gov.in/portal/Directory"),
    ]

    # Official police apps that turn citizen photo reports into challans.
    # Package ids verified on Google Play (developer = the police force) and
    # linked from the force's site. Keyed by CITIES name or state code.
    POLICE_APPS = {
        "DL": ("com.dtp.trafficsentinel", "Traffic Prahari",
               "https://traffic.delhipolice.gov.in/en/node/67"),
        "Bengaluru": ("com.BTPASTraM", "BTP ASTraM",
                      "https://btp.karnataka.gov.in/en"),
        "Mumbai": ("com.sparken.mum.policealert", "Mumbai Traffic Police App",
                   "https://trafficpolicemumbai.maharashtra.gov.in/"),
    }

    # Municipal grievance channels for road hazards (potholes, streetlights,
    # waterlogging, manholes): (name, lat, lon, radius_km or state code,
    # Play package or "", helpline or "", web or "", official source).
    CIVIC_CHANNELS = [
        ("Delhi (MCD 311)", 28.6139, 77.2090, "DL", "com.everythingcivic.mcd",
         "155305", "https://mcd.everythingcivic.com", "https://mcdonline.nic.in/portal"),
        ("Mumbai (MyBMC)", 19.0760, 72.8777, 25, "in.cdac.gov.mgov.mcgm", "", "",
         "Play developer: BMC (mcgm.gov.in)"),
        ("Bengaluru (Sahaaya 2.0)", 12.9716, 77.5946, 25, "com.nammabengaluruNew.org",
         "", "", "Play developer: BBMP (bbmp.gov.in)"),
        ("Chennai (Namma Chennai)", 13.0827, 80.2707, 25, "com.ceedeev.grivenancev2",
         "1913", "", "https://chennaicorporation.gov.in/gcc/"),
        ("Hyderabad (GHMC)", 17.3850, 78.4867, 22, "cgg.gov.ghmc", "04021111111",
         "https://igs.ghmc.gov.in/operator/send_otp_mobile", "https://www.ghmc.gov.in/"),
        ("Kolkata (KMC)", 22.5726, 88.3639, 15, "com.kmc.app", "", "",
         "Play developer: KMC (kmcgov.in)"),
        ("Pune (PMC CARE)", 18.5204, 73.8567, 20, "in.gov.pmc.pmccare", "", "",
         "Play developer: Pune Municipal Corporation"),
        ("Ahmedabad (AMC CCRS)", 23.0225, 72.5714, 20, "com.amplvb.ccrs", "155303",
         "https://www.amccrs.com", "https://ahmedabadcity.gov.in/"),
        ("Jaipur (Nagar Nigam)", 26.9124, 75.7873, 18, "com.oispl.citizen_app",
         "01412747400", "", "https://jaipurmc.org/"),
        ("Patna (Clean Patna)", 25.5941, 85.1376, 15, "com.citizen.grievance.app",
         "06122223791", "", "https://pmc.bihar.gov.in/"),
    ]

    @staticmethod
    def police_app_for(state_code, city_name=""):
        apps = CivicDirectory.POLICE_APPS
        return apps.get(city_name) or apps.get(CivicDirectory.canonical(state_code))

    @staticmethod
    def civic_channel_for(lat, lon, state_code=""):
        """Nearest municipal channel covering (lat, lon), as a dict or None."""
        best, best_d = None, float("inf")
        for name, cla, clo, area, pkg, phone, web, src in CivicDirectory.CIVIC_CHANNELS:
            d = haversine_m(lat, lon, cla, clo)
            covers = (area == CivicDirectory.canonical(state_code)
                      if isinstance(area, str) else d <= area * 1000.0)
            if covers and d < best_d:
                best_d = d
                best = {"name": name, "package": pkg, "phone": phone, "web": web,
                        "source": src}
        return best

    # Official WhatsApp numbers for photo reports (international format).
    WHATSAPP = {
        "GA": ("917875756110", "Goa Traffic Sentinel scheme, citizen.goapolice.gov.in"),
        "TR": ("919402303100", "https://trafficpolice.tripura.gov.in/contact-us"),
        "DL": ("918750871493", "Delhi Traffic Police official Facebook page"),
    }

    # No official email found anywhere: point the reporter to these instead.
    NO_EMAIL = {
        "TN": "Greater Chennai Traffic Police on X (@ChennaiTraffic) or the "
              "TN Police citizen portal (police.tn.gov.in/citizenportal)",
        "CG": "Chhattisgarh Police traffic helpline 1073 or CPGRAMS",
        "MZ": "Mizoram Police feedback form (police.mizoram.gov.in) or CPGRAMS",
        "AN": "A&N Traffic Police WhatsApp 9531892228 or CPGRAMS",
    }

    CPGRAMS_PORTAL = "https://pgportal.gov.in/"

    SOURCES = {
        "DL": "https://traffic.delhipolice.gov.in/en/contact-us",
        "MH": "https://trafficpolicemumbai.maharashtra.gov.in/en/contact-us/ ; "
              "https://highwaypolice.maharashtra.gov.in/contact-us/",
        "KA": "https://btp.karnataka.gov.in/105/contactless-enforcement/en",
        "UP": "https://uppolice.gov.in/pages/en/topmenu/en-contact-us/en-contact-us",
        "HR": "https://haryanapolice.gov.in/static/TelephoneDirectory_Traffic.aspx ; "
              "https://haryanapolice.gov.in/static/TelephoneDirectory_cpggn.aspx",
        "KL": "https://keralapolice.gov.in/page/rank-wise-details",
        "GJ": "https://police.gujarat.gov.in/upload/IPS_Civil_List-2026_Web18022026.pdf",
        "WB": "https://www.kolkatatrafficpolice.gov.in/",
        "TS": "https://www.hyderabadpolice.gov.in/Important_Contacts.html ; "
              "https://cyberabadpolice.gov.in/Preview?page_id=54",
        "PB": "https://www.punjabpolice.gov.in/en/contact-us/punjab-police-officer/",
        "RJ": "https://police.rajasthan.gov.in/portal/Directory",
        "GA": "https://citizen.goapolice.gov.in/ (Traffic Sentinel Scheme FAQ)",
        "MP": "https://bhopal.mppolice.gov.in/contact/ ; https://indore.mppolice.gov.in/contact/",
        "UK": "https://dehraduntrafficpolice.uk.gov.in/WebInformationManager",
        "CH": "https://negd.gov.in/isl/Directory/statedata/572",
        "JK": "https://jkpolice.gov.in/JK-Traffic-Police",
        "LA": "https://police.ladakh.gov.in/pages/contact.html",
        "BR": "https://police.bihar.gov.in/En/Traffic.aspx",
        "JH": "https://www.jhpolice.gov.in/imp-contacts",
        "OD": "https://bhubaneswarcuttackpolice.gov.in/important-contact-number",
        "TR": "https://trafficpolice.tripura.gov.in/contact-us",
        "PY": "https://police.py.gov.in/senior-officer-address.php",
        "AP": "https://ntr.ap.gov.in/about-district/whos-who/ ; "
              "https://negd.gov.in/isl/Directory/statedata/716",
        "AS": "https://police.assam.gov.in/contact-us",
        "HP": "https://citizenportal.hppolice.gov.in/citizen/contactus.htm",
        "SK": "https://police.sikkim.gov.in/visitor/citizencharter",
        "ML": "https://megpolice.gov.in/telephone-directory",
        "AR": "https://arunpol.nic.in/contactus.html",
        "MN": "https://manipurpolice.gov.in/",
        "NL": "https://police.nagaland.gov.in/contact-us/",
        "LD": "https://www.lakshadweeppolice.gov.in/downloads/citizen_charter_v2.pdf",
        "DD": "https://police.ddd.gov.in/?p=194",
    }

    # Traffic / state police X handles. Tagging these is the channel that
    # most reliably gets action. New entries are handles linked from the
    # force's own official website; empty lists simply omit a tag.
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
        "MP": ["@MPPoliceDeptt"],
        "UK": ["@sptrafficdoon", "@uttarakhandcops"],
        "HP": ["@himachalpolice"],
        "CH": ["@ChdPol"],
        "LA": ["@trafficpoliceLA"],
        "BR": ["@bihar_police"],
        "JH": ["@jharkhandpolice"],
        "SK": ["@sikkim_police"],
        "ML": ["@MeghalayaPolice"],
        "AR": ["@dgppradesh"],
        "MN": ["@manipur_police"],
        "PY": ["@PuducheryPolice"],
        "DD": ["@dddutpolice"],
    }

    STATE_NAME_TO_CODE = {
        "Delhi": "DL", "National Capital Territory of Delhi": "DL",
        "Maharashtra": "MH", "Karnataka": "KA", "Tamil Nadu": "TN",
        "Uttar Pradesh": "UP", "Haryana": "HR", "Kerala": "KL",
        "Gujarat": "GJ", "West Bengal": "WB", "Telangana": "TS",
        "Punjab": "PB", "Rajasthan": "RJ", "Goa": "GA",
        "Madhya Pradesh": "MP", "Chhattisgarh": "CG", "Himachal Pradesh": "HP",
        "Uttarakhand": "UK", "Chandigarh": "CH", "Jammu and Kashmir": "JK",
        "Ladakh": "LA", "Bihar": "BR", "Jharkhand": "JH", "Odisha": "OD",
        "Assam": "AS", "Sikkim": "SK", "Meghalaya": "ML", "Tripura": "TR",
        "Manipur": "MN", "Mizoram": "MZ", "Nagaland": "NL",
        "Arunachal Pradesh": "AR", "Andhra Pradesh": "AP", "Puducherry": "PY",
        "Andaman and Nicobar Islands": "AN", "Lakshadweep": "LD",
        "Dadra and Nagar Haveli and Daman and Diu": "DD",
    }
    # Legacy registration codes that route like their canonical state
    # (Odisha plates before 2012 read "OR"; old DNH plates read "DN").
    CODE_ALIASES = {"OR": "OD", "DN": "DD"}

    # National emergency / helpline numbers
    EMERGENCY = "112"        # unified emergency
    AMBULANCE = "108"        # ambulance
    ROAD_ACCIDENT = "1073"   # road accident / highway help
    WOMEN = "1091"           # women's helpline

    @staticmethod
    def canonical(state_code):
        sc = (state_code or "").upper()
        return CivicDirectory.CODE_ALIASES.get(sc, sc)

    @staticmethod
    def emails(state_code):
        return list(CivicDirectory.EMAILS.get(CivicDirectory.canonical(state_code), []))

    # ── Over-the-air directory updates ───────────────────────────────────
    # CI publishes this file with each release (see export_directory), so a
    # changed police address reaches devices without a new APK.
    DIRECTORY_URL = ("https://github.com/ankitjha67/SentinelX-Build/releases/"
                     "latest/download/directory.json")
    _EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

    @classmethod
    def export_directory(cls):
        return {
            "schema": 1,
            "emails": cls.EMAILS,
            "no_email": cls.NO_EMAIL,
            "whatsapp": {k: list(v) for k, v in cls.WHATSAPP.items()},
            "cities": [list(c) for c in cls.CITIES],
        }

    @classmethod
    def apply_overrides(cls, data):
        """Validate and apply a downloaded directory. Anything malformed is
        rejected wholesale (returns False) so a bad file can never blank or
        corrupt routing; unknown state codes are ignored."""
        try:
            if not isinstance(data, dict) or data.get("schema") != 1:
                return False
            codes = set(cls.STATE_NAME_TO_CODE.values())
            emails = {}
            for code, lst in data.get("emails", {}).items():
                if code not in codes:
                    continue
                if (not isinstance(lst, list) or not 1 <= len(lst) <= 5
                        or not all(isinstance(e, str) and cls._EMAIL_RE.match(e)
                                   for e in lst)):
                    return False
                emails[code] = list(lst)
            if len(emails) < len(cls.EMAILS) // 2:
                return False  # suspiciously small: keep the built-in copy
            cities = []
            for c in data.get("cities", []):
                name, state, la, lo, rad, lst, src = c
                if (state not in codes or not 1 <= float(rad) <= 60
                        or not all(cls._EMAIL_RE.match(e) for e in lst)):
                    return False
                cities.append((str(name), state, float(la), float(lo), float(rad),
                               list(lst), str(src)))
            wa = {}
            for code, (num, src) in data.get("whatsapp", {}).items():
                if code in codes and re.match(r"^\d{11,13}$", str(num)):
                    wa[code] = (str(num), str(src))
            no_email = {k: str(v) for k, v in data.get("no_email", {}).items()
                        if k in codes and k not in emails}
        except Exception:
            return False
        cls.EMAILS.clear()
        cls.EMAILS.update(emails)
        cls.NO_EMAIL.clear()
        cls.NO_EMAIL.update(no_email)
        cls.WHATSAPP.clear()
        cls.WHATSAPP.update(wa)
        if cities:
            cls.CITIES[:] = cities
        return True

    @staticmethod
    def city_for(lat, lon):
        """Nearest configured city whose radius contains (lat, lon), as a
        dict, or None. Overlapping cities resolve to the closer centre."""
        best, best_d = None, float("inf")
        for name, state, cla, clo, rad_km, emails, src in CivicDirectory.CITIES:
            d = haversine_m(lat, lon, cla, clo)
            if d <= rad_km * 1000.0 and d < best_d:
                best_d = d
                best = {"name": name, "state": state, "emails": list(emails),
                        "source": src, "distance_m": d}
        return best

    @staticmethod
    def handles(state_code):
        return list(CivicDirectory.TWITTER.get(CivicDirectory.canonical(state_code), []))


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
# Vehicle (RC) lookup — Masters India VAHAN API (+ optional generic fallback)
# ─────────────────────────────────────────────────────────────────────────
class VehicleLookup:
    """Vehicle / RC lookup via the Masters India VAHAN API.

    Masters India is auth-gated (https://docs.mastersindia.co): it needs a JWT
    and a Subid from your account. Provide them via set_credentials(), the
    SENTINELX_MI_* env vars, or a vahan.json in the app data dir. The default
    JWT is the (expired) demo token from the public docs, so a real token + Subid
    must be configured. It never fabricates data and surfaces the real API error
    (e.g. expired token) so misconfiguration is obvious. A generic GET endpoint
    (SENTINELX_VAHAN_URL) is supported as a fallback for self-hosted providers.
    """

    MI_URL = os.environ.get(
        "SENTINELX_MI_URL",
        "https://api-platform.mastersindia.co/api/v2/sbt/VAHAN/")
    # Authorization header value INCLUDING the "JWT " prefix. Default = expired
    # public demo token; replace with your own via config/env for production.
    MI_JWT = os.environ.get(
        "SENTINELX_MI_JWT",
        "JWT eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
        "eyJ1c2VyX2lkIjoxNDgsInVzZXJuYW1lIjoicHJhdGVla3JhaStkZW1vQG1hc3RlcnNpbmRpYS5jby"
        "IsImV4cCI6MTY5NjA0Njc4MCwiZW1haWwiOiJwcmF0ZWVrcmFpK2RlbW9AbWFzdGVyc2luZGlhLmNv"
        "Iiwib3JpZ19pYXQiOjE2OTU5NjAzODB9.zWJsCcqMd06X1aMjvXPQRqQGQddKjF6vpkOZgKFG_80")
    MI_SUBID = os.environ.get("SENTINELX_MI_SUBID", "")
    MI_PRODUCTID = os.environ.get("SENTINELX_MI_PRODUCTID", "arap")
    MI_MODE = os.environ.get("SENTINELX_MI_MODE", "Buyer")

    # Optional generic fallback endpoint (GET ?plate=, flat JSON)
    ENDPOINT = os.environ.get("SENTINELX_VAHAN_URL", "")

    @classmethod
    def set_credentials(cls, jwt=None, subid=None, productid=None, mode=None, url=None):
        if jwt:
            cls.MI_JWT = jwt if jwt.upper().startswith("JWT ") else "JWT " + jwt
        if subid is not None:
            cls.MI_SUBID = subid
        if productid:
            cls.MI_PRODUCTID = productid
        if mode:
            cls.MI_MODE = mode
        if url:
            cls.MI_URL = url

    @classmethod
    def set_endpoint(cls, url):
        cls.ENDPOINT = url or ""

    @classmethod
    def _mi_configured(cls):
        return bool(cls.MI_JWT and cls.MI_SUBID)

    @classmethod
    def available(cls):
        return cls._mi_configured() or bool(cls.ENDPOINT)

    @staticmethod
    def normalize_plate(plate):
        return re.sub(r"[^A-Z0-9]", "", (plate or "").upper())

    @classmethod
    def lookup(cls, plate):
        p = cls.normalize_plate(plate)
        if not p:
            return {"ok": False, "error": "empty plate"}
        if cls._mi_configured():
            return cls.lookup_mastersindia(p)
        if cls.ENDPOINT:
            return cls._lookup_generic(p)
        return {"ok": False, "error": "no provider configured"}

    @classmethod
    def lookup_mastersindia(cls, plate):
        p = cls.normalize_plate(plate)
        if not p:
            return {"ok": False, "error": "empty plate"}
        try:
            import urllib.request
            import urllib.error
            import json as _json
            body = _json.dumps({"vehiclenumber": p}).encode("utf-8")
            req = urllib.request.Request(cls.MI_URL, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
            req.add_header("Authorization", cls.MI_JWT)
            req.add_header("Subid", cls.MI_SUBID)
            req.add_header("Productid", cls.MI_PRODUCTID)
            req.add_header("Mode", cls.MI_MODE)
            with urllib.request.urlopen(req, timeout=12) as r:
                data = _json.loads(r.read().decode("utf-8", "replace"))
            return cls.parse_mastersindia(data)
        except urllib.error.HTTPError as e:
            msg = {
                400: "Bad request (check plate format)",
                401: "Unauthorized — set a valid Masters India JWT",
                403: "Forbidden — check JWT / Subid",
                500: "Provider server error",
                502: "Provider not responding",
            }.get(getattr(e, "code", 0), "HTTP %s" % getattr(e, "code", "error"))
            return {"ok": False, "error": msg}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def parse_mastersindia(data):
        """Parse the Masters India envelope (XML-in-JSON)."""
        if not isinstance(data, dict):
            return {"ok": False, "error": "bad response"}
        if str(data.get("error", "")).lower() == "true":
            return {"ok": False, "error": data.get("message", "request failed")}
        resp = data.get("response")
        if not isinstance(resp, list) or not resp:
            return {"ok": False, "error": data.get("message", "no data")}
        first = resp[0] if isinstance(resp[0], dict) else {}
        inner = first.get("response", "") or ""
        if "VehicleDetails" not in inner:
            return {"ok": False, "error": (inner.strip() or "vehicle not found")}
        return VehicleLookup._parse_vahan_xml(inner)

    @staticmethod
    def _parse_vahan_xml(xml_text):
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(xml_text.strip())
        except Exception as e:
            return {"ok": False, "error": "parse error: %s" % e}

        def t(tag):
            el = root.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        model = (t("rc_maker_desc") + " " + t("rc_maker_model")).strip()
        return {
            "ok": True,
            "plate": t("rc_regn_no"),
            "owner": t("rc_owner_name"),
            "model": model,
            "rc_status": t("rc_status"),
            "registered": t("rc_regn_dt"),
            "registered_at": t("rc_registered_at"),
            "insurance": t("rc_insurance_upto"),
            "insurer": t("rc_insurance_comp"),
            "puc": t("rc_pucc_upto"),
            "fitness": t("rc_fit_upto"),
            "tax": t("rc_tax_upto"),
            "fuel": t("rc_fuel_desc"),
            "vclass": t("rc_vh_class_desc"),
            "financer": t("rc_financer"),
            "blacklist": t("rc_blacklist_status"),
            "gvw": t("rc_gvw"),
        }

    @classmethod
    def _lookup_generic(cls, plate):
        try:
            import urllib.request
            import json as _json
            sep = "&" if "?" in cls.ENDPOINT else "?"
            url = cls.ENDPOINT + sep + "plate=" + plate
            with urllib.request.urlopen(url, timeout=8) as r:
                data = _json.loads(r.read().decode("utf-8", "replace"))
            return cls.parse(data)
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @staticmethod
    def parse(data):
        """Generic flat-JSON parser for a self-hosted fallback endpoint."""
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
    """Runtime UI translation: English, Hindi, Marathi, Tamil, Kannada, Bengali.

    Kivy's default font has no Indic glyphs and its renderer only shapes
    Indic scripts when given a HarfBuzz script tag, so each language carries
    the Android system Noto font and script code to render it with. Those
    fonts have no Latin letters, so translations must not contain any (the
    unit tests enforce this); text with plates/emails stays in the Latin
    font (see main.RootUI._popup).
    """

    LANG = "en"
    # code: (native name, Noto font family, HarfBuzz/ISO-15924 script)
    LANGS = {
        "en": ("English", None, "Zyyy"),
        "hi": ("हिंदी", "Devanagari", "Deva"),
        "mr": ("मराठी", "Devanagari", "Deva"),
        "ta": ("தமிழ்", "Tamil", "Taml"),
        "kn": ("ಕನ್ನಡ", "Kannada", "Knda"),
        "bn": ("বাংলা", "Bengali", "Beng"),
    }
    SUPPORTED = tuple(LANGS)
    FONT_DIR = "/system/fonts"

    STRINGS = {
        "hi": {
            "Report in official police app": "आधिकारिक पुलिस ऐप में रिपोर्ट करें",
            "Evidence pack (PDF)": "साक्ष्य पैक (पीडीएफ)", "RTI request for last report": "पिछली रिपोर्ट पर आरटीआई आवेदन",
            "MORE": "और", "HISTORY": "इतिहास", "SETTINGS": "सेटिंग्स",
            "Anonymous Reporter": "गुमनाम रिपोर्टर", "Night Mode": "रात्रि मोड",
            "CV Assist": "दृष्टि सहायता", "Plate OCR": "प्लेट पहचान",
            "VIOLATION REPORT": "उल्लंघन रिपोर्ट", "Plate": "नंबर प्लेट",
            "Offense": "अपराध", "Sign": "संकेत", "Notes": "टिप्पणी",
            "JURISDICTION ROUTING": "क्षेत्राधिकार", "SCAN": "स्कैन",
            "CAPTURE": "फ़ोटो", "SEND": "भेजें", "CLEAR": "साफ़ करें",
            "Plate OCR: standby": "प्लेट पहचान: तैयार", "Close": "बंद करें",
            "OK": "ठीक है", "Missing": "अधूरा",
            "Enter plate number.": "नंबर प्लेट दर्ज करें।",
            "Select a violation.": "उल्लंघन चुनें।", "Ready": "तैयार",
            "Email app opened.": "ईमेल ऐप खुल गया।", "Saved!": "सहेजा गया!",
            "Duplicate": "डुप्लिकेट", "No route": "कोई मार्ग नहीं",
            "History": "इतिहास", "No reports sent yet.": "अभी तक कोई रिपोर्ट नहीं भेजी गई।",
            "Language": "भाषा", "More - Citizen Tools": "और - नागरिक सुविधाएँ",
            "Share to X / Twitter": "एक्स / ट्विटर पर साझा करें",
            "Share to WhatsApp": "व्हाट्सऐप पर साझा करें",
            "WhatsApp traffic police (official no.)": "ट्रैफ़िक पुलिस व्हाट्सऐप (आधिकारिक नंबर)",
            "Vehicle lookup (RC/Insurance/PUC)": "वाहन जानकारी (आरसी/बीमा/प्रदूषण)",
            "Report a road hazard": "सड़क खतरे की रिपोर्ट",
            "SOS / Emergency": "आपातकाल", "Violation hotspots": "उल्लंघन हॉटस्पॉट",
            "Save last 15 s as video clip": "पिछले 15 सेकंड का वीडियो सहेजें",
            "Emergency contact (crash SOS)": "आपातकालीन संपर्क (दुर्घटना)",
            "Check for app updates": "ऐप अपडेट जाँचें",
            "Privacy blur (faces)": "चेहरे धुंधले करें", "ON": "चालू", "OFF": "बंद",
        },
        "mr": {
            "Report in official police app": "अधिकृत पोलीस ॲपमध्ये तक्रार करा",
            "Evidence pack (PDF)": "पुरावा संच (पीडीएफ)", "RTI request for last report": "मागील अहवालावर माहिती अधिकार अर्ज",
            "MORE": "अधिक", "HISTORY": "इतिहास", "SETTINGS": "सेटिंग्ज",
            "Anonymous Reporter": "निनावी तक्रारदार", "Night Mode": "रात्र मोड",
            "CV Assist": "दृष्टी सहाय्य", "Plate OCR": "प्लेट ओळख",
            "VIOLATION REPORT": "उल्लंघन अहवाल", "Plate": "नंबर प्लेट",
            "Offense": "गुन्हा", "Sign": "चिन्ह", "Notes": "टीप",
            "JURISDICTION ROUTING": "कार्यक्षेत्र", "SCAN": "स्कॅन",
            "CAPTURE": "फोटो", "SEND": "पाठवा", "CLEAR": "पुसा",
            "Plate OCR: standby": "प्लेट ओळख: तयार", "Close": "बंद करा",
            "OK": "ठीक आहे", "Missing": "अपूर्ण",
            "Enter plate number.": "नंबर प्लेट टाका.",
            "Select a violation.": "उल्लंघन निवडा.", "Ready": "तयार",
            "Email app opened.": "ईमेल ॲप उघडले.", "Saved!": "जतन केले!",
            "Duplicate": "पुनरावृत्ती", "No route": "मार्ग नाही",
            "History": "इतिहास", "No reports sent yet.": "अद्याप एकही अहवाल पाठवला नाही.",
            "Language": "भाषा", "More - Citizen Tools": "अधिक - नागरिक सुविधा",
            "Share to X / Twitter": "एक्स / ट्विटरवर शेअर करा",
            "Share to WhatsApp": "व्हॉट्सॲपवर शेअर करा",
            "WhatsApp traffic police (official no.)": "वाहतूक पोलीस व्हॉट्सॲप (अधिकृत क्रमांक)",
            "Vehicle lookup (RC/Insurance/PUC)": "वाहन माहिती (आरसी/विमा/प्रदूषण)",
            "Report a road hazard": "रस्त्यावरील धोक्याची तक्रार",
            "SOS / Emergency": "आणीबाणी", "Violation hotspots": "उल्लंघन ठिकाणे",
            "Save last 15 s as video clip": "मागील 15 सेकंदांचा व्हिडिओ जतन करा",
            "Emergency contact (crash SOS)": "आपत्कालीन संपर्क (अपघात)",
            "Check for app updates": "ॲप अपडेट तपासा",
            "Privacy blur (faces)": "चेहरे अस्पष्ट करा", "ON": "चालू", "OFF": "बंद",
        },
        "ta": {
            "Report in official police app": "அதிகாரப்பூர்வ காவல் செயலியில் புகாரளி",
            "Evidence pack (PDF)": "சான்று தொகுப்பு (பிடிஎஃப்)", "RTI request for last report": "கடைசி புகாருக்கு தகவல் உரிமை மனு",
            "MORE": "மேலும்", "HISTORY": "வரலாறு", "SETTINGS": "அமைப்புகள்",
            "Anonymous Reporter": "பெயரில்லா புகார்தாரர்", "Night Mode": "இரவு முறை",
            "CV Assist": "பார்வை உதவி", "Plate OCR": "பலகை அறிதல்",
            "VIOLATION REPORT": "விதிமீறல் புகார்", "Plate": "எண் பலகை",
            "Offense": "குற்றம்", "Sign": "அடையாளம்", "Notes": "குறிப்பு",
            "JURISDICTION ROUTING": "அதிகார வரம்பு", "SCAN": "ஸ்கேன்",
            "CAPTURE": "படம்", "SEND": "அனுப்பு", "CLEAR": "அழி",
            "Plate OCR: standby": "பலகை அறிதல்: தயார்", "Close": "மூடு",
            "OK": "சரி", "Missing": "குறைவு",
            "Enter plate number.": "வாகன எண்ணை உள்ளிடவும்.",
            "Select a violation.": "விதிமீறலைத் தேர்ந்தெடுக்கவும்.", "Ready": "தயார்",
            "Email app opened.": "மின்னஞ்சல் செயலி திறக்கப்பட்டது.",
            "Saved!": "சேமிக்கப்பட்டது!", "Duplicate": "நகல்",
            "No route": "வழி இல்லை", "History": "வரலாறு",
            "No reports sent yet.": "இதுவரை புகார் எதுவும் அனுப்பப்படவில்லை.",
            "Language": "மொழி", "More - Citizen Tools": "மேலும் - குடிமக்கள் கருவிகள்",
            "Share to X / Twitter": "எக்ஸ் / ட்விட்டரில் பகிர்",
            "Share to WhatsApp": "வாட்ஸ்அப்பில் பகிர்",
            "WhatsApp traffic police (official no.)": "போக்குவரத்து காவல் வாட்ஸ்அப் (அதிகாரப்பூர்வ எண்)",
            "Vehicle lookup (RC/Insurance/PUC)": "வாகன விவரம் (பதிவு/காப்பீடு/மாசு)",
            "Report a road hazard": "சாலை ஆபத்தைப் புகாரளி",
            "SOS / Emergency": "அவசரம்", "Violation hotspots": "விதிமீறல் இடங்கள்",
            "Save last 15 s as video clip": "கடைசி 15 விநாடி காணொளியைச் சேமி",
            "Emergency contact (crash SOS)": "அவசரத் தொடர்பு (விபத்து)",
            "Check for app updates": "செயலி புதுப்பிப்பைச் சரிபார்",
            "Privacy blur (faces)": "முகங்களை மங்கலாக்கு", "ON": "இயக்கு", "OFF": "அணை",
        },
        "kn": {
            "Report in official police app": "ಅಧಿಕೃತ ಪೊಲೀಸ್ ಆ್ಯಪ್‌ನಲ್ಲಿ ವರದಿ ಮಾಡಿ",
            "Evidence pack (PDF)": "ಸಾಕ್ಷ್ಯ ಸಂಗ್ರಹ (ಪಿಡಿಎಫ್)", "RTI request for last report": "ಕೊನೆಯ ವರದಿಗೆ ಮಾಹಿತಿ ಹಕ್ಕು ಅರ್ಜಿ",
            "MORE": "ಇನ್ನಷ್ಟು", "HISTORY": "ಇತಿಹಾಸ", "SETTINGS": "ಸೆಟ್ಟಿಂಗ್‌ಗಳು",
            "Anonymous Reporter": "ಅನಾಮಧೇಯ ದೂರುದಾರ", "Night Mode": "ರಾತ್ರಿ ಮೋಡ್",
            "CV Assist": "ದೃಷ್ಟಿ ನೆರವು", "Plate OCR": "ಫಲಕ ಗುರುತಿಸುವಿಕೆ",
            "VIOLATION REPORT": "ಉಲ್ಲಂಘನೆ ವರದಿ", "Plate": "ನಂಬರ್ ಪ್ಲೇಟ್",
            "Offense": "ಅಪರಾಧ", "Sign": "ಚಿಹ್ನೆ", "Notes": "ಟಿಪ್ಪಣಿ",
            "JURISDICTION ROUTING": "ವ್ಯಾಪ್ತಿ", "SCAN": "ಸ್ಕ್ಯಾನ್",
            "CAPTURE": "ಫೋಟೋ", "SEND": "ಕಳುಹಿಸು", "CLEAR": "ಅಳಿಸು",
            "Plate OCR: standby": "ಫಲಕ ಗುರುತಿಸುವಿಕೆ: ಸಿದ್ಧ", "Close": "ಮುಚ್ಚು",
            "OK": "ಸರಿ", "Missing": "ಅಪೂರ್ಣ",
            "Enter plate number.": "ನಂಬರ್ ಪ್ಲೇಟ್ ನಮೂದಿಸಿ.",
            "Select a violation.": "ಉಲ್ಲಂಘನೆ ಆಯ್ಕೆಮಾಡಿ.", "Ready": "ಸಿದ್ಧ",
            "Email app opened.": "ಇಮೇಲ್ ಆ್ಯಪ್ ತೆರೆಯಲಾಗಿದೆ.", "Saved!": "ಉಳಿಸಲಾಗಿದೆ!",
            "Duplicate": "ನಕಲು", "No route": "ಮಾರ್ಗವಿಲ್ಲ", "History": "ಇತಿಹಾಸ",
            "No reports sent yet.": "ಇನ್ನೂ ಯಾವುದೇ ವರದಿ ಕಳುಹಿಸಿಲ್ಲ.",
            "Language": "ಭಾಷೆ", "More - Citizen Tools": "ಇನ್ನಷ್ಟು - ನಾಗರಿಕ ಸಾಧನಗಳು",
            "Share to X / Twitter": "ಎಕ್ಸ್ / ಟ್ವಿಟರ್‌ನಲ್ಲಿ ಹಂಚಿಕೊಳ್ಳಿ",
            "Share to WhatsApp": "ವಾಟ್ಸ್‌ಆ್ಯಪ್‌ನಲ್ಲಿ ಹಂಚಿಕೊಳ್ಳಿ",
            "WhatsApp traffic police (official no.)": "ಸಂಚಾರ ಪೊಲೀಸ್ ವಾಟ್ಸ್‌ಆ್ಯಪ್ (ಅಧಿಕೃತ ಸಂಖ್ಯೆ)",
            "Vehicle lookup (RC/Insurance/PUC)": "ವಾಹನ ಮಾಹಿತಿ (ನೋಂದಣಿ/ವಿಮೆ/ಮಾಲಿನ್ಯ)",
            "Report a road hazard": "ರಸ್ತೆ ಅಪಾಯ ವರದಿ ಮಾಡಿ",
            "SOS / Emergency": "ತುರ್ತು", "Violation hotspots": "ಉಲ್ಲಂಘನೆ ತಾಣಗಳು",
            "Save last 15 s as video clip": "ಕೊನೆಯ 15 ಸೆಕೆಂಡ್ ವೀಡಿಯೊ ಉಳಿಸಿ",
            "Emergency contact (crash SOS)": "ತುರ್ತು ಸಂಪರ್ಕ (ಅಪಘಾತ)",
            "Check for app updates": "ಆ್ಯಪ್ ನವೀಕರಣ ಪರಿಶೀಲಿಸಿ",
            "Privacy blur (faces)": "ಮುಖಗಳನ್ನು ಮಸುಕುಗೊಳಿಸಿ", "ON": "ಆನ್", "OFF": "ಆಫ್",
        },
        "bn": {
            "Report in official police app": "সরকারি পুলিশ অ্যাপে রিপোর্ট করুন",
            "Evidence pack (PDF)": "প্রমাণ সংকলন (পিডিএফ)", "RTI request for last report": "শেষ রিপোর্টের জন্য তথ্য অধিকার আবেদন",
            "MORE": "আরও", "HISTORY": "ইতিহাস", "SETTINGS": "সেটিংস",
            "Anonymous Reporter": "বেনামী অভিযোগকারী", "Night Mode": "রাত্রি মোড",
            "CV Assist": "দৃষ্টি সহায়তা", "Plate OCR": "প্লেট শনাক্তকরণ",
            "VIOLATION REPORT": "লঙ্ঘনের রিপোর্ট", "Plate": "নম্বর প্লেট",
            "Offense": "অপরাধ", "Sign": "চিহ্ন", "Notes": "মন্তব্য",
            "JURISDICTION ROUTING": "এখতিয়ার", "SCAN": "স্ক্যান",
            "CAPTURE": "ছবি", "SEND": "পাঠান", "CLEAR": "মুছুন",
            "Plate OCR: standby": "প্লেট শনাক্তকরণ: প্রস্তুত", "Close": "বন্ধ করুন",
            "OK": "ঠিক আছে", "Missing": "অসম্পূর্ণ",
            "Enter plate number.": "নম্বর প্লেট লিখুন।",
            "Select a violation.": "লঙ্ঘন বেছে নিন।", "Ready": "প্রস্তুত",
            "Email app opened.": "ইমেল অ্যাপ খোলা হয়েছে।", "Saved!": "সংরক্ষিত!",
            "Duplicate": "পুনরাবৃত্তি", "No route": "কোনো পথ নেই",
            "History": "ইতিহাস", "No reports sent yet.": "এখনও কোনো রিপোর্ট পাঠানো হয়নি।",
            "Language": "ভাষা", "More - Citizen Tools": "আরও - নাগরিক পরিষেবা",
            "Share to X / Twitter": "এক্স / টুইটারে শেয়ার করুন",
            "Share to WhatsApp": "হোয়াটসঅ্যাপে শেয়ার করুন",
            "WhatsApp traffic police (official no.)": "ট্রাফিক পুলিশ হোয়াটসঅ্যাপ (সরকারি নম্বর)",
            "Vehicle lookup (RC/Insurance/PUC)": "গাড়ির তথ্য (নিবন্ধন/বিমা/দূষণ)",
            "Report a road hazard": "রাস্তার বিপদ জানান",
            "SOS / Emergency": "জরুরি", "Violation hotspots": "লঙ্ঘনের স্থান",
            "Save last 15 s as video clip": "শেষ 15 সেকেন্ডের ভিডিও সংরক্ষণ করুন",
            "Emergency contact (crash SOS)": "জরুরি যোগাযোগ (দুর্ঘটনা)",
            "Check for app updates": "অ্যাপ আপডেট দেখুন",
            "Privacy blur (faces)": "মুখ ঝাপসা করুন", "ON": "চালু", "OFF": "বন্ধ",
        },
    }

    @classmethod
    def set_lang(cls, lang):
        cls.LANG = lang if lang in cls.SUPPORTED else "en"

    @classmethod
    def tr(cls, s, lang=None):
        """Translate `s` (lang defaults to the current one). The explicit
        `lang` argument lets KV rules re-evaluate when the language changes."""
        lang = cls.LANG if lang is None else lang
        if lang == "en":
            return s
        return cls.STRINGS.get(lang, {}).get(s, s)

    @classmethod
    def next_lang(cls, lang=None):
        order = list(cls.SUPPORTED)
        cur = cls.LANG if lang is None else lang
        return order[(order.index(cur) + 1) % len(order)] if cur in order else "en"

    @classmethod
    def font_for(cls, lang=None):
        """(font path or "Roboto", script tag) to render `lang` with; falls
        back to the Latin default if the device lacks the Noto font."""
        lang = cls.LANG if lang is None else lang
        _name, family, script = cls.LANGS.get(lang, cls.LANGS["en"])
        if family:
            for suffix in ("-VF.ttf", "-Regular.ttf", "UI-VF.ttf", "UI-Regular.ttf"):
                path = os.path.join(cls.FONT_DIR, "NotoSans%s%s" % (family, suffix))
                if os.path.isfile(path):
                    return path, script
        return "Roboto", "Zyyy"

    @staticmethod
    def has_latin(s):
        return any("A" <= c <= "Z" or "a" <= c <= "z" for c in (s or ""))


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

    # Crash only counts if the phone was moving at vehicle speed just before,
    # so dropping the phone on a desk or while walking doesn't trigger SOS.
    CRASH_MIN_SPEED_KMH = 15.0
    CRASH_SPEED_WINDOW_S = 15.0
    SOS_COUNTDOWN_S = 15

    @staticmethod
    def is_crash(g_dyn, last_moving_ts, now_ts):
        return (g_dyn >= Emergency.CRASH_G
                and now_ts - last_moving_ts <= Emergency.CRASH_SPEED_WINDOW_S)

    @staticmethod
    def crash_text(lat, lon):
        return ("Possible road accident detected by Sentinel-X. I may need help. "
                "Location: %s" % Emergency.maps_link(lat, lon))

    @staticmethod
    def good_samaritan_text(lat, lon):
        return ("Accident reported. Location: %s. Reporting under Good Samaritan "
                "protection (MVA Sec.134A). Please dispatch help."
                % Emergency.maps_link(lat, lon))


# ─────────────────────────────────────────────────────────────────────────
# Pre-send evidence quality check (mirrors common police-app rejections)
# ─────────────────────────────────────────────────────────────────────────
class QualityCheck:
    """Flags evidence that police apps commonly reject: no photo, a blurry
    photo, an imprecise GPS fix, or a plate that isn't a valid format."""

    MIN_SHARPNESS = 60.0      # variance of Laplacian; below = blurry
    MAX_GPS_ACCURACY_M = 50.0
    MAX_GPS_AGE_S = 120.0     # older fix = location may be wrong
    DARK_MEAN = 60.0          # mean grey level below which a photo is "dark"

    @staticmethod
    def issues(has_photo, sharpness=None, gps_accuracy_m=None, plate_conf=1.0,
               gps_age_s=None):
        out = []
        if not has_photo:
            out.append("No photo attached - tap CAPTURE with the plate in view.")
        elif sharpness is not None and sharpness < QualityCheck.MIN_SHARPNESS:
            out.append("Photo looks blurry (sharpness %.0f) - hold steady and recapture."
                       % sharpness)
        if gps_age_s is not None and gps_age_s > QualityCheck.MAX_GPS_AGE_S:
            out.append("GPS position is %s old - go outdoors / enable location "
                       "until it updates." % (
                           "%.0f min" % (gps_age_s / 60) if gps_age_s < 7200
                           else "%.0f h" % (gps_age_s / 3600)))
        if gps_accuracy_m is not None and gps_accuracy_m > QualityCheck.MAX_GPS_ACCURACY_M:
            out.append("GPS is imprecise (+/- %.0f m) - wait for a better fix."
                       % gps_accuracy_m)
        if plate_conf < 0.5:
            out.append("Plate doesn't look like a valid Indian registration number.")
        return out


# ─────────────────────────────────────────────────────────────────────────
# Power / heat policy for the always-on camera pipeline
# ─────────────────────────────────────────────────────────────────────────
class PowerPolicy:
    """Pause the dashcam + live OCR on low battery or a hot phone, with
    hysteresis so it doesn't flap on/off around the thresholds."""

    LOW_PCT, RESUME_PCT = 15, 20
    HOT_C, COOL_C = 44.0, 41.0

    @staticmethod
    def should_save(pct, charging, temp_c, saving):
        hot = temp_c is not None and temp_c >= PowerPolicy.HOT_C
        low = pct is not None and pct < PowerPolicy.LOW_PCT and not charging
        if not saving:
            return hot or low
        cool = temp_c is None or temp_c <= PowerPolicy.COOL_C
        ok_batt = charging or pct is None or pct >= PowerPolicy.RESUME_PCT
        return not (cool and ok_batt)


class FlagGesture:
    """Hands-free flag: two volume-key presses within WINDOW_S seconds."""

    WINDOW_S = 1.2
    COOLDOWN_S = 10.0

    def __init__(self):
        self._presses = []
        self._last_flag = -1e9

    def press(self, ts):
        """Record a press at ts; returns True when it completes a flag."""
        self._presses = [t for t in self._presses if ts - t <= self.WINDOW_S] + [ts]
        if len(self._presses) >= 2 and ts - self._last_flag >= self.COOLDOWN_S:
            self._presses = []
            self._last_flag = ts
            return True
        return False


# ─────────────────────────────────────────────────────────────────────────
# Accident victims: cashless treatment + Rah-Veer (Good Samaritan) reward
# ─────────────────────────────────────────────────────────────────────────
class AccidentHelp:
    """Facts shown in the SOS flow and the Rah-Veer application draft.

    Cashless Treatment of Road Accident Victims Scheme, 2025 (MoRTH):
    up to Rs 1.5 lakh for the first 7 days at designated hospitals; police
    should be informed (112) promptly. Rah-Veer: Rs 25,000 for taking a
    victim to hospital within the golden hour; the helper must disclose
    their identity to claim, and is protected from legal harassment.
    """

    CASHLESS_INFO = (
        "Any road-accident victim in India is entitled to cashless treatment "
        "up to Rs 1.5 lakh for the first 7 days at designated hospitals. "
        "Call 112 so the police record the accident.")
    GOLDEN_HOUR_S = 3600
    RAHVEER_REWARD = "Rs 25,000"

    @staticmethod
    def within_golden_hour(accident_ts, hospital_ts):
        return 0 <= hospital_ts - accident_ts <= AccidentHelp.GOLDEN_HOUR_S

    @staticmethod
    def rahveer_application(name, phone, accident, hospital, hospital_name=""):
        """accident / hospital: dicts with ts, lat, lon."""
        fmt = "%d %b %Y %H:%M"
        mins = (hospital["ts"] - accident["ts"]) / 60.0
        return (
            "To: The District Level Appraisal Committee (Rah-Veer Scheme),\n"
            "Office of the District Magistrate\n\n"
            "Subject: Application for Rah-Veer (Good Samaritan) award\n\n"
            "I, %s (mobile %s), helped a road-accident victim reach hospital.\n\n"
            "Accident: %s at GPS %.6f, %.6f (%s)\n"
            "Reached hospital%s: %s at GPS %.6f, %.6f (%s)\n"
            "Time taken: %.0f minutes (%s the golden hour)\n\n"
            "These times and locations were recorded on my phone and are "
            "available as signed records. I consent to share my identity for "
            "this award and request the reward under the Rah-Veer scheme.\n"
            % (name or "[your name]", phone or "[your mobile]",
               time.strftime(fmt, time.localtime(accident["ts"])),
               accident["lat"], accident["lon"],
               Emergency.maps_link(accident["lat"], accident["lon"]),
               (" (%s)" % hospital_name) if hospital_name else "",
               time.strftime(fmt, time.localtime(hospital["ts"])),
               hospital["lat"], hospital["lon"],
               Emergency.maps_link(hospital["lat"], hospital["lon"]),
               mins, "within" if AccidentHelp.within_golden_hour(
                   accident["ts"], hospital["ts"]) else "after"))


# ─────────────────────────────────────────────────────────────────────────
# RTI request: ask what action was taken on a report
# ─────────────────────────────────────────────────────────────────────────
class RTIRequest:
    """Draft under Section 6(1) of the RTI Act, 2005. Central bodies file
    at rtionline.gov.in; most state police accept their own state RTI
    portal or a postal application to the PIO with the Rs 10 fee."""

    CENTRAL_PORTAL = "https://rtionline.gov.in/"

    @staticmethod
    def draft(entry):
        when = time.strftime("%d %b %Y %H:%M", time.localtime(float(entry.get("ts", 0))))
        return (
            "To: The Public Information Officer, Traffic Police\n\n"
            "Subject: Application under Section 6(1) of the Right to "
            "Information Act, 2005\n\n"
            "On %s I reported a traffic violation by vehicle %s (%s, %s) at "
            "GPS %.6f, %.6f, by email to %s with photographic evidence.\n\n"
            "Please provide:\n"
            "1. Whether the complaint was received and registered, with its "
            "reference number.\n"
            "2. The action taken on it, including whether a challan was "
            "issued to the vehicle, with date.\n"
            "3. The name and designation of the officer who handled it.\n"
            "4. If no action was taken, the reasons recorded.\n\n"
            "I am an Indian citizen. The application fee of Rs 10 is paid "
            "herewith."
            % (when, entry.get("plate", "?"), entry.get("offense", "?"),
               entry.get("section", ""), float(entry.get("lat", 0.0)),
               float(entry.get("lon", 0.0)),
               ", ".join(entry.get("recipients", []) or ["the traffic police"])))


# ─────────────────────────────────────────────────────────────────────────
# Follow-up reminders: escalate reports with no visible action
# ─────────────────────────────────────────────────────────────────────────
class FollowUp:
    """Finds sent reports old enough to escalate and drafts the grievance."""

    DAYS = 7
    MAX_SHOWN = 3

    @staticmethod
    def key(entry):
        return "%s|%s" % (entry.get("plate", ""), entry.get("ts", ""))

    @staticmethod
    def due(entries, done_keys, now_ts=None, days=None):
        now_ts = time.time() if now_ts is None else now_ts
        age = (FollowUp.DAYS if days is None else days) * 86400
        out = []
        for e in entries or []:
            ts = e.get("ts")
            if ts is None or not str(e.get("status", "")).startswith("sent"):
                continue
            if now_ts - float(ts) >= age and FollowUp.key(e) not in done_keys:
                out.append(e)
        return out

    @staticmethod
    def draft(entry):
        when = time.strftime("%d %b %Y", time.localtime(float(entry.get("ts", 0))))
        return (
            "Subject: No action on traffic violation report - vehicle %s\n\n"
            "On %s I reported vehicle %s for %s (%s) at GPS %.6f, %.6f to %s, "
            "with photo evidence. I have not received any acknowledgement or "
            "information on action taken. I request that the complaint be "
            "acted upon and the status communicated.\n\n"
            "This report was made under the Good Samaritan protection of "
            "Section 134A of the Motor Vehicles Act, 1988."
            % (entry.get("plate", "?"), when, entry.get("plate", "?"),
               entry.get("offense", "?"), entry.get("section", ""),
               float(entry.get("lat", 0.0)), float(entry.get("lon", 0.0)),
               ", ".join(entry.get("recipients", []) or ["the traffic police"]))
        )


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

    CASCADE = "haarcascade_frontalface_default.xml"
    _cascade = None

    @staticmethod
    def _face_cascade():
        """Face detector, cached. The p4a OpenCV build ships only cv2.so (no
        cv2.data), so the cascade bundled in assets/ is tried first;
        without it face blur silently did nothing on Android."""
        if cv2 is None:
            return None
        if PrivacyBlur._cascade is not None:
            return PrivacyBlur._cascade
        here = os.path.dirname(os.path.abspath(__file__))
        paths = [os.path.join(here, "assets", PrivacyBlur.CASCADE)]
        base = getattr(getattr(cv2, "data", None), "haarcascades", None)
        if base:
            paths.append(os.path.join(base, PrivacyBlur.CASCADE))
        for p in paths:
            try:
                if os.path.isfile(p):
                    casc = cv2.CascadeClassifier(p)
                    if not casc.empty():
                        PrivacyBlur._cascade = casc
                        return casc
            except Exception:
                continue
        return None

    @staticmethod
    def blur_regions(bgr, boxes):
        """Blur each (x, y, w, h) box. Returns the image."""
        if cv2 is None or bgr is None:
            return bgr
        for (x, y, w, h) in boxes:
            bgr = PrivacyBlur._blur_region(bgr, x, y, w, h)
        return bgr

    @staticmethod
    def overlaps(a, b):
        """True if two (x, y, w, h) boxes intersect."""
        return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0]
                    or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])

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
