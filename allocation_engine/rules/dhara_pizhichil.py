"""Dhara & Pizhichil identification (TherapyMaster flag only) and strict room continuity."""
from allocation_engine.core.primitives.therapy_catalog import get_therapy_details


def is_dhara_pizhichil_treatment(therapy_name=None, therapy_code=None):
    """
    Check if a therapy is marked as Dhara & Pizhichil in TherapyMaster (is_dhara_pizhichil=True).
    Strictly relies on the TherapyMaster flag (no hardcoded name-string fallback).
    """
    try:
        from masters.models import TherapyMaster
        tm = None
        if therapy_code:
            tm = TherapyMaster.objects.filter(therapy_code=str(therapy_code).strip()).first()
        if not tm and therapy_name:
            tm = TherapyMaster.objects.filter(therapy_name__iexact=str(therapy_name).strip()).first()
        if not tm and therapy_name:
            tm = get_therapy_details(therapy_name)
        if tm:
            return bool(getattr(tm, 'is_dhara_pizhichil', False))
    except Exception:
        pass
    return False


def get_dhara_pizhichil_assigned_room(patient_id=None, patient=None, allocation=None):
    """
    Find the room originally assigned to a Dhara Pizhichil patient at the
    beginning of treatment, ensuring strict room continuity until discharge
    (even across temporary cancellations and resumptions).
    """
    from Patient.models import RoomBooking
    from Sheduling.models import TherapyAllocation, Booking

    pid = patient_id or (getattr(patient, 'id', None) if patient else None)
    pat_reg_no = getattr(patient, 'pat_reg_no', None) if patient else None

    # 1. If allocation directly has an assigned active room
    if allocation and getattr(allocation, 'room', None) and getattr(allocation.room, 'is_active', False):
        return allocation.room

    # 2. Check TherapyAllocation room for Dhara Pizhichil for this patient
    if pid:
        alloc_qs = TherapyAllocation.objects.filter(
            patient_id=pid,
            room__isnull=False,
            room__is_active=True,
        ).order_by('from_date', 'id').select_related('room')
        for a in alloc_qs:
            if is_dhara_pizhichil_treatment(therapy_name=a.therapy_name, therapy_code=a.therapy_code):
                return a.room

    # 3. Check earliest RoomBooking for this patient (including CANCELED, so room is remembered across cancellations)
    rb_qs = RoomBooking.objects.filter(room__isnull=False, room__is_active=True)
    if pid:
        rb_qs = rb_qs.filter(patient_id=pid)
    elif pat_reg_no:
        rb_qs = rb_qs.filter(patient_id=pat_reg_no)
    else:
        rb_qs = None

    if rb_qs is not None:
        for rb in rb_qs.order_by('date', 'id').select_related('room'):
            if is_dhara_pizhichil_treatment(therapy_name=rb.therapy_name):
                return rb.room

    # 4. Check earliest Booking record for this patient
    if pid:
        bk_qs = Booking.objects.filter(
            allocation__patient_id=pid,
            room__isnull=False,
            room__is_active=True,
        ).order_by('date', 'id').select_related('room', 'allocation')
        for bk in bk_qs:
            th_name = bk.snapshot_therapy_name or (bk.allocation.therapy_name if bk.allocation else None)
            th_code = bk.allocation.therapy_code if bk.allocation else None
            if is_dhara_pizhichil_treatment(therapy_name=th_name, therapy_code=th_code):
                return bk.room

    return None
