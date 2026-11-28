"""
Rescheduling Slot Attempter (Layer 3B).

Hosts `attempt_allocate_slot` for evaluating or persisting room + therapist
allocations for a single canonical slot during rescheduling.

Must NEVER import `allocation_engine.scheduling`, `final_allocation`,
`reshedule`, or `resheduleMorningandNight`.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from django.db import transaction, IntegrityError
from django.db.models import Q

from allocation_engine.core.primitives.date_utils import daterange
from allocation_engine.core.primitives.patient_utils import (
    is_patient_active,
    parse_patient_age,
    resolve_desired_gender,
)
from allocation_engine.core.primitives.room_utils import get_treatment_rooms_for_staying_room
from allocation_engine.core.primitives.slot_utils import (
    map_to_canonical_slot,
    _slot_time_value,
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
from allocation_engine.core.allocators.room_allocator import (
    RESCHEDULING_ROOM_CONFIG,
    allocate_treatment_room as _allocate_treatment_room_core,
)
from allocation_engine.core.allocators.slot_policy import get_allowed_slot_values
from allocation_engine.core.allocators.therapist_allocator import (
    RESCHEDULING_THERAPIST_CONFIG,
    allocate_therapists as _allocate_therapists_core,
    allocate_therapists_with_grade_substitution as _allocate_therapists_grade_sub_core,
    make_readonly_therapist_config,
)


def therapist_requirements(allocation_or_therapy_obj):
    return _core_therapist_requirements(allocation_or_therapy_obj, default_total_if_missing=1)


def create_room_booking_safe(room, date, time_slot, therapy_name, patient_id, visit):
    return _core_create_room_booking_safe(
        room, date, time_slot, therapy_name, patient_id, visit,
        use_atomic=True, refresh=False,
    )


def create_therapist_booking_safe(therapist, date, time_slot, therapy_name, patient_id, visit, is_bathing=False):
    return _core_create_therapist_booking_safe(
        therapist, date, time_slot, therapy_name, patient_id, visit,
        is_bathing=is_bathing, use_atomic=True, resolve_therapy_fk=True, refresh=False,
    )


def allocate_treatment_room(date, time_slot, last_room=None, therapy_name=None, patient_id=None, patient_staying_room=None, patient=None, booking_id=None, is_wheelchair=False):
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


def allocate_therapists(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False, patient_gender=None, patient_id=None, allow_helping_fallback=False, patient_age=None, *, create_bookings=True):
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


def attempt_allocate_slot(allocation, booking, date, canonical_slot, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, last_allocation, AllocationAttempt, allow_helping_fallback=False):
    """
    Try to allocate room + therapists for this canonical_slot.
    Returns (task_dict, success_bool, reason_if_failed)
    """
    from Patient.models import RoomBooking, TherapistBooking
    from masters.models import SlotMaster as SlotModel  # used when saving canonical slot objects
    from masters.models import is_therapist_on_emergency_leave, is_therapist_deputed, is_therapist_omitted_for_treatment
    therapy_name = allocation.therapy_name
    booking_id = getattr(booking, 'pk', None)

    requested_slot_value = None
    try:
        requested_slot_value = canonical_slot.slot_time.strftime("%H:%M")
    except Exception:
        pass

    # patient already has booking check (prevents multiple sections for same date+slot)
    # When rescheduling, exclude bookings from the same allocation to allow slot changes
    patient_already_booked = False
    try:
        # Exclude current booking and any bookings from the same allocation (for rescheduling)
        room_booking_qs = RoomBooking.objects.filter(
            patient_id=patient_id, 
            date=date, 
            time_slot=canonical_slot, 
            status__in=['BOOKED','scheduled']
        ).exclude(pk=getattr(booking,'pk',None)).exclude(visit__status='cancelled')
        
        if booking and hasattr(booking, 'pk') and booking.pk:
            room_booking_qs = room_booking_qs.exclude(visit=booking)
        # Also exclude bookings from the same allocation (allows rescheduling to different slots)
        if allocation and hasattr(allocation, 'pk'):
            room_booking_qs = room_booking_qs.exclude(therapy=allocation).exclude(visit__allocation=allocation)
        
        therapist_booking_qs = TherapistBooking.objects.filter(
            patient_id=patient_id, 
            date=date, 
            time_slot=canonical_slot, 
            status='BOOKED'
        ).exclude(visit__status='cancelled')
        
        # Also exclude therapist bookings from the same allocation
        if allocation and hasattr(allocation, 'pk'):
            therapist_booking_qs = therapist_booking_qs.exclude(visit=allocation)
        
        patient_already_booked = room_booking_qs.exists() or therapist_booking_qs.exists()
    except Exception:
        # fallback: compare by start_time
        try:
            slot_start = getattr(canonical_slot, 'start_time', None)
            if slot_start:
                room_booking_qs = RoomBooking.objects.filter(
                    patient_id=patient_id, 
                    date=date, 
                    time_slot__start_time=slot_start, 
                    status__in=['BOOKED','scheduled']
                ).exclude(
                    Q(therapy__status='cancelled') | Q(visit__status='cancelled') | Q(visit__allocation__status='cancelled')
                )
                if booking and hasattr(booking, 'pk') and booking.pk:
                    room_booking_qs = room_booking_qs.exclude(visit=booking)
                if allocation and hasattr(allocation, 'pk'):
                    room_booking_qs = room_booking_qs.exclude(therapy=allocation).exclude(visit__allocation=allocation)
                
                therapist_booking_qs = TherapistBooking.objects.filter(
                    patient_id=patient_id, 
                    date=date, 
                    time_slot__start_time=slot_start, 
                    status='BOOKED'
                ).exclude(visit__status='cancelled')
                
                if allocation and hasattr(allocation, 'pk'):
                    therapist_booking_qs = therapist_booking_qs.exclude(visit=allocation)
                
                patient_already_booked = room_booking_qs.exists() or therapist_booking_qs.exists()
        except Exception:
            patient_already_booked = False

    if patient_already_booked:
        reason = "patient_already_has_booking"
        print(f"[DEBUG attempt_allocate_slot] Patient {patient_id} already has a booking at slot {requested_slot_value} on {date} (excluding allocation {allocation.pk if allocation else None})")
        return ({
            "booking_id": booking_id,
            "allocation_id": allocation.pk,
            "date": date.isoformat(),
            "therapy_name": therapy_name,
            "slot": requested_slot_value,
            "status": "FAILED",
            "reason": reason,
            "room_no": getattr(booking.room, 'room_no', None) if getattr(booking,'room',None) else None,
            "therapists": []
        }, False, reason)

    # HARD TREATMENT RESTRICTION: Two hard treatments should not be scheduled in the same session
    # Exception: Medium and Easy treatments (e.g. Lepam) can be assigned in the same session
    if is_hard_treatment(allocation, therapy_name=therapy_name) or (therapy_req and str(therapy_req.get("therapy_category", "")).strip().lower() == 'hard'):
        slot_session = get_slot_session(canonical_slot)
        if slot_session and patient_id and patient_has_hard_treatment_in_session(
            patient_id=patient_id,
            target_date=date,
            session=slot_session,
            exclude_booking_id=booking_id,
            exclude_allocation_id=allocation.pk if allocation and hasattr(allocation, 'pk') else None
        ):
            reason = "hard_treatment_same_session_conflict"
            print(f"[HARD TREATMENT RESTRICTION] BLOCKED: Patient {patient_id} already has a hard treatment in {slot_session} session on {date}")
            if AllocationAttempt and create_bookings:
                try:
                    AllocationAttempt.objects.create(
                        visit=allocation if allocation and hasattr(allocation, 'pk') else None,
                        therapy=allocation if allocation and hasattr(allocation, 'pk') else None,
                        date=date,
                        requested_time_slot=canonical_slot,
                        requested_time_slot_value=requested_slot_value or '',
                        status='FAILED',
                        reason=reason,
                        extra={"booking_id": booking_id, "session": slot_session}
                    )
                except Exception:
                    pass
            return ({
                "booking_id": booking_id,
                "allocation_id": allocation.pk if allocation and hasattr(allocation, 'pk') else None,
                "date": date.isoformat() if hasattr(date, 'isoformat') else str(date),
                "therapy_name": therapy_name,
                "slot": requested_slot_value,
                "status": "FAILED",
                "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None,
                "therapists": []
            }, False, reason)

    # in-run used slot check (use slot_time for SlotMaster; avoid matching on None)
    canonical_time = _slot_time_value(canonical_slot)
    if canonical_time and used_slots:
        for s in used_slots:
            st = _slot_time_value(s)
            if st and st == canonical_time:
                reason = "slot_already_used_in_run"
                return ({
                    "booking_id": booking_id,
                    "allocation_id": allocation.pk,
                    "date": date.isoformat(),
                    "therapy_name": therapy_name,
                    "slot": requested_slot_value,
                    "status": "FAILED",
                    "reason": reason,
                    "room_no": getattr(booking.room, 'room_no', None) if getattr(booking,'room',None) else None,
                    "therapists": []
                }, False, reason)

    # Check for previous therapists (bathing + others) for continuity
    # If ALL previous therapists are available together, assign them as a group
    previous_bathing_therapist = None
    previous_therapist_group = []  # All previous therapists (bathing + non-bathing) from most recent day
    pref_roster = None
    if patient_id:
        try:
            from Sheduling.preferred_therapist_service import get_active_preferred_roster
            pref_roster = get_active_preferred_roster(patient_id)
        except Exception:
            pref_roster = None
    try:
        from Patient.models import TherapistBooking
        from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave, is_therapist_omitted_for_treatment
        from django.db.models import Q
        from django.db.models import Max
        
        # Find the most recent date where this patient had therapists assigned
        most_recent_date = TherapistBooking.objects.filter(
            patient_id=patient_id,
            status='BOOKED'
        ).exclude(
            visit=allocation  # Exclude current allocation
        ).aggregate(Max('date'))['date__max']
        
        if most_recent_date:
            # Get ALL therapists from that most recent date (same time slot if possible, or any slot)
            # Note: TherapistBooking.therapist is a ForeignKey to TherapistMaster, so we get TherapistMaster objects directly
            prev_bookings = TherapistBooking.objects.filter(
                patient_id=patient_id,
                date=most_recent_date,
                status='BOOKED'
            ).exclude(
                visit=allocation
            ).select_related('therapist').order_by('time_slot')
            
            # Extract TherapistMaster objects directly (no need to lookup by code)
            previous_therapist_masters = []
            seen_therapist_ids = set()
            for prev_booking in prev_bookings:
                if prev_booking.therapist:
                    if not getattr(prev_booking.therapist, 'is_active', True):
                        continue
                    if getattr(prev_booking.therapist, 'is_helping_therapist', False):
                        if not (pref_roster and prev_booking.therapist.therapist_code in pref_roster.get('therapist_codes_set', set())):
                            continue
                    therapist_id = prev_booking.therapist.pk
                    if therapist_id not in seen_therapist_ids:
                        previous_therapist_masters.append(prev_booking.therapist)
                        seen_therapist_ids.add(therapist_id)
            
            # Check if ALL previous therapists are available together
            day_of_week = date.weekday()
            all_available = True
            available_previous_therapists = []
            
            for prev_tm in previous_therapist_masters:
                is_available = True
                
                # Check if therapist is already booked at this date/time_slot
                if TherapistBooking.objects.filter(
                    therapist=prev_tm,
                    date=date,
                    time_slot=canonical_slot,
                    status='BOOKED'
                ).exists():
                    is_available = False
                # Check if therapist is on recurring leave
                elif TherapistLeaveMaster.objects.filter(
                    therapist=prev_tm,
                    leave_day=day_of_week
                ).exists():
                    is_available = False
                # Check emergency leave
                elif is_therapist_on_emergency_leave(prev_tm, date, canonical_slot):
                    is_available = False
                # Check deputation
                elif is_therapist_deputed(prev_tm, date):
                    is_available = False
                # Check treatment omission
                elif is_therapist_omitted_for_treatment(prev_tm, therapy_name):
                    is_available = False
                
                if is_available:
                    available_previous_therapists.append(prev_tm)
                else:
                    all_available = False
                    break
            
            # If ALL previous therapists are available, use them as a group
            if all_available and len(available_previous_therapists) > 0:
                previous_therapist_group = available_previous_therapists
                print(f"[DEBUG] Found complete previous therapist group ({len(previous_therapist_group)} therapists) for patient {patient_id} - will assign together for continuity")
                
                # Identify bathing therapist: from START OF THERAPY for THIS allocation and slot (day 1 bathing carries to day 2-7)
                if needs_bath_flag:
                    therapy_start_date = getattr(allocation, 'from_date', None)
                    prev_bath_qs = TherapistBooking.objects.filter(
                        patient_id=patient_id,
                        visit_id=allocation.id,
                        time_slot=canonical_slot,
                        date__lt=date,
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
                    for th in therapists_from_start:
                        on_leave = False
                        if TherapistBooking.objects.filter(therapist=th, date=date, time_slot=canonical_slot, status='BOOKED').exists():
                            on_leave = True
                        if not on_leave and TherapistLeaveMaster.objects.filter(therapist=th, leave_day=day_of_week).exists():
                            on_leave = True
                        from masters.models import is_therapist_on_emergency_leave, is_therapist_deputed, is_therapist_omitted_for_treatment
                        if not on_leave and is_therapist_on_emergency_leave(th, date, canonical_slot):
                            on_leave = True
                        if not on_leave and is_therapist_deputed(th, date):
                            on_leave = True
                        if not on_leave and is_therapist_omitted_for_treatment(th, therapy_name):
                            on_leave = True
                        if not on_leave:
                            previous_bathing_therapist = th
                            print(f"[DEBUG] Bathing continuity from start of therapy: {th.therapist_code} for patient {patient_id}")
                            break
                    if not previous_bathing_therapist:
                        for prev_tm in previous_therapist_group:
                            if getattr(prev_tm, 'is_bathing_therapist', False) and getattr(prev_tm, 'is_active', True):
                                previous_bathing_therapist = prev_tm
                                break
            else:
                # Not all available - use "from start of therapy" bathing logic for THIS allocation and slot
                if needs_bath_flag:
                    therapy_start_date = getattr(allocation, 'from_date', None)
                    prev_bath_qs = TherapistBooking.objects.filter(
                        patient_id=patient_id,
                        visit_id=allocation.id,
                        time_slot=canonical_slot,
                        date__lt=date,
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
                    for th in therapists_from_start:
                        on_leave = False
                        if TherapistBooking.objects.filter(therapist=th, date=date, time_slot=canonical_slot, status='BOOKED').exists():
                            on_leave = True
                        if not on_leave and TherapistLeaveMaster.objects.filter(therapist=th, leave_day=day_of_week).exists():
                            on_leave = True
                        from masters.models import is_therapist_on_emergency_leave, is_therapist_deputed, is_therapist_omitted_for_treatment
                        if not on_leave and is_therapist_on_emergency_leave(th, date, canonical_slot):
                            on_leave = True
                        if not on_leave and is_therapist_deputed(th, date):
                            on_leave = True
                        if not on_leave and is_therapist_omitted_for_treatment(th, therapy_name):
                            on_leave = True
                        if not on_leave:
                            previous_bathing_therapist = th
                            print(f"[DEBUG] Found previous bathing therapist {previous_bathing_therapist.therapist_code} for patient {patient_id} (from start of therapy)")
                            break
    except Exception as e:
        print(f"[DEBUG] Error checking previous therapists: {e}")
        import traceback
        traceback.print_exc()
    
    # candidate therapists
    candidate_therapists = []
    pass1_continuity_objects = []  # TherapistMaster objects from PASS 1
    patient_obj = getattr(allocation, 'patient', None)
    patient_reg_no = getattr(patient_obj, 'pat_reg_no', None) if patient_obj else (str(patient_id) if patient_id else None)
    patient_name = getattr(patient_obj, 'pat_name', 'Unknown') if patient_obj else 'Unknown'
    preferred_roster_info = None
    if patient_reg_no or patient_id:
        try:
            from Sheduling.preferred_therapist_service import get_active_preferred_roster
            preferred_roster_info = get_active_preferred_roster(patient_reg_no or patient_id)
        except Exception:
            preferred_roster_info = None
    try:
        # Derive patient gender and age from allocation patient snapshot (Rule: Male children below 5 assigned to female therapist)
        pat_sex = getattr(patient_obj, 'pat_sex', None)
        pat_age = getattr(patient_obj, 'pat_age', None)
        
        # First check if we have continuity therapists from PASS 1 (via last_allocation)
        last_therapists = []
        pass1_continuity_assigned = None
        if last_allocation and isinstance(last_allocation, dict):
            continuity_assigned = last_allocation.get('continuity_assigned', {})
            if continuity_assigned and isinstance(continuity_assigned, dict):
                pass1_continuity_objects = continuity_assigned.get('assigned_therapists', [])
                pass1_continuity_assigned = continuity_assigned
                last_therapists = [getattr(t, 'therapist_code', None) for t in pass1_continuity_objects if getattr(t, 'therapist_code', None)]
                print(f"[RESCHEDULE PASS2] Using {len(last_therapists)} continuity therapists from PASS 1: {last_therapists}")
                # Prefer "from start of therapy" when filling remaining slots (e.g. therapist returned from leave)
                try:
                    from Patient.models import TherapistBooking as _TB
                    therapy_start_date = getattr(allocation, 'from_date', None)
                    if therapy_start_date and canonical_slot:
                        from_start_qs = _TB.objects.filter(
                            visit_id=allocation.id,
                            date__gte=therapy_start_date,
                            date__lt=date,
                            time_slot=canonical_slot,
                            status='BOOKED',
                        ).select_related('therapist').order_by('date', 'created_at')
                        assigned_codes = set(last_therapists)
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
                            last_therapists = list(last_therapists) + from_start_codes
                            print(f"[RESCHEDULE PASS2] Preferring {len(from_start_codes)} from-start therapist(s) when filling remaining: {from_start_codes}")
                except Exception as e:
                    print(f"[RESCHEDULE PASS2] Error building from-start for remaining: {e}")
            elif last_allocation.get('therapists'):
                last_therapists = last_allocation.get('therapists', [])
                print(f"[RESCHEDULE PASS2] Using continuity therapists from last_allocation: {last_therapists}")
        
        # If we have a complete previous therapist group, prioritize them (fallback if no PASS 1 continuity)
        if not last_therapists and previous_therapist_group and len(previous_therapist_group) > 0:
            # Use the complete group as last_therapists
            last_therapists = [tm.therapist_code for tm in previous_therapist_group]
            print(f"[DEBUG] Using complete previous therapist group for continuity: {last_therapists}")
        
        if not last_therapists:
            # Build last_therapists list: include previous bathing therapist if available, plus any from last_allocation
            if previous_bathing_therapist:
                last_therapists.append(previous_bathing_therapist.therapist_code)
            if last_allocation and isinstance(last_allocation, dict) and last_allocation.get("last_therapist_codes"):
                # Add other last therapists, avoiding duplicates
                for code in last_allocation.get("last_therapist_codes", []):
                    if code not in last_therapists:
                        last_therapists.append(code)
        
        # PASS 2: Check PatientHistory for previous years' therapists if no recent treatment
        # This helps assign therapists who treated the patient in previous years
        if not last_therapists:
            print(f"[RESCHEDULE PASS2] ========== CHECKING PATIENT HISTORY FOR BOOKING {booking_id} ==========")
            try:
                patient_obj = getattr(allocation, 'patient', None)
                if patient_obj:
                    patient_reg_no = getattr(patient_obj, 'pat_reg_no', None)
                    patient_name = getattr(patient_obj, 'pat_name', 'Unknown')
                    if patient_reg_no:
                        print(f"[RESCHEDULE PASS2] Patient: {patient_name} (Reg No: {patient_reg_no})")
                        print(f"[RESCHEDULE PASS2] Target Date: {date}, Slot: {getattr(canonical_slot, 'id', None) if canonical_slot else None}")
                        
                        from Patient.models import PatientHistory, Repeated_Visitors
                        from masters.models import TherapistMaster, TherapistLeaveMaster
                        from Patient.models import TherapistBooking
                        
                        # First check if patient exists in Repeated_Visitors model
                        is_repeated_visitor = False
                        try:
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
                                    print(f"[RESCHEDULE PASS2] [OK] Patient is a REPEATED VISITOR (Total visits: {total_visits}, VIP: {is_vip})")
                                    print(f"[RESCHEDULE PASS2] Proceeding with PatientHistory check...")
                                else:
                                    print(f"[RESCHEDULE PASS2] [FAIL] Patient is NOT a repeated visitor - Skipping PatientHistory check")
                            else:
                                print(f"[RESCHEDULE PASS2] [FAIL] Could not extract registration number digits - Skipping PatientHistory check")
                        except (ValueError, TypeError) as e:
                            print(f"[RESCHEDULE PASS2] [FAIL] Error checking Repeated_Visitors: {e} - Skipping PatientHistory check")
                        
                        # Only query PatientHistory if patient is a repeated visitor
                        if is_repeated_visitor:
                            # Query PatientHistory by preg_no (patient registration number)
                            history_records = PatientHistory.objects.filter(
                                preg_no=str(patient_reg_no)
                            ).order_by('-date')
                            
                            if history_records.exists():
                                # Get up to 50 unique dates in most recent order
                                unique_dates = history_records.values_list('date', flat=True).distinct().order_by('-date')[:50]
                                
                                print(f"[RESCHEDULE PASS2] Found {len(unique_dates)} unique date(s) in PatientHistory (checking up to 50 most recent)")
                                
                                # Check each date in order until we find available therapists
                                available_history_therapists = []
                                day_of_week = date.weekday()
                                dates_checked = 0
                                
                                for check_date in unique_dates:
                                    dates_checked += 1
                                    print(f"[RESCHEDULE PASS2] Checking date {dates_checked}/{len(unique_dates)}: {check_date}")
                                    
                                    # Get all history records for this date
                                    date_history = history_records.filter(date=check_date)
                                    
                                    # Get unique therapist codes from this date
                                    therapist_codes_from_date = list(
                                        set([h.therapist_code for h in date_history if h.therapist_code])
                                    )
                                    
                                    if not therapist_codes_from_date:
                                        print(f"[RESCHEDULE PASS2]   No therapists found for date {check_date} - checking next date")
                                        continue
                                    
                                    print(f"[RESCHEDULE PASS2]   Found {len(therapist_codes_from_date)} unique therapist(s) from date {check_date}")
                                    
                                    # Check availability for therapists from this date
                                    date_available_therapists = []
                                    
                                    for therapist_code in therapist_codes_from_date:
                                        try:
                                            therapist = TherapistMaster.objects.filter(
                                                therapist_code=therapist_code,
                                                is_active=True
                                            ).first()
                                            
                                            if therapist:
                                                # Check if therapist is available
                                                # 1. Check weekly leave
                                                if TherapistLeaveMaster.objects.filter(
                                                    therapist=therapist, 
                                                    leave_day=day_of_week
                                                ).exists():
                                                    print(f"[RESCHEDULE PASS2]   Therapist {therapist_code} is on weekly leave - skipping")
                                                    continue

                                                # 1b. Check deputation
                                                from masters.models import is_therapist_deputed, is_therapist_omitted_for_treatment
                                                if is_therapist_deputed(therapist, date):
                                                    print(f"[RESCHEDULE PASS2]   Therapist {therapist_code} is deputed - skipping")
                                                    continue
                                                if is_therapist_omitted_for_treatment(therapist, therapy_name):
                                                    print(f"[RESCHEDULE PASS2]   Therapist {therapist_code} omitted treatment {therapy_name} - skipping")
                                                    continue
                                                
                                                # 2. Check if already booked at this date+time_slot
                                                if canonical_slot and TherapistBooking.objects.filter(
                                                    therapist=therapist,
                                                    date=date,
                                                    time_slot=canonical_slot,
                                                    status='BOOKED'
                                                ).exists():
                                                    print(f"[RESCHEDULE PASS2]   Therapist {therapist_code} already booked at {date} {canonical_slot} - skipping")
                                                    continue
                                                
                                                # 3. Check daily session limit (max 6 sessions)
                                                session_count = TherapistBooking.objects.filter(
                                                    therapist=therapist,
                                                    date=date,
                                                    status='BOOKED'
                                                ).count()
                                                
                                                if session_count >= 6:
                                                    print(f"[RESCHEDULE PASS2]   Therapist {therapist_code} has reached max sessions (6) - skipping")
                                                    continue
                                                
                                                # Therapist is available
                                                if therapist_code not in available_history_therapists:
                                                    date_available_therapists.append(therapist_code)
                                                    available_history_therapists.append(therapist_code)
                                                    print(f"[RESCHEDULE PASS2]   [OK] Therapist {therapist_code} is available - adding to last_therapists")
                                                
                                        except Exception as e:
                                            print(f"[RESCHEDULE PASS2]   Error checking therapist {therapist_code}: {e}")
                                            continue
                                    
                                    # If we found available therapists from this date, we can stop checking further dates
                                    # (prioritize most recent date's therapists)
                                    if date_available_therapists:
                                        print(f"[RESCHEDULE PASS2] [OK] Found {len(date_available_therapists)} available therapist(s) from date {check_date} - stopping date check")
                                        break
                                
                                if available_history_therapists:
                                    last_therapists = available_history_therapists
                                    print(f"[RESCHEDULE PASS2] [OK] ASSIGNED {len(available_history_therapists)} therapist(s) from PatientHistory (checked {dates_checked} date(s)): {available_history_therapists}")
                                else:
                                    print(f"[RESCHEDULE PASS2] [FAIL] No available therapists found after checking {dates_checked} date(s) from PatientHistory")
                            else:
                                print(f"[RESCHEDULE PASS2] [FAIL] No history records found for patient {patient_reg_no}")
                        else:
                            print(f"[RESCHEDULE PASS2] ========== END PATIENT HISTORY CHECK (Not a repeated visitor) ==========")
                    else:
                        print(f"[RESCHEDULE PASS2] [FAIL] Patient registration number not found")
                else:
                    print(f"[RESCHEDULE PASS2] [FAIL] Patient object not found in allocation")
            except Exception as e:
                print(f"[RESCHEDULE PASS2] [FAIL] ERROR querying PatientHistory: {e}")
                import traceback
                traceback.print_exc()
            print(f"[RESCHEDULE PASS2] ========== END PATIENT HISTORY CHECK ==========")
        
        # When PASS 1 assigned continuity therapists, add them DIRECTLY to candidate_therapists
        # (bypassing allocate_therapists which would skip them because their PASS 1 BOOKED records
        # make them appear "already booked at this slot"). Only call allocate_therapists for
        # the remaining slots.
        if pass1_continuity_objects and pass1_continuity_assigned:
            candidate_therapists = list(pass1_continuity_objects)
            remaining_req = dict(pass1_continuity_assigned.get('remaining_requirements', {}))
            if 'therapy_code' not in remaining_req or not remaining_req['therapy_code']:
                remaining_req['therapy_code'] = therapy_req.get('therapy_code') or getattr(allocation, 'therapy_code', None)
            if 'therapy_name' not in remaining_req or not remaining_req['therapy_name']:
                remaining_req['therapy_name'] = therapy_req.get('therapy_name') or getattr(allocation, 'therapy_name', None) or therapy_name
            remaining_total = remaining_req.get('total', 0)
            print(f"[RESCHEDULE PASS2] Prepended {len(pass1_continuity_objects)} PASS 1 continuity therapists to candidate_therapists")
            if remaining_total > 0:
                continuity_codes_to_avoid = {
                    getattr(t, 'therapist_code', None)
                    for t in pass1_continuity_objects
                    if getattr(t, 'therapist_code', None)
                }
                remaining_last_therapists = [c for c in last_therapists if c not in continuity_codes_to_avoid] if last_therapists else None
                if remaining_last_therapists:
                    treatment_to_check = remaining_req.get('therapy_code') or remaining_req.get('therapy_name') or therapy_name
                    if treatment_to_check:
                        from masters.models import is_therapist_omitted_for_treatment
                        remaining_last_therapists = [c for c in remaining_last_therapists if not is_therapist_omitted_for_treatment(c, treatment_to_check)]
                additional = allocate_therapists(
                    date,
                    canonical_slot,
                    remaining_req,
                    remaining_last_therapists if remaining_last_therapists else None,
                    needs_bath_flag and not pass1_continuity_assigned.get('bath_assigned'),
                    patient_gender=pat_sex,
                    patient_id=patient_reg_no,
                    allow_helping_fallback=allow_helping_fallback,
                    patient_age=pat_age,
                    create_bookings=create_bookings,
                )
                candidate_therapists.extend(additional)
                print(f"[RESCHEDULE PASS2] Added {len(additional)} additional therapists for remaining slots")
        else:
            candidate_therapists = allocate_therapists(
                date,
                canonical_slot,
                therapy_req,
                last_therapists if last_therapists else None,
                needs_bath_flag,
                patient_gender=pat_sex,
                patient_id=patient_reg_no,
                allow_helping_fallback=allow_helping_fallback,
                patient_age=pat_age,
                create_bookings=create_bookings,
            )
    except Exception as e:
        print(f"[DEBUG] allocate_therapists exception: {e}")
        candidate_therapists = []

    req_total = int(therapy_req.get("total", 1) or 1)
    
    # FALLBACK: If normal allocation failed, try with aggressive grade substitution
    use_grade_substitution = False
    if len(candidate_therapists) < req_total:
        print(f"[RESCHEDULE FALLBACK] Normal allocation failed: found {len(candidate_therapists)}/{req_total} therapists")
        print(f"[RESCHEDULE FALLBACK] Attempting allocation with grade substitution (Senior/Super Senior can fill Junior/Trainee slots)")
        
        try:
            candidate_therapists_fallback = allocate_therapists_with_grade_substitution(
                date,
                canonical_slot,
                therapy_req,
                last_therapists if last_therapists else None,
                needs_bath_flag,
                patient_gender=pat_sex,
                allow_helping_fallback=allow_helping_fallback,
                patient_age=pat_age,
                patient_id=patient_reg_no,
                create_audit_logs=create_bookings,
            )
            
            if len(candidate_therapists_fallback) >= req_total:
                candidate_therapists = candidate_therapists_fallback
                use_grade_substitution = True
                print(f"[RESCHEDULE FALLBACK] [OK] Grade substitution successful: found {len(candidate_therapists)}/{req_total} therapists")
            else:
                print(f"[RESCHEDULE FALLBACK] [FAIL] Grade substitution also failed: found {len(candidate_therapists_fallback)}/{req_total} therapists")
        except Exception as e:
            print(f"[RESCHEDULE FALLBACK] Error in grade substitution fallback: {e}")
            import traceback
            traceback.print_exc()

    pat_reg_id = getattr(getattr(allocation, 'patient', None), 'pat_reg_no', None) or getattr(allocation, 'patient_id', None) or patient_reg_no
    from Sheduling.vip_service import is_patient_vip
    is_vip_booking = (
        getattr(booking, 'is_vip', False) or
        getattr(allocation, 'is_vip', False) or
        is_patient_vip(pat_reg_id) or
        is_patient_vip(getattr(allocation, 'patient', None))
    )

    if is_vip_booking and create_bookings and len(candidate_therapists) < req_total:
        print(f"[VIP FAIL-SAFE Reschedule] Shortage for VIP booking {booking_id} ({len(candidate_therapists)}/{req_total}). Attempting preemption...")
        try:
            conf_tbs = TherapistBooking.objects.filter(
                date=date,
                time_slot=canonical_slot,
                status='BOOKED'
            ).select_related('therapist', 'visit')
            for c_tb in conf_tbs:
                if len(candidate_therapists) >= req_total:
                    break
                if c_tb.therapist and c_tb.therapist not in candidate_therapists:
                    from Sheduling.preferred_therapist_service import displace_non_vip_therapist_for_slot
                    displace_non_vip_therapist_for_slot(
                        c_tb.therapist, date, canonical_slot,
                        exclude_therapist_codes=[getattr(t, 'therapist_code', '') for t in candidate_therapists]
                    )

            candidate_therapists = allocate_therapists(
                date,
                canonical_slot,
                therapy_req,
                last_therapists if last_therapists else None,
                needs_bath_flag,
                patient_gender=pat_sex,
                patient_id=patient_reg_no,
                allow_helping_fallback=True,
                patient_age=pat_age
            )
        except Exception as e:
            print(f"[VIP FAIL-SAFE Reschedule] Error during preemption/retry: {e}")

    if len(candidate_therapists) < req_total:
        other_vip_conflict_exists = False
        if is_vip_booking and preferred_roster_info:
            pref_codes = preferred_roster_info.get('therapist_codes', [])
            conf_tbs = TherapistBooking.objects.filter(
                date=date,
                time_slot=canonical_slot,
                therapist__therapist_code__in=pref_codes,
                status='BOOKED'
            ).exclude(visit=allocation)
            if patient_reg_no:
                if str(patient_reg_no).isdigit():
                    conf_tbs = conf_tbs.exclude(patient_id=int(patient_reg_no))
                conf_tbs = conf_tbs.exclude(visit__patient__pat_reg_no=str(patient_reg_no))
            for c_tb in conf_tbs:
                c_pat = getattr(getattr(c_tb, 'visit', None), 'patient', None)
                if patient_reg_no and (getattr(c_pat, 'pat_reg_no', None) == str(patient_reg_no) or str(c_tb.patient_id) == str(patient_reg_no)):
                    continue
                from Sheduling.vip_service import is_patient_vip
                if is_patient_vip(c_pat) or is_patient_vip(c_tb.patient_id):
                    other_vip_conflict_exists = True
                    break

        if other_vip_conflict_exists:
            reason = "Preferred therapist is assigned to another VIP patient at this slot. Change slot to reschedule."
        else:
            reason = "insufficient_therapists_available"
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
            day_of_week = date.weekday()
            grade_availability = {}
            for grade, needed in therapy_req.items():
                if grade in ("super_senior","senior","junior","trainee") and int(therapy_req.get(grade,0) or 0) > 0:
                    pool = TherapistMaster.objects.filter(therapist_grade__name__icontains=grade.replace('_',' '), is_active=True)
                    available = 0
                    for t in pool:
                        if desired_gender and _tg(t) != desired_gender:
                            continue
                        if TherapistLeaveMaster.objects.filter(therapist=t, leave_day=day_of_week).exists():
                            continue
                        from masters.models import is_therapist_deputed, is_therapist_omitted_for_treatment
                        if is_therapist_deputed(t, date):
                            continue
                        if is_therapist_omitted_for_treatment(t, therapy_name):
                            continue
                        if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=canonical_slot, status='BOOKED').exists():
                            continue
                        available += 1
                    grade_availability[grade] = available
            gender_info = {"required_gender": desired_gender, "available_matching_gender": match_count, "grade_availability": grade_availability}
            # Append a concise summary into the reason so it's visible in UI
            try:
                reason = f"insufficient_therapists_available (required={req_total}, found={len(candidate_therapists)}, gender={desired_gender or 'n/a'})"
            except Exception:
                pass
        except Exception:
            gender_info = {}
        therapists_for_audit = [{"therapist_code": getattr(t,'therapist_code',str(t)), "is_bathing": False, "is_helping": bool(getattr(t, 'is_helping_therapist', False))} for t in candidate_therapists]
        if AllocationAttempt:
            try:
                AllocationAttempt.objects.create(visit=None, therapy=None, date=date,
                                                 requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                                 status='FAILED', reason=reason, extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id, "therapists": therapists_for_audit, **gender_info})
            except Exception:
                pass
        return ({
            "booking_id": booking_id,
            "allocation_id": allocation.pk,
            "date": date.isoformat(),
            "therapy_name": therapy_name,
            "slot": requested_slot_value,
            "status": "FAILED",
            "reason": reason,
            "room_no": getattr(booking.room, 'room_no', None) if getattr(booking,'room',None) else None,
            "therapists": therapists_for_audit
        }, False, reason)

    # choose bathing assignee
    assigned_therapists = candidate_therapists[:req_total]
    bath_assigned = None
    bath_assigned_from_pass1 = None
    
    # CRITICAL FIX: Ensure previous bathing therapist is in assigned_therapists if available
    # This fixes the issue where previous bathing therapist might be available but not in first req_total positions
    if needs_bath_flag and previous_bathing_therapist:
        if previous_bathing_therapist in candidate_therapists:
            # Previous bathing therapist is in candidate list but might not be in assigned_therapists
            if previous_bathing_therapist not in assigned_therapists:
                # Previous bathing therapist is available but not in assigned_therapists
                # Force them into assigned_therapists by replacing the last therapist if needed
                print(f"[RESCHEDULE PASS2] [WARN] Previous bathing therapist {previous_bathing_therapist.therapist_code} is available but not in first {req_total} positions")
                print(f"[RESCHEDULE PASS2]   Forcing previous bathing therapist into assigned_therapists for continuity")
                
                # Remove last therapist if we're at capacity, or just add if we have space
                if len(assigned_therapists) >= req_total:
                    # Replace last therapist with previous bathing therapist
                    removed = assigned_therapists.pop()
                    print(f"[RESCHEDULE PASS2]   Removed {removed.therapist_code} to make room for previous bathing therapist")
                assigned_therapists.append(previous_bathing_therapist)
                print(f"[RESCHEDULE PASS2] [OK] Previous bathing therapist {previous_bathing_therapist.therapist_code} now in assigned_therapists")
        else:
            # Previous bathing therapist is NOT in candidate_therapists - check if they're still available
            # This might happen if they were filtered out due to session limit or other constraints
            # Try to add them if they meet basic requirements
            print(f"[RESCHEDULE PASS2] [WARN] Previous bathing therapist {previous_bathing_therapist.therapist_code} is NOT in candidate_therapists")
            print(f"[RESCHEDULE PASS2]   Checking if they can still be added for continuity...")
            
            # Check basic availability
            from masters.models import TherapistLeaveMaster, EmergencyLeave
            from django.db.models import Q
            day_of_week = date.weekday()
            can_add = True
            
            # Check if on leave
            if TherapistLeaveMaster.objects.filter(therapist=previous_bathing_therapist, leave_day=day_of_week).exists():
                can_add = False
                print(f"[RESCHEDULE PASS2]   Previous bathing therapist is on leave - cannot add")
            # Check emergency leave
            elif is_therapist_on_emergency_leave(previous_bathing_therapist, date, canonical_slot):
                can_add = False
                print(f"[RESCHEDULE PASS2]   Previous bathing therapist is on emergency leave - cannot add")
            # Check deputation
            elif is_therapist_deputed(previous_bathing_therapist, date):
                can_add = False
                print(f"[RESCHEDULE PASS2]   Previous bathing therapist is deputed - cannot add")
            # Check treatment omission
            elif is_therapist_omitted_for_treatment(previous_bathing_therapist, therapy_name):
                can_add = False
                print(f"[RESCHEDULE PASS2]   Previous bathing therapist omitted treatment {therapy_name} - cannot add")
            # Check if already booked
            elif TherapistBooking.objects.filter(
                therapist=previous_bathing_therapist,
                date=date,
                time_slot=canonical_slot,
                status='BOOKED'
            ).exists():
                can_add = False
                print(f"[RESCHEDULE PASS2]   Previous bathing therapist already booked at this slot - cannot add")
            # Check daily session limit (max 6) - avoid adding then failing at create_therapist_booking_safe
            elif TherapistBooking.objects.filter(
                therapist=previous_bathing_therapist,
                date=date,
                status='BOOKED'
            ).count() >= 6:
                can_add = False
                print(f"[RESCHEDULE PASS2]   Previous bathing therapist at max sessions (6) for this date - cannot add (would fail booking creation)")
            # Check gender match (Rule: Male children below 5 assigned to female therapist)
            elif pat_sex or pat_age:
                desired_gender = resolve_desired_gender(pat_sex, pat_age)
                t_gender = getattr(previous_bathing_therapist, 'therapist_gender', None)
                if t_gender:
                    t_gender_str = str(t_gender).strip().lower()
                    t_gender_normalized = 'female' if t_gender_str.startswith('f') else 'male'
                    if t_gender_normalized != desired_gender:
                        can_add = False
                        print(f"[RESCHEDULE PASS2]   Previous bathing therapist gender mismatch ({t_gender_normalized} vs {desired_gender}) - cannot add")
            
            if can_add:
                # Previous bathing therapist is available - add them to assigned_therapists
                if len(assigned_therapists) >= req_total:
                    removed = assigned_therapists.pop()
                    print(f"[RESCHEDULE PASS2]   Removed {removed.therapist_code} to make room for previous bathing therapist")
                assigned_therapists.append(previous_bathing_therapist)
                print(f"[RESCHEDULE PASS2] [OK] Added previous bathing therapist {previous_bathing_therapist.therapist_code} to assigned_therapists for continuity")
            else:
                print(f"[RESCHEDULE PASS2]   Previous bathing therapist cannot be added due to constraints")
    
    # Extract bath_assigned from PASS 1 continuity if available
    if last_allocation and isinstance(last_allocation, dict):
        continuity_assigned = last_allocation.get('continuity_assigned', {})
        if continuity_assigned and isinstance(continuity_assigned, dict):
            bath_assigned_from_pass1 = continuity_assigned.get('bath_assigned', None)
            if bath_assigned_from_pass1:
                bath_assigned = bath_assigned_from_pass1
                print(f"[RESCHEDULE PASS2] PASS 1 provided bath_assigned: {bath_assigned_from_pass1.therapist_code if bath_assigned_from_pass1 else None}")
                print(f"[RESCHEDULE PASS2] Previous bathing therapist: {previous_bathing_therapist.therapist_code if previous_bathing_therapist else None}")
                print(f"[RESCHEDULE PASS2] Previous bathing therapist in assigned_therapists: {previous_bathing_therapist in assigned_therapists if previous_bathing_therapist else False}")
    
    # Check if this treatment requires special senior therapist handling
    requires_senior_tag = is_treatment_requiring_senior_tag(therapy_name)
    senior_therapist = None
    
    # For special treatments: identify a senior therapist candidate with available senior-tag capacity
    # When grade substitution is used, Super Senior can also get the senior tag
    if requires_senior_tag:
        senior_candidates = []
        for t in assigned_therapists:
            grade_name = getattr(getattr(t, 'therapist_grade', None), 'name', '') if hasattr(t, 'therapist_grade') else ''
            # Allow both Senior and Super Senior to get senior tag (especially when grade substitution is used)
            if 'Senior' in grade_name:
                senior_candidates.append((t, grade_name))
        
        if senior_candidates:
            from math import inf
            best = None
            best_count = inf
            for t, grade_name in senior_candidates:
                current = get_senior_tag_count_for_therapist(t, date)
                # Prefer therapists below the limit of 2; among them pick the one with fewest senior tags
                if current < 2 and current < best_count:
                    best = t
                    best_count = current
            if best is not None:
                senior_therapist = best
                grade_name_best = getattr(getattr(best, 'therapist_grade', None), 'name', '') if hasattr(best, 'therapist_grade') else ''
                if use_grade_substitution and 'Super Senior' in grade_name_best:
                    print(f"[DEBUG] Senior tag (with grade substitution): selected Super Senior {best.therapist_code} with existing senior-tag count={best_count} on {date}")
                else:
                    print(f"[DEBUG] Senior tag: selected senior {best.therapist_code} with existing senior-tag count={best_count} on {date}")
            else:
                # All potential seniors are already at or above the limit -> no senior tag for this booking
                requires_senior_tag = False
                print(f"[DEBUG] Senior tag: no available senior below daily limit for {therapy_name} on {date}")
    
    if needs_bath_flag and assigned_therapists:
        # For special treatments: Senior therapist should NOT be the bathing therapist
        # CRITICAL VALIDATION: Check if PASS 1 assigned same therapist as both bathing and senior
        if requires_senior_tag and senior_therapist and bath_assigned_from_pass1:
            if bath_assigned_from_pass1 == senior_therapist:
                print(f"[RESCHEDULE] [WARN] PASS 1 assigned same therapist as both bathing and senior: {bath_assigned_from_pass1.therapist_code}")
                print(f"[RESCHEDULE] Fixing: Keeping bathing therapist {bath_assigned_from_pass1.therapist_code} (maintain continuity), will reassign senior tag to different senior")
                # Clear senior assignment - will be reassigned below to a different senior
                senior_therapist = None
                requires_senior_tag = is_treatment_requiring_senior_tag(therapy_name)  # Re-enable senior tag requirement
                # Re-select senior therapist from assigned list (excluding bathing therapist)
                senior_candidates = []
                for t in assigned_therapists:
                    grade_name = getattr(getattr(t, 'therapist_grade', None), 'name', '') if hasattr(t, 'therapist_grade') else ''
                    if 'Senior' in grade_name and t != bath_assigned_from_pass1:
                        senior_candidates.append((t, grade_name))
                if senior_candidates:
                    from math import inf
                    best = None
                    best_count = inf
                    for t, _ in senior_candidates:
                        current = get_senior_tag_count_for_therapist(t, date)
                        if current < 2 and current < best_count:
                            best = t
                            best_count = current
                    if best:
                        senior_therapist = best
                        print(f"[RESCHEDULE] [OK] Reassigned senior tag to {best.therapist_code} (bathing {bath_assigned_from_pass1.therapist_code} maintained)")
        
        if requires_senior_tag and senior_therapist:
            # Exclude senior therapist from bathing assignment
            bathing_candidates = [t for t in assigned_therapists if t != senior_therapist and getattr(t, 'is_bathing_therapist', False)]
            
            # PREFERRED ROSTER: Priority for roster's designated bathing therapist
            roster_bath = None
            if patient_id and needs_bath_flag:
                try:
                    from Sheduling.preferred_therapist_service import get_active_preferred_roster, pick_bathing_therapist_from_roster
                    _r_info = get_active_preferred_roster(patient_id)
                    if _r_info:
                        roster_bath, _ = pick_bathing_therapist_from_roster(_r_info, date, canonical_slot)
                except Exception:
                    roster_bath = None

            # CRITICAL: Prefer roster_bath first, then bath_assigned_from_pass1, then previous_bathing_therapist.
            if roster_bath and roster_bath in bathing_candidates:
                bath_assigned = roster_bath
                print(f"[RESCHEDULE] [OK] Special treatment: Using preferred roster bathing therapist {bath_assigned.therapist_code} (senior {senior_therapist.therapist_code} excluded)")
            elif bath_assigned_from_pass1 and bath_assigned_from_pass1 in bathing_candidates:
                bath_assigned = bath_assigned_from_pass1
                print(f"[RESCHEDULE] [OK] Special treatment: Using PASS 1 bathing therapist {bath_assigned.therapist_code} (from start of therapy, senior {senior_therapist.therapist_code} excluded)")
            elif previous_bathing_therapist and previous_bathing_therapist in bathing_candidates:
                if bath_assigned != previous_bathing_therapist:
                    print(f"[RESCHEDULE] [WARN] Special treatment: Overriding PASS 1 bathing therapist {bath_assigned.therapist_code if bath_assigned else None} with previous bathing therapist {previous_bathing_therapist.therapist_code} for continuity")
                bath_assigned = previous_bathing_therapist
                print(f"[RESCHEDULE] [OK] Special treatment: Using previous bathing therapist {previous_bathing_therapist.therapist_code} (maintaining continuity, senior {senior_therapist.therapist_code} excluded)")
            elif bathing_candidates:
                # Prefer non-senior therapist for bathing in special treatments
                bathing_candidates.sort(key=lambda t: 0 if not ('Senior' in getattr(getattr(t, 'therapist_grade', None), 'name', '')) else 1)
                # Pick first available bathing therapist (excluding senior)
                bath_assigned = bathing_candidates[0]
                print(f"[RESCHEDULE] Special treatment: Assigned bathing therapist {bath_assigned.therapist_code} (senior {senior_therapist.therapist_code} excluded)")
            else:
                # No bathing therapist available except senior - need to find another senior or fail
                # Try to find next available senior therapist who is also a bathing therapist
                print(f"[DEBUG] Dhara & Pizichil: Senior {senior_therapist.therapist_code} is the only bathing therapist. Looking for alternative senior...")
                
                # Get all available senior therapists (excluding current senior)
                # When grade substitution is used, also consider Super Senior therapists
                if use_grade_substitution:
                    alternative_seniors = TherapistMaster.objects.filter(
                        therapist_grade__name__in=['Senior Therapist', 'Super Senior Therapist'],
                        is_active=True
                    ).exclude(
                        therapist_code=senior_therapist.therapist_code
                    )
                    print(f"[DEBUG] Grade substitution active: Also considering Super Senior therapists as alternatives")
                else:
                    alternative_seniors = TherapistMaster.objects.filter(
                        therapist_grade__name='Senior Therapist',
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
                day_of_week = date.weekday()
                for alt_senior in alternative_seniors:
                    if TherapistBooking.objects.filter(therapist=alt_senior, date=date, time_slot=canonical_slot, status='BOOKED').exists():
                        continue
                    if TherapistLeaveMaster.objects.filter(therapist=alt_senior, leave_day=day_of_week).exists():
                        continue
                    # Check emergency leave
                    from masters.models import is_therapist_on_emergency_leave, is_therapist_deputed, is_therapist_omitted_for_treatment
                    if is_therapist_on_emergency_leave(alt_senior, date, canonical_slot):
                        continue
                    # Check deputation
                    if is_therapist_deputed(alt_senior, date):
                        continue
                    # Check treatment omission
                    if is_therapist_omitted_for_treatment(alt_senior, therapy_name):
                        continue
                    
                    # Found alternative senior - replace current senior and use this one for bathing
                    print(f"[DEBUG] Dhara & Pizichil: Found alternative senior {alt_senior.therapist_code} who can be bathing therapist")
                    # Replace senior in assigned list
                    assigned_therapists = [alt_senior if t == senior_therapist else t for t in assigned_therapists]
                    senior_therapist = alt_senior
                    bath_assigned = alt_senior
                    break
                
                if not bath_assigned:
                    # No alternative senior found - fail allocation
                    reason = "bathing_therapist_unavailable: Senior therapist for Dhara & Pizichil cannot be bathing therapist, and no alternative senior available"
                    print(f"[DEBUG] FAILING allocation: Dhara & Pizichil - Senior {senior_therapist.therapist_code} is only bathing therapist and no alternative found. Patient: {patient_id}, Date: {date}")
                    
                    if create_bookings and booking:
                        try:
                            booking.status = 'failed'
                            booking.failure_reason = (str(reason) or '')[:512]
                            booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                        except Exception as e:
                            print(f"Error updating booking {booking_id} to failed: {e}")
                    
                    therapists_for_audit = [{"therapist_code": getattr(t,'therapist_code',str(t)), "is_bathing": False} for t in assigned_therapists]
                    if AllocationAttempt and create_bookings:
                        try:
                            AllocationAttempt.objects.create(
                                visit=None, therapy=None, date=date,
                                requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                status='FAILED', reason=reason,
                                extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id, "therapists": therapists_for_audit, "bathing_required": True, "senior_therapist": senior_therapist.therapist_code if senior_therapist else None}
                            )
                        except Exception:
                            pass
                    return ({
                        "booking_id": booking_id,
                        "allocation_id": allocation.pk,
                        "date": date.isoformat(),
                        "therapy_name": therapy_name,
                        "slot": requested_slot_value,
                        "status": "FAILED",
                        "reason": reason,
                        "room_no": getattr(booking.room, 'room_no', None) if getattr(booking,'room',None) else None,
                        "therapists": therapists_for_audit
                    }, False, reason)
        else:
            # Not special treatment or no senior therapist - use normal logic
            roster_bath = None
            if patient_id and needs_bath_flag:
                try:
                    from Sheduling.preferred_therapist_service import get_active_preferred_roster, pick_bathing_therapist_from_roster
                    _r_info = get_active_preferred_roster(patient_id)
                    if _r_info:
                        roster_bath, _ = pick_bathing_therapist_from_roster(_r_info, date, canonical_slot)
                except Exception:
                    roster_bath = None

            if roster_bath and roster_bath in assigned_therapists:
                bath_assigned = roster_bath
                print(f"[RESCHEDULE] [OK] Using preferred roster bathing therapist {bath_assigned.therapist_code} for patient {patient_id}")
            elif bath_assigned_from_pass1 and bath_assigned_from_pass1 in assigned_therapists:
                # PASS 1 chose the first-day bathing therapist - keep them
                bath_assigned = bath_assigned_from_pass1
                print(f"[RESCHEDULE] [OK] Using PASS 1 bathing therapist {bath_assigned.therapist_code} for patient {patient_id} (first-day continuity)")
            elif previous_bathing_therapist and previous_bathing_therapist in assigned_therapists:
                # Fallback: previous day's bathing therapist when PASS 1 therapist not in list
                if bath_assigned != previous_bathing_therapist:
                    print(f"[RESCHEDULE] Using previous bathing therapist {previous_bathing_therapist.therapist_code} (PASS 1 therapist not in assigned list)")
                bath_assigned = previous_bathing_therapist
                print(f"[RESCHEDULE] [OK] Using previous bathing therapist {previous_bathing_therapist.therapist_code} for patient {patient_id} (maintaining continuity)")
            else:
                # PASS 1 / previous bathing therapist not in assigned_therapists (e.g. cancelled,
                # on leave, or at max sessions). Reset bath_assigned and pick from the actual list.
                if bath_assigned and bath_assigned not in assigned_therapists:
                    print(f"[RESCHEDULE] [WARN] PASS 1 bathing therapist {getattr(bath_assigned, 'therapist_code', '?')} is NOT in assigned_therapists - resetting to pick from assigned list")
                    bath_assigned = None
                if not bath_assigned:
                    bath_assigned = next((t for t in assigned_therapists if getattr(t, 'is_bathing_therapist', False)), None)
                    if bath_assigned:
                        print(f"[RESCHEDULE] Using first assigned bathing therapist {bath_assigned.therapist_code} for patient {patient_id} (no continuity available)")
                
                # If no bathing therapist available in assigned list, FAIL the allocation
                if not bath_assigned:
                    reason = "bathing_therapist_unavailable: No bathing therapist available for this therapy"
                    print(f"[DEBUG] FAILING allocation: Therapy requires bathing but no bathing therapist available. Patient: {patient_id}, Date: {date}")
                    
                    # Update booking status to failed
                    if create_bookings and booking:
                        try:
                            booking.status = 'failed'
                            booking.failure_reason = (str(reason) or '')[:512]
                            booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                        except Exception as e:
                            print(f"Error updating booking {booking_id} to failed: {e}")
                    
                    therapists_for_audit = [{"therapist_code": getattr(t,'therapist_code',str(t)), "is_bathing": False} for t in assigned_therapists]
                    if create_bookings and AllocationAttempt:
                        try:
                            AllocationAttempt.objects.create(
                                visit=None, therapy=None, date=date,
                                requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                status='FAILED', reason=reason,
                                extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id, "therapists": therapists_for_audit, "bathing_required": True}
                            )
                        except Exception:
                            pass
                    return ({
                        "booking_id": booking_id,
                        "allocation_id": allocation.pk,
                        "date": date.isoformat(),
                        "therapy_name": therapy_name,
                        "slot": requested_slot_value,
                        "status": "FAILED",
                        "reason": reason,
                        "room_no": getattr(booking.room, 'room_no', None) if getattr(booking,'room',None) else None,
                        "therapists": therapists_for_audit
                    }, False, reason)

    # build therapist audit list - mark senior therapist for special treatments and helping therapist
    therapists_for_audit = []
    for t in assigned_therapists:
        is_bath = (t == bath_assigned)
        # Only mark senior therapist if it's a special treatment AND the therapist is not bathing
        is_senior = (requires_senior_tag and t == senior_therapist and not is_bath)
        is_helping = bool(getattr(t, 'is_helping_therapist', False))
        therapist_dict = {
            "therapist_code": getattr(t, 'therapist_code', str(t)),
            "is_bathing": is_bath,
            "is_helping": is_helping
        }
        if is_senior:
            therapist_dict["is_senior"] = True  # Mark senior therapist for UI highlighting
        therapists_for_audit.append(therapist_dict)

    # room allocation if needed (never blindly reuse a stale room from a failed booking)
    room_candidate = None if getattr(booking, 'status', None) == 'failed' else getattr(booking, 'room', None)
    if room_candidate:
        if getattr(booking, 'timeslot', None) != canonical_slot:
            room_candidate = None
        else:
            from Patient.models import RoomBooking
            from Sheduling.models import Booking
            rb_conflict = RoomBooking.objects.filter(
                room=room_candidate,
                date=date,
                time_slot=canonical_slot,
                status__in=['BOOKED', 'scheduled']
            ).exclude(visit__allocation__status='cancelled').exclude(therapy__status='cancelled').exclude(visit__status='cancelled')
            if booking and hasattr(booking, 'pk') and booking.pk:
                rb_conflict = rb_conflict.exclude(visit=booking)
            if allocation and hasattr(allocation, 'pk') and allocation.pk:
                rb_conflict = rb_conflict.exclude(therapy=allocation).exclude(visit__allocation=allocation)
            
            b_conflict = Booking.objects.filter(
                room=room_candidate,
                date=date,
                timeslot=canonical_slot,
                status__in=['scheduled', 'BOOKED']
            ).exclude(status='cancelled').exclude(allocation__status='cancelled')
            if booking and hasattr(booking, 'pk') and booking.pk:
                b_conflict = b_conflict.exclude(pk=booking.pk)
            
            if rb_conflict.exists() or b_conflict.exists():
                room_candidate = None

    if needs_room_flag and not room_candidate:
        try:
            # Get patient staying room from allocation
            patient_staying_room = getattr(allocation.patient, 'pat_room_no', None) if allocation and hasattr(allocation, 'patient') else None
            patient_obj = allocation.patient if allocation and hasattr(allocation, 'patient') else None
            is_wc = getattr(allocation, 'is_wheelchair', False) if allocation else False
            if not is_wc and booking:
                is_wc = getattr(booking, 'is_wheelchair', False)
            # Pass therapy_name and patient_id for Dhara & Pizichil special handling
            room_candidate = allocate_treatment_room(
                date, 
                canonical_slot, 
                last_allocation.get("last_t_room") if last_allocation else None,
                therapy_name=therapy_name,
                patient_id=patient_id,
                patient_staying_room=patient_staying_room,
                patient=patient_obj,
                booking_id=booking_id,
                is_wheelchair=is_wc
            )
        except Exception:
            room_candidate = None

    if needs_room_flag and not room_candidate:
        # Build detailed error message based on patient staying room or OP status
        reason = "no_room_available"
        if getattr(allocation, 'is_wheelchair', False) or (booking and getattr(booking, 'is_wheelchair', False)):
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
        # Check if this is Dhara & Pizhichil and we had an assigned room that's unavailable
        elif is_dhara_pizhichil_treatment(therapy_name=therapy_name):
            prev_room = get_dhara_pizhichil_assigned_room(patient_id=patient_id, patient=patient_obj)
            if prev_room:
                reason = f"previous_room_unavailable: Original Dhara & Pizhichil room {prev_room.room_no} is unavailable at this slot"
            else:
                reason = "no_room_available: No suitable room available for Dhara & Pizhichil treatment"
        if allocation and hasattr(allocation, 'patient'):
            patient_staying_room = getattr(allocation.patient, 'pat_room_no', None)
            if patient_staying_room:
                staying_room_upper = str(patient_staying_room).strip().upper()
                # Check if it's an OP- prefix (not a real staying room)
                if staying_room_upper.startswith('OP-'):
                    # This is an OP patient identifier, not a real staying room
                    # Check if OP patient has CT room
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
            else:
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
        if AllocationAttempt:
            try:
                AllocationAttempt.objects.create(visit=None, therapy=None, date=date,
                                                 requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                                 status='FAILED', reason=reason, extra={"booking_id": booking_id, "therapists": therapists_for_audit})
            except Exception:
                pass
        return ({
            "booking_id": booking_id,
            "allocation_id": allocation.pk,
            "date": date.isoformat(),
            "therapy_name": therapy_name,
            "slot": requested_slot_value,
            "status": "FAILED",
            "reason": reason,
            "room_no": None,
            "therapists": therapists_for_audit
        }, False, reason)

    # FINAL SAFETY CHECK: Ensure bath_assigned is actually in assigned_therapists.
    # Prevents the scenario where PASS 1 set bath_assigned to a therapist that
    # ended up NOT being in the final assigned list (e.g. cancelled, on leave,
    # at max sessions), which would cause all bookings to have is_bathing=False.
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

    # Attempt atomic creation/confirmation
    try:
        with transaction.atomic():
            rb_obj = None
            if needs_room_flag and create_bookings:
                # Pass booking (Booking) as visit parameter - RoomBooking.visit expects Booking, not TherapyAllocation
                # Also set therapy field to link to TherapyAllocation
                rb_obj, rb_created = create_room_booking_safe(room_candidate, date, canonical_slot, therapy_name, patient_id, booking)
                # Set therapy field to link to TherapyAllocation
                if rb_obj and allocation:
                    rb_obj.therapy = allocation
                    rb_obj.save(update_fields=['therapy'])
                if not rb_created:
                    raise RuntimeError("room_already_booked")
            elif needs_room_flag:
                rb_obj = booking if getattr(booking, 'room', None) else None

            tb_objs = []
            pass1_ids = {getattr(t, 'id', None) for t in pass1_continuity_objects} if pass1_continuity_objects else set()
            for t in assigned_therapists:
                is_bath_for_t = (t in bath_assigned_set)
                if create_bookings:
                    is_pass1 = getattr(t, 'id', None) in pass1_ids if pass1_ids else False
                    if is_pass1:
                        from Patient.models import TherapistBooking as _TBp1
                        tb_obj = _TBp1.objects.filter(
                            therapist=t, date=date, time_slot=canonical_slot, status='BOOKED'
                        ).first()
                        if tb_obj:
                            if is_bath_for_t and not getattr(tb_obj, 'is_bathing', False):
                                tb_obj.is_bathing = True
                                tb_obj.save(update_fields=['is_bathing'])
                            if tb_obj.visit_id != allocation.id:
                                tb_obj.visit = allocation
                                tb_obj.save(update_fields=['visit'])
                            tb_objs.append(tb_obj)
                            print(f"[RESCHEDULE PASS2] Reused existing PASS 1 TherapistBooking pk={tb_obj.pk} for {t.therapist_code}")
                            continue
                    # Pass allocation (TherapyAllocation) as visit parameter - CRITICAL for is_bathing flag to work
                    tb_obj, tb_created = create_therapist_booking_safe(t, date, canonical_slot, therapy_name, patient_id, allocation, is_bathing=is_bath_for_t)
                    if tb_obj is None:
                        # Booking was blocked due to session limit (>= 6 sessions)
                        raise RuntimeError(f"therapist_session_limit_exceeded:{getattr(t,'therapist_code',str(t))}")
                    if not tb_created:
                        if is_pass1:
                            print(f"[RESCHEDULE PASS2] PASS 1 therapist {t.therapist_code} already booked (reusing)")
                            tb_objs.append(tb_obj)
                            continue
                        # Booking already exists (race condition or duplicate)
                        raise RuntimeError(f"therapist_already_booked:{getattr(t,'therapist_code',str(t))}")
                    tb_objs.append(tb_obj)
                else:
                    tb_objs.append(SimpleNamespace(therapist_code=getattr(t,'therapist_code',str(t)), is_bathing=is_bath_for_t))

            # Clean up any extra TherapistBooking rows for this visit/date/slot that are
            # not part of the final assigned_therapists list. This prevents over-booking
            # (e.g. 5 bookings when only 3 therapists are actually required/assigned).
            if create_bookings:
                try:
                    from Patient.models import TherapistBooking as _TB
                    assigned_ids = {getattr(t, 'id', None) for t in assigned_therapists if getattr(t, 'id', None)}
                    extra_qs = _TB.objects.filter(
                        visit=allocation,
                        date=date,
                        time_slot=canonical_slot,
                        status='BOOKED',
                    )
                    if assigned_ids:
                        extra_qs = extra_qs.exclude(therapist_id__in=assigned_ids)
                    extra_count = extra_qs.count()
                    if extra_count:
                        print(f"[RESCHEDULE] Cleaning up {extra_count} extra TherapistBooking rows for allocation {allocation.pk} on {date} at {canonical_slot}")
                        extra_qs.delete()
                except Exception as e:
                    print(f"[RESCHEDULE] Error cleaning up extra TherapistBooking rows: {e}")
            # success audit
            if create_bookings and AllocationAttempt:
                try:
                    extra_data = {
                        "room_no": getattr(room_candidate,'room_no',None) if room_candidate else None,
                        "therapists": therapists_for_audit,
                        "booking_id": booking_id
                    }
                    # Add grade substitution flag if used
                    if use_grade_substitution:
                        extra_data["grade_substitution_used"] = True
                        extra_data["substitution_note"] = "Senior/Super Senior therapists used to fill Junior/Trainee requirements"
                    AllocationAttempt.objects.create(visit=None, therapy=None, date=date,
                                                     requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                                     status='SUCCESS', reason='slot_booked', extra=extra_data)
                except Exception:
                    pass

            # mark used slot in-run if create_bookings
            if create_bookings:
                used_slots.append(canonical_slot)

            # update booking row (ONLY when create_bookings=True; dry-run preview must NOT schedule the booking)
            if create_bookings:
                try:
                    booking.timeslot = canonical_slot
                    booking.room = room_candidate or booking.room
                    booking.status = 'scheduled'
                    booking.failure_reason = ''
                    booking.save(update_fields=['timeslot', 'room', 'status', 'failure_reason', 'updated_at'])
                except Exception as e:
                    print(f"[ERROR Reschedule] Failed to update booking {booking_id}: {e}")
                    raise e

            # ensure UI-visible assignments are created for scheduled bookings
            if create_bookings:
                try:
                    from Sheduling.models import BookingAssignment
                    from Patient.models import Therapist as PatientTherapist
                    assigned_codes = [getattr(t, 'therapist_code', None) or str(t) for t in assigned_therapists]
                    BookingAssignment.objects.filter(booking=booking).exclude(therapist__therapist_code__in=assigned_codes).delete()
                    for t in assigned_therapists:
                        try:
                            therapist_code = getattr(t, 'therapist_code', None) or str(t)
                            # resolve to Patient.models.Therapist by code
                            pt = PatientTherapist.objects.filter(pk=therapist_code).first()
                            if not pt:
                                # create minimal therapist record for display if missing
                                pt = PatientTherapist.objects.create(
                                    therapist_code=therapist_code,
                                    therapist_name=getattr(t, 'therapist_name', therapist_code),
                                    therapist_grade=get_therapist_grade_name(t) or '' ,
                                    is_bathing_therapist=bool(getattr(t, 'is_bathing_therapist', False))
                                )

                            # avoid duplicates and unique constraint failures from stale/released assignments
                            existing = BookingAssignment.objects.filter(
                                therapist=pt,
                                booking_date=date,
                                booking_timeslot=canonical_slot
                            ).first()
                            
                            if existing:
                                existing.booking = booking
                                existing.status = 'assigned'
                                existing.assigned_for = 'booking'
                                existing.save()
                            else:
                                BookingAssignment.objects.create(
                                    booking=booking,
                                    therapist=pt,
                                    assigned_for='booking',
                                    status='assigned'
                                )
                        except Exception as e:
                            print(f"[ERROR BookingAssignment] Failed for therapist {getattr(t, 'therapist_code', str(t))}: {e}")
                            continue
                except Exception as e:
                    # If BookingAssignment model isn't available or fails, continue; UI may fall back to related bookings
                    print(f"[ERROR BookingAssignment] Fatal error in creating assignments: {e}")
                    pass

            task = {
                "booking_id": booking_id,
                "allocation_id": allocation.pk,
                "date": date.isoformat(),
                "therapy_name": therapy_name,
                "slot": requested_slot_value,
                "status": "BOOKED",
                "reason": None,
                "room_no": getattr(room_candidate,"room_no",None) if room_candidate else getattr(booking.room,"room_no",None) if getattr(booking,"room",None) else None,
                "therapists": therapists_for_audit
            }
            # Add grade substitution flag if used
            if use_grade_substitution:
                task["grade_substitution_used"] = True
                task["substitution_note"] = "Senior/Super Senior therapists used to fill Junior/Trainee requirements"
            return (task, True, None)
    except RuntimeError as rte:
        reason = str(rte)
        if AllocationAttempt:
            try:
                AllocationAttempt.objects.create(visit=None, therapy=None, date=date,
                                                 requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                                 status='FAILED', reason=reason, extra={"booking_id": booking_id})
            except Exception:
                pass
        return ({
            "booking_id": booking_id,
            "allocation_id": allocation.pk,
            "date": date.isoformat(),
            "therapy_name": therapy_name,
            "slot": requested_slot_value,
            "status": "FAILED",
            "reason": reason,
            "room_no": getattr(room_candidate,"room_no",None) if room_candidate else None,
            "therapists": therapists_for_audit
        }, False, reason)
    except Exception as exc:
        reason = f"exception:{str(exc)}"
        if AllocationAttempt:
            try:
                AllocationAttempt.objects.create(visit=None, therapy=None, date=date,
                                                 requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                                 status='FAILED', reason=reason, extra={"booking_id": booking_id})
            except Exception:
                pass
        return ({
            "booking_id": booking_id,
            "allocation_id": allocation.pk,
            "date": date.isoformat(),
            "therapy_name": therapy_name,
            "slot": requested_slot_value,
            "status": "FAILED",
            "reason": reason,
            "room_no": getattr(room_candidate,"room_no",None) if room_candidate else None,
            "therapists": therapists_for_audit
        }, False, reason)

