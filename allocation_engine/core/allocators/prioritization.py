"""
Patient category prioritization for allocation ordering (Layer 1B).

Priority tiers:
  0 = Wheelchair patients (highest - requires scarce accessible rooms)
  1 = Dhara Pizhichil patients (second - requires strict room continuity)
  2 = Normal treatment patients (flexible room allocation)
"""

from allocation_engine.rules.dhara_pizhichil import is_dhara_pizhichil_treatment


def get_patient_category_priority(patient, allocation=None, bookings=None):
    """
    Returns priority tier:
      0 = Wheelchair patients (Highest - requires scarce accessible rooms)
      1 = Dhara Pizhichil patients (Second - requires room continuity)
      2 = Normal treatment patients (Flexible room allocation)
    """
    is_wc = False
    if patient and getattr(patient, 'is_wheelchair', False):
        is_wc = True
    elif allocation and getattr(allocation, 'is_wheelchair', False):
        is_wc = True
    elif bookings:
        is_wc = any(
            getattr(b, 'is_wheelchair', False)
            or (b.allocation and getattr(b.allocation, 'is_wheelchair', False))
            for b in bookings
        )
    if is_wc:
        return 0

    is_dp = False
    if allocation and is_dhara_pizhichil_treatment(
        therapy_name=getattr(allocation, 'therapy_name', None),
        therapy_code=getattr(allocation, 'therapy_code', None),
    ):
        is_dp = True
    elif bookings:
        for b in bookings:
            th_name = getattr(b, 'snapshot_therapy_name', None) or (
                b.allocation.therapy_name if b.allocation else None
            )
            th_code = b.allocation.therapy_code if b.allocation else None
            if is_dhara_pizhichil_treatment(therapy_name=th_name, therapy_code=th_code):
                is_dp = True
                break
    if is_dp:
        return 1

    return 2
