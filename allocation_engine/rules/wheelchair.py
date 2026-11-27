"""Wheelchair accessibility room lookup rules."""


def get_wheelchair_accessible_rooms():
    """
    Returns list of active wheelchair accessible treatment room numbers.
    Dynamically fetched from TreatmentRoom where is_wheelchair_accessible=True.
    """
    try:
        from Patient.models import TreatmentRoom
        return list(
            TreatmentRoom.objects.filter(is_active=True, is_wheelchair_accessible=True)
            .order_by('room_no')
            .values_list('room_no', flat=True)
        )
    except Exception as e:
        print(f"[WHEELCHAIR ROOMS] Error querying wheelchair accessible rooms: {e}")
        return []
