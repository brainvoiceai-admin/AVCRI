# allocation_logic.py
from datetime import datetime, timedelta
from types import SimpleNamespace
from django.db import transaction, IntegrityError

# -----------------------
# Helper: date range
# -----------------------
def daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)

# -----------------------
# Therapy master cache
# -----------------------
therapy_cache = {}
def get_therapy_details(therapy_name):
    """
    Return TherapyMaster row (or None). caches by lowercased name.
    """
    from masters.models import TherapyMaster
    name = (therapy_name or "").strip().lower()
    if not name:
        return None
    if name in therapy_cache:
        return therapy_cache[name]
    # Use filter().first() because duplicate therapy_name rows may exist.
    details = (
        TherapyMaster.objects.filter(therapy_name__iexact=therapy_name)
        .order_by("id")
        .first()
    )
    therapy_cache[name] = details
    return details

# -----------------------
# Therapy attribute helpers
# -----------------------
def therapy_needs_room(allocation_or_booking):
    """
    Determine from allocation or therapy name whether a room is required.
    """
    th_name = getattr(allocation_or_booking, 'therapy_name', None) or getattr(allocation_or_booking, 'therapy', None)
    details = get_therapy_details(th_name) if th_name else None
    return bool(details and str(getattr(details, 'treatment_room_required', '')).lower() == 'yes')

def therapy_needs_bath(allocation_or_booking):
    th_name = getattr(allocation_or_booking, 'therapy_name', None) or getattr(allocation_or_booking, 'therapy', None)
    details = get_therapy_details(th_name) if th_name else None
    return bool(details and str(getattr(details, 'bathing_required', '')).lower() == 'yes')

def therapist_requirements(allocation_or_therapy_obj):
    """
    Return dict with role counts and total from TherapyMaster for a therapy name.
    Accepts a TherapyAllocation instance or object with .therapy_name.
    """
    name = getattr(allocation_or_therapy_obj, 'therapy_name', None)
    details = get_therapy_details(name) if name else None
    if not details:
        return {"super_senior":0, "senior":0, "junior":0, "trainee":0, "total":0, "therapy_code": None, "therapy_category": None}
    return {
        "super_senior": int(getattr(details, 'no_of_super_senior_therapist', 0) or 0),
        "senior": int(getattr(details, 'no_of_senior_therapist', 0) or 0),
        "junior": int(getattr(details, 'no_of_junior_therapist', 0) or 0),
        "trainee": int(getattr(details, 'no_of_trainee_therapist', 0) or 0),
        "total": int(getattr(details, 'total_no_of_therapist', 0) or 0),
        "therapy_code": getattr(details, 'therapy_code', None),
        "therapy_category": getattr(details, 'therapy_category', None)
    }

# -----------------------
# Slot mapping helper
# -----------------------
def map_to_canonical_slot(slot_like):
    """
    Map Booking.timeslot (masters.SlotMaster instance) to the canonical slot model used by TherapistBooking.time_slot FK.
    Matching is done on start_time attribute.
    If slot_like already is instance of canonical model, return it.
    """
    if slot_like is None:
        return None
    # Try to detect canonical slot model from TherapistBooking
    try:
        from Patient.models import TherapistBooking as TBModel
        slot_field = TBModel._meta.get_field('time_slot')
        canonical_model = slot_field.related_model
        # If same class, return slot_like
        if isinstance(slot_like, canonical_model):
            return slot_like
        start = getattr(slot_like, 'start_time', None)
        if start is None:
            return None
        return canonical_model.objects.filter(start_time=start).first()
    except Exception:
        # If anything fails, fallback to returning slot_like
        return slot_like

# -----------------------
# Safe booking creation helpers
# -----------------------
def create_room_booking_safe(room, date, time_slot, therapy_name, patient_id, visit):
    """
    Create RoomBooking safely (handles concurrent creation).
    Returns (room_booking_instance, created_bool)
    """
    from Patient.models import RoomBooking
    try:
        with transaction.atomic():
            rb, created = RoomBooking.objects.get_or_create(
                room=room,
                date=date,
                time_slot=time_slot,
                status='BOOKED',
                defaults={
                    'therapy_name': therapy_name,
                    'patient_id': patient_id,
                    'visit': visit
                }
            )
            if not created and rb.visit is None and visit is not None:
                rb.visit = visit
                rb.save(update_fields=['visit'])
            return rb, created
    except IntegrityError:
        rb = RoomBooking.objects.filter(room=room, date=date, time_slot=time_slot, status='BOOKED').first()
        return rb, False

def create_therapist_booking_safe(therapist, date, time_slot, therapy_name, patient_id, visit):
    """
    Create TherapistBooking safely (handles concurrent creation).
    Returns (therapist_booking_instance, created_bool)
    """
    from Patient.models import TherapistBooking
    try:
        with transaction.atomic():
            tb, created = TherapistBooking.objects.get_or_create(
                therapist=therapist,
                date=date,
                time_slot=time_slot,
                status='BOOKED',
                defaults={
                    'therapy_name': therapy_name,
                    'patient_id': patient_id,
                    'visit': visit
                }
            )
            if not created and tb.visit is None and visit is not None:
                tb.visit = visit
                tb.save(update_fields=['visit'])
            return tb, created
    except IntegrityError:
        tb = TherapistBooking.objects.filter(therapist=therapist, date=date, time_slot=time_slot, status='BOOKED').first()
        return tb, False

# -----------------------
# Room allocation helper
# -----------------------
def allocate_treatment_room(date, time_slot, last_room=None):
    """
    Try to return a TreatmentRoom instance that is free (no RoomBooking with status='BOOKED' at date+slot).
    Preference: last_room -> same floor -> any available.
    """
    from Patient.models import RoomBooking
    from Patient.models import TreatmentRoom
    # prefer last_room
    if last_room:
        try:
            if not RoomBooking.objects.filter(room__room_no=last_room, date=date, time_slot=time_slot, status='BOOKED').exists():
                return TreatmentRoom.objects.get(room_no=last_room)
        except TreatmentRoom.DoesNotExist:
            pass
    # same floor fallback
    if last_room:
        try:
            last_room_obj = TreatmentRoom.objects.get(room_no=last_room)
            same_floor = TreatmentRoom.objects.filter(floor=last_room_obj.floor)
            for r in same_floor:
                if not RoomBooking.objects.filter(room=r, date=date, time_slot=time_slot, status='BOOKED').exists():
                    return r
        except TreatmentRoom.DoesNotExist:
            pass
    # any available room
    for r in TreatmentRoom.objects.all():
        if not RoomBooking.objects.filter(room=r, date=date, time_slot=time_slot, status='BOOKED').exists():
            return r
    return None

# -----------------------
# Slot allocation (unused in strict preferred-only but kept)
# -----------------------
def allocate_treatment_slot(patient_type, therapy_category, used_slots=None):
    general_slots = ["06:30","08:30","10:00","11:30","14:30","16:00","17:30"]
    if patient_type and str(patient_type).upper() == "OP":
        allowed_slots = ["11:30","17:30"]
    elif patient_type and str(patient_type).upper() == "IP":
        allowed_slots = ["06:30","08:30","10:00","14:30","16:00"]
    else:
        allowed_slots = general_slots
    if therapy_category and str(therapy_category).lower() in ["hard","special"]:
        allowed_slots = [s for s in general_slots if s not in ["11:30","17:30"]]
    if used_slots:
        used_slot_strs = [getattr(s, 'start_time').strftime("%H:%M") for s in used_slots if getattr(s, 'start_time', None)]
        allowed_slots = [s for s in allowed_slots if s not in used_slot_strs]
    return allowed_slots[0] if allowed_slots else None

# -----------------------
# Therapist allocation
# -----------------------
def allocate_therapists(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False):
    """
    Return list of TherapistMaster instances fulfilling therapy_requirements for given date+time_slot.

    This version treats a therapist as 'on leave' if either:
      - TherapistLeaveMaster indicates leave for the weekday (recurring leaves), OR
      - EmergencyLeave contains a row covering the date (from_date <= date <= to_date) that either:
          * has therapist FK pointing to the therapist, or
          * has employee_code matching TherapistMaster.employee_code (if that field exists)
    Blocking: TherapistBooking with status='BOOKED' blocks.
    """
    from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave
    from Patient.models import TherapistBooking

    day_of_week = date.weekday()
    allocated = []

    # Shift eligibility (additive): only enforced when shift masters/mappings are configured.
    shift_filter_enabled = False
    mapped_ids, eligible_ids = (set(), set())
    try:
        from masters.models import ShiftSlotMapping, TherapistShiftMapping

        shift_filter_enabled = ShiftSlotMapping.objects.filter(is_active=True).exists() and TherapistShiftMapping.objects.filter(is_active=True).exists()
        if shift_filter_enabled:
            mapped_ids = set(
                TherapistShiftMapping.objects.filter(is_active=True).values_list("therapist_id", flat=True).distinct()
            )
            if mapped_ids:
                eligible_ids = set(
                    TherapistShiftMapping.objects.filter(
                        is_active=True,
                        shift__shift_slots__slot=time_slot,
                        shift__shift_slots__is_active=True,
                    ).values_list("therapist_id", flat=True).distinct()
                )
    except Exception:
        shift_filter_enabled = False

    # Build grade_map expected by allocator
    grade_map = {
        "Super Senior Therapist": therapy_requirements.get("super_senior", 0),
        "Senior Therapist": therapy_requirements.get("senior", 0),
        "Junior Therapist": therapy_requirements.get("junior", 0),
        "Trainee Therapist": therapy_requirements.get("trainee", 0)
    }

    # Preload emergency leaves overlapping the date to avoid per-therapist queries
    # We'll build two quick lookup sets:
    #  - emergency_leave_therapist_ids: therapist FK ids present in EmergencyLeave covering date
    #  - emergency_leave_employee_codes: employee_code values present in EmergencyLeave covering date
    try:
        em_leaves_qs = EmergencyLeave.objects.filter(from_date__lte=date, to_date__gte=date)
        full_day_leaves = []
        half_day_leaves = []
        for el in em_leaves_qs:
            if el.is_half_day and (not el.half_day_date or el.half_day_date == date):
                half_day_leaves.append(el)
            else:
                full_day_leaves.append(el)
        full_leave_therapist_ids = set(el.therapist_id for el in full_day_leaves if el.therapist_id)
        full_leave_emp_codes = set(el.employee_code for el in full_day_leaves if el.employee_code)
    except Exception:
        full_leave_therapist_ids = set()
        full_leave_emp_codes = set()
        half_day_leaves = []

    # Helper to decide if a therapist is on leave (recurring or emergency)
    def therapist_on_leave(t: TherapistMaster, slot=None):
        target_slot = slot if slot is not None else time_slot
        # 1) recurring leave (weekday)
        if TherapistLeaveMaster.objects.filter(therapist=t, leave_day=day_of_week).exists():
            return True
        t_id = getattr(t, 'id', None)
        emp_code = getattr(t, 'employee_code', None)
        if t_id in full_leave_therapist_ids:
            return True
        if emp_code and emp_code in full_leave_emp_codes:
            return True
        for el in half_day_leaves:
            if (t_id and el.therapist_id == t_id) or (emp_code and el.employee_code == emp_code):
                if el.is_slot_on_leave(date, target_slot):
                    return True
        return False

    total_required = sum(v for v in grade_map.values() if v > 0)

    # Helper function for grade allocation
    def _allocate_per_grade(is_helping_flag=False):
        for grade, needed in list(grade_map.items()):
            if needed <= 0:
                continue
            candidates_qs = TherapistMaster.objects.filter(
                therapist_grade=grade, 
                is_active=True,
                is_helping_therapist=is_helping_flag
            )
            if needs_bathing:
                candidates_qs = candidates_qs.filter(is_bathing_therapist=True)

            for t in candidates_qs:
                if t in allocated:
                    continue
                if therapist_on_leave(t):
                    continue
                if shift_filter_enabled and t.id in mapped_ids and t.id not in eligible_ids:
                    continue
                if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                    continue

                allocated.append(t)
                grade_map[grade] -= 1

                if is_helping_flag:
                    try:
                        from Sheduling.models import HelpingTherapistAllocationLog
                        HelpingTherapistAllocationLog.objects.create(
                            patient_id='',
                            helping_therapist=t,
                            date=date,
                            time_slot=str(getattr(time_slot, 'slot_number', time_slot) or ''),
                            therapy_name=str(therapy_requirements.get('therapy_name', '')),
                            reason_for_fallback="Primary therapist shortage/failure",
                            shortage_condition=f"Shortage detected during normal therapist allocation for date {date} slot {time_slot}.",
                            is_supporting_backup=True
                        )
                    except Exception as log_err:
                        print(f"[ERROR HelpingTherapistLog in allocation_logic.py] {log_err}")

                if grade_map[grade] <= 0:
                    break

    # STEP 1: Normal Scheduling (Primary Therapists: is_helping_therapist=False)
    if last_therapists:
        for code in last_therapists:
            try:
                t = TherapistMaster.objects.get(therapist_code=code, is_active=True)
                if getattr(t, 'is_helping_therapist', False):
                    continue
            except TherapistMaster.DoesNotExist:
                continue

            if grade_map.get(t.therapist_grade, 0) > 0:
                if therapist_on_leave(t):
                    continue
                if shift_filter_enabled and t.id in mapped_ids and t.id not in eligible_ids:
                    continue
                if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                    continue
                allocated.append(t)
                grade_map[t.therapist_grade] -= 1

    # Allocate remaining normal primary therapists
    _allocate_per_grade(is_helping_flag=False)

    # STEP 2 & 3: Shortage Detection and Helping Therapist Fallback (is_helping_therapist=True)
    shortage = total_required - len(allocated)
    if shortage > 0:
        if last_therapists:
            for code in last_therapists:
                if len(allocated) >= total_required:
                    break
                try:
                    t = TherapistMaster.objects.get(therapist_code=code, is_active=True, is_helping_therapist=True)
                except TherapistMaster.DoesNotExist:
                    continue
                if t in allocated or therapist_on_leave(t):
                    continue
                if shift_filter_enabled and t.id in mapped_ids and t.id not in eligible_ids:
                    continue
                if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                    continue

                allocated.append(t)
                try:
                    from Sheduling.models import HelpingTherapistAllocationLog
                    HelpingTherapistAllocationLog.objects.create(
                        patient_id='',
                        helping_therapist=t,
                        date=date,
                        time_slot=str(getattr(time_slot, 'slot_number', time_slot) or ''),
                        therapy_name=str(therapy_requirements.get('therapy_name', '')),
                        reason_for_fallback="Primary therapist shortage/failure",
                        shortage_condition="Continuity Helping Therapist fallback triggered due to primary therapist shortage.",
                        is_supporting_backup=True
                    )
                except Exception as log_err:
                    print(f"[ERROR HelpingTherapistLog in allocation_logic.py] {log_err}")

        _allocate_per_grade(is_helping_flag=True)

    return allocated

# -----------------------
# Main: strict preferred-slot-only allocation
# -----------------------
def allocate_for_allocation_date_preferred_only(therapy_allocation_id, target_date, create_bookings=True):
    """
    Strict preferred-slot-only allocation using Booking rows.
    Returns list of task dicts (one per Booking processed).
    """
    # normalize target_date
    if isinstance(target_date, str):
        try:
            target_date = datetime.strptime(target_date, "%Y-%m-%d").date()
        except Exception:
            return {"error": f"Invalid date format: {target_date}. Use YYYY-MM-DD."}

    # Defensive imports (model names per your schema)
    from Sheduling.models import TherapyAllocation, Booking
    from Patient.models import TherapistBooking, RoomBooking, AllocationAttempt
    # Slot model used by Booking is masters.SlotMaster
    from masters.models import SlotMaster

    allocation = TherapyAllocation.objects.filter(pk=therapy_allocation_id).first()
    if not allocation:
        return {"error": f"TherapyAllocation id {therapy_allocation_id} not found."}

    bookings_qs = Booking.objects.filter(allocation_id=therapy_allocation_id, date=target_date)
    if not bookings_qs.exists():
        return {"error": f"No Booking rows found for allocation {therapy_allocation_id} on {target_date.isoformat()}."}

    tasks = []
    used_slots = []   # canonical slot instances used in this run
    any_success = False
    patient_id = getattr(allocation.patient, 'id', None)

    for booking in bookings_qs:
        booking_id = booking.pk
        therapy_name = allocation.therapy_name

        # Preferred slot (strict)
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
            # fail: no preferred slot present
            reason = "no_preferred_slot"
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None,
                        therapy=None,
                        date=target_date,
                        requested_time_slot=None,
                        requested_time_slot_value='',
                        status='FAILED',
                        reason=reason,
                        extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
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
            continue

        # Map to canonical slot expected by TherapistBooking (matching by start_time)
        canonical_slot = map_to_canonical_slot(pref_slot) or pref_slot

        # 1) patient already booked check (RoomBooking/TherapistBooking)
        patient_already_booked = False
        try:
            patient_already_booked = (
                RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=canonical_slot, status__in=['BOOKED','scheduled']).exclude(pk=booking.pk).exists()
                or TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=canonical_slot, status='BOOKED').exclude(pk=booking.pk).exists()
            )
        except Exception:
            # fallback: match on start_time
            try:
                slot_start = getattr(pref_slot, 'start_time', None)
                if slot_start:
                    patient_already_booked = (
                        RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot__start_time=slot_start, status__in=['BOOKED','scheduled']).exclude(pk=booking.pk).exists()
                        or TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot__start_time=slot_start, status='BOOKED').exclude(pk=booking.pk).exists()
                    )
            except Exception:
                patient_already_booked = False

        if patient_already_booked:
            reason = "patient_already_has_booking"
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None,
                        therapy=None,
                        date=target_date,
                        requested_time_slot=canonical_slot,
                        requested_time_slot_value=requested_slot_value or '',
                        status='FAILED',
                        reason=reason,
                        extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id,
                "allocation_id": therapy_allocation_id,
                "date": target_date.isoformat(),
                "therapy_name": therapy_name,
                "slot": requested_slot_value,
                "status": "FAILED",
                "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None,
                "therapists": []
            })
            continue

        # 2) in-run used slot check
        if any(getattr(s, 'start_time', None) == getattr(canonical_slot, 'start_time', None) for s in used_slots):
            reason = "slot_already_used_in_run"
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None,
                        therapy=None,
                        date=target_date,
                        requested_time_slot=canonical_slot,
                        requested_time_slot_value=requested_slot_value or '',
                        status='FAILED',
                        reason=reason,
                        extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id,
                "allocation_id": therapy_allocation_id,
                "date": target_date.isoformat(),
                "therapy_name": therapy_name,
                "slot": requested_slot_value,
                "status": "FAILED",
                "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None,
                "therapists": []
            })
            continue

        # 3) therapist requirements and flags
        try:
            therapy_req = therapist_requirements(allocation)
        except Exception:
            therapy_req = {"total": 1, "therapy_category": None}

        needs_room_flag = therapy_needs_room(allocation) if therapy_needs_room else bool(getattr(booking, 'room', None))
        needs_bath_flag = therapy_needs_bath(allocation) if therapy_needs_bath else False

        # 4) allocate therapists for this canonical slot only
        try:
            candidate_therapists = allocate_therapists(target_date, canonical_slot, therapy_req, None, needs_bath_flag)
        except Exception:
            candidate_therapists = []

        req_total = int(therapy_req.get("total", 1) or 1)
        if len(candidate_therapists) < req_total:
            reason = "insufficient_therapists_available"
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None,
                        therapy=None,
                        date=target_date,
                        requested_time_slot=canonical_slot,
                        requested_time_slot_value=requested_slot_value or '',
                        status='FAILED',
                        reason=reason,
                        extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id,
                "allocation_id": therapy_allocation_id,
                "date": target_date.isoformat(),
                "therapy_name": therapy_name,
                "slot": requested_slot_value,
                "status": "FAILED",
                "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None,
                "therapists": [getattr(t,'therapist_code',str(t)) for t in candidate_therapists]
            })
            continue

        # 5) room allocation if needed
        room_candidate = getattr(booking, 'room', None)
        if needs_room_flag and not room_candidate:
            try:
                room_candidate = allocate_treatment_room(target_date, canonical_slot, None)
            except Exception:
                room_candidate = None

        if needs_room_flag and not room_candidate:
            reason = "no_room_available"
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None,
                        therapy=None,
                        date=target_date,
                        requested_time_slot=canonical_slot,
                        requested_time_slot_value=requested_slot_value or '',
                        status='FAILED',
                        reason=reason,
                        extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id,
                "allocation_id": therapy_allocation_id,
                "date": target_date.isoformat(),
                "therapy_name": therapy_name,
                "slot": requested_slot_value,
                "status": "FAILED",
                "reason": reason,
                "room_no": None,
                "therapists": [getattr(t,'therapist_code',str(t)) for t in candidate_therapists]
            })
            continue

        # 6) create bookings atomically
        try:
            with transaction.atomic():
                rb_obj = None
                if needs_room_flag and create_bookings:
                    rb_obj, rb_created = create_room_booking_safe(room_candidate, target_date, canonical_slot, therapy_name, patient_id, None)
                    if not rb_created:
                        raise RuntimeError("room_already_booked")
                elif needs_room_flag:
                    rb_obj = booking if getattr(booking, 'room', None) else None

                tb_objs = []
                for t in candidate_therapists[:req_total]:
                    if create_bookings:
                        tb_obj, tb_created = create_therapist_booking_safe(t, target_date, canonical_slot, therapy_name, patient_id, None)
                        if not tb_created:
                            raise RuntimeError(f"therapist_already_booked:{getattr(t,'therapist_code',str(t))}")
                        tb_objs.append(tb_obj)
                    else:
                        tb_objs.append(SimpleNamespace(therapist_code=getattr(t, 'therapist_code', str(t))))

                # success audit
                if AllocationAttempt:
                    try:
                        AllocationAttempt.objects.create(
                            visit=None,
                            therapy=None,
                            date=target_date,
                            requested_time_slot=canonical_slot,
                            requested_time_slot_value=requested_slot_value or '',
                            status='SUCCESS',
                            reason='preferred_slot_booked',
                            extra={
                                "room_no": getattr(room_candidate, 'room_no', None) if room_candidate else None,
                                "therapists": [getattr(t,'therapist_code',str(t)) for t in candidate_therapists[:req_total]],
                                "booking_id": booking_id
                            }
                        )
                    except Exception:
                        pass

                # mark used slot for in-run check
                used_slots.append(canonical_slot)

                # update Booking record
                try:
                    # preserve booking.timeslot if it existed; otherwise set canonical_slot
                    booking.timeslot = getattr(booking, 'timeslot', None) or canonical_slot
                    booking.room = room_candidate or booking.room
                    booking.status = 'scheduled'
                    booking.save(update_fields=['timeslot','room','status','updated_at'])
                except Exception:
                    pass

                tasks.append({
                    "booking_id": booking_id,
                    "allocation_id": therapy_allocation_id,
                    "date": target_date.isoformat(),
                    "therapy_name": therapy_name,
                    "slot": requested_slot_value,
                    "status": "BOOKED",
                    "reason": None,
                    "room_no": getattr(room_candidate, "room_no", None) if room_candidate else getattr(booking.room, "room_no", None) if getattr(booking, "room", None) else None,
                    "therapists": [getattr(t,'therapist_code',str(t)) for t in candidate_therapists[:req_total]]
                })
                any_success = True

        except RuntimeError as rte:
            reason = str(rte)
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None,
                        therapy=None,
                        date=target_date,
                        requested_time_slot=canonical_slot,
                        requested_time_slot_value=requested_slot_value or '',
                        status='FAILED',
                        reason=reason,
                        extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id,
                "allocation_id": therapy_allocation_id,
                "date": target_date.isoformat(),
                "therapy_name": therapy_name,
                "slot": requested_slot_value,
                "status": "FAILED",
                "reason": reason,
                "room_no": getattr(room_candidate, "room_no", None) if room_candidate else None,
                "therapists": [getattr(t,'therapist_code',str(t)) for t in candidate_therapists]
            })
            continue

        except Exception as exc:
            reason = f"exception:{str(exc)}"
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None,
                        therapy=None,
                        date=target_date,
                        requested_time_slot=canonical_slot,
                        requested_time_slot_value=requested_slot_value or '',
                        status='FAILED',
                        reason=reason,
                        extra={"booking_id": booking_id}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id,
                "allocation_id": therapy_allocation_id,
                "date": target_date.isoformat(),
                "therapy_name": therapy_name,
                "slot": requested_slot_value,
                "status": "FAILED",
                "reason": reason,
                "room_no": getattr(room_candidate, "room_no", None) if room_candidate else None,
                "therapists": []
            })
            continue

    # update allocation header status
    try:
        allocation.status = 'allocated' if any_success else 'failed'
        allocation.save(update_fields=['status'])
    except Exception:
        pass

    return tasks

# -----------------------
# Optional quick runner
# -----------------------
if __name__ == "__main__":
    # Quick CLI runner when executed directly (ensure DJANGO_SETTINGS_MODULE is set)
    import os
    allocation_id = input("TherapyAllocation id: ").strip()
    date_str = input("Date (YYYY-MM-DD): ").strip()
    try:
        res = allocate_for_allocation_date_preferred_only(int(allocation_id), date_str, create_bookings=True)
        print(res)
    except Exception as e:
        print("Error:", e)
