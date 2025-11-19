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

def get_therapist_grade_name(therapist):
    """Helper function to get therapist grade name from TherapistGrade FK"""
    if not therapist:
        return ''
    if hasattr(therapist, 'therapist_grade') and therapist.therapist_grade:
        if hasattr(therapist.therapist_grade, 'name'):
            return therapist.therapist_grade.name
    return ''

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
    print(f"[DEBUG create_room_booking_safe] Called with: room={room} (pk={room.pk if room else None}), date={date}, time_slot={time_slot} (type={type(time_slot)}, pk={time_slot.pk if time_slot else None}), visit={visit} (type={type(visit)}, pk={visit.pk if visit else None})")
    try:
        # Don't use nested transaction.atomic() - we're already in a transaction
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
        print(f"[DEBUG create_room_booking_safe] get_or_create returned: rb={rb} (pk={rb.pk if rb else None}), created={created}")
        # Update visit if it's not set and we have a booking instance
        # CRITICAL: Use full save() instead of update_fields to ensure FK is properly set in SQLite
        if not created and rb.visit is None and visit is not None:
            print(f"[DEBUG create_room_booking_safe] Updating visit for existing RoomBooking: rb.visit = {visit}")
            rb.visit = visit
            rb.save()  # Full save to ensure FK is properly persisted
            rb.refresh_from_db()
            print(f"[DEBUG create_room_booking_safe] Visit updated successfully")
        elif created and rb.visit != visit and visit is not None:
            print(f"[DEBUG create_room_booking_safe] Updating visit for newly created RoomBooking: rb.visit = {visit}")
            rb.visit = visit
            rb.save()  # Full save to ensure FK is properly persisted
            rb.refresh_from_db()
            print(f"[DEBUG create_room_booking_safe] Visit updated successfully")
        return rb, created
    except IntegrityError as ie:
        print(f"[DEBUG create_room_booking_safe] IntegrityError caught: {ie}")
        import traceback
        traceback.print_exc()
        rb = RoomBooking.objects.filter(room=room, date=date, time_slot=time_slot, status='BOOKED').first()
        print(f"[DEBUG create_room_booking_safe] Found existing RoomBooking: {rb} (pk={rb.pk if rb else None})")
        # Try to update visit if not set
        if rb and rb.visit is None and visit is not None:
            try:
                print(f"[DEBUG create_room_booking_safe] Attempting to update visit on existing RoomBooking")
                rb.visit = visit
                rb.save()  # Full save to ensure FK is properly persisted
                rb.refresh_from_db()
                print(f"[DEBUG create_room_booking_safe] Visit updated on existing RoomBooking")
            except Exception as e:
                print(f"[DEBUG create_room_booking_safe] Error updating visit: {e}")
                import traceback
                traceback.print_exc()
        return rb, False

def create_therapist_booking_safe(therapist, date, time_slot, therapy_name, patient_id, visit, is_bathing=False):
    """
    Create TherapistBooking safely and optionally set is_bathing if the model has that field.
    Returns (therapist_booking_instance, created_bool)
    Note: Don't use nested transaction.atomic() - we're already in a transaction
    """
    from Patient.models import TherapistBooking
    print(f"[DEBUG create_therapist_booking_safe] Called with: therapist={therapist} (pk={therapist.pk if therapist else None}), date={date}, time_slot={time_slot} (type={type(time_slot)}, pk={time_slot.pk if time_slot else None}), visit={visit} (type={type(visit)}, pk={visit.pk if visit else None})")
    try:
        # Don't use nested transaction.atomic() - we're already in a transaction
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
        print(f"[DEBUG create_therapist_booking_safe] get_or_create returned: tb={tb} (pk={tb.pk if tb else None}), created={created}")
        # CRITICAL: Use full save() instead of update_fields to ensure FK is properly set in SQLite
        if not created and tb.visit is None and visit is not None:
            print(f"[DEBUG create_therapist_booking_safe] Updating visit for existing TherapistBooking: tb.visit = {visit}")
            tb.visit = visit
            tb.save()  # Full save to ensure FK is properly persisted
            tb.refresh_from_db()
            print(f"[DEBUG create_therapist_booking_safe] Visit updated successfully")
        elif created and tb.visit != visit and visit is not None:
            print(f"[DEBUG create_therapist_booking_safe] Updating visit for newly created TherapistBooking: tb.visit = {visit}")
            tb.visit = visit
            tb.save()  # Full save to ensure FK is properly persisted
            tb.refresh_from_db()
            print(f"[DEBUG create_therapist_booking_safe] Visit updated successfully")
        # persist is_bathing if model supports it and we either created or it's not set
        try:
            if is_bathing and hasattr(tb, 'is_bathing'):
                # save only if value differs to avoid unnecessary writes
                if getattr(tb, 'is_bathing', False) != bool(is_bathing):
                    tb.is_bathing = bool(is_bathing)
                    tb.save()  # Full save to ensure FK is properly persisted
                    tb.refresh_from_db()
        except Exception as e:
            print(f"[DEBUG create_therapist_booking_safe] Error setting is_bathing: {e}")
        return tb, created
    except IntegrityError as ie:
        print(f"[DEBUG create_therapist_booking_safe] IntegrityError caught: {ie}")
        import traceback
        traceback.print_exc()
        tb = TherapistBooking.objects.filter(therapist=therapist, date=date, time_slot=time_slot, status='BOOKED').first()
        print(f"[DEBUG create_therapist_booking_safe] Found existing TherapistBooking: {tb} (pk={tb.pk if tb else None})")
        # attempt to mark is_bathing if possible (best-effort, non-fatal)
        try:
            if tb and is_bathing and hasattr(tb, 'is_bathing'):
                if not tb.is_bathing:
                    tb.is_bathing = True
                    tb.save(update_fields=['is_bathing'])
        except Exception as e:
            print(f"[DEBUG create_therapist_booking_safe] Error updating is_bathing on existing: {e}")
        # Try to update visit if not set
        if tb and tb.visit is None and visit is not None:
            try:
                print(f"[DEBUG create_therapist_booking_safe] Attempting to update visit on existing TherapistBooking")
                tb.visit = visit
                tb.save(update_fields=['visit'])
                print(f"[DEBUG create_therapist_booking_safe] Visit updated on existing TherapistBooking")
            except Exception as e:
                print(f"[DEBUG create_therapist_booking_safe] Error updating visit: {e}")
                import traceback
                traceback.print_exc()
        return tb, False

# -----------------------
# Room allocation helper - determines treatment rooms based on patient staying room
# -----------------------
def get_treatment_rooms_for_staying_room(patient_staying_room):
    """
    Returns list of treatment room numbers to check based on patient staying room.
    Returns empty list if no match found.
    
    Rules:
    - DS-1 to DS-6: TR-1/TR-2, then TR-3/TR-4, then TR-7/TR-8
    - NR-7 to NR-14: TR-3/TR-4
    - NR-15 to NR-21: TR-5/TR-6
    - NR-22 to NR-27: TR-7/TR-8
    - NR-28 to NR-33: TR-15/TR-16
    - MG-1 to MG-10, CB-1/CB-2, FG-1 to FG-12: TR-9 to TR-14
    - CT-1, CT-2, etc.: TRC-1, TRC-2, etc. (same number)
    """
    if not patient_staying_room:
        return []
    
    staying_room = str(patient_staying_room).strip().upper()
    
    # Extract prefix and number
    import re
    match = re.match(r'([A-Z]+)-?(\d+)', staying_room)
    if not match:
        return []
    
    prefix = match.group(1)
    try:
        room_num = int(match.group(2))
    except ValueError:
        return []
    
    # DS-1 to DS-6: TR-1/TR-2, then TR-3/TR-4, then TR-7/TR-8
    if prefix == 'DS' and 1 <= room_num <= 6:
        return ['TR-1', 'TR-2', 'TR-3', 'TR-4', 'TR-7', 'TR-8']
    
    # NR-7 to NR-14: TR-3/TR-4
    if prefix == 'NR' and 7 <= room_num <= 14:
        return ['TR-3', 'TR-4']
    
    # NR-15 to NR-21: TR-5/TR-6
    if prefix == 'NR' and 15 <= room_num <= 21:
        return ['TR-5', 'TR-6']
    
    # NR-22 to NR-27: TR-7/TR-8
    if prefix == 'NR' and 22 <= room_num <= 27:
        return ['TR-7', 'TR-8']
    
    # NR-28 to NR-33: TR-15/TR-16
    if prefix == 'NR' and 28 <= room_num <= 33:
        return ['TR-15', 'TR-16']
    
    # MG-1 to MG-10, CB-1/CB-2, FG-1 to FG-12: TR-9 to TR-14
    if prefix == 'MG' and 1 <= room_num <= 10:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14']
    if prefix == 'CB' and room_num in [1, 2]:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14']
    if prefix == 'FG' and 1 <= room_num <= 12:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14']
    
    # CT-1, CT-2, etc.: TRC-1, TRC-2, etc. (same number)
    if prefix == 'CT':
        return [f'TRC-{room_num}']
    
    # No match found
    return []

def allocate_treatment_room(date, time_slot, last_room=None, therapy_name=None, patient_id=None, patient_staying_room=None, patient=None):
    """
    Allocate treatment room based on patient staying room rules.
    
    NEW LOGIC: Allocates treatment rooms based on patient staying room:
    - DS-1 to DS-6: Check TR-1/TR-2 first, then TR-3/TR-4, then TR-7/TR-8
    - NR-7 to NR-14: Assign TR-3/TR-4
    - NR-15 to NR-21: Assign TR-5/TR-6
    - NR-22 to NR-27: Assign TR-7/TR-8
    - NR-28 to NR-33: Assign TR-15/TR-16
    - MG-1 to MG-10, CB-1/CB-2, FG-1 to FG-12: Assign TR-9 to TR-14
    - CT-1, CT-2, etc.: Assign TRC-1, TRC-2, etc. (same number)
    
    For OP patients (no staying room):
    - First try TR-9 to TR-14
    - If not available, try TR-5, TR-6, TR-7
    - If still not available, return None (allocation fails)
    
    If no room available from the list, returns None (allocation will fail).
    
    Args:
        date: Date for allocation
        time_slot: Time slot for allocation
        last_room: Preferred room number (string) or room object (legacy, kept for compatibility)
        therapy_name: Name of the therapy (legacy, kept for compatibility)
        patient_id: Patient ID (legacy, kept for compatibility)
        patient_staying_room: Patient staying room number (e.g., 'DS-1', 'NR-7', 'CT-1')
        patient: Patient object (PatientSnapshot) to check if OP (optional)
    
    Returns:
        TreatmentRoom instance or None if no room available
    """
    from Patient.models import RoomBooking, TreatmentRoom
    
    # Helper function to check room availability
    def check_room_availability(room_no, exclude_trc=False):
        try:
            room = TreatmentRoom.objects.get(room_no=room_no)
            # Strictly exclude TRC rooms for OP patients
            if exclude_trc and room_no.upper().startswith('TRC'):
                return None
            if not RoomBooking.objects.filter(
                room=room,
                date=date,
                time_slot=time_slot,
                status='BOOKED'
            ).exists():
                return room
        except TreatmentRoom.DoesNotExist:
            pass
        return None
    
    # NEW: Primary logic - allocate based on patient staying room
    if patient_staying_room:
        treatment_rooms = get_treatment_rooms_for_staying_room(patient_staying_room)
        
        if treatment_rooms:
            # Check each treatment room in order for availability
            for room_no in treatment_rooms:
                room = check_room_availability(room_no)
                if room:
                    return room
            
            # None of the assigned rooms are available
            return None
    
    # NEW: OP patient fallback logic
    # Check if patient is OP (outpatient)
    is_op_patient = False
    if not patient_staying_room and patient:
        try:
            # Check if patient has is_op method (PatientSnapshot)
            if hasattr(patient, 'is_op'):
                is_op_patient = patient.is_op()
            # Alternative: check registration number length (5 digits = OP)
            elif hasattr(patient, 'pat_reg_no'):
                digits = ''.join(ch for ch in str(patient.pat_reg_no or '') if ch.isdigit())
                is_op_patient = len(digits) == 5
        except Exception:
            pass
    
    # For OP patients, check if they have a staying room from Treatment model
    # If OP patient has staying room, use it for allocation
    if is_op_patient and not patient_staying_room and patient:
        try:
            # Try to get room number from patient's pat_room_no (should be populated from Treatment model)
            op_staying_room = getattr(patient, 'pat_room_no', None)
            if op_staying_room:
                patient_staying_room = str(op_staying_room).strip()
        except Exception:
            pass
    
    # If OP patient has staying room (e.g., CT-1), apply staying room rules
    if is_op_patient and patient_staying_room:
        # Check if it's a CT room - if yes, apply CT room logic (TRC rooms)
        staying_room_upper = str(patient_staying_room).strip().upper()
        if staying_room_upper.startswith('CT'):
            # Extract CT room number and assign TRC room
            import re
            match = re.match(r'CT-?(\d+)', staying_room_upper)
            if match:
                try:
                    ct_room_num = int(match.group(1))
                    trc_room_no = f'TRC-{ct_room_num}'
                    room = check_room_availability(trc_room_no)
                    if room:
                        return room
                    # TRC room not available
                    return None
                except (ValueError, AttributeError):
                    pass
        
        # For other room types, use staying room rules
        treatment_rooms = get_treatment_rooms_for_staying_room(patient_staying_room)
        if treatment_rooms:
            for room_no in treatment_rooms:
                room = check_room_availability(room_no)
                if room:
                    return room
            return None
    
    # OP patients with no room or non-CT room: Try TR-1 to TR-16 in order
    if is_op_patient:
        op_rooms = ['TR-1', 'TR-2', 'TR-3', 'TR-4', 'TR-5', 'TR-6', 'TR-7', 'TR-8', 
                   'TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-15', 'TR-16']
        
        # Try all rooms in order, explicitly excluding TRC rooms
        for room_no in op_rooms:
            # Double check: ensure room_no doesn't start with TRC
            if room_no.upper().startswith('TRC'):
                continue
            room = check_room_availability(room_no, exclude_trc=True)
            if room:
                return room
        
        # No room available for OP patient - DO NOT fall through to legacy logic
        return None
    
    # FALLBACK: Legacy logic if patient_staying_room is not provided and not OP
    # Check if this is a 'Dhara & Pizichil' therapy
    is_dhara_pizichil = False
    if therapy_name:
        therapy_lower = str(therapy_name).lower()
        is_dhara_pizichil = 'dhara' in therapy_lower and 'pizichil' in therapy_lower
    
    # For 'Dhara & Pizichil', try to find previous room assignment
    previous_room_no = None
    if is_dhara_pizichil and patient_id:
        try:
            from django.db.models import Q
            previous_bookings = RoomBooking.objects.filter(
                patient_id=patient_id,
                status='BOOKED'
            ).exclude(
                date=date,
                time_slot=time_slot
            ).order_by('-date', '-time_slot').select_related('room')
            
            for booking in previous_bookings:
                therapy_name_lower = str(booking.therapy_name or '').lower()
                if 'dhara' in therapy_name_lower and 'pizichil' in therapy_name_lower:
                    if booking.room:
                        previous_room_no = booking.room.room_no
                        break
        except Exception as e:
            print(f"[DEBUG allocate_treatment_room] Error finding previous room: {e}")
            previous_room_no = None
    
    # If we have a previous room for 'Dhara & Pizichil', try to use it first
    # BUT STRICTLY exclude TRC rooms for OP patients
    if is_dhara_pizichil and previous_room_no:
        # Don't assign TRC rooms to OP patients
        if is_op_patient and previous_room_no.upper().startswith('TRC'):
            pass  # Skip TRC rooms for OP patients
        else:
            try:
                previous_room = TreatmentRoom.objects.get(room_no=previous_room_no)
                if not RoomBooking.objects.filter(
                    room=previous_room,
                    date=date,
                    time_slot=time_slot,
                    status='BOOKED'
                ).exists():
                    return previous_room
            except TreatmentRoom.DoesNotExist:
                pass
    
    # Use last_room if provided (legacy fallback)
    # BUT STRICTLY exclude TRC rooms for OP patients
    if last_room and not is_op_patient:
        try:
            if isinstance(last_room, str):
                room_no = last_room
            else:
                room_no = getattr(last_room, 'room_no', None)
            if room_no:
                # Don't assign TRC rooms to OP patients
                if room_no.upper().startswith('TRC'):
                    pass  # Skip TRC rooms
                else:
                    room = TreatmentRoom.objects.get(room_no=room_no)
                    if not RoomBooking.objects.filter(room=room, date=date, time_slot=time_slot, status='BOOKED').exists():
                        return room
        except TreatmentRoom.DoesNotExist:
            pass
    
    # Same floor fallback (legacy) - exclude OP patients and TRC rooms
    if last_room and not is_op_patient:
        try:
            if isinstance(last_room, str):
                last_room_obj = TreatmentRoom.objects.get(room_no=last_room)
            else:
                last_room_obj = last_room
            same_floor = TreatmentRoom.objects.filter(floor=last_room_obj.floor)
            for r in same_floor:
                # Exclude TRC rooms
                if r.room_no and r.room_no.upper().startswith('TRC'):
                    continue
                if not RoomBooking.objects.filter(room=r, date=date, time_slot=time_slot, status='BOOKED').exists():
                    return r
        except TreatmentRoom.DoesNotExist:
            pass
    
    # Any available room (legacy fallback - only if no staying room provided and NOT OP)
    # STRICTLY exclude OP patients from this fallback to prevent TRC room assignment
    if not patient_staying_room and not is_op_patient:
        for r in TreatmentRoom.objects.all():
            # Also exclude TRC rooms from legacy fallback
            if r.room_no and r.room_no.upper().startswith('TRC'):
                continue
            if not RoomBooking.objects.filter(room=r, date=date, time_slot=time_slot, status='BOOKED').exists():
                return r
    
    # No room available
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
def allocate_therapists(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False, patient_gender=None):
    from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave
    from Patient.models import TherapistBooking

    day_of_week = date.weekday()
    allocated = []

    # Normalize patient gender: default to 'male' if not explicitly female
    desired_gender = None
    try:
        if patient_gender:
            g = str(patient_gender).strip().lower()
            if g.startswith('f'):
                desired_gender = 'female'
            else:
                desired_gender = 'male'
    except Exception:
        desired_gender = 'male'

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

    def get_therapist_gender(t):
        try:
            # Prioritize therapist_gender field from TherapistMaster (values: "Male"/"Female")
            v = getattr(t, 'therapist_gender', None)
            if v:
                v_str = str(v).strip()
                # Handle "Male"/"Female" (capitalized) or "male"/"female" (lowercase)
                if v_str.lower().startswith('m'):
                    return 'male'
                if v_str.lower().startswith('f'):
                    return 'female'
        except Exception:
            pass
        return None

    def get_therapist_daily_session_count(t):
        """Count how many therapy sessions a therapist already has on this date"""
        try:
            return TherapistBooking.objects.filter(
                therapist=t,
                date=date,
                status='BOOKED'
            ).count()
        except Exception:
            return 0

    def can_assign_therapist(t, allow_extra=False):
        """
        Check if therapist can be assigned based on daily session limit.
        - Normal limit: 5 sessions per day
        - If allow_extra=True and all therapists have 5 sessions, allow 1 extra (max 6)
        - If therapist already has 6 sessions, cannot assign
        """
        session_count = get_therapist_daily_session_count(t)
        max_sessions = 6 if allow_extra else 5
        return session_count < max_sessions

    def check_grade_availability(grade, gender_filter):
        """Check how many therapists of a specific grade and gender are available"""
        candidates_qs = TherapistMaster.objects.filter(therapist_grade__name__iexact=grade)
        
        if gender_filter:
            candidates_qs = candidates_qs.filter(therapist_gender__istartswith=gender_filter[0])
        
        print(f"[DEBUG Availability] Checking {gender_filter} {grade}: Found {candidates_qs.count()} in database")
            
        available_count = 0
        unavailable_reasons = {}
        
        for t in candidates_qs:
            reason = None
            if t in allocated:
                reason = "already_allocated_in_this_run"
            elif therapist_on_leave(t):
                reason = "on_leave"
            elif TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                reason = "already_booked_at_this_slot"
            elif not can_assign_therapist(t, allow_extra=False) and not can_assign_therapist(t, allow_extra=True):
                reason = "session_limit_reached"
            else:
                available_count += 1
                reason = "available"
            
            unavailable_reasons[t.therapist_code] = reason
        
        # Print detailed breakdown
        for code, reason in unavailable_reasons.items():
            print(f"[DEBUG Availability] {code}: {reason}")
        
        print(f"[DEBUG Availability] {gender_filter} {grade}: {available_count} available out of {candidates_qs.count()}")
        return available_count

    # Check if all therapists have 5 sessions (to allow 1 extra)
    all_therapists_at_limit = False

    # Use last therapists first
    if last_therapists:
        for code in last_therapists:
            try:
                t = TherapistMaster.objects.get(therapist_code=code)
            except TherapistMaster.DoesNotExist:
                continue
            therapist_grade_name = get_therapist_grade_name(t)
            if grade_map.get(therapist_grade_name, 0) > 0:
                # STRICT GENDER MATCH: skip if therapist gender does not match desired
                if desired_gender:
                    t_gender = get_therapist_gender(t)
                    if t_gender != desired_gender:
                        continue
                if therapist_on_leave(t):
                    continue
                # CHECK FOR EXISTING BOOKINGS: Do not assign if already booked at this date+time_slot
                if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                    continue
                # Check daily session limit (max 5, or 6 if all therapists are at limit)
                if not can_assign_therapist(t, allow_extra=False):
                    # Check if we should allow extra (if all therapists have 5 sessions)
                    if not can_assign_therapist(t, allow_extra=True):
                        continue  # Therapist already has 6 sessions
                    # Otherwise, we'll allow this if all therapists are at limit
                allocated.append(t)
                grade_map[therapist_grade_name] -= 1

    # Allocate remaining
    for grade, needed_original in list(grade_map.items()):
        
        needed = needed_original
        current_grade_search = grade
        
        if needed <= 0:
            continue

        # --- STRICT GENDER MATCHING WITH GRADE SUBSTITUTION ONLY ---
        substitution_hierarchy = {
            "Trainee Therapist": ["Junior Therapist", "Senior Therapist", "Super Senior Therapist"],
            "Junior Therapist": ["Senior Therapist", "Super Senior Therapist"],
            "Senior Therapist": ["Super Senior Therapist"],
            "Super Senior Therapist": []  # No substitution for highest grade
        }
        
        is_substitution = False
        substitution_chain = []
        
        # Check if we need substitution for the current grade
        if current_grade_search in substitution_hierarchy and desired_gender:
            # First check availability of current grade with matching gender
            available_exact_match = check_grade_availability(current_grade_search, desired_gender)
            print(f"[DEBUG Allocation] {desired_gender.capitalize()} {current_grade_search} required (needed={needed}). Exact match available: {available_exact_match}")
            
            # If exact grade+gender not available, try substitution hierarchy WITH SAME GENDER
            if available_exact_match == 0:
                print(f"[DEBUG Allocation] No exact {desired_gender} {current_grade_search} available. Attempting substitution with SAME GENDER...")
                
                # Try each grade in substitution hierarchy WITH SAME GENDER
                substitution_found = False
                for substitute_grade in substitution_hierarchy[current_grade_search]:
                    available_substitute = check_grade_availability(substitute_grade, desired_gender)
                    print(f"[DEBUG Allocation] Checking {desired_gender} {substitute_grade}: {available_substitute} available")
                    
                    if available_substitute > 0:
                        print(f"[DEBUG Allocation] Substituting {current_grade_search} with {substitute_grade} for {desired_gender} patient")
                        current_grade_search = substitute_grade
                        is_substitution = True
                        substitution_chain = [current_grade_search, substitute_grade]
                        substitution_found = True
                        break
                
                if not substitution_found:
                    print(f"[DEBUG Allocation] No substitution available for {desired_gender} {current_grade_search}. Strict gender matching enforced.")
        # --- END STRICT GENDER MATCHING LOGIC ---

        # Search for therapists with strict gender matching
        candidates_qs = TherapistMaster.objects.filter(therapist_grade__name=current_grade_search)
        
        # STRICT GENDER FILTER - never remove this
        if desired_gender:
            candidates_qs = candidates_qs.filter(therapist_gender__istartswith=desired_gender[0])
        
        if needs_bathing:
            candidates_qs = candidates_qs.filter(is_bathing_therapist=True) | candidates_qs
            
        # First, try to find therapists with < 5 sessions
        candidates_list = list(candidates_qs)
        available_candidates = []
        for t in candidates_list:
            if t in allocated:
                continue
            if therapist_on_leave(t):
                continue
            # CHECK FOR EXISTING BOOKINGS: Do not assign if already booked at this date+time_slot
            if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                continue
            
            # STRICT GENDER MATCH: Already enforced in query, but double-check
            if desired_gender:
                t_gender = get_therapist_gender(t)
                if t_gender != desired_gender:
                    continue  # This should never happen due to query filter, but safety check
            
            # Check daily session limit (prefer therapists with < 5 sessions)
            session_count = get_therapist_daily_session_count(t)
            if session_count < 5:
                available_candidates.append((t, session_count))
            elif session_count == 5:
                # Keep track of therapists at limit (5 sessions) for potential extra assignment
                available_candidates.append((t, session_count))
        
        # Sort by session count (prefer therapists with fewer sessions)
        available_candidates.sort(key=lambda x: x[1])
        
        # Check if all therapists in this grade have 5 sessions
        all_at_limit = all(count >= 5 for _, count in available_candidates) if available_candidates else False
        
        # If all therapists have 5 sessions, allow 1 extra (max 6)
        # Otherwise, only assign to therapists with < 5 sessions
        allow_extra = all_at_limit
        
        # Iterate through available candidates
        for t, session_count in available_candidates:
            if needed <= 0:
                break
            
            # Check if we can assign (max 5 normally, or 6 if allowing extra)
            if not allow_extra and session_count >= 5:
                continue  # Skip therapists with 5+ sessions if not allowing extra
            if allow_extra and session_count >= 6:
                continue  # Skip therapists with 6+ sessions even when allowing extra
            
            allocated.append(t)
            needed -= 1
            grade_map[grade] -= 1 # Decrement original grade count

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
                booking.save(update_fields=['status', 'updated_at'])
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

    tasks = []
    used_slots = []
    any_success = False
    patient_id = getattr(allocation.patient, 'id', None)
    patient_staying_room = getattr(allocation.patient, 'pat_room_no', None)

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
        patient_already_booked = False
        try:
            patient_already_booked = (
                RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=query_slot, status__in=['BOOKED','scheduled']).exclude(pk=booking.pk).exists()
                or TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=query_slot, status='BOOKED').exclude(pk=booking.pk).exists()
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
        if any(getattr(s, 'start_time', None) == getattr(query_slot, 'start_time', None) for s in used_slots):
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
        # allocate therapists - use slot_master if available, otherwise canonical_slot
        allocate_slot = slot_master if slot_master else canonical_slot
        try:
            # Pass patient gender to enforce male-patient→male-therapist and female-patient→female-therapist
            pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
            candidate_therapists = allocate_therapists(target_date, allocate_slot, therapy_req, None, needs_bath_flag, patient_gender=pat_sex)
        except Exception:
            candidate_therapists = []

        req_total = int(therapy_req.get("total", 1) or 1)
        if len(candidate_therapists) < req_total:
            reason = "insufficient_therapists_available"
            
            # Check if all therapists have reached max sessions (6)
            try:
                from masters.models import TherapistMaster
                from Patient.models import TherapistBooking
                # Count therapists with 6 sessions on this date
                from django.db.models import Count, Q
                therapists_with_6_sessions = TherapistMaster.objects.annotate(
                    session_count=Count(
                        'therapistbooking',
                        filter=Q(
                            therapistbooking__date=target_date,
                            therapistbooking__status='BOOKED'
                        )
                    )
                ).filter(session_count__gte=6).count()
                
                total_therapists = TherapistMaster.objects.count()
                
                # If all therapists have 6 sessions, show specific error
                if total_therapists > 0 and therapists_with_6_sessions == total_therapists:
                    reason = "therapist_unavailability: All therapists have reached maximum sessions (6) for this day"
            except Exception:
                pass
            
            # Gender availability insight (non-blocking, for debugging/UX)
            try:
                desired_gender = None
                pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
                if pat_sex:
                    g = str(pat_sex).strip().lower()
                    if g.startswith('m'):
                        desired_gender = 'male'
                    elif g.startswith('f'):
                        desired_gender = 'female'
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
                        pool = TherapistMaster.objects.filter(therapist_grade__name__icontains=grade_text)
                        available = 0
                        # Use query_slot (resolved SlotMaster) for exact slot match when checking bookings
                        for t in pool:
                            if desired_gender and _tg(t) != desired_gender:
                                continue
                            if TherapistLeaveMaster.objects.filter(therapist=t, leave_day=day_of_week).exists():
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

        # choose single bathing-assigned therapist if bathing required
        assigned_therapists = candidate_therapists[:req_total]
        bath_assigned = None
        if needs_bath_flag and assigned_therapists:
            bath_assigned = next((t for t in assigned_therapists if getattr(t, 'is_bathing_therapist', False)), None)
            if not bath_assigned:
                bath_assigned = assigned_therapists[0]
        # build therapist audit list
        therapists_for_audit = [therapist_entry(t, is_bath=(t == bath_assigned)) for t in assigned_therapists]
        # room allocation - use slot_master if available, otherwise canonical_slot
        if not slot_master:
            # If we couldn't resolve slot_master earlier, try one more time before room allocation
            if canonical_slot and not isinstance(canonical_slot, SlotMaster):
                slot_time = getattr(canonical_slot, 'slot_time', None)
                if slot_time:
                    slot_master = SlotMaster.objects.filter(slot_time=slot_time, is_active=True).first()
        allocate_slot_for_room = slot_master if slot_master else canonical_slot
        
        room_candidate = getattr(booking, 'room', None)
        if needs_room_flag and not room_candidate:
            try:
                room_candidate = allocate_treatment_room(
                    target_date, 
                    allocate_slot_for_room, 
                    None,
                    therapy_name=therapy_name,
                    patient_id=patient_id,
                    patient_staying_room=patient_staying_room,
                    patient=allocation.patient if allocation and hasattr(allocation, 'patient') else None
                )
            except Exception:
                room_candidate = None
        if needs_room_flag and not room_candidate:
            # Build detailed error message based on patient staying room or OP status
            reason = "no_room_available"
            if patient_staying_room:
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
            elif therapy_name:
                # Legacy: Check if this is 'Dhara & Pizichil' and we had a previous room that's unavailable
                therapy_lower = str(therapy_name).lower()
                if 'dhara' in therapy_lower and 'pizichil' in therapy_lower and patient_id:
                    # Try to find previous room to show in error message
                    try:
                        from Patient.models import RoomBooking
                        previous_booking = RoomBooking.objects.filter(
                            patient_id=patient_id,
                            status='BOOKED'
                        ).exclude(date=target_date).order_by('-date', '-time_slot').select_related('room').first()
                        if previous_booking:
                            prev_therapy_lower = str(previous_booking.therapy_name or '').lower()
                            if 'dhara' in prev_therapy_lower and 'pizichil' in prev_therapy_lower:
                                if previous_booking.room:
                                    reason = f"previous_room_unavailable: Previous room {previous_booking.room.room_no} for Dhara & Pizichil is unavailable"
                    except Exception:
                        pass
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
                            print(f"[DEBUG] Room {room_candidate.room_no} already booked for {target_date} at {slot_master}, trying alternative room...")
                            alternative_room = allocate_treatment_room(
                                target_date, 
                                slot_master, 
                                getattr(room_candidate, 'room_no', None),
                                therapy_name=therapy_name,
                                patient_id=patient_id,
                                patient_staying_room=patient_staying_room,
                                patient=allocation.patient if allocation and hasattr(allocation, 'patient') else None
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
                    print(f"[DEBUG] Setting booking.timeslot and room BEFORE creating any related objects")
                    booking.timeslot = slot_master
                    booking.room = room_candidate or booking.room
                    booking.status = 'scheduled'
                    # Save booking COMPLETELY before creating any FK references to it
                    booking.save()
                    # Refresh to ensure it's fully loaded
                    booking.refresh_from_db()
                    print(f"[DEBUG] Booking fully saved: pk={booking.pk}, timeslot_id={booking.timeslot_id}, room_id={booking.room_id}")
                    
                    rb_obj = None
                    if needs_room_flag and create_bookings:
                        # Now create RoomBooking - booking is fully saved and persisted
                        # Use slot_master (resolved SlotMaster) instead of canonical_slot to ensure FK is valid
                        print(f"[DEBUG] Creating RoomBooking: room={room_candidate} (pk={room_candidate.pk if room_candidate else None}), date={target_date}, slot_master={slot_master} (pk={slot_master.pk if slot_master else None}), booking={booking} (pk={booking.pk})")
                        try:
                            rb_obj, rb_created = create_room_booking_safe(room_candidate, target_date, slot_master, therapy_name, patient_id, booking)
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
                            # RoomBooking already exists, try alternative room
                            alternative_room = allocate_treatment_room(
                                target_date, 
                                slot_master, 
                                getattr(room_candidate, 'room_no', None),
                                therapy_name=therapy_name,
                                patient_id=patient_id,
                                patient_staying_room=patient_staying_room,
                                patient=allocation.patient if allocation and hasattr(allocation, 'patient') else None
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
                    for t in assigned_therapists:
                        is_bath_for_t = (t == bath_assigned)
                        if create_bookings:
                            print(f"[DEBUG] Creating TherapistBooking: therapist={t.therapist_code}, date={target_date}, slot_master={slot_master} (pk={slot_master.pk if slot_master else None})")
                            # Pass allocation (TherapyAllocation) instead of None for visit FK
                            # Use slot_master (resolved SlotMaster) instead of canonical_slot to ensure FK is valid
                            tb_obj, tb_created = create_therapist_booking_safe(t, target_date, slot_master, therapy_name, patient_id, allocation, is_bathing=is_bath_for_t)
                            print(f"[DEBUG] TherapistBooking created: {tb_obj}, created={tb_created}")
                            if not tb_created:
                                raise RuntimeError(f"therapist_already_booked:{getattr(t,'therapist_code',str(t))}")
                            # Refresh TherapistBooking to get actual FK IDs
                            if tb_obj:
                                tb_obj.refresh_from_db()
                                print(f"[DEBUG] TherapistBooking FK IDs: therapist_id={tb_obj.therapist_id}, time_slot_id={tb_obj.time_slot_id}, visit_id={tb_obj.visit_id}")
                            tb_objs.append(tb_obj)
                        else:
                            tb_objs.append(SimpleNamespace(therapist_code=getattr(t,'therapist_code',str(t)), is_bathing=is_bath_for_t))
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
                            print(f"[DEBUG] Therapist object verified: pk={therapist_obj.pk}, type={type(therapist_obj.pk)}")
                            
                            # Check if assignment already exists
                            existing = BookingAssignment.objects.filter(booking=booking, therapist=therapist_obj).first()
                            if existing:
                                ba_obj = existing
                                ba_created = False
                                print(f"[DEBUG] BookingAssignment already exists: pk={ba_obj.pk}")
                            else:
                                # Create BookingAssignment to link therapist to booking
                                # Explicitly set booking_timeslot to slot_master to avoid FK constraint issues
                                # IMPORTANT: Ensure booking is fully saved and refreshed before creating BookingAssignment
                                print(f"[DEBUG] Creating BookingAssignment:")
                                print(f"[DEBUG]   - booking={booking} (pk={booking.pk}, timeslot_id={booking.timeslot_id})")
                                print(f"[DEBUG]   - booking.timeslot={booking.timeslot} (pk={booking.timeslot.pk if booking.timeslot else None})")
                                print(f"[DEBUG]   - slot_master={slot_master} (pk={slot_master.pk})")
                                print(f"[DEBUG]   - therapist={therapist_obj} (pk={therapist_obj.pk}, type={type(therapist_obj.pk)})")
                                print(f"[DEBUG]   - Explicitly setting booking_timeslot=slot_master to ensure FK is valid")
                                
                                # Create BookingAssignment - use create() then save() to ensure FK is set correctly
                                ba_obj = BookingAssignment(
                                    booking=booking,
                                    therapist=therapist_obj,
                                    booking_item=None,
                                    booking_date=target_date,
                                    booking_timeslot=slot_master,  # Explicitly set to avoid FK constraint issues
                                    role=get_therapist_grade_name(t),
                                    assigned_for='booking',
                                    status='assigned'
                                )
                                # Save explicitly to trigger any save() logic
                                ba_obj.save()
                                print(f"[DEBUG] BookingAssignment created successfully: {ba_obj.pk}, booking_timeslot={ba_obj.booking_timeslot} (pk={ba_obj.booking_timeslot.pk if ba_obj.booking_timeslot else None})")
                                print(f"[DEBUG] BookingAssignment FK IDs: therapist_id={ba_obj.therapist_id}, booking_id={ba_obj.booking_id}, booking_timeslot_id={ba_obj.booking_timeslot_id}")
                                ba_created = True
                        except Exception as e:
                            print(f"[DEBUG] Error creating BookingAssignment for {getattr(t, 'therapist_code', 'unknown')}: {e}")
                            import traceback
                            traceback.print_exc()
                            pass
                    booking.refresh_from_db()  # Refresh to clear any cached relations
                    print(f"[DEBUG] Booking {booking_id} refreshed from DB")
                    
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
                        booking.save(update_fields=['status','updated_at'])
                    except Exception as e:
                        print(f"[DEBUG] Error marking booking as failed: {e}")
                    # Re-raise to be caught by outer exception handler
                    raise RuntimeError(f"booking_transaction_failed: {str(ie)}")
            
            print(f"[DEBUG] Transaction.atomic() block exited - checking for commit errors...")
            # If we reach here, transaction committed successfully
            print(f"[DEBUG] Transaction committed successfully for booking {booking_id}")
            booking_saved_successfully = True
            
            # Only append BOOKED task if transaction committed successfully
            if booking_saved_successfully:
                tasks.append({
                    "booking_id": booking_id, "allocation_id": therapy_allocation_id, "date": target_date.isoformat(),
                    "therapy_name": therapy_name, "slot": requested_slot_value, "status": "BOOKED", "reason": None,
                    "room_no": getattr(room_candidate,"room_no",None) if room_candidate else getattr(booking.room,"room_no",None) if getattr(booking,"room",None) else None,
                    "therapists": therapists_for_audit
                })
                any_success = True

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