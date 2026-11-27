"""Vamanam therapy identification, dynamic slots/timings, and tiered room allocation rules."""

VAMANAM_THERAPY_CODE = 'THEB126'


def is_vamanam_treatment(therapy_name=None, therapy_code=None):
    """
    True when therapy is Vamanam treatment (recognized by therapy_code THEB126,
    or TherapyMaster lookup, or name containing 'vamanam').
    """
    try:
        if therapy_code and str(therapy_code).strip().upper() == VAMANAM_THERAPY_CODE:
            return True
        from masters.models import TherapyMaster
        tm = None
        if therapy_code:
            tm = TherapyMaster.objects.filter(therapy_code=str(therapy_code).strip()).first()
        if not tm and therapy_name:
            tm = TherapyMaster.objects.filter(therapy_name__iexact=str(therapy_name).strip()).first()
        if tm:
            if getattr(tm, 'therapy_code', None) == VAMANAM_THERAPY_CODE:
                return True
            if getattr(tm, 'is_vamanam', False):
                return True
        if therapy_name and 'vamanam' in str(therapy_name).strip().lower():
            return True
    except Exception as e:
        print(f"[VAMANAM CHECK] Error: {e}")
    return False


def get_vamanam_slots():
    """
    Returns ordered list of slot time strings "HH:MM" designated as Vamanam slots.
    Dynamically fetched from SlotMaster where is_vamanam_slot=True and is_active=True.
    Falls back to ['06:30'] if none are configured.
    """
    try:
        from masters.models import SlotMaster
        slots = list(
            SlotMaster.objects.filter(is_vamanam_slot=True, is_active=True)
            .order_by('slot_time')
            .values_list('slot_time', flat=True)
        )
        if slots:
            slot_strs = []
            for st in slots:
                if hasattr(st, 'strftime'):
                    slot_strs.append(st.strftime('%H:%M'))
                else:
                    slot_strs.append(str(st)[:5])
            return slot_strs
    except Exception as e:
        print(f"[VAMANAM SLOTS] Error querying Vamanam slots: {e}")
    return ['06:30']


def get_vamanam_timings():
    """
    Returns ordered list of active Vamanam timing strings, e.g. ['05:00 AM', '05:30 AM'].
    Dynamically fetched from VamanamTimingMaster ordered by display_order.
    """
    try:
        from masters.models import VamanamTimingMaster
        timings = list(
            VamanamTimingMaster.objects.filter(is_active=True)
            .order_by('display_order', 'timing_time')
        )
        if timings:
            result = []
            for t in timings:
                if t.timing_name:
                    result.append(t.timing_name.strip())
                elif t.timing_time:
                    result.append(t.timing_time.strftime('%I:%M %p'))
            return result
    except Exception as e:
        print(f"[VAMANAM TIMINGS] Error querying Vamanam timings: {e}")
    return ['05:00 AM', '05:30 AM']


def get_vamanam_rooms_by_tier():
    """
    Returns tuple of (primary_rooms, secondary_rooms) room numbers (str).
    Primary Vamanam rooms: TR-11, TR-12 (vamanam_room_type='primary').
    Secondary Vamanam room: TR-9 (vamanam_room_type='secondary').
    """
    try:
        from Patient.models import TreatmentRoom
        primary = list(
            TreatmentRoom.objects.filter(is_vamanam_room=True, vamanam_room_type='primary', is_active=True)
            .order_by('room_no')
            .values_list('room_no', flat=True)
        )
        secondary = list(
            TreatmentRoom.objects.filter(is_vamanam_room=True, vamanam_room_type='secondary', is_active=True)
            .order_by('room_no')
            .values_list('room_no', flat=True)
        )
        untyped = list(
            TreatmentRoom.objects.filter(is_vamanam_room=True, is_active=True)
            .exclude(vamanam_room_type__in=['primary', 'secondary'])
            .order_by('room_no')
            .values_list('room_no', flat=True)
        )
        primary.extend(untyped)
        if not primary and not secondary:
            return ['TR-11', 'TR-12'], ['TR-9']
        return primary, secondary
    except Exception as e:
        print(f"[VAMANAM ROOMS BY TIER] Error: {e}")
        return ['TR-11', 'TR-12'], ['TR-9']


def get_vamanam_treatment_rooms():
    """
    Returns an ordered list of all Vamanam treatment room numbers.
    Primary rooms come first, followed by Secondary rooms.
    """
    p, s = get_vamanam_rooms_by_tier()
    return p + s


def get_primary_vamanam_treatment_rooms():
    p, _ = get_vamanam_rooms_by_tier()
    return p


def get_secondary_vamanam_treatment_rooms():
    _, s = get_vamanam_rooms_by_tier()
    return s


def allocate_vamanam_treatment_room(date, time_slot, check_room_availability_func=None, booking_id=None):
    """
    Dedicated room allocation function for Vamanam treatments.
    1. First considers available Primary Vamanam rooms (e.g. TR-11 & TR-12).
    2. Considers Secondary rooms (e.g. TR-9) only when no Primary room is available.
    3. Returns TreatmentRoom instance or None if no room is available.
    """
    from Patient.models import TreatmentRoom, RoomBooking

    def _default_check(room_no):
        try:
            room = TreatmentRoom.objects.get(room_no=room_no)
            if not room.is_active:
                return None

            filter_kwargs = {
                'room': room,
                'date': date,
                'status': "BOOKED",
            }
            if time_slot is not None:
                if isinstance(time_slot, str):
                    from masters.models import SlotMaster
                    from datetime import datetime as dt_cls
                    try:
                        slot_t = dt_cls.strptime(time_slot, "%H:%M").time()
                        s_obj = SlotMaster.objects.filter(slot_time=slot_t).first()
                    except Exception:
                        s_obj = SlotMaster.objects.filter(slot_name__icontains=time_slot).first()
                    if s_obj:
                        filter_kwargs['time_slot'] = s_obj
                else:
                    filter_kwargs['time_slot'] = time_slot

            rb_qs = RoomBooking.objects.filter(**filter_kwargs)
            if booking_id:
                rb_qs = rb_qs.exclude(visit_id=booking_id)
            if not rb_qs.exists():
                return room
        except TreatmentRoom.DoesNotExist:
            pass
        return None

    check_func = check_room_availability_func or _default_check
    primary_rooms, secondary_rooms = get_vamanam_rooms_by_tier()

    for r_no in primary_rooms:
        r_obj = check_func(r_no)
        if r_obj:
            print(f"[VAMANAM ROOM ALLOCATION] Assigned Primary Vamanam room: {r_no}")
            return r_obj

    for r_no in secondary_rooms:
        r_obj = check_func(r_no)
        if r_obj:
            print(f"[VAMANAM ROOM ALLOCATION] Primary rooms busy, assigned Secondary Vamanam room: {r_no}")
            return r_obj

    print(f"[VAMANAM ROOM ALLOCATION] All Primary ({primary_rooms}) and Secondary ({secondary_rooms}) Vamanam rooms are unavailable on {date} at {time_slot}.")
    return None
