"""
Preferred Therapist Service for VIP and Repeated Patients.

Business Rules:
1. Doctor Monthly Quota: A doctor can only mark/allow up to 5 patients per calendar month
   to have preferred therapists assigned.
2. Scheduling Team Roster: For allowed patients only, scheduling team can configure
   up to 7 preferred therapists.
3. Bathing Roles: Exactly 1 Primary Bathing Therapist and 1 Secondary Bathing Therapist
   must be designated from within the 7 therapists (Primary != Secondary).
4. Week Off Visibility: Week offs are shown during therapist selection to ensure complementary
   coverage (when Primary is off, Secondary is available).
5. Strict Scheduling Constraint: Once configured, ONLY the therapists from the 7 pool can be
   scheduled for ANY treatment for this patient. Never schedule outside therapists.
6. Treatment Requirements: If treatment requires N therapists (e.g. 5), pick N from the 7.
   Always ensure bathing therapist is accounted for.
7. Bathing Substitution: When Primary Bathing Therapist is not available (on leave/off/booked),
   mark Secondary Bathing Therapist as the bathing therapist.
8. Continuity & Replacement: If yesterday N therapists were scheduled (e.g. 5) and today some are
   available (e.g. 4) while 1 is off, retain the available ones (continuity) and replace the missing
   one(s) strictly from the remaining members of the 7 pool!
"""
from datetime import date
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ValidationError

from masters.models import TherapistMaster, TherapistLeaveMaster, EmergencyLeave
from Patient.models import Repeated_Visitors, TherapistBooking
from .models import DoctorPatientPreferenceAllowance, PatientPreferredTherapistRoster, PatientSnapshot


def normalize_patient_reg_no(patient_id_or_obj):
    """
    Extract a normalized string registration number from a patient object,
    snapshot, or ID string.
    """
    if not patient_id_or_obj:
        return ""
    if hasattr(patient_id_or_obj, 'pat_reg_no'):
        return str(patient_id_or_obj.pat_reg_no).strip()
    if hasattr(patient_id_or_obj, 'patient_reg_no'):
        return str(patient_id_or_obj.patient_reg_no).strip()
    val = str(patient_id_or_obj).strip()
    return val


def is_cottage_room(room_identifier):
    """
    Check if a given room identifier represents a Cottage room.
    Matches:
      - Room code starting with 'CT' (e.g. 'CT-1', 'CT-12', 'CT23')
      - Description containing 'cottage'
      - StayingRoom lookup by number or room_no
    """
    if not room_identifier:
        return False
    room_str = str(room_identifier).strip().upper()
    if not room_str:
        return False

    if room_str.startswith('CT') or 'COTTAGE' in room_str:
        return True

    try:
        from masters.models import StayingRoom
        from django.db.models import Q
        sr = StayingRoom.objects.filter(
            Q(number__iexact=room_str) | Q(room_no__iexact=room_str)
        ).first()
        if sr:
            if (sr.room_no and sr.room_no.upper().startswith('CT')) or \
               (sr.room_desc and 'COTTAGE' in sr.room_desc.upper()):
                return True
    except Exception:
        pass

    return False


def resolve_patient_vip_and_repeated(patient_reg_no, room_no=None):
    """
    Determine whether a patient is VIP, Repeated, and/or Cottage Repeated,
    along with their total visits count.

    Eligibility Rule:
    - VIP Patients: Eligible for preferred therapist marking.
    - Repeated Patients: ONLY Cottage Repeated Patients (staying in a Cottage room CT-*)
      are eligible for preferred therapist marking! Normal/non-cottage repeated patients
      are NOT eligible.
    """
    reg_str = normalize_patient_reg_no(patient_reg_no)
    is_vip = False
    is_repeated = False
    total_visits = 1

    # Extract digits for integer-based register_number in Repeated_Visitors
    digits = ''.join(ch for ch in reg_str if ch.isdigit())
    if digits:
        try:
            reg_int = int(digits)
            rep_rec = Repeated_Visitors.objects.filter(register_number=reg_int).first()
            if rep_rec:
                is_vip = bool(getattr(rep_rec, 'is_vip', False))
                total_visits = getattr(rep_rec, 'total_visits', 1) or 1
                is_repeated = total_visits > 1
        except Exception:
            pass

    # Also check PatientProfile is_vip flag if user profile exists
    if not is_vip:
        try:
            from authentication.models import PatientProfile
            pp = PatientProfile.objects.filter(patient_reg_no=reg_str).first()
            if pp and getattr(pp, 'is_vip', False):
                is_vip = True
        except Exception:
            pass

    # Check cottage room
    effective_room = room_no
    if not effective_room:
        try:
            ps = PatientSnapshot.objects.filter(pat_reg_no=reg_str).first()
            if ps and ps.pat_room_no:
                effective_room = ps.pat_room_no
        except Exception:
            pass

    is_cottage = is_cottage_room(effective_room)
    is_cottage_repeated = bool(is_repeated and is_cottage)
    is_eligible = bool(is_vip or is_cottage_repeated)

    return {
        'is_vip': is_vip,
        'is_repeated': is_repeated,
        'is_cottage': is_cottage,
        'is_cottage_repeated': is_cottage_repeated,
        'is_eligible': is_eligible,
        'total_visits': total_visits,
        'room_no': effective_room or '',
    }


def get_active_preferred_roster(patient_identifier):
    """
    Retrieve active preferred therapist roster for a patient, if configured.
    Returns None if no active roster exists.
    """
    reg_str = normalize_patient_reg_no(patient_identifier)
    if not reg_str:
        return None

    candidate_keys = [reg_str]
    digits = ''.join(ch for ch in reg_str if ch.isdigit())
    if digits and digits not in candidate_keys:
        candidate_keys.append(digits)

    roster = PatientPreferredTherapistRoster.objects.filter(
        patient_reg_no__in=candidate_keys,
        is_active=True
    ).order_by('-updated_at').first()

    if not roster or not roster.therapist_codes:
        return None

    # Verify if linked allowance is active (if allowance exists)
    if roster.allowance and not roster.allowance.is_active:
        return None

    codes_list = [str(c).strip() for c in roster.therapist_codes if str(c).strip()]
    if not codes_list:
        return None

    return {
        'roster': roster,
        'patient_reg_no': roster.patient_reg_no,
        'therapist_codes': codes_list,
        'therapist_codes_set': set(codes_list),
        'primary_bathing_code': (roster.primary_bathing_code or '').strip(),
        'secondary_bathing_code': (roster.secondary_bathing_code or '').strip(),
        'primary_bathing_therapist': roster.primary_bathing_therapist,
        'secondary_bathing_therapist': roster.secondary_bathing_therapist,
    }


def get_therapists_with_schedule_info(gender=None):
    """
    Get all active therapists with their weekly off day(s), grade, gender,
    and bathing qualification.
    Optional gender parameter ('Female' or 'Male') to strictly show therapists with matching gender.
    """
    therapists = TherapistMaster.objects.filter(is_active=True).select_related('therapist_grade').prefetch_related('leaves')
    if gender:
        g = str(gender).strip().lower()
        if g in ['female', 'f']:
            therapists = therapists.filter(therapist_gender__iexact='Female')
        elif g in ['male', 'm']:
            therapists = therapists.filter(therapist_gender__iexact='Male')
    result = []
    for t in therapists:
        leaves = list(t.leaves.filter(is_active=True))
        week_off_names = [l.leave_day_name for l in leaves if l.leave_day_name]
        week_off_ints = [l.leave_day for l in leaves]
        week_off_display = ", ".join(week_off_names) if week_off_names else "None"

        grade_name = t.therapist_grade.name if t.therapist_grade else "Therapist"

        result.append({
            'id': t.id,
            'therapist_code': t.therapist_code,
            'therapist_name': t.therapist_name,
            'gender': t.therapist_gender or 'Male',
            'grade': grade_name,
            'is_bathing_therapist': bool(t.is_bathing_therapist),
            'week_offs': week_off_names,
            'week_off_ints': week_off_ints,
            'week_off_display': week_off_display,
        })
    result.sort(key=lambda x: (x['therapist_name'].lower(), x['therapist_code']))
    return result


def is_therapist_available(therapist_obj_or_code, target_date, slot=None, exclude_booking_id=None):
    """
    Check if a therapist is available on target_date (and slot if specified).
    Takes into account:
      - Weekly off day (TherapistLeaveMaster)
      - Emergency / half-day leave
      - Deputation
      - Already booked at target_date + slot
      - Daily session limits (< 5 normal, max 6)
    """
    if isinstance(therapist_obj_or_code, str):
        therapist = TherapistMaster.objects.filter(therapist_code=therapist_obj_or_code, is_active=True).first()
    else:
        therapist = therapist_obj_or_code

    if not therapist or not getattr(therapist, 'is_active', True):
        return False

    day_of_week = target_date.weekday()
    # Check weekly off
    if TherapistLeaveMaster.objects.filter(therapist=therapist, leave_day=day_of_week, is_active=True).exists():
        return False

    # Check emergency leave / deputation
    try:
        from masters.models import is_therapist_on_emergency_leave, is_therapist_deputed
        if is_therapist_on_emergency_leave(therapist, target_date, slot):
            return False
        if is_therapist_deputed(therapist, target_date):
            return False
    except Exception:
        pass

    # If slot is provided, check booking collision
    if slot:
        qs = TherapistBooking.objects.filter(
            therapist=therapist,
            date=target_date,
            time_slot=slot,
            status='BOOKED'
        )
        if exclude_booking_id:
            qs = qs.exclude(id=exclude_booking_id)
        if qs.exists():
            return False

    # Check daily session limit
    session_count = TherapistBooking.objects.filter(
        therapist=therapist,
        date=target_date,
        status='BOOKED'
    ).count()
    if session_count >= 5:
        return False

    return True


def pick_bathing_therapist_from_roster(roster_info, target_date, slot=None, exclude_booking_id=None):
    """
    Primary bathing therapist rule:
    Always choose Primary Bathing Therapist if available.
    If Primary Bathing Therapist is NOT available (weekly off, leave, booked),
    choose Secondary Bathing Therapist as bathing therapist.
    """
    if not roster_info:
        return None, None

    primary_code = roster_info.get('primary_bathing_code')
    secondary_code = roster_info.get('secondary_bathing_code')

    primary_therapist = None
    if primary_code:
        primary_therapist = TherapistMaster.objects.filter(therapist_code=primary_code, is_active=True).first()

    secondary_therapist = None
    if secondary_code:
        secondary_therapist = TherapistMaster.objects.filter(therapist_code=secondary_code, is_active=True).first()

    # Try Primary Bathing Therapist first
    if primary_therapist and is_therapist_available(primary_therapist, target_date, slot, exclude_booking_id):
        return primary_therapist, 'primary'

    # When Primary is not available, try Secondary Bathing Therapist
    if secondary_therapist and is_therapist_available(secondary_therapist, target_date, slot, exclude_booking_id):
        return secondary_therapist, 'secondary'

    # Fallback to any bathing therapist within the 7 roster who is available
    roster_codes = roster_info.get('therapist_codes', [])
    for code in roster_codes:
        if code in [primary_code, secondary_code]:
            continue
        cand = TherapistMaster.objects.filter(therapist_code=code, is_bathing_therapist=True, is_active=True).first()
        if cand and is_therapist_available(cand, target_date, slot, exclude_booking_id):
            return cand, 'pool_bathing'

    return None, None


def is_real_doctor_user(u):
    """Check if a user is an authentic doctor (role in doctor/doctor_admin or has doctor_profile)."""
    if not u:
        return False
    role = getattr(u, 'role', '')
    if role in ['doctor', 'doctor_admin']:
        return True
    if hasattr(u, 'doctor_profile') and u.doctor_profile is not None:
        return True
    return False


def find_doctor_user_by_code_or_name(doc_code, doc_name):
    """Find a CustomUser doctor matching a doctor code or doctor name."""
    from authentication.models import CustomUser
    from .hospital_doctor_lookup import doctor_code_string_variants
    from django.db.models import Q
    import re

    doc_users_qs = CustomUser.objects.filter(
        Q(role__in=['doctor', 'doctor_admin']) | Q(doctor_profile__isnull=False)
    ).distinct()

    if doc_code:
        code_variants = set(doctor_code_string_variants(str(doc_code).strip()))
        for u in doc_users_qs:
            u_doc_id = str(getattr(getattr(u, 'doctor_profile', None), 'doctor_id', '') or '').strip()
            u_username = str(getattr(u, 'username', '') or '').strip()
            u_variants = set(doctor_code_string_variants(u_doc_id) + doctor_code_string_variants(u_username))
            if code_variants.intersection(u_variants):
                return u

    if doc_name and doc_name != "Not Assigned":
        def _clean(s):
            s = re.sub(r'\b(dr\.?|doctor)\b', '', s, flags=re.IGNORECASE)
            s = re.sub(r'[^a-zA-Z0-9\s]', '', s)
            return set(s.lower().split())

        d_tokens = _clean(doc_name)
        if d_tokens:
            for u in doc_users_qs:
                u_fullname = u.get_full_name() or ''
                u_username = u.username or ''
                u_tokens = _clean(f"{u_fullname} {u_username}")
                if d_tokens and u_tokens:
                    if d_tokens == u_tokens or d_tokens.issubset(u_tokens) or u_tokens.issubset(d_tokens):
                        return u
            for u in doc_users_qs:
                u_fullname = u.get_full_name() or ''
                u_username = u.username or ''
                u_tokens = _clean(f"{u_fullname} {u_username}")
                if d_tokens.intersection(u_tokens):
                    return u

    return None


def resolve_treating_doctor_for_patient(patient_reg_no):
    """
    Resolve treating doctor (doctor_user, doctor_code, doctor_name) for a patient.
    Priority order:
      1. Hospital DB via get_patient_treating_doctor (Registration -> doctcode, Treatment -> Treat_Doc_Code).
      2. Local TherapistPreferenceRequest.treating_doctor_code/name.
      3. Local DoctorPatientPreferenceAllowance.doctor.
      4. Local PrescriptionScheduling.doctor (ONLY if role is doctor).
      5. Local TherapyAllocation.allocated_by (ONLY if role is doctor).

    CRITICAL RULE:
      Scheduling coordinators (Nibin, Arun, vasanthi, etc.) are NOT doctors.
      Never label non-doctors with 'Dr.' and never treat them as treating doctors!
      If no doctor is assigned, returns (None, None, 'Not Assigned').
    """
    patient_id_str = str(patient_reg_no).strip()
    if not patient_id_str:
        return None, None, "Not Assigned"

    # 1. Hospital DB via get_patient_treating_doctor (Top Authority!)
    try:
        from .preference_views import get_patient_treating_doctor
        code, name = get_patient_treating_doctor(patient_id_str)
        if code or name:
            doc_user = find_doctor_user_by_code_or_name(code, name)
            clean_name = name or (f"Dr. {code}" if code else "Not Assigned")
            if not clean_name.lower().startswith('dr') and clean_name != "Not Assigned":
                clean_name = f"Dr. {clean_name}"
            return doc_user, code, clean_name
    except Exception:
        pass

    # 2. Local TherapistPreferenceRequest
    try:
        from .models import TherapistPreferenceRequest
        pr = TherapistPreferenceRequest.objects.filter(
            patient_id=patient_id_str
        ).exclude(treating_doctor_name__isnull=True).exclude(treating_doctor_name='').order_by('-updated_at').first()
        if pr and pr.treating_doctor_name:
            doc_user = find_doctor_user_by_code_or_name(pr.treating_doctor_code, pr.treating_doctor_name)
            name = pr.treating_doctor_name.strip()
            if not name.lower().startswith('dr'):
                name = f"Dr. {name}"
            return doc_user, pr.treating_doctor_code, name
    except Exception:
        pass

    # 3. Local DoctorPatientPreferenceAllowance
    try:
        from .models import DoctorPatientPreferenceAllowance
        al = DoctorPatientPreferenceAllowance.objects.filter(
            patient_reg_no=patient_id_str,
            is_active=True
        ).select_related('doctor', 'doctor__doctor_profile').first()
        if al and al.doctor and is_real_doctor_user(al.doctor):
            name = al.doctor_name or al.doctor.get_full_name() or al.doctor.username
            if not name.lower().startswith('dr'):
                name = f"Dr. {name}"
            return al.doctor, al.doctor_code or al.doctor.username, name
    except Exception:
        pass

    # 4. Local PrescriptionScheduling.doctor (ONLY if real doctor)
    try:
        from .models import PrescriptionScheduling
        from django.db.models import Q
        ps = PrescriptionScheduling.objects.filter(
            Q(patient__pat_reg_no=patient_id_str) | Q(allocation__patient__pat_reg_no=patient_id_str),
            doctor__isnull=False
        ).select_related('doctor', 'doctor__doctor_profile').order_by('-updated_at').first()
        if ps and ps.doctor and is_real_doctor_user(ps.doctor):
            u = ps.doctor
            code = getattr(getattr(u, 'doctor_profile', None), 'doctor_id', None) or u.username
            name = u.get_full_name() or u.username
            if not name.lower().startswith('dr'):
                name = f"Dr. {name}"
            return u, code, name
    except Exception:
        pass

    # 5. Local TherapyAllocation.allocated_by (STRICTLY ONLY if allocated_by is a verified doctor!)
    try:
        from .models import TherapyAllocation
        from django.db.models import Q
        q = Q(patient__pat_reg_no=patient_id_str)
        if patient_id_str.isdigit():
            q |= Q(patient__id=int(patient_id_str))
        alloc = TherapyAllocation.objects.filter(
            q,
            allocated_by__isnull=False
        ).select_related('allocated_by', 'allocated_by__doctor_profile').order_by('-updated_at').first()
        if alloc and alloc.allocated_by and is_real_doctor_user(alloc.allocated_by):
            u = alloc.allocated_by
            code = getattr(getattr(u, 'doctor_profile', None), 'doctor_id', None) or u.username
            name = u.get_full_name() or u.username
            if not name.lower().startswith('dr'):
                name = f"Dr. {name}"
            return u, code, name
    except Exception:
        pass

    return None, None, "Not Assigned"


def is_user_patient_treating_doctor(user, patient_reg_no):
    """
    Check if the given user is the assigned Treating Doctor for this patient.
    Rule: Only the particular treating doctor can give access to allow preferred therapist.

    CRITICAL RULE:
      Scheduling staff, receptionists, nurses, etc. can NEVER be the treating doctor.
      Must return False immediately for any non-doctor.
    """
    if not user or not user.is_authenticated:
        return False

    # 1. Strictly verify the user is a doctor
    if not is_real_doctor_user(user):
        return False

    patient_id_str = str(patient_reg_no).strip()
    if not patient_id_str:
        return False

    # 2. Check resolved doctor for this patient
    doc_user, doc_code, doc_name = resolve_treating_doctor_for_patient(patient_id_str)
    if doc_user and doc_user.id == user.id:
        return True

    user_doc_id = str(getattr(getattr(user, 'doctor_profile', None), 'doctor_id', '') or '').strip()
    user_username = str(getattr(user, 'username', '') or '').strip()
    user_fullname = (user.get_full_name() or '').strip()

    from .hospital_doctor_lookup import doctor_code_string_variants

    # Compare doc_code
    if doc_code:
        dc_str = str(doc_code).strip()
        doc_code_variants = set(doctor_code_string_variants(dc_str))
        user_code_variants = set(doctor_code_string_variants(user_doc_id) + doctor_code_string_variants(user_username))
        if doc_code_variants.intersection(user_code_variants):
            return True

    # Compare doc_name
    if doc_name and doc_name != "Not Assigned":
        import re
        def _clean(s):
            s = re.sub(r'\b(dr\.?|doctor)\b', '', s, flags=re.IGNORECASE)
            s = re.sub(r'[^a-zA-Z0-9\s]', '', s)
            return set(s.lower().split())
        d_tokens = _clean(doc_name)
        u_tokens = _clean(f"{user_fullname} {user_username}")
        if d_tokens and u_tokens and (d_tokens.issubset(u_tokens) or u_tokens.issubset(d_tokens) or d_tokens.intersection(u_tokens)):
            return True

    # 3. Check hospital DB doctor patients lookup
    try:
        from .hospital_doctor_lookup import get_doctor_codes_for_user, pat_reg_nos_for_hospital_doctor
        doc_codes = get_doctor_codes_for_user(user)
        for dc in doc_codes:
            try:
                doc_patients = set(pat_reg_nos_for_hospital_doctor(dc))
                if patient_id_str in doc_patients:
                    return True
            except Exception:
                pass
    except Exception:
        pass

    # 4. Check existing DoctorPatientPreferenceAllowance granted by this doctor
    try:
        from .models import DoctorPatientPreferenceAllowance
        if DoctorPatientPreferenceAllowance.objects.filter(
            patient_reg_no=patient_id_str,
            doctor=user,
            is_active=True
        ).exists():
            return True
    except Exception:
        pass

    # 5. Check PrescriptionScheduling where doctor=user
    try:
        from .models import PrescriptionScheduling
        from django.db.models import Q
        if PrescriptionScheduling.objects.filter(
            Q(patient__pat_reg_no=patient_id_str) | Q(allocation__patient__pat_reg_no=patient_id_str),
            doctor=user
        ).exists():
            return True
    except Exception:
        pass

    # 6. Direct allocation check in TherapyAllocation (valid only because user is verified doctor)
    try:
        from .models import TherapyAllocation
        from django.db.models import Q
        q = Q(patient__pat_reg_no=patient_id_str)
        if patient_id_str.isdigit():
            q |= Q(patient__id=int(patient_id_str))
        if TherapyAllocation.objects.filter(q, allocated_by=user).exists():
            return True
    except Exception:
        pass

    # 7. Check preference_views.is_user_treating_doctor
    try:
        from .preference_views import is_user_treating_doctor
        if is_user_treating_doctor(user, patient_id_str):
            return True
    except Exception:
        pass

    return False


def toggle_doctor_patient_allowance(doctor_user, patient_reg_no, patient_name='', notes='', room_no=None):
    """
    Toggle preferred therapist allowance for a patient by the doctor.
    Enforces:
      1. Treating Doctor: Only the particular treating doctor can give access to allow preferred therapist!
      2. Eligibility: Only VIP patients and Cottage Repeated patients are eligible!
      3. Monthly quota: At most 5 patients per doctor per calendar month!
    """
    now = timezone.now()
    year = now.year
    month = now.month
    reg_str = str(patient_reg_no).strip()

    with transaction.atomic():
        # Check existing allowance
        allowance = DoctorPatientPreferenceAllowance.objects.filter(
            doctor=doctor_user,
            patient_reg_no=reg_str,
            year=year,
            month=month
        ).first()

        if allowance and allowance.is_active:
            # Revoke/Deactivate allowance (allowed if this user granted it or is treating doctor)
            allowance.is_active = False
            allowance.save()

            # Deactivate any linked roster
            PatientPreferredTherapistRoster.objects.filter(patient_reg_no=reg_str).update(is_active=False)

            quota = DoctorPatientPreferenceAllowance.get_monthly_quota(doctor_user, year, month)
            return {
                'status': 'revoked',
                'is_allowed': False,
                'message': f'Allowance revoked for patient {reg_str}.',
                'quota': quota
            }

        # 1. ENFORCE: Only the particular treating doctor can give access!
        if not is_user_patient_treating_doctor(doctor_user, reg_str):
            _, treating_code, treating_name = resolve_treating_doctor_for_patient(reg_str)
            doc_label = treating_name or (f"Dr. {treating_code}" if treating_code else "the assigned treating doctor")
            quota = DoctorPatientPreferenceAllowance.get_monthly_quota(doctor_user, year, month)
            return {
                'status': 'not_treating_doctor',
                'error': f'Only the particular treating doctor ({doc_label}) can give access to allow preferred therapist for this patient.',
                'quota': quota
            }

        # 2. Check eligibility before activating
        info = resolve_patient_vip_and_repeated(reg_str, room_no=room_no)
        if not info['is_eligible']:
            quota = DoctorPatientPreferenceAllowance.get_monthly_quota(doctor_user, year, month)
            return {
                'status': 'ineligible',
                'error': 'Only VIP patients and Cottage Repeated patients are eligible for preferred therapist assignment.',
                'quota': quota
            }

        # 3. Otherwise, activating allowance. First verify quota!
        used_count = DoctorPatientPreferenceAllowance.objects.filter(
            doctor=doctor_user,
            year=year,
            month=month,
            is_active=True
        ).count()

        if used_count >= 5:
            quota = DoctorPatientPreferenceAllowance.get_monthly_quota(doctor_user, year, month)
            return {
                'status': 'quota_exceeded',
                'error': f'Monthly quota limit of 5 patients reached for {now.strftime("%B %Y")}. You cannot mark more than 5 patients.',
                'quota': quota
            }

        doc_code = ''
        if hasattr(doctor_user, 'doctor_profile') and doctor_user.doctor_profile:
            doc_code = doctor_user.doctor_profile.doctor_id or ''
        doc_name = doctor_user.get_full_name() or doctor_user.username
        if not doc_name.lower().startswith('dr'):
            doc_name = f"Dr. {doc_name}"

        if not patient_name:
            ps = PatientSnapshot.objects.filter(pat_reg_no=reg_str).first()
            if ps:
                patient_name = ps.pat_name or ''

        if allowance:
            allowance.is_active = True
            allowance.patient_name = patient_name or allowance.patient_name
            allowance.notes = notes or allowance.notes
            allowance.save()
        else:
            allowance = DoctorPatientPreferenceAllowance.objects.create(
                doctor=doctor_user,
                doctor_code=doc_code,
                doctor_name=doc_name,
                patient_reg_no=reg_str,
                patient_name=patient_name or f"Patient {reg_str}",
                year=year,
                month=month,
                is_active=True,
                notes=notes
            )

        # Reactivate roster if one existed previously
        PatientPreferredTherapistRoster.objects.filter(patient_reg_no=reg_str).update(is_active=True, allowance=allowance)

        quota = DoctorPatientPreferenceAllowance.get_monthly_quota(doctor_user, year, month)
        return {
            'status': 'allowed',
            'is_allowed': True,
            'message': f'Patient {reg_str} is now allowed for preferred therapist assignment.',
            'quota': quota
        }


def save_preferred_therapist_roster(patient_reg_no, therapist_codes, primary_bathing_code, secondary_bathing_code, configured_by=None, notes=''):
    """
    Save or update the preferred therapist roster (up to 7 therapists) for an allowed patient.
    Validations:
      - Patient must be marked as allowed by doctor in an active allowance.
      - Total therapist codes must be between 1 and 7.
      - Primary bathing code must be in the selected 7 codes.
      - Secondary bathing code must be in the selected 7 codes.
      - Primary bathing therapist != Secondary bathing therapist.
    """
    reg_str = str(patient_reg_no).strip()
    if not reg_str:
        raise ValidationError("Patient registration number is required.")

    # 1. Verify patient is allowed
    allowance = DoctorPatientPreferenceAllowance.objects.filter(
        patient_reg_no=reg_str,
        is_active=True
    ).order_by('-year', '-month', '-created_at').first()

    if not allowance:
        # Fallback check by digits
        digits = ''.join(ch for ch in reg_str if ch.isdigit())
        if digits:
            allowance = DoctorPatientPreferenceAllowance.objects.filter(
                patient_reg_no=digits,
                is_active=True
            ).order_by('-year', '-month', '-created_at').first()

    if not allowance:
        raise ValidationError("Patient has not been allowed for preferred therapist assignment by their doctor.")

    # 2. Clean therapist codes
    clean_codes = []
    for c in therapist_codes or []:
        code_str = str(c).strip()
        if code_str and code_str not in clean_codes:
            clean_codes.append(code_str)

    if not clean_codes:
        raise ValidationError("At least 1 preferred therapist must be selected.")
    if len(clean_codes) > 7:
        raise ValidationError(f"A maximum of 7 preferred therapists can be marked (selected: {len(clean_codes)}).")

    # 3. Validate bathing therapists
    p_code = str(primary_bathing_code).strip() if primary_bathing_code else ''
    s_code = str(secondary_bathing_code).strip() if secondary_bathing_code else ''

    if not p_code:
        raise ValidationError("Primary Bathing Therapist is required.")
    if not s_code:
        raise ValidationError("Secondary Bathing Therapist is required.")

    if p_code not in clean_codes:
        raise ValidationError(f"Primary Bathing Therapist ({p_code}) must be one of the selected therapists.")
    if s_code not in clean_codes:
        raise ValidationError(f"Secondary Bathing Therapist ({s_code}) must be one of the selected therapists.")
    if p_code == s_code:
        raise ValidationError("Primary and Secondary Bathing Therapists cannot be the same therapist.")

    # Resolve therapist objects
    therapist_objs = list(TherapistMaster.objects.filter(therapist_code__in=clean_codes, is_active=True))
    p_obj = next((t for t in therapist_objs if t.therapist_code == p_code), None)
    s_obj = next((t for t in therapist_objs if t.therapist_code == s_code), None)

    # Validate therapist gender matches patient gender
    patient_sex = None
    patient_age = None
    ps = PatientSnapshot.objects.filter(pat_reg_no=reg_str).first()
    if ps:
        patient_sex = ps.pat_sex
        patient_age = ps.pat_age
    if not patient_sex:
        try:
            from MySql_Data_pull.models import Registration
            d = ''.join(ch for ch in reg_str if ch.isdigit())
            if d:
                h_r = Registration.objects.using('therapy_db').filter(pat_reg_no=int(d)).values('pat_sex', 'pat_age').first()
                if h_r:
                    patient_sex = h_r.get('pat_sex')
                    patient_age = h_r.get('pat_age')
        except Exception:
            pass

    if patient_sex:
        from final_allocation import resolve_desired_gender
        desired_gender = resolve_desired_gender(patient_sex, patient_age)
        for t_obj in therapist_objs:
            t_g = str(t_obj.therapist_gender or '').strip().lower()
            if t_g and t_g != desired_gender:
                raise ValidationError(
                    f"Therapist {t_obj.therapist_name} ({t_obj.therapist_code}) is {t_obj.therapist_gender}, but patient is {patient_sex}. Only {desired_gender.capitalize()} therapists can be selected for this patient."
                )

    patient_name = allowance.patient_name
    if not patient_name:
        ps = PatientSnapshot.objects.filter(pat_reg_no=reg_str).first()
        if ps:
            patient_name = ps.pat_name or ''

    with transaction.atomic():
        roster, _ = PatientPreferredTherapistRoster.objects.update_or_create(
            patient_reg_no=reg_str,
            defaults={
                'patient_name': patient_name or f"Patient {reg_str}",
                'allowance': allowance,
                'therapist_codes': clean_codes,
                'primary_bathing_therapist': p_obj,
                'primary_bathing_code': p_code,
                'secondary_bathing_therapist': s_obj,
                'secondary_bathing_code': s_code,
                'is_active': True,
                'configured_by': configured_by,
                'notes': notes or ''
            }
        )
        if therapist_objs:
            roster.therapists.set(therapist_objs)

    return roster
