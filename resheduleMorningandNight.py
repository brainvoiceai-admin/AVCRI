#!/usr/bin/env python3
"""
reschedule_full_reassign.py

Standalone script to reassign TherapistBooking rows when therapists take EmergencyLeave.
Place this file next to manage.py and run from project root.

Edit DJANGO_SETTINGS_MODULE below to your project's settings module if needed.

Usage:
    python reschedule_full_reassign.py [--dry-run] [--date YYYY-MM-DD] [--settings myproject.settings]
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from collections import Counter

# -------------------------
# DJANGO SETTINGS - EDIT IF NEEDED
# -------------------------
# default: will use DJANGO_SETTINGS_MODULE env var if you already set it, otherwise change below
DEFAULT_DJANGO_SETTINGS = "AVCRI.settings"  # <-- CHANGE THIS to your project settings module if needed

# -------------------------
# Attempt to setup Django
# -------------------------
parser = argparse.ArgumentParser(description="Reassign therapist bookings when therapist is on emergency leave.")
parser.add_argument("--dry-run", action="store_true", help="Do not commit changes; show what would happen.")
parser.add_argument("--date", type=str, default=None, help="Date to run for (YYYY-MM-DD). Defaults to today (server local timezone).")
parser.add_argument("--settings", type=str, default=None, help="Optional DJANGO_SETTINGS_MODULE to use.")
args = parser.parse_args()

# apply settings if provided
if args.settings:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", args.settings)
else:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", DEFAULT_DJANGO_SETTINGS))

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

try:
    import django

    django.setup()
except Exception as e:
    logger.exception("Failed to setup Django. Make sure this script runs from the project root and DJANGO_SETTINGS_MODULE is set. Error: %s", e)
    sys.exit(1)

from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Count

# -------------------------
# Model import helper (try multiple likely modules)
# -------------------------
import importlib


def import_model(name_candidates):
    """
    Try importing a model/class from a list of "<module>:<Name>" strings.
    Return the class if found, else None.
    """
    for cand in name_candidates:
        try:
            module_name, cls_name = cand.split(":")
        except ValueError:
            logger.warning("Bad import candidate format (expected module:Class): %s", cand)
            continue
        try:
            mod = importlib.import_module(module_name)
            cls = getattr(mod, cls_name, None)
            if cls:
                logger.debug("Imported %s from %s", cls_name, module_name)
                return cls
        except Exception:
            continue
    return None


# Common candidate import paths (edit/add to suit your project)
MODEL_IMPORT_HINTS = {
    # TherapistBooking likely in Patient.models
    "TherapistBooking": ["Patient.models:TherapistBooking", "your_app.models:TherapistBooking"],
    # EmergencyLeave may be in HR/leave app or same app as other models
    "EmergencyLeave": ["your_app.models:EmergencyLeave", "Patient.models:EmergencyLeave", "leaves.models:EmergencyLeave", "masters.models:EmergencyLeave"],
    # TherapistMaster and TherapistLeaveMaster usually in masters.models
    "TherapistMaster": ["masters.models:TherapistMaster", "your_app.models:TherapistMaster"],
    "TherapistLeaveMaster": ["masters.models:TherapistLeaveMaster", "your_app.models:TherapistLeaveMaster"],
    "TherapyMaster": ["masters.models:TherapyMaster"],
    "RoomBooking": ["Patient.models:RoomBooking"],
    "SlotMaster": ["masters.models:SlotMaster"],
    "RoomBookingModel": ["Patient.models:RoomBooking"],
}

# import models (best-effort)
TherapistBooking = import_model(MODEL_IMPORT_HINTS["TherapistBooking"])
EmergencyLeave = import_model(MODEL_IMPORT_HINTS["EmergencyLeave"])
TherapistMaster = import_model(MODEL_IMPORT_HINTS["TherapistMaster"])
TherapistLeaveMaster = import_model(MODEL_IMPORT_HINTS["TherapistLeaveMaster"])
TherapyMaster = import_model(MODEL_IMPORT_HINTS["TherapyMaster"])
RoomBooking = import_model(MODEL_IMPORT_HINTS["RoomBooking"])

# Validate imports
missing = []
if TherapistBooking is None:
    missing.append("TherapistBooking")
if EmergencyLeave is None:
    missing.append("EmergencyLeave")
if TherapistMaster is None:
    missing.append("TherapistMaster")
if TherapistLeaveMaster is None:
    missing.append("TherapistLeaveMaster")
if TherapyMaster is None:
    logger.debug("TherapyMaster not found; some fallback behavior will use default counts.")

if missing:
    logger.error("Failed to import required models: %s. Please update MODEL_IMPORT_HINTS in script to point to correct modules.", ", ".join(missing))
    sys.exit(1)

# -------------------------
# Import helper functions from reshedule.py
# -------------------------
try:
    # Try to import from reshedule.py if available
    import reshedule
    is_treatment_requiring_senior_tag = getattr(reshedule, 'is_treatment_requiring_senior_tag', None)
    get_therapy_details = getattr(reshedule, 'get_therapy_details', None)
    therapy_needs_room = getattr(reshedule, 'therapy_needs_room', None)
    therapy_needs_bath = getattr(reshedule, 'therapy_needs_bath', None)
    get_therapist_grade_name = getattr(reshedule, 'get_therapist_grade_name', None)
    therapist_requirements = getattr(reshedule, 'therapist_requirements', None)
except Exception:
    # Define fallback functions if import fails
    is_treatment_requiring_senior_tag = None
    get_therapy_details = None
    therapy_needs_room = None
    therapy_needs_bath = None
    get_therapist_grade_name = None
    therapist_requirements = None

# Define helper functions if not imported
if not is_treatment_requiring_senior_tag:
    def is_treatment_requiring_senior_tag(therapy_name):
        """Check if a treatment requires special senior tag handling."""
        if not therapy_name:
            return False
        therapy_lower = str(therapy_name).lower().strip()
        has_dhara = 'dhara' in therapy_lower
        has_thakradhara = 'thakradhara' in therapy_lower
        if not (has_dhara or has_thakradhara):
            return False
        has_pizhichil = 'pizhichil' in therapy_lower or 'pizichil' in therapy_lower
        has_abh = 'abh' in therapy_lower and 'abhyangam' not in therapy_lower
        has_abyangam = 'abyangam' in therapy_lower or 'abhyangam' in therapy_lower
        if has_dhara and (has_pizhichil or has_abh or has_abyangam):
            return True
        if has_thakradhara and (has_pizhichil or has_abyangam):
            return True
        return False

if not get_therapist_grade_name:
    def get_therapist_grade_name(therapist):
        """Get therapist grade name from TherapistGrade FK"""
        if not therapist:
            return ''
        if hasattr(therapist, 'therapist_grade') and therapist.therapist_grade:
            if hasattr(therapist.therapist_grade, 'name'):
                return therapist.therapist_grade.name
        return ''

if not therapist_requirements:
    therapy_cache = {}
    def get_therapy_details(therapy_name):
        """Get therapy details from TherapyMaster"""
        if not TherapyMaster:
            return None
        name = (therapy_name or "").strip().lower()
        if not name:
            return None
        if name in therapy_cache:
            return therapy_cache[name]
        try:
            details = TherapyMaster.objects.filter(therapy_name__iexact=therapy_name).first()
            therapy_cache[name] = details
            return details
        except Exception:
            therapy_cache[name] = None
            return None
    
    def therapist_requirements(booking_or_therapy):
        """Get therapist requirements from TherapyMaster"""
        name = getattr(booking_or_therapy, 'therapy_name', None)
        details = get_therapy_details(name) if name else None
        if not details:
            return {"super_senior":0, "senior":0, "junior":0, "trainee":0, "total":1, "therapy_code": None, "therapy_category": None}
        return {
            "super_senior": int(getattr(details, 'no_of_super_senior_therapist', 0) or 0),
            "senior": int(getattr(details, 'no_of_senior_therapist', 0) or 0),
            "junior": int(getattr(details, 'no_of_junior_therapist', 0) or 0),
            "trainee": int(getattr(details, 'no_of_trainee_therapist', 0) or 0),
            "total": int(getattr(details, 'total_no_of_therapist', 0) or 1),
            "therapy_code": getattr(details, 'therapy_code', None),
            "therapy_category": getattr(details, 'therapy_category', None)
        }

# -------------------------
# Utility helpers
# -------------------------
def parse_target_date(date_str=None):
    if date_str:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            logger.error("Invalid date format: %s. Use YYYY-MM-DD.", date_str)
            sys.exit(1)
    return timezone.localtime(timezone.now()).date()


def get_emergency_leave_sets_for_date(target_date):
    """
    Returns (set_of_therapist_pks, set_of_employee_codes) for EmergencyLeave overlapping target_date.
    """
    try:
        leaves = EmergencyLeave.objects.filter(from_date__lte=target_date, to_date__gte=target_date)
        em_ids = set(leaves.exclude(therapist__isnull=True).values_list("therapist__pk", flat=True))
        em_codes = set(leaves.exclude(employee_code__isnull=True).values_list("employee_code", flat=True))
        return em_ids, em_codes
    except Exception as e:
        logger.exception("Error fetching EmergencyLeave: %s", e)
        return set(), set()


def therapist_has_weekly_leave_on(t_obj, target_date):
    """
    Return True if t_obj has an active weekly leave on the weekday of target_date.
    """
    try:
        dow = target_date.weekday()
        return TherapistLeaveMaster.objects.filter(therapist=t_obj, leave_day=dow, is_active=True).exists()
    except Exception:
        return False


def get_required_therapist_count_for_booking(booking):
    """
    Determine the required number of therapists for the treatment for this booking.
    Uses therapist_requirements to get total count.
    """
    try:
        req = therapist_requirements(booking) if therapist_requirements else {}
        return int(req.get("total", 1) or 1)
    except Exception:
        logger.exception("Error determining required therapist count for booking %s", getattr(booking, "pk", None))
    return 1

def get_patient_gender_from_booking(booking):
    """
    Get patient gender from booking. Tries multiple sources.
    """
    try:
        # Try to get from booking's patient relationship
        if hasattr(booking, 'patient') and booking.patient:
            if hasattr(booking.patient, 'pat_sex'):
                return booking.patient.pat_sex
        # Try to get from visit (TherapyAllocation)
        if hasattr(booking, 'visit') and booking.visit:
            if hasattr(booking.visit, 'patient') and booking.visit.patient:
                if hasattr(booking.visit.patient, 'pat_sex'):
                    return booking.visit.patient.pat_sex
        # Try from PatientSnapshot via patient_id
        try:
            from Sheduling.models import PatientSnapshot
            if hasattr(booking, 'patient_id') and booking.patient_id:
                patient = PatientSnapshot.objects.filter(pat_reg_no=str(booking.patient_id)).first()
                if patient and hasattr(patient, 'pat_sex'):
                    return patient.pat_sex
        except Exception:
            pass
    except Exception:
        pass
    return None

def normalize_patient_gender(pat_sex):
    """Normalize patient gender to 'male' or 'female'"""
    if not pat_sex:
        return None
    g = str(pat_sex).strip().lower()
    if g.startswith('f'):
        return 'female'
    elif g.startswith('m'):
        return 'male'
    return None

def get_therapist_gender(therapist):
    """Get therapist gender from TherapistMaster"""
    try:
        v = getattr(therapist, 'therapist_gender', None)
        if v:
            v_str = str(v).strip()
            if v_str.lower().startswith('m'):
                return 'male'
            if v_str.lower().startswith('f'):
                return 'female'
    except Exception:
        pass
    return None

def patient_already_has_booking(patient_id, target_date, time_slot, exclude_booking_pk=None, exclude_allocation=None):
    """
    Check if patient already has a booking at this date+slot.
    Excludes the current booking and bookings from same allocation.
    """
    try:
        room_qs = RoomBooking.objects.filter(
            patient_id=patient_id,
            date=target_date,
            time_slot=time_slot,
            status__in=['BOOKED', 'scheduled']
        )
        if exclude_booking_pk:
            room_qs = room_qs.exclude(pk=exclude_booking_pk)
        if exclude_allocation and hasattr(RoomBooking, 'therapy'):
            room_qs = room_qs.exclude(therapy=exclude_allocation)
        
        therapist_qs = TherapistBooking.objects.filter(
            patient_id=patient_id,
            date=target_date,
            time_slot=time_slot,
            status='BOOKED'
        )
        if exclude_booking_pk:
            therapist_qs = therapist_qs.exclude(pk=exclude_booking_pk)
        if exclude_allocation and hasattr(TherapistBooking, 'visit'):
            therapist_qs = therapist_qs.exclude(visit=exclude_allocation)
        
        return room_qs.exists() or therapist_qs.exists()
    except Exception:
        return False


def count_assigned_therapists_for_patient_slot(patient_id, target_date, time_slot):
    """
    Count therapist bookings for a patient at target_date+time_slot in statuses considered active.
    """
    active_statuses = ['BOOKED', 'scheduled']
    try:
        return TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=time_slot, status__in=active_statuses).count()
    except Exception:
        return 0


def should_cancel_full_treatment(booking, target_date):
    """
    Decide whether to cancel the full treatment (all bookings for the patient at that date+slot).
    If removing this booking would make assigned_count < required_count => cancel full treatment.
    """
    required = get_required_therapist_count_for_booking(booking)
    assigned = count_assigned_therapists_for_patient_slot(booking.patient_id, target_date, booking.time_slot)
    # assigned includes current booking, so removing one -> assigned - 1
    return (assigned - 1) < required


def cancel_full_treatment_for_patient_slot(patient_id, target_date, time_slot, by_user=None, reason="therapist_unavailable"):
    """
    Cancel all TherapistBooking & RoomBooking for this patient/date/slot.
    Returns counts of canceled records.
    """
    canceled = {"therapist_bookings": 0, "room_bookings": 0}
    try:
        tbs = TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=time_slot, status__in=['BOOKED', 'scheduled'])
        for tb in tbs:
            try:
                tb.cancel(by_user=by_user, reason=reason, cascade=True)
                canceled['therapist_bookings'] += 1
            except Exception:
                # fallback: mark canceled
                try:
                    tb.status = 'CANCELED'
                    tb.save(update_fields=['status', 'updated_at'])
                    canceled['therapist_bookings'] += 1
                except Exception:
                    logger.exception("Failed to cancel TherapistBooking %s", getattr(tb, 'pk', None))
    except Exception:
        logger.exception("Error while canceling therapist bookings.")

    try:
        if RoomBooking:
            rbs = RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=time_slot, status__in=['BOOKED', 'scheduled'])
            for rb in rbs:
                try:
                    rb.status = 'CANCELED'
                    rb.save(update_fields=['status', 'updated_at'])
                    canceled['room_bookings'] += 1
                except Exception:
                    logger.exception("Failed to cancel RoomBooking %s", getattr(rb, 'pk', None))
    except Exception:
        logger.exception("Error while canceling room bookings.")

    return canceled


# -------------------------
# Candidate selection & assignment helpers
# -------------------------
def available_candidates_by_level_and_bathing(target_date, time_slot, level, require_bathing, 
                                               desired_gender=None, patient_gender=None, 
                                               em_therapist_ids=None, em_emp_codes=None,
                                               allow_trainee_substitution=False):
    """
    Return list of TherapistMaster candidates that:
      - have therapist_grade == level (or Junior if Trainee needed and allow_trainee_substitution=True)
      - optionally have is_bathing_therapist == True
      - match desired_gender if provided
      - are NOT on emergency leave (by FK or emp code)
      - do NOT have weekly leave on that weekday
      - NOT already BOOKED at date+slot
    """
    try:
        # Handle trainee substitution: if level is Trainee and desired_gender is male, search for Junior instead
        search_level = level
        if allow_trainee_substitution and desired_gender == 'male':
            # Check if level is Trainee Therapist
            level_name = get_therapist_grade_name(level) if hasattr(level, '__class__') else str(level)
            if 'Trainee' in str(level_name):
                # Find Junior Therapist grade
                try:
                    from masters.models import TherapistGrade
                    junior_grade = TherapistGrade.objects.filter(name__icontains='Junior').first()
                    if junior_grade:
                        search_level = junior_grade
                        logger.debug("Trainee substitution: Using Junior Therapist grade for male patient")
                except Exception:
                    pass
        
        qs = TherapistMaster.objects.filter(therapist_grade=search_level)
        
        # STRICT GENDER FILTER
        if desired_gender:
            qs = qs.filter(therapist_gender__istartswith=desired_gender[0])
        
        # STRICT: Only return bathing therapists when bathing is required
        if require_bathing:
            qs = qs.filter(is_bathing_therapist=True)
    except Exception:
        logger.exception("Error accessing TherapistMaster")
        return []

    if em_therapist_ids is None or em_emp_codes is None:
        em_therapist_ids, em_emp_codes = get_emergency_leave_sets_for_date(target_date)

    if em_therapist_ids:
        qs = qs.exclude(pk__in=em_therapist_ids)
    if em_emp_codes:
        qs = qs.exclude(employee_code__in=em_emp_codes)

    # exclude weekly leave therapists
    try:
        dow = target_date.weekday()
        weekly_leave_pks = list(TherapistLeaveMaster.objects.filter(leave_day=dow, is_active=True).values_list('therapist__pk', flat=True))
        if weekly_leave_pks:
            qs = qs.exclude(pk__in=weekly_leave_pks)
    except Exception:
        logger.debug("No weekly leave check applied (error or model missing)")

    # exclude therapists already booked at same slot
    try:
        busy_ids = list(TherapistBooking.objects.filter(date=target_date, time_slot=time_slot, status='BOOKED').values_list('therapist__pk', flat=True))
        if busy_ids:
            qs = qs.exclude(pk__in=busy_ids)
    except Exception:
        logger.debug("Skipping slot-busy exclusion due to error.")

    # Additional gender check (double-check after query)
    candidates = list(qs)
    if desired_gender:
        candidates = [c for c in candidates if get_therapist_gender(c) == desired_gender]

    return candidates


def find_previous_bathing_therapist_for_patient(booking, target_date, em_therapist_ids, em_emp_codes):
    """
    Find most recent previous bathing therapist for the same patient.
    Returns TherapistMaster instance or None.
    """
    try:
        prev_bath_booking = TherapistBooking.objects.filter(
            patient_id=booking.patient_id,
            is_bathing=True,
            status='BOOKED'
        ).exclude(
            pk=booking.pk
        ).exclude(
            date=target_date,
            time_slot=booking.time_slot
        ).select_related('therapist').order_by('-date', '-created_at').first()
        
        if prev_bath_booking and prev_bath_booking.therapist:
            cand = prev_bath_booking.therapist
            # Validate availability
            if getattr(cand, 'pk', None) in em_therapist_ids or getattr(cand, 'employee_code', None) in em_emp_codes:
                return None
            if therapist_has_weekly_leave_on(cand, target_date):
                return None
            if TherapistBooking.objects.filter(therapist=cand, date=target_date, time_slot=booking.time_slot, status='BOOKED').exists():
                return None
            if not getattr(cand, 'is_bathing_therapist', False):
                return None
            return cand
    except Exception:
        pass
    return None

def find_previous_assigned_therapist_for_booking_patient_only(booking, needs_bathing, same_level, target_date, 
                                                                em_therapist_ids, em_emp_codes, desired_gender=None):
    """
    Preference: 
    1. Most recent previous BATHING therapist if needs_bathing=True
    2. Most recent previous therapist for the same patient (ignore therapy).
    Validate candidate against constraints (level, bathing, gender, not on leave, not weekly leave, not already booked at slot).
    """
    # First try to find previous bathing therapist if needed
    if needs_bathing:
        prev_bath = find_previous_bathing_therapist_for_patient(booking, target_date, em_therapist_ids, em_emp_codes)
        if prev_bath:
            # Validate same level if required
            if same_level:
                old_grade = get_therapist_grade_name(booking.therapist) if booking.therapist else ''
                new_grade = get_therapist_grade_name(prev_bath)
                if old_grade != new_grade:
                    prev_bath = None  # Grade mismatch, continue to regular search
            # Validate gender if required
            if prev_bath and desired_gender:
                t_gender = get_therapist_gender(prev_bath)
                if t_gender != desired_gender:
                    prev_bath = None  # Gender mismatch, continue to regular search
            if prev_bath:
                return prev_bath
    
    # Fallback to regular previous therapist search
    try:
        prev = (TherapistBooking.objects
                .filter(patient_id=booking.patient_id)
                .exclude(pk=booking.pk)
                .order_by('-date')
                .select_related('therapist')
                .first())
    except Exception:
        prev = None

    if not prev or not prev.therapist:
        return None
    cand = prev.therapist

    # validate same level
    if same_level:
        old_grade = get_therapist_grade_name(booking.therapist) if booking.therapist else ''
        new_grade = get_therapist_grade_name(cand)
        if old_grade != new_grade:
            return None
    
    # validate gender match
    if desired_gender:
        t_gender = get_therapist_gender(cand)
        if t_gender != desired_gender:
            return None
    
    # validate bathing if needed
    if needs_bathing and not getattr(cand, 'is_bathing_therapist', False):
        return None

    # check emergency leave sets
    if getattr(cand, 'pk', None) in em_therapist_ids or getattr(cand, 'employee_code', None) in em_emp_codes:
        return None

    # weekly leave check
    if therapist_has_weekly_leave_on(cand, target_date):
        return None

    # slot conflict
    try:
        if TherapistBooking.objects.filter(therapist=cand, date=target_date, time_slot=booking.time_slot, status='BOOKED').exists():
            return None
    except Exception:
        pass

    return cand


def pick_least_loaded_candidate(candidates, target_date, max_daily_normal, max_daily_overtime_extra, therapy_category=None):
    """
    From candidate TherapistMaster list, pick one based on daily load and overtime rules,
    with additional balancing for the current therapy difficulty category (Easy/Medium/Hard).
    """
    if not candidates:
        return None
    cand_pks = [c.pk for c in candidates]
    try:
        counts_qs = (TherapistBooking.objects
                     .filter(therapist_id__in=cand_pks, date=target_date, status='BOOKED')
                     .values('therapist_id')
                     .annotate(cn=Count('pk')))
        counts = {row['therapist_id']: row['cn'] for row in counts_qs}
    except Exception:
        counts = {}
    for pk in cand_pks:
        counts.setdefault(pk, 0)

    # Category-specific counts using TherapyMaster FK when available
    category_counts = {}
    if therapy_category:
        try:
            cat_qs = (TherapistBooking.objects
                      .filter(
                          therapist_id__in=cand_pks,
                          date=target_date,
                          status='BOOKED',
                          therapy__therapy_category__iexact=str(therapy_category),
                      )
                      .values('therapist_id')
                      .annotate(cn=Count('pk')))
            category_counts = {row['therapist_id']: row['cn'] for row in cat_qs}
        except Exception:
            category_counts = {}
    for pk in cand_pks:
        category_counts.setdefault(pk, 0)

    def sort_key(p):
        # Prefer therapists with fewer sessions in this difficulty category,
        # then fewer total sessions, then stable by pk.
        return (category_counts.get(p, 0), counts.get(p, 0), p)

    under_normal = [pk for pk, cnt in counts.items() if cnt < max_daily_normal]
    if under_normal:
        pick_pk = sorted(under_normal, key=sort_key)[0]
        return next((c for c in candidates if c.pk == pick_pk), None)

    under_overtime = [pk for pk, cnt in counts.items() if cnt < (max_daily_normal + max_daily_overtime_extra)]
    if under_overtime:
        pick_pk = sorted(under_overtime, key=sort_key)[0]
        return next((c for c in candidates if c.pk == pick_pk), None)

    return None


# -------------------------
# Main algorithm
# -------------------------
def process_reassignments(target_date=None, dry_run=True, max_daily_normal=5, max_daily_overtime_extra=2):
    """
    Entry point. Returns summary dict.
    """
    if target_date is None:
        target_date = timezone.localtime(timezone.now()).date()

    summary = {'checked': 0, 'reassigned': [], 'cancelled': [], 'failed': []}

    em_therapist_ids, em_emp_codes = get_emergency_leave_sets_for_date(target_date)

    # find bookings whose therapist is on emergency leave
    try:
        qs = TherapistBooking.objects.filter(date=target_date, status='BOOKED').select_related('therapist', 'time_slot')
    except Exception as e:
        logger.exception("Failed to query TherapistBooking: %s", e)
        return summary

    affected = []
    for b in qs:
        thr = getattr(b, 'therapist', None)
        if not thr:
            continue
        if (getattr(thr, 'pk', None) in em_therapist_ids) or (getattr(thr, 'employee_code', None) in em_emp_codes):
            affected.append(b)

    logger.info("Found %d affected bookings for date %s", len(affected), target_date.isoformat())
    if not affected:
        return summary

    for booking in affected:
        summary['checked'] += 1
        old = booking.therapist
        if not old:
            continue
        
        # Get therapist grade properly
        old_grade_name = get_therapist_grade_name(old)
        try:
            from masters.models import TherapistGrade
            if old_grade_name:
                level = TherapistGrade.objects.filter(name=old_grade_name).first()
            else:
                level = getattr(old, 'therapist_grade', None)
        except Exception:
            level = getattr(old, 'therapist_grade', None)
        
        slot = booking.time_slot
        therapy_name = getattr(booking, 'therapy_name', None)

        # Determine therapy requirements (to get difficulty category for fair distribution)
        therapy_req = therapist_requirements(booking) if therapist_requirements else {}
        therapy_category = therapy_req.get("therapy_category")
        
        # Determine if therapy needs bathing (from TherapyMaster, not just booking flag)
        needs_bathing = False
        if therapy_needs_bath:
            needs_bathing = therapy_needs_bath(booking)
        else:
            needs_bathing = bool(getattr(booking, 'is_bathing', False))
        
        # Check if special treatment (Dhara & Pizichil)
        requires_senior_tag = False
        if is_treatment_requiring_senior_tag and therapy_name:
            requires_senior_tag = is_treatment_requiring_senior_tag(therapy_name)
        
        # Get patient gender
        patient_gender = get_patient_gender_from_booking(booking)
        desired_gender = normalize_patient_gender(patient_gender)
        
        # Check if patient already has booking at this slot (excluding this booking and same allocation)
        exclude_allocation = None
        if hasattr(booking, 'visit'):
            exclude_allocation = booking.visit
        if patient_already_has_booking(booking.patient_id, target_date, slot, 
                                       exclude_booking_pk=booking.pk, 
                                       exclude_allocation=exclude_allocation):
            logger.warning("Patient %s already has booking at %s %s - skipping reassignment", 
                          booking.patient_id, target_date, slot)
            summary['failed'].append((booking.pk, "patient_already_has_booking_at_slot"))
            continue

        # 1) prefer previous therapist for same patient (not patient+therapy)
        # Prioritize previous bathing therapist if needed
        prev = find_previous_assigned_therapist_for_booking_patient_only(
            booking, needs_bathing=needs_bathing,
            same_level=True, target_date=target_date,
            em_therapist_ids=em_therapist_ids, em_emp_codes=em_emp_codes,
            desired_gender=desired_gender
        )
        if prev:
            today_cnt = TherapistBooking.objects.filter(therapist=prev, date=target_date, status='BOOKED').count()
            if today_cnt < max_daily_normal or today_cnt < (max_daily_normal + max_daily_overtime_extra):
                # reassign to prev
                if dry_run:
                    summary['reassigned'].append((booking.pk, getattr(old, 'therapist_code', old.pk), getattr(prev, 'therapist_code', prev.pk)))
                    logger.info("[DRY RUN] Would reassign booking %s -> therapist %s", booking.pk, getattr(prev, 'therapist_code', prev.pk))
                else:
                    try:
                        with transaction.atomic():
                            booking.therapist = prev
                            if hasattr(booking, 'is_bathing') and needs_bathing:
                                booking.is_bathing = True
                            booking.save(update_fields=['therapist', 'updated_at'] + (['is_bathing'] if hasattr(booking, 'is_bathing') else []))
                        summary['reassigned'].append((booking.pk, getattr(old, 'therapist_code', old.pk), getattr(prev, 'therapist_code', prev.pk)))
                        logger.info("Reassigned booking %s -> therapist %s", booking.pk, getattr(prev, 'therapist_code', prev.pk))
                    except Exception as e:
                        logger.exception("Error reassigning booking %s to prev therapist: %s", booking.pk, e)
                        summary['failed'].append((booking.pk, str(e)))
                continue

        # 2) build candidate pool by level & bathing requirement with gender matching
        # Check if trainee substitution is needed (male trainee -> junior)
        allow_trainee_sub = False
        if old_grade_name and 'Trainee' in old_grade_name and desired_gender == 'male':
            allow_trainee_sub = True
        
        candidates = available_candidates_by_level_and_bathing(
            target_date, slot, level, require_bathing=needs_bathing, 
            desired_gender=desired_gender, patient_gender=patient_gender,
            em_therapist_ids=em_therapist_ids, em_emp_codes=em_emp_codes,
            allow_trainee_substitution=allow_trainee_sub
        )

        # If booking doesn't require bathing and no bathing-only candidates, allow any same-level therapist
        if not candidates and not needs_bathing:
            candidates = available_candidates_by_level_and_bathing(
                target_date, slot, level, require_bathing=False,
                desired_gender=desired_gender, patient_gender=patient_gender,
                em_therapist_ids=em_therapist_ids, em_emp_codes=em_emp_codes,
                allow_trainee_substitution=allow_trainee_sub
            )

        # 3) if no candidates -> cancel (single or full treatment)
        if not candidates:
            if should_cancel_full_treatment(booking, target_date):
                # cancel full treatment
                if dry_run:
                    summary['cancelled'].append(("FULL_TREATMENT", booking.pk, booking.patient_id))
                    logger.info("[DRY RUN] Would cancel full treatment for patient %s at slot %s", booking.patient_id, getattr(slot, 'id', slot))
                else:
                    try:
                        canceled_counts = cancel_full_treatment_for_patient_slot(booking.patient_id, target_date, slot, by_user=None, reason="therapist_unavailable")
                        summary['cancelled'].append(("FULL_TREATMENT", booking.pk, booking.patient_id, canceled_counts))
                        logger.info("Cancelled full treatment for patient %s: %s", booking.patient_id, canceled_counts)
                    except Exception as e:
                        logger.exception("Error cancelling full treatment for booking %s: %s", booking.pk, e)
                        summary['failed'].append((booking.pk, str(e)))
            else:
                # cancel just the single therapist booking
                if dry_run:
                    summary['cancelled'].append(("SINGLE", booking.pk, booking.patient_id))
                    logger.info("[DRY RUN] Would cancel single therapist booking %s", booking.pk)
                else:
                    try:
                        booking.cancel(by_user=None, reason="therapist_unavailable", cascade=True)
                        summary['cancelled'].append(("SINGLE", booking.pk, booking.patient_id))
                        logger.info("Cancelled therapist booking %s", booking.pk)
                    except Exception as e:
                        logger.exception("Error cancelling booking %s: %s", booking.pk, e)
                        summary['failed'].append((booking.pk, str(e)))
            continue

        # 4) pick candidate with daily-load & overtime rules + difficulty balancing
        pick = pick_least_loaded_candidate(
            candidates,
            target_date,
            max_daily_normal,
            max_daily_overtime_extra,
            therapy_category=therapy_category,
        )
        if not pick:
            # no pick due to load limits -> treat like no candidates
            if should_cancel_full_treatment(booking, target_date):
                if dry_run:
                    summary['cancelled'].append(("FULL_TREATMENT", booking.pk, booking.patient_id))
                    logger.info("[DRY RUN] Would cancel full treatment for patient %s at slot %s (no pick due to load limits)", booking.patient_id, getattr(slot, 'id', slot))
                else:
                    try:
                        canceled_counts = cancel_full_treatment_for_patient_slot(booking.patient_id, target_date, slot, by_user=None, reason="therapist_unavailable")
                        summary['cancelled'].append(("FULL_TREATMENT", booking.pk, booking.patient_id, canceled_counts))
                        logger.info("Cancelled full treatment for patient %s: %s", booking.patient_id, canceled_counts)
                    except Exception as e:
                        logger.exception("Error cancelling full treatment for booking %s: %s", booking.pk, e)
                        summary['failed'].append((booking.pk, str(e)))
            else:
                if dry_run:
                    summary['cancelled'].append(("SINGLE", booking.pk, booking.patient_id))
                    logger.info("[DRY RUN] Would cancel single therapist booking %s (no pick due to load limits)", booking.pk)
                else:
                    try:
                        booking.cancel(by_user=None, reason="therapist_unavailable", cascade=True)
                        summary['cancelled'].append(("SINGLE", booking.pk, booking.patient_id))
                        logger.info("Cancelled therapist booking %s (no pick due to load limits)", booking.pk)
                    except Exception as e:
                        logger.exception("Error cancelling booking %s: %s", booking.pk, e)
                        summary['failed'].append((booking.pk, str(e)))
            continue

        # 5) perform reassignment with special treatment handling
        # For special treatments (Dhara & Pizichil): Senior therapist should NOT be bathing therapist
        # Check if picked therapist is senior and needs to be bathing - find alternative if needed
        if requires_senior_tag and needs_bathing and pick:
            pick_grade = get_therapist_grade_name(pick)
            if pick_grade and 'Senior' in pick_grade:
                # Senior therapist cannot be bathing therapist - need to find alternative
                # Try to find non-senior bathing therapist first
                non_senior_bathing = [c for c in candidates if c != pick and getattr(c, 'is_bathing_therapist', False) and 'Senior' not in get_therapist_grade_name(c)]
                
                if non_senior_bathing:
                    # Use non-senior bathing therapist instead (respect difficulty balancing)
                    alt_pick = pick_least_loaded_candidate(
                        non_senior_bathing,
                        target_date,
                        max_daily_normal,
                        max_daily_overtime_extra,
                        therapy_category=therapy_category,
                    )
                    if alt_pick:
                        pick = alt_pick
                        logger.info("Special treatment: Using non-senior bathing therapist %s instead of senior", getattr(pick, 'therapist_code', pick.pk))
                    else:
                        logger.warning("Special treatment: Senior therapist %s cannot be bathing therapist, no non-senior alternative found", 
                                      getattr(pick, 'therapist_code', 'unknown'))
                        summary['failed'].append((booking.pk, "special_treatment_senior_cannot_be_bathing_no_alternative"))
                        continue
                else:
                    # No non-senior bathing therapist available - this is a problem
                    logger.warning("Special treatment: Senior therapist %s is only bathing option, but cannot be bathing therapist", 
                                  getattr(pick, 'therapist_code', 'unknown'))
                    summary['failed'].append((booking.pk, "special_treatment_senior_only_bathing_option"))
                    continue
        
        # Check room availability if therapy needs room
        if therapy_needs_room and therapy_needs_room(booking):
            try:
                from Patient.models import TreatmentRoom
                # Get room from booking or check if room is still available
                booking_room = getattr(booking, 'room', None)
                if not booking_room and hasattr(booking, 'visit') and booking.visit:
                    # Try to get room from related RoomBooking
                    try:
                        from Patient.models import RoomBooking
                        room_booking = RoomBooking.objects.filter(
                            patient_id=booking.patient_id,
                            date=target_date,
                            time_slot=slot,
                            status='BOOKED'
                        ).first()
                        if room_booking:
                            booking_room = room_booking.room
                    except Exception:
                        pass
                
                # If room exists, verify it's still available
                if booking_room:
                    room_conflict = RoomBooking.objects.filter(
                        room=booking_room,
                        date=target_date,
                        time_slot=slot,
                        status='BOOKED'
                    ).exclude(
                        patient_id=booking.patient_id
                    ).exists()
                    if room_conflict:
                        logger.warning("Room %s not available for reassignment", getattr(booking_room, 'room_no', 'unknown'))
                        summary['failed'].append((booking.pk, "room_not_available"))
                        continue
            except Exception as e:
                logger.debug("Error checking room availability: %s", e)
        
        # Perform reassignment
        dry_run_flag = getattr(args, 'dry_run', False) if hasattr(args, 'dry_run') else dry_run
        if dry_run_flag:
            summary['reassigned'].append((booking.pk, getattr(old, 'therapist_code', old.pk), getattr(pick, 'therapist_code', pick.pk)))
            logger.info("[DRY RUN] Would reassign booking %s -> therapist %s", booking.pk, getattr(pick, 'therapist_code', pick.pk))
        else:
            try:
                with transaction.atomic():
                    booking.therapist = pick
                    if hasattr(booking, 'is_bathing') and needs_bathing:
                        # For special treatments: ensure senior is NOT marked as bathing
                        if requires_senior_tag:
                            pick_grade = get_therapist_grade_name(pick)
                            if pick_grade and 'Senior' in pick_grade:
                                booking.is_bathing = False
                                logger.info("Special treatment: Senior therapist %s NOT marked as bathing", getattr(pick, 'therapist_code', pick.pk))
                            else:
                                booking.is_bathing = True
                        else:
                            booking.is_bathing = True
                    booking.save(update_fields=['therapist', 'updated_at'] + (['is_bathing'] if hasattr(booking, 'is_bathing') else []))
                summary['reassigned'].append((booking.pk, getattr(old, 'therapist_code', old.pk), getattr(pick, 'therapist_code', pick.pk)))
                logger.info("Reassigned booking %s -> therapist %s", booking.pk, getattr(pick, 'therapist_code', pick.pk))
            except Exception as e:
                logger.exception("Error reassigning booking %s: %s", booking.pk, e)
                summary['failed'].append((booking.pk, str(e)))

    return summary


# -------------------------
# CLI main
# -------------------------
def main():
    target_date = parse_target_date(args.date)
    logger.info("Running reassignment for date: %s (dry_run=%s)", target_date.isoformat(), args.dry_run)

    summary = process_reassignments(target_date=target_date, dry_run=args.dry_run, max_daily_normal=5, max_daily_overtime_extra=2)

    logger.info("Done. Summary: checked=%s reassigned=%s cancelled=%s failed=%s",
                summary.get('checked', 0), len(summary.get('reassigned', [])),
                len(summary.get('cancelled', [])), len(summary.get('failed', [])))
    if args.dry_run:
        logger.info("Dry-run mode - no DB changes were committed.")
    else:
        logger.info("Modifications were applied to the database (where replacements found).")

    # print details
    if summary.get('reassigned'):
        logger.info("Reassigned examples (up to 50):")
        for item in summary['reassigned'][:50]:
            logger.info(" - booking %s : %s -> %s", item[0], item[1], item[2])
    if summary.get('cancelled'):
        logger.info("Cancelled examples (up to 50):")
        for c in summary['cancelled'][:50]:
            logger.info(" - %s", c)

    return 0


if __name__ == "__main__":
    sys.exit(main())
