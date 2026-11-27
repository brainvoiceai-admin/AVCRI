"""
Shared slot policy & allowed-slot resolution (Layer 1B).

Consolidates `get_allowed_slot_values` and `allocate_treatment_slot`,
eliminating the legacy `final_allocation.py -> reshedule.py` dependency.
"""

from allocation_engine.core.primitives.slot_utils import _slot_time_value
from allocation_engine.rules.hard_treatment import (
    get_slot_session,
    is_hard_treatment,
    patient_has_hard_treatment_in_session,
)
from allocation_engine.rules.vamanam import get_vamanam_slots, is_vamanam_treatment
from allocation_engine.rules.vasthi import is_group_vasthi_0830_only


def get_allowed_slot_values(
    patient_type,
    therapy_category,
    used_slots=None,
    therapy_name=None,
    therapy_code=None,
    patient_id=None,
    target_date=None,
    exclude_booking_id=None,
    exclude_allocation_id=None,
):
    """
    Return ordered list of allowed slot strings "HH:MM" for this patient_type and therapy_category.
    Excludes any used_slots provided (list of slot model instances).

    Args:
        patient_type: Patient type (OP/IP)
        therapy_category: Therapy category (easy/medium/hard/special)
        used_slots: List of slot model instances that are already used
        therapy_name: Name of the therapy (for treatment-specific restrictions)
        therapy_code: Therapy code (master lookup + THEB037 exemption)
        patient_id: Optional patient ID or snapshot for session hard-treatment checks
        target_date: Optional target date for session hard-treatment checks
        exclude_booking_id: Optional booking ID to exclude from session conflict checks
        exclude_allocation_id: Optional allocation ID to exclude from session conflict checks
    """
    # VAMANAM SPECIAL RULE: Vamanam therapies ONLY use designated Vamanam slots (e.g. 05:00, 05:30)
    if is_vamanam_treatment(therapy_name, therapy_code):
        allowed_slots = get_vamanam_slots()
        if used_slots:
            used_slot_strs = []
            for s in used_slots:
                t = _slot_time_value(s)
                if t:
                    try:
                        used_slot_strs.append(t.strftime("%H:%M"))
                    except Exception:
                        pass
            allowed_slots = [s for s in allowed_slots if s not in used_slot_strs]
        print(f"[SLOT RESTRICTION] Vamanam therapy detected - allowed slots: {allowed_slots}")
        return allowed_slots

    general_slots = ["06:30", "08:30", "10:00", "11:30", "14:30", "16:00", "17:30"]

    # default allowed by patient type
    if patient_type and str(patient_type).upper() == "OP":
        allowed_slots = ["11:30", "17:30"]
    elif patient_type and str(patient_type).upper() == "IP":
        allowed_slots = ["06:30", "08:30", "10:00", "14:30", "16:00"]
    else:
        allowed_slots = general_slots

    # Exclude early-morning dedicated slots (like 05:00, 05:30) from regular therapy allocations.
    # Note: 06:30 AM is a standard treatment slot and is NOT excluded from regular treatments.
    try:
        early_slots = set(s for s in get_vamanam_slots() if s in ['05:00', '05:30'])
        if early_slots:
            allowed_slots = [s for s in allowed_slots if s not in early_slots]
    except Exception:
        pass

    # If therapy category requires excluding OP-only slots for 'hard'/'special'
    if therapy_category and str(therapy_category).lower() in ["hard", "special"]:
        allowed_slots = [s for s in general_slots if s not in ["11:30", "17:30"]]

    # NEW: allow IP 'easy'/'medium' therapies to use OP slots (11:30/17:30)
    try:
        if patient_type and str(patient_type).upper() == "IP":
            if therapy_category and str(therapy_category).lower() in ["easy", "medium"]:
                # merge OP slots, keeping order: keep IP slots then append OP preferreds if missing
                for op_slot in ["11:30", "17:30"]:
                    if op_slot not in allowed_slots:
                        allowed_slots.append(op_slot)
    except Exception:
        # fail-safe: ignore errors in category check
        pass

    # RESTRICTION: Lepam treatment should not be assigned to 6.30 slot
    if therapy_name:
        therapy_name_lower = str(therapy_name).strip().lower()
        if 'lepam' in therapy_name_lower:
            # Remove 06:30 from allowed slots for Lepam
            allowed_slots = [s for s in allowed_slots if s != "06:30"]
            print(f"[SLOT RESTRICTION] Lepam treatment detected - excluding 06:30 slot. Allowed slots: {allowed_slots}")

    # Vasthi therapy group (masters.TherapyGroup name 'Vasthi'), except THEB037: only 08:30
    if is_group_vasthi_0830_only(therapy_name, therapy_code):
        allowed_slots = [s for s in allowed_slots if s == "08:30"]
        if not allowed_slots:
            allowed_slots = ["08:30"]
        print(f"[SLOT RESTRICTION] Vasthi therapy group -- only 08:30 allowed. Slots: {allowed_slots}")

    # HARD TREATMENT RESTRICTION: Two hard treatments should not be scheduled in the same session
    # Exception: Medium and Easy treatments (e.g. Lepam) can be assigned in the same session
    if is_hard_treatment(therapy_name=therapy_name, therapy_code=therapy_code, category=therapy_category):
        if patient_id and target_date:
            has_morning_hard = patient_has_hard_treatment_in_session(
                patient_id,
                target_date,
                'morning',
                exclude_booking_id=exclude_booking_id,
                exclude_allocation_id=exclude_allocation_id,
            )
            has_evening_hard = patient_has_hard_treatment_in_session(
                patient_id,
                target_date,
                'evening',
                exclude_booking_id=exclude_booking_id,
                exclude_allocation_id=exclude_allocation_id,
            )
            if has_morning_hard:
                allowed_slots = [s for s in allowed_slots if get_slot_session(s) != 'morning']
                print(
                    f"[SLOT RESTRICTION] Patient {patient_id} already has a hard treatment in morning session on {target_date} - excluding morning slots. Remaining: {allowed_slots}"
                )
            if has_evening_hard:
                allowed_slots = [s for s in allowed_slots if get_slot_session(s) != 'evening']
                print(
                    f"[SLOT RESTRICTION] Patient {patient_id} already has a hard treatment in evening session on {target_date} - excluding evening slots. Remaining: {allowed_slots}"
                )

    # remove any used slots (used_slots is list of slot model instances; use slot_time for SlotMaster)
    if used_slots:
        used_slot_strs = []
        for s in used_slots:
            t = _slot_time_value(s)
            if t:
                try:
                    used_slot_strs.append(t.strftime("%H:%M"))
                except Exception:
                    pass
        allowed_slots = [s for s in allowed_slots if s not in used_slot_strs]

    return allowed_slots


def allocate_treatment_slot(
    patient_type,
    therapy_category,
    used_slots=None,
    patient_id=None,
    target_date=None,
    therapy_name=None,
    therapy_code=None,
):
    """Return the first allowed slot string for the given criteria, or None."""
    allowed_slots = get_allowed_slot_values(
        patient_type=patient_type,
        therapy_category=therapy_category,
        used_slots=used_slots,
        therapy_name=therapy_name,
        therapy_code=therapy_code,
        patient_id=patient_id,
        target_date=target_date,
    )
    return allowed_slots[0] if allowed_slots else None
