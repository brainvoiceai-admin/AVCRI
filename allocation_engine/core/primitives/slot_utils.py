"""Slot canonicalization and time-extraction primitives."""


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


def _slot_time_value(slot_obj):
    """Return datetime.time for a SlotMaster or legacy TimeSlot object."""
    return getattr(slot_obj, "slot_time", None) or getattr(slot_obj, "start_time", None)
