"""Patient status, age parsing, and desired therapist gender helpers."""
import re


def is_patient_active(pat_reg_no):
    """
    Check if a patient is active by querying the external Registration table.

    IP patients: Registration.pat_status == 'Y' (from therapy_db).
    OP patients: always treated as active (client requirement).

    Returns True if the patient is active and scheduling should proceed.
    Returns True on any lookup error (fail-open: don't block scheduling if DB is unreachable).
    """
    if not pat_reg_no:
        return True  # fail-open

    pat_reg_no_str = str(pat_reg_no).strip()

    try:
        from MySql_Data_pull.models import Registration
        reg = Registration.objects.using('therapy_db').filter(pat_reg_no=pat_reg_no_str).first()
        if not reg:
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
            return True
    except Exception as e:
        print(f"[PATIENT STATUS] Error checking IP status for {pat_reg_no_str}: {e}")

    return True


def parse_patient_age(age_val):
    """
    Safely parse patient age into a float.
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
