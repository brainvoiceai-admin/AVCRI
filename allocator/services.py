# allocator/services.py
"""
AllocationService for AVCRI allocator app.

Features:
- Loads slots, therapists, rooms, weekly-off/leaves from external DB or local models
- Supports bathing-therapist requirement (uses Therapist.is_bathing_therapist or 'bathing' grade)
- Continuity from previous Assignment or PatientHistory
- Batch allocation: assign_all(allocation_run=None)
- Real-time allocation: allocate_visit(visit_id=None, visit_obj=None)
- Delete allocations by date: delete_allocations_for_date(date)
- Configurable constants at top of file
"""

import datetime
import random
import traceback
from collections import defaultdict
from typing import Optional, Any, Dict, List

from django.db import connections, transaction
from django.utils import timezone

# Local models (allocator)
from .models import AllocationRun, Assignment

# Patient models (therapy metadata & repeats & therapist)
try:
    from Patient.models import TherapyDetails, Repeated_Visitors, PatientHistory, Therapist as PatientTherapist
except Exception:
    TherapyDetails = None
    Repeated_Visitors = None
    PatientHistory = None
    PatientTherapist = None

# External DB models (MySql_Data_pull)
try:
    from MySql_Data_pull.models import Visit, TimeSlot, Therapist_Details, RoomMaster, Scheduling
    ORM_EXTERNAL_AVAILABLE = True
except Exception:
    Visit = None
    TimeSlot = None
    Therapist_Details = None
    RoomMaster = None
    Scheduling = None
    ORM_EXTERNAL_AVAILABLE = False

# ---------------- CONFIG ----------------
EXTERNAL_DB_ALIAS = "therapy_db"  # database connection for external SQL Server
MAX_SESSIONS_PER_THERAPIST = 5
MIN_THERAPISTS_PER_TREATMENT = 2
MAX_THERAPISTS_PER_TREATMENT = 7
DHARAP_MAX_PER_DAY = 40
POT_LIMIT_PER_SENIOR_PER_DAY = 2

# per-therapist room-type daily maxima
ROOM_LIMITS_PER_THERAPIST = {"regular": 2, "cottage": 1, "ward": 2, "opd": 2}

# labels that indicate OP/IP slots (can be extended)
OP_SLOT_TIME_LABELS = set(["11:30", "17:30"])
IP_SLOT_TIME_LABELS = set(["06:30", "08:30", "10:00", "14:30", "16:00"])

# ---------------- Helpers ----------------
def _safe_query(sql: str, params=None, db_alias=EXTERNAL_DB_ALIAS) -> List[Dict[str, Any]]:
    try:
        with connections[db_alias].cursor() as cur:
            cur.execute(sql, params or [])
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = cur.fetchall()
            return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []

def _first_present(d: Dict[str, Any], keys: List[str], default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default

def normalize_grade(raw: Optional[str]) -> str:
    if not raw:
        return "unknown"
    s = str(raw).lower()
    if "super" in s and "senior" in s:
        return "super_senior"
    if "most" in s and "senior" in s:
        return "most_senior"
    if "senior" in s:
        return "senior"
    if "junior" in s:
        return "junior"
    if "trainee" in s or "intern" in s:
        return "trainee"
    if "bathing" in s:
        return "bathing"
    return "unknown"

def _normalize_time_string(raw_time: Optional[str]) -> Optional[str]:
    if raw_time is None:
        return None
    s = str(raw_time).strip()
    if not s:
        return None
    s = s.replace(".", ":")
    su = s.upper()
    ampm = None
    if "AM" in su or "PM" in su:
        ampm = "AM" if "AM" in su else "PM"
        s = su.replace("AM", "").replace("PM", "").strip()
    s = s.replace(" ", "")
    if ":" in s:
        parts = s.split(":")
        try:
            hr = int(parts[0]); mn = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            if ampm == "PM" and hr < 12: hr += 12
            if ampm == "AM" and hr == 12: hr = 0
            return f"{hr:02d}:{mn:02d}"
        except Exception:
            return s[:5]
    if s.isdigit() and len(s) in (3,4):
        try:
            hr = int(s[:-2]); mn = int(s[-2:])
            if ampm == "PM" and hr < 12: hr += 12
            return f"{hr:02d}:{mn:02d}"
        except Exception:
            return s[:5]
    return s[:5]

def _get_model_field(model_class, candidates: List[str]) -> Optional[str]:
    try:
        model_fields = {f.name.lower(): f.name for f in model_class._meta.get_fields() if hasattr(f, "name")}
    except Exception:
        return None
    for c in candidates:
        if c is None: continue
        lower = c.lower()
        if lower in model_fields:
            return model_fields[lower]
    return None

# ---------------- AllocationService ----------------
class AllocationService:
    def __init__(self, run_date: datetime.date, rand_seed: int = 42, external_db_alias: str = EXTERNAL_DB_ALIAS):
        if isinstance(run_date, str):
            self.run_date = datetime.date.fromisoformat(run_date)
        elif isinstance(run_date, datetime.datetime):
            self.run_date = run_date.date()
        else:
            self.run_date = run_date

        self._rand = random.Random(rand_seed)
        self.external_db_alias = external_db_alias

        # runtime
        self.slots_order: List[str] = []
        self.slot_label: Dict[str, str] = {}
        self.slot_time_map: Dict[str, Optional[datetime.time]] = {}

        self.therapists: Dict[str, Dict[str, Any]] = {}   # code -> {name, grade, is_bathing(boolean)}
        self.therapists_by_grade = defaultdict(list)
        self.on_leave = set()

        self.rooms: Dict[str, Dict[str, Any]] = {}

        self.therapy_map = {}
        self.repeats_map = {}

        # trackers
        self.therapist_slots = defaultdict(set)
        self.room_slots = defaultdict(set)
        self.therapist_loads = defaultdict(lambda: {"sessions": 0, "easy": 0, "medium": 0, "hard": 0, "pot": 0})
        self.therapist_room_type_counts = defaultdict(lambda: defaultdict(int))
        self.rotation_counter = defaultdict(int)
        self.dharap_assigned_today = 0

        self.fail_list = []

    # -------- data loaders --------
    def load_slots_from_db(self):
        entries = []
        try:
            if TimeSlot is not None:
                qs = TimeSlot.objects.using(self.external_db_alias).all().order_by("slot_no")
                for r in qs:
                    key = str(getattr(r, "slot_no", None) or getattr(r, "Slot_No", None) or getattr(r, "pk", None))
                    label_raw = getattr(r, "starting_time", None) or getattr(r, "Start_Time", None)
                    label = _normalize_time_string(label_raw)
                    entries.append((key, label))
            else:
                rows = _safe_query("SELECT slot_no, starting_time FROM Slot_Master ORDER BY slot_no", db_alias=self.external_db_alias)
                for r in rows:
                    key = str(_first_present(r, ["slot_no", "SlotNo", "Slot_No", "id"]) or "")
                    label = _normalize_time_string(_first_present(r, ["starting_time", "Start_Time", "startingtime"]))
                    entries.append((key, label))
        except Exception:
            entries = []

        if not entries:
            defaults = [("1","06:30"),("2","08:30"),("3","10:00"),("4","11:30"),("5","14:30"),("6","16:00"),("7","17:30")]
            entries = defaults

        # dedupe preserve order
        seen = set(); filtered=[]
        for k,v in entries:
            if k in seen: continue
            seen.add(k); filtered.append((k,v))
        self.slots_order = [k for k,_ in filtered]
        self.slot_label = {k:(v or "") for k,v in filtered}
        for k,lbl in self.slot_label.items():
            try: self.slot_time_map[k] = datetime.datetime.strptime(lbl,"%H:%M").time()
            except Exception: self.slot_time_map[k] = None

    def load_therapists_from_db(self):
        self.therapists = {}
        self.therapists_by_grade = defaultdict(list)
        try:
            if Therapist_Details is not None:
                qs = Therapist_Details.objects.using(self.external_db_alias).all()
                for r in qs:
                    code = str(getattr(r,"therapist_code",None) or getattr(r,"Therapist_Code",None) or getattr(r,"id",None) or "").strip()
                    if not code: continue
                    name = getattr(r,"therapist_name",None) or getattr(r,"Therapist_Name",None) or code
                    grade_raw = getattr(r,"therapist_grade",None) or getattr(r,"Therapist_Grade",None) or getattr(r,"service_grade",None) or ""
                    grade = normalize_grade(grade_raw)
                    # Bathing column or flag
                    is_bathing = False
                    if hasattr(r, "is_bathing_therapist"):
                        try: is_bathing = bool(getattr(r,"is_bathing_therapist"))
                        except Exception: is_bathing=False
                    else:
                        # fallback: detect 'bathing' in grade string
                        if "bathing" in str(grade_raw).lower():
                            is_bathing=True
                    # weekly_off may store weekday name or number
                    weekly_off = None
                    try:
                        weekly_off = getattr(r, "weekly_off", None)
                    except Exception:
                        weekly_off = None
                    self.therapists[code] = {"name": str(name), "grade": grade, "is_bathing": is_bathing, "weekly_off": weekly_off}
                    self.therapists_by_grade[grade].append(code)
            elif PatientTherapist is not None:
                qs = PatientTherapist.objects.all()
                for r in qs:
                    code = str(getattr(r,"therapist_code",None) or r.pk)
                    name = getattr(r,"therapist_name",None) or code
                    grade = normalize_grade(getattr(r,"therapist_grade",None))
                    is_bathing = bool(getattr(r, "is_bathing_therapist", False))
                    weekly_off = getattr(r, "weekly_off", None) if hasattr(r, "weekly_off") else None
                    self.therapists[code] = {"name": str(name), "grade": grade, "is_bathing": is_bathing, "weekly_off": weekly_off}
                    self.therapists_by_grade[grade].append(code)
        except Exception:
            pass

        # fallback test therapists if none found (avoid crash)
        if not self.therapists:
            for i in range(1,9):
                code=f"THP_TEST_{i}"; grade = "senior" if i<=3 else "junior"
                self.therapists[code] = {"name":f"Therapist {i}","grade":grade,"is_bathing": False, "weekly_off": None}
                self.therapists_by_grade[grade].append(code)

    def load_rooms_from_db(self):
        self.rooms = {}
        try:
            if RoomMaster is not None:
                qs = RoomMaster.objects.using(self.external_db_alias).all()
                for r in qs:
                    code = str(getattr(r,"room_code",None) or getattr(r,"Room_No",None) or getattr(r,"id",None))
                    name = getattr(r,"room_name",None) or getattr(r,"Room_Name",None) or code
                    cap = getattr(r,"room_capacity",None) or getattr(r,"Room_Capacity",None) or 1
                    try: cap = int(cap)
                    except Exception: cap = 1
                    rtype_raw = (getattr(r,"room_type",None) or getattr(r,"Room_Type",None) or "").lower()
                    if "cottage" in rtype_raw: rtype="cottage"
                    elif "ward" in rtype_raw or "general" in rtype_raw: rtype="ward"
                    elif "op" in rtype_raw or "opd" in rtype_raw: rtype="opd"
                    else: rtype="regular"
                    self.rooms[str(code).strip()] = {"name": str(name), "capacity": cap, "type": rtype}
            else:
                rows = _safe_query("SELECT * FROM Room_Master", db_alias=self.external_db_alias)
                if not rows: rows = _safe_query("SELECT * FROM RoomMaster", db_alias=self.external_db_alias)
                for r in rows:
                    code = _first_present(r, ["room_code","Room_No","RoomID","id"])
                    if not code: continue
                    code = str(code).strip()
                    name = _first_present(r, ["room_name","Room_Name","name"], default=code)
                    cap = _first_present(r, ["room_capacity","Room_Capacity","capacity"], default=1)
                    try: cap=int(cap)
                    except Exception: cap=1
                    rtype_raw = str(_first_present(r, ["room_type","Room_Type","type"], default="")).lower()
                    if "cottage" in rtype_raw: rtype="cottage"
                    elif "ward" in rtype_raw or "general" in rtype_raw: rtype="ward"
                    elif "op" in rtype_raw or "opd" in rtype_raw: rtype="opd"
                    else: rtype="regular"
                    self.rooms[code] = {"name": str(name), "capacity": cap, "type": rtype}
        except Exception:
            pass

        if not self.rooms:
            for i in range(1,8):
                code=f"R{i}"; rtype="regular" if i<=4 else ("cottage" if i==5 else "ward")
                self.rooms[code] = {"name":f"Room {i}","capacity": 2 if rtype=="regular" else 1, "type": rtype}

    def load_leaves_from_db(self):
        """
        Load explicit leave rows AND mark weekly_off as leave for run_date weekday.
        weekly_off field may be name of weekday ('Sunday') or number (0-6) depending on source.
        """
        self.on_leave = set()
        try:
            # explicit leave table first
            rows = _safe_query("SELECT * FROM Therapist_Leaves WHERE 1=1", db_alias=self.external_db_alias)
            if not rows: rows = _safe_query("SELECT * FROM TherapistLeaves WHERE 1=1", db_alias=self.external_db_alias)
            for r in rows:
                code = _first_present(r, ["therapist_code","Therapist_Code","therapist_id","id"])
                if not code: continue
                code = str(code).strip()
                ld = _first_present(r, ["leave_date","LeaveDate","date"])
                sd = _first_present(r, ["start_date","StartDate","from_date"])
                ed = _first_present(r, ["end_date","EndDate","to_date"])
                def _to_date(x):
                    if x is None: return None
                    if isinstance(x, datetime.date): return x
                    try: return datetime.date.fromisoformat(str(x)[:10])
                    except Exception: return None
                ld=_to_date(ld); sd=_to_date(sd); ed=_to_date(ed)
                if ld and ld == self.run_date: self.on_leave.add(code)
                elif sd and ed and sd <= self.run_date <= ed: self.on_leave.add(code)
                elif sd and sd == self.run_date: self.on_leave.add(code)
        except Exception:
            pass

        # Mark weekly_off as leave for this run_date weekday
        try:
            wd = self.run_date.weekday()  # Monday=0
            for code, info in self.therapists.items():
                wo = info.get("weekly_off")
                if not wo: continue
                s = str(wo).strip().lower()
                if not s: continue
                # try textual mapping
                daymap = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
                if s.isdigit():
                    try:
                        if int(s) == wd:
                            self.on_leave.add(code)
                            continue
                    except Exception:
                        pass
                if s in daymap and daymap[s] == wd:
                    self.on_leave.add(code)
                    continue
                # sometimes abbreviated: mon,tue etc
                for k,v in daymap.items():
                    if k[:3] in s and v==wd:
                        self.on_leave.add(code)
                        break
        except Exception:
            pass

    def load_therapy_and_repeats(self):
        self.therapy_map = {}
        try:
            if TherapyDetails is not None:
                for t in TherapyDetails.objects.all():
                    key = str(getattr(t, "therapy_code", None) or getattr(t, "Therapy_Code", None) or getattr(t, "pk", None))
                    if key:
                        self.therapy_map[key.strip()] = t
        except Exception:
            self.therapy_map = {}
        self.repeats_map = {}
        try:
            if Repeated_Visitors is not None:
                for r in Repeated_Visitors.objects.all():
                    try: reg = int(getattr(r,"register_number", None) or r.pk)
                    except Exception: continue
                    self.repeats_map[reg] = r
        except Exception:
            self.repeats_map = {}

    # load bookings from Visit or Scheduling
    def load_bookings(self) -> List[Dict[str, Any]]:
        bookings=[]
        try:
            if Visit is not None:
                date_field = _get_model_field(Visit, ["tdate","TDate","visit_date","date_of_visit","date"])
                qs = Visit.objects.using(self.external_db_alias).all()
                if date_field:
                    qs = qs.filter(**{f"{date_field}__date": self.run_date})
                for v in qs:
                    preg = getattr(v,"pat_reg_no",None) or getattr(v,"PReg_No",None) or ""
                    tcode = getattr(v,"therapy_code",None) or getattr(v,"Therapy_Code",None) or ""
                    tname = getattr(v,"therapy_name",None) or getattr(v,"Therapy_Name",None) or ""
                    preferred_slot_label = getattr(v,"start_time",None) or getattr(v,"Start_Time",None) or ""
                    preferred_room = getattr(v,"troom_no",None) or getattr(v,"TRoom_No",None)
                    visit_type = getattr(v,"is_ip_or_op",None) or getattr(v,"visit_type",None) or ""
                    is_vip_flag = bool(getattr(v,"is_vip",False))
                    bookings.append({"visit_obj":v,"preg_no":preg,"therapy_code":tcode,"therapy_name":tname,
                                     "preferred_slot_label":str(preferred_slot_label).strip(),"preferred_room":preferred_room,
                                     "visit_type":visit_type,"is_vip":is_vip_flag,"raw":v})
                if bookings:
                    return bookings
        except Exception:
            pass

        try:
            rows = _safe_query("SELECT * FROM Scheduling WHERE CAST(TDate AS DATE) = %s", [self.run_date], db_alias=self.external_db_alias)
            if not rows:
                rows = _safe_query("SELECT * FROM Scheduling WHERE CONVERT(VARCHAR(10), TDate, 120) = %s", [self.run_date.isoformat()], db_alias=self.external_db_alias)
            for r in rows:
                preg = _first_present(r, ["PReg_No","pat_reg_no","PRegNo"]) or ""
                tcode = _first_present(r, ["Therapy_Code","therapy_code","TherapyCode"]) or ""
                tname = _first_present(r, ["Therapy_Name","therapy_name","Therapy"]) or ""
                preferred_slot_label = _first_present(r, ["Start_Time","StartTime","slot_label"]) or ""
                preferred_room = _first_present(r, ["TRoom_No","TRoomNo","room_no","troom_no"])
                visit_type = _first_present(r, ["is_ip_or_op","visit_type"]) or ""
                is_vip_flag = bool(_first_present(r, ["is_vip","VIP"], False))
                bookings.append({"preg_no":preg,"therapy_code":tcode,"therapy_name":tname,
                                 "preferred_slot_label":str(preferred_slot_label).strip(),"preferred_room":preferred_room,
                                 "visit_type":visit_type,"is_vip":is_vip_flag,"raw":r})
            return bookings
        except Exception:
            return bookings

    # ---------- helpers for allocation ----------

    def is_vip_patient(self, preg_no, booking):
        try:
            if booking.get("is_vip"): return True
            if preg_no:
                try:
                    reg=int(str(preg_no).strip())
                    r=self.repeats_map.get(reg)
                    if r and getattr(r,"is_vip",False): return True
                except Exception:
                    pass
        except Exception:
            pass
        return bool(booking.get("is_vip", False))

    def get_difficulty(self, therapy_code, therapy_name=None):
        if therapy_code:
            t=self.therapy_map.get(str(therapy_code).strip())
            if t:
                cat=(getattr(t,"therapy_category",None) or "").strip().lower()
                if cat in ("hard","difficult","high"): return "Hard"
                if cat in ("medium","moderate"): return "Medium"
        if therapy_name and "hard" in therapy_name.lower(): return "Hard"
        if therapy_code and "hard" in str(therapy_code).lower(): return "Hard"
        return "Easy"

    def get_required_composition(self, therapy_code, therapy_name=None):
        """Return composition dict with total, seniors, juniors and bathing_required flag."""
        bathing_required = False
        if therapy_name and "dharap" in therapy_name.strip().lower():
            return {"total":6,"seniors":4,"juniors":2,"bathing_required":False}
        t = self.therapy_map.get(str(therapy_code).strip()) if therapy_code else None
        if t:
            total = getattr(t,"total_no_of_therapist",None) or getattr(t,"total_no_of_therapist",None) or 0
            try: total = int(total)
            except Exception: total = MIN_THERAPISTS_PER_TREATMENT
            total = max(MIN_THERAPISTS_PER_TREATMENT, min(MAX_THERAPISTS_PER_TREATMENT, total))
            seniors = int(getattr(t,"no_of_senior_therapist",0) or 0)
            juniors = int(getattr(t,"no_of_junior_therapist",0) or 0)
            # bathing_required in model could be '1', 'yes', True, etc.
            bath = getattr(t, "bathing_required", None)
            bathing_required = str(bath).strip().lower() in ("1","true","yes","y") if bath is not None else False
            return {"total": total, "seniors": seniors, "juniors": juniors, "bathing_required": bathing_required}
        # fallback
        return {"total": MIN_THERAPISTS_PER_TREATMENT, "seniors": 0, "juniors": 0, "bathing_required": False}

    def dharap_can_allocate_more(self):
        if self.dharap_assigned_today >= DHARAP_MAX_PER_DAY: return False
        try:
            existing = Assignment.objects.filter(therapy_code__icontains="dharap", created_at__date=self.run_date).count()
            if (existing + self.dharap_assigned_today) >= DHARAP_MAX_PER_DAY:
                return False
        except Exception:
            pass
        return True

    def _available_therapists_for_slot(self, slot_key):
        cand=[]
        for code,info in self.therapists.items():
            if code in self.on_leave: continue
            if slot_key in self.therapist_slots.get(code,set()): continue
            if self.therapist_loads[code]["sessions"] >= MAX_SESSIONS_PER_THERAPIST: continue
            cand.append(code)
        return cand

    def _sort_candidates(self, codes, difficulty_label):
        def key_fn(c):
            loads = self.therapist_loads[c]
            return (loads["sessions"], loads.get(difficulty_label.lower(),0), self.rotation_counter[c], self._rand.random())
        return sorted(codes, key=key_fn)

    def _room_ok_for_patient(self, room_code, visit_type, slot_k, required_people):
        info = self.rooms.get(room_code)
        if not info: return False
        rtype = (info.get("type") or "").lower()
        if "opd" in rtype and (visit_type or "").strip().lower() not in ("op", "out", "outpatient", "o"):
            return False
        if info.get("capacity",1) < required_people: return False
        if slot_k in self.room_slots.get(room_code, set()): return False
        return True

    # ---------- allocation core (batch) ----------
    @transaction.atomic
    def assign_all(self, allocation_run: Optional[AllocationRun] = None):
        run = allocation_run
        if run is None:
            run = AllocationRun.objects.create(run_date=self.run_date, status="running")

        # load everything
        self.load_slots_from_db(); self.load_therapists_from_db(); self.load_rooms_from_db(); self.load_leaves_from_db(); self.load_therapy_and_repeats()
        bookings = self.load_bookings()

        # existing dharap
        try:
            existing_d = Assignment.objects.filter(therapy_code__icontains="dharap", created_at__date=self.run_date).count()
            self.dharap_assigned_today = existing_d
        except Exception:
            self.dharap_assigned_today = 0

        created = 0; self.fail_list = []

        def booking_priority(bk):
            vt = (bk.get("visit_type") or "") or ""
            is_ip = 1 if str(vt).strip().lower().startswith("ip") else 0
            vip = 1 if self.is_vip_patient(bk.get("preg_no"), bk) else 0
            diff = {"Hard":0,"Medium":1,"Easy":2}.get(self.get_difficulty(bk.get("therapy_code"), bk.get("therapy_name")),2)
            pref = bk.get("preferred_slot_label") or ""
            idx = 999
            if pref:
                try:
                    idx = next((i for i,k in enumerate(self.slots_order) if pref.lower() in str(self.slot_label.get(k,"")).lower()), 0)
                except Exception:
                    idx = 999
            return (-is_ip, -vip, diff, idx)

        bookings_sorted = sorted(bookings, key=booking_priority)
        first_three = set(self.slots_order[:3])

        for b in bookings_sorted:
            try:
                preg = b.get("preg_no")
                tcode = str(b.get("therapy_code") or "").strip()
                tname = str(b.get("therapy_name") or "") or ""
                visit_type = b.get("visit_type") or ""
                is_vip_flag = self.is_vip_patient(preg, b)
                preferred_label = b.get("preferred_slot_label") or ""
                preferred_room = b.get("preferred_room")
                difficulty = self.get_difficulty(tcode, tname)
                comp = self.get_required_composition(tcode, tname)
                total_needed = int(comp.get("total", MIN_THERAPISTS_PER_TREATMENT))
                total_needed = max(MIN_THERAPISTS_PER_TREATMENT, min(MAX_THERAPISTS_PER_TREATMENT, total_needed))
                seniors_needed = int(comp.get("seniors", 0) or 0)
                juniors_needed = int(comp.get("juniors", 0) or 0)
                bathing_required = bool(comp.get("bathing_required", False))

                # special Dharap
                if "dharap" in tname.lower():
                    if not self.dharap_can_allocate_more():
                        self.fail_list.append((b, "dharap_daily_limit_reached")); continue
                    seniors_needed = max(seniors_needed, 4); juniors_needed = max(juniors_needed, 2); total_needed = max(total_needed, 6)

                # build slots_to_try
                slots_to_try=[]
                if preferred_label:
                    matched=None
                    for k,lbl in self.slot_label.items():
                        if preferred_label.strip().lower() in str(lbl or "").strip().lower():
                            matched=k; break
                    if matched: slots_to_try.append(matched)
                for k in self.slots_order:
                    if k not in slots_to_try: slots_to_try.append(k)

                assigned_group=None; assigned_slot=None; assigned_rooms=None

                # continuity previous therapist
                prev_thr=None
                try:
                    prev = Assignment.objects.filter(pat_reg_no=str(preg).strip(), therapy_code=tcode).order_by("-created_at").first()
                    if prev and prev.therapist_code: prev_thr = prev.therapist_code
                    else:
                        if PatientHistory is not None:
                            ph = PatientHistory.objects.filter(preg_no=str(preg).strip()).order_by("-date").first()
                            if ph and getattr(ph,"therapist_code",None): prev_thr = getattr(ph,"therapist_code")
                except Exception:
                    prev_thr=None

                # try slots
                for slot_k in slots_to_try:
                    slot_lbl = self.slot_label.get(slot_k,"")
                    slot_t = self.slot_time_map.get(slot_k)
                    # infer slot_type
                    slot_type=None
                    if slot_lbl:
                        if slot_lbl in OP_SLOT_TIME_LABELS: slot_type="OP"
                        elif slot_lbl in IP_SLOT_TIME_LABELS: slot_type="IP"
                    vtype = (str(visit_type) or "").strip().lower()
                    if vtype and vtype.startswith("op") and slot_type!="OP": continue
                    if vtype and vtype.startswith("ip") and slot_type!="IP": continue
                    # hard only in first three slots
                    if difficulty=="Hard" and slot_k not in first_three: continue
                    avail = self._available_therapists_for_slot(slot_k)
                    if not avail: continue
                    if difficulty=="Hard":
                        avail = [c for c in avail if "super_senior" not in (self.therapists[c]["grade"] or "")]
                    # pools
                    seniors_pool=[c for c in avail if "senior" in (self.therapists[c]["grade"] or "")]
                    juniors_pool=[c for c in avail if "junior" in (self.therapists[c]["grade"] or "")]
                    trainee_pool=[c for c in avail if "trainee" in (self.therapists[c]["grade"] or "")]
                    bathing_pool=[c for c in avail if self.therapists[c].get("is_bathing")]
                    prefer_seniors = slot_k in first_three

                    preferred_codes=[]
                    if prev_thr and prev_thr in avail and prev_thr not in self.on_leave:
                        preferred_codes.append(prev_thr)
                    elif is_vip_flag:
                        cand=[c for c in seniors_pool if c in avail]
                        if cand: preferred_codes.append(cand[0])

                    def sort_codes(codes): return self._sort_candidates(codes, difficulty)

                    chosen=[]
                    for p in preferred_codes:
                        if p and p in avail and p not in chosen: chosen.append(p)

                    # ensure composition
                    if seniors_needed>0 or juniors_needed>0:
                        s_sorted=sort_codes([c for c in avail if "senior" in (self.therapists[c]["grade"] or "")])
                        j_sorted=sort_codes([c for c in avail if "junior" in (self.therapists[c]["grade"] or "")] + trainee_pool)
                        for c in s_sorted:
                            if c in chosen: continue
                            chosen.append(c)
                            if len([x for x in chosen if "senior" in (self.therapists[x]["grade"] or "")])>=seniors_needed: break
                        for c in j_sorted:
                            if c in chosen: continue
                            chosen.append(c)
                            if len([x for x in chosen if ("junior" in (self.therapists[x]["grade"] or "") or "trainee" in (self.therapists[x]["grade"] or ""))])>=juniors_needed: break
                        if len(chosen) < total_needed:
                            general = sort_codes([c for c in avail if c not in chosen])
                            for c in general:
                                chosen.append(c)
                                if len(chosen) >= total_needed: break
                    else:
                        pool = avail
                        if prefer_seniors:
                            senior_pool_all = [c for c in pool if "senior" in (self.therapists[c]["grade"] or "")]
                            if len(senior_pool_all) >= total_needed: pool = senior_pool_all
                        chosen = sort_codes(pool)[:total_needed]

                    if not chosen or len(chosen) < total_needed: continue

                    # bathing constraint: if therapy requires bathing, need at least ONE bathing therapist in chosen
                    if bathing_required:
                        current_bathing = [c for c in chosen if self.therapists.get(c,{}).get("is_bathing")]
                        if not current_bathing:
                            # try to replace a non-bathing with a bathing therapist (prefer previous bathing)
                            prev_bathing = None
                            try:
                                # find from patient history last bathing therapist
                                if PatientHistory is not None:
                                    ph = PatientHistory.objects.filter(preg_no=str(preg).strip()).order_by("-date").first()
                                    if ph and getattr(ph,"therapist_code",None):
                                        thr_code = getattr(ph,"therapist_code")
                                        if thr_code in bathing_pool and thr_code in avail:
                                            prev_bathing = thr_code
                            except Exception:
                                prev_bathing=None
                            if prev_bathing and prev_bathing not in chosen:
                                # replace the least-preferred chosen member
                                chosen[-1] = prev_bathing
                            else:
                                bath_candidates = sort_codes([c for c in bathing_pool if c not in chosen])
                                if bath_candidates:
                                    chosen[-1] = bath_candidates[0]
                                else:
                                    # cannot satisfy bathing requirement here
                                    continue

                    # POT constraint
                    if "pot" in tname.lower():
                        non_seniors = [c for c in chosen if "senior" not in (self.therapists[c]["grade"] or "")]
                        if non_seniors:
                            seniors_available = sort_codes([c for c in avail if "senior" in (self.therapists[c]["grade"] or "") and c not in chosen])
                            for i in range(len(chosen)):
                                if "senior" not in (self.therapists[chosen[i]]["grade"] or "") and seniors_available:
                                    chosen[i] = seniors_available.pop(0)
                            non_seniors = [c for c in chosen if "senior" not in (self.therapists[c]["grade"] or "")]
                            if non_seniors: continue
                        # per-senior pot limit
                        any_exceed=False
                        for c in chosen:
                            if self.therapist_loads[c]["pot"] >= POT_LIMIT_PER_SENIOR_PER_DAY:
                                any_exceed=True; break
                        if any_exceed: continue

                    # Room assignment
                    required_people = len(chosen)
                    assigned_room_list=[]
                    if preferred_room and preferred_room in self.rooms and self._room_ok_for_patient(preferred_room, visit_type, slot_k, required_people):
                        assigned_room_list=[preferred_room]
                    else:
                        single_room=None
                        for rc,info in self.rooms.items():
                            if slot_k in self.room_slots.get(rc,set()): continue
                            if info.get("capacity",1) >= required_people:
                                if "opd" in (info.get("type") or "").lower() and not (visit_type and str(visit_type).strip().lower().startswith("op")):
                                    continue
                                single_room = rc; break
                        if single_room:
                            assigned_room_list=[single_room]
                        else:
                            free_rooms=[rc for rc in self.rooms.keys() if slot_k not in self.room_slots.get(rc,set())]
                            if not (visit_type and str(visit_type).strip().lower().startswith("op")):
                                free_rooms=[rc for rc in free_rooms if "opd" not in (self.rooms[rc].get("type") or "").lower()]
                            if len(free_rooms) >= required_people:
                                assigned_room_list = free_rooms[:required_people]
                            else:
                                continue

                    # per-therapist room-type limits
                    room_map={}
                    if len(assigned_room_list)==1:
                        for thr in chosen: room_map[thr]=assigned_room_list[0]
                    else:
                        for idx, thr in enumerate(chosen):
                            room_map[thr] = assigned_room_list[idx] if idx < len(assigned_room_list) else assigned_room_list[0]

                    violation=False
                    for thr, rc in room_map.items():
                        rtype = (self.rooms.get(rc,{}).get("type") or "regular").lower()
                        curr = self.therapist_room_type_counts[thr].get(rtype,0)
                        allowed = ROOM_LIMITS_PER_THERAPIST.get(rtype, ROOM_LIMITS_PER_THERAPIST.get("regular",2))
                        if (curr + 1) > allowed:
                            violation=True; break
                    if violation: continue

                    # all checks passed: assign
                    assigned_group = chosen; assigned_slot = slot_k; assigned_rooms = assigned_room_list
                    break

                # end for slots

                if not assigned_group:
                    self.fail_list.append((b, "no_slot_or_group_found"))
                    continue

                # persist assignments
                for i, thr in enumerate(assigned_group):
                    rc = assigned_rooms[0] if len(assigned_rooms)==1 else (assigned_rooms[i] if i < len(assigned_rooms) else assigned_rooms[0])
                    self.therapist_slots[thr].add(assigned_slot)
                    self.room_slots[rc].add(assigned_slot)
                    self.therapist_loads[thr]["sessions"] += 1
                    self.therapist_loads[thr][difficulty.lower()] += 1
                    if "pot" in tname.lower(): self.therapist_loads[thr]["pot"] += 1
                    rtype = (self.rooms.get(rc,{}).get("type") or "regular").lower()
                    self.therapist_room_type_counts[thr][rtype] += 1
                    self.rotation_counter[thr] += 1
                    try:
                        Assignment.objects.create(
                            allocation=run,
                            pat_reg_no=str(preg).strip(),
                            therapy_code=tcode,
                            therapist_code=thr,
                            slot_no=(self.slots_order.index(assigned_slot)+1) if assigned_slot in self.slots_order else None,
                            slot_label=self.slot_label.get(assigned_slot, assigned_slot),
                            room_code=rc,
                            reason=None,
                            difficulty=difficulty
                        )
                        created += 1
                    except Exception as e:
                        self.fail_list.append((b, f"db_write_error:{e}"))

                if "dharap" in str(tname).lower():
                    self.dharap_assigned_today += 1

            except Exception as ex:
                self.fail_list.append((b, f"exception:{str(ex)}"))
                continue

        try:
            run.status = "completed" if not self.fail_list else "completed_with_issues"
            run.save()
        except Exception:
            pass

        return {"created": created, "failures": len(self.fail_list), "fail_list": self.fail_list, "dharap_assigned": self.dharap_assigned_today}

    # ---------- allocate a single visit (real-time) ----------
    @transaction.atomic
    def allocate_visit(self, visit_id: Optional[int] = None, visit_obj: Optional[Any] = None):
        # prepare data
        self.load_slots_from_db(); self.load_therapists_from_db(); self.load_rooms_from_db(); self.load_leaves_from_db(); self.load_therapy_and_repeats()

        v = visit_obj
        if visit_id and visit_obj is None and Visit is not None:
            try: v = Visit.objects.using(self.external_db_alias).get(pk=visit_id)
            except Exception as e: return {"status":"error","reason":f"visit_not_found:{e}"}

        # allow visit_obj to be a dict (for demo/test)
        try:
            if isinstance(v, dict):
                b = v
            else:
                b = {
                    "visit_obj": v,
                    "preg_no": getattr(v,"pat_reg_no",None) or getattr(v,"PReg_No",None) or "",
                    "therapy_code": getattr(v,"therapy_code",None) or getattr(v,"Therapy_Code",None) or "",
                    "therapy_name": getattr(v,"therapy_name",None) or getattr(v,"Therapy_Name",None) or "",
                    "preferred_slot_label": getattr(v,"start_time",None) or getattr(v,"Start_Time",None) or "",
                    "preferred_room": getattr(v,"troom_no",None) or getattr(v,"TRoom_No",None) or None,
                    "visit_type": getattr(v,"is_ip_or_op",None) or getattr(v,"visit_type",None) or "",
                    "is_vip": bool(getattr(v,"is_vip",False)),
                    "raw": v
                }
        except Exception:
            return {"status":"error","reason":"invalid_visit_object"}

        # create or reuse run
        run = None
        try:
            run = AllocationRun.objects.create(run_date=self.run_date, status="running")
        except Exception:
            try: run = AllocationRun.objects.filter(run_date=self.run_date).order_by("-id").first()
            except Exception: run = None

        # Use same allocation logic but only for single booking (extract)
        try:
            # re-use inner simplified version of assign_all's slot loop
            def _assign_single_booking(bk):
                preg = bk.get("preg_no"); tcode = str(bk.get("therapy_code") or "").strip()
                tname = str(bk.get("therapy_name") or "") or ""; visit_type = bk.get("visit_type") or ""
                is_vip_flag = self.is_vip_patient(preg, bk)
                preferred_label = bk.get("preferred_slot_label") or ""; preferred_room = bk.get("preferred_room")
                difficulty = self.get_difficulty(tcode, tname); comp = self.get_required_composition(tcode, tname)
                total_needed = int(comp.get("total", MIN_THERAPISTS_PER_TREATMENT))
                total_needed = max(MIN_THERAPISTS_PER_TREATMENT, min(MAX_THERAPISTS_PER_TREATMENT, total_needed))
                seniors_needed = int(comp.get("seniors",0) or 0); juniors_needed = int(comp.get("juniors",0) or 0)
                bathing_required = bool(comp.get("bathing_required", False))

                if "dharap" in tname.lower():
                    if not self.dharap_can_allocate_more(): return {"status":"failed","reason":"dharap_daily_limit_reached"}
                    seniors_needed = max(seniors_needed,4); juniors_needed=max(juniors_needed,2); total_needed=max(total_needed,6)

                slots_to_try=[]
                if preferred_label:
                    matched=None
                    for k,lbl in self.slot_label.items():
                        if preferred_label.strip().lower() in str(lbl or "").strip().lower():
                            matched=k; break
                    if matched: slots_to_try.append(matched)
                for k in self.slots_order:
                    if k not in slots_to_try: slots_to_try.append(k)

                first_three = set(self.slots_order[:3])

                for slot_k in slots_to_try:
                    slot_lbl = self.slot_label.get(slot_k,"")
                    slot_type=None
                    if slot_lbl:
                        if slot_lbl in OP_SLOT_TIME_LABELS: slot_type="OP"
                        elif slot_lbl in IP_SLOT_TIME_LABELS: slot_type="IP"
                    vtype = (str(visit_type) or "").strip().lower()
                    if vtype and vtype.startswith("op") and slot_type!="OP": continue
                    if vtype and vtype.startswith("ip") and slot_type!="IP": continue
                    if difficulty=="Hard" and slot_k not in first_three: continue
                    avail=self._available_therapists_for_slot(slot_k)
                    if not avail: continue
                    if difficulty=="Hard":
                        avail=[c for c in avail if "super_senior" not in (self.therapists[c]["grade"] or "")]
                    def sort_codes(codes): return self._sort_candidates(codes,difficulty)
                    chosen=[]
                    # continuity & vip
                    prev_thr=None
                    try:
                        prev=Assignment.objects.filter(pat_reg_no=str(preg).strip(), therapy_code=tcode).order_by("-created_at").first()
                        if prev and prev.therapist_code: prev_thr=prev.therapist_code
                    except Exception: prev_thr=None
                    if prev_thr and prev_thr in avail: chosen.append(prev_thr)
                    elif is_vip_flag:
                        cand=[c for c in avail if "senior" in (self.therapists[c]["grade"] or "")]
                        if cand: chosen.append(cand[0])
                    # pick composition
                    if seniors_needed>0 or juniors_needed>0:
                        s_sorted=sort_codes([c for c in avail if "senior" in (self.therapists[c]["grade"] or "")])
                        j_sorted=sort_codes([c for c in avail if "junior" in (self.therapists[c]["grade"] or "")])
                        for c in s_sorted:
                            if c in chosen: continue
                            chosen.append(c)
                            if len([x for x in chosen if "senior" in (self.therapists[x]["grade"] or "")])>=seniors_needed: break
                        for c in j_sorted:
                            if c in chosen: continue
                            chosen.append(c)
                            if len([x for x in chosen if "junior" in (self.therapists[x]["grade"] or "")])>=juniors_needed: break
                        if len(chosen) < total_needed:
                            general = sort_codes([c for c in avail if c not in chosen])
                            for c in general:
                                chosen.append(c)
                                if len(chosen) >= total_needed: break
                    else:
                        pool = avail
                        if slot_k in first_three:
                            sp=[c for c in pool if "senior" in (self.therapists[c]["grade"] or "")]
                            if len(sp) >= total_needed: pool=sp
                        chosen = sort_codes(pool)[:total_needed]

                    if not chosen or len(chosen) < total_needed: continue

                    # bathing requirement
                    if bathing_required:
                        if not any(self.therapists.get(c,{}).get("is_bathing") for c in chosen):
                            bathing_pool = sort_codes([c for c in avail if self.therapists[c].get("is_bathing")])
                            if bathing_pool:
                                chosen[-1] = bathing_pool[0]
                            else:
                                continue

                    # rooms - try preferred then single large room else multiple
                    required_people = len(chosen)
                    assigned_room = None
                    if preferred_room and preferred_room in self.rooms and self._room_ok_for_patient(preferred_room, visit_type, slot_k, required_people):
                        assigned_room = preferred_room
                    else:
                        for rc,info in self.rooms.items():
                            if slot_k in self.room_slots.get(rc,set()): continue
                            if info.get("capacity",1) >= required_people:
                                if "opd" in (info.get("type") or "").lower() and not (visit_type and str(visit_type).strip().lower().startswith("op")):
                                    continue
                                assigned_room = rc; break
                        if not assigned_room:
                            continue

                    # check room-type limits per therapist
                    violation=False
                    for thr in chosen:
                        rtype=(self.rooms.get(assigned_room,{}).get("type") or "regular").lower()
                        curr=self.therapist_room_type_counts[thr].get(rtype,0)
                        allowed=ROOM_LIMITS_PER_THERAPIST.get(rtype, ROOM_LIMITS_PER_THERAPIST.get("regular",2))
                        if (curr+1) > allowed:
                            violation=True; break
                    if violation: continue

                    # commit to DB and trackers
                    for thr in chosen:
                        self.therapist_slots[thr].add(slot_k)
                        self.room_slots[assigned_room].add(slot_k)
                        self.therapist_loads[thr]["sessions"] += 1
                        self.therapist_loads[thr][difficulty.lower()] += 1
                        if "pot" in tname.lower(): self.therapist_loads[thr]["pot"] += 1
                        rtype=(self.rooms.get(assigned_room,{}).get("type") or "regular").lower()
                        self.therapist_room_type_counts[thr][rtype] += 1
                        self.rotation_counter[thr] += 1
                        try:
                            Assignment.objects.create(
                                allocation=run,
                                pat_reg_no=str(preg).strip(),
                                therapy_code=tcode,
                                therapist_code=thr,
                                slot_no=(self.slots_order.index(slot_k)+1) if slot_k in self.slots_order else None,
                                slot_label=self.slot_label.get(slot_k,slot_k),
                                room_code=assigned_room,
                                reason="realtime_alloc",
                                difficulty=difficulty
                            )
                        except Exception as e:
                            return {"status":"failed","reason":f"db_write_error:{e}"}
                    if "dharap" in tname.lower(): self.dharap_assigned_today += 1
                    return {"status":"success","slot": self.slot_label.get(slot_k,slot_k), "therapists": chosen, "room": assigned_room}
                return {"status":"failed","reason":"no_slot_found"}

            return _assign_single_booking(b)
        except Exception as ex:
            return {"status":"error","reason":f"exception:{ex}", "trace": traceback.format_exc()}

    # ---------- delete allocations for a specific date ----------
    def delete_allocations_for_date(self, date: datetime.date):
        try:
            qs = Assignment.objects.filter(created_at__date=date)
            cnt = qs.count()
            qs.delete()
            return cnt
        except Exception:
            return 0
