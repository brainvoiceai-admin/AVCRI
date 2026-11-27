#!/usr/bin/env python3
"""
Backward-compatible facade and CLI entry point for emergency-leave therapist reassignment.

Core implementation lives in `allocation_engine.rescheduling.leave_reassignment`.
"""

import argparse
import logging
import os
import sys

DEFAULT_DJANGO_SETTINGS = "AVCRI.settings"

parser = argparse.ArgumentParser(description="Reassign therapist bookings when therapist is on emergency leave.")
parser.add_argument("--dry-run", action="store_true", help="Do not commit changes; show what would happen.")
parser.add_argument("--date", type=str, default=None, help="Date to run for (YYYY-MM-DD). Defaults to today (server local timezone).")
parser.add_argument("--settings", type=str, default=None, help="Optional DJANGO_SETTINGS_MODULE to use.")
args, _unknown_args = parser.parse_known_args()

if args.settings:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", args.settings)
else:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE", DEFAULT_DJANGO_SETTINGS))

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

try:
    import django
    if not django.apps.apps.ready:
        django.setup()
except Exception as e:
    logger.exception("Failed to setup Django: %s", e)
    sys.exit(1)

from allocation_engine.rescheduling.leave_reassignment import (
    TherapistBooking,
    EmergencyLeave,
    TherapistMaster,
    TherapistLeaveMaster,
    TherapyMaster,
    RoomBooking,
    is_treatment_requiring_senior_tag,
    get_therapy_details,
    therapy_needs_room,
    therapy_needs_bath,
    get_therapist_grade_name,
    therapist_requirements,
    parse_target_date,
    get_emergency_leave_sets_for_date,
    sync_booking_assignment_after_reassign,
    therapist_has_weekly_leave_on,
    get_required_therapist_count_for_booking,
    get_patient_gender_from_booking,
    get_patient_age_from_booking,
    normalize_patient_gender,
    get_therapist_gender,
    patient_already_has_booking,
    count_assigned_therapists_for_patient_slot,
    should_cancel_full_treatment,
    cancel_full_treatment_for_patient_slot,
    available_candidates_by_level_and_bathing,
    expand_candidates_with_grade_substitution,
    _get_therapist_continuity_plan_model,
    get_continuity_therapists_from_plan,
    find_bathing_therapist_from_start_of_therapy,
    find_previous_therapist_from_start_of_therapy,
    find_previous_bathing_therapist_for_patient,
    find_previous_assigned_therapist_for_booking_patient_only,
    pick_least_loaded_candidate,
    process_reassignments,
)


def main():
    target_date = parse_target_date(args.date)
    dry_run = bool(args.dry_run)
    logger.info("Running emergency leave reassignment for %s (dry_run=%s)", target_date, dry_run)
    summary = process_reassignments(target_date=target_date, dry_run=dry_run)
    logger.info("Summary: %s", summary)


if __name__ == "__main__":
    main()
