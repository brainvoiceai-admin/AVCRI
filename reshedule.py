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

def allocate_treatment_room(date, time_slot, last_room=None, patient_staying_room=None, patient=None):
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
    
    # NEW: OP patient fallback logic (no staying room)
    # Check if patient is OP (outpatient) - they don't have staying room
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
    
    if is_op_patient:
        # OP patients: Try TR-1 to TR-16 in order (STRICTLY NO TRC ROOMS)
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
    # Any available room (legacy fallback - only if no staying room provided and NOT OP)
    # STRICTLY exclude OP patients from this fallback to prevent TRC room assignment
    if not patient_staying_room and not is_op_patient:
        for r in TreatmentRoom.objects.all():
            # Also exclude TRC rooms from legacy fallback
            if r.room_no and r.room_no.upper().startswith('TRC'):
                continue
            if not RoomBooking.objects.filter(room=r, date=date, time_slot=time_slot, status='BOOKED').exists():
                return r
    return None

# -----------------------
# Slot helpers: return allowed slots (list) for patient type
# -----------------------
def get_allowed_slot_values(patient_type, therapy_category, used_slots=None):
    """
    Return ordered list of allowed slot strings "HH:MM" for this patient_type and therapy_category.
    Excludes any used_slots provided (list of slot model instances).
    """
    general_slots = ["06:30","08:30","10:00","11:30","14:30","16:00","17:30"]

    # default allowed by patient type
    if patient_type and str(patient_type).upper() == "OP":
        allowed_slots = ["11:30","17:30"]
    elif patient_type and str(patient_type).upper() == "IP":
        allowed_slots = ["06:30","08:30","10:00","14:30","16:00"]
    else:
        allowed_slots = general_slots

    # If therapy category requires excluding OP-only slots for 'hard'/'special'
    if therapy_category and str(therapy_category).lower() in ["hard","special"]:
        allowed_slots = [s for s in general_slots if s not in ["11:30","17:30"]]

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

    # remove any used slots (used_slots is list of slot model instances)
    if used_slots:
        used_slot_strs = [getattr(s, 'start_time').strftime("%H:%M") for s in used_slots if getattr(s, 'start_time', None)]
        allowed_slots = [s for s in allowed_slots if s not in used_slot_strs]

    return allowed_slots 

# -----------------------
# Therapist allocation with Trainee -> Junior substitution (MODIFIED)
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

    # Use last therapists first
    if last_therapists:
        for code in last_therapists:
            try:
                t = TherapistMaster.objects.get(therapist_code=code)
            except TherapistMaster.DoesNotExist:
                continue
            therapist_grade_name = get_therapist_grade_name(t)
            if grade_map.get(therapist_grade_name, 0) > 0:
                # Gender match: skip if therapist gender does not match desired
                if desired_gender:
                    t_gender = get_therapist_gender(t)
                    if t_gender != desired_gender:
                        continue
                if therapist_on_leave(t):
                    continue
                if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                    continue
                allocated.append(t)
                grade_map[therapist_grade_name] -= 1

    # Allocate remaining
    for grade_original, needed_original in list(grade_map.items()):
        
        needed = needed_original
        current_grade_search = grade_original
        
        if needed <= 0:
            continue

        # --- NEW TRAINEE SUBSTITUTION LOGIC ---
        if current_grade_search == "Trainee Therapist" and desired_gender == 'male':
            # Check if any Male Trainee is available (based on previous shell check result: 0)
            # This check is performed using the general TherapistMaster query (no need for a pre-count, filtering query is enough)
            
            # Use a temporary search grade if Trainee is needed and we are looking for a male therapist
            current_grade_search = "Junior Therapist" # Substitute Trainee requirement with Junior search
            print(f"[DEBUG Allocation] Male Trainee required (needed={needed}). Substituting search grade to Junior Therapist.")
            
            # NOTE: The grade_map decrement still targets the original 'Trainee Therapist' key, 
            # ensuring we satisfy the required number of trainee slots with Junior staff.
        # --- END NEW LOGIC ---

        candidates_qs = TherapistMaster.objects.filter(therapist_grade__name=current_grade_search)
        
        # Build an ordered list of candidates (bathing first, then non-bathing)
        if needs_bathing:
            bathing_candidates = list(candidates_qs.filter(is_bathing_therapist=True))
            non_bathing = [t for t in candidates_qs if t not in bathing_candidates]
            candidates_iter = bathing_candidates + non_bathing
        else:
            candidates_iter = list(candidates_qs)
            
        # iterate candidates
        for t in candidates_iter:
            if needed <= 0:
                break
            
            # Check availability constraints
            if t in allocated:
                continue
            if therapist_on_leave(t):
                continue
            if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                continue
            
            # Enforce gender match
            if desired_gender:
                t_gender = get_therapist_gender(t)
                if t_gender != desired_gender:
                    continue
            
            # Allocation successful
            allocated.append(t)
            
            # Decrement both the local needed count AND the original grade map count
            needed -= 1
            grade_map[grade_original] -= 1 # Decrement the original requirement (e.g., Trainee)
            
    return allocated

# -----------------------
# Helper: attempt to allocate for a single canonical slot (returns task dict)
# -----------------------
def attempt_allocate_slot(allocation, booking, date, canonical_slot, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, last_allocation, AllocationAttempt):
    """
    Try to allocate room + therapists for this canonical_slot.
    Returns (task_dict, success_bool, reason_if_failed)
    """
    from Patient.models import RoomBooking, TherapistBooking
    from masters.models import SlotMaster as SlotModel  # used when saving canonical slot objects
    therapy_name = allocation.therapy_name
    booking_id = getattr(booking, 'pk', None)

    requested_slot_value = None
    try:
        requested_slot_value = canonical_slot.slot_time.strftime("%H:%M")
    except Exception:
        pass

    # patient already has booking check (prevents multiple sections for same date+slot)
    patient_already_booked = False
    try:
        patient_already_booked = (
            RoomBooking.objects.filter(patient_id=patient_id, date=date, time_slot=canonical_slot, status__in=['BOOKED','scheduled']).exclude(pk=getattr(booking,'pk',None)).exists()
            or TherapistBooking.objects.filter(patient_id=patient_id, date=date, time_slot=canonical_slot, status='BOOKED').exclude(pk=getattr(booking,'pk',None)).exists()
        )
    except Exception:
        # fallback: compare by start_time
        try:
            slot_start = getattr(canonical_slot, 'start_time', None)
            if slot_start:
                patient_already_booked = (
                    RoomBooking.objects.filter(patient_id=patient_id, date=date, time_slot__start_time=slot_start, status__in=['BOOKED','scheduled']).exclude(pk=getattr(booking,'pk',None)).exists()
                    or TherapistBooking.objects.filter(patient_id=patient_id, date=date, time_slot__start_time=slot_start, status='BOOKED').exclude(pk=getattr(booking,'pk',None)).exists()
                )
        except Exception:
            patient_already_booked = False

    if patient_already_booked:
        reason = "patient_already_has_booking"
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

    # in-run used slot check
    if any(getattr(s, 'start_time', None) == getattr(canonical_slot, 'start_time', None) for s in used_slots):
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

    # candidate therapists
    candidate_therapists = []
    try:
        # Derive patient gender from allocation patient snapshot (e.g., 'Male'/'Female')
        pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
        candidate_therapists = allocate_therapists(
            date,
            canonical_slot,
            therapy_req,
            last_allocation.get("last_therapist_codes"),
            needs_bath_flag,
            patient_gender=pat_sex
        )
    except Exception:
        candidate_therapists = []

    req_total = int(therapy_req.get("total", 1) or 1)
    if len(candidate_therapists) < req_total:
        reason = "insufficient_therapists_available"
        # Gender availability insight (non-blocking, for debugging/UX)
        try:
            desired_gender = None
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
            day_of_week = date.weekday()
            grade_availability = {}
            for grade, needed in therapy_req.items():
                if grade in ("super_senior","senior","junior","trainee") and int(therapy_req.get(grade,0) or 0) > 0:
                    pool = TherapistMaster.objects.filter(therapist_grade__name__icontains=grade.replace('_',' '))
                    available = 0
                    for t in pool:
                        if desired_gender and _tg(t) != desired_gender:
                            continue
                        if TherapistLeaveMaster.objects.filter(therapist=t, leave_day=day_of_week).exists():
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
        therapists_for_audit = [{"therapist_code": getattr(t,'therapist_code',str(t)), "is_bathing": False} for t in candidate_therapists]
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
    if needs_bath_flag and assigned_therapists:
        bath_assigned = next((t for t in assigned_therapists if getattr(t, 'is_bathing_therapist', False)), None)
        if not bath_assigned:
            bath_assigned = assigned_therapists[0]

    therapists_for_audit = [{"therapist_code": getattr(t,'therapist_code',str(t)), "is_bathing": (t==bath_assigned)} for t in assigned_therapists]

    # room allocation if needed
    room_candidate = getattr(booking, 'room', None)
    if needs_room_flag and not room_candidate:
        try:
            # Get patient staying room from allocation
            patient_staying_room = getattr(allocation.patient, 'pat_room_no', None) if allocation and hasattr(allocation, 'patient') else None
            patient_obj = allocation.patient if allocation and hasattr(allocation, 'patient') else None
            room_candidate = allocate_treatment_room(
                date, 
                canonical_slot, 
                last_allocation.get("last_t_room"),
                patient_staying_room=patient_staying_room,
                patient=patient_obj
            )
        except Exception:
            room_candidate = None

    if needs_room_flag and not room_candidate:
        # Build detailed error message based on patient staying room or OP status
        reason = "no_room_available"
        if allocation and hasattr(allocation, 'patient'):
            patient_staying_room = getattr(allocation.patient, 'pat_room_no', None)
            if patient_staying_room:
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

    # Attempt atomic creation/confirmation
    try:
        with transaction.atomic():
            rb_obj = None
            if needs_room_flag and create_bookings:
                rb_obj, rb_created = create_room_booking_safe(room_candidate, date, canonical_slot, therapy_name, patient_id, None)
                if not rb_created:
                    raise RuntimeError("room_already_booked")
            elif needs_room_flag:
                rb_obj = booking if getattr(booking, 'room', None) else None

            tb_objs = []
            for t in assigned_therapists:
                is_bath_for_t = (t == bath_assigned)
                if create_bookings:
                    tb_obj, tb_created = create_therapist_booking_safe(t, date, canonical_slot, therapy_name, patient_id, None, is_bathing=is_bath_for_t)
                    if not tb_created:
                        raise RuntimeError(f"therapist_already_booked:{getattr(t,'therapist_code',str(t))}")
                    tb_objs.append(tb_obj)
                else:
                    tb_objs.append(SimpleNamespace(therapist_code=getattr(t,'therapist_code',str(t)), is_bathing=is_bath_for_t))

            # success audit
            if AllocationAttempt:
                try:
                    AllocationAttempt.objects.create(visit=None, therapy=None, date=date,
                                                     requested_time_slot=canonical_slot, requested_time_slot_value=requested_slot_value or '',
                                                     status='SUCCESS', reason='slot_booked', extra={"room_no": getattr(room_candidate,'room_no',None) if room_candidate else None, "therapists": therapists_for_audit, "booking_id": booking_id})
                except Exception:
                    pass

            # mark used slot in-run
            used_slots.append(canonical_slot)

            # update booking row
            try:
                booking.timeslot = canonical_slot
                booking.room = room_candidate or booking.room
                booking.status = 'scheduled'
                booking.save()
            except Exception:
                pass

            # ensure UI-visible assignments are created for scheduled bookings
            if create_bookings:
                try:
                    from Sheduling.models import BookingAssignment
                    from Patient.models import Therapist as PatientTherapist
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

                            # avoid duplicates by checking therapist+date+slot
                            existing = BookingAssignment.objects.filter(
                                therapist=pt,
                                booking_date=date,
                                booking_timeslot=canonical_slot,
                                booking=booking,
                                status='assigned'
                            ).first()
                            if not existing:
                                BookingAssignment.objects.create(
                                    booking=booking,
                                    therapist=pt,
                                    assigned_for='booking',
                                    status='assigned'
                                )
                        except Exception:
                            continue
                except Exception:
                    # If BookingAssignment model isn't available or fails, continue; UI may fall back to related bookings
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

# -----------------------
# Main: strict preferred-slot-first allocation with automatic fallback
# -----------------------
def expand_therapies_for_visit(therapy_allocation_id, target_date, create_bookings=True):
    """
    Preferred-slot-first allocation using Booking rows.
    If preferred slot fails due to capacity/conflicts, attempts automatic slot allocation
    (OP/IP-aware) to reschedule that booking on the same date.

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

    bookings_qs = Booking.objects.filter(allocation_id=therapy_allocation_id, date=target_date)
    if not bookings_qs.exists():
        return {"error": f"No Booking rows found for allocation {therapy_allocation_id} on {target_date.isoformat()}."}

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

    for booking in bookings_qs:
        booking_id = booking.pk
        therapy_name = allocation.therapy_name

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
            # No preferred -> use automatic slot allocation immediately (do not fail early)
            # Prepare allowed slots for this patient (OP/IP aware)
            therapy_req = therapist_requirements(allocation)
            allowed_slot_values = get_allowed_slot_values(patient_type, therapy_req.get("therapy_category"), used_slots)
            allocated_here = False
            for sv in allowed_slot_values:
                # map to canonical slot model instance
                try:
                    parsed_time = datetime.strptime(sv, "%H:%M").time()
                    canonical_slot = SlotMaster.objects.filter(slot_time=parsed_time).first()
                except Exception:
                    canonical_slot = None
                if not canonical_slot:
                    continue
                task, success, reason = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, therapy_needs_room(allocation), therapy_needs_bath(allocation), used_slots, create_bookings, patient_id, {}, AllocationAttempt)
                if success:
                    tasks.append(task)
                    any_success = True
                    allocated_here = True
                    break
                # else continue trying next slot
            if not allocated_here:
                # Could not allocate any automatic slot
                reason = "no_slot_available_auto"
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

        therapy_req = therapist_requirements(allocation)
        needs_room_flag = therapy_needs_room(allocation)
        needs_bath_flag = therapy_needs_bath(allocation)

        task, success, reason = attempt_allocate_slot(allocation, booking, target_date, canonical_pref, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, {}, AllocationAttempt)
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
            # preferred slot failed -> attempt automatic slots as reschedule when failure is due to
            # capacity/conflict OR patient/slot conflicts. This enables trying alternate slots when
            # the patient already has a booking at the preferred slot.
            fallback_reasons = {
                "insufficient_therapists_available",
                "no_room_available",
                "room_already_booked",
                "therapist_already_booked",
                "patient_already_has_booking",
                "slot_already_used_in_run",
            }
            if reason and any(r in str(reason) for r in fallback_reasons):
                # attempt other allowed slots (OP/IP aware)
                allowed_slot_values = get_allowed_slot_values(patient_type, therapy_req.get("therapy_category"), used_slots)
                # remove preferred if present
                try:
                    pref_val = getattr(canonical_pref, 'start_time', None).strftime("%H:%M") if getattr(canonical_pref,'start_time',None) else None
                except Exception:
                    pref_val = None
                allowed_slot_values = [s for s in allowed_slot_values if s != pref_val]
                allocated_here = False
                for sv in allowed_slot_values:
                    try:
                        parsed_time = datetime.strptime(sv, "%H:%M").time()
                        canonical_slot = SlotMaster.objects.filter(slot_time=parsed_time).first()
                    except Exception:
                        canonical_slot = None
                    if not canonical_slot:
                        continue
                    task2, success2, reason2 = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, {}, AllocationAttempt)
                    if success2:
                        # flag slot_changed so caller knows we used an alternate slot
                        task2["slot_changed"] = True
                        task2["preferred_slot"] = pref_val
                        tasks.append(task2)
                        any_success = True
                        allocated_here = True
                        break
                if allocated_here:
                    continue
                # else fall through to return original failure reason task
            # Preferred failed and no fallback succeeded -> include the failure task (task contains reason)
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
def allocate_therapy_for_visit(therapy_allocation_id, target_date, create_bookings=True):
    """
    Backwards-compatible wrapper expected by callers. Delegates to expand_therapies_for_visit.
    """
    return expand_therapies_for_visit(therapy_allocation_id, target_date, create_bookings=create_bookings)

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