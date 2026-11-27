"""
Read-only Reschedule Options Preview Service (Layer 3B).

Provides strictly read-only preview helpers for evaluating candidate reschedule
slots and helping-therapist options without performing any database mutations.

Must NEVER import `allocation_engine.scheduling`, `final_allocation`, `reshedule`,
or `resheduleMorningandNight`.
"""

from allocation_engine.core.allocators.continuity_pass1 import (
    RESCHEDULING_PASS1_CONFIG,
    assign_continuity_therapists_pass1,
)
from allocation_engine.core.allocators.slot_policy import get_allowed_slot_values
from allocation_engine.core.primitives.slot_utils import map_to_canonical_slot
from allocation_engine.core.primitives.therapy_catalog import (
    therapist_requirements as _core_therapist_requirements,
    therapy_needs_bath,
    therapy_needs_room,
)
from allocation_engine.rescheduling.slot_attempter import attempt_allocate_slot


def preview_continuity_for_booking(booking, allocation, target_date):
    """
    Run Pass-1 continuity evaluation in strictly read-only mode (`create_bookings=False`).
    Returns `(continuity_codes, pass1_result)`.
    """
    p1_res = assign_continuity_therapists_pass1(
        booking=booking,
        allocation=allocation,
        target_date=target_date,
        locked_therapist_slots={},
        create_bookings=False,
        config=RESCHEDULING_PASS1_CONFIG,
    )
    if p1_res and p1_res.get('success'):
        assigned = p1_res.get('assigned_therapists', [])
        codes = [getattr(t, 'therapist_code', None) for t in assigned if getattr(t, 'therapist_code', None)]
        return codes, p1_res
    return [], p1_res


def preview_slot_reschedule(
    allocation,
    booking,
    target_date,
    canonical_slot,
    *,
    therapy_req=None,
    needs_room_flag=None,
    needs_bath_flag=None,
    last_allocation=None,
    allow_helping_fallback=False,
):
    """
    Evaluate whether `canonical_slot` can be allocated for `(allocation, booking, target_date)`
    in strictly read-only mode (`create_bookings=False`, `AllocationAttempt=None`).
    Returns `(task_dict, success_bool, reason_if_failed)`.
    """
    if therapy_req is None:
        therapy_req = _core_therapist_requirements(allocation, default_total_if_missing=0)
    if needs_room_flag is None:
        needs_room_flag = therapy_needs_room(allocation)
    if needs_bath_flag is None:
        needs_bath_flag = therapy_needs_bath(allocation)
    patient_id = getattr(getattr(allocation, 'patient', None), 'id', None)

    return attempt_allocate_slot(
        allocation=allocation,
        booking=booking,
        date=target_date,
        canonical_slot=canonical_slot,
        therapy_req=therapy_req,
        needs_room_flag=needs_room_flag,
        needs_bath_flag=needs_bath_flag,
        used_slots=[],
        create_bookings=False,
        patient_id=patient_id,
        last_allocation=last_allocation or {'therapists': []},
        AllocationAttempt=None,
        allow_helping_fallback=allow_helping_fallback,
    )


def compute_reschedule_options_preview(allocation, booking, target_date):
    """
    Compute read-only reschedule slot previews for an allocation/booking on `target_date`.
    Returns a dict with `allowed_slots`, `registered_slot`, `registered_with_helping`,
    and `available_slots` without writing to the database.
    """
    from datetime import datetime
    from masters.models import SlotMaster

    patient = getattr(allocation, 'patient', None)
    patient_id = getattr(patient, 'id', None)
    patient_type = "OP" if (patient and hasattr(patient, 'is_op') and patient.is_op()) else "IP"
    therapy_req = _core_therapist_requirements(allocation, default_total_if_missing=0)
    needs_room_flag = therapy_needs_room(allocation)
    needs_bath_flag = therapy_needs_bath(allocation)

    allowed_slot_values = get_allowed_slot_values(
        patient_type=patient_type,
        therapy_category=therapy_req.get("therapy_category"),
        used_slots=[],
        therapy_name=getattr(allocation, 'therapy_name', None),
        therapy_code=getattr(allocation, 'therapy_code', None),
        patient_id=patient_id,
        target_date=target_date,
        exclude_allocation_id=getattr(allocation, 'id', None),
        exclude_booking_id=getattr(booking, 'id', None) if booking else None,
    )

    continuity_codes, p1_res = preview_continuity_for_booking(booking, allocation, target_date)
    registered_context = {
        'therapists': continuity_codes,
        'continuity_assigned': p1_res if (p1_res and p1_res.get('success')) else {},
    }
    general_context = {'therapists': continuity_codes}

    reg_slot = getattr(booking, 'timeslot', None) or getattr(allocation, 'timeslot', None)
    canonical_reg_slot = map_to_canonical_slot(reg_slot) if reg_slot else None

    registered_with_helping = None
    if canonical_reg_slot:
        task, ok, reason = preview_slot_reschedule(
            allocation,
            booking,
            target_date,
            canonical_reg_slot,
            therapy_req=therapy_req,
            needs_room_flag=needs_room_flag,
            needs_bath_flag=needs_bath_flag,
            last_allocation=registered_context,
            allow_helping_fallback=True,
        )
        registered_with_helping = {'available': ok, 'task': task, 'reason': reason}

    available_slots = []
    for slot_val in allowed_slot_values:
        try:
            t_obj = datetime.strptime(slot_val, "%H:%M").time()
            cand_slot = SlotMaster.objects.filter(slot_time=t_obj, is_active=True).first()
            if not cand_slot:
                continue
            is_reg = canonical_reg_slot is not None and cand_slot.id == canonical_reg_slot.id
            task, ok, reason = preview_slot_reschedule(
                allocation,
                booking,
                target_date,
                cand_slot,
                therapy_req=therapy_req,
                needs_room_flag=needs_room_flag,
                needs_bath_flag=needs_bath_flag,
                last_allocation=registered_context if is_reg else general_context,
                allow_helping_fallback=False,
            )
            if ok:
                available_slots.append({'slot_id': cand_slot.id, 'slot_value': slot_val, 'task': task})
        except Exception:
            continue

    return {
        'allowed_slots': allowed_slot_values,
        'registered_slot_id': getattr(canonical_reg_slot, 'id', None),
        'registered_with_helping': registered_with_helping,
        'available_slots': available_slots,
    }
