"""Steam therapy identification and dedicated room rules."""


def is_steam_therapy_treatment(therapy_name=None, therapy_code=None):
    """
    True when therapy is marked as Steam Therapy in TherapyMaster (is_steam_therapy=True).
    Such therapy is strictly allocated to designated steam rooms (e.g. TR-12, TR-9).
    """
    try:
        from masters.models import TherapyMaster

        tm = None
        if therapy_code:
            tm = TherapyMaster.objects.filter(therapy_code=str(therapy_code).strip()).first()
        if not tm and therapy_name:
            tm = TherapyMaster.objects.filter(therapy_name__iexact=str(therapy_name).strip()).first()
        if tm and getattr(tm, 'is_steam_therapy', False):
            return True
        return False
    except Exception:
        return False


# Backward compatibility alias
is_steam_therapy_530_tr12_only = is_steam_therapy_treatment


def get_steam_therapy_rooms():
    """
    Returns an ordered list of room numbers (str) designated as steam therapy rooms.
    Dynamically fetched from TreatmentRoom where is_steam_room=True and is_active=True.
    Falls back to ['TR-12', 'TR-9'] if none are configured.
    Ensures TR-12 and TR-9 are prioritized first if present.
    """
    try:
        from Patient.models import TreatmentRoom
        rooms = list(
            TreatmentRoom.objects.filter(is_steam_room=True, is_active=True)
            .values_list('room_no', flat=True)
        )
        if rooms:
            def steam_priority(r):
                if r == 'TR-12':
                    return (0, r)
                if r == 'TR-9':
                    return (1, r)
                return (2, r)
            rooms.sort(key=steam_priority)
            return rooms
    except Exception as e:
        print(f"[STEAM ROOM] Error querying dynamic steam rooms: {e}")
    return ['TR-12', 'TR-9']
