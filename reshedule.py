# allocation_logic.py
from datetime import datetime, timedelta
from types import SimpleNamespace
from django.db import transaction, IntegrityError
from django.db.models import Q

# -----------------------
# Helper: date range
# -----------------------
def daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)

# -----------------------
# Helper: Check if patient is active (not discharged/inactive)
# Reuse from final_allocation to avoid duplication
# -----------------------
try:
    from final_allocation import is_patient_active
except ImportError:
    # Fallback: if import fails, fail-open (treat all patients as active)
    def is_patient_active(pat_reg_no):
        return True

# -----------------------
# Helper: Check if treatment requires senior tag
# -----------------------
def is_treatment_requiring_senior_tag(therapy_name):
    """
    Check if a treatment requires special senior tag handling.
    Returns True ONLY if the therapy name exactly matches one of the specified treatments.
    """
    if not therapy_name:
        return False
    
    # List of treatments that require senior tag (only one senior, not bathing)
    # ONLY these exact treatments should show the senior tag
    special_treatments = [
        'dhara & abh(3)',
        'dhara& pizhichil (4)',
        'dhara & pizhichil (5)',
        'dhara & pizhichil (6)',
        'dhara & pizhichil (7)',
        'dhara & abyangam ( 3 t)',
        'dhara & sudhikalpana dhara (5t)',
        'dhara ( 2 t)',
        'thakradhara & abhyangam (4)',
        'thakradhara & pizichil(6)',
        'thakradhara ( 2 t)',
        'thakradhara&fbkadee kizhi (5 t)',
        'thakradhara& thakrapizhichil(7)',
    ]
    
    # Normalize therapy name: lowercase, remove extra spaces, keep structure
    therapy_normalized = ' '.join(str(therapy_name).lower().strip().split())
    
    # Check for exact match (case-insensitive, ignoring extra spaces)
    for special_treatment in special_treatments:
        special_normalized = ' '.join(special_treatment.lower().strip().split())
        if therapy_normalized == special_normalized:
            return True
    return False
    
# -----------------------
# Senior tag usage helper (max N per therapist per day)
# -----------------------
def get_senior_tag_count_for_therapist(therapist, date):
    """
    Count how many special senior-tag treatments a therapist is already assigned to
    on a given date (based on TherapistBooking records).
    A \"senior-tag\" assignment is defined as:
      - TherapistBooking.therapist == therapist
      - same date
      - status == 'BOOKED'
      - is_bathing == False (only non-bathing senior gets the tag)
      - treatment name is in the special senior list (via is_treatment_requiring_senior_tag)
    """
    from Patient.models import TherapistBooking

    try:
        qs = (TherapistBooking.objects
              .filter(therapist=therapist, date=date, status='BOOKED')
              .select_related('therapy', 'visit'))
    except Exception:
        return 0

    count = 0
    for tb in qs:
        # Only non-bathing sessions can have the senior tag
        if getattr(tb, 'is_bathing', False):
            continue
        name = getattr(tb.therapy, 'therapy_name', None) or getattr(tb, 'therapy_name', None)
        if not name and getattr(tb, 'visit', None) is not None:
            name = getattr(tb.visit, 'therapy_name', None)
        if is_treatment_requiring_senior_tag(name):
            count += 1
    return count

# -----------------------
# Therapy master cache
# -----------------------
therapy_cache = {}
def get_therapy_details(therapy_name):
    """
    Robust therapy lookup that tolerates minor name formatting differences.
    Tries by normalized name (lowercase, extra spaces collapsed) so that
    variations like 'Full Body Navaradhara ( 5 T)' and 'Full Body Navaradhara (5 T)'
    resolve to the same TherapyMaster row.
    """
    from masters.models import TherapyMaster

    raw = (therapy_name or "").strip()
    if not raw:
        return None

    # Cache key based on normalized whitespace + lowercase
    norm_key = " ".join(raw.lower().split())
    if norm_key in therapy_cache:
        return therapy_cache[norm_key]

    details = None

    # 1) Try exact iexact on original name first
    try:
        details = TherapyMaster.objects.get(therapy_name__iexact=raw)
    except TherapyMaster.DoesNotExist:
        details = None

    # 2) If not found, try normalized name match (whitespace-insensitive)
    if details is None:
        try:
            candidates = TherapyMaster.objects.all()
            best = None
            for tm in candidates:
                tname = getattr(tm, "therapy_name", "") or ""
                t_norm = " ".join(tname.lower().split())
                if t_norm == norm_key:
                    best = tm
                    break
            details = best
        except Exception:
            details = None

    therapy_cache[norm_key] = details
    return details

# -----------------------
# Therapy attribute helpers
# -----------------------
def therapy_needs_room(allocation_or_booking):
    th_name = getattr(allocation_or_booking, 'therapy_name', None) or getattr(allocation_or_booking, 'therapy', None)
    details = get_therapy_details(th_name) if th_name else None
    if not details:
        return False
    val = getattr(details, 'treatment_room_required', '')
    return str(val).strip().lower() == 'yes'

def therapy_needs_bath(allocation_or_booking):
    th_name = getattr(allocation_or_booking, 'therapy_name', None) or getattr(allocation_or_booking, 'therapy', None)
    details = get_therapy_details(th_name) if th_name else None
    if not details:
        return False
    val = getattr(details, 'bathing_required', '')
    return str(val).strip().lower() == 'yes'

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
    """
    Create RoomBooking safely.
    visit parameter should be a Booking instance (for RoomBooking.visit FK)
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
                    'visit': visit  # This should be a Booking instance
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
    from django.db import transaction
    
    # CRITICAL: Final check - prevent creating booking if therapist already has 6 sessions
    # This is an atomic database check to prevent race conditions
    if therapist and date:
        current_session_count = TherapistBooking.objects.filter(
            therapist=therapist,
            date=date,
            status='BOOKED'
        ).count()
        if current_session_count >= 6:
            print(f"[DEBUG create_therapist_booking_safe] BLOCKED: Therapist {getattr(therapist, 'therapist_code', 'UNKNOWN')} already has {current_session_count} sessions (max 6) - refusing to create booking")
            # Return None and False to indicate booking was not created due to session limit
            return None, False
    
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
                    # CRITICAL: Before setting this therapist as bathing, ensure NO OTHER therapist
                    # for the SAME visit, SAME date and SAME time_slot is marked as bathing.
                    if visit and time_slot:
                        TherapistBooking.objects.filter(
                            visit=visit,
                            date=date,
                            time_slot=time_slot,
                            status='BOOKED'
                        ).exclude(
                            pk=tb.pk  # Exclude current record
                        ).update(is_bathing=False)
                        print(f"[DEBUG create_therapist_booking_safe] Cleared is_bathing for other therapists in visit {visit.pk} on {date} at {time_slot}")
                    
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
                # CRITICAL: Before setting this therapist as bathing, ensure NO OTHER therapist
                # for the SAME visit, SAME date and SAME time_slot is marked as bathing.
                if tb.visit and tb.time_slot:
                    TherapistBooking.objects.filter(
                        visit=tb.visit,
                        date=tb.date,
                        time_slot=tb.time_slot,
                        status='BOOKED'
                    ).exclude(
                        pk=tb.pk  # Exclude current record
                    ).update(is_bathing=False)
                    print(f"[DEBUG create_therapist_booking_safe] Cleared is_bathing for other therapists in visit {tb.visit.pk} on {tb.date} at {tb.time_slot}")
                
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
    
    Updated Rules:
    - DS-1 to DS-6: TR-1/TR-2 → TR-3/TR-4 → TR-7/TR-8
    - NR-7 to NR-14: TR-3/TR-4 → TR-7/TR-8 → TR-11/TR-12
    - NR-15 to NR-21: TR-5/TR-6 → TR-7/TR-8 → TR-11/TR-12 → TR-9/TR-14
    - NR-22 to NR-27: TR-7/TR-8 → TR-5/TR-6 → TR-11/TR-12 → TR-9/TR-14
    - NR-28 to NR-33: TR-15/TR-16
    - MG-1 to MG-10, CB-1/CB-2, FG-1 to FG-12: TR-9 to TR-14 → TR-7/TR-8
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
    
    # DS-1 to DS-6: TR-1/TR-2 → TR-3/TR-4 → TR-7/TR-8
    if prefix == 'DS' and 1 <= room_num <= 6:
        return ['TR-1', 'TR-2', 'TR-3', 'TR-4', 'TR-7', 'TR-8']
    
    # NR-7 to NR-14: TR-3/TR-4 → TR-7/TR-8 → TR-11/TR-12
    if prefix == 'NR' and 7 <= room_num <= 14:
        return ['TR-3', 'TR-4', 'TR-7', 'TR-8', 'TR-11', 'TR-12']
    
    # NR-15 to NR-21: TR-5/TR-6 → TR-7/TR-8 → TR-11/TR-12 → TR-9/TR-14
    if prefix == 'NR' and 15 <= room_num <= 21:
        return ['TR-5', 'TR-6', 'TR-7', 'TR-8', 'TR-11', 'TR-12', 'TR-9', 'TR-10', 'TR-13', 'TR-14']
    
    # NR-22 to NR-27: TR-7/TR-8 → TR-5/TR-6 → TR-11/TR-12 → TR-9/TR-14
    if prefix == 'NR' and 22 <= room_num <= 27:
        return ['TR-7', 'TR-8', 'TR-5', 'TR-6', 'TR-11', 'TR-12', 'TR-9', 'TR-10', 'TR-13', 'TR-14']
    
    # NR-28 to NR-33: TR-15/TR-16
    if prefix == 'NR' and 28 <= room_num <= 33:
        return ['TR-15', 'TR-16']
    
    # MG-1 to MG-10, CB-1/CB-2, FG-1 to FG-12: TR-9 to TR-14 → TR-7/TR-8
    if prefix == 'MG' and 1 <= room_num <= 10:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']
    if prefix == 'CB' and room_num in [1, 2]:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']
    if prefix == 'FG' and 1 <= room_num <= 12:
        return ['TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-7', 'TR-8']
    
    # CT-1, CT-2, etc.: TRC-1, TRC-2, etc. (same number)
    if prefix == 'CT':
        return [f'TRC-{room_num}']
    
    # OP-* prefix: Return empty list (OP patients are handled separately in allocate_treatment_room)
    if prefix == 'OP':
        return []
    
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
    
    SPECIAL: For 'Dhara & Pizichil' therapies, tries to use previous room assignment first.
    
    If no room available from the list, returns None (allocation will fail).
    
    Args:
        date: Date for allocation
        time_slot: Time slot for allocation
        last_room: Preferred room number (string) or room object (legacy, kept for compatibility)
        therapy_name: Name of the therapy (for Dhara & Pizichil special handling)
        patient_id: Patient ID (for Dhara & Pizichil special handling)
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
    # Special handling: If patient_staying_room starts with "OP-", treat it as if there's no staying room
    # (OP patients are handled in the OP patient fallback logic below)
    staying_room_upper = None
    is_op_prefix = False
    if patient_staying_room:
        staying_room_upper = str(patient_staying_room).strip().upper()
        is_op_prefix = staying_room_upper.startswith('OP-')
    
    if patient_staying_room and not is_op_prefix:
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
    # Check if patient is OP (outpatient) or if staying room starts with "OP-"
    is_op_patient = False
    if (not patient_staying_room or is_op_prefix) and patient:
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
    
    # If staying room starts with "OP-", treat as OP patient
    if is_op_prefix:
        is_op_patient = True
    
    # For OP patients, check if they have a CT room from Treatment model
    # If OP patient has CT room, use TRC room; otherwise use TR-1 to TR-16
    if is_op_patient and patient:
        try:
            # Try to get room number from patient's pat_room_no (should be populated from Treatment model)
            op_staying_room = getattr(patient, 'pat_room_no', None)
            if op_staying_room:
                op_room_upper = str(op_staying_room).strip().upper()
                # Check if it's a CT room - if yes, apply CT room logic (TRC rooms)
                if op_room_upper.startswith('CT'):
                    # Extract CT room number and assign TRC room
                    import re
                    match = re.match(r'CT-?(\d+)', op_room_upper)
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
        except Exception:
            pass
    
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
    
    # SPECIAL: Check if this is a 'Dhara & Pizichil' therapy - try to use previous room first
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
    if is_dhara_pizichil and previous_room_no:
        try:
            previous_room = TreatmentRoom.objects.get(room_no=previous_room_no)
            if not RoomBooking.objects.filter(
                room=previous_room,
                date=date,
                time_slot=time_slot,
                status='BOOKED'
            ).exists():
                print(f"[DEBUG allocate_treatment_room] Using previous Dhara & Pizichil room: {previous_room_no}")
                return previous_room
        except TreatmentRoom.DoesNotExist:
            pass
    
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
def _slot_time_value(slot_obj):
    """Return time (time object) for a slot model. SlotMaster uses slot_time; legacy may use start_time."""
    return getattr(slot_obj, 'slot_time', None) or getattr(slot_obj, 'start_time', None)


def get_allowed_slot_values(patient_type, therapy_category, used_slots=None, therapy_name=None):
    """
    Return ordered list of allowed slot strings "HH:MM" for this patient_type and therapy_category.
    Excludes any used_slots provided (list of slot model instances).
    
    Args:
        patient_type: Patient type (OP/IP)
        therapy_category: Therapy category (easy/medium/hard/special)
        used_slots: List of slot model instances that are already used
        therapy_name: Name of the therapy (for treatment-specific restrictions)
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

    # RESTRICTION: Lepam treatment should not be assigned to 6.30 slot
    if therapy_name:
        therapy_name_lower = str(therapy_name).strip().lower()
        if 'lepam' in therapy_name_lower:
            # Remove 06:30 from allowed slots for Lepam
            allowed_slots = [s for s in allowed_slots if s != "06:30"]
            print(f"[SLOT RESTRICTION] Lepam treatment detected - excluding 06:30 slot. Allowed slots: {allowed_slots}")

    # remove any used slots (used_slots is list of slot model instances; use slot_time for SlotMaster)
    if used_slots:
        used_slot_strs = []
        for s in used_slots:
            t = _slot_time_value(s)
            if t:
                try:
                    used_slot_strs.append(t.strftime("%H:%M"))
                except Exception:
                    pass
        allowed_slots = [s for s in allowed_slots if s not in used_slot_strs]

    return allowed_slots 

# -----------------------
# Therapist allocation with Trainee -> Junior substitution (MODIFIED)
# -----------------------
def allocate_therapists(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False, patient_gender=None):
    from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave, TherapyMaster
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

    # -----------------------
    # Difficulty-aware helpers (Easy / Medium / Hard balance)
    # -----------------------
    therapy_category = None
    category_therapy_names = set()
    try:
        # Expect therapy_requirements to carry the therapy difficulty category
        therapy_category = (therapy_requirements or {}).get("therapy_category")
        if therapy_category:
            # Collect all therapy names that belong to this category so we can
            # count per-therapist load of Easy/Medium/Hard for the day.
            category_therapy_names = set(
                TherapyMaster.objects.filter(
                    therapy_category__iexact=str(therapy_category)
                ).values_list("therapy_name", flat=True)
            )
    except Exception:
        therapy_category = None
        category_therapy_names = set()

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
            db_count = TherapistBooking.objects.filter(
                therapist=t,
                date=date,
                status='BOOKED'
            ).count()
            # Add count of times this therapist has been allocated in current run
            # This prevents assigning 7+ sessions when multiple therapies are allocated in same run
            current_run_count = sum(1 for a in allocated if a == t)
            return db_count + current_run_count
        except Exception:
            return sum(1 for a in allocated if a == t)

    def get_therapist_daily_category_count(t):
        """
        Count how many sessions a therapist already has on this date
        for the current therapy difficulty category (Easy / Medium / Hard).
        If category information is missing, this safely returns 0 so that
        existing behaviour is preserved.
        """
        if not category_therapy_names:
            return 0
        try:
            return TherapistBooking.objects.filter(
                therapist=t,
                date=date,
                status='BOOKED',
                therapy_name__in=category_therapy_names,
            ).count()
        except Exception:
            return 0

    # Use last therapists first
    if last_therapists:
        for code in last_therapists:
            try:
                t = TherapistMaster.objects.get(therapist_code=code)
            except TherapistMaster.DoesNotExist:
                continue
            therapist_grade_name = get_therapist_grade_name(t)
            
            # PRIORITIZE CONTINUITY: Assign previous therapists regardless of grade match
            # Check if grade is needed or can substitute, but don't skip if not needed
            grade_substitution_map = {
                "Super Senior Therapist": ["Senior Therapist", "Junior Therapist", "Trainee Therapist"],
                "Senior Therapist": ["Junior Therapist", "Trainee Therapist"],
                "Junior Therapist": ["Trainee Therapist"],
                "Trainee Therapist": []  # Cannot substitute for higher grades
            }
            
            grade_can_be_used = False
            grade_to_decrement = None
            
            # First check if exact grade is needed
            if grade_map.get(therapist_grade_name, 0) > 0:
                grade_can_be_used = True
                grade_to_decrement = therapist_grade_name
            else:
                # Check if this grade can substitute for a needed grade (for continuity)
                for needed_grade, substitutes in grade_substitution_map.items():
                    if therapist_grade_name in substitutes and grade_map.get(needed_grade, 0) > 0:
                        grade_can_be_used = True
                        grade_to_decrement = needed_grade
                        print(f"[DEBUG Continuity] {t.therapist_code} ({therapist_grade_name}) - using for continuity to substitute {needed_grade}")
                        break
            
            # If no grade can be used, still assign for continuity but log it
            if not grade_can_be_used:
                # Find any grade that still needs therapists (for continuity)
                for needed_grade in grade_map:
                    if grade_map.get(needed_grade, 0) > 0:
                        grade_to_decrement = needed_grade
                        grade_can_be_used = True
                        print(f"[DEBUG Continuity] {t.therapist_code} ({therapist_grade_name}) - assigning for continuity, will use for {needed_grade} requirement")
                        break
            
            # If still no grade available, assign anyway for continuity (will reduce total requirement)
            if not grade_can_be_used:
                # Use the highest priority grade that's still needed
                priority_order = ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
                for priority_grade in priority_order:
                    if grade_map.get(priority_grade, 0) > 0:
                        grade_to_decrement = priority_grade
                        print(f"[DEBUG Continuity] {t.therapist_code} ({therapist_grade_name}) - assigning for continuity, using for {priority_grade} requirement")
                        break
            
            # Gender match: skip if therapist gender does not match desired
            if desired_gender:
                t_gender = get_therapist_gender(t)
                if t_gender != desired_gender:
                    continue
            # Check bathing requirement: if bathing is required, therapist must be a bathing therapist
            if needs_bathing and not getattr(t, 'is_bathing_therapist', False):
                continue
            if therapist_on_leave(t):
                continue
            if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                continue
            
            # Check daily session limit (max 6 sessions)
            session_count = get_therapist_daily_session_count(t)
            if session_count >= 6:
                print(f"[DEBUG Allocation] Therapist {t.therapist_code} at max sessions ({session_count}/6) - skipping")
                continue
            
            # All checks passed - assign this therapist for continuity
            allocated.append(t)
            # Decrement the appropriate grade (may be different from therapist's grade for continuity)
            if grade_to_decrement and grade_map.get(grade_to_decrement, 0) > 0:
                grade_map[grade_to_decrement] -= 1
            print(f"[DEBUG Continuity] ✓ Assigned previous therapist {t.therapist_code} ({therapist_grade_name}) for continuity. Used for {grade_to_decrement} requirement.")

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
        
        # STRICT GENDER FILTER - apply in query for efficiency
        if desired_gender:
            candidates_qs = candidates_qs.filter(therapist_gender__istartswith=desired_gender[0])
        
        # STRICT: Only return bathing therapists when bathing is required
        if needs_bathing:
            candidates_qs = candidates_qs.filter(is_bathing_therapist=True)
        
        candidates_iter = list(candidates_qs)
            
        # Score candidates by (category-specific count, total count) for fair distribution
        scored_candidates = []
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
            
            # Double-check gender match (should already be filtered in query, but safety check)
            if desired_gender:
                t_gender = get_therapist_gender(t)
                if t_gender != desired_gender:
                    continue
            
            total_sessions = get_therapist_daily_session_count(t)
            category_sessions = get_therapist_daily_category_count(t)
            scored_candidates.append((t, category_sessions, total_sessions))

        # Prefer therapists with fewer sessions of this difficulty, then fewer total sessions
        scored_candidates.sort(
            key=lambda item: (
                item[1],                              # category_sessions
                item[2],                              # total_sessions
                getattr(item[0], "id", 0) or 0,       # stable tie-breaker
            )
        )

        # iterate candidates in fair order
        for t, category_sessions, total_sessions in scored_candidates:
            if needed <= 0:
                break

            # Check daily session limit (max 6 sessions)
            # Use total_sessions from scoring, which already includes current run allocations
            if total_sessions >= 6:
                print(f"[DEBUG Allocation] Therapist {t.therapist_code} at max sessions ({total_sessions}/6) - skipping")
                continue

            allocated.append(t)
            
            # Decrement both the local needed count AND the original grade map count
            needed -= 1
            grade_map[grade_original] -= 1  # Decrement the original requirement (e.g., Trainee)
            
    return allocated

# -----------------------
# FALLBACK: Therapist allocation with aggressive grade substitution
# Allows Senior/Super Senior to substitute for Junior/Trainee when they're unavailable
# This is used as a fallback when normal allocation fails
# -----------------------
def allocate_therapists_with_grade_substitution(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False, patient_gender=None):
    """
    Fallback allocation function that allows aggressive grade substitution:
    - Senior/Super Senior can substitute for Junior/Trainee when they're unavailable
    - Senior and Super Senior can substitute for each other (bidirectional)
    - This helps handle more failed schedules by using available therapists
    
    Returns list of allocated TherapistMaster objects.
    """
    from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave, TherapyMaster
    from Patient.models import TherapistBooking

    day_of_week = date.weekday()
    allocated = []

    # Normalize patient gender
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

    # Start with original requirements
    grade_map = {
        "Super Senior Therapist": therapy_requirements.get("super_senior", 0),
        "Senior Therapist": therapy_requirements.get("senior", 0),
        "Junior Therapist": therapy_requirements.get("junior", 0),
        "Trainee Therapist": therapy_requirements.get("trainee", 0)
    }

    # Preload emergency leaves
    try:
        em_leaves_qs = EmergencyLeave.objects.filter(from_date__lte=date, to_date__gte=date)
        emergency_leave_therapist_ids = set(em_leaves_qs.exclude(therapist__isnull=True).values_list('therapist_id', flat=True))
        emergency_leave_employee_codes = set(em_leaves_qs.exclude(employee_code__isnull=True).values_list('employee_code', flat=True))
    except Exception:
        emergency_leave_therapist_ids = set()
        emergency_leave_employee_codes = set()

    def therapist_on_leave(t):
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
            v = getattr(t, 'therapist_gender', None)
            if v:
                v_str = str(v).strip()
                if v_str.lower().startswith('m'):
                    return 'male'
                if v_str.lower().startswith('f'):
                    return 'female'
        except Exception:
            pass
        return None

    def get_therapist_grade_name(t):
        if not t:
            return ''
        if hasattr(t, 'therapist_grade') and t.therapist_grade:
            if hasattr(t.therapist_grade, 'name'):
                return t.therapist_grade.name
        return ''

    def get_therapist_daily_session_count(t):
        try:
            return TherapistBooking.objects.filter(
                therapist=t,
                date=date,
                status='BOOKED'
            ).count()
        except Exception:
            return 0

    # Use last therapists first (if available)
    if last_therapists:
        for code in last_therapists:
            try:
                t = TherapistMaster.objects.get(therapist_code=code)
            except TherapistMaster.DoesNotExist:
                continue
            therapist_grade_name = get_therapist_grade_name(t)
            
            # Check if this therapist can fill any needed grade (with substitution)
            can_use = False
            target_grade = None
            
            # Direct match
            if grade_map.get(therapist_grade_name, 0) > 0:
                can_use = True
                target_grade = therapist_grade_name
            else:
                # Check substitution with bidirectional Senior <-> Super Senior substitution
                if therapist_grade_name == "Senior Therapist":
                    # Senior can substitute for: Super Senior, Junior, Trainee
                    if grade_map.get("Super Senior Therapist", 0) > 0:
                        can_use = True
                        target_grade = "Super Senior Therapist"
                    elif grade_map.get("Junior Therapist", 0) > 0:
                        can_use = True
                        target_grade = "Junior Therapist"
                    elif grade_map.get("Trainee Therapist", 0) > 0:
                        can_use = True
                        target_grade = "Trainee Therapist"
                elif therapist_grade_name == "Super Senior Therapist":
                    # Super Senior can substitute for: Senior, Junior, Trainee
                    if grade_map.get("Senior Therapist", 0) > 0:
                        can_use = True
                        target_grade = "Senior Therapist"
                    elif grade_map.get("Junior Therapist", 0) > 0:
                        can_use = True
                        target_grade = "Junior Therapist"
                    elif grade_map.get("Trainee Therapist", 0) > 0:
                        can_use = True
                        target_grade = "Trainee Therapist"
            
            if not can_use:
                continue
            
            # Check constraints
            if desired_gender:
                t_gender = get_therapist_gender(t)
                if t_gender != desired_gender:
                    continue
            if needs_bathing and not getattr(t, 'is_bathing_therapist', False):
                continue
            if therapist_on_leave(t):
                continue
            if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                continue
            
            # Check daily session limit (max 6 sessions)
            session_count = get_therapist_daily_session_count(t)
            if session_count >= 6:
                print(f"[FALLBACK Grade Substitution] Therapist {t.therapist_code} at max sessions ({session_count}/6) - skipping")
                continue
            
            allocated.append(t)
            grade_map[target_grade] -= 1
            print(f"[FALLBACK Grade Substitution] Assigned {therapist_grade_name} {t.therapist_code} to fill {target_grade} requirement")

    # Allocate remaining with aggressive substitution
    # Process grades in order: Trainee -> Junior -> Senior -> Super Senior
    grade_order = ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
    
    for target_grade in grade_order:
        needed = grade_map.get(target_grade, 0)
        if needed <= 0:
            continue
        
        # Try to find therapists for this grade
        # If not enough, allow substitution with bidirectional Senior <-> Super Senior substitution
        substitution_grades = []
        if target_grade == "Trainee Therapist":
            substitution_grades = ["Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
        elif target_grade == "Junior Therapist":
            substitution_grades = ["Senior Therapist", "Super Senior Therapist"]
        elif target_grade == "Senior Therapist":
            # Senior can be replaced by Super Senior (and vice versa)
            substitution_grades = ["Super Senior Therapist"]
        elif target_grade == "Super Senior Therapist":
            # Super Senior can be replaced by Senior if no Super Senior available
            substitution_grades = ["Senior Therapist"]
        
        # Try exact grade first
        grades_to_try = [target_grade] + substitution_grades
        
        for search_grade in grades_to_try:
            if needed <= 0:
                break
            
            candidates_qs = TherapistMaster.objects.filter(therapist_grade__name=search_grade)
            
            if desired_gender:
                candidates_qs = candidates_qs.filter(therapist_gender__istartswith=desired_gender[0])
            
            if needs_bathing:
                candidates_qs = candidates_qs.filter(is_bathing_therapist=True)
            
            candidates_list = list(candidates_qs)
            scored_candidates = []
            
            for t in candidates_list:
                if t in allocated:
                    continue
                if therapist_on_leave(t):
                    continue
                if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                    continue
                
                if desired_gender:
                    t_gender = get_therapist_gender(t)
                    if t_gender != desired_gender:
                        continue
                
                session_count = get_therapist_daily_session_count(t)
                scored_candidates.append((t, session_count))
            
            # Sort by session count (prefer therapists with fewer sessions)
            scored_candidates.sort(key=lambda x: (x[1], getattr(x[0], "id", 0) or 0))
            
            for t, session_count in scored_candidates:
                if needed <= 0:
                    break
                
                # Check daily session limit (max 6 sessions)
                # Use session_count from scoring, which already includes current run allocations
                if session_count >= 6:
                    print(f"[FALLBACK Grade Substitution] Therapist {t.therapist_code} at max sessions ({session_count}/6) - skipping")
                    continue
                
                allocated.append(t)
                needed -= 1
                grade_map[target_grade] -= 1
                
                if search_grade != target_grade:
                    print(f"[FALLBACK Grade Substitution] Assigned {search_grade} {t.therapist_code} to fill {target_grade} requirement (substitution)")
    
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
    # When rescheduling, exclude bookings from the same allocation to allow slot changes
    patient_already_booked = False
    try:
        # Exclude current booking and any bookings from the same allocation (for rescheduling)
        room_booking_qs = RoomBooking.objects.filter(
            patient_id=patient_id, 
            date=date, 
            time_slot=canonical_slot, 
            status__in=['BOOKED','scheduled']
        ).exclude(pk=getattr(booking,'pk',None))
        
        # Also exclude bookings from the same allocation (allows rescheduling to different slots)
        # RoomBooking.therapy references TherapyAllocation
        if allocation and hasattr(allocation, 'pk'):
            room_booking_qs = room_booking_qs.exclude(therapy=allocation)
        
        therapist_booking_qs = TherapistBooking.objects.filter(
            patient_id=patient_id, 
            date=date, 
            time_slot=canonical_slot, 
            status='BOOKED'
        ).exclude(pk=getattr(booking,'pk',None))
        
        # Also exclude therapist bookings from the same allocation
        # TherapistBooking.visit references TherapyAllocation
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
                ).exclude(pk=getattr(booking,'pk',None))
                
                # RoomBooking.therapy references TherapyAllocation
                if allocation and hasattr(allocation, 'pk'):
                    room_booking_qs = room_booking_qs.exclude(therapy=allocation)
                
                therapist_booking_qs = TherapistBooking.objects.filter(
                    patient_id=patient_id, 
                    date=date, 
                    time_slot__start_time=slot_start, 
                    status='BOOKED'
                ).exclude(pk=getattr(booking,'pk',None))
                
                # TherapistBooking.visit references TherapyAllocation
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
    try:
        from Patient.models import TherapistBooking
        from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave
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
                    # prev_booking.therapist is already a TherapistMaster object
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
                elif EmergencyLeave.objects.filter(
                    from_date__lte=date,
                    to_date__gte=date
                ).filter(
                    Q(therapist=prev_tm) | 
                    Q(employee_code=prev_tm.employee_code)
                ).exists():
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
                        if b.therapist.pk not in seen_b:
                            seen_b.add(b.therapist.pk)
                            therapists_from_start.append(b.therapist)
                    for th in therapists_from_start:
                        on_leave = False
                        if TherapistBooking.objects.filter(therapist=th, date=date, time_slot=canonical_slot, status='BOOKED').exists():
                            on_leave = True
                        if not on_leave and TherapistLeaveMaster.objects.filter(therapist=th, leave_day=day_of_week).exists():
                            on_leave = True
                        if not on_leave and EmergencyLeave.objects.filter(
                            from_date__lte=date, to_date__gte=date
                        ).filter(Q(therapist=th) | Q(employee_code=th.employee_code)).exists():
                            on_leave = True
                        if not on_leave:
                            previous_bathing_therapist = th
                            print(f"[DEBUG] Bathing continuity from start of therapy: {th.therapist_code} for patient {patient_id}")
                            break
                    if not previous_bathing_therapist:
                        for prev_tm in previous_therapist_group:
                            if getattr(prev_tm, 'is_bathing_therapist', False):
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
                        if b.therapist.pk not in seen_b:
                            seen_b.add(b.therapist.pk)
                            therapists_from_start.append(b.therapist)
                    for th in therapists_from_start:
                        on_leave = False
                        if TherapistBooking.objects.filter(therapist=th, date=date, time_slot=canonical_slot, status='BOOKED').exists():
                            on_leave = True
                        if not on_leave and TherapistLeaveMaster.objects.filter(therapist=th, leave_day=day_of_week).exists():
                            on_leave = True
                        if not on_leave and EmergencyLeave.objects.filter(
                            from_date__lte=date, to_date__gte=date
                        ).filter(Q(therapist=th) | Q(employee_code=th.employee_code)).exists():
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
    try:
        # Derive patient gender from allocation patient snapshot (e.g., 'Male'/'Female')
        pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
        
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
                                    print(f"[RESCHEDULE PASS2] ✓ Patient is a REPEATED VISITOR (Total visits: {total_visits}, VIP: {is_vip})")
                                    print(f"[RESCHEDULE PASS2] Proceeding with PatientHistory check...")
                                else:
                                    print(f"[RESCHEDULE PASS2] ✗ Patient is NOT a repeated visitor - Skipping PatientHistory check")
                            else:
                                print(f"[RESCHEDULE PASS2] ✗ Could not extract registration number digits - Skipping PatientHistory check")
                        except (ValueError, TypeError) as e:
                            print(f"[RESCHEDULE PASS2] ✗ Error checking Repeated_Visitors: {e} - Skipping PatientHistory check")
                        
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
                                                therapist_code=therapist_code
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
                                                    print(f"[RESCHEDULE PASS2]   ✓ Therapist {therapist_code} is available - adding to last_therapists")
                                                
                                        except Exception as e:
                                            print(f"[RESCHEDULE PASS2]   Error checking therapist {therapist_code}: {e}")
                                            continue
                                    
                                    # If we found available therapists from this date, we can stop checking further dates
                                    # (prioritize most recent date's therapists)
                                    if date_available_therapists:
                                        print(f"[RESCHEDULE PASS2] ✓ Found {len(date_available_therapists)} available therapist(s) from date {check_date} - stopping date check")
                                        break
                                
                                if available_history_therapists:
                                    last_therapists = available_history_therapists
                                    print(f"[RESCHEDULE PASS2] ✓ ASSIGNED {len(available_history_therapists)} therapist(s) from PatientHistory (checked {dates_checked} date(s)): {available_history_therapists}")
                                else:
                                    print(f"[RESCHEDULE PASS2] ✗ No available therapists found after checking {dates_checked} date(s) from PatientHistory")
                            else:
                                print(f"[RESCHEDULE PASS2] ✗ No history records found for patient {patient_reg_no}")
                        else:
                            print(f"[RESCHEDULE PASS2] ========== END PATIENT HISTORY CHECK (Not a repeated visitor) ==========")
                    else:
                        print(f"[RESCHEDULE PASS2] ✗ Patient registration number not found")
                else:
                    print(f"[RESCHEDULE PASS2] ✗ Patient object not found in allocation")
            except Exception as e:
                print(f"[RESCHEDULE PASS2] ✗ ERROR querying PatientHistory: {e}")
                import traceback
                traceback.print_exc()
            print(f"[RESCHEDULE PASS2] ========== END PATIENT HISTORY CHECK ==========")
        
        # When PASS 1 assigned continuity therapists, add them DIRECTLY to candidate_therapists
        # (bypassing allocate_therapists which would skip them because their PASS 1 BOOKED records
        # make them appear "already booked at this slot"). Only call allocate_therapists for
        # the remaining slots.
        if pass1_continuity_objects and pass1_continuity_assigned:
            candidate_therapists = list(pass1_continuity_objects)
            remaining_req = pass1_continuity_assigned.get('remaining_requirements', {})
            remaining_total = remaining_req.get('total', 0)
            print(f"[RESCHEDULE PASS2] Prepended {len(pass1_continuity_objects)} PASS 1 continuity therapists to candidate_therapists")
            if remaining_total > 0:
                continuity_codes_to_avoid = {
                    getattr(t, 'therapist_code', None)
                    for t in pass1_continuity_objects
                    if getattr(t, 'therapist_code', None)
                }
                remaining_last_therapists = [c for c in last_therapists if c not in continuity_codes_to_avoid] if last_therapists else None
                additional = allocate_therapists(
                    date,
                    canonical_slot,
                    remaining_req,
                    remaining_last_therapists if remaining_last_therapists else None,
                    needs_bath_flag and not pass1_continuity_assigned.get('bath_assigned'),
                    patient_gender=pat_sex,
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
                patient_gender=pat_sex
            )
    except Exception:
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
                patient_gender=pat_sex
            )
            
            if len(candidate_therapists_fallback) >= req_total:
                candidate_therapists = candidate_therapists_fallback
                use_grade_substitution = True
                print(f"[RESCHEDULE FALLBACK] ✓ Grade substitution successful: found {len(candidate_therapists)}/{req_total} therapists")
            else:
                print(f"[RESCHEDULE FALLBACK] ✗ Grade substitution also failed: found {len(candidate_therapists_fallback)}/{req_total} therapists")
        except Exception as e:
            print(f"[RESCHEDULE FALLBACK] Error in grade substitution fallback: {e}")
            import traceback
            traceback.print_exc()
    
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
    bath_assigned_from_pass1 = None
    
    # CRITICAL FIX: Ensure previous bathing therapist is in assigned_therapists if available
    # This fixes the issue where previous bathing therapist might be available but not in first req_total positions
    if needs_bath_flag and previous_bathing_therapist:
        if previous_bathing_therapist in candidate_therapists:
            # Previous bathing therapist is in candidate list but might not be in assigned_therapists
            if previous_bathing_therapist not in assigned_therapists:
                # Previous bathing therapist is available but not in assigned_therapists
                # Force them into assigned_therapists by replacing the last therapist if needed
                print(f"[RESCHEDULE PASS2] ⚠ Previous bathing therapist {previous_bathing_therapist.therapist_code} is available but not in first {req_total} positions")
                print(f"[RESCHEDULE PASS2]   Forcing previous bathing therapist into assigned_therapists for continuity")
                
                # Remove last therapist if we're at capacity, or just add if we have space
                if len(assigned_therapists) >= req_total:
                    # Replace last therapist with previous bathing therapist
                    removed = assigned_therapists.pop()
                    print(f"[RESCHEDULE PASS2]   Removed {removed.therapist_code} to make room for previous bathing therapist")
                assigned_therapists.append(previous_bathing_therapist)
                print(f"[RESCHEDULE PASS2] ✓ Previous bathing therapist {previous_bathing_therapist.therapist_code} now in assigned_therapists")
        else:
            # Previous bathing therapist is NOT in candidate_therapists - check if they're still available
            # This might happen if they were filtered out due to session limit or other constraints
            # Try to add them if they meet basic requirements
            print(f"[RESCHEDULE PASS2] ⚠ Previous bathing therapist {previous_bathing_therapist.therapist_code} is NOT in candidate_therapists")
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
            elif EmergencyLeave.objects.filter(
                from_date__lte=date,
                to_date__gte=date
            ).filter(
                Q(therapist=previous_bathing_therapist) | 
                Q(employee_code=previous_bathing_therapist.employee_code)
            ).exists():
                can_add = False
                print(f"[RESCHEDULE PASS2]   Previous bathing therapist is on emergency leave - cannot add")
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
            # Check gender match
            elif pat_sex:
                desired_gender = 'female' if str(pat_sex).strip().lower().startswith('f') else 'male'
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
                print(f"[RESCHEDULE PASS2] ✓ Added previous bathing therapist {previous_bathing_therapist.therapist_code} to assigned_therapists for continuity")
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
                print(f"[RESCHEDULE] ⚠ PASS 1 assigned same therapist as both bathing and senior: {bath_assigned_from_pass1.therapist_code}")
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
                        print(f"[RESCHEDULE] ✓ Reassigned senior tag to {best.therapist_code} (bathing {bath_assigned_from_pass1.therapist_code} maintained)")
        
        if requires_senior_tag and senior_therapist:
            # Exclude senior therapist from bathing assignment
            bathing_candidates = [t for t in assigned_therapists if t != senior_therapist and getattr(t, 'is_bathing_therapist', False)]
            
            # CRITICAL: Prefer bath_assigned_from_pass1 first (from start of therapy), then previous_bathing_therapist.
            # So Dhara & Pizichil use start-of-therapy bathing therapist when available, not just previous day.
            if bath_assigned_from_pass1 and bath_assigned_from_pass1 in bathing_candidates:
                bath_assigned = bath_assigned_from_pass1
                print(f"[RESCHEDULE] ✓ Special treatment: Using PASS 1 bathing therapist {bath_assigned.therapist_code} (from start of therapy, senior {senior_therapist.therapist_code} excluded)")
            elif previous_bathing_therapist and previous_bathing_therapist in bathing_candidates:
                if bath_assigned != previous_bathing_therapist:
                    print(f"[RESCHEDULE] ⚠ Special treatment: Overriding PASS 1 bathing therapist {bath_assigned.therapist_code if bath_assigned else None} with previous bathing therapist {previous_bathing_therapist.therapist_code} for continuity")
                bath_assigned = previous_bathing_therapist
                print(f"[RESCHEDULE] ✓ Special treatment: Using previous bathing therapist {previous_bathing_therapist.therapist_code} (maintaining continuity, senior {senior_therapist.therapist_code} excluded)")
            elif bathing_candidates:
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
                        therapist_grade__name__in=['Senior Therapist', 'Super Senior Therapist']
                    ).exclude(
                        therapist_code=senior_therapist.therapist_code
                    )
                    print(f"[DEBUG] Grade substitution active: Also considering Super Senior therapists as alternatives")
                else:
                    alternative_seniors = TherapistMaster.objects.filter(
                        therapist_grade__name='Senior Therapist'
                    ).exclude(
                        therapist_code=senior_therapist.therapist_code
                    )
                
                # Filter by gender if needed
                pat_sex = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)
                if pat_sex:
                    desired_gender = 'female' if str(pat_sex).strip().lower().startswith('f') else 'male'
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
                    if EmergencyLeave.objects.filter(
                        from_date__lte=date, to_date__gte=date
                    ).filter(
                        Q(therapist=alt_senior) | Q(employee_code=alt_senior.employee_code)
                    ).exists():
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
                    
                    try:
                        booking.status = 'failed'
                        booking.failure_reason = (str(reason) or '')[:512]
                        booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                    except Exception as e:
                        print(f"Error updating booking {booking_id} to failed: {e}")
                    
                    therapists_for_audit = [{"therapist_code": getattr(t,'therapist_code',str(t)), "is_bathing": False} for t in assigned_therapists]
                    if AllocationAttempt:
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
            # CRITICAL: Prioritize PASS 1 bathing therapist (first-day / from-start-of-therapy) over previous day's.
            # PASS 1 implements "from start of therapy" - when original therapist returns from leave, do not override with yesterday's replacement.
            # Priority order: 1) bath_assigned_from_pass1, 2) previous_bathing_therapist, 3) first from list
            if bath_assigned_from_pass1 and bath_assigned_from_pass1 in assigned_therapists:
                # PASS 1 chose the first-day bathing therapist - keep them
                bath_assigned = bath_assigned_from_pass1
                print(f"[RESCHEDULE] ✓ Using PASS 1 bathing therapist {bath_assigned.therapist_code} for patient {patient_id} (first-day continuity)")
            elif previous_bathing_therapist and previous_bathing_therapist in assigned_therapists:
                # Fallback: previous day's bathing therapist when PASS 1 therapist not in list
                if bath_assigned != previous_bathing_therapist:
                    print(f"[RESCHEDULE] Using previous bathing therapist {previous_bathing_therapist.therapist_code} (PASS 1 therapist not in assigned list)")
                bath_assigned = previous_bathing_therapist
                print(f"[RESCHEDULE] ✓ Using previous bathing therapist {previous_bathing_therapist.therapist_code} for patient {patient_id} (maintaining continuity)")
            else:
                # PASS 1 / previous bathing therapist not in assigned_therapists (e.g. cancelled,
                # on leave, or at max sessions). Reset bath_assigned and pick from the actual list.
                if bath_assigned and bath_assigned not in assigned_therapists:
                    print(f"[RESCHEDULE] ⚠ PASS 1 bathing therapist {getattr(bath_assigned, 'therapist_code', '?')} is NOT in assigned_therapists - resetting to pick from assigned list")
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
                    try:
                        booking.status = 'failed'
                        booking.failure_reason = (str(reason) or '')[:512]
                        booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
                    except Exception as e:
                        print(f"Error updating booking {booking_id} to failed: {e}")
                    
                    therapists_for_audit = [{"therapist_code": getattr(t,'therapist_code',str(t)), "is_bathing": False} for t in assigned_therapists]
                    if AllocationAttempt:
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

    # build therapist audit list - mark senior therapist for special treatments
    therapists_for_audit = []
    for t in assigned_therapists:
        is_bath = (t == bath_assigned)
        # Only mark senior therapist if it's a special treatment AND the therapist is not bathing
        is_senior = (requires_senior_tag and t == senior_therapist and not is_bath)
        therapist_dict = {"therapist_code": getattr(t,'therapist_code',str(t)), "is_bathing": is_bath}
        if is_senior:
            therapist_dict["is_senior"] = True  # Mark senior therapist for UI highlighting
        therapists_for_audit.append(therapist_dict)

    # room allocation if needed
    room_candidate = getattr(booking, 'room', None)
    if needs_room_flag and not room_candidate:
        try:
            # Get patient staying room from allocation
            patient_staying_room = getattr(allocation.patient, 'pat_room_no', None) if allocation and hasattr(allocation, 'patient') else None
            patient_obj = allocation.patient if allocation and hasattr(allocation, 'patient') else None
            # Pass therapy_name and patient_id for Dhara & Pizichil special handling
            room_candidate = allocate_treatment_room(
                date, 
                canonical_slot, 
                last_allocation.get("last_t_room"),
                therapy_name=therapy_name,
                patient_id=patient_id,
                patient_staying_room=patient_staying_room,
                patient=patient_obj
            )
        except Exception:
            room_candidate = None

    if needs_room_flag and not room_candidate:
        # Build detailed error message based on patient staying room or OP status
        reason = "no_room_available"
        # Check if this is Dhara & Pizichil and we had a previous room that's unavailable
        therapy_lower = str(therapy_name or '').lower()
        is_dhara_pizichil = 'dhara' in therapy_lower and 'pizichil' in therapy_lower
        if is_dhara_pizichil and patient_id:
            # Try to find previous room to show in error message
            try:
                from Patient.models import RoomBooking
                previous_booking = RoomBooking.objects.filter(
                    patient_id=patient_id,
                    status='BOOKED'
                ).exclude(date=date).order_by('-date', '-time_slot').select_related('room').first()
                if previous_booking:
                    prev_therapy_lower = str(previous_booking.therapy_name or '').lower()
                    if 'dhara' in prev_therapy_lower and 'pizichil' in prev_therapy_lower:
                        if previous_booking.room:
                            reason = f"previous_room_unavailable: Previous room {previous_booking.room.room_no} for Dhara & Pizichil is unavailable at this slot"
            except Exception:
                pass
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
    if needs_bath_flag and bath_assigned and bath_assigned not in assigned_therapists:
        print(f"[RESCHEDULE] ⚠ SAFETY: bath_assigned {getattr(bath_assigned, 'therapist_code', '?')} is NOT in assigned_therapists! Picking replacement from assigned list.")
        bath_assigned = next((t for t in assigned_therapists if getattr(t, 'is_bathing_therapist', False)), None)
        if bath_assigned:
            print(f"[RESCHEDULE] ✓ SAFETY: Replaced with {bath_assigned.therapist_code} from assigned list")
        else:
            print(f"[RESCHEDULE] ⚠ SAFETY: No bathing therapist in assigned list - bath_assigned remains None")

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
                is_bath_for_t = (t == bath_assigned)
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
            if AllocationAttempt:
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

# -----------------------
# PASS 1: Continuity Priority Pass
# -----------------------
def assign_continuity_therapists_pass1(booking, allocation, target_date, locked_therapist_slots):
    """
    PASS 1 - Continuity Priority Pass:
    Assigns ONLY previous-day therapists for a booking and locks them.
    Does NOT fill remaining slots - that's done in PASS 2.
    
    Args:
        booking: Booking instance
        allocation: TherapyAllocation instance
        target_date: Date for allocation
        locked_therapist_slots: Set of (therapist_id, slot_id) tuples that are already locked
    
    Returns:
        dict with keys:
            - 'assigned_therapists': List of TherapistMaster objects assigned (continuity only)
            - 'remaining_requirements': Dict of remaining therapist requirements
            - 'bath_assigned': TherapistMaster assigned for bathing (if needed)
            - 'senior_therapist': TherapistMaster with senior tag (if special treatment)
            - 'success': bool indicating if any continuity therapists were assigned
    """
    from Patient.models import TherapistBooking
    from Sheduling.models import TherapistContinuityPlan
    from masters.models import SlotMaster, TherapistMaster, TherapistLeaveMaster, EmergencyLeave
    from datetime import timedelta
    
    result = {
        'assigned_therapists': [],
        'remaining_requirements': {},
        'bath_assigned': None,
        'senior_therapist': None,
        'success': False
    }
    
    # Get therapy requirements
    try:
        therapy_req = therapist_requirements(allocation)
    except Exception:
        therapy_req = {"total": 1, "super_senior": 0, "senior": 0, "junior": 0, "trainee": 0, "therapy_category": None}
    
    req_total = int(therapy_req.get("total", 1) or 1)
    if req_total == 0:
        return result
    
    # Get patient info
    patient_id = getattr(allocation.patient, 'id', None)
    patient_gender = getattr(getattr(allocation, 'patient', None), 'pat_sex', None)

    # Determine if this therapy needs a bathing therapist.
    # Primary source: TherapyMaster.bathing_required via therapy_needs_bath(allocation).
    needs_bath_flag = therapy_needs_bath(allocation) if therapy_needs_bath else False

    # Secondary source (continuity): if this allocation already has any previous
    # TherapistBooking rows with is_bathing=True for this patient/allocation,
    # we must continue to treat it as a bathing-required therapy on reschedule,
    # even if the master data is misconfigured.
    if not needs_bath_flag and patient_id:
        try:
            from Patient.models import TherapistBooking
            has_previous_bath = TherapistBooking.objects.filter(
                patient_id=patient_id,
                visit_id=allocation.id,
                is_bathing=True,
                status='BOOKED'
            ).exists()
            if has_previous_bath:
                needs_bath_flag = True
                print(f"[RESCHEDULE] Enabling bathing requirement from history for allocation {allocation.id} (patient {patient_id})")
        except Exception as e:
            print(f"[RESCHEDULE] Error checking previous bathing bookings for allocation {allocation.id}: {e}")

    therapy_name = allocation.therapy_name
    
    # Get slot
    slot = getattr(booking, 'timeslot', None)
    if not slot:
        return result
    
    # Resolve SlotMaster
    slot_master = None
    if isinstance(slot, SlotMaster):
        slot_master = slot
    else:
        slot_time = getattr(slot, 'slot_time', None)
        if slot_time:
            slot_master = SlotMaster.objects.filter(slot_time=slot_time, is_active=True).first()
    
    if not slot_master:
        return result
    
    # Get continuity therapists from plan
    continuity_therapists = []
    previous_bathing_therapist = None
    
    if patient_id:
        try:
            continuity_qs = TherapistContinuityPlan.objects.filter(
                date=target_date,
                time_slot=slot_master,
                allocation_id=allocation.id,
                patient_id=patient_id,
            ).select_related('therapist').order_by('priority', 'therapist_id')
            
            continuity_therapists = [row.therapist for row in continuity_qs if row.therapist]
            
            if needs_bath_flag:
                # BATHING: Always prefer first-day bathing therapist when available (this allocation + slot only).
                try:
                    from masters.models import TherapistLeaveMaster, EmergencyLeave
                    from django.db.models import Q
                    therapy_start_date = getattr(allocation, 'from_date', None)
                    prev_bath_qs = TherapistBooking.objects.filter(
                        patient_id=patient_id,
                        visit_id=allocation.id,
                        time_slot=slot_master,
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
                        if b.therapist.pk not in seen_b:
                            seen_b.add(b.therapist.pk)
                            therapists_from_start.append(b.therapist)
                    original_bathing_therapist = None
                    most_recent_bathing_therapist = therapists_from_start[-1] if therapists_from_start else None
                    day_w = target_date.weekday()
                    for th in therapists_from_start:
                        on_leave = False
                        if TherapistLeaveMaster.objects.filter(therapist=th, leave_day=day_w).exists():
                            on_leave = True
                        if not on_leave and EmergencyLeave.objects.filter(
                            from_date__lte=target_date, to_date__gte=target_date
                        ).filter(Q(therapist=th) | Q(employee_code=th.employee_code)).exists():
                            on_leave = True
                        if not on_leave and TherapistBooking.objects.filter(
                            therapist=th, date=target_date, time_slot=slot_master, status='BOOKED'
                        ).exists():
                            on_leave = True
                        if not on_leave:
                            original_bathing_therapist = th
                            print(f"[RESCHEDULE PASS1] ✓ Bathing continuity: first-day therapist {th.therapist_code} available - use as bathing")
                            break
                    if original_bathing_therapist:
                        previous_bathing_therapist = original_bathing_therapist
                        if original_bathing_therapist not in continuity_therapists:
                            continuity_therapists.insert(0, original_bathing_therapist)
                            print(f"[RESCHEDULE PASS1] ✓ Added first-day bathing therapist {original_bathing_therapist.therapist_code} to continuity_therapists")
                        print(f"[RESCHEDULE PASS1] ✓ Using bathing therapist {previous_bathing_therapist.therapist_code} (from start of therapy)")
                    else:
                        bath_row = next((row for row in continuity_qs if row.is_bathing and getattr(row.therapist, 'is_bathing_therapist', False)), None)
                        if most_recent_bathing_therapist and most_recent_bathing_therapist in continuity_therapists:
                            previous_bathing_therapist = most_recent_bathing_therapist
                        elif bath_row:
                            previous_bathing_therapist = bath_row.therapist
                            print(f"[RESCHEDULE PASS1] ⚠ Using plan bath_row (no one from start available)")
                        else:
                            for t in continuity_therapists:
                                if getattr(t, 'is_bathing_therapist', False):
                                    previous_bathing_therapist = t
                                    break
                except Exception as e:
                    print(f"[RESCHEDULE PASS1] Error finding bathing from start: {e}")
                    bath_row = next((row for row in continuity_qs if row.is_bathing and getattr(row.therapist, 'is_bathing_therapist', False)), None)
                    if bath_row:
                        previous_bathing_therapist = bath_row.therapist
                    else:
                        for t in continuity_therapists:
                            if getattr(t, 'is_bathing_therapist', False):
                                previous_bathing_therapist = t
                                break
            
            print(f"[RESCHEDULE PASS1] Booking {booking.pk}: Found {len(continuity_therapists)} continuity therapists from TherapistContinuityPlan")
            if continuity_therapists:
                print(f"[RESCHEDULE PASS1]   Continuity therapists: {[getattr(t, 'therapist_code', 'UNKNOWN') for t in continuity_therapists]}")
        except Exception as e:
            print(f"[RESCHEDULE PASS1] Error reading continuity plan: {e}")
            continuity_therapists = []
    
    # If no continuity plan, try to find previous day therapists from TherapistBooking
    if not continuity_therapists and patient_id:
        try:
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
                prev_bookings = TherapistBooking.objects.filter(
                    patient_id=patient_id,
                    date=most_recent_date,
                    status='BOOKED'
                ).exclude(
                    visit=allocation
                ).select_related('therapist').order_by('time_slot')
                
                # Extract TherapistMaster objects directly
                previous_therapist_masters = []
                seen_therapist_ids = set()
                for prev_booking in prev_bookings:
                    if prev_booking.therapist:
                        therapist_id = prev_booking.therapist.pk
                        if therapist_id not in seen_therapist_ids:
                            previous_therapist_masters.append(prev_booking.therapist)
                            seen_therapist_ids.add(therapist_id)
                
                if previous_therapist_masters:
                    continuity_therapists = previous_therapist_masters
                    print(f"[RESCHEDULE PASS1] Booking {booking.pk}: Found {len(continuity_therapists)} continuity therapists from previous day ({most_recent_date})")
                    # NORMAL THERAPIST CONTINUITY: Prefer "from start of therapy" for whole set (same as bathing).
                    therapy_start_date = getattr(allocation, 'from_date', None)
                    if therapy_start_date and slot_master:
                        try:
                            from_start_qs = TherapistBooking.objects.filter(
                                visit_id=allocation.id,
                                date__gte=therapy_start_date,
                                date__lt=target_date,
                                time_slot=slot_master,
                                status='BOOKED',
                            ).select_related('therapist').order_by('date', 'created_at')
                            seen_fs = set()
                            therapists_from_start = []
                            for tb in from_start_qs:
                                if not tb.therapist:
                                    continue
                                tid = getattr(tb.therapist, 'id', None)
                                if tid is None or tid in seen_fs:
                                    continue
                                seen_fs.add(tid)
                                therapists_from_start.append(tb.therapist)
                            if therapists_from_start:
                                # Prefer from-start first, then previous-day only
                                continuity_therapists = therapists_from_start + [t for t in continuity_therapists if t not in therapists_from_start]
                                print(f"[RESCHEDULE PASS1] Preferring {len(therapists_from_start)} from-start therapist(s), then previous-day: {[getattr(t, 'therapist_code', '?') for t in continuity_therapists]}")
                        except Exception as e:
                            print(f"[RESCHEDULE PASS1] Error building from-start list: {e}")
                    if needs_bath_flag:
                        # BATHING CONTINUITY: Start from START OF THERAPY (allocation.from_date).
                        # Prefer therapist from Jan 1, then Jan 2, Jan 3, etc. First available today wins.
                        # Bathing therapist should be continuous unless on leave; if Jan 1 not available, try 2nd, 3rd, etc.
                        from masters.models import TherapistLeaveMaster, EmergencyLeave
                        from django.db.models import Q
                        from datetime import timedelta
                        
                        therapy_start_date = getattr(allocation, 'from_date', None)
                        prev_bath_bookings_qs = TherapistBooking.objects.filter(
                            patient_id=patient_id,
                            visit_id=allocation.id,
                            time_slot=slot_master,
                            date__lt=target_date,
                            is_bathing=True,
                            status='BOOKED'
                        ).select_related('therapist').order_by('date', 'created_at')
                        if therapy_start_date:
                            prev_bath_bookings_qs = prev_bath_bookings_qs.filter(date__gte=therapy_start_date)
                        
                        prev_bath_bookings = list(prev_bath_bookings_qs)
                        seen_therapist_ids = set()
                        therapists_from_start = []
                        for prev_bath_booking in prev_bath_bookings:
                            if not prev_bath_booking.therapist:
                                continue
                            tid = prev_bath_booking.therapist.pk
                            if tid not in seen_therapist_ids:
                                seen_therapist_ids.add(tid)
                                therapists_from_start.append(prev_bath_booking.therapist)
                        
                        original_bathing_therapist = None
                        most_recent_bathing_therapist = therapists_from_start[-1] if therapists_from_start else None
                        day_of_week = target_date.weekday()
                        
                        for therapist in therapists_from_start:
                            is_on_leave = False
                            if TherapistLeaveMaster.objects.filter(therapist=therapist, leave_day=day_of_week).exists():
                                is_on_leave = True
                            if not is_on_leave and EmergencyLeave.objects.filter(
                                from_date__lte=target_date,
                                to_date__gte=target_date
                            ).filter(
                                Q(therapist=therapist) | Q(employee_code=therapist.employee_code)
                            ).exists():
                                is_on_leave = True
                            if not is_on_leave and TherapistBooking.objects.filter(
                                therapist=therapist,
                                date=target_date,
                                time_slot=slot_master,
                                status='BOOKED'
                            ).exists():
                                is_on_leave = True
                            if not is_on_leave:
                                original_bathing_therapist = therapist
                                print(f"[RESCHEDULE PASS1] ✓ Bathing continuity from start of therapy: using {therapist.therapist_code} (first available in order from therapy start)")
                                break
                        
                        if original_bathing_therapist:
                            previous_bathing_therapist = original_bathing_therapist
                            if original_bathing_therapist not in continuity_therapists:
                                continuity_therapists.insert(0, original_bathing_therapist)
                                print(f"[RESCHEDULE PASS1] ✓ Added bathing therapist {original_bathing_therapist.therapist_code} to continuity_therapists list")
                            print(f"[RESCHEDULE PASS1] ✓ Using bathing therapist {previous_bathing_therapist.therapist_code} for continuity (from start of therapy)")
                        elif most_recent_bathing_therapist and most_recent_bathing_therapist in continuity_therapists:
                            previous_bathing_therapist = most_recent_bathing_therapist
                            print(f"[RESCHEDULE PASS1] ⚠ All therapists from start on leave; using most recent {most_recent_bathing_therapist.therapist_code} from continuity list")
                        else:
                            for t in continuity_therapists:
                                if getattr(t, 'is_bathing_therapist', False):
                                    previous_bathing_therapist = t
                                    print(f"[RESCHEDULE PASS1] ⚠ Using fallback: Found bathing therapist {t.therapist_code}")
                                    break
        except Exception as e:
            print(f"[RESCHEDULE PASS1] Error finding previous day therapists: {e}")
            continuity_therapists = []
    
    if not continuity_therapists:
        # No continuity therapists - skip this booking in PASS 1
        result['remaining_requirements'] = therapy_req.copy()
        return result
    
    # Check which continuity therapists are available and can be assigned
    day_of_week = target_date.weekday()
    assigned_continuity = []
    grade_map = {
        "Super Senior Therapist": therapy_req.get("super_senior", 0),
        "Senior Therapist": therapy_req.get("senior", 0),
        "Junior Therapist": therapy_req.get("junior", 0),
        "Trainee Therapist": therapy_req.get("trainee", 0)
    }
    
    # Normalize patient gender
    desired_gender = None
    if patient_gender:
        g = str(patient_gender).strip().lower()
        if g.startswith('f'):
            desired_gender = 'female'
        else:
            desired_gender = 'male'
    
    # Check emergency leaves
    try:
        em_leaves_qs = EmergencyLeave.objects.filter(from_date__lte=target_date, to_date__gte=target_date)
        emergency_leave_therapist_ids = set(em_leaves_qs.exclude(therapist__isnull=True).values_list('therapist_id', flat=True))
        emergency_leave_employee_codes = set(em_leaves_qs.exclude(employee_code__isnull=True).values_list('employee_code', flat=True))
    except Exception:
        emergency_leave_therapist_ids = set()
        emergency_leave_employee_codes = set()
    
    def therapist_on_leave(t):
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
            v = getattr(t, 'therapist_gender', None)
            if v:
                v_str = str(v).strip()
                if v_str.lower().startswith('m'):
                    return 'male'
                if v_str.lower().startswith('f'):
                    return 'female'
        except Exception:
            pass
        return None
    
    def get_therapist_grade_name(t):
        if not t:
            return ''
        if hasattr(t, 'therapist_grade') and t.therapist_grade:
            if hasattr(t.therapist_grade, 'name'):
                return t.therapist_grade.name
        return ''
    
    # Try to assign continuity therapists
    for t in continuity_therapists:
        if len(assigned_continuity) >= req_total:
            break
        
        # Check if therapist is already locked by another booking
        lock_key = (t.id, slot_master.id)
        if lock_key in locked_therapist_slots:
            print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} already locked for slot {slot_master.id}")
            continue
        
        # Check availability constraints
        if therapist_on_leave(t):
            print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} on leave - skipping")
            continue
        
        # Check if already booked at this slot
        if TherapistBooking.objects.filter(therapist=t, date=target_date, time_slot=slot_master, status='BOOKED').exists():
            print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} already booked at {target_date} {slot_master} - skipping")
            continue
        
        # Check gender match
        if desired_gender:
            t_gender = get_therapist_gender(t)
            if t_gender != desired_gender:
                print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} gender mismatch ({t_gender} vs {desired_gender}) - skipping")
                continue
        
        # PRIORITIZE CONTINUITY: Assign previous therapists regardless of grade match
        # Check if grade is needed or can substitute, but don't skip if not needed
        therapist_grade_name = get_therapist_grade_name(t)
        
        # Grade substitution hierarchy for continuity (higher grades can substitute for lower)
        substitution_map = {
            "Super Senior Therapist": ["Senior Therapist", "Junior Therapist", "Trainee Therapist"],
            "Senior Therapist": ["Junior Therapist", "Trainee Therapist"],
            "Junior Therapist": ["Trainee Therapist"],
            "Trainee Therapist": []  # Cannot substitute for higher grades
        }
        
        grade_can_be_used = False
        grade_to_decrement = None
        
        # First check if exact grade is needed
        if grade_map.get(therapist_grade_name, 0) > 0:
            grade_can_be_used = True
            grade_to_decrement = therapist_grade_name
        else:
            # Check if this grade can substitute for a needed grade (for continuity)
            for needed_grade, substitutes in substitution_map.items():
                if therapist_grade_name in substitutes and grade_map.get(needed_grade, 0) > 0:
                    grade_can_be_used = True
                    grade_to_decrement = needed_grade
                    print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} grade {therapist_grade_name} can substitute for needed {needed_grade} (continuity)")
                    break
        
        # If no grade can be used, still assign for continuity
        if not grade_can_be_used:
            # Find any grade that still needs therapists (for continuity)
            for needed_grade in grade_map:
                if grade_map.get(needed_grade, 0) > 0:
                    grade_to_decrement = needed_grade
                    grade_can_be_used = True
                    print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} ({therapist_grade_name}) - assigning for continuity, will use for {needed_grade} requirement")
                    break
        
        # If still no grade available, assign anyway for continuity (will reduce total requirement)
        if not grade_can_be_used:
            # Use the highest priority grade that's still needed
            priority_order = ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
            for priority_grade in priority_order:
                if grade_map.get(priority_grade, 0) > 0:
                    grade_to_decrement = priority_grade
                    print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} ({therapist_grade_name}) - assigning for continuity, using for {priority_grade} requirement")
                    break
        
        # Check bathing requirement
        if needs_bath_flag and not getattr(t, 'is_bathing_therapist', False):
            # Only skip if we haven't assigned a bathing therapist yet
            if not result['bath_assigned']:
                print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} not a bathing therapist but bathing required - skipping")
                continue
        
        # Check daily session limit (max 6 sessions)
        # Include therapists already assigned in this pass to prevent exceeding 6 sessions
        db_count = TherapistBooking.objects.filter(
            therapist=t,
            date=target_date,
            status='BOOKED'
        ).count()
        current_pass_count = sum(1 for a in assigned_continuity if a == t)
        session_count = db_count + current_pass_count
        
        if session_count >= 6:
            print(f"[RESCHEDULE PASS1] Therapist {t.therapist_code} at max sessions ({session_count}/6) - skipping")
            continue
        
        # All checks passed - assign this continuity therapist
        assigned_continuity.append(t)
        
        # Decrement the appropriate grade (may be different from therapist's grade for continuity)
        if grade_to_decrement and grade_map.get(grade_to_decrement, 0) > 0:
            grade_map[grade_to_decrement] -= 1
            if grade_to_decrement != therapist_grade_name:
                print(f"[RESCHEDULE PASS1] Using {therapist_grade_name} for continuity to satisfy {grade_to_decrement} requirement")
        
        locked_therapist_slots.add(lock_key)
        
        therapist_code = getattr(t, 'therapist_code', 'UNKNOWN')
        print(f"[RESCHEDULE PASS1] ✓ SELECTED continuity therapist {therapist_code} ({therapist_grade_name}) for booking {booking.pk}")
    
    # Assign bathing therapist if needed
    if needs_bath_flag and assigned_continuity:
        if previous_bathing_therapist and previous_bathing_therapist in assigned_continuity:
            result['bath_assigned'] = previous_bathing_therapist
        else:
            # Find first bathing therapist from assigned list
            for t in assigned_continuity:
                if getattr(t, 'is_bathing_therapist', False):
                    result['bath_assigned'] = t
                    break
    
    # Check for senior tag assignment (special treatments)
    # CRITICAL: Senior therapist MUST be different from bathing therapist
    # Priority: Maintain bathing therapist continuity, assign senior tag to different senior
    requires_senior_tag = is_treatment_requiring_senior_tag(therapy_name)
    if requires_senior_tag and assigned_continuity:
        senior_candidates = []
        bath_assigned = result.get('bath_assigned')
        
        for t in assigned_continuity:
            grade_name = get_therapist_grade_name(t)
            if 'Senior' in grade_name:
                # Exclude bathing therapist from senior tag assignment
                if t != bath_assigned:
                    senior_candidates.append((t, grade_name))
                else:
                    print(f"[RESCHEDULE PASS1] Excluding bathing therapist {t.therapist_code} from senior tag (must be different)")
        
        if senior_candidates:
            from math import inf
            best = None
            best_count = inf
            for t, _ in senior_candidates:
                current = get_senior_tag_count_for_therapist(t, target_date)
                if current < 2 and current < best_count:
                    best = t
                    best_count = current
            if best is not None:
                result['senior_therapist'] = best
                print(f"[RESCHEDULE PASS1] ✓ Assigned senior therapist {best.therapist_code} for senior tag (bathing therapist: {bath_assigned.therapist_code if bath_assigned else None})")
            else:
                print(f"[RESCHEDULE PASS1] ⚠ No suitable senior therapist found for senior tag (all at limit or are bathing therapist)")
        else:
            print(f"[RESCHEDULE PASS1] ⚠ No senior candidates available (excluding bathing therapist)")
    
    # Create TherapistBooking records to lock the therapists
    if assigned_continuity:
        print(f"[RESCHEDULE PASS1] ===== LOCKING {len(assigned_continuity)} THERAPISTS FOR BOOKING {booking.pk} =====")
        try:
            for t in assigned_continuity:
                is_bath = (t == result['bath_assigned'])
                therapist_code = getattr(t, 'therapist_code', 'UNKNOWN')
                therapist_id = getattr(t, 'id', None)
                slot_id = getattr(slot_master, 'id', None)
                
                print(f"[RESCHEDULE PASS1] Creating TherapistBooking to LOCK: therapist={therapist_code} (id={therapist_id}), date={target_date}, slot_id={slot_id}, booking_id={booking.pk}")
                
                # Create TherapistBooking to lock the therapist-slot
                tb_obj, tb_created = create_therapist_booking_safe(
                    t, target_date, slot_master, therapy_name, patient_id, allocation, is_bathing=is_bath
                )
                
                if tb_obj is None:
                    print(f"[RESCHEDULE PASS1] ✗ ERROR: Cannot create TherapistBooking for {therapist_code} - session limit exceeded (>= 6 sessions)")
                    # Remove from assigned list since we couldn't create the booking
                    result['assigned_therapists'] = [at for at in result['assigned_therapists'] if at != t]
                    continue
                elif tb_created:
                    print(f"[RESCHEDULE PASS1] ✓✓✓ LOCKED therapist {therapist_code} (id={therapist_id}) with TherapistBooking pk={tb_obj.pk} for booking {booking.pk}")
                else:
                    print(f"[RESCHEDULE PASS1] ⚠ TherapistBooking already exists for {therapist_code} (id={therapist_id}) - therapist already locked")
        except Exception as e:
            print(f"[RESCHEDULE PASS1] ❌ ERROR creating TherapistBooking locks for booking {booking.pk}: {e}")
            import traceback
            traceback.print_exc()
        print(f"[RESCHEDULE PASS1] ===== FINISHED LOCKING THERAPISTS FOR BOOKING {booking.pk} =====")
    
    # Calculate remaining requirements
    result['assigned_therapists'] = assigned_continuity
    result['remaining_requirements'] = {
        "super_senior": grade_map.get("Super Senior Therapist", 0),
        "senior": grade_map.get("Senior Therapist", 0),
        "junior": grade_map.get("Junior Therapist", 0),
        "trainee": grade_map.get("Trainee Therapist", 0),
        "total": req_total - len(assigned_continuity),
        "therapy_category": therapy_req.get("therapy_category", None)
    }
    result['success'] = len(assigned_continuity) > 0
    
    print(f"[RESCHEDULE PASS1] Booking {booking.pk}: Assigned {len(assigned_continuity)}/{req_total} continuity therapists. Remaining: {result['remaining_requirements']['total']}")
    
    return result

# -----------------------
# Main: strict preferred-slot-first allocation with automatic fallback
# -----------------------
def expand_therapies_for_visit(therapy_allocation_id, target_date, create_bookings=True, booking_continuity_map=None):
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
            # 1. Cancel existing TherapistBooking records linked to this allocation/date
            TherapistBooking.objects.filter(
                visit=allocation,
                date=target_date,
                status='BOOKED'
            ).update(status='CANCELED')

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
            
            print(f"[RESCHEDULE] 🧹 Cleared existing bookings/assignments for allocation {therapy_allocation_id} on {target_date} to prevent ghost therapists")
        except Exception as cleanup_e:
            print(f"[RESCHEDULE] ⚠ Cleanup error (non-fatal): {cleanup_e}")

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
            # No preferred -> use automatic slot allocation immediately (do not fail early)
            # Prepare allowed slots for this patient (OP/IP aware)
            therapy_req = therapist_requirements(allocation)
            allowed_slot_values = get_allowed_slot_values(patient_type, therapy_req.get("therapy_category"), used_slots, therapy_name)
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
                    task, success, reason = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, therapy_needs_room(allocation), therapy_needs_bath(allocation), used_slots, create_bookings, patient_id, last_allocation, AllocationAttempt)
                    if success:
                        task["continuity_maintained"] = True
                        tasks.append(task)
                        any_success = True
                        allocated_here = True
                        print(f"[DEBUG Reschedule] ✓ Successfully allocated to slot {sv} WITH continuity")
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
                    task, success, reason = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, therapy_needs_room(allocation), therapy_needs_bath(allocation), used_slots, create_bookings, patient_id, last_allocation_no_continuity, AllocationAttempt)
                    if success:
                        task["continuity_maintained"] = False
                        tasks.append(task)
                        any_success = True
                        allocated_here = True
                        print(f"[DEBUG Reschedule] ✓ Successfully allocated to slot {sv} WITHOUT continuity")
                        break
                    # else continue trying next slot
            
            if not allocated_here:
                # Could not allocate any automatic slot (neither with nor without continuity)
                reason = "no_slot_available_auto"
                print(f"[DEBUG Reschedule] ✗ Could not allocate to any slot (tried WITH and WITHOUT continuity)")
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
                except Exception as e:
                    print(f"[SLOT RESTRICTION] Error checking preferred slot for Lepam: {e}")

        therapy_req = therapist_requirements(allocation)
        needs_room_flag = therapy_needs_room(allocation)
        needs_bath_flag = therapy_needs_bath(allocation)

        # If preferred slot was rejected for Lepam (canonical_pref is None), skip attempting it
        if not canonical_pref:
            # Force fallback to automatic slot allocation
            task = None
            success = False
            reason = "lepam_cannot_use_0630_slot"
            print(f"[SLOT RESTRICTION] Lepam treatment: Preferred slot 06:30 rejected. Will try alternate slots.")
        else:
            task, success, reason = attempt_allocate_slot(allocation, booking, target_date, canonical_pref, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, last_allocation, AllocationAttempt)
        
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
                elif any(keyword in reason_str for keyword in ["room", "therapist", "patient", "bathing", "available", "booked"]):
                    should_try_fallback = True
                    print(f"[DEBUG Reschedule] Preferred slot failed with reason: {reason}. Will try alternate slots (keyword match).")
            else:
                # If no reason provided, still try fallback (might be a generic failure)
                should_try_fallback = True
                print(f"[DEBUG Reschedule] Preferred slot failed with no reason. Will try alternate slots as fallback.")
            
            if should_try_fallback:
                # attempt other allowed slots (OP/IP aware)
                allowed_slot_values = get_allowed_slot_values(patient_type, therapy_req.get("therapy_category"), used_slots, therapy_name)
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
                        task2, success2, reason2 = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, last_allocation, AllocationAttempt)
                        print(f"[DEBUG Reschedule] Alternate slot {sv} WITH continuity result: success={success2}, reason={reason2}")
                        
                        if success2:
                            # flag slot_changed so caller knows we used an alternate slot
                            task2["slot_changed"] = True
                            task2["preferred_slot"] = pref_val
                            task2["continuity_maintained"] = True
                            tasks.append(task2)
                            any_success = True
                            allocated_here = True
                            print(f"[DEBUG Reschedule] ✓ Successfully allocated to alternate slot {sv} WITH continuity (preferred was {pref_val})")
                            break
                        else:
                            print(f"[DEBUG Reschedule] Alternate slot {sv} WITH continuity failed: {reason2}")
                    
                    if allocated_here:
                        continue
                    else:
                        print(f"[DEBUG Reschedule] ✗ All alternate slots WITH continuity failed. Trying WITHOUT continuity...")
                
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
                    task2, success2, reason2 = attempt_allocate_slot(allocation, booking, target_date, canonical_slot, therapy_req, needs_room_flag, needs_bath_flag, used_slots, create_bookings, patient_id, last_allocation_no_continuity, AllocationAttempt)
                    print(f"[DEBUG Reschedule] Alternate slot {sv} WITHOUT continuity result: success={success2}, reason={reason2}")
                    
                    if success2:
                        # flag slot_changed so caller knows we used an alternate slot
                        task2["slot_changed"] = True
                        task2["preferred_slot"] = pref_val
                        task2["continuity_maintained"] = False
                        tasks.append(task2)
                        any_success = True
                        allocated_here = True
                        print(f"[DEBUG Reschedule] ✓ Successfully allocated to alternate slot {sv} WITHOUT continuity (preferred was {pref_val})")
                        break
                    else:
                        print(f"[DEBUG Reschedule] Alternate slot {sv} WITHOUT continuity failed: {reason2}")
                
                if allocated_here:
                    continue
                else:
                    print(f"[DEBUG Reschedule] ✗ All alternate slots failed (both WITH and WITHOUT continuity). Original failure reason: {reason}")
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