# allocation_logic.py
from datetime import datetime, timedelta
from types import SimpleNamespace
from django.db import transaction, IntegrityError
from django.db.models import Q

# Layer 1A Core Primitives (re-exported for backward compatibility)
from allocation_engine.core.primitives.date_utils import daterange
from allocation_engine.core.primitives.patient_utils import (
    is_patient_active,
    parse_patient_age,
    resolve_desired_gender,
)

# -----------------------
# Layer 2 Therapy-Specific Rules & Layer 1A Room Mapping (re-exported for backward compatibility)
# -----------------------
from allocation_engine.core.primitives.room_utils import get_treatment_rooms_for_staying_room
from allocation_engine.rules import (
    is_steam_therapy_treatment,
    is_steam_therapy_530_tr12_only,
    get_steam_therapy_rooms,
    VAMANAM_THERAPY_CODE,
    is_vamanam_treatment,
    get_vamanam_slots,
    get_vamanam_timings,
    get_vamanam_rooms_by_tier,
    get_vamanam_treatment_rooms,
    get_primary_vamanam_treatment_rooms,
    get_secondary_vamanam_treatment_rooms,
    allocate_vamanam_treatment_room,
    GROUP_VASTHI_MATHRA_THERAPY_CODE,
    VASTHI_THERAPY_GROUP_NAME_NORMALIZED,
    is_vasthi_treatment,
    is_group_vasthi_0830_only,
    get_vasthi_slots,
    get_vasthi_slot_names,
    allocate_vasthi_treatment_room,
    is_dhara_pizhichil_treatment,
    get_dhara_pizhichil_assigned_room,
    get_wheelchair_accessible_rooms,
    is_hard_treatment,
    get_slot_session,
    patient_has_hard_treatment_in_session,
    is_treatment_requiring_senior_tag,
    get_senior_tag_count_for_therapist,
)

# -----------------------
# Therapy master catalog, slot canonicalization & safe booking persistence (Layer 1A)
# -----------------------
from allocation_engine.core.primitives.therapy_catalog import (
    therapy_cache,
    clear_therapy_cache,
    get_therapy_details,
    therapy_needs_room,
    therapy_needs_bath,
    get_therapist_grade_name,
    therapist_requirements as _core_therapist_requirements,
)
from allocation_engine.core.primitives.slot_utils import (
    map_to_canonical_slot,
    _slot_time_value,
)
from allocation_engine.core.primitives.booking_persistence import (
    create_room_booking_safe as _core_create_room_booking_safe,
    create_therapist_booking_safe as _core_create_therapist_booking_safe,
)


def therapist_requirements(allocation_or_therapy_obj):
    # Missing TherapyMaster defaults to total=1 (consistent with scheduling)
    return _core_therapist_requirements(allocation_or_therapy_obj, default_total_if_missing=1)


def create_room_booking_safe(room, date, time_slot, therapy_name, patient_id, visit):
    # Preserve reshedule.py behavior: atomic wrapper with update_fields
    return _core_create_room_booking_safe(
        room, date, time_slot, therapy_name, patient_id, visit,
        use_atomic=True, refresh=False,
    )


def create_therapist_booking_safe(therapist, date, time_slot, therapy_name, patient_id, visit, is_bathing=False):
    # Rescheduling wrapper: atomic with TherapyMaster FK resolution and update_fields
    return _core_create_therapist_booking_safe(
        therapist, date, time_slot, therapy_name, patient_id, visit,
        is_bathing=is_bathing, use_atomic=True, resolve_therapy_fk=True, refresh=False,
    )

# (get_treatment_rooms_for_staying_room & get_wheelchair_accessible_rooms imported from allocation_engine above)


from allocation_engine.core.allocators.room_allocator import (
    RESCHEDULING_ROOM_CONFIG,
    allocate_treatment_room as _allocate_treatment_room_core,
)
from allocation_engine.core.allocators.slot_policy import get_allowed_slot_values


def allocate_treatment_room(date, time_slot, last_room=None, therapy_name=None, patient_id=None, patient_staying_room=None, patient=None, booking_id=None, is_wheelchair=False):
    """Backward-compatible rescheduling shim delegating to allocation_engine.core.allocators.room_allocator."""
    return _allocate_treatment_room_core(
        date=date,
        time_slot=time_slot,
        last_room=last_room,
        therapy_name=therapy_name,
        patient_id=patient_id,
        patient_staying_room=patient_staying_room,
        patient=patient,
        booking_id=booking_id,
        is_wheelchair=is_wheelchair,
        config=RESCHEDULING_ROOM_CONFIG,
    )

# -----------------------
# Therapist allocation with Trainee -> Junior substitution (MODIFIED)
# -----------------------
from allocation_engine.core.allocators.therapist_allocator import (
    RESCHEDULING_THERAPIST_CONFIG,
    allocate_therapists as _allocate_therapists_core,
    allocate_therapists_with_grade_substitution as _allocate_therapists_grade_sub_core,
    make_readonly_therapist_config,
)


def allocate_therapists(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False, patient_gender=None, patient_id=None, allow_helping_fallback=False, patient_age=None, *, create_bookings=True):
    """Backward-compatible rescheduling shim delegating to allocation_engine.core.allocators.therapist_allocator."""
    cfg = RESCHEDULING_THERAPIST_CONFIG if create_bookings else make_readonly_therapist_config(RESCHEDULING_THERAPIST_CONFIG)
    return _allocate_therapists_core(
        date=date,
        time_slot=time_slot,
        therapy_requirements=therapy_requirements,
        last_therapists=last_therapists,
        needs_bathing=needs_bathing,
        patient_gender=patient_gender,
        patient_id=patient_id,
        allow_helping_fallback=allow_helping_fallback,
        patient_age=patient_age,
        config=cfg,
    )


def allocate_therapists_with_grade_substitution(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False, patient_gender=None, allow_helping_fallback=False, patient_age=None, patient_id=None, *, create_audit_logs=True):
    """Backward-compatible rescheduling shim delegating to allocation_engine.core.allocators.therapist_allocator."""
    return _allocate_therapists_grade_sub_core(
        date=date,
        time_slot=time_slot,
        therapy_requirements=therapy_requirements,
        last_therapists=last_therapists,
        needs_bathing=needs_bathing,
        patient_gender=patient_gender,
        allow_helping_fallback=allow_helping_fallback,
        patient_age=patient_age,
        patient_id=patient_id,
        create_audit_logs=create_audit_logs,
    )


# PASS 1: Continuity Priority Pass
# -----------------------
from allocation_engine.core.allocators.continuity_pass1 import (
    RESCHEDULING_PASS1_CONFIG,
    assign_continuity_therapists_pass1 as _assign_continuity_pass1_core,
)


def assign_continuity_therapists_pass1(booking, allocation, target_date, locked_therapist_slots, create_bookings=True):
    """Backward-compatible rescheduling shim delegating to allocation_engine.core.allocators.continuity_pass1."""
    return _assign_continuity_pass1_core(
        booking=booking,
        allocation=allocation,
        target_date=target_date,
        locked_therapist_slots=locked_therapist_slots,
        create_bookings=create_bookings,
        config=RESCHEDULING_PASS1_CONFIG,
    )


# -----------------------
# Layer 3B Rescheduling Orchestrators (re-exported for backward compatibility)
# -----------------------
from allocation_engine.rescheduling.slot_attempter import attempt_allocate_slot
from allocation_engine.rescheduling.visit_rescheduler import (
    expand_therapies_for_visit,
    allocate_therapy_for_visit,
)
from allocation_engine.rescheduling.options_preview import (
    preview_continuity_for_booking,
    preview_slot_reschedule,
    compute_reschedule_options_preview,
)

# -----------------------
# CLI quick-run
# -----------------------
if __name__ == "__main__":
    allocation_id = input("TherapyAllocation id: ").strip()
    date_str = input("Date (YYYY-MM-DD): ").strip()
    try:
        res = expand_therapies_for_visit(int(allocation_id), date_str, create_bookings=True)
        print(res)
    except Exception as e:
        print("Error:", e)