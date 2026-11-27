"""
Shared treatment room allocator (Layer 1B).

Unifies `allocate_treatment_room` from `final_allocation.py` and `reshedule.py`
while preserving all behavioral differences via `RoomAllocationConfig`.
"""

from dataclasses import dataclass
from datetime import datetime
import re
from django.db.models import Q

from allocation_engine.core.primitives.room_utils import get_treatment_rooms_for_staying_room
from allocation_engine.rules.dhara_pizhichil import (
    get_dhara_pizhichil_assigned_room,
    is_dhara_pizhichil_treatment,
)
from allocation_engine.rules.steam import get_steam_therapy_rooms, is_steam_therapy_treatment
from allocation_engine.rules.vamanam import allocate_vamanam_treatment_room, is_vamanam_treatment
from allocation_engine.rules.vasthi import allocate_vasthi_treatment_room, is_vasthi_treatment
from allocation_engine.rules.wheelchair import get_wheelchair_accessible_rooms


@dataclass(frozen=True)
class RoomAllocationConfig:
    """Configuration preserving exact scheduling vs rescheduling room-allocator behavior."""
    check_booking_table: bool = True
    exclude_cancelled_therapy_and_alloc: bool = False
    wheelchair_no_staying_room_fallback: bool = True
    use_reschedule_legacy_fallback: bool = True


SCHEDULING_ROOM_CONFIG = RoomAllocationConfig(
    check_booking_table=False,
    exclude_cancelled_therapy_and_alloc=True,
    wheelchair_no_staying_room_fallback=False,
    use_reschedule_legacy_fallback=False,
)

RESCHEDULING_ROOM_CONFIG = RoomAllocationConfig(
    check_booking_table=True,
    exclude_cancelled_therapy_and_alloc=False,
    wheelchair_no_staying_room_fallback=True,
    use_reschedule_legacy_fallback=True,
)


def allocate_treatment_room(
    date,
    time_slot,
    last_room=None,
    therapy_name=None,
    patient_id=None,
    patient_staying_room=None,
    patient=None,
    booking_id=None,
    is_wheelchair=False,
    *,
    config: RoomAllocationConfig = RESCHEDULING_ROOM_CONFIG,
):
    """
    Allocate treatment room based on therapy-specific restrictions, patient staying room rules,
    Dhara Pizhichil continuity, and wheelchair accessibility requirements.
    """
    from Patient.models import RoomBooking, TreatmentRoom
    from masters.models import SlotMaster

    # Ensure time_slot is resolved to a SlotMaster instance if string or time object was passed
    if time_slot is not None and not isinstance(time_slot, SlotMaster):
        if hasattr(time_slot, 'slot_time') and time_slot.slot_time:
            slot_candidate = SlotMaster.objects.filter(slot_time=time_slot.slot_time, is_active=True).first()
            if slot_candidate:
                time_slot = slot_candidate
        elif hasattr(time_slot, 'start_time') and time_slot.start_time:
            slot_candidate = SlotMaster.objects.filter(slot_time=time_slot.start_time, is_active=True).first()
            if slot_candidate:
                time_slot = slot_candidate
        else:
            time_str = str(time_slot).strip()
            if ":" in time_str:
                try:
                    p_time = datetime.strptime(time_str[:5], "%H:%M").time()
                    slot_candidate = SlotMaster.objects.filter(slot_time=p_time, is_active=True).first()
                    if slot_candidate:
                        time_slot = slot_candidate
                except Exception:
                    pass

    # Auto-detect wheelchair requirement from booking or patient if not explicitly passed
    if not is_wheelchair:
        if booking_id:
            try:
                from Sheduling.models import Booking
                b = Booking.objects.filter(pk=booking_id).first()
                if b and (
                    getattr(b, 'is_wheelchair', False)
                    or (b.allocation and getattr(b.allocation, 'is_wheelchair', False))
                ):
                    is_wheelchair = True
            except Exception:
                pass
        if not is_wheelchair and patient:
            if getattr(patient, 'is_wheelchair', False):
                is_wheelchair = True

    # Helper function to check room availability
    def check_room_availability(room_no, exclude_trc=False):
        try:
            room = TreatmentRoom.objects.get(room_no=room_no)
            if not room.is_active:
                return None
            # Wheelchair requirement: Wheelchair patients require accessible rooms.
            if is_wheelchair and not getattr(room, 'is_wheelchair_accessible', False):
                return None
            # Strictly exclude TRC rooms for OP patients
            if exclude_trc and room_no.upper().startswith('TRC'):
                return None

            rb_qs = RoomBooking.objects.filter(
                room=room,
                date=date,
                time_slot=time_slot,
                status='BOOKED',
            )
            if config.exclude_cancelled_therapy_and_alloc:
                rb_qs = rb_qs.exclude(
                    Q(therapy__status='cancelled')
                    | Q(visit__status='cancelled')
                    | Q(visit__allocation__status='cancelled')
                ).exclude(visit__status='cancelled')
            else:
                rb_qs = rb_qs.exclude(visit__status='cancelled')

            if rb_qs.exists():
                return None

            if config.check_booking_table:
                from Sheduling.models import Booking
                b_conflict = Booking.objects.filter(
                    room=room,
                    date=date,
                    timeslot=time_slot,
                    status__in=['scheduled', 'BOOKED'],
                ).exclude(status='cancelled').exclude(allocation__status='cancelled')
                if booking_id:
                    b_conflict = b_conflict.exclude(pk=booking_id)
                if b_conflict.exists():
                    return None

            return room
        except TreatmentRoom.DoesNotExist:
            pass
        return None

    # STEAM THERAPY RESTRICTION: Always allocate strictly to designated steam therapy rooms (dynamic from Room Master)
    try:
        if is_steam_therapy_treatment(therapy_name):
            steam_rooms = get_steam_therapy_rooms()
            for candidate_room_no in steam_rooms:
                steam_room = check_room_availability(candidate_room_no)
                if steam_room:
                    print(f"[ROOM RESTRICTION] Steam therapy detected - assigned {candidate_room_no} room.")
                    return steam_room
            print(
                f"[ROOM RESTRICTION] Steam therapy detected - all steam rooms ({', '.join(steam_rooms)}) are unavailable on {date} at {time_slot}."
            )
            return None
    except Exception as _st_err:
        print(f"[ROOM RESTRICTION] Error checking steam therapy room: {_st_err}")

    # VAMANAM THERAPY RESTRICTION: Dedicated Vamanam room allocation (Primary first: TR-11/TR-12, then Secondary: TR-9)
    try:
        if is_vamanam_treatment(therapy_name):
            v_room = allocate_vamanam_treatment_room(
                date, time_slot, check_room_availability, booking_id=booking_id
            )
            if v_room:
                return v_room
            return None
    except Exception as _vm_err:
        print(f"[ROOM RESTRICTION] Error checking Vamanam room: {_vm_err}")

    # VASTHI THERAPY RESTRICTION: Dedicated room allocation function for Vasthi treatments
    try:
        therapy_code = getattr(patient, 'therapy_code', None) if patient else None
        if is_vasthi_treatment(therapy_name, therapy_code):
            return allocate_vasthi_treatment_room(
                date,
                time_slot,
                last_room=last_room,
                therapy_name=therapy_name,
                patient_id=patient_id,
                patient_staying_room=patient_staying_room,
                patient=patient,
                booking_id=booking_id,
            )
    except Exception as _vsth_err:
        print(f"[ROOM RESTRICTION] Error in Vasthi room allocation: {_vsth_err}")

    # DHARA PIZHICHIL STRICT ROOM CONTINUITY:
    # If this therapy is marked as Dhara & Pizhichil in Therapy Master:
    # Maintain the same room until patient discharge, even across cancellations or rescheduling.
    try:
        if is_dhara_pizhichil_treatment(therapy_name=therapy_name):
            assigned_room = get_dhara_pizhichil_assigned_room(patient_id=patient_id, patient=patient)
            if assigned_room:
                room_obj = check_room_availability(assigned_room.room_no)
                if room_obj:
                    return room_obj
                # STRICT: If the assigned room is unavailable at this timeslot, do NOT switch rooms!
                return None
    except Exception as _dp_err:
        print(f"[ROOM RESTRICTION] Error checking Dhara Pizhichil room: {_dp_err}")

    # Primary logic - allocate based on patient staying room
    # Special handling: If patient_staying_room starts with "OP-", treat it as if there's no staying room
    staying_room_upper = None
    is_op_prefix = False
    if patient_staying_room:
        staying_room_upper = str(patient_staying_room).strip().upper()
        is_op_prefix = staying_room_upper.startswith('OP-')

    if patient_staying_room and not is_op_prefix:
        treatment_rooms = get_treatment_rooms_for_staying_room(patient_staying_room)

        if treatment_rooms:
            for room_no in treatment_rooms:
                room = check_room_availability(room_no)
                if room:
                    return room

            # If wheelchair patient and staying room rooms didn't yield an accessible room,
            # fallback to any available wheelchair accessible rooms in facility
            if is_wheelchair:
                for wc_room_no in get_wheelchair_accessible_rooms():
                    room = check_room_availability(wc_room_no)
                    if room:
                        return room
                return None

            # None of the assigned rooms are available
            return None

    # OP patient fallback logic
    is_op_patient = False
    if (not patient_staying_room or is_op_prefix) and patient:
        try:
            if hasattr(patient, 'is_op'):
                is_op_patient = patient.is_op()
            elif hasattr(patient, 'pat_reg_no'):
                digits = ''.join(ch for ch in str(patient.pat_reg_no or '') if ch.isdigit())
                is_op_patient = len(digits) == 5
        except Exception:
            pass

    if is_op_prefix:
        is_op_patient = True

    # For OP patients, check if they have a CT room from Treatment model
    if is_op_patient and patient:
        try:
            op_staying_room = getattr(patient, 'pat_room_no', None)
            if op_staying_room:
                op_room_upper = str(op_staying_room).strip().upper()
                if op_room_upper.startswith('CT'):
                    match = re.match(r'CT-?(\d+)', op_room_upper)
                    if match:
                        try:
                            ct_room_num = int(match.group(1))
                            trc_room_no = f'TRC-{ct_room_num}'
                            room = check_room_availability(trc_room_no)
                            if room:
                                return room
                            return None
                        except (ValueError, AttributeError):
                            pass
        except Exception:
            pass

    # OP patients with no room or non-CT room: Try TR-1 to TR-16 in order
    if is_op_patient:
        op_rooms = [
            'TR-1', 'TR-2', 'TR-3', 'TR-4', 'TR-5', 'TR-6', 'TR-7', 'TR-8',
            'TR-9', 'TR-10', 'TR-11', 'TR-12', 'TR-13', 'TR-14', 'TR-15', 'TR-16',
        ]
        for room_no in op_rooms:
            if room_no.upper().startswith('TRC'):
                continue
            room = check_room_availability(room_no, exclude_trc=True)
            if room:
                return room

        if is_wheelchair:
            for wc_room_no in get_wheelchair_accessible_rooms():
                if wc_room_no.upper().startswith('TRC'):
                    continue
                room = check_room_availability(wc_room_no, exclude_trc=True)
                if room:
                    return room

        # No room available for OP patient - DO NOT fall through to legacy logic
        return None

    # Rescheduling path: if wheelchair patient has no staying room, try any accessible room
    if config.wheelchair_no_staying_room_fallback and is_wheelchair:
        for wc_room_no in get_wheelchair_accessible_rooms():
            room = check_room_availability(wc_room_no)
            if room:
                return room
        return None

    # FALLBACK: Legacy logic if patient_staying_room is not provided and not OP
    is_dhara_pizichil = is_dhara_pizhichil_treatment(therapy_name=therapy_name) if therapy_name else False

    if config.use_reschedule_legacy_fallback:
        previous_room_no = None
        if is_dhara_pizichil and patient_id:
            try:
                previous_bookings = (
                    RoomBooking.objects.filter(patient_id=patient_id, status='BOOKED')
                    .exclude(date=date, time_slot=time_slot)
                    .order_by('-date', '-time_slot')
                    .select_related('room')
                )
                for booking in previous_bookings:
                    if is_dhara_pizhichil_treatment(therapy_name=booking.therapy_name):
                        if booking.room:
                            previous_room_no = booking.room.room_no
                            break
            except Exception as e:
                print(f"[DEBUG allocate_treatment_room] Error finding previous room: {e}")
                previous_room_no = None

        if is_dhara_pizichil and previous_room_no:
            try:
                previous_room = TreatmentRoom.objects.get(room_no=previous_room_no)
                if not RoomBooking.objects.filter(
                    room=previous_room,
                    date=date,
                    time_slot=time_slot,
                    status='BOOKED',
                ).exists():
                    print(f"[DEBUG allocate_treatment_room] Using previous Dhara & Pizhichil room: {previous_room_no}")
                    return previous_room
            except TreatmentRoom.DoesNotExist:
                pass

        if last_room:
            last_room_no = last_room if isinstance(last_room, str) else getattr(last_room, 'room_no', None)
            if last_room_no:
                room = check_room_availability(last_room_no)
                if room:
                    return room
        if last_room:
            try:
                if isinstance(last_room, str):
                    last_room_obj = TreatmentRoom.objects.get(room_no=last_room)
                else:
                    last_room_obj = last_room
                same_floor = TreatmentRoom.objects.filter(floor=last_room_obj.floor, is_active=True)
                for r in same_floor:
                    room = check_room_availability(r.room_no)
                    if room:
                        return room
            except TreatmentRoom.DoesNotExist:
                pass
        if not patient_staying_room and not is_op_patient:
            for r in TreatmentRoom.objects.filter(is_active=True):
                if r.room_no and r.room_no.upper().startswith('TRC'):
                    continue
                room = check_room_availability(r.room_no)
                if room:
                    return room
        return None

    # Scheduling legacy fallback
    previous_room_no = None
    if is_dhara_pizichil and patient_id:
        prev_room = get_dhara_pizhichil_assigned_room(patient_id=patient_id, patient=patient)
        if prev_room:
            previous_room_no = prev_room.room_no

    if is_dhara_pizichil and previous_room_no:
        if is_op_patient and previous_room_no.upper().startswith('TRC'):
            pass
        else:
            try:
                previous_room = TreatmentRoom.objects.get(room_no=previous_room_no)
                if is_wheelchair and not getattr(previous_room, 'is_wheelchair_accessible', False):
                    pass
                elif not RoomBooking.objects.filter(
                    room=previous_room,
                    date=date,
                    time_slot=time_slot,
                    status='BOOKED',
                ).exists():
                    return previous_room
            except TreatmentRoom.DoesNotExist:
                pass

    if last_room and not is_op_patient:
        try:
            room_no = last_room if isinstance(last_room, str) else getattr(last_room, 'room_no', None)
            if room_no and not room_no.upper().startswith('TRC'):
                room = TreatmentRoom.objects.get(room_no=room_no)
                if is_wheelchair and not getattr(room, 'is_wheelchair_accessible', False):
                    pass
                elif not RoomBooking.objects.filter(
                    room=room, date=date, time_slot=time_slot, status='BOOKED'
                ).exists():
                    return room
        except TreatmentRoom.DoesNotExist:
            pass

    if last_room and not is_op_patient:
        try:
            if isinstance(last_room, str):
                last_room_obj = TreatmentRoom.objects.get(room_no=last_room)
            else:
                last_room_obj = last_room
            same_floor = TreatmentRoom.objects.filter(floor=last_room_obj.floor)
            for r in same_floor:
                if r.room_no and r.room_no.upper().startswith('TRC'):
                    continue
                if is_wheelchair and not getattr(r, 'is_wheelchair_accessible', False):
                    continue
                if not RoomBooking.objects.filter(
                    room=r, date=date, time_slot=time_slot, status='BOOKED'
                ).exists():
                    return r
        except TreatmentRoom.DoesNotExist:
            pass

    if not patient_staying_room and not is_op_patient:
        for r in TreatmentRoom.objects.all():
            if r.room_no and r.room_no.upper().startswith('TRC'):
                continue
            if is_wheelchair and not getattr(r, 'is_wheelchair_accessible', False):
                continue
            if not RoomBooking.objects.filter(
                room=r, date=date, time_slot=time_slot, status='BOOKED'
            ).exists():
                return r

    return None
