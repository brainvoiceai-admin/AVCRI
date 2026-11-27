"""Vasthi therapy identification, slot rules, and cottage-preferred room allocation."""
import re
from allocation_engine.core.primitives.room_utils import get_treatment_rooms_for_staying_room

# Mathra Vasthi (THEB037) is exempt from the Vasthi therapy-group 08:30-only rule.
GROUP_VASTHI_MATHRA_THERAPY_CODE = "THEB037"
# masters.TherapyGroup.name (normalized) for therapies that may use only the 08:30 slot
VASTHI_THERAPY_GROUP_NAME_NORMALIZED = "vasthi"


def is_vasthi_treatment(therapy_name=None, therapy_code=None):
    """
    True when therapy is marked as Vasthi Therapy in TherapyMaster (is_vasthi=True)
    or belongs to the Vasthi therapy group in masters (except Mathra Vasthi THEB037).
    """
    code = (therapy_code or "").strip().upper()
    if code == GROUP_VASTHI_MATHRA_THERAPY_CODE:
        return False
    try:
        from masters.models import TherapyMaster

        tm = None
        if therapy_code:
            tm = (
                TherapyMaster.objects.filter(therapy_code=str(therapy_code).strip())
                .select_related("therapy_group")
                .first()
            )
        if not tm and therapy_name:
            tm = (
                TherapyMaster.objects.filter(therapy_name__iexact=str(therapy_name).strip())
                .select_related("therapy_group")
                .first()
            )
        if tm:
            if getattr(tm, "is_vasthi", False):
                return True
            if getattr(tm, "therapy_group_id", None) and tm.therapy_group:
                gname = (tm.therapy_group.name or "").strip().lower()
                if gname == VASTHI_THERAPY_GROUP_NAME_NORMALIZED:
                    return True
    except Exception:
        pass

    t_str = str(therapy_name or "").strip().lower()
    if "vasthi" in t_str and "mathra" not in t_str:
        return True
    return False


def is_group_vasthi_0830_only(therapy_name, therapy_code=None):
    """Backward-compatible alias: True when therapy is a Vasthi treatment restricted to 08:30 slot."""
    return is_vasthi_treatment(therapy_name, therapy_code)


def get_vasthi_slots():
    """
    Return list of slot times (HH:MM strings) designated for Vasthi treatments.
    Checks SlotMaster.is_vasthi_slot=True; falls back to ['08:30'].
    """
    try:
        from masters.models import SlotMaster
        slots = list(
            SlotMaster.objects.filter(is_active=True, is_vasthi_slot=True).values_list("slot_time", flat=True)
        )
        if slots:
            return [s.strftime("%H:%M") if hasattr(s, "strftime") else str(s)[:5] for s in slots]
    except Exception:
        pass
    return ["08:30"]


def get_vasthi_slot_names():
    """
    Return list of formatted slot names / times for Vasthi treatments.
    Uses slot_name if provided; includes formatted time for clarity.
    """
    try:
        from masters.models import SlotMaster
        slots = SlotMaster.objects.filter(is_active=True, is_vasthi_slot=True).order_by("slot_time")
        names = []
        for s in slots:
            time_formatted = s.slot_time.strftime("%I:%M %p").lstrip("0")
            if s.slot_name and s.slot_name.strip():
                s_name = s.slot_name.strip()
                if time_formatted.lower() in s_name.lower() or "am" in s_name.lower() or "pm" in s_name.lower():
                    names.append(s_name)
                else:
                    names.append(f"{s_name} ({time_formatted})")
            else:
                names.append(time_formatted)
        if names:
            return names
    except Exception:
        pass
    return ["08:30 AM"]


def allocate_vasthi_treatment_room(
    date,
    time_slot,
    last_room=None,
    therapy_name=None,
    patient_id=None,
    patient_staying_room=None,
    patient=None,
    booking_id=None,
):
    """
    Dedicated room allocation function for Vasthi treatments:
    1. Cottage patients (CT-*) preferably receive their matching TRC-* Cottage Room.
    2. If multiple patients share a Cottage Room, only one gets TRC-*; others receive
       suitable standard treatment rooms (TR-1..TR-16, excluding Vamanam/Steam rooms).
    3. Non-Cottage patients follow standard staying-room mapping, then OP fallback.
    """
    from Patient.models import RoomBooking, TreatmentRoom

    def check_room_availability(room_no, exclude_trc=False):
        try:
            room = TreatmentRoom.objects.get(room_no=room_no)
            if not room.is_active:
                return None
            if exclude_trc and room_no.upper().startswith("TRC"):
                return None
            rb_qs = RoomBooking.objects.filter(
                room=room,
                date=date,
                time_slot=time_slot,
                status="BOOKED",
            )
            if booking_id:
                rb_qs = rb_qs.exclude(visit_id=booking_id)
            if not rb_qs.exists():
                return room
        except TreatmentRoom.DoesNotExist:
            pass
        return None

    staying_room_str = str(patient_staying_room or "").strip().upper()
    is_cottage = staying_room_str.startswith("CT")

    if is_cottage:
        match = re.match(r"CT-?(\d+)", staying_room_str)
        cottage_room_no = f"TRC-{match.group(1)}" if match else None

        if cottage_room_no:
            c_room = check_room_availability(cottage_room_no)
            if c_room:
                print(f"[VASTHI ROOM ALLOCATION] Cottage patient {staying_room_str} assigned preferred Cottage Room {c_room.room_no}.")
                return c_room

        print(f"[VASTHI ROOM ALLOCATION] Cottage Room {cottage_room_no} unavailable/already assigned for another patient in {staying_room_str}. Assigning to other suitable treatment room...")

        standard_rooms = [f"TR-{i}" for i in range(1, 17)]
        vamanam_rooms = set(TreatmentRoom.objects.filter(is_vamanam_room=True).values_list("room_no", flat=True))
        steam_rooms = set(TreatmentRoom.objects.filter(is_steam_room=True).values_list("room_no", flat=True))

        for cand_room_no in standard_rooms:
            if cand_room_no in vamanam_rooms or cand_room_no in steam_rooms:
                continue
            alt_room = check_room_availability(cand_room_no)
            if alt_room:
                print(f"[VASTHI ROOM ALLOCATION] Cottage patient {staying_room_str} successfully assigned alternative suitable room {alt_room.room_no}.")
                return alt_room

        fallback_rooms = TreatmentRoom.objects.filter(is_active=True).exclude(room_no__startswith="TRC").exclude(room_no__in=vamanam_rooms).order_by("room_no")
        for f_room in fallback_rooms:
            room = check_room_availability(f_room.room_no)
            if room:
                print(f"[VASTHI ROOM ALLOCATION] Cottage patient {staying_room_str} assigned fallback room {room.room_no}.")
                return room

        print(f"[VASTHI ROOM ALLOCATION] No suitable room available for Cottage patient {staying_room_str} on {date} at {time_slot}.")
        return None

    treatment_rooms = get_treatment_rooms_for_staying_room(patient_staying_room)
    if treatment_rooms:
        for room_no in treatment_rooms:
            room = check_room_availability(room_no)
            if room:
                return room
        return None

    op_rooms = ["TR-9", "TR-10", "TR-11", "TR-12", "TR-13", "TR-14", "TR-5", "TR-6", "TR-7"]
    for room_no in op_rooms:
        room = check_room_availability(room_no, exclude_trc=True)
        if room:
            return room
    return None
