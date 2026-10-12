# allocation_logic.py
from datetime import datetime, timedelta
from types import SimpleNamespace
from django.db import transaction, IntegrityError
from django.db.models import Q

# Raised when not all therapist assignments could be created for a booking.
# Handled so the booking is marked as failed with a user-friendly message (not shown as a site error).
class IncompleteAssignmentError(Exception):
    pass

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
# -----------------------
def is_patient_active(pat_reg_no):
    """
    Check if a patient is active by querying the external Registration / Treatment tables.
    
    IP patients: Registration.pat_status == 'Y' (from therapy_db)
    OP patients: always treated as active (client requirement)
    
    Returns True if the patient is active and scheduling should proceed.
    Returns True on any lookup error (fail-open: don't block scheduling if DB is unreachable).
    """
    if not pat_reg_no:
        return True  # fail-open

    pat_reg_no_str = str(pat_reg_no).strip()

    # --- Check IP patients (Registration table) ---
    try:
        from MySql_Data_pull.models import Registration
        reg = Registration.objects.using('therapy_db').filter(pat_reg_no=pat_reg_no_str).first()
        if not reg:
            # Try numeric lookup (Registration.pat_reg_no is BigIntegerField)
            try:
                reg_no_int = int(pat_reg_no_str)
                reg = Registration.objects.using('therapy_db').filter(pat_reg_no=reg_no_int).first()
            except (ValueError, TypeError):
                pass
        if reg:
            status = (getattr(reg, 'pat_status', None) or '').strip().upper()
            if status and status != 'Y':
                print(f"[PATIENT STATUS] Patient {pat_reg_no_str} is INACTIVE (pat_status='{status}')")
                return False
            # pat_status == 'Y' or empty/null → treat as active
            return True
    except Exception as e:
        print(f"[PATIENT STATUS] Error checking IP status for {pat_reg_no_str}: {e}")

    # OP patients should not be filtered by active/inactive status.
    # We intentionally skip Treatment.Status checks for OP.

    # Default: treat as active (fail-open)
    return True


# -----------------------
# Helper: Patient Age & Desired Therapist Gender
# -----------------------
def parse_patient_age(age_val):
    """
    Safely parse patient age into a float or int.
    Handles None, strings with numbers ('4', '4 years', '4 yrs', '4.5'), ints, floats.
    Returns None if unparseable or unknown.
    """
    if age_val is None:
        return None
    try:
        if isinstance(age_val, (int, float)):
            return float(age_val)
        s = str(age_val).strip()
        if not s or s.lower() in ('unknown', 'none', 'null', 'na', 'n/a', 'undefined'):
            return None
        import re
        m = re.search(r'(\d+(?:\.\d+)?)', s)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def resolve_desired_gender(patient_gender=None, patient_age=None):
    """
    Determine desired therapist gender according to business rules:
    - Female patients -> Female therapist ('female').
    - Male children below 5 -> Female therapist ('female').
    - Male patients aged 5 and above (or default) -> Male therapist ('male').
    """
    try:
        age_num = parse_patient_age(patient_age)
        if age_num is not None and age_num < 5.0:
            return 'female'
        
        if patient_gender:
            g = str(patient_gender).strip().lower()
            if g.startswith('f'):
                return 'female'
            elif g.startswith('m'):
                return 'male'
        return 'male'
    except Exception:
        return 'male'


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
    Tries by therapy_code (if encoded in parentheses) and by normalized name
    (lowercase, extra spaces collapsed) so that variations like
    'Full Body Navaradhara ( 5 T)' and 'Full Body Navaradhara (5 T)' resolve
    to the same TherapyMaster row.
    """
    from masters.models import TherapyMaster

    raw = (therapy_name or "").strip()
    if not raw:
        return None

    # First, try cache by normalized name key
    norm_key = " ".join(raw.lower().split())
    if norm_key in therapy_cache:
        return therapy_cache[norm_key]

    details = None

    # 1) Try exact iexact match on original name.
    # Use filter().first() because duplicate rows may exist.
    details = (
        TherapyMaster.objects.filter(therapy_name__iexact=raw)
        .order_by("id")
        .first()
    )

    # 2) If not found, try normalized whitespace-insensitive match
    if details is None:
        try:
            # Fetch candidates and normalize in Python
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
    # When therapy is NOT found in TherapyMaster, default total=1 (require at least 1 therapist).
    # Previously total=0 caused therapies with unknown names to be auto-scheduled without running
    # the allocation algorithm, resulting in "allocated" status but no therapist assigned.
    if not details:
        return {"super_senior":0, "senior":0, "junior":0, "trainee":0, "total":1, "therapy_code": None, "therapy_category": None}
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
    from masters.models import TherapyMaster
    print(f"[DEBUG create_therapist_booking_safe] Called with: therapist={therapist} (pk={therapist.pk if therapist else None}), date={date}, time_slot={time_slot} (type={type(time_slot)}, pk={time_slot.pk if time_slot else None}), visit={visit} (type={type(visit)}, pk={visit.pk if visit else None})")

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

    # Resolve TherapyMaster FK so TherapistBooking.therapy is never left null when possible
    therapy_obj = None
    try:
        # Prefer therapy_code from the allocation/visit if present
        therapy_code = getattr(visit, "therapy_code", None) if visit is not None else None
        visit_therapy_name = getattr(visit, "therapy_name", None) if visit is not None else None
        if therapy_code:
            therapy_obj = TherapyMaster.objects.filter(therapy_code=therapy_code).first()
        if not therapy_obj and (therapy_name or visit_therapy_name):
            # Fallback: match by case-insensitive therapy_name
            name_for_lookup = therapy_name or visit_therapy_name
            therapy_obj = TherapyMaster.objects.filter(therapy_name__iexact=name_for_lookup).first()
    except Exception as e:
        print(f"[DEBUG create_therapist_booking_safe] Error resolving TherapyMaster for therapy_name='{therapy_name}': {e}")
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
                'visit': visit,
                'therapy': therapy_obj,  # NEW: set FK to TherapyMaster when available
            }
        )
        print(f"[DEBUG create_therapist_booking_safe] get_or_create returned: tb={tb} (pk={tb.pk if tb else None}), created={created}")
        # CRITICAL: Use full save() instead of update_fields to ensure FK is properly set in SQLite
        needs_save = False
        if not created and tb.visit is None and visit is not None:
            print(f"[DEBUG create_therapist_booking_safe] Updating visit for existing TherapistBooking: tb.visit = {visit}")
            tb.visit = visit
            needs_save = True
        elif created and tb.visit != visit and visit is not None:
            print(f"[DEBUG create_therapist_booking_safe] Updating visit for newly created TherapistBooking: tb.visit = {visit}")
            tb.visit = visit
            needs_save = True

        # Ensure therapy FK is populated if we resolved TherapyMaster
        if therapy_obj is not None and getattr(tb, "therapy_id", None) is None:
            print(f"[DEBUG create_therapist_booking_safe] Setting therapy FK on TherapistBooking to {therapy_obj} (pk={therapy_obj.pk})")
            tb.therapy = therapy_obj
            needs_save = True

        if therapist and getattr(therapist, 'is_helping_therapist', False):
            if hasattr(tb, 'is_helping_therapist_assignment') and not tb.is_helping_therapist_assignment:
                tb.is_helping_therapist_assignment = True
                needs_save = True

        if needs_save:
            tb.save()  # Full save to ensure FKs are properly persisted
            tb.refresh_from_db()
            print(f"[DEBUG create_therapist_booking_safe] TherapistBooking FKs updated successfully")
        # persist is_bathing if model supports it and we either created or it's not set
        try:
            if is_bathing and hasattr(tb, 'is_bathing'):
                # CRITICAL: Before setting this therapist as bathing, ensure NO OTHER therapist
                # for the SAME visit, SAME date and SAME time_slot is marked as bathing.
                # We must NOT clear flags from other days.
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
# Shift eligibility helpers (for therapist allocation)
# -----------------------
def _shift_enforcement_enabled():
    """
    Enable shift filtering only when both masters are configured and populated.
    This prevents changing behaviour in existing environments where the new masters
    haven't been filled yet.
    """
    try:
        from masters.models import ShiftSlotMapping, TherapistShiftMapping
        return ShiftSlotMapping.objects.filter(is_active=True).exists() and TherapistShiftMapping.objects.filter(is_active=True).exists()
    except Exception:
        return False


def _shift_eligibility_sets_for_slot(slot_master):
    """
    Returns (mapped_ids, eligible_ids) for a given SlotMaster.
    - mapped_ids: therapists who have at least one active shift mapping
    - eligible_ids: subset of mapped_ids whose shifts contain slot_master
    """
    from masters.models import ShiftSlotMapping, TherapistShiftMapping

    mapped_ids = set(
        TherapistShiftMapping.objects.filter(is_active=True).values_list("therapist_id", flat=True).distinct()
    )
    if not mapped_ids:
        return set(), set()

    eligible_ids = set(
        TherapistShiftMapping.objects.filter(
            is_active=True,
            shift__shift_slots__slot=slot_master,
            shift__shift_slots__is_active=True,
        ).values_list("therapist_id", flat=True).distinct()
    )
    return mapped_ids, eligible_ids

# -----------------------
# Therapist allocation with EmergencyLeave integration
# -----------------------
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
    from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave, TherapyMaster
    from Patient.models import TherapistBooking

    day_of_week = date.weekday()
    allocated = []

    # If patient_age not passed directly, attempt lookup via patient_id
    if patient_age is None and patient_id:
        try:
            from Sheduling.models import PatientSnapshot
            ps = PatientSnapshot.objects.filter(pat_reg_no=str(patient_id)).first()
            if ps and ps.pat_age:
                patient_age = ps.pat_age
        except Exception:
            pass

    # Retrieve active doctor-approved unpreferred therapist preferences for exclusion
    unpreferred_codes = set()
    if patient_id:
        try:
            from Sheduling.preference_views import get_active_patient_therapist_preferences
            _, pref_u = get_active_patient_therapist_preferences(patient_id)
            unpreferred_codes.update(pref_u)
        except Exception as e:
            print(f"[DEBUG TherapistPref] Error fetching preferences for patient {patient_id}: {e}")

    exclusion_set = set(avoid_therapists or [])
    if unpreferred_codes:
        exclusion_set.update(unpreferred_codes)

    # Exclude unpreferred therapists and Helping Therapists from continuity list
    if last_therapists:
        if unpreferred_codes:
            last_therapists = [c for c in last_therapists if c not in unpreferred_codes]
        filtered_last = []
        for c in last_therapists:
            try:
                tm = TherapistMaster.objects.filter(therapist_code=c, is_active=True).first()
                if tm and getattr(tm, 'is_helping_therapist', False):
                    continue
                filtered_last.append(c)
            except Exception:
                filtered_last.append(c)
        last_therapists = filtered_last

    shift_filter_enabled = _shift_enforcement_enabled()
    mapped_ids, eligible_ids = (set(), set())
    if shift_filter_enabled:
        mapped_ids, eligible_ids = _shift_eligibility_sets_for_slot(time_slot)

    # Normalize patient gender (Rule: Male children below 5 should be assigned to a female therapist)
    desired_gender = resolve_desired_gender(patient_gender, patient_age)

    grade_map = {
        # Senior distribution: we still read super_senior for capacity,
        # but do not treat \"Super Senior\" as a senior-tag candidate for special treatments.
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

    def can_assign_therapist(t, allow_extra=False):
        """
        Check if therapist can be assigned based on daily session limit.
        - Normal limit: 5 sessions per day
        - If allow_extra=True and all therapists have 5 sessions, allow 1 extra (max 6)
        - If therapist already has 6 sessions, cannot assign
        """
        if shift_filter_enabled and getattr(t, "id", None) in mapped_ids and getattr(t, "id", None) not in eligible_ids:
            return False
        session_count = get_therapist_daily_session_count(t)
        max_sessions = 6 if allow_extra else 5
        return session_count < max_sessions

    def check_grade_availability(grade, gender_filter, is_helping=False):
        """Check how many therapists of a specific grade and gender are available"""
        candidates_qs = TherapistMaster.objects.filter(therapist_grade__name__iexact=grade, is_active=True, is_helping_therapist=is_helping)
        
        if gender_filter:
            candidates_qs = candidates_qs.filter(therapist_gender__istartswith=gender_filter[0])
        
        print(f"[DEBUG Availability] Checking {gender_filter} {grade}: Found {candidates_qs.count()} in database")
            
        available_count = 0
        unavailable_reasons = {}
        
        for t in candidates_qs:
            reason = None
            if t in allocated:
                reason = "already_allocated_in_this_run"
            elif shift_filter_enabled and t.id in mapped_ids and t.id not in eligible_ids:
                reason = "not_in_shift_time_slot"
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

    # Calculate total required count before allocation
    total_required = sum(v for v in grade_map.values() if v > 0)

    # Helper function to find and allocate candidate therapists per grade requirement
    def _find_and_allocate_candidates(target_grade, needed_original, is_helping_flag=False):
        needed = needed_original
        if needed <= 0:
            return 0

        if not is_helping_flag:
            substitution_hierarchy = {
                "Trainee Therapist": ["Junior Therapist", "Senior Therapist", "Super Senior Therapist"],
                "Junior Therapist": ["Senior Therapist", "Super Senior Therapist", "Trainee Therapist"],
                "Senior Therapist": ["Super Senior Therapist", "Junior Therapist", "Trainee Therapist"],
                "Super Senior Therapist": ["Senior Therapist", "Junior Therapist", "Trainee Therapist"]
            }
        else:
            substitution_hierarchy = {
                "Trainee Therapist": ["Junior Therapist", "Senior Therapist"],
                "Junior Therapist": ["Senior Therapist"],
                "Senior Therapist": [],
                "Super Senior Therapist": []
            }

        search_grades = [target_grade] + substitution_hierarchy.get(target_grade, [])
        assigned_cnt = 0

        for current_grade_search in search_grades:
            if needed <= 0:
                break

            candidates_qs = TherapistMaster.objects.filter(
                therapist_grade__name__iexact=current_grade_search, 
                is_active=True,
                is_helping_therapist=is_helping_flag
            )

            if exclusion_set:
                candidates_qs = candidates_qs.exclude(therapist_code__in=exclusion_set)

            if desired_gender:
                candidates_qs = candidates_qs.filter(therapist_gender__istartswith=desired_gender[0])

            if needs_bathing:
                candidates_qs = candidates_qs.filter(is_bathing_therapist=True)

            candidates_list = list(candidates_qs)
            available_candidates = []
            for t in candidates_list:
                if t in allocated:
                    continue
                if therapist_on_leave(t):
                    continue
                if shift_filter_enabled and t.id in mapped_ids and t.id not in eligible_ids:
                    continue
                if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                    continue

                if desired_gender:
                    t_gender = get_therapist_gender(t)
                    if t_gender != desired_gender:
                        continue

                session_count = get_therapist_daily_session_count(t)
                category_session_count = get_therapist_daily_category_count(t)
                if session_count < 5:
                    available_candidates.append((t, category_session_count, session_count))
                elif session_count == 5:
                    available_candidates.append((t, category_session_count, session_count))

            available_candidates.sort(
                key=lambda x: (
                    x[1],
                    x[2],
                    getattr(x[0], "id", 0) or 0,
                )
            )

            ordered_candidates = available_candidates
            if avoid_therapists:
                try:
                    avoid_set = set(avoid_therapists)
                except TypeError:
                    avoid_set = set(str(c) for c in (avoid_therapists or []))

                primary = []
                secondary = []
                for cand in available_candidates:
                    t = cand[0]
                    code = getattr(t, "therapist_code", None)
                    if code and code in avoid_set:
                        secondary.append(cand)
                    else:
                        primary.append(cand)
                ordered_candidates = primary + secondary

            all_at_limit = all(total_count >= 5 for _, _, total_count in ordered_candidates) if ordered_candidates else False
            allow_extra = all_at_limit

            for t, category_session_count, session_count in ordered_candidates:
                if needed <= 0:
                    break
                if not allow_extra and session_count >= 5:
                    continue
                if allow_extra and session_count >= 6:
                    continue

                allocated.append(t)
                needed -= 1
                assigned_cnt += 1

                if is_helping_flag:
                    try:
                        from Sheduling.models import HelpingTherapistAllocationLog
                        shortage_reason = f"Therapist shortage detected for grade {target_grade} on {date} slot {time_slot}. Primary therapist pool exhausted or unavailable."
                        HelpingTherapistAllocationLog.objects.create(
                            patient_id=str(patient_id or ''),
                            helping_therapist=t,
                            date=date,
                            time_slot=str(getattr(time_slot, 'slot_number', time_slot) or ''),
                            therapy_name=str((therapy_requirements or {}).get('therapy_name', '')),
                            reason_for_fallback="Primary therapist shortage/failure",
                            shortage_condition=shortage_reason,
                            is_supporting_backup=True
                        )
                        print(f"[AUDIT HelpingTherapistLog] Logged fallback allocation of Helping Therapist {t.therapist_code} for patient {patient_id}")
                    except Exception as log_err:
                        print(f"[ERROR HelpingTherapistLog] {log_err}")

        return assigned_cnt

    # -----------------------
    # STEP 1 – Normal Scheduling (First Attempt: consider only is_helping_therapist=False)
    # -----------------------
    if last_therapists:
        for code in last_therapists:
            try:
                t = TherapistMaster.objects.get(therapist_code=code, is_active=True)
                if getattr(t, 'is_helping_therapist', False):
                    continue
            except TherapistMaster.DoesNotExist:
                continue

            therapist_grade_name = get_therapist_grade_name(t)
            grade_substitution_map = {
                "Super Senior Therapist": ["Senior Therapist", "Junior Therapist", "Trainee Therapist"],
                "Senior Therapist": ["Junior Therapist", "Trainee Therapist"],
                "Junior Therapist": ["Trainee Therapist"],
                "Trainee Therapist": []
            }
            
            grade_can_be_used = False
            grade_to_decrement = None
            
            if grade_map.get(therapist_grade_name, 0) > 0:
                grade_can_be_used = True
                grade_to_decrement = therapist_grade_name
            else:
                for needed_grade, substitutes in grade_substitution_map.items():
                    if therapist_grade_name in substitutes and grade_map.get(needed_grade, 0) > 0:
                        grade_can_be_used = True
                        grade_to_decrement = needed_grade
                        break
            
            if not grade_can_be_used:
                for needed_grade in grade_map:
                    if grade_map.get(needed_grade, 0) > 0:
                        grade_to_decrement = needed_grade
                        grade_can_be_used = True
                        break
            
            if not grade_can_be_used:
                priority_order = ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
                for priority_grade in priority_order:
                    if grade_map.get(priority_grade, 0) > 0:
                        grade_to_decrement = priority_grade
                        break

            if desired_gender and get_therapist_gender(t) != desired_gender:
                continue

            if therapist_on_leave(t):
                continue

            if TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                continue

            if not can_assign_therapist(t, allow_extra=False):
                if not can_assign_therapist(t, allow_extra=True):
                    continue

            allocated.append(t)
            if grade_to_decrement and grade_map.get(grade_to_decrement, 0) > 0:
                grade_map[grade_to_decrement] -= 1

    # Allocate remaining using Normal Primary Therapists (is_helping_therapist=False)
    for grade, needed_original in list(grade_map.items()):
        if needed_original <= 0:
            continue
        assigned_cnt = _find_and_allocate_candidates(grade, needed_original, is_helping_flag=False)
        grade_map[grade] -= assigned_cnt

    # -----------------------
    # STEP 2 & 3 – Check for Shortage and Helping Therapist Fallback (Second Attempt)
    # -----------------------
    allocated_primary_count = len(allocated)
    shortage = total_required - allocated_primary_count

    if shortage > 0 and allow_helping_fallback:
        print(f"[DEBUG HelpingTherapist] Primary shortage detected ({shortage} remaining needed out of {total_required}). Triggering Helping Therapist fallback...")

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
                if desired_gender and get_therapist_gender(t) != desired_gender:
                    continue
                if needs_bathing and not t.is_bathing_therapist:
                    continue
                if not can_assign_therapist(t, allow_extra=True):
                    continue

                allocated.append(t)
                try:
                    from Sheduling.models import HelpingTherapistAllocationLog
                    HelpingTherapistAllocationLog.objects.create(
                        patient_id=str(patient_id or ''),
                        helping_therapist=t,
                        date=date,
                        time_slot=str(getattr(time_slot, 'slot_number', time_slot) or ''),
                        therapy_name=str((therapy_requirements or {}).get('therapy_name', '')),
                        reason_for_fallback="Primary therapist shortage/failure",
                        shortage_condition=f"Continuity Helping Therapist fallback triggered due to primary therapist shortage.",
                        is_supporting_backup=True
                    )
                except Exception as log_err:
                    print(f"[ERROR HelpingTherapistLog] {log_err}")

        for grade, needed_original in list(grade_map.items()):
            if needed_original <= 0:
                continue
            assigned_cnt = _find_and_allocate_candidates(grade, needed_original, is_helping_flag=True)
            grade_map[grade] -= assigned_cnt

    return allocated

    return allocated

# -----------------------
# PASS 1: Continuity Priority Pass - Assign previous-day therapists only and lock them
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
    patient_age = getattr(getattr(allocation, 'patient', None), 'pat_age', None)
    needs_bath_flag = therapy_needs_bath(allocation) if therapy_needs_bath else False
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

    # Shift eligibility filter (additive): enforce only when shift masters are configured.
    shift_filter_enabled = _shift_enforcement_enabled()
    mapped_ids, eligible_ids = (set(), set())
    if shift_filter_enabled:
        mapped_ids, eligible_ids = _shift_eligibility_sets_for_slot(slot_master)
    
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
            
            continuity_therapists = [row.therapist for row in continuity_qs if row.therapist and getattr(row.therapist, 'is_active', True)]
            
            if needs_bath_flag:
                # BATHING CONTINUITY: Always prefer FIRST-DAY bathing therapist when they are available.
                # Do NOT use plan's bath_row alone - on Jan 3 plan may say B (from Jan 2), but A (Jan 1) is
                # available again and must be bathing therapist. So always resolve from start of therapy first.
                try:
                    from Patient.models import TherapistBooking
                    from masters.models import TherapistLeaveMaster, EmergencyLeave
                    from django.db.models import Q
                    therapy_start_date = getattr(allocation, 'from_date', None)
                    # Only bathing history for THIS allocation and THIS slot (Dhara & Pizichil 7-day: day 1 bathing must carry to day 2-7)
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
                        if not getattr(prev_bath_booking.therapist, 'is_active', True):
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
                            print(f"[CONTINUITY PASS1] ✓ Bathing continuity: first-day therapist {therapist.therapist_code} available - use as bathing (from start of therapy)")
                            break
                    if original_bathing_therapist:
                        previous_bathing_therapist = original_bathing_therapist
                        if original_bathing_therapist not in continuity_therapists:
                            continuity_therapists.insert(0, original_bathing_therapist)
                            print(f"[CONTINUITY PASS1] ✓ Added first-day bathing therapist {original_bathing_therapist.therapist_code} to continuity_therapists so they get assigned")
                        print(f"[CONTINUITY PASS1] ✓ Using bathing therapist {previous_bathing_therapist.therapist_code} (first available from start of therapy)")
                    else:
                        bath_row = next((row for row in continuity_qs if row.is_bathing and getattr(row.therapist, 'is_bathing_therapist', False) and getattr(row.therapist, 'is_active', True)), None)
                        if most_recent_bathing_therapist and most_recent_bathing_therapist in continuity_therapists:
                            previous_bathing_therapist = most_recent_bathing_therapist
                            print(f"[CONTINUITY PASS1] ⚠ All from start on leave; using most recent {most_recent_bathing_therapist.therapist_code}")
                        elif bath_row:
                            previous_bathing_therapist = bath_row.therapist
                            print(f"[CONTINUITY PASS1] ⚠ Using plan bath_row {previous_bathing_therapist.therapist_code} (no one from start available)")
                        else:
                            for t in continuity_therapists:
                                if getattr(t, 'is_bathing_therapist', False) and getattr(t, 'is_active', True):
                                    previous_bathing_therapist = t
                                    print(f"[CONTINUITY PASS1] ⚠ Using fallback bathing therapist: {t.therapist_code}")
                                    break
                except Exception as e:
                    print(f"[CONTINUITY PASS1] Error finding previous bathing therapist: {e}")
                    bath_row = next((row for row in continuity_qs if row.is_bathing and getattr(row.therapist, 'is_bathing_therapist', False) and getattr(row.therapist, 'is_active', True)), None)
                    if bath_row:
                        previous_bathing_therapist = bath_row.therapist
                    else:
                        for t in continuity_therapists:
                            if getattr(t, 'is_bathing_therapist', False) and getattr(t, 'is_active', True):
                                previous_bathing_therapist = t
                                break
            
            print(f"[CONTINUITY PASS1] Booking {booking.pk}: Found {len(continuity_therapists)} continuity therapists from TherapistContinuityPlan")
            if continuity_therapists:
                print(f"[CONTINUITY PASS1]   Continuity therapists: {[getattr(t, 'therapist_code', 'UNKNOWN') for t in continuity_therapists]}")
        except Exception as e:
            print(f"[CONTINUITY PASS1] Error reading continuity plan: {e}")
            continuity_therapists = []

    # Check active doctor-approved unpreferred therapist preferences for patient
    unpreferred_codes = set()
    if patient_id:
        try:
            from Sheduling.preference_views import get_active_patient_therapist_preferences
            _, pref_u = get_active_patient_therapist_preferences(patient_id)
            unpreferred_codes.update(pref_u)
        except Exception as e:
            print(f"[CONTINUITY PASS1] Error fetching active preferences for patient {patient_id}: {e}")

    if unpreferred_codes:
        continuity_therapists = [t for t in continuity_therapists if getattr(t, 'therapist_code', None) not in unpreferred_codes]

    # Exclude Helping Therapists from Pass 1 (Primary Continuity Pass)
    if continuity_therapists:
        continuity_therapists = [t for t in continuity_therapists if not getattr(t, 'is_helping_therapist', False)]

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
    
    # Normalize patient gender (Rule: Male children below 5 should be assigned to a female therapist)
    desired_gender = resolve_desired_gender(patient_gender, patient_age)
    
    # Check emergency leaves
    try:
        from masters.models import EmergencyLeave
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
        
        # Skip inactive therapists
        if not getattr(t, 'is_active', True):
            print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} is INACTIVE - skipping")
            continue
        
        # Check if therapist is already locked by another booking
        lock_key = (t.id, slot_master.id)
        if lock_key in locked_therapist_slots:
            print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} already locked for slot {slot_master.id}")
            continue
        
        # Check availability constraints
        if therapist_on_leave(t):
            print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} on leave - skipping")
            continue

        # Shift eligibility
        if shift_filter_enabled and t.id in mapped_ids and t.id not in eligible_ids:
            continue
        
        # Check if already booked at this slot
        if TherapistBooking.objects.filter(therapist=t, date=target_date, time_slot=slot_master, status='BOOKED').exists():
            print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} already booked at {target_date} {slot_master} - skipping")
            continue
        
        # Check gender match
        if desired_gender:
            t_gender = get_therapist_gender(t)
            if t_gender != desired_gender:
                print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} gender mismatch ({t_gender} vs {desired_gender}) - skipping")
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
                    print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} grade {therapist_grade_name} can substitute for needed {needed_grade} (continuity)")
                    break
        
        # If no grade can be used, still assign for continuity
        if not grade_can_be_used:
            # Find any grade that still needs therapists (for continuity)
            for needed_grade in grade_map:
                if grade_map.get(needed_grade, 0) > 0:
                    grade_to_decrement = needed_grade
                    grade_can_be_used = True
                    print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} ({therapist_grade_name}) - assigning for continuity, will use for {needed_grade} requirement")
                    break
        
        # If still no grade available, assign anyway for continuity (will reduce total requirement)
        if not grade_can_be_used:
            # Use the highest priority grade that's still needed
            priority_order = ["Trainee Therapist", "Junior Therapist", "Senior Therapist", "Super Senior Therapist"]
            for priority_grade in priority_order:
                if grade_map.get(priority_grade, 0) > 0:
                    grade_to_decrement = priority_grade
                    print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} ({therapist_grade_name}) - assigning for continuity, using for {priority_grade} requirement")
                    break
        
        # Check bathing requirement
        if needs_bath_flag and not getattr(t, 'is_bathing_therapist', False):
            # Only skip if we haven't assigned a bathing therapist yet
            if not result['bath_assigned']:
                print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} not a bathing therapist but bathing required - skipping")
                continue
        
        # Check daily session limit (max 5, or 6 if all therapists are at limit)
        # Include therapists already assigned in this pass to prevent exceeding 6 sessions
        db_count = TherapistBooking.objects.filter(
            therapist=t,
            date=target_date,
            status='BOOKED'
        ).count()
        current_pass_count = sum(1 for a in assigned_continuity if a == t)
        session_count = db_count + current_pass_count
        
        if session_count >= 6:
            print(f"[CONTINUITY PASS1] Therapist {t.therapist_code} at max sessions ({session_count}/6) - skipping")
            continue
        
        # All checks passed - assign this continuity therapist
        assigned_continuity.append(t)
        
        # Decrement the appropriate grade (may be different from therapist's grade for continuity)
        if grade_to_decrement and grade_map.get(grade_to_decrement, 0) > 0:
            grade_map[grade_to_decrement] -= 1
            if grade_to_decrement != therapist_grade_name:
                print(f"[CONTINUITY PASS1] Using {therapist_grade_name} for continuity to satisfy {grade_to_decrement} requirement")
        
        locked_therapist_slots.add(lock_key)
        
        therapist_code = getattr(t, 'therapist_code', 'UNKNOWN')
        print(f"[CONTINUITY PASS1] ✓ SELECTED continuity therapist {therapist_code} ({therapist_grade_name}) for booking {booking.pk}")
        print(f"[CONTINUITY PASS1]   - Added to locked_therapist_slots: (therapist_id={t.id}, slot_id={slot_master.id})")
        print(f"[CONTINUITY PASS1]   - Will create TherapistBooking to LOCK this therapist-slot combination")
    
    # Assign bathing therapist FIRST (maintain continuity for bathing)
    # Priority: Previous bathing therapist should remain as bathing therapist
    if needs_bath_flag and assigned_continuity:
        if previous_bathing_therapist and previous_bathing_therapist in assigned_continuity:
            result['bath_assigned'] = previous_bathing_therapist
            print(f"[CONTINUITY PASS1] ✓ Using previous bathing therapist: {previous_bathing_therapist.therapist_code} (maintaining continuity)")
        else:
            # Find first bathing therapist from assigned list
            # But log a warning if previous_bathing_therapist was identified but not in assigned_continuity
            if previous_bathing_therapist:
                print(f"[CONTINUITY PASS1] ⚠ Previous bathing therapist {previous_bathing_therapist.therapist_code} identified but not in assigned_continuity (may have been filtered out)")
            for t in assigned_continuity:
                if getattr(t, 'is_bathing_therapist', False):
                    result['bath_assigned'] = t
                    print(f"[CONTINUITY PASS1] Assigned bathing therapist: {t.therapist_code} (previous {previous_bathing_therapist.therapist_code if previous_bathing_therapist else 'None'} not available)")
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
                    print(f"[CONTINUITY PASS1] Excluding bathing therapist {t.therapist_code} from senior tag (must be different)")
        
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
                print(f"[CONTINUITY PASS1] Assigned senior_therapist: {best.therapist_code} (senior tag count: {best_count}, different from bathing {bath_assigned.therapist_code if bath_assigned else None})")
            else:
                print(f"[CONTINUITY PASS1] ⚠ No senior therapist available for senior tag (excluding bathing therapist)")
        else:
            print(f"[CONTINUITY PASS1] ⚠ No senior candidates available (excluding bathing therapist)")
    
    # Final validation: Ensure bathing and senior therapists are different for special treatments
    if requires_senior_tag and result.get('senior_therapist') and result.get('bath_assigned'):
        if result['senior_therapist'] == result['bath_assigned']:
            print(f"[CONTINUITY PASS1] ⚠ ERROR: Senior therapist {result['senior_therapist'].therapist_code} is same as bathing therapist!")
            print(f"[CONTINUITY PASS1] This should not happen - clearing senior assignment, will be reassigned in PASS 2")
            # Clear senior assignment - it will be reassigned in PASS 2 with proper exclusion
            result['senior_therapist'] = None
    
    # Create TherapistBooking records to lock the therapists
    if assigned_continuity:
        print(f"[CONTINUITY PASS1] ===== LOCKING {len(assigned_continuity)} THERAPISTS FOR BOOKING {booking.pk} =====")
        try:
            for t in assigned_continuity:
                is_bath = (t == result['bath_assigned'])
                therapist_code = getattr(t, 'therapist_code', 'UNKNOWN')
                therapist_id = getattr(t, 'id', None)
                slot_id = getattr(slot_master, 'id', None)
                
                print(f"[CONTINUITY PASS1] Creating TherapistBooking to LOCK: therapist={therapist_code} (id={therapist_id}), date={target_date}, slot_id={slot_id}, booking_id={booking.pk}")
                
                # Create TherapistBooking to lock the therapist-slot
                # This creates a BOOKED record that prevents other bookings from using this therapist-slot
                tb_obj, tb_created = create_therapist_booking_safe(
                    t, target_date, slot_master, therapy_name, patient_id, allocation, is_bathing=is_bath
                )
                
                if tb_obj is None:
                    print(f"[CONTINUITY PASS1] ✗ ERROR: Cannot create TherapistBooking for {therapist_code} - session limit exceeded (>= 6 sessions)")
                    # Remove from assigned list since we couldn't create the booking
                    result['assigned_therapists'] = [at for at in result['assigned_therapists'] if at != t]
                    continue
                elif tb_created:
                    print(f"[CONTINUITY PASS1] ✓✓✓ LOCKED therapist {therapist_code} (id={therapist_id}) with TherapistBooking pk={tb_obj.pk} for booking {booking.pk}")
                    print(f"[CONTINUITY PASS1]   - TherapistBooking: pk={tb_obj.pk}, therapist_id={tb_obj.therapist_id}, date={tb_obj.date}, slot_id={tb_obj.time_slot_id}, status={tb_obj.status}")
                else:
                    print(f"[CONTINUITY PASS1] ⚠ TherapistBooking already exists for {therapist_code} (id={therapist_id}) - therapist already locked")
                    if tb_obj:
                        print(f"[CONTINUITY PASS1]   - Existing TherapistBooking: pk={tb_obj.pk}, therapist_id={tb_obj.therapist_id}, date={tb_obj.date}, slot_id={tb_obj.time_slot_id}")
        except Exception as e:
            print(f"[CONTINUITY PASS1] ❌ ERROR creating TherapistBooking locks for booking {booking.pk}: {e}")
            import traceback
            traceback.print_exc()
        print(f"[CONTINUITY PASS1] ===== FINISHED LOCKING THERAPISTS FOR BOOKING {booking.pk} =====")
    
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
    
    print(f"[CONTINUITY PASS1] Booking {booking.pk}: Assigned {len(assigned_continuity)}/{req_total} continuity therapists. Remaining: {result['remaining_requirements']['total']}")
    
    return result

# -----------------------
# Main: strict preferred-slot-only allocation with bathing assignee persisted
# -----------------------
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
    patient_staying_room = getattr(allocation.patient, 'pat_room_no', None)
    
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
        # Vasthi therapy group (masters), except Mathra THEB037: final schedule must use 08:30 only
        try:
            from reshedule import is_group_vasthi_0830_only
            if is_group_vasthi_0830_only(therapy_name, getattr(allocation, 'therapy_code', None)):
                sm0830 = SlotMaster.objects.filter(
                    slot_time=datetime.strptime('08:30', '%H:%M').time(),
                    is_active=True,
                ).first()
                if sm0830:
                    pref_slot = sm0830
                    if create_bookings and getattr(booking, 'timeslot_id', None) != sm0830.id:
                        booking.timeslot = sm0830
                        booking.save(update_fields=['timeslot', 'updated_at'])
                else:
                    print('[VASTHI GROUP] Final schedule: no active SlotMaster for 08:30')
        except Exception as _gv_e:
            print(f'[VASTHI GROUP] Final schedule slot rule skipped: {_gv_e}')
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
        # IMPORTANT: Exclude TherapistBooking records from PASS 1 (same visit/allocation) to avoid false positives
        patient_already_booked = False
        try:
            patient_already_booked = (
                RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=query_slot, status__in=['BOOKED','scheduled']).exclude(pk=booking.pk).exists()
                or TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot=query_slot, status='BOOKED').exclude(pk=booking.pk).exclude(visit_id=allocation.id).exists()
            )
        except Exception:
            try:
                slot_start = getattr(pref_slot, 'start_time', None)
                if slot_start:
                    patient_already_booked = (
                        RoomBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot__start_time=slot_start, status__in=['BOOKED','scheduled']).exclude(pk=booking.pk).exists()
                        or TherapistBooking.objects.filter(patient_id=patient_id, date=target_date, time_slot__start_time=slot_start, status='BOOKED').exclude(pk=booking.pk).exclude(visit_id=allocation.id).exists()
                    )
            except Exception:
                patient_already_booked = False

        if patient_already_booked:
            reason = "patient_already_has_booking"
            print(f"[CONTINUITY PASS2] Booking {booking_id}: SKIPPING due to patient_already_has_booking (continuity_assigned={continuity_assigned is not None})")
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
                            if not on_leave and EmergencyLeave.objects.filter(
                                from_date__lte=target_date, to_date__gte=target_date
                            ).filter(Q(therapist=th) | Q(employee_code=th.employee_code)).exists():
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
            remaining_req = continuity_assigned.get('remaining_requirements', therapy_req)
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
                if previous_therapist_group and len(previous_therapist_group) > 0:
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
        if len(candidate_therapists) < req_total:
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
            # Try to infer patient gender for message consistency (Rule: Male children below 5 assigned to female therapist)
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
                # CRITICAL FIX: Prioritize bath_assigned_from_pass1 (from PASS 1) over previous_bathing_therapist
                # This ensures continuity is maintained even if previous_bathing_therapist is not in assigned_therapists
                preferred_bathing_therapist = bath_assigned_from_pass1 if bath_assigned_from_pass1 and bath_assigned_from_pass1 in assigned_therapists else None
                if not preferred_bathing_therapist and previous_bathing_therapist and previous_bathing_therapist in assigned_therapists:
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
                            from masters.models import EmergencyLeave
                            from django.db.models import Q
                            if EmergencyLeave.objects.filter(
                                from_date__lte=target_date, to_date__gte=target_date
                            ).filter(
                                Q(therapist=alt_senior) | Q(employee_code=alt_senior.employee_code)
                            ).exists():
                                continue
                            
                            # Found alternative senior - replace current senior and use this one for bathing
                            print(f"[DEBUG] Dhara & Pizichil: Found alternative senior {alt_senior.therapist_code} who can be bathing therapist")
                            assigned_therapists = [alt_senior if t == senior_therapist else t for t in assigned_therapists]
                            senior_therapist = alt_senior
                            bath_assigned = alt_senior
                            break
                        
                        if not bath_assigned:
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
                # CRITICAL: Prioritize PASS 1 bathing therapist (first-day / from-start-of-therapy) over previous day's.
                # PASS 1 already implements "from start of therapy" - so when original therapist returns from leave, we must not override with yesterday's replacement.
                # Priority order: 1) bath_assigned_from_pass1, 2) previous_bathing_therapist, 3) first from list
                if bath_assigned_from_pass1 and bath_assigned_from_pass1 in assigned_therapists:
                    # PASS 1 chose the first-day bathing therapist (or first available from start of therapy) - keep them
                    bath_assigned = bath_assigned_from_pass1
                    print(f"[DEBUG] ✓ Using PASS 1 bathing therapist {bath_assigned.therapist_code} for patient {patient_id} (first-day continuity)")
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

        # build therapist audit list - mark senior therapist for special treatments
        therapists_for_audit = []
        for t in assigned_therapists:
            is_bath = (t == bath_assigned)
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
                    # DO NOT set status='scheduled' yet - wait until all BookingAssignment records are created
                    print(f"[DEBUG] Setting booking.timeslot and room BEFORE creating any related objects")
                    booking.timeslot = slot_master
                    booking.room = room_candidate or booking.room
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
                    # Check which therapists are from PASS 1 continuity (already have TherapistBooking)
                    continuity_therapist_ids = set()
                    if continuity_assigned and isinstance(continuity_assigned, dict):
                        continuity_therapists = continuity_assigned.get('assigned_therapists', [])
                        continuity_therapist_ids = {getattr(t, 'id', None) for t in continuity_therapists if hasattr(t, 'id')}
                    
                    for t in assigned_therapists:
                        is_bath_for_t = (t == bath_assigned)
                        therapist_id = getattr(t, 'id', None)
                        is_continuity_therapist = therapist_id in continuity_therapist_ids
                        
                        if create_bookings:
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
                                        print(f"[CONTINUITY PASS2] ✗ ERROR: Cannot create TherapistBooking for {t.therapist_code} - session limit exceeded (>= 6 sessions)")
                                        # This should not happen if checks were done correctly, but handle gracefully
                                        continue
                                    tb_objs.append(tb_obj)
                            else:
                                # New therapist - create TherapistBooking
                                print(f"[CONTINUITY PASS2] Creating new TherapistBooking for therapist {t.therapist_code}")
                                # Pass allocation (TherapyAllocation) instead of None for visit FK
                                # Use slot_master (resolved SlotMaster) instead of canonical_slot to ensure FK is valid
                                tb_obj, tb_created = create_therapist_booking_safe(t, target_date, slot_master, therapy_name, patient_id, allocation, is_bathing=is_bath_for_t)
                                if tb_obj is None:
                                    print(f"[CONTINUITY PASS2] ✗ ERROR: Cannot create TherapistBooking for {t.therapist_code} - session limit exceeded (>= 6 sessions)")
                                    # This should not happen if checks were done correctly, but handle gracefully
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
    from Sheduling.models import TherapyAllocation, TherapistContinuityPlan
    
    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return {
            'success': False,
            'error': f'Invalid date format: {target_date_str}. Expected YYYY-MM-DD'
        }
    
    # Get all draft bookings for the target date
    # We will process them in a patient-aware order (older-from_date therapies first)
    from Sheduling.models import Booking
    draft_bookings_qs = Booking.objects.filter(
        date=target_date,
        status='draft'
    ).select_related('allocation', 'allocation__patient')
    
    if not draft_bookings_qs.exists():
        return {
            'success': True,
            'message': 'No draft therapies found for the selected date',
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'results': []
        }

    # Order bookings per patient by therapy start date (allocation.from_date) so that,
    # for the same patient, earlier-started therapies get continuity first.
    from collections import defaultdict
    by_patient = defaultdict(list)
    for b in draft_bookings_qs:
        pat = getattr(b.allocation, 'patient', None)
        pid = getattr(pat, 'id', None)
        by_patient[pid].append(b)

    # ----- INACTIVE PATIENT CHECK (bulk) -----
    # Before processing, check each patient's active status.
    # If inactive, mark all their draft bookings as failed and remove from processing.
    inactive_patient_ids = set()
    inactive_failed_count = 0
    for pid, bookings in list(by_patient.items()):
        if not bookings:
            continue
        # Get pat_reg_no from the first booking's patient snapshot
        first_pat = getattr(bookings[0].allocation, 'patient', None) if bookings[0].allocation else None
        pat_reg_no = getattr(first_pat, 'pat_reg_no', None) if first_pat else None
        if pat_reg_no and not is_patient_active(pat_reg_no):
            pat_name = getattr(first_pat, 'pat_name', 'Unknown') if first_pat else 'Unknown'
            print(f"[PATIENT STATUS] Patient {pat_reg_no} ({pat_name}) is INACTIVE - "
                  f"marking {len(bookings)} draft bookings as failed")
            for b in bookings:
                try:
                    b.status = 'failed'
                    b.failure_reason = 'Patient Inactive'
                    b.save(update_fields=['status', 'failure_reason', 'updated_at'])
                    inactive_failed_count += 1
                except Exception as e:
                    print(f"[PATIENT STATUS] Error marking booking {b.pk} as failed: {e}")
            inactive_patient_ids.add(pid)
    # Remove inactive patients from the processing map
    for pid in inactive_patient_ids:
        del by_patient[pid]
    if inactive_failed_count > 0:
        print(f"[PATIENT STATUS] Total inactive patient bookings marked as failed: {inactive_failed_count}")

    ordered_bookings = []
    for pid, bookings in by_patient.items():
        bookings.sort(key=lambda bk: getattr(bk.allocation, 'from_date', target_date))
        ordered_bookings.extend(bookings)
    
    # Derive the unique allocations from these ordered bookings
    allocation_ids = []
    seen_alloc_ids = set()
    for b in ordered_bookings:
        aid = getattr(b.allocation, 'id', None)
        if aid and aid not in seen_alloc_ids:
            seen_alloc_ids.add(aid)
            allocation_ids.append(aid)
    draft_allocations = TherapyAllocation.objects.filter(id__in=allocation_ids)
    
    results = []
    successful_count = 0
    failed_count = 0

    # ---------------------------------------
    # Phase 1: Build continuity plan in DB
    # ---------------------------------------
    try:
        from Sheduling.models import Booking as _Booking
        from Patient.models import TherapistBooking as _TB
        from masters.models import SlotMaster as _SlotMaster, TherapistMaster as _TM, TherapyMaster as _ThM
        from django.db.models import Max, Q

        # Clear existing plan for this date
        TherapistContinuityPlan.objects.filter(date=target_date).delete()

        # Draft bookings for this date
        draft_bookings = _Booking.objects.filter(
            date=target_date,
            status='draft',
        ).select_related('allocation', 'timeslot', 'allocation__patient')

        for booking in draft_bookings:
            allocation = booking.allocation
            patient = getattr(allocation, 'patient', None)
            slot = booking.timeslot
            if not allocation or not patient or not slot:
                continue

            patient_snapshot_id = getattr(patient, 'id', None)
            patient_name = getattr(patient, 'pat_name', '') or ''
            current_therapy_name = allocation.therapy_name

            # Resolve TherapyMaster for robust matching
            therapy_obj = None
            therapy_code = getattr(allocation, 'therapy_code', None)
            if therapy_code:
                therapy_obj = _ThM.objects.filter(therapy_code=therapy_code).first()
            if not therapy_obj and current_therapy_name:
                therapy_obj = _ThM.objects.filter(therapy_name__iexact=current_therapy_name).first()

            print(f"[CONTINUITY PLAN] ----")
            print(f"[CONTINUITY PLAN] Building for date={target_date}, slot={getattr(slot,'slot_time',None)}(id={getattr(slot,'id',None)}), "
                  f"patient_id={patient_snapshot_id}, patient_name='{patient_name}', therapy='{current_therapy_name}'")

            # SAME-THERAPY continuity (any slot; we will re-use therapists in today's slot)
            same_therapy_date = None
            if current_therapy_name:
                base_same_qs = _TB.objects.filter(
                    patient_id=patient_snapshot_id,
                    status='BOOKED',
                    date__lt=target_date,  # ONLY look at days before the target date
                )
                if therapy_obj:
                    # Match either by therapy FK or by case-insensitive name when therapy FK is null
                    base_same_qs = base_same_qs.filter(
                        Q(therapy=therapy_obj) | Q(therapy__isnull=True, therapy_name__iexact=current_therapy_name)
                    )
                else:
                    base_same_qs = base_same_qs.filter(therapy_name__iexact=current_therapy_name)
                same_therapy_date = base_same_qs.aggregate(Max('date'))['date__max']

            continuity_rows = []

            # FROM START OF THERAPY: Add all therapists who have done this allocation from from_date to today (in order of first appearance).
            # Use distinct priorities (-1000, -999, ...) so order is preserved: first-day therapist always tried first when they return from leave.
            therapy_start_date = getattr(allocation, 'from_date', None)
            if therapy_start_date and slot:
                try:
                    from_start_qs = _TB.objects.filter(
                        visit_id=allocation.id,
                        date__gte=therapy_start_date,
                        date__lt=target_date,
                        time_slot=slot,
                        status='BOOKED',
                    ).select_related('therapist').order_by('date', 'created_at')
                    seen_from_start = set()
                    from_start_index = 0
                    for tb in from_start_qs:
                        if not tb.therapist:
                            continue
                        if not getattr(tb.therapist, 'is_active', True):
                            continue
                        if getattr(tb.therapist, 'is_helping_therapist', False):
                            continue
                        tid = getattr(tb.therapist, 'id', None)
                        if tid is None or tid in seen_from_start:
                            continue
                        seen_from_start.add(tid)
                        continuity_rows.append({
                            "therapist": tb.therapist,
                            "is_bathing": bool(getattr(tb, 'is_bathing', False)),
                            "priority": -1000 + from_start_index,
                            "source_date": tb.date,
                        })
                        from_start_index += 1
                    if seen_from_start:
                        print(f"[CONTINUITY PLAN]   From start of therapy (priority -1000..): {len(seen_from_start)} therapists in order of first appearance")
                except Exception as e:
                    print(f"[CONTINUITY PLAN]   Error building from-start list: {e}")

            def _add_rows_for_date(source_date, base_priority):
                if not source_date:
                    return
                
                # First, check ALL TherapistBooking records for this patient and date (without filters)
                all_tb_for_date = _TB.objects.filter(
                    patient_id=patient_snapshot_id,
                    date=source_date,
                )
                print(f"[CONTINUITY PLAN]   DEBUG: Total TherapistBooking records for patient {patient_snapshot_id} on {source_date}: {all_tb_for_date.count()}")
                if all_tb_for_date.exists():
                    for tb_debug in all_tb_for_date[:5]:  # Show first 5 for debugging
                        print(f"[CONTINUITY PLAN]   DEBUG: TB pk={tb_debug.pk}, status={tb_debug.status}, therapy_name='{tb_debug.therapy_name}', visit_id={tb_debug.visit_id}, therapist_id={tb_debug.therapist_id}")
                
                base_prev_qs = _TB.objects.filter(
                    patient_id=patient_snapshot_id,
                    status='BOOKED',
                    date=source_date,
                )
                print(f"[CONTINUITY PLAN]   DEBUG: After status='BOOKED' filter: {base_prev_qs.count()} records")
                
                # Don't exclude visit=allocation - we want therapists from previous allocations
                # The exclude was preventing us from finding therapists from previous dates
                # base_prev_qs = base_prev_qs.exclude(visit=allocation)
                
                if base_priority in (0, 1) and current_therapy_name:
                    # Same-therapy rows
                    before_filter_count = base_prev_qs.count()
                    if therapy_obj:
                        base_prev_qs = base_prev_qs.filter(
                            Q(therapy=therapy_obj) | Q(therapy__isnull=True, therapy_name__iexact=current_therapy_name)
                        )
                    else:
                        base_prev_qs = base_prev_qs.filter(therapy_name__iexact=current_therapy_name)
                    print(f"[CONTINUITY PLAN]   DEBUG: After therapy filter (before={before_filter_count}, after={base_prev_qs.count()}): therapy_name='{current_therapy_name}', therapy_obj={therapy_obj}")
                print(f"[CONTINUITY PLAN]   Querying TherapistBooking for date {source_date}: found {base_prev_qs.count()} records")
                prev_qs = base_prev_qs.select_related('therapist')
                rows_added = 0
                for tb in prev_qs:
                    if not tb.therapist:
                        print(f"[CONTINUITY PLAN]   Skipping TherapistBooking {tb.pk} - no therapist")
                        continue
                    if not getattr(tb.therapist, 'is_active', True):
                        print(f"[CONTINUITY PLAN]   Skipping TherapistBooking {tb.pk} - therapist {tb.therapist.therapist_code} is INACTIVE")
                        continue
                    if getattr(tb.therapist, 'is_helping_therapist', False):
                        print(f"[CONTINUITY PLAN]   Skipping TherapistBooking {tb.pk} - therapist {tb.therapist.therapist_code} is HELPING THERAPIST")
                        continue
                    # CRITICAL FIX: Only mark as bathing if the TherapistBooking record actually has is_bathing=True
                    # Do NOT use therapist.is_bathing_therapist attribute - that just means they CAN be a bathing therapist,
                    # not that they WERE the bathing therapist on this specific day
                    # Only ONE therapist per visit/date/slot should have is_bathing=True
                    tb_is_bathing = bool(getattr(tb, 'is_bathing', False))
                    therapist_can_bathe = bool(getattr(tb.therapist, 'is_bathing_therapist', False))
                    continuity_rows.append({
                        "therapist": tb.therapist,
                        "is_bathing": tb_is_bathing,  # ONLY use actual is_bathing flag from TherapistBooking
                        "priority": base_priority,
                        "source_date": source_date,
                    })
                    if tb_is_bathing:
                        print(f"[CONTINUITY PLAN]   ✓ Therapist {tb.therapist.therapist_code} marked as bathing (is_bathing=True in TherapistBooking)")
                    elif therapist_can_bathe:
                        print(f"[CONTINUITY PLAN]   ℹ Therapist {tb.therapist.therapist_code} CAN be bathing therapist but was NOT on {source_date} (is_bathing=False)")
                    rows_added += 1
                print(f"[CONTINUITY PLAN]   Added {rows_added} therapists from date {source_date} (priority {base_priority})")

            # Use MOST RECENT date (not just yesterday) - prioritize by recency
            # Always use the most recent date found, whether it's yesterday or older
            if same_therapy_date:
                # Use most recent same-therapy date (whether yesterday or older)
                print(f"[CONTINUITY PLAN]   Same-therapy most recent date: {same_therapy_date}")
                _add_rows_for_date(same_therapy_date, 0)  # Priority 0 for same-therapy regardless of how old
            else:
                print(f"[CONTINUITY PLAN]   No same-therapy history found")

            # If none found, ANY-THERAPY continuity (use most recent date)
            if not continuity_rows:
                any_date = _TB.objects.filter(
                    patient_id=patient_snapshot_id,
                    status='BOOKED',
                    date__lt=target_date,  # ONLY look at days before the target date
                ).aggregate(Max('date'))['date__max']
                if any_date:
                    print(f"[CONTINUITY PLAN]   Any-therapy most recent date: {any_date}")
                    # DEBUG: Check all records first
                    all_any_tb = _TB.objects.filter(
                        patient_id=patient_snapshot_id,
                        date=any_date,
                    )
                    print(f"[CONTINUITY PLAN]   DEBUG: Total TherapistBooking for any-therapy date {any_date}: {all_any_tb.count()}")
                    if all_any_tb.exists():
                        for tb_debug in all_any_tb[:5]:
                            print(f"[CONTINUITY PLAN]   DEBUG: TB pk={tb_debug.pk}, status='{tb_debug.status}', therapy_name='{tb_debug.therapy_name}', visit_id={tb_debug.visit_id}, therapist_id={tb_debug.therapist_id}")
                    
                    prev_any_qs = _TB.objects.filter(
                        patient_id=patient_snapshot_id,
                        status='BOOKED',
                        date=any_date,  # Use most recent date
                    )
                    print(f"[CONTINUITY PLAN]   DEBUG: After status='BOOKED' filter for any-therapy: {prev_any_qs.count()} records")
                    
                    # Don't exclude visit=allocation - we want therapists from previous allocations
                    prev_any_qs = prev_any_qs.exclude(visit_id=allocation.id if allocation and hasattr(allocation, 'id') else None)
                    prev_any_qs = prev_any_qs.select_related('therapist')
                    
                    rows_added_any = 0
                    for tb in prev_any_qs:
                        if not tb.therapist:
                            print(f"[CONTINUITY PLAN]   DEBUG: Skipping TherapistBooking {tb.pk} - no therapist")
                            continue
                        if not getattr(tb.therapist, 'is_active', True):
                            print(f"[CONTINUITY PLAN]   DEBUG: Skipping TherapistBooking {tb.pk} - therapist {tb.therapist.therapist_code} is INACTIVE")
                            continue
                        if getattr(tb.therapist, 'is_helping_therapist', False):
                            print(f"[CONTINUITY PLAN]   DEBUG: Skipping TherapistBooking {tb.pk} - therapist {tb.therapist.therapist_code} is HELPING THERAPIST")
                            continue
                        # CRITICAL FIX: Only mark as bathing if the TherapistBooking record actually has is_bathing=True
                        # Do NOT use therapist.is_bathing_therapist attribute - that just means they CAN be a bathing therapist,
                        # not that they WERE the bathing therapist on this specific day
                        continuity_rows.append({
                            "therapist": tb.therapist,
                            "is_bathing": bool(getattr(tb, 'is_bathing', False)),  # ONLY use actual is_bathing flag from TherapistBooking
                            "priority": 2,
                            "source_date": any_date,
                        })
                        rows_added_any += 1
                    print(f"[CONTINUITY PLAN]   Found {rows_added_any} therapists from any-therapy date {any_date}")
                else:
                    print(f"[CONTINUITY PLAN]   No any-therapy history found")

            if continuity_rows:
                print(f"[CONTINUITY PLAN]   Raw continuity candidates:")
                for r in continuity_rows:
                    t = r["therapist"]
                    t_name = getattr(t, "therapist_name", "")
                    t_code = getattr(t, "therapist_code", "")
                    grade_name = getattr(getattr(t, "therapist_grade", None), "name", "")
                    print(f"    - {t_name} ({t_code}), grade='{grade_name}', "
                          f"is_bathing={r['is_bathing']}, priority={r['priority']}, source_date={r['source_date']}")
            else:
                print(f"[CONTINUITY PLAN]   No continuity candidates found for this patient/therapy/slot")

            # Deduplicate by therapist id and persist
            seen_ids = set()
            for r in sorted(continuity_rows, key=lambda x: (x["priority"], x["therapist"].id)):
                tid = r["therapist"].id
                if tid in seen_ids:
                    continue
                seen_ids.add(tid)
                TherapistContinuityPlan.objects.create(
                    date=target_date,
                    time_slot=slot,
                    patient=patient,
                    allocation=allocation,
                    therapist=r["therapist"],
                    therapy_name=current_therapy_name,
                    is_bathing=r["is_bathing"],
                    priority=r["priority"],
                    source_date=r["source_date"],
                )

            print(f"[CONTINUITY PLAN]   Persisted {len(seen_ids)} unique continuity rows for this booking")
    except Exception as e:
        print(f"[DEBUG ContinuityPlan] Error building continuity plan: {e}")

    # ---------------------------------------
    # Build slot_avoid_map from continuity plan
    # ---------------------------------------
    slot_avoid_map = {}
    try:
        plan_qs = TherapistContinuityPlan.objects.filter(date=target_date).select_related('time_slot', 'therapist')
        for row in plan_qs:
            slot_id = row.time_slot_id
            code = row.therapist.therapist_code
            if slot_id not in slot_avoid_map:
                slot_avoid_map[slot_id] = set()
            slot_avoid_map[slot_id].add(code)
    except Exception as e:
        print(f"[DEBUG ContinuityPlan] Error building slot_avoid_map from plan: {e}")

    # Priority-based sorting: Process patients with same treatment yesterday first for maximum continuity
    # This ensures therapists needed for continuity are assigned before others.
    # 
    # How this handles therapist conflicts:
    # 1. Patients with same therapy yesterday are processed FIRST
    # 2. When continuity therapists are assigned, they're marked as BOOKED in the database
    # 3. Later patients (without continuity needs) won't be able to claim those therapists
    # 4. If two patients both need the same therapist for continuity:
    #    - The one with more recent previous date gets processed first (higher priority)
    #    - First-come-first-served: first patient gets the therapist, second gets a replacement
    # 5. This maximizes continuity slot-wise without requiring multiprocessing or complex conflict resolution
    from Patient.models import TherapistBooking
    from masters.models import TherapyMaster
    from django.db.models import Max, Q
    
    def get_continuity_priority(allocation):
        """
        Returns a tuple (priority_score, most_recent_date) for sorting.
        Lower priority_score = higher priority (processed first).
        Priority 0: Same therapy (any slot) on most recent date
        Priority 2: Any previous therapy (any slot)
        Priority 3: No previous therapy
        """
        patient_id = getattr(allocation.patient, 'id', None)
        current_therapy_name = getattr(allocation, 'therapy_name', None)
        
        if not patient_id or not current_therapy_name:
            return (3, None)  # No continuity possible

        try:
            # Resolve TherapyMaster for robust matching (by code or case-insensitive name)
            therapy_obj = None
            therapy_code = getattr(allocation, 'therapy_code', None)
            if therapy_code:
                therapy_obj = TherapyMaster.objects.filter(therapy_code=therapy_code).first()
            if not therapy_obj and current_therapy_name:
                therapy_obj = TherapyMaster.objects.filter(therapy_name__iexact=current_therapy_name).first()

            base_qs = TherapistBooking.objects.filter(
                patient_id=patient_id,
                status='BOOKED',
                date__lt=target_date,  # ONLY look at days before the target date
            )

            # First check: Same therapy (any slot) on most recent date
            if therapy_obj:
                same_therapy_qs = base_qs.filter(therapy=therapy_obj)
            else:
                same_therapy_qs = base_qs.filter(therapy_name__iexact=current_therapy_name)
            same_therapy_date = same_therapy_qs.aggregate(Max('date'))['date__max']
            if same_therapy_date:
                print(f"[CONTINUITY PRIORITY] Patient {patient_id}, therapy='{current_therapy_name}': most recent SAME-therapy date = {same_therapy_date}")
                return (0, same_therapy_date)  # Priority 0: Same therapy
            else:
                print(f"[CONTINUITY PRIORITY] Patient {patient_id}, therapy='{current_therapy_name}': no previous SAME-therapy bookings found")

            # Second check: Any previous therapy (any slot)
            any_therapy_date = base_qs.aggregate(Max('date'))['date__max']
            if any_therapy_date:
                return (2, any_therapy_date)  # Priority 2: Any previous therapy

            return (3, None)  # Priority 3: No previous therapy

        except Exception as e:
            print(f"[CONTINUITY PRIORITY] Error computing priority for patient {patient_id}, therapy='{current_therapy_name}': {e}")
            return (3, None)  # Error case: treat as no continuity
    
    # Compute priority for each allocation once
    allocation_priorities = []
    for allocation in draft_allocations:
        priority_score, most_recent_date = get_continuity_priority(allocation)
        # Use date ordinal for sorting (more recent = larger ordinal = higher priority)
        # We negate it so that larger dates come first in ascending sort
        date_ordinal = -most_recent_date.toordinal() if most_recent_date else 0
        allocation_priorities.append((allocation, priority_score, date_ordinal))
    
    # Sort by priority score (0 = highest), then by most recent date (larger ordinal = more recent)
    sorted_allocations = [a for a, _, _ in sorted(allocation_priorities, key=lambda x: (x[1], x[2]))]
    
    # Count statistics
    continuity_stats = {
        'same_therapy': sum(1 for _, p, _ in allocation_priorities if p == 0),
        'any_therapy': sum(1 for _, p, _ in allocation_priorities if p == 2),
        'no_continuity': sum(1 for _, p, _ in allocation_priorities if p == 3)
    }
    print(f"[DEBUG Continuity Priority] Processing {len(sorted_allocations)} allocations:")
    print(f"  - Same therapy yesterday: {continuity_stats['same_therapy']}")
    print(f"  - Any previous therapy: {continuity_stats['any_therapy']}")
    print(f"  - No continuity: {continuity_stats['no_continuity']}")
    
    # ============================================================
    # PASS 1: CONTINUITY PRIORITY PASS
    # Assign ONLY previous-day therapists and lock them
    # ============================================================
    print(f"[CONTINUITY PASS1] ========== STARTING PASS 1: CONTINUITY PRIORITY ==========")
    locked_therapist_slots = set()  # Set of (therapist_id, slot_id) tuples
    booking_continuity_map = {}  # Map booking_id -> continuity_assigned dict
    
    # Get all draft bookings for this date
    from Sheduling.models import Booking
    from collections import defaultdict
    all_draft_bookings = Booking.objects.filter(
        date=target_date,
        status='draft'
    ).select_related('allocation', 'timeslot', 'allocation__patient').order_by('allocation_id', 'timeslot_id')
    
    # Group bookings by PATIENT (not allocation) for PASS 1
    # Process one patient and all their treatments, then move to next patient
    patient_bookings_map = defaultdict(list)
    for booking in all_draft_bookings:
        patient_id = getattr(booking.allocation, 'patient', None)
        if patient_id:
            patient_id_val = getattr(patient_id, 'id', None) if hasattr(patient_id, 'id') else patient_id
            patient_bookings_map[patient_id_val].append(booking)
        else:
            # Bookings without patient - process separately
            patient_bookings_map[None].append(booking)
    
    # Sort patients by priority (same as allocations)
    allocation_id_to_priority = {alloc.id: (p, d) for alloc, p, d in allocation_priorities}
    
    # Tie-breaker: earliest "from start" date in continuity plan (priority < 0).
    # Patients whose therapy started earliest get processed first so their first-day therapists (e.g. Latha) are locked for them, not for a patient who had that therapist only on a later date.
    from django.db.models import Min
    try:
        plan_earliest = dict(
            TherapistContinuityPlan.objects.filter(
                date=target_date,
                priority__lt=0
            ).values('patient_id').annotate(earliest=Min('source_date')).values_list('patient_id', 'earliest')
        )
    except Exception:
        plan_earliest = {}
    
    def get_patient_priority(patient_id):
        """Get (priority_score, date_ordinal, earliest_from_start_ordinal) for sorting.
        Patients with earlier 'from start' date get processed first so first-day therapists are assigned to them."""
        if patient_id is None:
            return (3, 0, 999999)
        min_priority = (3, 0)
        for booking in patient_bookings_map[patient_id]:
            alloc_id = booking.allocation_id
            priority = allocation_id_to_priority.get(alloc_id, (3, 0))
            if priority[0] < min_priority[0] or (priority[0] == min_priority[0] and priority[1] > min_priority[1]):
                min_priority = priority
        earliest_sd = plan_earliest.get(patient_id)
        earliest_ord = earliest_sd.toordinal() if earliest_sd else 999999
        return (min_priority[0], min_priority[1], earliest_ord)
    
    # Sort patients by priority, then by earliest from-start date (therapy started first = process first)
    sorted_patient_ids = sorted(
        patient_bookings_map.keys(),
        key=lambda pid: get_patient_priority(pid)
    )
    
    continuity_assigned_count = 0
    partial_assignments = 0  # Count of bookings with partial continuity (K < N)
    
    # PASS 1: Process PATIENT-WISE - one patient and all their treatments, then next patient
    # Assign continuity therapists and lock them, but do NOT complete bookings
    print(f"[CONTINUITY PASS1] Processing {len(sorted_patient_ids)} patients with bookings")
    
    for patient_id in sorted_patient_ids:
        patient_bookings = patient_bookings_map[patient_id]
        patient_name = getattr(patient_bookings[0].allocation.patient, 'pat_name', 'Unknown') if patient_id and patient_bookings else 'Unknown'
        
        print(f"[CONTINUITY PASS1] ===== PATIENT: {patient_name} (id={patient_id}) - Processing {len(patient_bookings)} bookings =====")
        
        # Process all bookings for this patient
        for booking in patient_bookings:
            allocation = booking.allocation
            if not allocation:
                continue
        
            # Skip nurse treatments in PASS 1 (they don't need therapists)
            from Sheduling.nurse_allocation import is_nurse_treatment
            if is_nurse_treatment(allocation.therapy_code, allocation.therapy_name):
                booking_continuity_map[booking.pk] = None  # Mark as no continuity needed
                continue
            
            # Skip therapies with zero therapist requirements in PASS 1 (they don't need therapists)
            # Note: This does NOT include nurse treatments - they are handled above
            therapy_req = therapist_requirements(allocation)
            if therapy_req.get('total', 1) == 0:
                booking_continuity_map[booking.pk] = None  # Mark as no continuity needed
                print(f"[CONTINUITY PASS1] Skipping booking {booking.pk} - zero therapists required (total=0)")
                continue
            
            # Assign continuity therapists for this booking (partial assignment is OK)
            # This will lock therapists but NOT complete the booking
            print(f"[CONTINUITY PASS1] >>> Processing booking {booking.pk} (allocation_id={allocation.id}, patient_id={getattr(allocation.patient, 'id', None)})")
            try:
                continuity_result = assign_continuity_therapists_pass1(
                    booking, allocation, target_date, locked_therapist_slots
                )
                
                if continuity_result['success']:
                    booking_continuity_map[booking.pk] = continuity_result
                    continuity_assigned_count += 1
                    assigned_count = len(continuity_result['assigned_therapists'])
                    remaining_count = continuity_result['remaining_requirements'].get('total', 0)
                    
                    if remaining_count > 0:
                        partial_assignments += 1
                        print(f"[CONTINUITY PASS1] Booking {booking.pk}: Assigned {assigned_count} continuity therapists, {remaining_count} remaining (PARTIAL - will fill in PASS 2)")
                    else:
                        print(f"[CONTINUITY PASS1] Booking {booking.pk}: Assigned {assigned_count} continuity therapists (COMPLETE)")
                else:
                    # No continuity therapists available - will be handled in PASS 2
                    booking_continuity_map[booking.pk] = None
                    print(f"[CONTINUITY PASS1] Booking {booking.pk}: No continuity therapists available (will assign all in PASS 2)")
            except Exception as e:
                print(f"[CONTINUITY PASS1] Error assigning continuity for booking {booking.pk}: {e}")
                import traceback
                traceback.print_exc()
                booking_continuity_map[booking.pk] = None
        
        print(f"[CONTINUITY PASS1] ===== FINISHED PATIENT: {patient_name} (id={patient_id}) =====")
    
    print(f"[CONTINUITY PASS1] ========== PASS 1 COMPLETE ==========")
    total_bookings_processed = sum(len(bookings) for bookings in patient_bookings_map.values())
    print(f"[CONTINUITY PASS1] - Processed {len(sorted_patient_ids)} patients")
    print(f"[CONTINUITY PASS1] - Processed {total_bookings_processed} bookings")
    print(f"[CONTINUITY PASS1] - Assigned continuity for {continuity_assigned_count} bookings")
    print(f"[CONTINUITY PASS1] - Partial assignments (need remaining slots): {partial_assignments}")
    print(f"[CONTINUITY PASS1] - Locked {len(locked_therapist_slots)} therapist-slot pairs")
    print(f"[CONTINUITY PASS1] - Moving to PASS 2 to fill remaining slots and complete bookings")
    
    # ============================================================
    # PASS 2: GENERAL ALLOCATION PASS
    # Fill remaining slots for ALL bookings and complete them
    # ============================================================
    print(f"[CONTINUITY PASS2] ========== STARTING PASS 2: GENERAL ALLOCATION ==========")
    total_bookings_count = sum(len(bookings) for bookings in patient_bookings_map.values())
    print(f"[CONTINUITY PASS2] Processing {len(sorted_allocations)} allocations ({total_bookings_count} bookings)")
    print(f"[CONTINUITY PASS2] - ALL bookings already processed in PASS 1 (continuity therapists locked)")
    print(f"[CONTINUITY PASS2] - Now processing ALL bookings again to fill remaining slots and complete them")
    print(f"[CONTINUITY PASS2] - Continuity therapists are already locked via TherapistBooking records from PASS 1")
    
    # PASS 2: Process ALL allocations (which means ALL bookings)
    # All continuity therapists are already locked from PASS 1
    # For each allocation, expand_therapies_for_visit processes ALL bookings for that allocation
    # This ensures ALL bookings go through PASS 2 to fill remaining slots and complete
    pass2_booking_count = 0
    allocation_count = 0
    for allocation in sorted_allocations:
        allocation_count += 1
        # Get bookings for this allocation to count them
        allocation_bookings = Booking.objects.filter(allocation=allocation, date=target_date, status='draft')
        pass2_booking_count += allocation_bookings.count()
        
        print(f"[CONTINUITY PASS2] Processing allocation {allocation.id} ({allocation_bookings.count()} bookings)")
        
        # Check if this therapy requires zero therapists (total_no_of_therapist = 0)
        # Note: This does NOT include nurse treatments - they go through normal flow to allocate nurses
        from Sheduling.nurse_allocation import is_nurse_treatment
        is_nurse = is_nurse_treatment(allocation.therapy_code, allocation.therapy_name)
        
        # Only auto-schedule if it's NOT a nurse treatment AND has zero therapist requirements
        if not is_nurse:
            therapy_req = therapist_requirements(allocation)
            if therapy_req.get('total', 1) == 0:
                # Mark all bookings for this allocation as scheduled (they don't need algorithm)
                allocation_bookings.update(status='scheduled')
                from Sheduling.models import BookingItem
                BookingItem.objects.filter(booking__allocation=allocation, booking__date=target_date).update(status='scheduled')
                
                successful_count += 1
                results.append({
                    'allocation_id': allocation.id,
                    'patient_name': str(allocation.patient),
                    'therapy_name': allocation.therapy_name,
                    'status': 'success',
                    'booked_tasks': allocation_bookings.count(),
                    'failed_tasks': 0,
                    'auto_scheduled': True  # Flag to indicate auto-scheduled without algorithm
                })
                print(f"[CONTINUITY PASS2] Auto-scheduled {allocation_bookings.count()} bookings for allocation {allocation.id} (zero therapists required, total=0, NOT nurse treatment)")
                continue  # Skip algorithm for this allocation
        
        # Nurse treatments go through normal flow (expand_therapies_for_visit) which will allocate nurses
        
        try:
            # PASS 2: Run the allocation algorithm for this allocation and target date.
            # expand_therapies_for_visit processes ALL bookings for this allocation.
            # It will use continuity_assigned from PASS 1 per booking via booking_continuity_map,
            # fill remaining slots, and complete bookings.
            tasks = expand_therapies_for_visit(
                allocation.id,
                target_date_str,
                create_bookings=True,
                slot_avoid_map=slot_avoid_map,
                booking_continuity_map=booking_continuity_map,  # Pass the continuity map from PASS 1
            )
            
            print(f"[CONTINUITY PASS2] expand_therapies_for_visit returned {len(tasks) if isinstance(tasks, list) else 'error'} for allocation {allocation.id}")
            
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
                                booking.failure_reason = (str(task.get('reason') or ''))[:512]
                                booking.save(update_fields=['status', 'failure_reason', 'updated_at'])
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
            print(f"[CONTINUITY PASS2] ❌ ERROR processing allocation {allocation.id}: {e}")
            import traceback
            traceback.print_exc()
            failed_count += 1
            results.append({
                'allocation_id': allocation.id,
                'patient_name': str(allocation.patient),
                'therapy_name': allocation.therapy_name,
                'status': 'failed',
                'reason': f'Exception: {str(e)}'
            })
    
    print(f"[CONTINUITY PASS2] ========== PASS 2 COMPLETE ==========")
    print(f"[CONTINUITY PASS2] - Processed {allocation_count} allocations")
    print(f"[CONTINUITY PASS2] - Processed {pass2_booking_count} bookings")
    
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