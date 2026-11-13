"""
Central VIP Patient Service.
Handles VIP status resolution, persistence, and consistency checks across:
- Sheduling.models.PatientSnapshot
- Sheduling.models.TherapyAllocation
- Sheduling.models.Booking
- Patient.models.Repeated_Visitors
- authentication.models.PatientProfile
"""
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def normalize_reg_no(patient_identifier: Any) -> str:
    """Normalize various patient objects or IDs into a clean registration string."""
    if not patient_identifier:
        return ""
    if hasattr(patient_identifier, 'pat_reg_no'):
        return str(patient_identifier.pat_reg_no or "").strip()
    if hasattr(patient_identifier, 'patient_reg_no'):
        return str(patient_identifier.patient_reg_no or "").strip()
    if hasattr(patient_identifier, 'patient_id') and patient_identifier.patient_id:
        return str(patient_identifier.patient_id).strip()
    if hasattr(patient_identifier, 'pat_op_reg_no') and patient_identifier.pat_op_reg_no:
        return str(patient_identifier.pat_op_reg_no).strip()
    if hasattr(patient_identifier, 'patient') and patient_identifier.patient:
        return normalize_reg_no(patient_identifier.patient)
    if hasattr(patient_identifier, 'allocation') and patient_identifier.allocation:
        return normalize_reg_no(patient_identifier.allocation)
    if hasattr(patient_identifier, 'visit') and patient_identifier.visit:
        return normalize_reg_no(patient_identifier.visit)
    return str(patient_identifier).strip()


def extract_reg_digits(patient_identifier: Any) -> Optional[int]:
    """Extract integer digits from registration number (for Repeated_Visitors lookup)."""
    reg_str = normalize_reg_no(patient_identifier)
    digits = ''.join(ch for ch in reg_str if ch.isdigit())
    if digits:
        try:
            return int(digits)
        except (ValueError, TypeError):
            return None
    return None


def is_patient_vip(patient_identifier: Any) -> bool:
    """
    Check if a patient is marked as VIP across all applicable models.
    Returns True if ANY source designates the patient as VIP.
    """
    if not patient_identifier:
        return False

    # 1. Direct attribute check on object if already loaded
    if hasattr(patient_identifier, 'is_vip') and getattr(patient_identifier, 'is_vip', False) is True:
        return True

    # 2. If object is a Booking or Allocation
    if hasattr(patient_identifier, 'allocation') and patient_identifier.allocation:
        if getattr(patient_identifier.allocation, 'is_vip', False):
            return True
        if hasattr(patient_identifier.allocation, 'patient') and getattr(patient_identifier.allocation.patient, 'is_vip', False):
            return True
    if hasattr(patient_identifier, 'visit') and patient_identifier.visit:
        if getattr(patient_identifier.visit, 'is_vip', False):
            return True
        if hasattr(patient_identifier.visit, 'patient') and getattr(patient_identifier.visit.patient, 'is_vip', False):
            return True
    if hasattr(patient_identifier, 'patient'):
        pat = getattr(patient_identifier, 'patient', None)
        if pat and getattr(pat, 'is_vip', False):
            return True

    reg_str = normalize_reg_no(patient_identifier)
    if not reg_str:
        return False

    # 3. PatientSnapshot lookup
    try:
        from Sheduling.models import PatientSnapshot
        ps = PatientSnapshot.objects.filter(pat_reg_no=reg_str).first()
        if ps and getattr(ps, 'is_vip', False):
            return True
        reg_digits = extract_reg_digits(reg_str)
        if reg_digits is not None:
            ps_digit = PatientSnapshot.objects.filter(pat_reg_no=str(reg_digits)).first()
            if ps_digit and getattr(ps_digit, 'is_vip', False):
                return True
    except Exception as e:
        logger.debug("Error checking PatientSnapshot is_vip: %s", e)

    # 4. Repeated_Visitors lookup
    reg_digits = extract_reg_digits(reg_str)
    if reg_digits is not None:
        try:
            from Patient.models import Repeated_Visitors
            if Repeated_Visitors.objects.filter(register_number=reg_digits, is_vip=True).exists():
                return True
        except Exception as e:
            logger.debug("Error checking Repeated_Visitors is_vip: %s", e)

    # 5. PatientProfile lookup
    try:
        from authentication.models import PatientProfile
        if PatientProfile.objects.filter(patient_reg_no=reg_str, is_vip=True).exists():
            return True
    except Exception as e:
        logger.debug("Error checking PatientProfile is_vip: %s", e)

    return False


def set_patient_vip_status(patient_identifier: Any, is_vip: bool, patient_name: str = "") -> dict:
    """
    Persist VIP status for a patient across PatientSnapshot, Repeated_Visitors,
    PatientProfile, and all existing TherapyAllocation / Booking records.
    """
    reg_str = normalize_reg_no(patient_identifier)
    if not reg_str:
        return {'success': False, 'error': 'Missing patient registration number'}

    is_vip_bool = bool(is_vip)
    name_clean = (patient_name or "").strip()

    # 1. Update or create PatientSnapshot
    try:
        from Sheduling.models import PatientSnapshot
        ps = PatientSnapshot.objects.filter(pat_reg_no=reg_str).first()
        if ps:
            ps.is_vip = is_vip_bool
            update_fields = ['is_vip', 'updated_at']
            if name_clean and not ps.pat_name:
                ps.pat_name = name_clean
                update_fields.append('pat_name')
            ps.save(update_fields=update_fields)
        else:
            ps = PatientSnapshot.objects.create(
                pat_reg_no=reg_str,
                pat_name=name_clean or f"Patient {reg_str}",
                is_vip=is_vip_bool
            )
    except Exception as e:
        logger.warning("Error saving PatientSnapshot VIP status: %s", e)

    # 2. Update or create Repeated_Visitors
    reg_digits = extract_reg_digits(reg_str)
    if reg_digits is not None:
        try:
            from Patient.models import Repeated_Visitors
            rep = Repeated_Visitors.objects.filter(register_number=reg_digits).first()
            if rep:
                rep.is_vip = is_vip_bool
                update_fields = ['is_vip']
                if name_clean and not rep.patient_name:
                    rep.patient_name = name_clean
                    update_fields.append('patient_name')
                rep.save(update_fields=update_fields)
            else:
                Repeated_Visitors.objects.create(
                    register_number=reg_digits,
                    patient_name=name_clean or f"Patient {reg_str}",
                    total_visits=1,
                    is_vip=is_vip_bool
                )
        except Exception as e:
            logger.warning("Error saving Repeated_Visitors VIP status: %s", e)

    # 3. Update PatientProfile if exists
    try:
        from authentication.models import PatientProfile
        pp = PatientProfile.objects.filter(patient_reg_no=reg_str).first()
        if pp:
            pp.is_vip = is_vip_bool
            pp.save(update_fields=['is_vip'])
    except Exception as e:
        logger.debug("Error saving PatientProfile VIP status: %s", e)

    # 4. Synchronize existing TherapyAllocation and Booking records for this patient
    try:
        from Sheduling.models import TherapyAllocation, Booking
        allocations = TherapyAllocation.objects.filter(patient__pat_reg_no=reg_str)
        allocations.update(is_vip=is_vip_bool)
        Booking.objects.filter(allocation__patient__pat_reg_no=reg_str).update(is_vip=is_vip_bool)
    except Exception as e:
        logger.debug("Error synchronizing Allocation/Booking VIP status: %s", e)

    return {
        'success': True,
        'patient_reg_no': reg_str,
        'is_vip': is_vip_bool,
        'vip_status': 'Yes' if is_vip_bool else 'No'
    }
