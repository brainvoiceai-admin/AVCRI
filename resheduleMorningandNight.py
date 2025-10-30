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
    Attempts to use booking.therapy (FK) or booking.therapy_name -> TherapyMaster.total_no_of_therapist.
    Falls back to 1 if unknown.
    """
    try:
        # if booking has therapy FK
        if hasattr(booking, "therapy") and booking.therapy:
            tm = booking.therapy
            return int(getattr(tm, "total_no_of_therapist", getattr(tm, "total", 1) or 1))
        # fallback: match by name
        name = getattr(booking, "therapy_name", None)
        if name and TherapyMaster:
            tm = TherapyMaster.objects.filter(therapy_name__iexact=name).first()
            if tm:
                return int(getattr(tm, "total_no_of_therapist", getattr(tm, "total", 1) or 1))
    except Exception:
        logger.exception("Error determining required therapist count for booking %s", getattr(booking, "pk", None))
    return 1


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
def available_candidates_by_level_and_bathing(target_date, time_slot, level, require_bathing, em_therapist_ids=None, em_emp_codes=None):
    """
    Return list of TherapistMaster candidates that:
      - have therapist_grade == level
      - optionally have is_bathing_therapist == True
      - are NOT on emergency leave (by FK or emp code)
      - do NOT have weekly leave on that weekday
      - NOT already BOOKED at date+slot
    """
    try:
        qs = TherapistMaster.objects.filter(therapist_grade=level)
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
        busy_ids = list(TherapistBooking.objects.filter(date=target_date, time_slot=time_slot, status='BOOKED').values_list('therapist__pk', flat_true:=False))
    except Exception:
        busy_ids = []
    # The above attempt with flat_true may raise; do robust approach:
    try:
        busy_ids = list(TherapistBooking.objects.filter(date=target_date, time_slot=time_slot, status='BOOKED').values_list('therapist__pk', flat=True))
        if busy_ids:
            qs = qs.exclude(pk__in=busy_ids)
    except Exception:
        logger.debug("Skipping slot-busy exclusion due to error.")

    return list(qs)


def find_previous_assigned_therapist_for_booking_patient_only(booking, needs_bathing, same_level, target_date, em_therapist_ids, em_emp_codes):
    """
    Preference: most recent previous therapist for the same patient (ignore therapy).
    Validate candidate against constraints (level, bathing, not on leave, not weekly leave, not already booked at slot).
    """
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
    if same_level and getattr(cand, 'therapist_grade', None) != getattr(booking.therapist, 'therapist_grade', None):
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


def pick_least_loaded_candidate(candidates, target_date, max_daily_normal, max_daily_overtime_extra):
    """
    From candidate TherapistMaster list, pick one based on daily load and overtime rules.
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

    under_normal = [pk for pk, cnt in counts.items() if cnt < max_daily_normal]
    if under_normal:
        pick_pk = sorted(under_normal, key=lambda p: (counts[p], p))[0]
        return next((c for c in candidates if c.pk == pick_pk), None)

    under_overtime = [pk for pk, cnt in counts.items() if cnt < (max_daily_normal + max_daily_overtime_extra)]
    if under_overtime:
        pick_pk = sorted(under_overtime, key=lambda p: (counts[p], p))[0]
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
        level = getattr(old, 'therapist_grade', None)
        slot = booking.time_slot
        needs_bathing = bool(getattr(booking, 'is_bathing', False))

        # 1) prefer previous therapist for same patient (not patient+therapy)
        prev = find_previous_assigned_therapist_for_booking_patient_only(booking, needs_bathing=needs_bathing,
                                                                         same_level=True, target_date=target_date,
                                                                         em_therapist_ids=em_therapist_ids, em_emp_codes=em_emp_codes)
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

        # 2) build candidate pool by level & bathing requirement
        candidates = available_candidates_by_level_and_bathing(target_date, slot, level, require_bathing=needs_bathing, em_therapist_ids=em_therapist_ids, em_emp_codes=em_emp_codes)

        # If booking doesn't require bathing and no bathing-only candidates, allow any same-level therapist
        if not candidates and not needs_bathing:
            candidates = available_candidates_by_level_and_bathing(target_date, slot, level, require_bathing=False, em_therapist_ids=em_therapist_ids, em_emp_codes=em_emp_codes)

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

        # 4) pick candidate with daily-load & overtime rules
        pick = pick_least_loaded_candidate(candidates, target_date, max_daily_normal, max_daily_overtime_extra)
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

        # 5) perform reassignment
        if args.dry_run:
            summary['reassigned'].append((booking.pk, getattr(old, 'therapist_code', old.pk), getattr(pick, 'therapist_code', pick.pk)))
            logger.info("[DRY RUN] Would reassign booking %s -> therapist %s", booking.pk, getattr(pick, 'therapist_code', pick.pk))
        else:
            try:
                with transaction.atomic():
                    booking.therapist = pick
                    if hasattr(booking, 'is_bathing') and needs_bathing:
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
