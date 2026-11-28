"""
Rescheduling Visit Orchestrator (Layer 3B).

Hosts the rescheduling `expand_therapies_for_visit` and `allocate_therapy_for_visit`.
Must remain separate from `allocation_engine.scheduling.visit_allocator.expand_therapies_for_visit`.
Must NEVER import `allocation_engine.scheduling`, `final_allocation`,
`reshedule`, or `resheduleMorningandNight`.
"""

import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from django.db import transaction, IntegrityError
from django.db.models import Q

from allocation_engine.core.primitives.date_utils import daterange
from allocation_engine.core.primitives.patient_utils import (
    is_patient_active as _canonical_is_patient_active,
    parse_patient_age,
    resolve_desired_gender,
)
from allocation_engine.core.primitives.slot_utils import (
    map_to_canonical_slot,
    _slot_time_value,
)
from allocation_engine.core.primitives.therapy_catalog import (
    therapy_needs_room,
    therapy_needs_bath,
    therapist_requirements as _core_therapist_requirements,
)
from allocation_engine.rules import (
    is_vamanam_treatment,
    get_vamanam_slots,
    is_vasthi_treatment,
    is_group_vasthi_0830_only,
    is_hard_treatment,
    get_slot_session,
    patient_has_hard_treatment_in_session,
)
from allocation_engine.core.allocators.slot_policy import get_allowed_slot_values
from allocation_engine.core.allocators.continuity_pass1 import (
    RESCHEDULING_PASS1_CONFIG,
    assign_continuity_therapists_pass1 as _assign_continuity_pass1_core,
)
from allocation_engine.rescheduling.slot_attempter import attempt_allocate_slot


def is_patient_active(patient):
    """Call canonical is_patient_active while honoring legacy facade mock patches in tests."""
    legacy_mod = sys.modules.get("reshedule")
    if legacy_mod is not None:
        patched = getattr(legacy_mod, "is_patient_active", None)
        if patched is not None and patched is not _canonical_is_patient_active:
            return patched(patient)
    return _canonical_is_patient_active(patient)


def therapist_requirements(allocation_or_therapy_obj):
    return _core_therapist_requirements(allocation_or_therapy_obj, default_total_if_missing=1)


def assign_continuity_therapists_pass1(booking, allocation, target_date, locked_therapist_slots, create_bookings=True):
    return _assign_continuity_pass1_core(
        booking=booking,
        allocation=allocation,
        target_date=target_date,
        locked_therapist_slots=locked_therapist_slots,
        create_bookings=create_bookings,
        config=RESCHEDULING_PASS1_CONFIG,
    )


def expand_therapies_for_visit(therapy_allocation_id, target_date, create_bookings=True, booking_continuity_map=None, allow_helping_fallback=False, force_slot_only=False):
    """
    Preferred-slot-first allocation using Booking rows.
    If preferred slot fails due to capacity/conflicts, attempts automatic slot allocation
    (OP/IP-aware) to reschedule that booking on the same date (unless force_slot_only is True).

    Returns list of task dicts. Each task['therapists'] is a list of dicts:
      {"therapist_code": "...", "is_bathing": True|False}
    """
    # normalize date
    if isinstance(target_date, str):
        try:
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except Exception:
            return {"error": f"Invalid date format: {target_date}. Use YYYY-MM-DD."}

    # Defensive imports
    from Sheduling.models import TherapyAllocation, Booking
    from Patient.models import TherapistBooking, RoomBooking, AllocationAttempt
    from masters.models import SlotMaster

    allocation = TherapyAllocation.objects.filter(pk=therapy_allocation_id).first()
    if not allocation:
        return {"error": f"TherapyAllocation id {therapy_allocation_id} not found."}

    # ----- INACTIVE PATIENT CHECK -----
    # If the patient is inactive, mark all bookings for this date as failed
    # and skip rescheduling entirely.
    patient_snapshot = getattr(allocation, 'patient', None)
    pat_reg_no = getattr(patient_snapshot, 'pat_reg_no', None) if patient_snapshot else None
    if pat_reg_no and not is_patient_active(pat_reg_no):
        print(f"[PATIENT STATUS] Skipping rescheduling for inactive patient {pat_reg_no} "
              f"(allocation {therapy_allocation_id}, date {target_date})")
        # Mark all bookings for this allocation+date as failed
        inactive_bookings = Booking.objects.filter(
            allocation_id=therapy_allocation_id,
            date=target_date,
        ).exclude(status='failed')
        tasks = []
        for booking in inactive_bookings:
            booking.status = 'failed'
            booking.failure_reason = 'Patient Inactive'
            booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
            tasks.append({
                "booking_id": booking.pk,
                "allocation_id": therapy_allocation_id,
                "date": target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date),
                "therapy_name": allocation.therapy_name,
                "slot": None,
                "status": "FAILED",
                "reason": "Patient Inactive",
                "room_no": None,
                "therapists": []
            })
        if not tasks:
            tasks.append({
                "booking_id": None,
                "allocation_id": therapy_allocation_id,
                "date": target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date),
                "therapy_name": allocation.therapy_name,
                "slot": None,
                "status": "FAILED",
                "reason": "Patient Inactive",
                "room_no": None,
                "therapists": []
            })
        return tasks

    bookings_qs = Booking.objects.filter(allocation_id=therapy_allocation_id, date=target_date)
    if not bookings_qs.exists():
        return {"error": f"No Booking rows found for allocation {therapy_allocation_id} on {target_date.isoformat()}."}

    # CLEAR EXISTING ASSIGNMENTS/BOOKINGS for this allocation/date BEFORE starting algorithm.
    # This prevents accumulation of therapists (ghost records) when rescheduling.
    if create_bookings:
        try:
            from django.db.models import Q
            # 1. Cancel existing TherapistBooking records linked to this allocation/date safely
            existing_tbs = list(TherapistBooking.objects.filter(
                visit=allocation,
                date=target_date,
                status='BOOKED'
            ))
            for tb in existing_tbs:
                TherapistBooking.objects.filter(
                    therapist=tb.therapist,
                    date=tb.date,
                    time_slot=tb.time_slot,
                    status='CANCELED'
                ).delete()
                tb.status = 'CANCELED'
                tb.save(update_fields=['status'])

            # 2. Cancel existing RoomBooking records linked to this allocation/date safely
            existing_rbs = list(RoomBooking.objects.filter(
                date=target_date,
                status='BOOKED'
            ).filter(
                Q(therapy=allocation) | Q(visit__allocation=allocation)
            ))
            for rb in existing_rbs:
                RoomBooking.objects.filter(
                    room=rb.room,
                    date=rb.date,
                    time_slot=rb.time_slot,
                    status='CANCELED'
                ).delete()
                rb.status = 'CANCELED'
                rb.save(update_fields=['status'])

            # 3. Delete existing UI assignments for these bookings
            from Sheduling.models import BookingAssignment
            BookingAssignment.objects.filter(booking__in=bookings_qs).delete()
            
            print(f"[RESCHEDULE] [CLEAN] Cleared existing bookings/assignments for allocation {therapy_allocation_id} on {target_date} to prevent ghost therapists")
        except Exception as cleanup_e:
            print(f"[RESCHEDULE] [WARN] Cleanup error (non-fatal): {cleanup_e}")

    tasks = []
    used_slots = []
    any_success = False
    patient_id = getattr(allocation.patient, 'id', None)

    # determine patient type (OP/IP) from allocation.patient if possible
    patient_type = None
    try:
        p = getattr(allocation, 'patient', None)
        if p:
            if hasattr(p, 'is_op'):
                patient_type = "OP" if p.is_op() else "IP"
    except Exception:
        patient_type = None

    def therapist_entry(t_obj, is_bath=False):
        return {"therapist_code": getattr(t_obj, 'therapist_code', None) or str(t_obj), "is_bathing": bool(is_bath)}

    # PASS 1: If no continuity map provided, run continuity pass so bathing and first-day therapists are assigned (same as final_allocation).
    # Without this, reschedule would never get first-day continuity because callers do not build the plan or run PASS 1.
    if booking_continuity_map is None or not booking_continuity_map:
        booking_continuity_map = {}
        locked_therapist_slots = set()
        bookings_list = list(bookings_qs.select_related('allocation', 'timeslot', 'allocation__patient').order_by('timeslot_id', 'pk'))
        for booking in bookings_list:
            alloc = booking.allocation
            if not alloc:
                continue
            try:
                from Sheduling.nurse_allocation import is_nurse_treatment
                if is_nurse_treatment(getattr(alloc, 'therapy_code', None), getattr(alloc, 'therapy_name', None)):
                    booking_continuity_map[booking.pk] = None
                    continue
            except Exception:
                pass
            therapy_req = therapist_requirements(alloc)
            if therapy_req.get('total', 1) == 0:
                booking_continuity_map[booking.pk] = None
                continue
            try:
                continuity_result = assign_continuity_therapists_pass1(booking, alloc, target_date, locked_therapist_slots)
                if continuity_result.get('success'):
                    booking_continuity_map[booking.pk] = continuity_result
                    print(f"[RESCHEDULE PASS1] Built continuity for booking {booking.pk}: {len(continuity_result.get('assigned_therapists', []))} therapists")
                else:
                    booking_continuity_map[booking.pk] = continuity_result
            except Exception as e:
                print(f"[RESCHEDULE PASS1] Error running PASS 1 for booking {booking.pk}: {e}")
                booking_continuity_map[booking.pk] = None
        print(f"[RESCHEDULE PASS1] Built booking_continuity_map with {len([v for v in booking_continuity_map.values() if v and v.get('success')])} continuity assignments")

    # PASS 2: booking_continuity_map contains continuity assignments from PASS 1
    if booking_continuity_map is None:
        booking_continuity_map = {}
    
    print(f"[RESCHEDULE PASS2] booking_continuity_map has {len(booking_continuity_map)} entries (from PASS 1)")

    for booking in bookings_qs:
        booking_id = booking.pk
        therapy_name = allocation.therapy_name

        # Get continuity therapists from PASS 1 if available
        continuity_assigned = booking_continuity_map.get(booking_id, {})
        last_therapists_from_continuity = []
        if continuity_assigned:
            assigned_therapists = continuity_assigned.get('assigned_therapists', [])
            last_therapists_from_continuity = [getattr(t, 'therapist_code', None) for t in assigned_therapists if getattr(t, 'therapist_code', None)]
            print(f"[RESCHEDULE PASS2] Booking {booking_id}: Using {len(last_therapists_from_continuity)} continuity therapists from PASS 1: {last_therapists_from_continuity}")
        
        # Build last_allocation dict with continuity info
        last_allocation = {
            'therapists': last_therapists_from_continuity,
            'continuity_assigned': continuity_assigned
        }

        # preferred slot
        pref_slot = getattr(booking, 'timeslot', None) or getattr(allocation, 'timeslot', None)
        requested_slot_value = None
        if pref_slot:
            st = getattr(pref_slot, 'start_time', None)
            if st:
                try:
                    requested_slot_value = st.strftime("%H:%M")
                except Exception:
                    requested_slot_value = None

        if not pref_slot:
            if force_slot_only:
                print(f"[DEBUG Reschedule] No preferred/registered slot and force_slot_only=True. Failing.")
                tasks.append({
                    "booking_id": booking_id,
                    "allocation_id": therapy_allocation_id,
                    "date": target_date.isoformat() if hasattr(target_date, 'isoformat') else str(target_date),
                    "therapy_name": therapy_name,
                    "slot": None,
                    "status": "FAILED",
                    "reason": "no_registered_slot",
                    "room_no": None,
                    "therapists": []
                })
                continue
            # No preferred -> use automatic slot allocation immediately (do not fail early)
            # Prepare allowed slots for this patient (OP/IP aware)
            therapy_req = therapist_requirements(allocation)
            allowed_slot_values = get_allowed_slot_values(
                patient_type,
                therapy_req.get("therapy_category"),
                used_slots,
                therapy_name,
                getattr(allocation, "therapy_code", None),
                patient_id=patient_id,
                target_date=target_date,
            )
            allocated_here = False
            
            # TIER 1: Try slots WITH continuity (if continuity exists)
            if last_therapists_from_continuity or continuity_assigned:
                print(f"[DEBUG Reschedule] No preferred slot - TIER 1: Trying slots WITH continuity")
                for sv in allowed_slot_values:
                    # map to canonical slot model instance
                    try:
                        parsed_time = datetime.strptime(sv, "%H:%M").time()
                        canonical_slot = SlotMaster.objects.filter(slot_time=parsed_time).first()
                    except Exception:
                        canonical_slot = None
                    if not canonical_slot:
                        continue
                    print(f"[DEBUG Reschedule] Trying slot WITH continuity: {sv} (continuity therapists: {last_therapists_from_continuity})")
                    task, success, reason = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, therapy_needs_room(allocation), therapy_needs_bath(allocation), used_slots, create_bookings, patient_id, last_allocation, AllocationAttempt, allow_helping_fallback=allow_helping_fallback)
                    if success:
                        task["continuity_maintained"] = True
                        tasks.append(task)
                        any_success = True
                        allocated_here = True
                        print(f"[DEBUG Reschedule] [OK] Successfully allocated to slot {sv} WITH continuity")
                        break
                    # else continue trying next slot
                
                if allocated_here:
                    continue
            
            # TIER 2: Try slots WITHOUT continuity (fallback)
            if not allocated_here:
                print(f"[DEBUG Reschedule] No preferred slot - TIER 2: Trying slots WITHOUT continuity (fallback)")
                # Create empty last_allocation to disable continuity
                last_allocation_no_continuity = {
                    'therapists': [],
                    'continuity_assigned': {}
                }
                for sv in allowed_slot_values:
                    # map to canonical slot model instance
                    try:
                        parsed_time = datetime.strptime(sv, "%H:%M").time()
                        canonical_slot = SlotMaster.objects.filter(slot_time=parsed_time).first()
                    except Exception:
                        canonical_slot = None
                    if not canonical_slot:
                        continue
                    print(f"[DEBUG Reschedule] Trying slot WITHOUT continuity: {sv}")
                    task, success, reason = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, therapy_needs_room(allocation), therapy_needs_bath(allocation), used_slots, create_bookings, patient_id, last_allocation_no_continuity, AllocationAttempt, allow_helping_fallback=allow_helping_fallback)
                    if success:
                        task["continuity_maintained"] = False
                        tasks.append(task)
                        any_success = True
                        allocated_here = True
                        print(f"[DEBUG Reschedule] [OK] Successfully allocated to slot {sv} WITHOUT continuity")
                        break
                    # else continue trying next slot
            
            if not allocated_here:
                # Could not allocate any automatic slot (neither with nor without continuity)
                reason = "no_slot_available_auto"
                print(f"[DEBUG Reschedule] [FAIL] Could not allocate to any slot (tried WITH and WITHOUT continuity)")
                tasks.append({
                    "booking_id": booking_id,
                    "allocation_id": therapy_allocation_id,
                    "date": target_date.isoformat(),
                    "therapy_name": therapy_name,
                    "slot": None,
                    "status": "FAILED",
                    "reason": reason,
                    "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None,
                    "therapists": []
                })
            continue  # next booking

        # if preferred exists -> try preferred first
        canonical_pref = map_to_canonical_slot(pref_slot) or pref_slot
        preferred_rejected_reason = None

        # RESTRICTION: Check if preferred slot is 06:30 for Lepam treatment - reject it
        if therapy_name and canonical_pref:
            therapy_name_lower = str(therapy_name).strip().lower()
            if 'lepam' in therapy_name_lower:
                try:
                    pref_slot_time = getattr(canonical_pref, 'slot_time', None) or getattr(canonical_pref, 'start_time', None)
                    if pref_slot_time:
                        pref_slot_str = pref_slot_time.strftime("%H:%M") if hasattr(pref_slot_time, 'strftime') else str(pref_slot_time)
                        if pref_slot_str == "06:30":
                            print(f"[SLOT RESTRICTION] Lepam treatment cannot use 06:30 slot. Rejecting preferred slot and trying alternatives.")
                            canonical_pref = None  # Force fallback to automatic slot allocation
                            preferred_rejected_reason = "lepam_cannot_use_0630_slot"
                except Exception as e:
                    print(f"[SLOT RESTRICTION] Error checking preferred slot for Lepam: {e}")

        # Vasthi therapy group (except Mathra THEB037): force allocation attempts to 08:30 only
        if is_group_vasthi_0830_only(therapy_name, getattr(allocation, "therapy_code", None)):
            try:
                t0830 = datetime.strptime("08:30", "%H:%M").time()
                sm = SlotMaster.objects.filter(slot_time=t0830, is_active=True).first()
                if sm:
                    cur_t = None
                    if canonical_pref:
                        cur_t = getattr(canonical_pref, "slot_time", None) or getattr(canonical_pref, "start_time", None)
                    if cur_t != t0830:
                        canonical_pref = sm
                        preferred_rejected_reason = None
                        print("[SLOT RESTRICTION] Vasthi therapy group: normalized preferred slot to 08:30")
                else:
                    canonical_pref = None
                    preferred_rejected_reason = "group_vasthi_no_0830_slotmaster"
                    print("[SLOT RESTRICTION] Vasthi therapy group: no active SlotMaster for 08:30")
            except Exception as e:
                print(f"[SLOT RESTRICTION] Vasthi therapy group preferred-slot normalization error: {e}")

        # HARD TREATMENT RESTRICTION: Check if preferred slot is in a session where patient already has a hard treatment
        if canonical_pref and (is_hard_treatment(allocation, therapy_name=therapy_name) or (therapy_req.get("therapy_category") and str(therapy_req.get("therapy_category")).strip().lower() == 'hard')):
            pref_session = get_slot_session(canonical_pref)
            if pref_session and patient_id and patient_has_hard_treatment_in_session(
                patient_id=patient_id,
                target_date=target_date,
                session=pref_session,
                exclude_booking_id=booking_id,
                exclude_allocation_id=therapy_allocation_id
            ):
                print(f"[HARD TREATMENT RESTRICTION] Patient {patient_id} already has a hard treatment in {pref_session} session on {target_date}. Rejecting preferred slot and trying alternate slots.")
                canonical_pref = None
                preferred_rejected_reason = "hard_treatment_same_session_conflict"

        therapy_req = therapist_requirements(allocation)
        needs_room_flag = therapy_needs_room(allocation)
        needs_bath_flag = therapy_needs_bath(allocation)

        # If preferred slot was rejected (e.g. Lepam at 06:30, or Vasthi group with no 08:30 master), skip attempting it
        if not canonical_pref:
            # Force fallback to automatic slot allocation
            task = None
            success = False
            reason = preferred_rejected_reason or "no_preferred_slot"
            print(f"[SLOT RESTRICTION] Skipping preferred slot attempt (reason={reason}). Will try alternate slots where applicable.")
        else:
            task, success, reason = attempt_allocate_slot(allocation, booking, target_date, canonical_pref, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, last_allocation, AllocationAttempt, allow_helping_fallback=allow_helping_fallback)
        
        if success:
            tasks.append(task)
            any_success = True
            # update last allocation info: attempt to extract room/therapists from task
            try:
                last_room = task.get("room_no")
                if last_room:
                    # store last room identifier
                    # last_allocation is not used much here, but kept for parity
                    pass
            except Exception:
                pass
            continue
        else:
            if force_slot_only:
                # User or caller explicitly restricted allocation to ONLY the preferred/registered slot.
                # DO NOT attempt automatic fallback to alternate slots!
                print(f"[DEBUG Reschedule] Preferred/registered slot failed and force_slot_only=True. Will NOT try alternate slots.")
                try:
                    booking.status = 'failed'
                    booking.room = None
                    booking.failure_reason = str(reason or 'Preferred slot failed')[:512]
                    booking.save(update_fields=['status', 'room', 'failure_reason', 'updated_at'])
                except Exception:
                    pass
                tasks.append(task if isinstance(task, dict) else {
                    "booking_id": booking_id,
                    "allocation_id": therapy_allocation_id,
                    "date": target_date.isoformat(),
                    "therapy_name": therapy_name,
                    "slot": requested_slot_value,
                    "status": "FAILED",
                    "reason": reason or "Preferred slot failed",
                    "room_no": None,
                    "therapists": []
                })
                continue

            # preferred slot failed -> attempt automatic slots as reschedule when failure is due to
            # capacity/conflict OR patient/slot conflicts. This enables trying alternate slots when
            # the patient already has a booking at the preferred slot OR room is not available.
            
            # Extract reason from task if reason is None (fallback)
            if not reason and isinstance(task, dict):
                reason = task.get("reason", "unknown_failure")
            
            print(f"[DEBUG Reschedule] Preferred slot failed. Success: {success}, Reason: {reason}, Task: {task}")
            
            fallback_reasons = {
                "insufficient_therapists_available",
                "no_room_available",
                "room_already_booked",
                "therapist_already_booked",
                "patient_already_has_booking",
                "slot_already_used_in_run",
                "bathing_therapist_unavailable",  # Also try alternate slots if bathing therapist unavailable
                "hard_treatment_same_session_conflict",
            }
            # Always try alternate slots if preferred slot failed (unless it's a critical error that won't be fixed by slot change)
            # This ensures we try other slots when room/therapist/patient conflicts occur
            should_try_fallback = False
            if reason:
                reason_str = str(reason).lower()  # Convert to lowercase for case-insensitive matching
                # Check if reason matches any fallback reason (case-insensitive)
                if any(r.lower() in reason_str for r in fallback_reasons):
                    should_try_fallback = True
                    print(f"[DEBUG Reschedule] Preferred slot failed with reason: {reason}. Will try alternate slots.")
                # Also try fallback if reason contains keywords indicating availability issues
                elif any(keyword in reason_str for keyword in ["room", "therapist", "patient", "bathing", "available", "booked", "conflict"]):
                    should_try_fallback = True
                    print(f"[DEBUG Reschedule] Preferred slot failed with reason: {reason}. Will try alternate slots (keyword match).")
            else:
                # If no reason provided, still try fallback (might be a generic failure)
                should_try_fallback = True
                print(f"[DEBUG Reschedule] Preferred slot failed with no reason. Will try alternate slots as fallback.")
            
            if should_try_fallback:
                # attempt other allowed slots (OP/IP aware)
                allowed_slot_values = get_allowed_slot_values(
                    patient_type,
                    therapy_req.get("therapy_category"),
                    used_slots,
                    therapy_name,
                    getattr(allocation, "therapy_code", None),
                    patient_id=patient_id,
                    target_date=target_date,
                )
                print(f"[DEBUG Reschedule] Allowed slot values for patient_type={patient_type}, category={therapy_req.get('therapy_category')}: {allowed_slot_values}")
                
                # remove preferred if present
                try:
                    pref_val = getattr(canonical_pref, 'start_time', None).strftime("%H:%M") if getattr(canonical_pref,'start_time',None) else None
                except Exception:
                    pref_val = None
                allowed_slot_values = [s for s in allowed_slot_values if s != pref_val]
                print(f"[DEBUG Reschedule] After removing preferred slot {pref_val}, remaining slots: {allowed_slot_values}")
                
                allocated_here = False
                
                # TIER 1: Try alternate slots WITH continuity (if continuity exists)
                if last_therapists_from_continuity or continuity_assigned:
                    print(f"[DEBUG Reschedule] ===== TIER 1: Trying alternate slots WITH continuity =====")
                    for sv in allowed_slot_values:
                        try:
                            parsed_time = datetime.strptime(sv, "%H:%M").time()
                            canonical_slot = SlotMaster.objects.filter(slot_time=parsed_time).first()
                        except Exception:
                            canonical_slot = None
                        if not canonical_slot:
                            print(f"[DEBUG Reschedule] Could not find SlotMaster for time {sv}")
                            continue
                        
                        print(f"[DEBUG Reschedule] Trying alternate slot WITH continuity: {sv} (continuity therapists: {last_therapists_from_continuity})")
                        task2, success2, reason2 = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, last_allocation, AllocationAttempt, allow_helping_fallback=allow_helping_fallback)
                        print(f"[DEBUG Reschedule] Alternate slot {sv} WITH continuity result: success={success2}, reason={reason2}")
                        
                        if success2:
                            # flag slot_changed so caller knows we used an alternate slot
                            task2["slot_changed"] = True
                            task2["preferred_slot"] = pref_val
                            task2["continuity_maintained"] = True
                            tasks.append(task2)
                            any_success = True
                            allocated_here = True
                            print(f"[DEBUG Reschedule] [OK] Successfully allocated to alternate slot {sv} WITH continuity (preferred was {pref_val})")
                            break
                        else:
                            print(f"[DEBUG Reschedule] Alternate slot {sv} WITH continuity failed: {reason2}")
                    
                    if allocated_here:
                        continue
                    else:
                        print(f"[DEBUG Reschedule] [FAIL] All alternate slots WITH continuity failed. Trying WITHOUT continuity...")
                
                # TIER 2: Try alternate slots WITHOUT continuity (fallback)
                print(f"[DEBUG Reschedule] ===== TIER 2: Trying alternate slots WITHOUT continuity (fallback) =====")
                # Create empty last_allocation to disable continuity
                last_allocation_no_continuity = {
                    'therapists': [],
                    'continuity_assigned': {}
                }
                
                for sv in allowed_slot_values:
                    try:
                        parsed_time = datetime.strptime(sv, "%H:%M").time()
                        canonical_slot = SlotMaster.objects.filter(slot_time=parsed_time).first()
                    except Exception:
                        canonical_slot = None
                    if not canonical_slot:
                        print(f"[DEBUG Reschedule] Could not find SlotMaster for time {sv}")
                        continue
                    
                    print(f"[DEBUG Reschedule] Trying alternate slot WITHOUT continuity: {sv}")
                    task2, success2, reason2 = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, last_allocation_no_continuity, AllocationAttempt, allow_helping_fallback=allow_helping_fallback)
                    print(f"[DEBUG Reschedule] Alternate slot {sv} WITHOUT continuity result: success={success2}, reason={reason2}")
                    
                    if success2:
                        # flag slot_changed so caller knows we used an alternate slot
                        task2["slot_changed"] = True
                        task2["preferred_slot"] = pref_val
                        task2["continuity_maintained"] = False
                        tasks.append(task2)
                        any_success = True
                        allocated_here = True
                        print(f"[DEBUG Reschedule] [OK] Successfully allocated to alternate slot {sv} WITHOUT continuity (preferred was {pref_val})")
                        break
                    else:
                        print(f"[DEBUG Reschedule] Alternate slot {sv} WITHOUT continuity failed: {reason2}")
                
                if allocated_here:
                    continue
                else:
                    print(f"[DEBUG Reschedule] [FAIL] All alternate slots failed (both WITH and WITHOUT continuity). Original failure reason: {reason}")
                # else fall through to return original failure reason task
            # Preferred failed and no fallback succeeded -> include the failure task (task contains reason)
            try:
                booking.status = 'failed'
                booking.room = None
                booking.failure_reason = str(reason or 'All slots failed')[:512]
                booking.save(update_fields=['status', 'room', 'failure_reason', 'updated_at'])
            except Exception:
                pass
            tasks.append(task)

    # update allocation header
    try:
        allocation.status = 'allocated' if any_success else 'failed'
        allocation.save(update_fields=['status'])
    except Exception:
        pass

    return tasks

# -----------------------
# Compatibility wrapper for external callers
# -----------------------
def allocate_therapy_for_visit(therapy_allocation_id, target_date, create_bookings=True, allow_helping_fallback=False, force_slot_only=False):
    """
    Backwards-compatible wrapper expected by callers. Delegates to expand_therapies_for_visit.
    """
    return expand_therapies_for_visit(
        therapy_allocation_id, 
        target_date, 
        create_bookings=create_bookings, 
        allow_helping_fallback=allow_helping_fallback, 
        force_slot_only=force_slot_only
    )

