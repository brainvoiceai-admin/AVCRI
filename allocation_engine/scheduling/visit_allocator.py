"""
Scheduling Visit Allocator (Layer 3A).

Hosts the regular scheduling `expand_therapies_for_visit` orchestrator.
Must remain separate from `allocation_engine.rescheduling.visit_rescheduler.expand_therapies_for_visit`.
Must NEVER import `allocation_engine.rescheduling`, `reshedule`, or `resheduleMorningandNight`.
"""

import sys
from datetime import datetime, timedelta
from types import SimpleNamespace
from django.db import transaction, IntegrityError
from django.db.models import Q

from allocation_engine.core.primitives.exceptions import IncompleteAssignmentError
from allocation_engine.core.primitives.date_utils import daterange
from allocation_engine.core.primitives.patient_utils import (
    is_patient_active as _canonical_is_patient_active,
    parse_patient_age,
    resolve_desired_gender,
)
from allocation_engine.core.primitives.room_utils import get_treatment_rooms_for_staying_room
from allocation_engine.core.primitives.slot_utils import map_to_canonical_slot
from allocation_engine.core.primitives.shift_utils import (
    _shift_enforcement_enabled,
    _shift_eligibility_sets_for_slot,
)
from allocation_engine.core.primitives.therapy_catalog import (
    therapy_cache,
    clear_therapy_cache,
    get_therapy_details,
    therapy_needs_room,
    therapy_needs_bath,
    get_therapist_grade_name,
    therapist_requirements as _core_therapist_requirements,
)
from allocation_engine.core.primitives.booking_persistence import (
    create_room_booking_safe as _core_create_room_booking_safe,
    create_therapist_booking_safe as _core_create_therapist_booking_safe,
)
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
from allocation_engine.core.allocators.prioritization import get_patient_category_priority
from allocation_engine.core.allocators.room_allocator import (
    SCHEDULING_ROOM_CONFIG,
    allocate_treatment_room as _allocate_treatment_room_core,
)
from allocation_engine.core.allocators.slot_policy import (
    allocate_treatment_slot,
    get_allowed_slot_values,
)
from allocation_engine.core.allocators.therapist_allocator import (
    SCHEDULING_THERAPIST_CONFIG,
    allocate_therapists as _allocate_therapists_core,
)


def is_patient_active(patient):
    """Call canonical is_patient_active while honoring legacy facade mock patches in tests."""
    legacy_mod = sys.modules.get("final_allocation")
    if legacy_mod is not None:
        patched = getattr(legacy_mod, "is_patient_active", None)
        if patched is not None and patched is not _canonical_is_patient_active:
            return patched(patient)
    return _canonical_is_patient_active(patient)


def therapist_requirements(allocation_or_therapy_obj):
    return _core_therapist_requirements(allocation_or_therapy_obj, default_total_if_missing=1)


def create_room_booking_safe(room, date, time_slot, therapy_name, patient_id, visit):
    return _core_create_room_booking_safe(
        room, date, time_slot, therapy_name, patient_id, visit,
        use_atomic=False, refresh=True,
    )


def create_therapist_booking_safe(therapist, date, time_slot, therapy_name, patient_id, visit, is_bathing=False):
    return _core_create_therapist_booking_safe(
        therapist, date, time_slot, therapy_name, patient_id, visit,
        is_bathing=is_bathing, use_atomic=False, resolve_therapy_fk=True, refresh=True,
    )


def allocate_treatment_room(date, time_slot, last_room=None, therapy_name=None, patient_id=None, patient_staying_room=None, patient=None, is_wheelchair=False, booking_id=None):
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
        config=SCHEDULING_ROOM_CONFIG,
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


def expand_therapies_for_visit(therapy_allocation_id, target_date, create_bookings=True, slot_avoid_map=None, booking_continuity_map=None):
    """
    Strict preferred-slot-only allocation using Booking rows.
    Persists TherapistBooking.is_bathing when applicable.
    
    PASS 2: If booking_continuity_map is provided, uses continuity therapists from PASS 1
    and only fills remaining slots.
    
    Returns list of task dicts. Each task['therapists'] is a list of dicts:
      {"therapist_code": "...", "is_bathing": True|False}
    
    Args:
        booking_continuity_map: Dict mapping booking_id -> continuity_assigned dict from PASS 1
    """
    # normalize date
    if isinstance(target_date, str):
        try:
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except Exception:
            return {"error": f"Invalid date format: {target_date}. Use YYYY-MM-DD."}

    # Defensive imports (adjust paths if your apps differ)
    from Sheduling.models import TherapyAllocation, Booking
    from Patient.models import TherapistBooking, RoomBooking, AllocationAttempt
    from masters.models import SlotMaster

    allocation = TherapyAllocation.objects.filter(pk=therapy_allocation_id).first()
    if not allocation:
        return {"error": f"TherapyAllocation id {therapy_allocation_id} not found."}

    # ----- INACTIVE PATIENT CHECK -----
    # If the patient is inactive, mark all bookings for this date as failed
    # and skip scheduling entirely.
    patient_snapshot = getattr(allocation, 'patient', None)
    pat_reg_no = getattr(patient_snapshot, 'pat_reg_no', None) if patient_snapshot else None
    if pat_reg_no and not is_patient_active(pat_reg_no):
        print(f"[PATIENT STATUS] Skipping scheduling for inactive patient {pat_reg_no} "
              f"(allocation {therapy_allocation_id}, date {target_date})")
        # Mark all bookings for this allocation+date as failed
        inactive_bookings = Booking.objects.filter(
            allocation_id=therapy_allocation_id,
            date=target_date,
            status='draft'
        )
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
            # No draft bookings found, but still report the inactive status
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

    # Check if this is a nurse treatment - if so, handle it separately
    from Sheduling.nurse_allocation import is_nurse_treatment
    nurse_treatment = is_nurse_treatment(allocation.therapy_code, allocation.therapy_name)
    
    if nurse_treatment:
        # For nurse treatments, skip therapist allocation and just allocate nurses
        bookings_qs = Booking.objects.filter(allocation_id=therapy_allocation_id, date=target_date)
        if not bookings_qs.exists():
            return {"error": f"No Booking rows found for allocation {therapy_allocation_id} on {target_date.isoformat()}."}
        
        tasks = []
        from Sheduling.nurse_allocation import allocate_nurses_for_booking
        
        for booking in bookings_qs:
            booking_id = booking.pk
            therapy_name = allocation.therapy_name
            
            # Allocate nurses
            try:
                nurse_assignments = allocate_nurses_for_booking(booking)
                # Mark booking as scheduled (nurse treatments don't need therapists)
                booking.status = 'scheduled'
                booking.save(update_fields=['status', 'updated_at'])
                
                # Get nurse names for response
                nurse_names = [f"{na.nurse.nurse_name} ({na.nurse.nurse_code})" for na in nurse_assignments]
                
                tasks.append({
                    "booking_id": booking_id,
                    "allocation_id": therapy_allocation_id,
                    "date": target_date.isoformat(),
                    "therapy_name": therapy_name,
                    "slot": getattr(booking.timeslot, 'slot_time', None).strftime('%H:%M') if booking.timeslot and hasattr(booking.timeslot, 'slot_time') else None,
                    "status": "BOOKED",
                    "reason": None,
                    "room_no": getattr(booking.room, 'room_no', None) if booking.room else None,
                    "therapists": [],  # No therapists for nurse treatments
                    "nurses": nurse_names  # Include nurses in response
                })
            except Exception as e:
                print(f"Error allocating nurses for booking {booking_id}: {e}")
                booking.status = 'failed'
                booking.failure_reason = (f"nurse_allocation_error: {e}" or '')[:512]
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                tasks.append({
                    "booking_id": booking_id,
                    "allocation_id": therapy_allocation_id,
                    "date": target_date.isoformat(),
                    "therapy_name": therapy_name,
                    "slot": None,
                    "status": "FAILED",
                    "reason": f"Error allocating nurses: {str(e)}",
                    "room_no": None,
                    "therapists": [],
                    "nurses": []
                })
        
        return tasks

    bookings_qs = Booking.objects.filter(allocation_id=therapy_allocation_id, date=target_date)
    if not bookings_qs.exists():
        return {"error": f"No Booking rows found for allocation {therapy_allocation_id} on {target_date.isoformat()}."}

    # CLEAR EXISTING ASSIGNMENTS/BOOKINGS for this allocation/date BEFORE starting algorithm.
    # This prevents accumulation of therapists (ghost records) when rescheduling.
    # IMPORTANT: When booking_continuity_map is provided (PASS 1 was done), preserve the
    # TherapistBooking records created by PASS 1 so continuity therapists are not "freed"
    # and stolen by other allocations running in PASS 2.
    if create_bookings:
        try:
            from django.db.models import Q

            # Collect therapist IDs that PASS 1 locked for this allocation so we can exclude them from cleanup.
            pass1_locked_therapist_ids = set()
            if booking_continuity_map:
                for bk in bookings_qs:
                    cont = booking_continuity_map.get(bk.pk)
                    if cont and isinstance(cont, dict):
                        for t in cont.get('assigned_therapists', []):
                            tid = getattr(t, 'id', None)
                            if tid is not None:
                                pass1_locked_therapist_ids.add(tid)

            # 1. Cancel existing TherapistBooking records linked to this allocation/date
            #    BUT exclude PASS 1 continuity therapists so their locks remain intact.
            cancel_tb_qs = TherapistBooking.objects.filter(
                visit=allocation,
                date=target_date,
                status='BOOKED'
            )
            if pass1_locked_therapist_ids:
                cancel_tb_qs = cancel_tb_qs.exclude(therapist_id__in=pass1_locked_therapist_ids)
                print(f"[FINAL ALLOCATION] Preserving {len(pass1_locked_therapist_ids)} PASS 1 continuity therapist bookings during cleanup")
            cancel_tb_qs.update(status='CANCELED')

            # 2. Cancel existing RoomBooking records linked to this allocation/date
            RoomBooking.objects.filter(
                date=target_date,
                status='BOOKED'
            ).filter(
                Q(therapy=allocation) | Q(visit__allocation=allocation)
            ).update(status='CANCELED')

            # 3. Delete existing UI assignments for these bookings
            from Sheduling.models import BookingAssignment
            BookingAssignment.objects.filter(booking__in=bookings_qs).delete()
            
            print(f"[FINAL ALLOCATION] 🧹 Cleared existing bookings/assignments for allocation {therapy_allocation_id} on {target_date} to prevent ghost therapists")
        except Exception as cleanup_e:
            print(f"[FINAL ALLOCATION] ⚠ Cleanup error (non-fatal): {cleanup_e}")

    bookings_list = list(bookings_qs)
    print(f"[CONTINUITY PASS2] expand_therapies_for_visit: Processing {len(bookings_list)} bookings for allocation {therapy_allocation_id}")
    
    tasks = []
    used_slots = []
    any_success = False
    patient_id = getattr(allocation.patient, 'id', None)
    pat_reg_no = getattr(getattr(allocation, 'patient', None), 'pat_reg_no', None)
    patient_staying_room = getattr(allocation.patient, 'pat_room_no', None)

    preferred_roster_info = None
    for pid in filter(None, [patient_id, pat_reg_no]):
        try:
            from Sheduling.preferred_therapist_service import get_active_preferred_roster
            preferred_roster_info = get_active_preferred_roster(pid)
            if preferred_roster_info:
                break
        except Exception:
            pass
    
    # PASS 2: booking_continuity_map contains continuity assignments from PASS 1
    # Maps booking_id -> continuity_assigned dict
    if booking_continuity_map is None:
        booking_continuity_map = {}
    
    print(f"[CONTINUITY PASS2] booking_continuity_map has {len(booking_continuity_map)} entries (from PASS 1)")

    def therapist_entry(t_obj, is_bath=False):
        return {"therapist_code": getattr(t_obj, 'therapist_code', None) or str(t_obj), "is_bathing": bool(is_bath)}

    for booking in bookings_qs:
        booking_id = booking.pk
        therapy_name = allocation.therapy_name
        
        # PASS 2: Get continuity assignment from PASS 1 for this booking
        continuity_assigned = booking_continuity_map.get(booking_id, None)
        print(f"[CONTINUITY PASS2] Booking {booking_id}: continuity_assigned from PASS 1 = {continuity_assigned}")
        print(f"[CONTINUITY PASS2] Booking {booking_id}: type(continuity_assigned) = {type(continuity_assigned)}")
        if continuity_assigned:
            print(f"[CONTINUITY PASS2] Booking {booking_id}: Using continuity assignment from PASS 1")
            print(f"[CONTINUITY PASS2] Booking {booking_id}: continuity_assigned keys = {continuity_assigned.keys() if isinstance(continuity_assigned, dict) else 'NOT A DICT'}")
            if isinstance(continuity_assigned, dict):
                print(f"[CONTINUITY PASS2] Booking {booking_id}: assigned_therapists count = {len(continuity_assigned.get('assigned_therapists', []))}")

        # preferred slot only
        pref_slot = getattr(booking, 'timeslot', None) or getattr(allocation, 'timeslot', None)
        # Vasthi therapy (marked via TherapyMaster.is_vasthi or Vasthi group, except Mathra THEB037): schedule in dynamic Vasthi slot (defaults to 08:30)
        try:
            from allocation_engine.rules.vasthi import is_vasthi_treatment, get_vasthi_slots
            if is_vasthi_treatment(therapy_name, getattr(allocation, 'therapy_code', None)):
                # If pref_slot is already designated as an active Vasthi slot, keep it
                is_current_slot_vasthi = bool(pref_slot and getattr(pref_slot, 'is_vasthi_slot', False) and getattr(pref_slot, 'is_active', True))
                if not is_current_slot_vasthi:
                    vasthi_slot_obj = SlotMaster.objects.filter(is_vasthi_slot=True, is_active=True).order_by('slot_time').first()
                    if not vasthi_slot_obj:
                        vasthi_slot_obj = SlotMaster.objects.filter(
                            slot_time=datetime.strptime('08:30', '%H:%M').time(),
                            is_active=True,
                        ).first()
                    if vasthi_slot_obj:
                        pref_slot = vasthi_slot_obj
                        if create_bookings and getattr(booking, 'timeslot_id', None) != vasthi_slot_obj.id:
                            booking.timeslot = vasthi_slot_obj
                            booking.save(update_fields=['timeslot', 'updated_at'])
                    else:
                        print('[VASTHI GROUP] Final schedule: no active SlotMaster for Vasthi slot')
        except Exception as _gv_e:
            print(f'[SLOT RULE] Final schedule slot rule skipped: {_gv_e}')

        # Vamanam therapy: schedule in dynamic Vamanam slot (defaults to 06:30)
        try:
            from allocation_engine.rules.vamanam import is_vamanam_treatment, get_vamanam_slots
            if is_vamanam_treatment(therapy_name, getattr(allocation, 'therapy_code', None)):
                is_current_slot_vamanam = bool(pref_slot and getattr(pref_slot, 'is_vamanam_slot', False) and getattr(pref_slot, 'is_active', True))
                if not is_current_slot_vamanam:
                    vamanam_slot_obj = SlotMaster.objects.filter(is_vamanam_slot=True, is_active=True).order_by('slot_time').first()
                    if not vamanam_slot_obj:
                        vamanam_slot_obj = SlotMaster.objects.filter(
                            slot_time=datetime.strptime('06:30', '%H:%M').time(),
                            is_active=True,
                        ).first()
                    if vamanam_slot_obj:
                        pref_slot = vamanam_slot_obj
                        if create_bookings and getattr(booking, 'timeslot_id', None) != vamanam_slot_obj.id:
                            booking.timeslot = vamanam_slot_obj
                            booking.save(update_fields=['timeslot', 'updated_at'])
                    else:
                        print('[VAMANAM GROUP] Final schedule: no active SlotMaster for Vamanam slot')
        except Exception as _vm_slot_e:
            print(f'[VAMANAM SLOT RULE] Final schedule slot rule skipped: {_vm_slot_e}')
        requested_slot_value = None
        if pref_slot:
            st = getattr(pref_slot, 'start_time', None)
            if st:
                try:
                    requested_slot_value = st.strftime("%H:%M")
                except Exception:
                    requested_slot_value = None

        if not pref_slot:
            reason = "no_preferred_slot"
            print(f"[CONTINUITY PASS2] Booking {booking_id}: SKIPPING due to no_preferred_slot (continuity_assigned={continuity_assigned is not None})")
            # Update booking status to failed
            try:
                booking.status = 'failed'
                booking.failure_reason = (str(reason) or '')[:512]
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
            except Exception as e:
                print(f"Error updating booking {booking_id} to failed: {e}")
            
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=None, requested_time_slot_value='',
                        status='FAILED', reason=reason, extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": None, "status": "FAILED", "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": []
            })
            continue

        canonical_slot = map_to_canonical_slot(pref_slot) or pref_slot
        
        # Resolve slot_master early to ensure we always use SlotMaster instances for FK relationships
        # This prevents FK constraint failures when canonical_slot is not a SlotMaster
        slot_master = None
        if canonical_slot:
            if isinstance(canonical_slot, SlotMaster):
                slot_master = canonical_slot
            else:
                # Try to find SlotMaster by slot_time
                slot_time = getattr(canonical_slot, 'slot_time', None)
                if slot_time:
                    slot_master = SlotMaster.objects.filter(slot_time=slot_time, is_active=True).first()
                if not slot_master:
                    # Fallback: use existing booking timeslot if available
                    slot_master = getattr(booking, 'timeslot', None)
                    if not slot_master and pref_slot and isinstance(pref_slot, SlotMaster):
                        slot_master = pref_slot
        
        # Use slot_master for queries if available, otherwise fall back to canonical_slot
        query_slot = slot_master if slot_master else canonical_slot
        
        # patient already booked check
        # IMPORTANT: Exclude RoomBooking and TherapistBooking records for this booking/visit to avoid false positives
        patient_already_booked = False
        try:
            patient_already_booked = (
                RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=query_slot, status__in=['BOOKED','scheduled'])
                .exclude(visit=booking)
                .exclude(therapy_id=allocation.id)
                .exclude(Q(therapy__status='cancelled') | Q(visit__status='cancelled') | Q(visit__allocation__status='cancelled'))
                .exists()
                or TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=query_slot, status='BOOKED')
                .exclude(visit_id=allocation.id)
                .exclude(visit__status='cancelled')
                .exists()
            )
        except Exception:
            try:
                slot_start = getattr(pref_slot, 'start_time', None)
                if slot_start:
                    patient_already_booked = (
                        RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot__start_time=slot_start, status__in=['BOOKED','scheduled'])
                        .exclude(visit=booking)
                        .exclude(therapy_id=allocation.id)
                        .exclude(Q(therapy__status='cancelled') | Q(visit__status='cancelled') | Q(visit__allocation__status='cancelled'))
                        .exists()
                        or TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot__start_time=slot_start, status='BOOKED')
                        .exclude(visit_id=allocation.id)
                        .exclude(visit__status='cancelled')
                        .exists()
                    )
            except Exception:
                patient_already_booked = False

        if patient_already_booked:
            reason = "patient_already_has_booking"
            print(f"[CONTINUITY PASS2] Booking {booking_id}: SKIPPING due to patient_already_has_booking (continuity_assigned={continuity_assigned is not None})")
            # Release any PASS 1 TherapistBooking locks for this failed booking so they never leak or block other bookings
            if create_bookings:
                try:
                    TherapistBooking.objects.filter(
                        visit=allocation, date=target_date, time_slot=query_slot, status='BOOKED'
                    ).delete()
                except Exception as _cl_e:
                    print(f"[CONTINUITY PASS2] Error cleaning up PASS 1 locks for booking {booking_id}: {_cl_e}")
            # Update booking status to failed
            try:
                booking.status = 'failed'
                booking.failure_reason = (str(reason) or '')[:512]
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
            except Exception as e:
                print(f"Error updating booking {booking_id} to failed: {e}")
            
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason, extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": []
            })
            continue

        # HARD TREATMENT RESTRICTION: Two hard treatments should not be scheduled in the same session
        # Exception: Medium and Easy treatments (e.g. Lepam) can be assigned in the same session
        from allocation_engine.rules.hard_treatment import is_hard_treatment, get_slot_session, patient_has_hard_treatment_in_session
        is_hard = is_hard_treatment(allocation, therapy_name=therapy_name, therapy_code=getattr(allocation, 'therapy_code', None))
        if is_hard:
            slot_session = get_slot_session(query_slot or canonical_slot)
            if slot_session and patient_id and patient_has_hard_treatment_in_session(
                patient_id=patient_id,
                target_date=target_date,
                session=slot_session,
                exclude_booking_id=booking_id,
                exclude_allocation_id=therapy_allocation_id,
                in_memory_tasks=tasks
            ):
                reason = "hard_treatment_same_session_conflict"
                print(f"[CONTINUITY PASS2] Booking {booking_id}: SKIPPING due to hard_treatment_same_session_conflict for patient {patient_id} in {slot_session} session on {target_date}")
                try:
                    booking.status = 'failed'
                    booking.failure_reason = (str(reason) or '')[:512]
                    booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                except Exception as e:
                    print(f"Error updating booking {booking_id} to failed: {e}")
                
                if AllocationAttempt:
                    try:
                        AllocationAttempt.objects.create(
                            visit=None, therapy=None, date=target_date,
                            requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                            status='FAILED', reason=reason, extra={"booking_id": booking_id, "session": slot_session}
                        )
                    except Exception:
                        pass
                tasks.append({
                    "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                    "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                    "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": []
                })
                continue

        # in-run used slot check
        if any(getattr(s, 'start_time', None) == getattr(query_slot, 'start_time', None) for s in used_slots):
            reason = "slot_already_used_in_run"
            print(f"[CONTINUITY PASS2] Booking {booking_id}: SKIPPING due to slot_already_used_in_run (continuity_assigned={continuity_assigned is not None})")
            # Update booking status to failed
            try:
                booking.status = 'failed'
                booking.failure_reason = (str(reason) or '')[:512]
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
            except Exception as e:
                print(f"Error updating booking {booking_id} to failed: {e}")
            
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason, extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": []
            })
            continue
        
        print(f"[CONTINUITY PASS2] Booking {booking_id}: Passed all early checks, proceeding to therapist allocation (continuity_assigned={continuity_assigned is not None})")
        # therapist reqs and flags
        try:
            therapy_req = therapist_requirements(allocation)
        except Exception:
            therapy_req = {"total": 1, "therapy_category": None}

        needs_room_flag = therapy_needs_room(allocation) if therapy_needs_room else bool(getattr(booking, 'room', None))
        needs_bath_flag = therapy_needs_bath(allocation) if therapy_needs_bath else False
        
        # Check for previous therapists (bathing + others) for continuity
        # Now driven by TherapistContinuityPlan built in bulk_allocate_for_date
        previous_bathing_therapist = None
        previous_therapist_group = []
        allocate_slot = slot_master if slot_master else canonical_slot

        if patient_id and allocate_slot is not None:
            try:
                from Sheduling.models import TherapistContinuityPlan

                continuity_qs = TherapistContinuityPlan.objects.filter(
                    date=target_date,
                    time_slot=allocate_slot,
                    allocation_id=allocation.id,
                    patient_id=patient_id,
                ).select_related('therapist').order_by('priority', 'therapist_id')

                previous_therapist_group = [row.therapist for row in continuity_qs if row.therapist]

                # Debug: log continuity plan for this patient / therapy / slot
                patient_obj = getattr(allocation, 'patient', None)
                patient_name = getattr(patient_obj, 'pat_name', '') if patient_obj else ''
                therapy_name_dbg = getattr(allocation, 'therapy_name', '')
                slot_time_dbg = getattr(getattr(allocate_slot, 'slot_time', None), 'strftime', lambda *_: None)('%H:%M') if getattr(allocate_slot, 'slot_time', None) else None
                print(f"[CONTINUITY ASSIGN] ----")
                print(f"[CONTINUITY ASSIGN] Date={target_date}, slot_id={getattr(allocate_slot,'id',None)}, slot_time={slot_time_dbg}, "
                      f"patient_id={patient_id}, patient_name='{patient_name}', therapy='{therapy_name_dbg}'")
                if previous_therapist_group:
                    print(f"[CONTINUITY ASSIGN]   Previous-day therapists from plan:")
                    for row in continuity_qs:
                        t = row.therapist
                        if not t:
                            continue
                        t_name = getattr(t, "therapist_name", "")
                        t_code = getattr(t, "therapist_code", "")
                        grade_name = getattr(getattr(t, "therapist_grade", None), "name", "")
                        print(f"    - {t_name} ({t_code}), grade='{grade_name}', "
                              f"is_bathing_plan={row.is_bathing}, priority={row.priority}, source_date={row.source_date}")
                else:
                    print(f"[CONTINUITY ASSIGN]   No continuity therapists found in plan for this booking")

                if needs_bath_flag:
                    # BATHING CONTINUITY: Prefer bathing therapist from START OF THERAPY (same as PASS 1).
                    # So Dhara & Pizichil and all therapies get start-of-therapy bathing therapist when available.
                    try:
                        from Patient.models import TherapistBooking
                        from masters.models import TherapistLeaveMaster, EmergencyLeave
                        from django.db.models import Q
                        therapy_start_date = getattr(allocation, 'from_date', None)
                        # Only bathing history for THIS allocation and THIS slot
                        prev_bath_qs = TherapistBooking.objects.filter(
                            patient_id=patient_id,
                            visit_id=allocation.id,
                            time_slot=allocate_slot,
                            date__lt=target_date,
                            is_bathing=True,
                            status='BOOKED'
                        ).select_related('therapist').order_by('date', 'created_at')
                        if therapy_start_date:
                            prev_bath_qs = prev_bath_qs.filter(date__gte=therapy_start_date)
                        prev_bath_list = list(prev_bath_qs)
                        seen_b = set()
                        therapists_from_start = []
                        for b in prev_bath_list:
                            if not b.therapist:
                                continue
                            if not getattr(b.therapist, 'is_active', True):
                                continue
                            if b.therapist.pk not in seen_b:
                                seen_b.add(b.therapist.pk)
                                therapists_from_start.append(b.therapist)
                        day_w = target_date.weekday()
                        for th in therapists_from_start:
                            on_leave = False
                            if TherapistLeaveMaster.objects.filter(therapist=th, leave_day=day_w).exists():
                                on_leave = True
                            from masters.models import is_therapist_on_emergency_leave, is_therapist_deputed, is_therapist_omitted_for_treatment
                            if not on_leave and is_therapist_on_emergency_leave(th, target_date, allocate_slot):
                                on_leave = True
                            if not on_leave and is_therapist_deputed(th, target_date):
                                on_leave = True
                            if not on_leave and is_therapist_omitted_for_treatment(th, alloc_therapy or current_therapy_name):
                                on_leave = True
                            if not on_leave and TherapistBooking.objects.filter(
                                therapist=th, date=target_date, time_slot=allocate_slot, status='BOOKED'
                            ).exists():
                                on_leave = True
                            if not on_leave:
                                previous_bathing_therapist = th
                                break
                        if not previous_bathing_therapist and therapists_from_start:
                            # Fallback: use plan or first from group
                            bath_row = next((row for row in continuity_qs if row.is_bathing and getattr(row.therapist, 'is_bathing_therapist', False) and getattr(row.therapist, 'is_active', True)), None)
                            if bath_row:
                                previous_bathing_therapist = bath_row.therapist
                            else:
                                for t in previous_therapist_group:
                                    if getattr(t, 'is_bathing_therapist', False) and getattr(t, 'is_active', True):
                                        previous_bathing_therapist = t
                                        break
                    except Exception as e:
                        print(f"[CONTINUITY ASSIGN] Error resolving bathing from start: {e}")
                        bath_row = next((row for row in continuity_qs if row.is_bathing and getattr(row.therapist, 'is_bathing_therapist', False) and getattr(row.therapist, 'is_active', True)), None)
                        if bath_row:
                            previous_bathing_therapist = bath_row.therapist
                        else:
                            for t in previous_therapist_group:
                                if getattr(t, 'is_bathing_therapist', False) and getattr(t, 'is_active', True):
                                    previous_bathing_therapist = t
                                    break

                if previous_therapist_group:
                    print(f"[DEBUG] ContinuityPlan: {len(previous_therapist_group)} therapists for patient {patient_id} on {target_date} slot {getattr(allocate_slot,'id',None)}")
            except Exception as e:
                print(f"[DEBUG] Error reading TherapistContinuityPlan: {e}")
        
        # allocate therapists
        # PASS 2: If continuity_assigned is provided, use those therapists and only fill remaining slots
        candidate_therapists = []
        print(f"[CONTINUITY PASS2] Booking {booking_id}: ========== ENTERING THERAPIST ALLOCATION SECTION ==========")
        print(f"[CONTINUITY PASS2] Booking {booking_id}: About to check continuity_assigned. Value: {continuity_assigned}, Type: {type(continuity_assigned)}, Is dict: {isinstance(continuity_assigned, dict) if continuity_assigned else False}")
        print(f"[CONTINUITY PASS2] Booking {booking_id}: bool(continuity_assigned) = {bool(continuity_assigned)}, isinstance check = {isinstance(continuity_assigned, dict) if continuity_assigned else False}")
        if continuity_assigned and isinstance(continuity_assigned, dict):
            print(f"[CONTINUITY PASS2] Booking {booking_id}: ENTERING continuity_assigned block!")
            # PASS 2: Use continuity therapists from PASS 1 and fill remaining slots
            assigned_continuity = continuity_assigned.get('assigned_therapists', [])
            remaining_req = dict(continuity_assigned.get('remaining_requirements', therapy_req))
            if 'therapy_code' not in remaining_req or not remaining_req['therapy_code']:
                remaining_req['therapy_code'] = therapy_req.get('therapy_code') or getattr(allocation, 'therapy_code', None)
            if 'therapy_name' not in remaining_req or not remaining_req['therapy_name']:
                remaining_req['therapy_name'] = therapy_req.get('therapy_name') or getattr(allocation, 'therapy_name', None) or therapy_name
            result_bath_assigned = continuity_assigned.get('bath_assigned', None)
            result_senior_therapist = continuity_assigned.get('senior_therapist', None)
            
            print(f"[CONTINUITY PASS2] Booking {booking.pk}: Using {len(assigned_continuity)} continuity therapists from PASS 1, filling {remaining_req.get('total', 0)} remaining slots")
            print(f"[CONTINUITY PASS2]   Continuity therapists from PASS 1: {[getattr(t, 'therapist_code', 'UNKNOWN') for t in assigned_continuity]}")
            
            # Start with continuity therapists
            candidate_therapists = list(assigned_continuity)
            print(f"[CONTINUITY PASS2]   candidate_therapists initialized with {len(candidate_therapists)} continuity therapists")
            print(f"[CONTINUITY PASS2]   candidate_therapists list: {[getattr(t, 'therapist_code', 'UNKNOWN') for t in candidate_therapists]}")
            
            # Fill remaining slots using existing allocation logic
            if remaining_req.get('total', 0) > 0:
                try:
                    pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
                    pat_age = getattr(getattr(allocation, 'patient', None), 'pat_age', None)
                    pat_reg_id = getattr(getattr(allocation, 'patient', None), 'pat_reg_no', None) or getattr(allocation, 'patient_id', None)
                    
                    # Prefer "from start of therapy" therapists when filling remaining slots (e.g. they were on leave yesterday, back today)
                    last_therapists_for_remaining = None
                    try:
                        from Patient.models import TherapistBooking as _TB
                        therapy_start_date = getattr(allocation, 'from_date', None)
                        if therapy_start_date and allocate_slot:
                            from_start_qs = _TB.objects.filter(
                                visit_id=allocation.id,
                                date__gte=therapy_start_date,
                                date__lt=target_date,
                                time_slot=allocate_slot,
                                status='BOOKED',
                            ).select_related('therapist').order_by('date', 'created_at')
                            assigned_codes = {getattr(t, 'therapist_code', None) for t in assigned_continuity if getattr(t, 'therapist_code', None)}
                            from_start_codes = []
                            seen = set()
                            for tb in from_start_qs:
                                if not tb.therapist:
                                    continue
                                if not getattr(tb.therapist, 'is_active', True):
                                    continue
                                code = getattr(tb.therapist, 'therapist_code', None)
                                if code and code not in seen and code not in assigned_codes:
                                    seen.add(code)
                                    from_start_codes.append(code)
                            if from_start_codes:
                                last_therapists_for_remaining = from_start_codes
                                print(f"[CONTINUITY PASS2] Preferring {len(from_start_codes)} from-start therapist(s) when filling remaining: {from_start_codes}")
                    except Exception as e:
                        print(f"[CONTINUITY PASS2] Error building from-start for remaining: {e}")

                    if preferred_roster_info and preferred_roster_info.get('therapist_codes'):
                        last_therapists_for_remaining = [
                            c for c in preferred_roster_info['therapist_codes']
                            if c not in assigned_codes
                        ]
                        print(f"[PREFERRED ROSTER] Preferring {len(last_therapists_for_remaining)} preferred roster therapist(s) when filling remaining: {last_therapists_for_remaining}")

                    # Treatment omission exclusion: do not prefer any therapist who omitted this treatment
                    if last_therapists_for_remaining:
                        treatment_to_check = remaining_req.get('therapy_code') or remaining_req.get('therapy_name') or therapy_name or getattr(allocation, 'therapy_name', None)
                        if treatment_to_check:
                            from masters.models import is_therapist_omitted_for_treatment
                            last_therapists_for_remaining = [
                                c for c in last_therapists_for_remaining
                                if not is_therapist_omitted_for_treatment(c, treatment_to_check)
                            ]
                    
                    # Build avoid set from continuity therapists so allocate_therapists
                    # does not return them again (their PASS 1 bookings were cancelled by
                    # the cleanup step, so they appear "free" and can be picked as duplicates).
                    continuity_codes_to_avoid = {
                        getattr(t, 'therapist_code', None)
                        for t in assigned_continuity
                        if getattr(t, 'therapist_code', None)
                    }
                    # Allocate remaining therapists (prefer from-start who are available)
                    additional_therapists = allocate_therapists(
                        target_date,
                        allocate_slot,
                        remaining_req,
                        last_therapists=last_therapists_for_remaining,
                        needs_bathing=needs_bath_flag and (result_bath_assigned is None),  # Only if no bathing therapist yet
                        patient_gender=pat_sex,
                        avoid_therapists=continuity_codes_to_avoid if continuity_codes_to_avoid else None,
                        patient_id=pat_reg_id,
                        patient_age=pat_age,
                    )
                    candidate_therapists.extend(additional_therapists)
                    print(f"[CONTINUITY PASS2] Booking {booking.pk}: Added {len(additional_therapists)} additional therapists")
                except Exception as e:
                    print(f"[CONTINUITY PASS2] Error allocating remaining therapists: {e}")
        else:
            # Normal allocation (no PASS 1 continuity assigned)
            try:
                # Pass patient gender & age (Male children below 5 assigned to female therapist)
                pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
                pat_age = getattr(getattr(allocation, 'patient', None), 'pat_age', None)

                # Pass ALL previous therapists to allocate_therapists for maximum continuity
                # allocate_therapists will check availability for each and assign available ones,
                # then fill remaining slots with new therapists
                last_therapists = None
                if preferred_roster_info and preferred_roster_info.get('therapist_codes'):
                    last_therapists = list(preferred_roster_info['therapist_codes'])
                    print(f"[PREFERRED ROSTER] PASS 2 using preferred roster therapists: {last_therapists}")
                elif previous_therapist_group and len(previous_therapist_group) > 0:
                    # Use all previous therapists as last_therapists for maximum continuity
                    last_therapists = [tm.therapist_code for tm in previous_therapist_group]
                    print(f"[DEBUG] Using all previous therapists for maximum continuity: {last_therapists}")
                elif previous_bathing_therapist:
                    # Fallback: Pass previous bathing therapist as last_therapists if no group found
                    last_therapists = [previous_bathing_therapist.therapist_code]
                else:
                    # PASS 2: Check PatientHistory for previous years' therapists if no recent treatment
                    # This helps assign therapists who treated the patient in previous years
                    print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ========== CHECKING PATIENT HISTORY FOR BOOKING {booking_id} ==========")
                    try:
                        patient_obj = getattr(allocation, 'patient', None)
                        if patient_obj:
                            patient_reg_no = getattr(patient_obj, 'pat_reg_no', None)
                            patient_name = getattr(patient_obj, 'pat_name', 'Unknown')
                            if patient_reg_no:
                                print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Patient: {patient_name} (Reg No: {patient_reg_no})")
                                print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Target Date: {target_date}, Slot: {getattr(allocate_slot, 'id', None) if allocate_slot else None}")
                                
                                from Patient.models import PatientHistory, Repeated_Visitors
                                from masters.models import TherapistMaster, TherapistLeaveMaster
                                from Patient.models import TherapistBooking
                                
                                # First check if patient exists in Repeated_Visitors model
                                # Only proceed with PatientHistory check if patient is a repeated visitor
                                is_repeated_visitor = False
                                try:
                                    # Try to convert patient_reg_no to integer for Repeated_Visitors lookup
                                    # Extract digits from patient_reg_no (handles cases like "12345" or "OP-12345")
                                    reg_no_digits = ''.join(ch for ch in str(patient_reg_no) if ch.isdigit())
                                    if reg_no_digits:
                                        reg_no_int = int(reg_no_digits)
                                        is_repeated_visitor = Repeated_Visitors.objects.filter(
                                            register_number=reg_no_int
                                        ).exists()
                                        
                                        if is_repeated_visitor:
                                            repeated_visitor = Repeated_Visitors.objects.filter(
                                                register_number=reg_no_int
                                            ).first()
                                            total_visits = getattr(repeated_visitor, 'total_visits', 0) if repeated_visitor else 0
                                            is_vip = getattr(repeated_visitor, 'is_vip', False) if repeated_visitor else False
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✓ Patient is a REPEATED VISITOR (Total visits: {total_visits}, VIP: {is_vip})")
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Proceeding with PatientHistory check...")
                                        else:
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✗ Patient is NOT a repeated visitor - Skipping PatientHistory check")
                                    else:
                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✗ Could not extract registration number digits - Skipping PatientHistory check")
                                except (ValueError, TypeError) as e:
                                    print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✗ Error checking Repeated_Visitors: {e} - Skipping PatientHistory check")
                                
                                # Only query PatientHistory if patient is a repeated visitor
                                if is_repeated_visitor:
                                    # Query PatientHistory by preg_no (patient registration number)
                                    history_records = PatientHistory.objects.filter(
                                        preg_no=str(patient_reg_no)
                                    ).order_by('-date')
                                    
                                    total_history_count = history_records.count()
                                    print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Found {total_history_count} total history record(s) for patient {patient_reg_no}")
                                    
                                    if history_records.exists():
                                        # Get up to 50 unique dates in most recent order
                                        unique_dates = history_records.values_list('date', flat=True).distinct().order_by('-date')[:50]
                                        
                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Found {len(unique_dates)} unique date(s) in PatientHistory (checking up to 50 most recent)")
                                        
                                        # Check each date in order until we find available therapists
                                        available_history_therapists = []
                                        unavailable_therapists = []
                                        day_of_week = target_date.weekday()
                                        dates_checked = 0
                                        
                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Checking availability for target date {target_date} (day of week: {day_of_week})...")
                                        
                                        for check_date in unique_dates:
                                            dates_checked += 1
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Checking date {dates_checked}/{len(unique_dates)}: {check_date}")
                                            
                                            # Get all history records for this date
                                            date_history = history_records.filter(date=check_date)
                                            
                                            # Get unique therapist codes from this date
                                            therapist_codes_from_date = list(
                                                set([h.therapist_code for h in date_history if h.therapist_code])
                                            )
                                            
                                            if not therapist_codes_from_date:
                                                print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   No therapists found for date {check_date} - checking next date")
                                                continue
                                            
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   Found {len(therapist_codes_from_date)} unique therapist(s) from date {check_date}:")
                                            for idx, tc in enumerate(therapist_codes_from_date, 1):
                                                therapist_name = next((h.therapist_name for h in date_history if h.therapist_code == tc), 'Unknown')
                                                print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]     {idx}. {therapist_name} (Code: {tc})")
                                            
                                            # Check availability for therapists from this date
                                            date_available_therapists = []
                                            
                                            for therapist_code in therapist_codes_from_date:
                                                # Skip if already added from a previous date
                                                if therapist_code in available_history_therapists:
                                                    continue
                                                
                                                try:
                                                    therapist = TherapistMaster.objects.filter(
                                                        therapist_code=therapist_code,
                                                        is_active=True,
                                                        is_helping_therapist=False
                                                    ).first()
                                                    
                                                    if not therapist:
                                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   ✗ Therapist {therapist_code} NOT FOUND or INACTIVE in TherapistMaster - skipping")
                                                        unavailable_therapists.append((therapist_code, "Not found or inactive in TherapistMaster"))
                                                        continue
                                                    
                                                    therapist_name = getattr(therapist, 'therapist_name', 'Unknown')
                                                    print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   Checking therapist: {therapist_name} ({therapist_code})...")
                                                    
                                                    # Check if therapist is available
                                                    # 1. Check weekly leave
                                                    if TherapistLeaveMaster.objects.filter(
                                                        therapist=therapist, 
                                                        leave_day=day_of_week
                                                    ).exists():
                                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   ✗ {therapist_name} ({therapist_code}) is on weekly leave - NOT AVAILABLE")
                                                        unavailable_therapists.append((therapist_code, "On weekly leave"))
                                                        continue

                                                    # 1b. Check deputation & treatment omission
                                                    from masters.models import is_therapist_deputed, is_therapist_omitted_for_treatment
                                                    if is_therapist_deputed(therapist, target_date):
                                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   ✗ {therapist_name} ({therapist_code}) is deputed - NOT AVAILABLE")
                                                        unavailable_therapists.append((therapist_code, "On deputation"))
                                                        continue
                                                    if is_therapist_omitted_for_treatment(therapist, alloc_therapy or current_therapy_name):
                                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   ✗ {therapist_name} ({therapist_code}) has omitted treatment {alloc_therapy or current_therapy_name} - NOT AVAILABLE")
                                                        unavailable_therapists.append((therapist_code, "Treatment omitted"))
                                                        continue
                                                    
                                                    # 2. Check if already booked at this date+time_slot
                                                    if allocate_slot and TherapistBooking.objects.filter(
                                                        therapist=therapist,
                                                        date=target_date,
                                                        time_slot=allocate_slot,
                                                        status='BOOKED'
                                                    ).exists():
                                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   ✗ {therapist_name} ({therapist_code}) already booked at {target_date} slot {getattr(allocate_slot, 'id', None)} - NOT AVAILABLE")
                                                        unavailable_therapists.append((therapist_code, f"Already booked at {target_date} slot {getattr(allocate_slot, 'id', None)}"))
                                                        continue
                                                    
                                                    # 3. Check daily session limit (max 6 sessions)
                                                    # Note: This is in a different context (patient history), so we can't track current run
                                                    # But we should still check the database count
                                                    session_count = TherapistBooking.objects.filter(
                                                        therapist=therapist,
                                                        date=target_date,
                                                        status='BOOKED'
                                                    ).count()
                                                    
                                                    if session_count >= 6:
                                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   ✗ {therapist_name} ({therapist_code}) has reached max sessions ({session_count}/6) - NOT AVAILABLE")
                                                        unavailable_therapists.append((therapist_code, f"Max sessions reached ({session_count}/6)"))
                                                        continue
                                                    
                                                    # Therapist is available
                                                    date_available_therapists.append(therapist_code)
                                                    available_history_therapists.append(therapist_code)
                                                    print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   ✓ {therapist_name} ({therapist_code}) is AVAILABLE (sessions: {session_count}/6) - WILL BE ASSIGNED")
                                                    
                                                except Exception as e:
                                                    print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   ✗ Error checking therapist {therapist_code}: {e}")
                                                    unavailable_therapists.append((therapist_code, f"Error: {str(e)}"))
                                                    continue
                                            
                                            # If we found available therapists from this date, we can stop checking further dates
                                            # (prioritize most recent date's therapists)
                                            if date_available_therapists:
                                                print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✓ Found {len(date_available_therapists)} available therapist(s) from date {check_date} - stopping date check")
                                                break
                                        
                                        # Summary of availability check
                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ========== AVAILABILITY SUMMARY ==========")
                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Dates checked: {dates_checked}/{len(unique_dates)}")
                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Available therapists: {len(available_history_therapists)}")
                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Unavailable therapists: {len(unavailable_therapists)}")
                                        
                                        if unavailable_therapists:
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Unavailable therapist details:")
                                            for tc, reason in unavailable_therapists:
                                                print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   - {tc}: {reason}")
                                        
                                        if available_history_therapists:
                                            last_therapists = available_history_therapists
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ========== ASSIGNMENT RESULT ==========")
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✓ ASSIGNED {len(available_history_therapists)} therapist(s) from PatientHistory as last_therapists (checked {dates_checked} date(s)):")
                                            for idx, tc in enumerate(available_history_therapists, 1):
                                                therapist = TherapistMaster.objects.filter(therapist_code=tc).first()
                                                therapist_name = getattr(therapist, 'therapist_name', 'Unknown') if therapist else 'Unknown'
                                                print(f"[CONTINUITY FROM PATIENT HISTORY MODEL]   {idx}. {therapist_name} ({tc})")
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] These therapists will be preferred in allocation: {available_history_therapists}")
                                        else:
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✗ NO THERAPISTS ASSIGNED - All therapists from {dates_checked} checked date(s) are unavailable")
                                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Allocation will proceed with normal therapist selection")
                                    else:
                                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✗ No history records found for patient {patient_reg_no}")
                                else:
                                    print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ========== END PATIENT HISTORY CHECK (Not a repeated visitor) ==========")
                            else:
                                print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✗ Patient registration number not found")
                        else:
                            print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✗ Patient object not found in allocation")
                    except Exception as e:
                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ✗ ERROR querying PatientHistory: {e}")
                        import traceback
                        print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] Traceback: {traceback.format_exc()}")
                        # Continue with normal allocation if PatientHistory check fails
                    print(f"[CONTINUITY FROM PATIENT HISTORY MODEL] ========== END PATIENT HISTORY CHECK ==========")

                # Determine avoid_therapists for this slot **and same therapy**.
                # We avoid using therapists who are reserved as continuity for OTHER patients
                # for this SAME therapy and slot, but always allow this patient's own continuity therapists.
                avoid_for_slot = None
                if allocate_slot is not None:
                    try:
                        from Sheduling.models import TherapistContinuityPlan

                        current_therapy_name = getattr(allocation, 'therapy_name', None)
                        if current_therapy_name:
                            reserved_qs = TherapistContinuityPlan.objects.filter(
                                date=target_date,
                                time_slot=allocate_slot,
                                therapy_name=current_therapy_name,
                            ).exclude(
                                allocation_id=allocation.id,
                            ).select_related('therapist')

                            reserved_codes = {
                                row.therapist.therapist_code
                                for row in reserved_qs
                                if row.therapist and getattr(row.therapist, 'therapist_code', None)
                            }

                            if reserved_codes:
                                avoid_for_slot = set(reserved_codes)
                                if last_therapists:
                                    for c in last_therapists:
                                        avoid_for_slot.discard(c)
                                if not avoid_for_slot:
                                    avoid_for_slot = None
                    except Exception as e:
                        print(f"[DEBUG ContinuityPlan] Error building avoid_for_slot for therapy continuity: {e}")

                pat_reg_id = getattr(getattr(allocation, 'patient', None), 'pat_reg_no', None) or getattr(allocation, 'patient_id', None)
                candidate_therapists = allocate_therapists(
                    target_date,
                    allocate_slot,
                    therapy_req,
                    last_therapists,
                    needs_bath_flag,
                    patient_gender=pat_sex,
                    avoid_therapists=avoid_for_slot,
                    patient_id=pat_reg_id,
                    patient_age=pat_age,
                )
            except Exception:
                candidate_therapists = []

        req_total = int(therapy_req.get("total", 1) or 1)
        pat_reg_id = getattr(getattr(allocation, 'patient', None), 'pat_reg_no', None) or getattr(allocation, 'patient_id', None)
        from Sheduling.vip_service import is_patient_vip
        is_vip_booking = (
            getattr(booking, 'is_vip', False) or
            getattr(allocation, 'is_vip', False) or
            is_patient_vip(pat_reg_id) or
            is_patient_vip(getattr(allocation, 'patient', None))
        )

        if is_vip_booking and len(candidate_therapists) < req_total:
            print(f"[VIP FAIL-SAFE] Shortage for VIP booking {booking_id} ({len(candidate_therapists)}/{req_total}). Attempting preemption...")
            try:
                conf_tbs = TherapistBooking.objects.filter(
                    date=target_date,
                    time_slot=allocate_slot,
                    status='BOOKED'
                ).select_related('therapist', 'visit')
                for c_tb in conf_tbs:
                    if len(candidate_therapists) >= req_total:
                        break
                    if c_tb.therapist and c_tb.therapist not in candidate_therapists:
                        from Sheduling.preferred_therapist_service import displace_non_vip_therapist_for_slot
                        displace_non_vip_therapist_for_slot(
                            c_tb.therapist, target_date, allocate_slot,
                            exclude_therapist_codes=[getattr(t, 'therapist_code', '') for t in candidate_therapists]
                        )

                candidate_therapists = allocate_therapists(
                    target_date,
                    allocate_slot,
                    therapy_req,
                    last_therapists,
                    needs_bath_flag,
                    patient_gender=pat_sex,
                    avoid_therapists=None,
                    patient_id=pat_reg_id,
                    patient_age=pat_age,
                    allow_helping_fallback=True
                )
            except Exception as e:
                print(f"[VIP FAIL-SAFE] Error during preemption/retry: {e}")

        if len(candidate_therapists) < req_total:
            other_vip_conflict_exists = False
            if is_vip_booking and preferred_roster_info:
                pref_codes = preferred_roster_info.get('therapist_codes', [])
                conf_tbs = TherapistBooking.objects.filter(
                    date=target_date,
                    time_slot=allocate_slot,
                    therapist__therapist_code__in=pref_codes,
                    status='BOOKED'
                ).exclude(visit=allocation)
                if pat_reg_id:
                    if str(pat_reg_id).isdigit():
                        conf_tbs = conf_tbs.exclude(patient_id=int(pat_reg_id))
                    conf_tbs = conf_tbs.exclude(visit__patient__pat_reg_no=str(pat_reg_id))
                for c_tb in conf_tbs:
                    c_pat = getattr(getattr(c_tb, 'visit', None), 'patient', None)
                    if pat_reg_id and (getattr(c_pat, 'pat_reg_no', None) == str(pat_reg_id) or str(c_tb.patient_id) == str(pat_reg_id)):
                        continue
                    from Sheduling.vip_service import is_patient_vip
                    if is_patient_vip(c_pat) or is_patient_vip(c_tb.patient_id):
                        other_vip_conflict_exists = True
                        break

            if other_vip_conflict_exists:
                reason = "Preferred therapist is assigned to another VIP patient at this slot. Change slot to reschedule."
            else:
                reason = "insufficient_therapists_available"
            
            # Check if all therapists have reached max sessions (6)
            try:
                from masters.models import TherapistMaster
                from Patient.models import TherapistBooking
                # Count therapists with 6 sessions on this date
                from django.db.models import Count, Q
                therapists_with_6_sessions = TherapistMaster.objects.filter(is_active=True).annotate(
                    session_count=Count(
                        'therapistbooking',
                        filter=Q(
                            therapistbooking__date=target_date,
                            therapistbooking__status='BOOKED'
                        )
                    )
                ).filter(session_count__gte=6).count()
                
                total_therapists = TherapistMaster.objects.filter(is_active=True).count()
                
                # If all therapists have 6 sessions, show specific error
                if total_therapists > 0 and therapists_with_6_sessions == total_therapists:
                    reason = "therapist_unavailability: All therapists have reached maximum sessions (6) for this day"
            except Exception:
                pass
            
            # Gender availability insight (non-blocking, for debugging/UX)
            try:
                desired_gender = resolve_desired_gender(pat_sex, pat_age)
                def _tg(x):
                    try:
                        # Only check therapist_gender field from TherapistMaster (values: "Male"/"Female")
                        v = getattr(x, 'therapist_gender', None)
                        if v:
                            v_str = str(v).strip()
                            # Handle "Male"/"Female" (capitalized) or "male"/"female" (lowercase)
                            if v_str.lower().startswith('m'):
                                return 'male'
                            if v_str.lower().startswith('f'):
                                return 'female'
                    except Exception:
                        return None
                    return None
                match_count = sum(1 for t in candidate_therapists if (desired_gender is None or _tg(t) == desired_gender))
                # Per-grade availability of matching-gender therapists not on leave/booked
                from masters.models import TherapistMaster, TherapistLeaveMaster
                from Patient.models import TherapistBooking
                day_of_week = target_date.weekday()
                grade_availability = {}
                for grade_key in ("super_senior","senior","junior","trainee"):
                    if int(therapy_req.get(grade_key,0) or 0) > 0:
                        # Match grade text against stored therapist_grade name
                        grade_text = grade_key.replace('_',' ')
                        pool = TherapistMaster.objects.filter(therapist_grade__name__icontains=grade_text, is_active=True)
                        available = 0
                        # Use query_slot (resolved SlotMaster) for exact slot match when checking bookings
                        for t in pool:
                            if desired_gender and _tg(t) != desired_gender:
                                continue
                            if TherapistLeaveMaster.objects.filter(therapist=t, leave_day=day_of_week).exists():
                                continue
                            from masters.models import is_therapist_deputed, is_therapist_omitted_for_treatment
                            if is_therapist_deputed(t, target_date):
                                continue
                            if is_therapist_omitted_for_treatment(t, alloc.therapy_name):
                                continue
                            if TherapistBooking.objects.filter(therapist=t, date=target_date, time_slot=query_slot, status='BOOKED').exists():
                                continue
                            available += 1
                        grade_availability[grade_key] = available
                gender_info = {"required_gender": desired_gender, "available_matching_gender": match_count, "grade_availability": grade_availability}
                # Append concise summary into reason for UI visibility
                try:
                    reason = f"insufficient_therapists_available (required={req_total}, found={len(candidate_therapists)}, gender={desired_gender or 'n/a'})"
                except Exception:
                    pass
            except Exception:
                gender_info = {}
            therapists_for_audit = [therapist_entry(t, False) for t in candidate_therapists]
            # Update booking status to failed
            try:
                try:
                    fail_reason = reason
                except NameError:
                    fail_reason = 'insufficient_therapists_available'
                booking.status = 'failed'
                booking.failure_reason = (str(fail_reason) or '')[:512]
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
            except Exception as e:
                print(f"Error updating booking {booking_id} to failed: {e}")
            
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason,
                        extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id, "therapists": therapists_for_audit, **gender_info}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": therapists_for_audit
            })
            continue

        # STRICT TREATMENT OMISSION FILTER:
        # Exclude any therapist who has an approved omission for this treatment under any circumstances.
        from masters.models import is_therapist_omitted_for_treatment
        treatment_check = therapy_name or getattr(allocation, 'therapy_name', None) or getattr(allocation, 'therapy_code', None)
        if treatment_check:
            candidate_therapists = [
                t for t in candidate_therapists
                if not is_therapist_omitted_for_treatment(t, treatment_check)
            ]

        # choose single bathing-assigned therapist if bathing required
        assigned_therapists = candidate_therapists[:req_total]
        print(f"[CONTINUITY PASS2] assigned_therapists set to {len(assigned_therapists)} therapists from candidate_therapists (req_total={req_total})")
        print(f"[CONTINUITY PASS2]   assigned_therapists: {[getattr(t, 'therapist_code', 'UNKNOWN') for t in assigned_therapists]}")

        # De-duplicate assigned_therapists by therapist_code to avoid counting the same therapist twice
        # This prevents scenarios where we think we have N therapists but only N-1 unique assignments.
        seen_codes = set()
        deduped_assigned = []
        for t in assigned_therapists:
            code = getattr(t, 'therapist_code', None)
            key = code or id(t)
            if key in seen_codes:
                print(f"[CONTINUITY PASS2] ⚠ Duplicate therapist in assigned_therapists list: {code} - removing duplicate")
                continue
            seen_codes.add(key)
            deduped_assigned.append(t)
        if len(deduped_assigned) != len(assigned_therapists):
            print(f"[CONTINUITY PASS2] Deduplicated assigned_therapists from {len(assigned_therapists)} to {len(deduped_assigned)} based on therapist_code")
        assigned_therapists = deduped_assigned

        # If after de-duplication we have fewer therapists than required, treat as insufficient therapists
        # and expose the same style of message as the earlier insufficient_therapists_available branch.
        if len(assigned_therapists) < req_total:
            unique_count = len(assigned_therapists)
            other_vip_conflict_exists = False
            if is_vip_booking and preferred_roster_info:
                pref_codes = preferred_roster_info.get('therapist_codes', [])
                conf_tbs = TherapistBooking.objects.filter(
                    date=target_date,
                    time_slot=allocate_slot,
                    therapist__therapist_code__in=pref_codes,
                    status='BOOKED'
                ).exclude(visit=allocation)
                if pat_reg_id:
                    if str(pat_reg_id).isdigit():
                        conf_tbs = conf_tbs.exclude(patient_id=int(pat_reg_id))
                    conf_tbs = conf_tbs.exclude(visit__patient__pat_reg_no=str(pat_reg_id))
                for c_tb in conf_tbs:
                    c_pat = getattr(getattr(c_tb, 'visit', None), 'patient', None)
                    if pat_reg_id and (getattr(c_pat, 'pat_reg_no', None) == str(pat_reg_id) or str(c_tb.patient_id) == str(pat_reg_id)):
                        continue
                    from Sheduling.vip_service import is_patient_vip
                    if is_patient_vip(c_pat) or is_patient_vip(c_tb.patient_id):
                        other_vip_conflict_exists = True
                        break

            if other_vip_conflict_exists:
                reason = "Preferred therapist is assigned to another VIP patient at this slot. Change slot to reschedule."
            else:
                pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
                pat_age = getattr(getattr(allocation, 'patient', None), 'pat_age', None)
                desired_gender = resolve_desired_gender(pat_sex, pat_age) if (pat_sex or pat_age) else 'n/a'
                reason = f"insufficient_therapists_available (required={req_total}, found={unique_count}, gender={desired_gender})"
                print(f"[CONTINUITY PASS2] ❌ Not enough unique therapists after de-duplication: required={req_total}, unique={unique_count}")
                try:
                    booking.status = 'failed'
                    booking.failure_reason = (reason or '')[:512]
                    booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                    print(f"[CONTINUITY PASS2] Booking {booking_id} marked as failed (user message): {reason}")
                except Exception as e:
                    print(f"[CONTINUITY PASS2] Could not update booking status: {e}")
                if AllocationAttempt:
                    try:
                        AllocationAttempt.objects.create(
                            visit=None, therapy=None, date=target_date,
                            requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                            status='FAILED', reason=reason,
                            extra={"booking_id": booking_id, "therapists": [therapist_entry(t, False) for t in assigned_therapists]}
                        )
                    except Exception:
                        pass
                tasks.append({
                    "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                    "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                    "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None,
                    "therapists": [therapist_entry(t, False) for t in assigned_therapists]
                })
                continue

        bath_assigned = None
        
        # Initialize variables to store booking status info (will be set inside transaction)
        booking_expected_ba_count = len(assigned_therapists)
        booking_actual_ba_count = 0
        booking_ba_success_count = 0
        booking_ba_errors = []
        booking_needs_scheduled = False
        booking_failure_reason = None
        
        # Use bath_assigned and senior_therapist from PASS 1 if provided
        bath_assigned_from_pass1 = None
        if continuity_assigned and isinstance(continuity_assigned, dict):
            bath_assigned_from_pass1 = continuity_assigned.get('bath_assigned', None)
            bath_assigned = bath_assigned_from_pass1
            senior_therapist = continuity_assigned.get('senior_therapist', None)
            requires_senior_tag = is_treatment_requiring_senior_tag(therapy_name) and (senior_therapist is not None)
            
            # CRITICAL VALIDATION: For special treatments, bathing and senior therapists MUST be different
            # Priority: Maintain bathing therapist continuity, reassign senior tag to different senior
            if requires_senior_tag and bath_assigned and senior_therapist:
                if bath_assigned == senior_therapist:
                    print(f"[CONTINUITY PASS2] ⚠ PASS 1 assigned same therapist as both bathing and senior: {bath_assigned.therapist_code}")
                    print(f"[CONTINUITY PASS2] Fixing: Keeping bathing therapist {bath_assigned.therapist_code} (maintain continuity), will reassign senior tag to different senior")
                    # Clear senior assignment - will be reassigned below to a different senior
                    senior_therapist = None
                    requires_senior_tag = is_treatment_requiring_senior_tag(therapy_name)  # Re-enable senior tag requirement
            
            print(f"[CONTINUITY PASS2] PASS 1 provided: bath_assigned={bath_assigned.therapist_code if bath_assigned else None}, senior_therapist={senior_therapist.therapist_code if senior_therapist else None}")
            print(f"[CONTINUITY PASS2] Previous bathing therapist: {previous_bathing_therapist.therapist_code if previous_bathing_therapist else None}")
            print(f"[CONTINUITY PASS2] Previous bathing therapist in assigned_therapists: {previous_bathing_therapist in assigned_therapists if previous_bathing_therapist else False}")
        else:
            # Check if this treatment requires special senior therapist handling
            requires_senior_tag = is_treatment_requiring_senior_tag(therapy_name)
            senior_therapist = None
        
        # For special treatments: identify a senior therapist with available senior-tag capacity
        if requires_senior_tag:
            senior_candidates = []
            for t in assigned_therapists:
                grade_name = getattr(getattr(t, 'therapist_grade', None), 'name', '') if hasattr(t, 'therapist_grade') else ''
                if 'Senior' in grade_name:
                    senior_candidates.append((t, grade_name))
            if senior_candidates:
                from math import inf
                best = None
                best_count = inf
                for t, grade_name in senior_candidates:
                    current = get_senior_tag_count_for_therapist(t, target_date)
                    # Prefer therapists below the limit of 2; among them pick the one with fewest senior tags
                    if current < 2 and current < best_count:
                        best = t
                        best_count = current
                if best is not None:
                    senior_therapist = best
                    print(f"[DEBUG] Senior tag: selected senior {best.therapist_code} with existing senior-tag count={best_count} on {target_date}")
                else:
                    # All potential seniors are already at or above the limit -> no senior tag for this booking
                    requires_senior_tag = False
                    print(f"[DEBUG] Senior tag: no available senior below daily limit for {therapy_name} on {target_date}")
        
        # If bathing is required, we MUST have a bathing therapist assigned
        if needs_bath_flag:
            if not assigned_therapists:
                # No therapists assigned at all - this should have been caught earlier, but fail anyway
                reason = "bathing_therapist_unavailable: No therapists available for bathing therapy"
                print(f"[DEBUG] FAILING allocation: Therapy requires bathing but no therapists assigned. Patient: {patient_id}, Date: {target_date}")
                
                try:
                    booking.status = 'failed'
                    booking.failure_reason = (str(reason) or '')[:512]
                    booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                except Exception as e:
                    print(f"Error updating booking {booking_id} to failed: {e}")
                
                therapists_for_audit = []
                if AllocationAttempt:
                    try:
                        AllocationAttempt.objects.create(
                            visit=None, therapy=None, date=target_date,
                            requested_time_slot=allocate_slot, requested_time_slot_value=requested_slot_value or '',
                            status='FAILED', reason=reason,
                            extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id, "therapists": therapists_for_audit, "bathing_required": True}
                        )
                    except Exception:
                        pass
                tasks.append({
                    "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                    "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                    "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": therapists_for_audit
                })
                continue  # Skip to next booking
            
            # For special treatments: Senior therapist should NOT be the bathing therapist
            # Priority: Maintain bathing therapist continuity (previous bathing therapist should stay as bathing)
            if requires_senior_tag and senior_therapist:
                # PREFERRED ROSTER: Priority for roster's designated bathing therapist
                roster_bath = None
                if preferred_roster_info and needs_bath_flag:
                    try:
                        from Sheduling.preferred_therapist_service import pick_bathing_therapist_from_roster
                        roster_bath, _ = pick_bathing_therapist_from_roster(preferred_roster_info, target_date, slot_master or allocate_slot, exclude_visit_id=allocation.id)
                    except Exception:
                        roster_bath = None

                preferred_bathing_therapist = None
                if bath_assigned_from_pass1 and bath_assigned_from_pass1 in assigned_therapists:
                    preferred_bathing_therapist = bath_assigned_from_pass1
                elif roster_bath and roster_bath in assigned_therapists:
                    preferred_bathing_therapist = roster_bath
                    print(f"[DEBUG] Special treatment: Using designated preferred roster bathing therapist {preferred_bathing_therapist.therapist_code}")
                elif previous_bathing_therapist and previous_bathing_therapist in assigned_therapists:
                    preferred_bathing_therapist = previous_bathing_therapist
                
                if preferred_bathing_therapist:
                    if preferred_bathing_therapist != senior_therapist:
                        # Preferred bathing therapist is available and different from senior - use them (maintain continuity)
                        bath_assigned = preferred_bathing_therapist
                        print(f"[DEBUG] Dhara & Pizichil: Using preferred bathing therapist {preferred_bathing_therapist.therapist_code} (maintaining continuity, senior {senior_therapist.therapist_code} is different)")
                    else:
                        # Preferred bathing therapist IS the senior - reassign senior tag to different senior
                        print(f"[DEBUG] Dhara & Pizichil: Preferred bathing therapist {preferred_bathing_therapist.therapist_code} IS the senior - reassigning senior tag to different senior")
                        bath_assigned = preferred_bathing_therapist
                        senior_candidates = [t for t in assigned_therapists if t != bath_assigned and 'Senior' in getattr(getattr(t, 'therapist_grade', None), 'name', '')]
                        if senior_candidates:
                            from math import inf
                            best = None
                            best_count = inf
                            for t in senior_candidates:
                                current = get_senior_tag_count_for_therapist(t, target_date)
                                if current < 2 and current < best_count:
                                    best = t
                                    best_count = current
                            if best:
                                senior_therapist = best
                                print(f"[DEBUG] Dhara & Pizichil: Reassigned senior tag to {best.therapist_code} (bathing {bath_assigned.therapist_code} maintained)")
                        else:
                            print(f"[DEBUG] Dhara & Pizichil: No alternative senior available - keeping senior tag on {senior_therapist.therapist_code} (same as bathing)")
                else:
                    # No preferred bathing therapist available - exclude senior from bathing assignment
                    # But first check if previous_bathing_therapist exists but wasn't in assigned_therapists
                    if (bath_assigned_from_pass1 or previous_bathing_therapist) and (bath_assigned_from_pass1 not in assigned_therapists if bath_assigned_from_pass1 else True) and (previous_bathing_therapist not in assigned_therapists if previous_bathing_therapist else True):
                        missing_therapist = bath_assigned_from_pass1 if bath_assigned_from_pass1 else previous_bathing_therapist
                        print(f"[DEBUG] Dhara & Pizichil: ⚠ Preferred bathing therapist {missing_therapist.therapist_code if missing_therapist else 'None'} not in assigned_therapists - may have been filtered out")
                    
                    bathing_candidates = [t for t in assigned_therapists if t != senior_therapist and getattr(t, 'is_bathing_therapist', False)]
                    if bathing_candidates:
                        bathing_candidates.sort(key=lambda t: 0 if not ('Senior' in getattr(getattr(t, 'therapist_grade', None), 'name', '')) else 1)
                        bath_assigned = bathing_candidates[0]
                        print(f"[DEBUG] Dhara & Pizichil: Assigned bathing therapist {bath_assigned.therapist_code} (senior {senior_therapist.therapist_code} excluded, preferred {bath_assigned_from_pass1.therapist_code if bath_assigned_from_pass1 else previous_bathing_therapist.therapist_code if previous_bathing_therapist else 'None'} not available)")
                    else:
                        # No bathing therapist available except senior - need to find another senior or fail
                        print(f"[DEBUG] Dhara & Pizichil: Senior {senior_therapist.therapist_code} is the only bathing therapist. Looking for alternative senior...")
                        from masters.models import TherapistMaster
                        from Patient.models import TherapistBooking
                        day_of_week = target_date.weekday()
                        
                        alternative_seniors = TherapistMaster.objects.filter(
                            therapist_grade__name__in=['Senior Therapist', 'Super Senior Therapist'],
                            is_active=True
                        ).exclude(
                            therapist_code=senior_therapist.therapist_code
                        )
                        
                        # Filter by gender if needed (Rule: Male children below 5 assigned to female therapist)
                        pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
                        pat_age = getattr(getattr(allocation, 'patient', None), 'pat_age', None)
                        desired_gender = resolve_desired_gender(pat_sex, pat_age)
                        alternative_seniors = alternative_seniors.filter(therapist_gender__istartswith=desired_gender[0])
                        
                        # Filter by bathing therapist requirement
                        alternative_seniors = alternative_seniors.filter(is_bathing_therapist=True)
                        
                        # Exclude those on leave or booked
                        for alt_senior in alternative_seniors:
                            if TherapistBooking.objects.filter(therapist=alt_senior, date=target_date, time_slot=allocate_slot, status='BOOKED').exists():
                                continue
                            if TherapistLeaveMaster.objects.filter(therapist=alt_senior, leave_day=day_of_week).exists():
                                continue
                            from masters.models import is_therapist_on_emergency_leave, is_therapist_deputed, is_therapist_omitted_for_treatment
                            if is_therapist_on_emergency_leave(alt_senior, target_date, allocate_slot):
                                continue
                            if is_therapist_deputed(alt_senior, target_date):
                                continue
                            if is_therapist_omitted_for_treatment(alt_senior, alloc.therapy_name):
                                continue
                            
                            # Found alternative senior - replace current senior and use this one for bathing
                            print(f"[DEBUG] Dhara & Pizichil: Found alternative senior {alt_senior.therapist_code} who can be bathing therapist")
                            assigned_therapists = [alt_senior if t == senior_therapist else t for t in assigned_therapists]
                            senior_therapist = alt_senior
                            bath_assigned = alt_senior
                            break
                        
                        if not bath_assigned:
                            if is_vip_booking and assigned_therapists:
                                bath_assigned = assigned_therapists[0]
                                print(f"[VIP FAIL-SAFE] Designated {bath_assigned.therapist_code} as bathing therapist for VIP {patient_id}")
                            else:
                                # No alternative senior found - fail allocation
                                reason = "bathing_therapist_unavailable: Senior therapist for Dhara & Pizichil cannot be bathing therapist, and no alternative senior available"
                                print(f"[DEBUG] FAILING allocation: Dhara & Pizichil - Senior {senior_therapist.therapist_code} is only bathing therapist and no alternative found. Patient: {patient_id}, Date: {target_date}")
                                
                                try:
                                    booking.status = 'failed'
                                    booking.failure_reason = (str(reason) or '')[:512]
                                    booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                                except Exception as e:
                                    print(f"Error updating booking {booking_id} to failed: {e}")
                                
                                therapists_for_audit = [therapist_entry(t, False) for t in assigned_therapists]
                                if AllocationAttempt:
                                    try:
                                        AllocationAttempt.objects.create(
                                            visit=None, therapy=None, date=target_date,
                                            requested_time_slot=allocate_slot, requested_time_slot_value=requested_slot_value or '',
                                            status='FAILED', reason=reason,
                                            extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id, "therapists": therapists_for_audit, "bathing_required": True, "senior_therapist": senior_therapist.therapist_code if senior_therapist else None}
                                        )
                                    except Exception:
                                        pass
                                tasks.append({
                                    "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                                    "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                                    "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": therapists_for_audit
                                })
                                continue  # Skip to next booking
            else:
                # Not Dhara & Pizichil or no senior therapist - use normal logic
                # PREFERRED ROSTER: Always designate preferred roster's bathing therapist if in assigned list
                roster_bath = None
                if preferred_roster_info and needs_bath_flag:
                    try:
                        from Sheduling.preferred_therapist_service import pick_bathing_therapist_from_roster
                        roster_bath, _ = pick_bathing_therapist_from_roster(preferred_roster_info, target_date, slot_master or allocate_slot, exclude_visit_id=allocation.id)
                    except Exception:
                        roster_bath = None

                if bath_assigned_from_pass1 and bath_assigned_from_pass1 in assigned_therapists:
                    # PASS 1 chose the first-day bathing therapist (or designated from roster) - keep them
                    bath_assigned = bath_assigned_from_pass1
                    print(f"[DEBUG] ✓ Using PASS 1 bathing therapist {bath_assigned.therapist_code} for patient {patient_id} (first-day continuity)")
                elif roster_bath and roster_bath in assigned_therapists:
                    bath_assigned = roster_bath
                    print(f"[FINAL_ALLOC] ✓ Using designated preferred roster bathing therapist: {bath_assigned.therapist_code} for patient {patient_id}")
                elif previous_bathing_therapist and previous_bathing_therapist in assigned_therapists:
                    # Fallback: previous day's bathing therapist (e.g. when PASS 1 didn't assign or that therapist not in list)
                    if bath_assigned != previous_bathing_therapist:
                        print(f"[DEBUG] Using previous bathing therapist {previous_bathing_therapist.therapist_code} (PASS 1 therapist not in assigned list)")
                    bath_assigned = previous_bathing_therapist
                    print(f"[DEBUG] ✓ Using previous bathing therapist {previous_bathing_therapist.therapist_code} for patient {patient_id} (maintaining continuity)")
                else:
                    # PASS 1 / previous bathing therapist not in assigned_therapists (e.g. cancelled,
                    # on leave, or at max sessions). Reset stale bath_assigned and pick from actual list.
                    if bath_assigned and bath_assigned not in assigned_therapists:
                        print(f"[DEBUG] ⚠ PASS 1 bathing therapist {getattr(bath_assigned, 'therapist_code', '?')} is NOT in assigned_therapists - resetting to pick from assigned list")
                        bath_assigned = None
                    if not bath_assigned:
                        for t in assigned_therapists:
                            if getattr(t, 'is_bathing_therapist', False):
                                bath_assigned = t
                                print(f"[DEBUG] Assigned bathing therapist {bath_assigned.therapist_code} (no previous or PASS 1 therapist available)")
                                break
                        if bath_assigned:
                            print(f"[DEBUG] Using first assigned therapist {bath_assigned.therapist_code} for patient {patient_id} (no continuity available)")
                
                if not bath_assigned:
                    # Find any bathing therapist from assigned list
                    bath_assigned = next((t for t in assigned_therapists if getattr(t, 'is_bathing_therapist', False)), None)
                    if bath_assigned:
                        print(f"[DEBUG] Found bathing therapist {bath_assigned.therapist_code} from assigned list for patient {patient_id}")
                    
                    # If no bathing therapist available in assigned list, FAIL the allocation
                    if not bath_assigned:
                        if is_vip_booking and assigned_therapists:
                            bath_assigned = assigned_therapists[0]
                            print(f"[VIP FAIL-SAFE] Designated {bath_assigned.therapist_code} as bathing therapist for VIP patient {patient_id}")
                        else:
                            reason = "bathing_therapist_unavailable: No bathing therapist available for this therapy"
                            print(f"[DEBUG] FAILING allocation: Therapy requires bathing but no bathing therapist available. Patient: {patient_id}, Date: {target_date}")
                            
                            # Update booking status to failed
                            try:
                                booking.status = 'failed'
                                booking.failure_reason = (str(reason) or '')[:512]
                                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                            except Exception as e:
                                print(f"Error updating booking {booking_id} to failed: {e}")
                            
                            therapists_for_audit = [therapist_entry(t, False) for t in assigned_therapists]
                            if AllocationAttempt:
                                try:
                                    AllocationAttempt.objects.create(
                                        visit=None, therapy=None, date=target_date,
                                        requested_time_slot=allocate_slot, requested_time_slot_value=requested_slot_value or '',
                                        status='FAILED', reason=reason,
                                        extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id, "therapists": therapists_for_audit, "bathing_required": True}
                                    )
                                except Exception:
                                    pass
                            tasks.append({
                                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": therapists_for_audit
                            })
                            continue  # Skip to next booking
        
        # FINAL SAFETY CHECK: Ensure bath_assigned is actually in assigned_therapists.
        # Prevents the scenario where PASS 1 set bath_assigned to a therapist that
        # ended up NOT being in the final assigned list (e.g. cancelled, on leave,
        # at max sessions), which would cause all bookings to have is_bathing=False.
        if needs_bath_flag and bath_assigned and bath_assigned not in assigned_therapists:
            print(f"[FINAL_ALLOC] ⚠ SAFETY: bath_assigned {getattr(bath_assigned, 'therapist_code', '?')} is NOT in assigned_therapists! Picking replacement from assigned list.")
            bath_assigned = next((t for t in assigned_therapists if getattr(t, 'is_bathing_therapist', False)), None)
            if bath_assigned:
                print(f"[FINAL_ALLOC] ✓ SAFETY: Replaced with {bath_assigned.therapist_code} from assigned list")
            else:
                print(f"[FINAL_ALLOC] ⚠ SAFETY: No bathing therapist in assigned list - bath_assigned remains None")

        # Determine number of bathing therapists required
        req_bathing_count = getattr(booking, 'bathing_therapists_count', 0) or getattr(allocation, 'bathing_therapists_count', 0) or 0
        num_bathing_required = req_bathing_count if req_bathing_count > 0 else (1 if needs_bath_flag else 0)
        bath_assigned_set = set()
        if num_bathing_required > 0:
            if bath_assigned and bath_assigned in assigned_therapists:
                bath_assigned_set.add(bath_assigned)
            for t in assigned_therapists:
                if len(bath_assigned_set) >= num_bathing_required:
                    break
                if getattr(t, 'is_bathing_therapist', False):
                    bath_assigned_set.add(t)
            for t in assigned_therapists:
                if len(bath_assigned_set) >= num_bathing_required:
                    break
                bath_assigned_set.add(t)

        # build therapist audit list - mark senior therapist for special treatments
        therapists_for_audit = []
        for t in assigned_therapists:
            is_bath = (t in bath_assigned_set)
            # Only mark senior therapist if it's a special treatment AND the therapist is not bathing
            is_senior = (requires_senior_tag and t == senior_therapist and not is_bath)
            therapist_dict = therapist_entry(t, is_bath=is_bath)
            if is_senior:
                therapist_dict["is_senior"] = True  # Mark senior therapist for UI highlighting
            therapists_for_audit.append(therapist_dict)
        # room allocation - use slot_master if available, otherwise canonical_slot
        if not slot_master:
            # If we couldn't resolve slot_master earlier, try one more time before room allocation
            if canonical_slot and not isinstance(canonical_slot, SlotMaster):
                slot_time = getattr(canonical_slot, 'slot_time', None)
                if slot_time:
                    slot_master = SlotMaster.objects.filter(slot_time=slot_time, is_active=True).first()
        allocate_slot_for_room = slot_master if slot_master else canonical_slot
        
        room_candidate = getattr(booking, 'room', None)
        is_wc = False
        if allocation and getattr(allocation, 'is_wheelchair', False):
            is_wc = True
        elif booking and getattr(booking, 'is_wheelchair', False):
            is_wc = True

        if needs_room_flag and not room_candidate:
            try:
                room_candidate = allocate_treatment_room(
                    target_date, 
                    allocate_slot_for_room, 
                    None,
                    therapy_name=therapy_name,
                    patient_id=patient_id,
                    patient_staying_room=patient_staying_room,
                    patient=allocation.patient if allocation and hasattr(allocation, 'patient') else None,
                    is_wheelchair=is_wc,
                    booking_id=booking_id,
                )
            except Exception:
                room_candidate = None
        if needs_room_flag and not room_candidate:
            # Build detailed error message based on patient staying room or OP status
            reason = "no_room_available"
            from allocation_engine.rules import is_steam_therapy_treatment, get_steam_therapy_rooms, is_vamanam_treatment, get_vamanam_treatment_rooms
            if is_wc:
                reason = "no_room_available: No wheelchair accessible treatment room available"
            elif is_steam_therapy_treatment(therapy_name):
                steam_rooms = get_steam_therapy_rooms()
                reason = f"no_room_available: All steam therapy rooms ({', '.join(steam_rooms)}) are not available"
            elif is_vamanam_treatment(therapy_name):
                v_rooms = get_vamanam_treatment_rooms()
                if v_rooms:
                    reason = f"no_room_available: All Vamanam treatment rooms ({', '.join(v_rooms)}) are not available"
                else:
                    reason = "no_room_available: No Vamanam treatment rooms configured in Room Master"
            elif patient_staying_room:
                staying_room_upper = str(patient_staying_room).strip().upper()
                # Check if it's an OP- prefix (not a real staying room)
                if staying_room_upper.startswith('OP-'):
                    # This is an OP patient identifier, not a real staying room
                    # Check if OP patient has CT room
                    if allocation and hasattr(allocation, 'patient') and allocation.patient:
                        try:
                            is_op = False
                            if hasattr(allocation.patient, 'is_op'):
                                is_op = allocation.patient.is_op()
                            elif hasattr(allocation.patient, 'pat_reg_no'):
                                digits = ''.join(ch for ch in str(allocation.patient.pat_reg_no or '') if ch.isdigit())
                                is_op = len(digits) == 5
                            
                            if is_op:
                                # Check if OP patient has CT room from pat_room_no
                                op_room = getattr(allocation.patient, 'pat_room_no', None)
                                if op_room and str(op_room).strip().upper().startswith('CT'):
                                    import re
                                    match = re.match(r'CT-?(\d+)', str(op_room).strip().upper())
                                    if match:
                                        ct_num = match.group(1)
                                        reason = f"no_room_available: Treatment room TRC-{ct_num} for OP patient with CT room CT-{ct_num} is not available"
                                    else:
                                        reason = "no_room_available: No treatment room available for OP patient with CT room"
                                else:
                                    reason = "no_room_available: No treatment room available for OP patient (TR-1 to TR-16)"
                        except Exception:
                            reason = "no_room_available: No treatment room available for OP patient (TR-1 to TR-16)"
                else:
                    # Real staying room - check treatment room assignment
                    treatment_rooms = get_treatment_rooms_for_staying_room(patient_staying_room)
                    if treatment_rooms:
                        rooms_list = ', '.join(treatment_rooms)
                        reason = f"no_room_available: Treatment rooms assigned for staying room {patient_staying_room} ({rooms_list}) are not available"
                    else:
                        reason = f"no_room_available: No treatment room assignment rule found for staying room {patient_staying_room}"
            elif allocation and hasattr(allocation, 'patient') and allocation.patient:
                # Check if OP patient
                try:
                    is_op = False
                    if hasattr(allocation.patient, 'is_op'):
                        is_op = allocation.patient.is_op()
                    elif hasattr(allocation.patient, 'pat_reg_no'):
                        digits = ''.join(ch for ch in str(allocation.patient.pat_reg_no or '') if ch.isdigit())
                        is_op = len(digits) == 5
                    
                    if is_op:
                        # Check if OP patient has CT room
                        op_room = getattr(allocation.patient, 'pat_room_no', None)
                        if op_room and str(op_room).strip().upper().startswith('CT'):
                            import re
                            match = re.match(r'CT-?(\d+)', str(op_room).strip().upper())
                            if match:
                                ct_num = match.group(1)
                                reason = f"no_room_available: Treatment room TRC-{ct_num} for OP patient staying room CT-{ct_num} is not available"
                            else:
                                reason = "no_room_available: No treatment room available for OP patient with CT room"
                        else:
                            reason = "no_room_available: No treatment room available for OP patient (TR-1 to TR-16)"
                except Exception:
                    pass
            elif is_dhara_pizhichil_treatment(therapy_name=therapy_name):
                prev_room = get_dhara_pizhichil_assigned_room(patient_id=patient_id, patient=getattr(allocation, 'patient', None))
                if prev_room:
                    reason = f"previous_room_unavailable: Original Dhara & Pizhichil room {prev_room.room_no} is unavailable at this slot"
                else:
                    reason = "no_room_available: No suitable room available for Dhara & Pizhichil treatment"
            # Update booking status to failed
            try:
                try:
                    fail_reason = reason
                except NameError:
                    fail_reason = 'allocation_failed'
                reason = fail_reason
                booking.status = 'failed'
                booking.failure_reason = (str(fail_reason) or '')[:512]
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
            except Exception as e:
                print(f"Error updating booking {booking_id} to failed: {e}")
            
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason, extra={"booking_id": booking_id, "therapists": therapists_for_audit}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": None, "therapists": therapists_for_audit
            })
            continue
        # create bookings atomically and persist is_bathing on therapist bookings
        booking_saved_successfully = False
        try:
            with transaction.atomic():
                # Catch IntegrityError during transaction operations
                try:
                    # slot_master should already be resolved earlier, but validate it here
                    # This ensures booking.timeslot is set correctly before any FK references are created
                    from masters.models import SlotMaster
                    print(f"[DEBUG] Validating slot_master in transaction. slot_master type: {type(slot_master)}, pk={slot_master.pk if slot_master else None}")
                    
                    # Validate slot_master exists before proceeding
                    if not slot_master:
                        raise RuntimeError(f"no_slot_master: Cannot proceed without SlotMaster - should have been resolved earlier")
                    if not isinstance(slot_master, SlotMaster):
                        raise RuntimeError(f"slot_master_wrong_type: slot_master is {type(slot_master)}, expected SlotMaster")
                    if not SlotMaster.objects.filter(pk=slot_master.pk).exists():
                        raise RuntimeError(f"slot_master_not_found: SlotMaster {slot_master.pk} does not exist in database")
                    
                    # CRITICAL: Check for room/date/timeslot conflicts BEFORE saving
                    # The unique constraint prevents double-booking of the same room at the same time
                    from Sheduling.models import Booking as BookingModel
                    if room_candidate:
                        existing_booking = BookingModel.objects.filter(
                            room=room_candidate,
                            date=target_date,
                            timeslot=slot_master
                        ).exclude(pk=booking.pk).first()
                        
                        if existing_booking:
                            from allocation_engine.rules import is_steam_therapy_treatment, get_steam_therapy_rooms, is_vamanam_treatment, get_vamanam_treatment_rooms
                            if is_steam_therapy_treatment(therapy_name):
                                current_room_no = getattr(room_candidate, 'room_no', None)
                                steam_rooms = get_steam_therapy_rooms()
                                alt_steam_rooms = [r for r in steam_rooms if r != current_room_no]
                                from Patient.models import TreatmentRoom
                                alt_found = False
                                for alt_steam_room_no in alt_steam_rooms:
                                    alt_room_obj = TreatmentRoom.objects.filter(room_no=alt_steam_room_no, is_active=True).first()
                                    if alt_room_obj:
                                        alt_conflict = BookingModel.objects.filter(
                                            room=alt_room_obj,
                                            date=target_date,
                                            timeslot=slot_master
                                        ).exclude(pk=booking.pk).first()
                                        if not alt_conflict:
                                            room_candidate = alt_room_obj
                                            print(f"[DEBUG] Using alternative steam room: {alt_room_obj.room_no}")
                                            alt_found = True
                                            break
                                if not alt_found:
                                    raise RuntimeError(f"no_room_available: All steam therapy rooms ({', '.join(steam_rooms)}) are booked on {target_date} at {slot_master}")
                            elif is_vamanam_treatment(therapy_name):
                                current_room_no = getattr(room_candidate, 'room_no', None)
                                v_rooms = get_vamanam_treatment_rooms()
                                alt_v_rooms = [r for r in v_rooms if r != current_room_no]
                                from Patient.models import TreatmentRoom
                                alt_found = False
                                for alt_v_room_no in alt_v_rooms:
                                    alt_room_obj = TreatmentRoom.objects.filter(room_no=alt_v_room_no, is_active=True).first()
                                    if alt_room_obj:
                                        alt_conflict = BookingModel.objects.filter(
                                            room=alt_room_obj,
                                            date=target_date,
                                            timeslot=slot_master
                                        ).exclude(pk=booking.pk).first()
                                        if not alt_conflict:
                                            room_candidate = alt_room_obj
                                            print(f"[DEBUG] Using alternative Vamanam room: {alt_room_obj.room_no}")
                                            alt_found = True
                                            break
                                if not alt_found:
                                    raise RuntimeError(f"no_room_available: All Vamanam treatment rooms ({', '.join(v_rooms)}) are booked on {target_date} at {slot_master}")
                            elif is_dhara_pizhichil_treatment(therapy_name=therapy_name, therapy_code=getattr(allocation, 'therapy_code', None)):
                                locked_room = get_dhara_pizhichil_assigned_room(
                                    patient_id=patient_id,
                                    patient=allocation.patient if allocation and hasattr(allocation, 'patient') else None,
                                    allocation=allocation,
                                )
                                if locked_room and room_candidate and locked_room.room_no == room_candidate.room_no:
                                    raise RuntimeError(
                                        f"previous_room_unavailable: Original Dhara & Pizhichil room {locked_room.room_no} is unavailable on {target_date} at {slot_master}"
                                    )
                                print(f"[DEBUG] Room {room_candidate.room_no} already booked for {target_date} at {slot_master}, trying alternative room...")
                            else:
                                print(f"[DEBUG] Room {room_candidate.room_no} already booked for {target_date} at {slot_master}, trying alternative room...")
                            alternative_room = allocate_treatment_room(
                                target_date, 
                                slot_master, 
                                getattr(room_candidate, 'room_no', None),
                                therapy_name=therapy_name,
                                patient_id=patient_id,
                                patient_staying_room=patient_staying_room,
                                patient=allocation.patient if allocation and hasattr(allocation, 'patient') else None,
                                is_wheelchair=is_wc,
                                booking_id=booking_id,
                            )
                            if alternative_room and alternative_room != room_candidate:
                                # Check if alternative room is also booked
                                alt_conflict = BookingModel.objects.filter(
                                    room=alternative_room,
                                    date=target_date,
                                    timeslot=slot_master
                                ).exclude(pk=booking.pk).first()
                                if not alt_conflict:
                                    room_candidate = alternative_room
                                    print(f"[DEBUG] Using alternative room: {alternative_room.room_no}")
                                else:
                                    # Try any available room (last resort)
                                    from Patient.models import TreatmentRoom
                                    all_rooms = TreatmentRoom.objects.all()
                                    found_room = None
                                    for room in all_rooms:
                                        if room == room_candidate or room == alternative_room:
                                            continue
                                        if is_wc and not getattr(room, 'is_wheelchair_accessible', False):
                                            continue
                                        room_conflict = BookingModel.objects.filter(
                                            room=room,
                                            date=target_date,
                                            timeslot=slot_master
                                        ).exclude(pk=booking.pk).first()
                                        if not room_conflict:
                                            found_room = room
                                            print(f"[DEBUG] Using fallback room: {room.room_no}")
                                            break
                                    if found_room:
                                        room_candidate = found_room
                                    else:
                                        raise RuntimeError(f"no_room_available: All rooms are booked for {target_date} at {slot_master}")
                            else:
                                raise RuntimeError(f"no_room_available: No alternative room available for {target_date} at {slot_master}")
                    
                    # CRITICAL: Set booking.timeslot and room FIRST, then save booking COMPLETELY
                    # This ensures booking is fully persisted before any objects reference it
                    # DO NOT set status='scheduled' yet - wait until all BookingAssignment records are created
                    print(f"[DEBUG] Setting booking.timeslot and room BEFORE creating any related objects")
                    booking.timeslot = slot_master
                    booking.room = room_candidate or booking.room
                    if allocation and room_candidate and not getattr(allocation, 'room', None):
                        allocation.room = room_candidate
                        allocation.save(update_fields=['room'])
                    # Keep status as 'draft' until all therapists are assigned and BookingAssignment records are created
                    # booking.status = 'scheduled'  # Will be set later after BookingAssignment creation
                    # Save booking COMPLETELY before creating any FK references to it
                    booking.save()
                    # Refresh to ensure it's fully loaded
                    booking.refresh_from_db()
                    print(f"[DEBUG] Booking fully saved: pk={booking.pk}, timeslot_id={booking.timeslot_id}, room_id={booking.room_id}, status={booking.status}")
                    
                    rb_obj = None
                    if needs_room_flag and create_bookings:
                        # Now create RoomBooking - booking is fully saved and persisted
                        # Use slot_master (resolved SlotMaster) instead of canonical_slot to ensure FK is valid
                        print(f"[DEBUG] Creating RoomBooking: room={room_candidate} (pk={room_candidate.pk if room_candidate else None}), date={target_date}, slot_master={slot_master} (pk={slot_master.pk if slot_master else None}), booking={booking} (pk={booking.pk})")
                        try:
                            rb_obj, rb_created = create_room_booking_safe(room_candidate, target_date, slot_master, therapy_name, patient_id, booking)
                            if rb_obj and allocation and rb_obj.therapy_id != allocation.id:
                                rb_obj.therapy = allocation
                                rb_obj.save(update_fields=['therapy'])
                            print(f"[DEBUG] RoomBooking created: {rb_obj}, created={rb_created}")
                            # Refresh RoomBooking to get actual FK IDs
                            if rb_obj:
                                rb_obj.refresh_from_db()
                                print(f"[DEBUG] RoomBooking FK IDs: room_id={rb_obj.room_id}, time_slot_id={rb_obj.time_slot_id}, visit_id={rb_obj.visit_id}")
                        except Exception as rb_e:
                            print(f"[DEBUG] ERROR creating RoomBooking: {rb_e}")
                            import traceback
                            traceback.print_exc()
                            raise
                        if not rb_created:
                            # RoomBooking already exists, try alternative room.
                            # Do not pass booking_id here: create_room_booking_safe may have
                            # attached visit=booking to a preexisting visit=None RoomBooking
                            # before returning rb_created=False, and excluding booking_id
                            # would mask that conflict and return room_candidate again.
                            alternative_room = allocate_treatment_room(
                                target_date, 
                                slot_master, 
                                getattr(room_candidate, 'room_no', None),
                                therapy_name=therapy_name,
                                patient_id=patient_id,
                                patient_staying_room=patient_staying_room,
                                patient=allocation.patient if allocation and hasattr(allocation, 'patient') else None,
                                is_wheelchair=is_wc,
                                booking_id=None,
                            )
                            if alternative_room and alternative_room != room_candidate:
                                # Update booking room first
                                booking.room = alternative_room
                                booking.save()
                                booking.refresh_from_db()
                                rb_obj, rb_created = create_room_booking_safe(alternative_room, target_date, slot_master, therapy_name, patient_id, booking)
                                if rb_created:
                                    room_candidate = alternative_room
                                    if rb_obj:
                                        rb_obj.refresh_from_db()
                                else:
                                    raise RuntimeError("room_already_booked")
                            else:
                                raise RuntimeError("room_already_booked")
                    elif needs_room_flag:
                        rb_obj = booking if getattr(booking, 'room', None) else None
                    tb_objs = []
                    # Check which therapists are from PASS 1 continuity (already have TherapistBooking)
                    continuity_therapist_ids = set()
                    if continuity_assigned and isinstance(continuity_assigned, dict):
                        continuity_therapists = continuity_assigned.get('assigned_therapists', [])
                        continuity_therapist_ids = {getattr(t, 'id', None) for t in continuity_therapists if hasattr(t, 'id')}
                    
                    from masters.models import is_therapist_omitted_for_treatment
                    treatment_check = therapy_name or getattr(allocation, 'therapy_name', None) or getattr(allocation, 'therapy_code', None)
                    if treatment_check:
                        assigned_therapists = [t for t in assigned_therapists if not is_therapist_omitted_for_treatment(t, treatment_check)]

                    for t in list(assigned_therapists):
                        is_bath_for_t = (t in bath_assigned_set)
                        therapist_id = getattr(t, 'id', None)
                        is_continuity_therapist = therapist_id in continuity_therapist_ids
                        
                        if create_bookings:
                            if treatment_check and is_therapist_omitted_for_treatment(t, treatment_check):
                                print(f"[CONTINUITY PASS2] BLOCKED: Therapist {t.therapist_code} has approved omission for {treatment_check} - removing")
                                assigned_therapists = [at for at in assigned_therapists if at != t]
                                continue

                            if is_continuity_therapist:
                                # This therapist was locked in PASS 1 - use existing TherapistBooking
                                print(f"[CONTINUITY PASS2] Using existing TherapistBooking for continuity therapist {t.therapist_code} (locked in PASS 1)")
                                from Patient.models import TherapistBooking
                                tb_obj = TherapistBooking.objects.filter(
                                    therapist=t,
                                    date=target_date,
                                    time_slot=slot_master,
                                    status='BOOKED'
                                ).first()
                                if tb_obj:
                                    # Update is_bathing if needed
                                    if is_bath_for_t and hasattr(tb_obj, 'is_bathing') and not tb_obj.is_bathing:
                                        tb_obj.is_bathing = True
                                        tb_obj.save(update_fields=['is_bathing'])
                                    # Update visit FK if needed
                                    if tb_obj.visit_id != allocation.id:
                                        tb_obj.visit = allocation
                                        tb_obj.save(update_fields=['visit'])
                                    tb_obj.refresh_from_db()
                                    print(f"[CONTINUITY PASS2] Using existing TherapistBooking pk={tb_obj.pk} for continuity therapist {t.therapist_code}")
                                    tb_objs.append(tb_obj)
                                else:
                                    # Should not happen - continuity therapist should have TherapistBooking from PASS 1
                                    print(f"[CONTINUITY PASS2] ⚠ WARNING: Continuity therapist {t.therapist_code} has no TherapistBooking - creating one")
                                    tb_obj, tb_created = create_therapist_booking_safe(t, target_date, slot_master, therapy_name, patient_id, allocation, is_bathing=is_bath_for_t)
                                    if tb_obj is None:
                                        print(f"[CONTINUITY PASS2] ✗ ERROR: Cannot create TherapistBooking for {t.therapist_code} - session limit exceeded or treatment omitted")
                                        # This should not happen if checks were done correctly, but handle gracefully
                                        assigned_therapists = [at for at in assigned_therapists if at != t]
                                        continue
                                    tb_objs.append(tb_obj)
                            else:
                                # New therapist - create TherapistBooking
                                print(f"[CONTINUITY PASS2] Creating new TherapistBooking for therapist {t.therapist_code}")
                                # Pass allocation (TherapyAllocation) instead of None for visit FK
                                # Use slot_master (resolved SlotMaster) instead of canonical_slot to ensure FK is valid
                                tb_obj, tb_created = create_therapist_booking_safe(t, target_date, slot_master, therapy_name, patient_id, allocation, is_bathing=is_bath_for_t)
                                if tb_obj is None:
                                    print(f"[CONTINUITY PASS2] ✗ ERROR: Cannot create TherapistBooking for {t.therapist_code} - session limit exceeded or treatment omitted")
                                    # This should not happen if checks were done correctly, but handle gracefully
                                    assigned_therapists = [at for at in assigned_therapists if at != t]
                                    continue
                                print(f"[CONTINUITY PASS2] TherapistBooking created: {tb_obj}, created={tb_created}")
                                if not tb_created:
                                    # This is OK - therapist might have been booked by another process
                                    print(f"[CONTINUITY PASS2] ⚠ TherapistBooking already exists for {t.therapist_code} - using existing")
                                # Refresh TherapistBooking to get actual FK IDs
                                if tb_obj:
                                    tb_obj.refresh_from_db()
                                    print(f"[CONTINUITY PASS2] TherapistBooking FK IDs: therapist_id={tb_obj.therapist_id}, time_slot_id={tb_obj.time_slot_id}, visit_id={tb_obj.visit_id}")
                                tb_objs.append(tb_obj)
                        else:
                            tb_objs.append(SimpleNamespace(therapist_code=getattr(t,'therapist_code',str(t)), is_bathing=is_bath_for_t))

                    # Clean up any extra TherapistBooking rows for this allocation/date/slot
                    # that are not part of the final assigned_therapists list. This prevents
                    # over-booking (e.g. 5 bookings when only 3 therapists are required/assigned).
                    try:
                        from Patient.models import TherapistBooking as _TBModel
                        assigned_ids = {getattr(t, 'id', None) for t in assigned_therapists if getattr(t, 'id', None)}
                        extra_qs = _TBModel.objects.filter(
                            visit=allocation,
                            date=target_date,
                            time_slot=slot_master,
                            status='BOOKED',
                        )
                        if assigned_ids:
                            extra_qs = extra_qs.exclude(therapist_id__in=assigned_ids)
                        extra_count = extra_qs.count()
                        if extra_count:
                            print(f"[CONTINUITY PASS2] Cleaning up {extra_count} extra TherapistBooking rows for allocation {allocation.id} on {target_date} at {slot_master}")
                            extra_qs.delete()
                    except Exception as e:
                        print(f"[CONTINUITY PASS2] Error cleaning up extra TherapistBooking rows: {e}")
                    # slot_master and booking.timeslot are already set and saved above (before RoomBooking/TherapistBooking)
                    # Now create BookingAssignment records
                    
                    # Refresh booking to ensure all foreign keys are properly loaded before creating BookingAssignment
                    # CRITICAL: Refresh booking to get latest state including timeslot FK
                    booking.refresh_from_db()
                    print(f"[DEBUG] Booking refreshed: pk={booking.pk}, timeslot_id={booking.timeslot_id}, timeslot={booking.timeslot}")
                    
                    # Ensure booking.timeslot is set and saved before creating BookingAssignment
                    # BookingAssignment.save() accesses booking.timeslot, so it must be valid
                    if not booking.timeslot_id or booking.timeslot_id != slot_master.pk:
                        print(f"[DEBUG] WARNING: booking.timeslot_id mismatch! Expected {slot_master.pk}, got {booking.timeslot_id}")
                        booking.timeslot = slot_master
                        booking.save()
                        booking.refresh_from_db()
                        print(f"[DEBUG] Booking.timeslot re-saved and refreshed")
                    
                    # create BookingAssignment records to link therapists to Booking (Sheduling app)
                    from Sheduling.models import BookingAssignment
                    from Patient.models import Therapist
                    
                    # Track BookingAssignment creation success
                    ba_success_count = 0
                    ba_failed_count = 0
                    ba_errors = []
                    
                    for t in assigned_therapists:
                        try:
                            # Get or create Therapist object from Patient app (therapist_code is PK)
                            therapist_obj, _ = Therapist.objects.get_or_create(
                                therapist_code=t.therapist_code,
                                defaults={
                                    'therapist_name': getattr(t, 'therapist_name', t.therapist_code),
                                    'therapist_grade': get_therapist_grade_name(t),
                                    'is_bathing_therapist': getattr(t, 'is_bathing_therapist', False)
                                }
                            )
                            # Verify therapist_obj exists and has valid PK
                            if not therapist_obj.pk:
                                raise RuntimeError(f"Therapist object has no PK: {therapist_obj}")
                            print(f"[CONTINUITY PASS2] Therapist object verified: pk={therapist_obj.pk}, code={t.therapist_code}")
                            
                            # Check if assignment already exists for THIS booking
                            existing = BookingAssignment.objects.filter(booking=booking, therapist=therapist_obj).first()
                            if existing:
                                ba_obj = existing
                                ba_created = False
                                print(f"[CONTINUITY PASS2] BookingAssignment already exists: pk={ba_obj.pk} for therapist {t.therapist_code}")
                                ba_success_count += 1
                            else:
                                # CRITICAL FIX: Check for stale/released BookingAssignment for same
                                # therapist + date + timeslot (from a cancelled/released booking).
                                # The UNIQUE constraint on (therapist, booking_date, booking_timeslot)
                                # would cause IntegrityError if we try to create a new one while the
                                # stale record exists.  Overwrite it instead.
                                stale = BookingAssignment.objects.filter(
                                    therapist=therapist_obj,
                                    booking_date=target_date,
                                    booking_timeslot=slot_master,
                                ).exclude(booking=booking).first()
                                if stale:
                                    print(f"[CONTINUITY PASS2] Found stale BookingAssignment pk={stale.pk} for therapist {t.therapist_code} "
                                          f"(old booking={stale.booking_id}, status={stale.status}) — overwriting")
                                    stale.booking = booking
                                    stale.booking_item = None
                                    stale.role = get_therapist_grade_name(t)
                                    stale.assigned_for = 'booking'
                                    stale.status = 'assigned'
                                    stale.save()
                                    ba_obj = stale
                                    ba_created = True
                                    print(f"[CONTINUITY PASS2] ✓ Stale BookingAssignment overwritten: pk={ba_obj.pk} for therapist {t.therapist_code}")
                                    ba_success_count += 1
                                else:
                                    # No stale record — safe to create a new one
                                    print(f"[CONTINUITY PASS2] Creating BookingAssignment for therapist {t.therapist_code}")
                                    ba_obj = BookingAssignment(
                                        booking=booking,
                                        therapist=therapist_obj,
                                        booking_item=None,
                                        booking_date=target_date,
                                        booking_timeslot=slot_master,
                                        role=get_therapist_grade_name(t),
                                        assigned_for='booking',
                                        status='assigned'
                                    )
                                    ba_obj.save()
                                    print(f"[CONTINUITY PASS2] ✓ BookingAssignment created successfully: pk={ba_obj.pk} for therapist {t.therapist_code}")
                                    ba_created = True
                                    ba_success_count += 1
                        except Exception as e:
                            # Any exception here means the current DB transaction is now in an error state
                            # (e.g. UNIQUE constraint on BookingAssignment or other IntegrityError).
                            error_msg = f"Error creating BookingAssignment for {getattr(t, 'therapist_code', 'unknown')}: {e}"
                            print(f"[CONTINUITY PASS2] ❌ {error_msg}")
                            import traceback
                            traceback.print_exc()
                            ba_failed_count += 1
                            ba_errors.append(error_msg)
                            # Immediately abort the loop and bubble up as IncompleteAssignmentError so the
                            # outer handler can roll back the atomic block and mark the booking as failed.
                            raise IncompleteAssignmentError()
                    
                    expected_ba_count = len(assigned_therapists)
                    # At this point, all BookingAssignment saves have succeeded (no exceptions).
                    # It is now safe to run additional queries (e.g. .count()) within this atomic block.
                    
                    # Verify all therapists have BookingAssignment records
                    actual_ba_count = BookingAssignment.objects.filter(booking=booking).count()
                    print(f"[CONTINUITY PASS2] BookingAssignment summary for booking {booking_id}:")
                    print(f"[CONTINUITY PASS2]   - Expected: {expected_ba_count} therapists")
                    print(f"[CONTINUITY PASS2]   - Created successfully: {ba_success_count}")
                    print(f"[CONTINUITY PASS2]   - Failed: {ba_failed_count}")
                    print(f"[CONTINUITY PASS2]   - Actual BookingAssignment records in DB: {actual_ba_count}")
                    
                    # Store values to use after transaction
                    booking_expected_ba_count = expected_ba_count
                    booking_actual_ba_count = actual_ba_count
                    booking_ba_success_count = ba_success_count
                    booking_ba_errors = ba_errors.copy() if ba_errors else []
                    
                    # Only mark booking as 'scheduled' if ALL therapists have BookingAssignment records
                    # Don't raise error here - let transaction complete, then check status outside
                    if ba_success_count == expected_ba_count and actual_ba_count == expected_ba_count:
                        # All therapists assigned - will set status to 'scheduled' after transaction
                        print(f"[CONTINUITY PASS2] ✓ All {expected_ba_count} therapists assigned - will mark booking {booking_id} as 'scheduled' after transaction")
                        # Set a flag to mark as scheduled after transaction commits
                        booking_needs_scheduled = True
                    else:
                        # Not all therapists assigned - will mark as failed after transaction
                        error_reason = f"incomplete_assignment: Only {ba_success_count}/{expected_ba_count} therapists assigned. Errors: {', '.join(ba_errors) if ba_errors else 'Unknown error'}"
                        print(f"[CONTINUITY PASS2] ❌ Booking {booking_id} will be marked as 'failed': {error_reason}")
                        booking_needs_scheduled = False
                        booking_failure_reason = error_reason
                    
                    booking.refresh_from_db()  # Refresh to clear any cached relations
                    print(f"[CONTINUITY PASS2] Booking {booking_id} final status: {booking.status}")
                    
                    # Room conflict check is now done BEFORE saving booking (see above)
                    # This section is no longer needed as we check earlier
                    
                    # Validate before saving to prevent FK constraint failures
                    if not slot_master:
                        raise RuntimeError(f"no_slot_master: Cannot save booking without SlotMaster")
                    
                    # Verify slot_master exists in database
                    print(f"[DEBUG] Verifying slot_master exists: pk={slot_master.pk}")
                    slot_master_exists = SlotMaster.objects.filter(pk=slot_master.pk).exists()
                    print(f"[DEBUG] SlotMaster pk={slot_master.pk} exists: {slot_master_exists}")
                    if not slot_master_exists:
                        raise RuntimeError(f"slot_master_not_found: SlotMaster {slot_master.pk} does not exist")
                    
                    # Verify room exists if provided
                    if room_candidate:
                        from Patient.models import TreatmentRoom
                        print(f"[DEBUG] Verifying room_candidate exists: pk={room_candidate.pk}")
                        room_exists = TreatmentRoom.objects.filter(pk=room_candidate.pk).exists()
                        print(f"[DEBUG] TreatmentRoom pk={room_candidate.pk} exists: {room_exists}")
                        if not room_exists:
                            raise RuntimeError(f"room_not_found: TreatmentRoom {room_candidate.pk} does not exist")
                    
                    # Booking should already be saved with room and status above
                    # Just verify it's correct
                    print(f"[DEBUG] Verifying booking state:")
                    print(f"[DEBUG]   - booking.timeslot = {booking.timeslot} (pk={booking.timeslot.pk if booking.timeslot else None})")
                    print(f"[DEBUG]   - booking.room = {booking.room} (pk={booking.room.pk if booking.room else None})")
                    print(f"[DEBUG]   - booking.status = {booking.status}")
                    # Ensure room is set correctly (in case alternative room was used)
                    if room_candidate and booking.room != room_candidate:
                        booking.room = room_candidate
                        booking.save()
                        booking.refresh_from_db()
                    
                    # Validate ALL foreign key relationships before saving to catch FK issues early
                    print(f"[DEBUG] Validating all FK relationships before final save...")
                    from Patient.models import TreatmentRoom
                    from Sheduling.models import TherapyAllocation
                    
                    # Validate booking.allocation
                    if booking.allocation_id:
                        alloc_exists = TherapyAllocation.objects.filter(pk=booking.allocation_id).exists()
                        print(f"[DEBUG]   - booking.allocation_id={booking.allocation_id}, exists={alloc_exists}")
                        if not alloc_exists:
                            raise RuntimeError(f"FK validation failed: booking.allocation_id={booking.allocation_id} does not exist")
                    
                    # Validate booking.timeslot
                    if booking.timeslot_id:
                        slot_exists = SlotMaster.objects.filter(pk=booking.timeslot_id).exists()
                        print(f"[DEBUG]   - booking.timeslot_id={booking.timeslot_id}, exists={slot_exists}")
                        if not slot_exists:
                            raise RuntimeError(f"FK validation failed: booking.timeslot_id={booking.timeslot_id} does not exist")
                    
                    # Validate booking.room
                    if booking.room_id:
                        room_exists = TreatmentRoom.objects.filter(pk=booking.room_id).exists()
                        print(f"[DEBUG]   - booking.room_id={booking.room_id}, exists={room_exists}")
                        if not room_exists:
                            raise RuntimeError(f"FK validation failed: booking.room_id={booking.room_id} does not exist")
                    
                    # Validate RoomBooking FKs
                    if rb_obj:
                        print(f"[DEBUG]   - Validating RoomBooking {rb_obj.pk} FKs:")
                        rb_obj.refresh_from_db()  # Refresh to get actual FK IDs
                        if rb_obj.room_id:
                            rb_room_exists = TreatmentRoom.objects.filter(pk=rb_obj.room_id).exists()
                            print(f"[DEBUG]     - rb.room_id={rb_obj.room_id}, exists={rb_room_exists}")
                            if not rb_room_exists:
                                raise RuntimeError(f"FK validation failed: RoomBooking.room_id={rb_obj.room_id} does not exist")
                        if rb_obj.time_slot_id:
                            rb_slot_exists = SlotMaster.objects.filter(pk=rb_obj.time_slot_id).exists()
                            print(f"[DEBUG]     - rb.time_slot_id={rb_obj.time_slot_id}, exists={rb_slot_exists}")
                            if not rb_slot_exists:
                                raise RuntimeError(f"FK validation failed: RoomBooking.time_slot_id={rb_obj.time_slot_id} does not exist")
                        if rb_obj.visit_id:
                            rb_visit_exists = Booking.objects.filter(pk=rb_obj.visit_id).exists()
                            print(f"[DEBUG]     - rb.visit_id={rb_obj.visit_id}, exists={rb_visit_exists}")
                            if not rb_visit_exists:
                                raise RuntimeError(f"FK validation failed: RoomBooking.visit_id={rb_obj.visit_id} does not exist")
                    
                    # Validate TherapistBooking FKs
                    for tb_obj in tb_objs:
                        if hasattr(tb_obj, 'pk') and tb_obj.pk:
                            print(f"[DEBUG]   - Validating TherapistBooking {tb_obj.pk} FKs:")
                            tb_obj.refresh_from_db()  # Refresh to get actual FK IDs
                            if hasattr(tb_obj, 'therapist_id') and tb_obj.therapist_id:
                                from masters.models import TherapistMaster
                                tb_th_exists = TherapistMaster.objects.filter(pk=tb_obj.therapist_id).exists()
                                print(f"[DEBUG]     - tb.therapist_id={tb_obj.therapist_id}, exists={tb_th_exists}")
                                if not tb_th_exists:
                                    raise RuntimeError(f"FK validation failed: TherapistBooking.therapist_id={tb_obj.therapist_id} does not exist")
                            if hasattr(tb_obj, 'time_slot_id') and tb_obj.time_slot_id:
                                tb_slot_exists = SlotMaster.objects.filter(pk=tb_obj.time_slot_id).exists()
                                print(f"[DEBUG]     - tb.time_slot_id={tb_obj.time_slot_id}, exists={tb_slot_exists}")
                                if not tb_slot_exists:
                                    raise RuntimeError(f"FK validation failed: TherapistBooking.time_slot_id={tb_obj.time_slot_id} does not exist")
                            if hasattr(tb_obj, 'visit_id') and tb_obj.visit_id:
                                tb_visit_exists = TherapyAllocation.objects.filter(pk=tb_obj.visit_id).exists()
                                print(f"[DEBUG]     - tb.visit_id={tb_obj.visit_id}, exists={tb_visit_exists}")
                                if not tb_visit_exists:
                                    raise RuntimeError(f"FK validation failed: TherapistBooking.visit_id={tb_obj.visit_id} does not exist")
                    
                    # Validate BookingAssignment FKs (we just created these, so refresh to get IDs)
                    booking.refresh_from_db()
                    for ba in BookingAssignment.objects.filter(booking=booking):
                        print(f"[DEBUG]   - Validating BookingAssignment {ba.pk} FKs:")
                        if ba.booking_id:
                            ba_book_exists = Booking.objects.filter(pk=ba.booking_id).exists()
                            print(f"[DEBUG]     - ba.booking_id={ba.booking_id}, exists={ba_book_exists}")
                            if not ba_book_exists:
                                raise RuntimeError(f"FK validation failed: BookingAssignment.booking_id={ba.booking_id} does not exist")
                        if ba.therapist_id:
                            ba_th_exists = Therapist.objects.filter(pk=ba.therapist_id).exists()
                            print(f"[DEBUG]     - ba.therapist_id={ba.therapist_id}, exists={ba_th_exists}")
                            if not ba_th_exists:
                                raise RuntimeError(f"FK validation failed: BookingAssignment.therapist_id={ba.therapist_id} does not exist")
                        if ba.booking_timeslot_id:
                            ba_slot_exists = SlotMaster.objects.filter(pk=ba.booking_timeslot_id).exists()
                            print(f"[DEBUG]     - ba.booking_timeslot_id={ba.booking_timeslot_id}, exists={ba_slot_exists}")
                            if not ba_slot_exists:
                                raise RuntimeError(f"FK validation failed: BookingAssignment.booking_timeslot_id={ba.booking_timeslot_id} does not exist")
                    
                    print(f"[DEBUG] All FK validations passed!")
                    
                    # Booking should already be saved with all fields above
                    # Just do a final save to ensure everything is persisted
                    print(f"[DEBUG] Final booking save (should already be saved)")
                    try:
                        booking.save()  # Full save to ensure FK constraints work properly
                        booking.refresh_from_db()  # Refresh to get latest state
                        print(f"[DEBUG] Booking.save() completed successfully")
                    except IntegrityError as save_ie:
                        print(f"[DEBUG] IntegrityError during booking.save(): {save_ie}")
                        import traceback
                        traceback.print_exc()
                        raise
                    
                    # CRITICAL: Force SQLite to check FK constraints BEFORE commit
                    # This will catch any FK issues early
                    from django.db import connection
                    cursor = connection.cursor()
                    try:
                        cursor.execute("PRAGMA foreign_key_check")
                        fk_errors = cursor.fetchall()
                        if fk_errors:
                            error_msg = f"SQLite FK constraint violations found: {fk_errors}"
                            print(f"[DEBUG] {error_msg}")
                            # Try to get more details about the violation
                            for error in fk_errors:
                                table, rowid, ref_table, ref_rowid = error
                                print(f"[DEBUG] FK violation: table={table}, rowid={rowid}, ref_table={ref_table}, ref_rowid={ref_rowid}")
                                if table == 'Sheduling_bookingassignment':
                                    ba = BookingAssignment.objects.filter(pk=rowid).first()
                                    if ba:
                                        print(f"[DEBUG]   BookingAssignment pk={ba.pk}: booking_timeslot_id={ba.booking_timeslot_id}, booking_id={ba.booking_id}, therapist_id={ba.therapist_id}")
                            raise RuntimeError(error_msg)
                        print(f"[DEBUG] SQLite FK check passed - no violations")
                    except RuntimeError as fk_check_e:
                        # Re-raise RuntimeError (our FK violations)
                        raise
                    except Exception as fk_check_e:
                        print(f"[DEBUG] Error during FK check: {fk_check_e}")
                        # Don't fail here, let commit handle it
                        pass
                    
                    # DO NOT set booking_saved_successfully = True here
                    # Wait until transaction commits successfully (after the except block)
                    
                    # success audit (inside transaction)
                    if AllocationAttempt:
                        try:
                            AllocationAttempt.objects.create(
                                visit=None, therapy=None, date=target_date,
                                requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                status='SUCCESS', reason='preferred_slot_booked',
                                extra={"room_no": getattr(room_candidate,'room_no',None) if room_candidate else None,
                                       "therapists": therapists_for_audit, "booking_id": booking_id}
                            )
                        except Exception:
                            pass
                    used_slots.append(canonical_slot)
                    print(f"[DEBUG] All operations completed successfully inside transaction block")
                    print(f"[DEBUG] About to exit transaction.atomic() - this will trigger commit...")
                except IntegrityError as ie:
                    # IntegrityError during transaction - rollback will happen automatically
                    print(f"[DEBUG] ========== IntegrityError CAUGHT ==========")
                    print(f"[DEBUG] Error: {ie}")
                    print(f"[DEBUG] Error type: {type(ie)}")
                    print(f"[DEBUG] Error args: {ie.args}")
                    print(f"[DEBUG] Booking ID: {booking_id}")
                    print(f"[DEBUG] slot_master: {slot_master} (pk={slot_master.pk if slot_master else None}, type={type(slot_master) if slot_master else None})")
                    print(f"[DEBUG] room_candidate: {room_candidate} (pk={room_candidate.pk if room_candidate else None}, type={type(room_candidate) if room_candidate else None})")
                    print(f"[DEBUG] booking.timeslot before error: {getattr(booking, 'timeslot', None)}")
                    print(f"[DEBUG] booking.room before error: {getattr(booking, 'room', None)}")
                    import traceback
                    print(f"[DEBUG] Full traceback:")
                    traceback.print_exc()
                    print(f"[DEBUG] ============================================")
                    # Mark booking as failed (outside transaction)
                    try:
                        booking.status = 'failed'
                        booking.failure_reason = (f"booking_transaction_failed: {ie}" or '')[:512]
                        booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                    except Exception as e:
                        print(f"[DEBUG] Error marking booking as failed: {e}")
                    # Re-raise to be caught by outer exception handler
                    raise RuntimeError(f"booking_transaction_failed: {str(ie)}")
            
            print(f"[CONTINUITY PASS2] Transaction.atomic() block exited - checking for commit errors...")
            # If we reach here, transaction committed successfully
            print(f"[CONTINUITY PASS2] Transaction committed successfully for booking {booking_id}")
            booking_saved_successfully = True
            
            # Now check if all BookingAssignment records were created and set booking status
            booking.refresh_from_db()
            
            # Use stored values from inside transaction, verify with actual DB count
            expected_ba_count = booking_expected_ba_count
            actual_ba_count = BookingAssignment.objects.filter(booking=booking).count()
            ba_success_count = booking_ba_success_count
            ba_errors = booking_ba_errors
            
            print(f"[CONTINUITY PASS2] Final check for booking {booking_id} after transaction:")
            print(f"[CONTINUITY PASS2]   - Expected: {expected_ba_count} therapists")
            print(f"[CONTINUITY PASS2]   - Actual BookingAssignment in DB: {actual_ba_count}")
            print(f"[CONTINUITY PASS2]   - Success count: {ba_success_count}")
            print(f"[CONTINUITY PASS2]   - Current booking.status: {booking.status}")
            
            # Set booking status based on BookingAssignment count
            if actual_ba_count == expected_ba_count and expected_ba_count > 0 and ba_success_count == expected_ba_count:
                # All therapists have BookingAssignment records - mark as scheduled
                booking.status = 'scheduled'
                booking.save(update_fields=['status', 'updated_at'])
                print(f"[CONTINUITY PASS2] ✓ All {expected_ba_count} therapists assigned - booking {booking_id} marked as 'scheduled'")
                
                # Mark task as BOOKED
                tasks.append({
                    "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                    "therapy_name": therapy_name, "slot": requested_slot_value, "status": "BOOKED", "reason": None,
                    "room_no": getattr(room_candidate,"room_no",None) if room_candidate else getattr(booking.room,"room_no",None) if getattr(booking,"room",None) else None,
                    "therapists": therapists_for_audit
                })
                any_success = True
                print(f"[CONTINUITY PASS2] ✓ Booking {booking_id} marked as BOOKED in task list")
            else:
                # Not all therapists have BookingAssignment records - mark as failed with user-friendly reason.
                internal_reason = (
                    f"incomplete_assignment: Only {actual_ba_count}/{expected_ba_count} BookingAssignment records created. "
                    f"Success: {ba_success_count}/{expected_ba_count}. "
                    f"Errors: {', '.join(ba_errors) if ba_errors else 'None'}"
                )
                print(f"[CONTINUITY PASS2] ❌ Booking {booking_id} incomplete assignment (log): {internal_reason}")
                reason = "Could not assign all therapists for this slot."
                booking.status = 'failed'
                booking.failure_reason = (str(reason) or '')[:512]
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                print(f"[CONTINUITY PASS2] Booking {booking_id} marked as 'failed' (user message): {reason}")
                
                # Release locked therapists from PASS 1 if booking failed
                if booking_continuity_map and booking_id in booking_continuity_map:
                    continuity_result = booking_continuity_map[booking_id]
                    if continuity_result and isinstance(continuity_result, dict):
                        assigned_continuity = continuity_result.get('assigned_therapists', [])
                        if assigned_continuity:
                            print(f"[CONTINUITY PASS2] Releasing {len(assigned_continuity)} locked therapists from PASS 1 for failed booking {booking_id}")
                            from Patient.models import TherapistBooking
                            for therapist in assigned_continuity:
                                try:
                                    # Find and delete TherapistBooking records created in PASS 1 for this booking
                                    tb_records = TherapistBooking.objects.filter(
                                        therapist_id=therapist.pk,
                                        date=target_date,
                                        time_slot=slot_master,
                                        visit_id=therapy_allocation_id,
                                        status='BOOKED'
                                    )
                                    deleted_count = tb_records.count()
                                    tb_records.delete()
                                    if deleted_count > 0:
                                        print(f"[CONTINUITY PASS2]   - Released therapist {therapist.therapist_code} (deleted {deleted_count} TherapistBooking records)")
                                except Exception as release_e:
                                    print(f"[CONTINUITY PASS2]   - Error releasing therapist {getattr(therapist, 'therapist_code', 'unknown')}: {release_e}")
                
                # Mark task as FAILED
                tasks.append({
                    "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                    "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                    "room_no": getattr(room_candidate,"room_no",None) if room_candidate else getattr(booking.room,"room_no",None) if getattr(booking,"room",None) else None,
                    "therapists": therapists_for_audit
                })
                print(f"[CONTINUITY PASS2] ❌ Booking {booking_id} marked as FAILED in task list: {reason}")

        except IntegrityError as outer_ie:
            # IntegrityError might be raised during transaction commit (after atomic() block exits)
            print(f"[DEBUG] ========== IntegrityError CAUGHT IN OUTER HANDLER ==========")
            print(f"[DEBUG] This means the error occurred during transaction COMMIT, not during operations")
            print(f"[DEBUG] Error: {outer_ie}")
            print(f"[DEBUG] Error type: {type(outer_ie)}")
            print(f"[DEBUG] Error args: {outer_ie.args}")
            print(f"[DEBUG] Booking ID: {booking_id}")
            import traceback
            print(f"[DEBUG] Full traceback:")
            traceback.print_exc()
            print(f"[DEBUG] ============================================")
            reason = f"exception:{str(outer_ie)}"
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason, extra={"booking_id": booking_id, "therapists": therapists_for_audit}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": getattr(room_candidate,"room_no",None) if room_candidate else None, "therapists": therapists_for_audit
            })
            continue

        except IncompleteAssignmentError:
            # Booking could not be completed (e.g. only 4/5 therapist assignments created).
            # Mark as failed and show a user-friendly message, not a technical error.
            reason = "Could not assign all therapists for this slot."
            try:
                booking.refresh_from_db()
                booking.status = 'failed'
                booking.failure_reason = (reason or '')[:512]
                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                print(f"[CONTINUITY PASS2] ❌ Booking {booking_id} marked as failed (user message): {reason}")
            except Exception as e:
                print(f"[CONTINUITY PASS2] Could not update booking status: {e}")
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason, extra={"booking_id": booking_id, "therapists": therapists_for_audit}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": getattr(room_candidate,"room_no",None) if room_candidate else None, "therapists": therapists_for_audit
            })
            continue

        except RuntimeError as rte:
            reason = str(rte)
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason, extra={"booking_id": booking_id, "therapists": therapists_for_audit}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": getattr(room_candidate,"room_no",None) if room_candidate else None, "therapists": therapists_for_audit
            })
            continue

        except Exception as exc:
            reason = f"exception:{str(exc)}"
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason, extra={"booking_id": booking_id, "therapists": therapists_for_audit}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": getattr(room_candidate,"room_no",None) if room_candidate else None, "therapists": therapists_for_audit
            })
            continue

    # DO NOT update allocation.status automatically
    # Each booking date is processed independently
    # The TherapyAllocation.status field remains unchanged to allow:
    # - Mixed states: some dates scheduled, some dates draft (e.g., 23rd draft, 24th scheduled)
    # - Per-date processing without affecting overall allocation status
    # - Running Final Schedule for one date doesn't change allocation status
    # Only individual Booking.status is updated per date during processing

    return tasks

