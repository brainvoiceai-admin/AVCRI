# allocation_logic.py
from datetime import datetime, timedelta
from types import SimpleNamespace
from django.db import transaction, IntegrityError
from django.db.models import Q

# Layer 1A Core Primitives (re-exported for backward compatibility)
from allocation_engine.core.primitives.exceptions import IncompleteAssignmentError
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
    is_treatment_requiring_senior_tag,
    get_senior_tag_count_for_therapist,
    is_dhara_pizhichil_treatment,
    get_dhara_pizhichil_assigned_room,
    is_steam_therapy_treatment,
    get_steam_therapy_rooms,
    is_vamanam_treatment,
    get_vamanam_slots,
    get_vamanam_treatment_rooms,
    allocate_vamanam_treatment_room,
    is_vasthi_treatment,
    get_vasthi_slots,
    allocate_vasthi_treatment_room,
    get_wheelchair_accessible_rooms,
    is_hard_treatment,
    get_slot_session,
    patient_has_hard_treatment_in_session,
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
from allocation_engine.core.primitives.slot_utils import map_to_canonical_slot
from allocation_engine.core.primitives.booking_persistence import (
    create_room_booking_safe as _core_create_room_booking_safe,
    create_therapist_booking_safe as _core_create_therapist_booking_safe,
)


def therapist_requirements(allocation_or_therapy_obj):
    # Preserve final_allocation behavior: missing TherapyMaster defaults to total=1
    return _core_therapist_requirements(allocation_or_therapy_obj, default_total_if_missing=1)


def create_room_booking_safe(room, date, time_slot, therapy_name, patient_id, visit):
    # Preserve final_allocation behavior: runs inside outer transaction.atomic() with refresh_from_db()
    return _core_create_room_booking_safe(
        room, date, time_slot, therapy_name, patient_id, visit,
        use_atomic=False, refresh=True,
    )


def create_therapist_booking_safe(therapist, date, time_slot, therapy_name, patient_id, visit, is_bathing=False):
    # Preserve final_allocation behavior: outer transaction, TherapyMaster FK resolution, refresh_from_db()
    return _core_create_therapist_booking_safe(
        therapist, date, time_slot, therapy_name, patient_id, visit,
        is_bathing=is_bathing, use_atomic=False, resolve_therapy_fk=True, refresh=True,
    )

# (get_treatment_rooms_for_staying_room, is_dhara_pizhichil_treatment,
#  get_dhara_pizhichil_assigned_room imported from allocation_engine above)


from allocation_engine.core.allocators.prioritization import get_patient_category_priority
from allocation_engine.core.allocators.room_allocator import (
    SCHEDULING_ROOM_CONFIG,
    allocate_treatment_room as _allocate_treatment_room_core,
)
from allocation_engine.core.allocators.slot_policy import (
    allocate_treatment_slot,
    get_allowed_slot_values,
)


def allocate_treatment_room(date, time_slot, last_room=None, therapy_name=None, patient_id=None, patient_staying_room=None, patient=None, is_wheelchair=False):
    """Backward-compatible scheduling shim delegating to allocation_engine.core.allocators.room_allocator."""
    return _allocate_treatment_room_core(
        date=date,
        time_slot=time_slot,
        last_room=last_room,
        therapy_name=therapy_name,
        patient_id=patient_id,
        patient_staying_room=patient_staying_room,
        patient=patient,
        is_wheelchair=is_wheelchair,
        config=SCHEDULING_ROOM_CONFIG,
    )

# -----------------------
# Shift eligibility helpers (Layer 1A)
# -----------------------
from allocation_engine.core.primitives.shift_utils import (
    _shift_enforcement_enabled,
    _shift_eligibility_sets_for_slot,
)

# -----------------------
# Therapist allocation with EmergencyLeave integration
# -----------------------
from allocation_engine.core.allocators.therapist_allocator import (
    SCHEDULING_THERAPIST_CONFIG,
    allocate_therapists as _allocate_therapists_core,
)


def allocate_therapists(
    date,
    time_slot,
    therapy_requirements,
    last_therapists=None,
    needs_bathing=False,
    patient_gender=None,
    avoid_therapists=None,
    patient_id=None,
    allow_helping_fallback=False,
    patient_age=None,
):
    """Backward-compatible scheduling shim delegating to allocation_engine.core.allocators.therapist_allocator."""
    return _allocate_therapists_core(
        date=date,
        time_slot=time_slot,
        therapy_requirements=therapy_requirements,
        last_therapists=last_therapists,
        needs_bathing=needs_bathing,
        patient_gender=patient_gender,
        avoid_therapists=avoid_therapists,
        patient_id=patient_id,
        allow_helping_fallback=allow_helping_fallback,
        patient_age=patient_age,
        config=SCHEDULING_THERAPIST_CONFIG,
    )

# -----------------------
# PASS 1: Continuity Priority Pass - Assign previous-day therapists only and lock them
# -----------------------
from allocation_engine.core.allocators.continuity_pass1 import (
    SCHEDULING_PASS1_CONFIG,
    assign_continuity_therapists_pass1 as _assign_continuity_pass1_core,
)


def assign_continuity_therapists_pass1(booking, allocation, target_date, locked_therapist_slots):
    """Backward-compatible scheduling shim delegating to allocation_engine.core.allocators.continuity_pass1."""
    return _assign_continuity_pass1_core(
        booking=booking,
        allocation=allocation,
        target_date=target_date,
        locked_therapist_slots=locked_therapist_slots,
        create_bookings=True,
        config=SCHEDULING_PASS1_CONFIG,
    )

# -----------------------
# -----------------------
# Layer 3A Scheduling Orchestrators (re-exported for backward compatibility)
# -----------------------
from allocation_engine.scheduling.continuity_plan import build_continuity_plan_for_date
from allocation_engine.scheduling.visit_allocator import expand_therapies_for_visit
from allocation_engine.scheduling.bulk_allocator import bulk_allocate_for_date


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