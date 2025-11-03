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
    from masters.models import TherapyMaster
    name = (therapy_name or "").strip().lower()
    if not name:
        return None
    if name in therapy_cache:
        return therapy_cache[name]
    try:
        details = TherapyMaster.objects.get(therapy_name__iexact=therapy_name)
        therapy_cache[name] = details
        return details
    except TherapyMaster.DoesNotExist:
        therapy_cache[name] = None
        return None

# -----------------------
# Therapy attribute helpers
# -----------------------
def therapy_needs_room(allocation_or_booking):
    th_name = getattr(allocation_or_booking, 'therapy_name', None) or getattr(allocation_or_booking, 'therapy', None)
    details = get_therapy_details(th_name) if th_name else None
    return bool(details and str(getattr(details, 'treatment_room_required', '')).lower() == 'yes')

def therapy_needs_bath(allocation_or_booking):
    th_name = getattr(allocation_or_booking, 'therapy_name', None) or getattr(allocation_or_booking, 'therapy', None)
    details = get_therapy_details(th_name) if th_name else None
    return bool(details and str(getattr(details, 'bathing_required', '')).lower() == 'yes')

def therapist_requirements(allocation_or_therapy_obj):
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
    if slot_like is None:
        return None
    try:
        from Patient.models import TherapistBooking as TBModel
        slot_field = TBModel._meta.get_field('time_slot')
        canonical_model = slot_field.related_model
        if isinstance(slot_like, canonical_model):
            return slot_like
        start = getattr(slot_like, 'start_time', None)
        if start is None:
            return None
        return canonical_model.objects.filter(start_time=start).first()
    except Exception:
        return slot_like

# -----------------------
# Safe booking creation helpers (room + therapist)
# -----------------------
def create_room_booking_safe(room, date, time_slot, therapy_name, patient_id, visit):
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
            # Update visit if it's not set and we have a booking instance
            if not created and rb.visit is None and visit is not None:
                rb.visit = visit
                rb.save(update_fields=['visit'])
            elif created and rb.visit != visit and visit is not None:
                rb.visit = visit
                rb.save(update_fields=['visit'])
            return rb, created
    except IntegrityError:
        rb = RoomBooking.objects.filter(room=room, date=date, time_slot=time_slot, status='BOOKED').first()
        # Try to update visit if not set
        if rb and rb.visit is None and visit is not None:
            try:
                rb.visit = visit
                rb.save(update_fields=['visit'])
            except Exception:
                pass
        return rb, False

def create_therapist_booking_safe(therapist, date, time_slot, therapy_name, patient_id, visit, is_bathing=False):
    """
    Create TherapistBooking safely and optionally set is_bathing if the model has that field.
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
            # persist is_bathing if model supports it and we either created or it's not set
            try:
                if is_bathing and hasattr(tb, 'is_bathing'):
                    # save only if value differs to avoid unnecessary writes
                    if getattr(tb, 'is_bathing', False) != bool(is_bathing):
                        tb.is_bathing = bool(is_bathing)
                        tb.save(update_fields=['is_bathing'])
            except Exception:
                pass
            return tb, created
    except IntegrityError:
        tb = TherapistBooking.objects.filter(therapist=therapist, date=date, time_slot=time_slot, status='BOOKED').first()
        # attempt to mark is_bathing if possible (best-effort, non-fatal)
        try:
            if tb and is_bathing and hasattr(tb, 'is_bathing'):
                if not tb.is_bathing:
                    tb.is_bathing = True
                    tb.save(update_fields=['is_bathing'])
        except Exception:
            pass
        return tb, False

# -----------------------
# Room allocation helper
# -----------------------
def allocate_treatment_room(date, time_slot, last_room=None):
    from Patient.models import RoomBooking, TreatmentRoom
    if last_room:
        try:
            if not RoomBooking.objects.filter(room__room_no=last_room, date=date, time_slot=time_slot, status='BOOKED').exists():
                return TreatmentRoom.objects.get(room_no=last_room)
        except TreatmentRoom.DoesNotExist:
            pass
    if last_room:
        try:
            last_room_obj = TreatmentRoom.objects.get(room_no=last_room)
            same_floor = TreatmentRoom.objects.filter(floor=last_room_obj.floor)
            for r in same_floor:
                if not RoomBooking.objects.filter(room=r, date=date, time_slot=time_slot, status='BOOKED').exists():
                    return r
        except TreatmentRoom.DoesNotExist:
            pass
    for r in TreatmentRoom.objects.all():
        if not RoomBooking.objects.filter(room=r, date=date, time_slot=time_slot, status='BOOKED').exists():
            return r
    return None

# -----------------------
# Slot allocation helper (kept for possible fallback)
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
# Therapist allocation with EmergencyLeave integration
# -----------------------
def allocate_therapists(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False):
    from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave
    from Patient.models import TherapistBooking

    day_of_week = date.weekday()
    allocated = []

    grade_map = {
        "Super Senior Therapist": therapy_requirements.get("super_senior", 0),
        "Senior Therapist": therapy_requirements.get("senior", 0),
        "Junior Therapist": therapy_requirements.get("junior", 0),
        "Trainee Therapist": therapy_requirements.get("trainee", 0)
    }

    # Preload emergency leaves overlapping the date
    try:
        em_leaves_qs = EmergencyLeave.objects.filter(from_date__lte=date, to_date__gte=date)
        emergency_leave_therapist_ids = set(em_leaves_qs.exclude(therapist__isnull=True).values_list('therapist_id', flat=True))
        emergency_leave_employee_codes = set(em_leaves_qs.exclude(employee_code__isnull=True).values_list('employee_code', flat=True))
    except Exception:
        emergency_leave_therapist_ids = set()
        emergency_leave_employee_codes = set()

    def therapist_on_leave(t: TherapistMaster):
        if TherapistLeaveMaster.objects.filter(therapist=t, leave_day=day_of_week).exists():
            return True
        if getattr(t, 'id', None) in emergency_leave_therapist_ids:
            return True
        emp_code = getattr(t, 'employee_code', None)
        if emp_code and emp_code in emergency_leave_employee_codes:
            return True
        return False

    # Use last therapists first
    if last_therapists:
        for code in last_therapists:
            try:
                t = TherapistMaster.objects.get(therapist_code=code)
            except TherapistMaster.DoesNotExist:
                continue
            if grade_map.get(t.therapist_grade, 0) > 0:
                if therapist_on_leave(t):
                    continue
                if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                    continue
                allocated.append(t)
                grade_map[t.therapist_grade] -= 1

    # Allocate remaining
    for grade, needed in list(grade_map.items()):
        if needed <= 0:
            continue
        candidates_qs = TherapistMaster.objects.filter(therapist_grade=grade)
        if needs_bathing:
            candidates_qs = candidates_qs.filter(is_bathing_therapist=True) | candidates_qs
            # above keeps bathing-capable first only if you iterate deterministically; we'll check is_bathing flag explicitly below
        # iterate candidates
        for t in candidates_qs:
            if t in allocated:
                continue
            if therapist_on_leave(t):
                continue
            if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                continue
            allocated.append(t)
            needed -= 1
            if needed <= 0:
                break

    return allocated

# -----------------------
# Main: strict preferred-slot-only allocation with bathing assignee persisted
# -----------------------
def expand_therapies_for_visit(therapy_allocation_id, target_date, create_bookings=True):
    """
    Strict preferred-slot-only allocation using Booking rows.
    Persists TherapistBooking.is_bathing when applicable.
    Returns list of task dicts. Each task['therapists'] is a list of dicts:
      {"therapist_code": "...", "is_bathing": True|False}
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

    bookings_qs = Booking.objects.filter(allocation_id=therapy_allocation_id, date=target_date)
    if not bookings_qs.exists():
        return {"error": f"No Booking rows found for allocation {therapy_allocation_id} on {target_date.isoformat()}."}

    tasks = []
    used_slots = []
    any_success = False
    patient_id = getattr(allocation.patient, 'id', None)

    def therapist_entry(t_obj, is_bath=False):
        return {"therapist_code": getattr(t_obj, 'therapist_code', None) or str(t_obj), "is_bathing": bool(is_bath)}

    for booking in bookings_qs:
        booking_id = booking.pk
        therapy_name = allocation.therapy_name

        # preferred slot only
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
            reason = "no_preferred_slot"
            # Update booking status to failed
            try:
                booking.status = 'failed'
                booking.save(update_fields=['status', 'updated_at'])
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
        # patient already booked check
        patient_already_booked = False
        try:
            patient_already_booked = (
                RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=canonical_slot, status__in=['BOOKED','scheduled']).exclude(pk=booking.pk).exists()
                or TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=canonical_slot, status='BOOKED').exclude(pk=booking.pk).exists()
            )
        except Exception:
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
            # Update booking status to failed
            try:
                booking.status = 'failed'
                booking.save(update_fields=['status', 'updated_at'])
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

        # in-run used slot check
        if any(getattr(s, 'start_time', None) == getattr(canonical_slot, 'start_time', None) for s in used_slots):
            reason = "slot_already_used_in_run"
            # Update booking status to failed
            try:
                booking.status = 'failed'
                booking.save(update_fields=['status', 'updated_at'])
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
        # therapist reqs and flags
        try:
            therapy_req = therapist_requirements(allocation)
        except Exception:
            therapy_req = {"total": 1, "therapy_category": None}

        needs_room_flag = therapy_needs_room(allocation) if therapy_needs_room else bool(getattr(booking, 'room', None))
        needs_bath_flag = therapy_needs_bath(allocation) if therapy_needs_bath else False
        # allocate therapists
        try:
            candidate_therapists = allocate_therapists(target_date, canonical_slot, therapy_req, None, needs_bath_flag)
        except Exception:
            candidate_therapists = []

        req_total = int(therapy_req.get("total", 1) or 1)
        if len(candidate_therapists) < req_total:
            reason = "insufficient_therapists_available"
            therapists_for_audit = [therapist_entry(t, False) for t in candidate_therapists]
            # Update booking status to failed
            try:
                booking.status = 'failed'
                booking.save(update_fields=['status', 'updated_at'])
            except Exception as e:
                print(f"Error updating booking {booking_id} to failed: {e}")
            
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(
                        visit=None, therapy=None, date=target_date,
                        requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                        status='FAILED', reason=reason,
                        extra={"required": req_total, "found": len(candidate_therapists), "booking_id": booking_id, "therapists": therapists_for_audit}
                    )
                except Exception:
                    pass
            tasks.append({
                "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                "therapy_name": therapy_name, "slot": requested_slot_value, "status": "FAILED", "reason": reason,
                "room_no": getattr(booking.room, 'room_no', None) if getattr(booking, 'room', None) else None, "therapists": therapists_for_audit
            })
            continue

        # choose single bathing-assigned therapist if bathing required
        assigned_therapists = candidate_therapists[:req_total]
        bath_assigned = None
        if needs_bath_flag and assigned_therapists:
            bath_assigned = next((t for t in assigned_therapists if getattr(t, 'is_bathing_therapist', False)), None)
            if not bath_assigned:
                bath_assigned = assigned_therapists[0]
        # build therapist audit list
        therapists_for_audit = [therapist_entry(t, is_bath=(t == bath_assigned)) for t in assigned_therapists]
        # room allocation
        room_candidate = getattr(booking, 'room', None)
        if needs_room_flag and not room_candidate:
            try:
                room_candidate = allocate_treatment_room(target_date, canonical_slot, None)
            except Exception:
                room_candidate = None
        if needs_room_flag and not room_candidate:
            reason = "no_room_available"
            # Update booking status to failed
            try:
                booking.status = 'failed'
                booking.save(update_fields=['status', 'updated_at'])
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
        try:
            with transaction.atomic():
                rb_obj = None
                if needs_room_flag and create_bookings:
                    # Pass the booking instance so RoomBooking can be linked via visit field
                    rb_obj, rb_created = create_room_booking_safe(room_candidate, target_date, canonical_slot, therapy_name, patient_id, booking)
                    if not rb_created:
                        raise RuntimeError("room_already_booked")
                elif needs_room_flag:
                    rb_obj = booking if getattr(booking, 'room', None) else None
                tb_objs = []
                for t in assigned_therapists:
                    is_bath_for_t = (t == bath_assigned)
                    if create_bookings:
                        tb_obj, tb_created = create_therapist_booking_safe(t, target_date, canonical_slot, therapy_name, patient_id, None, is_bathing=is_bath_for_t)
                        if not tb_created:
                            raise RuntimeError(f"therapist_already_booked:{getattr(t,'therapist_code',str(t))}")
                        tb_objs.append(tb_obj)
                    else:
                        tb_objs.append(SimpleNamespace(therapist_code=getattr(t,'therapist_code',str(t)), is_bathing=is_bath_for_t))
                # create BookingAssignment records to link therapists to Booking (Sheduling app)
                from Sheduling.models import BookingAssignment
                from Patient.models import Therapist
                for t in assigned_therapists:
                    try:
                        # Get or create Therapist object from Patient app (therapist_code is PK)
                        therapist_obj, _ = Therapist.objects.get_or_create(
                            therapist_code=t.therapist_code,
                            defaults={
                                'therapist_name': getattr(t, 'therapist_name', t.therapist_code),
                                'therapist_grade': getattr(t, 'therapist_grade', ''),
                                'is_bathing_therapist': getattr(t, 'is_bathing_therapist', False)
                            }
                        )
                        # Check if assignment already exists
                        existing = BookingAssignment.objects.filter(booking=booking, therapist=therapist_obj).first()
                        if existing:
                            ba_obj = existing
                            ba_created = False
                        else:
                            # Create BookingAssignment to link therapist to booking
                            # Note: booking_timeslot now uses SlotMaster (same as Booking.timeslot)
                            # It will be auto-populated from booking.timeslot in save() if not provided
                            ba_obj = BookingAssignment.objects.create(
                                booking=booking,
                                therapist=therapist_obj,
                                booking_item=None,
                                booking_date=target_date,
                                booking_timeslot=canonical_slot,  # SlotMaster instance (same as Booking.timeslot)
                                role=getattr(t, 'therapist_grade', ''),
                                assigned_for='booking',
                                status='assigned'
                            )
                            ba_created = True
                    except Exception as e:
                        print(f"Error creating BookingAssignment for {getattr(t, 'therapist_code', 'unknown')}: {e}")
                        import traceback
                        traceback.print_exc()
                        pass
                booking.refresh_from_db()  # Refresh to clear any cached relations
                # success audit
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
                # update booking row
                try:
                    booking.timeslot = getattr(booking, 'timeslot', None) or canonical_slot
                    booking.room = room_candidate or booking.room
                    booking.status = 'scheduled'
                    booking.save(update_fields=['timeslot','room','status','updated_at'])
                except Exception as e:
                    print(f"Error updating booking {booking.id} to scheduled: {e}")
                    import traceback
                    traceback.print_exc()
                    # Still mark as failed if save doesn't work
                    try:
                        booking.status = 'failed'
                        booking.save(update_fields=['status','updated_at'])
                    except Exception:
                        pass
                tasks.append({
                    "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                    "therapy_name": therapy_name, "slot": requested_slot_value, "status": "BOOKED", "reason": None,
                    "room_no": getattr(room_candidate,"room_no",None) if room_candidate else getattr(booking.room,"room_no",None) if getattr(booking,"room",None) else None,
                    "therapists": therapists_for_audit
                })
                any_success = True

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

def bulk_allocate_for_date(target_date_str):
    """
    Bulk allocate all draft therapies for a specific date.
    This function is called by the Final Schedule button.
    
    Args:
        target_date_str: Date string in YYYY-MM-DD format
        
    Returns:
        dict: Summary of allocation results
    """
    from datetime import datetime
    from Sheduling.models import TherapyAllocation
    
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return {
            'success': False,
            'error': f'Invalid date format: {target_date_str}. Expected YYYY-MM-DD'
        }
    
    # Get all allocations that have draft bookings for the target date
    # This ensures we process dates separately, regardless of overall allocation status
    from Sheduling.models import Booking
    draft_bookings = Booking.objects.filter(
        date=target_date,
        status='draft'
    ).select_related('allocation')
    
    # Get unique allocations from these bookings
    draft_allocations = TherapyAllocation.objects.filter(
        bookings__in=draft_bookings
    ).distinct()
    
    if not draft_allocations.exists():
        return {
            'success': True,
            'message': 'No draft therapies found for the selected date',
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'results': []
        }
    
    results = []
    successful_count = 0
    failed_count = 0
    
    # Process each draft allocation - only process bookings for the target date
    # Don't change overall allocation status, only process bookings for this specific date
    for allocation in draft_allocations:
        try:
            # Run the allocation algorithm for this allocation and target date only
            tasks = expand_therapies_for_visit(
                allocation.id, 
                target_date_str, 
                create_bookings=True
            )
            
            # Analyze results - only affect bookings for this date, not overall allocation status
            if isinstance(tasks, dict) and "error" in tasks:
                # Algorithm returned an error for this date
                failed_count += 1
                results.append({
                    'allocation_id': allocation.id,
                    'patient_name': str(allocation.patient),
                    'therapy_name': allocation.therapy_name,
                    'status': 'failed',
                    'reason': tasks['error']
                })
            else:
                # Process algorithm results
                success_tasks = [t for t in tasks if t.get('status') == 'BOOKED']
                failed_tasks = [t for t in tasks if t.get('status') == 'FAILED']
                
                # Update booking statuses based on task results
                from Sheduling.models import Booking
                for task in tasks:
                    booking_id = task.get('booking_id')
                    if booking_id:
                        try:
                            booking = Booking.objects.get(id=booking_id, allocation=allocation, date=target_date)
                            if task.get('status') == 'BOOKED':
                                booking.status = 'scheduled'
                                booking.save(update_fields=['status', 'updated_at'])
                            elif task.get('status') == 'FAILED' and booking.status == 'draft':
                                booking.status = 'failed'
                                booking.save(update_fields=['status', 'updated_at'])
                        except Booking.DoesNotExist:
                            pass
                        except Exception as e:
                            print(f"Error updating booking {booking_id} status: {e}")
                
                if success_tasks:
                    successful_count += 1
                    results.append({
                        'allocation_id': allocation.id,
                        'patient_name': str(allocation.patient),
                        'therapy_name': allocation.therapy_name,
                        'status': 'success',
                        'booked_tasks': len(success_tasks),
                        'failed_tasks': len(failed_tasks)
                    })
                else:
                    failed_count += 1
                    reason = failed_tasks[0].get('reason', 'No available slots') if failed_tasks else 'Unknown error'
                    results.append({
                        'allocation_id': allocation.id,
                        'patient_name': str(allocation.patient),
                        'therapy_name': allocation.therapy_name,
                        'status': 'failed',
                        'reason': reason
                    })
                
                # DO NOT update overall allocation status
                # Each booking date is independent - one date can be scheduled while another remains draft
                # The TherapyAllocation.status field is not automatically updated based on booking statuses
                # This allows:
                # - Date 23rd in draft, Date 24th scheduled → perfectly fine, both remain independent
                # - Running Final Schedule for 23rd doesn't affect 24th's status
                # - Running Final Schedule for 24th doesn't affect 23rd's status
                # Only individual Booking.status is updated per date during Final Schedule
                    
        except Exception as e:
            failed_count += 1
            results.append({
                'allocation_id': allocation.id,
                'patient_name': str(allocation.patient),
                'therapy_name': allocation.therapy_name,
                'status': 'failed',
                'reason': f'Exception: {str(e)}'
            })
    
    return {
        'success': True,
        'message': f'Bulk allocation completed for {target_date_str}',
        'date': target_date_str,
        'total_processed': len(draft_allocations),
        'successful': successful_count,
        'failed': failed_count,
        'results': results
    }

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
