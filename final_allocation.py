import os
import django
from datetime import timedelta, datetime
from django.db import transaction, IntegrityError
from Patient.models import AllocationAttempt
# ---------------- SETUP DJANGO ----------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AVCRI.settings")
django.setup()

# ---------------- IMPORT MODELS ----------------
from MySql_Data_pull.models import Visit
from Patient.models import (
    TherapyDetails,
    PatientHistory,
    TreatmentRoom,
    RoomBooking,
    Therapist,
    TherapistLeave,
    TherapistBooking,
    TimeSlot,
)
from MySql_Data_pull.models import store_Therapy  # adjust if different location
from MySql_Data_pull.models import store_TherapyItem, store_PrescriptionItem  # only used in cascade examples

# ---------------- HELPERS ----------------
def daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)

# ---------------- CACHING THERAPY DETAILS ----------------
therapy_cache = {}
def get_therapy_details(therapy_name):
    name = therapy_name.strip().lower()
    if name in therapy_cache:
        return therapy_cache[name]
    try:
        details = TherapyDetails.objects.get(therapy_name__iexact=therapy_name)
        therapy_cache[name] = details
        return details
    except TherapyDetails.DoesNotExist:
        therapy_cache[name] = None
        return None

# ---------------- THERAPY ATTRIBUTE HELPERS ----------------
def therapy_needs_room(therapy_obj):
    details = get_therapy_details(therapy_obj.therapy_name)
    return details and getattr(details, 'treatment_room_required', '').lower() == "yes"

def therapy_needs_bath(therapy_obj):
    details = get_therapy_details(therapy_obj.therapy_name)
    return details and getattr(details, 'bathing_required', '').lower() == "yes"

def therapist_requirements(therapy_obj):
    details = get_therapy_details(therapy_obj.therapy_name)
    if not details:
        return {"super_senior":0, "senior":0, "junior":0, "trainee":0, "total":0,
                "therapy_code": None, "therapy_category": None}
    return {
        "super_senior": details.no_of_super_senior_therapist,
        "senior": details.no_of_senior_therapist,
        "junior": details.no_of_junior_therapist,
        "trainee": details.no_of_trainee_therapist,
        "total": details.total_no_of_therapist,
        "therapy_code": details.therapy_code,
        "therapy_category": details.therapy_category
    }

# ---------------- PATIENT HISTORY HELPER ----------------
def get_last_patient_allocation(preg_no):
    last_history = PatientHistory.objects.filter(preg_no=preg_no).order_by('-date')
    if not last_history.exists():
        return {"last_therapist_codes": [], "last_t_room": None}
    last_record = last_history.first()
    therapist_codes = [code.strip() for code in last_record.therapist_code.split(",")] if last_record.therapist_code else []
    return {
        "last_therapist_codes": therapist_codes,
        "last_t_room": last_record.t_room
    }

# ---------------- SAFE BOOKING CREATION HELPERS ----------------
def create_room_booking_safe(room, date, time_slot, therapy_name, patient_id, visit):
    """
    Safely create a RoomBooking with status='BOOKED'. Handles race conditions via DB constraint/IntegrityError.
    Returns (room_booking_instance, created_bool)
    """
    try:
        with transaction.atomic():
            rb, created = RoomBooking.objects.get_or_create(
                room=room,
                date=date,
                time_slot=time_slot,
                status='BOOKED',
                defaults={
                    'therapy_name': therapy_name,
                    'patient_id': patient_id,
                    'visit': visit
                }
            )
            # ensure visit set on existing booking for consistency
            if not created and rb.visit is None and visit is not None:
                rb.visit = visit
                rb.save(update_fields=['visit'])
            return rb, created
    except IntegrityError:
        # concurrent creation happened; fetch the existing active booking (if any)
        rb = RoomBooking.objects.filter(room=room, date=date, time_slot=time_slot, status='BOOKED').first()
        return rb, False

def create_therapist_booking_safe(therapist, date, time_slot, therapy_name, patient_id, visit):
    try:
        with transaction.atomic():
            tb, created = TherapistBooking.objects.get_or_create(
                therapist=therapist,
                date=date,
                time_slot=time_slot,
                status='BOOKED',
                defaults={
                    'therapy_name': therapy_name,
                    'patient_id': patient_id,
                    'visit': visit
                }
            )
            if not created and tb.visit is None and visit is not None:
                tb.visit = visit
                tb.save(update_fields=['visit'])
            return tb, created
    except IntegrityError:
        tb = TherapistBooking.objects.filter(therapist=therapist, date=date, time_slot=time_slot, status='BOOKED').first()
        return tb, False

# ---------------- ROOM ALLOCATION (uses active/booked only) ----------------
def allocate_treatment_room(date, time_slot, last_room=None):
    # Try last room first
    if last_room:
        # check only active/booked rows block a room
        if not RoomBooking.objects.filter(room__room_no=last_room, date=date, time_slot=time_slot, status='BOOKED').exists():
            try:
                return TreatmentRoom.objects.get(room_no=last_room)
            except TreatmentRoom.DoesNotExist:
                pass

    # Same floor fallback
    if last_room:
        try:
            last_room_obj = TreatmentRoom.objects.get(room_no=last_room)
            same_floor_rooms = TreatmentRoom.objects.filter(floor=last_room_obj.floor)
            for room in same_floor_rooms:
                if not RoomBooking.objects.filter(room=room, date=date, time_slot=time_slot, status='BOOKED').exists():
                    return room
        except TreatmentRoom.DoesNotExist:
            pass
    # Any available room
    for room in TreatmentRoom.objects.all():
        if not RoomBooking.objects.filter(room=room, date=date, time_slot=time_slot, status='BOOKED').exists():
            return room
    return None

# ---------------- SLOT ALLOCATION ----------------
def allocate_treatment_slot(patient_type, therapy_category, used_slots=None):
    general_slots = ["06:30","08:30","10:00","11:30","14:30","16:00","17:30"]
    if patient_type and patient_type.upper() == "OP":
        allowed_slots = ["11:30","17:30"]
    elif patient_type and patient_type.upper() == "IP":
        allowed_slots = ["06:30","08:30","10:00","14:30","16:00"]
    else:
        allowed_slots = general_slots
    if therapy_category and therapy_category.lower() in ["hard","special"]:
        allowed_slots = [s for s in general_slots if s not in ["11:30","17:30"]]

    # Remove used slots for the patient
    if used_slots:
        used_slot_strs = [s.start_time.strftime("%H:%M") for s in used_slots]
        allowed_slots = [s for s in allowed_slots if s not in used_slot_strs]

    if not allowed_slots:
        return None
    return allowed_slots[0]

# ---------------- THERAPIST ALLOCATION (only BOOKED blocks) ----------------
def allocate_therapists(date, time_slot, therapy_requirements, last_therapists=None, needs_bathing=False):
    day_of_week = date.weekday()
    allocated = []
    grade_map = {
        "Super Senior Therapist": therapy_requirements.get("super_senior",0),
        "Senior Therapist": therapy_requirements.get("senior",0),
        "Junior Therapist": therapy_requirements.get("junior",0),
        "Trainee Therapist": therapy_requirements.get("trainee",0)
    }
    # Use last therapists
    if last_therapists:
        for code in last_therapists:
            try:
                t = Therapist.objects.get(therapist_code=code)
                if grade_map.get(t.therapist_grade,0) > 0 and not TherapistLeave.objects.filter(therapist=t, leave_day=day_of_week).exists():
                    # only consider active/booked rows as blocking
                    if not TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                        allocated.append(t)
                        grade_map[t.therapist_grade]-=1
            except Therapist.DoesNotExist:
                continue
    # Allocate new therapists
    for grade, count in grade_map.items():
        if count<=0: continue
        candidates = Therapist.objects.filter(therapist_grade=grade)
        if needs_bathing:
            candidates = candidates.filter(is_bathing_therapist=True)
        # filter out already allocated and those on leave
        candidates = [t for t in candidates if t not in allocated and not TherapistLeave.objects.filter(therapist=t, leave_day=day_of_week).exists()]
        for t in candidates:
            # only treat booked rows as blocking
            if not TherapistBooking.objects.filter(therapist=t, date=date, time_slot=time_slot, status='BOOKED').exists():
                allocated.append(t)
                count-=1
            if count<=0:
                break
    return allocated

# ---------------- MAIN FUNCTION (updated) ----------------
def expand_therapies_for_visit(visit_id, create_bookings=True):
    """
    Slot-aware allocation:
      - If a store_Therapy has a preferred_time_slot (FK) or preferred_time_slot_value (HH:MM),
        attempt ONLY that slot for each date.
      - Check patient already booked at same date+slot (DB) and used slots in current run.
      - Attempt room + therapists atomically; on any conflict record FAILED AllocationAttempt.
      - If no preferred slot present, fallback to original automatic allocation logic.
    Returns list of per-date task dicts with status and reason details.
    """
    try:
        visit = Visit.objects.get(pk=visit_id)
    except Visit.DoesNotExist:
        return {"error": f"Visit id {visit_id} not found."}

    # import AllocationAttempt here so this function works even if model not present at module top
    try:
        from MySql_Data_pull.models import AllocationAttempt
    except Exception:
        AllocationAttempt = None  # graceful fallback if model doesn't exist; we will skip writes

    patient_id = visit.patient_id
    last_allocation = {}
    if visit.repeated_status and visit.repeated_status.lower() == "yes":
        last_allocation = get_last_patient_allocation(visit.patient_id)

    used_slots_per_date = {}  # {date: [TimeSlot instances used this run]}
    tasks = []

    for therapy in visit.therapies.all():
        therapy_req = therapist_requirements(therapy)
        needs_room_flag = therapy_needs_room(therapy)
        needs_bath_flag = therapy_needs_bath(therapy)

        # Resolve preferred TimeSlot (if present) to a TimeSlot instance
        preferred_ts = None
        # try FK id first
        try:
            pref_fk_id = getattr(therapy, 'preferred_time_slot_id', None)
        except Exception:
            pref_fk_id = None

        if pref_fk_id:
            # TimeSlot uses slot_number as PK; try that first, then pk
            preferred_ts = TimeSlot.objects.filter(slot_number=pref_fk_id).first() or TimeSlot.objects.filter(pk=pref_fk_id).first()

        # fallback to text value e.g. "06:30"
        if not preferred_ts:
            text_val = (getattr(therapy, 'preferred_time_slot_value', None) or getattr(therapy, 'preferred_slot_value', None) or '').strip()
            if text_val:
                try:
                    parsed_time = datetime.strptime(text_val, "%H:%M").time()
                    preferred_ts = TimeSlot.objects.filter(start_time=parsed_time).first()
                except Exception:
                    preferred_ts = None

        # iterate through therapy dates
        for dt in daterange(therapy.from_date, therapy.to_date):
            therapy_req = therapist_requirements(therapy)  # refresh per therapy
            # used slots for this date in this run
            used_slots = used_slots_per_date.get(dt, [])

            # If preferred slot exists -> try preferred-only allocation
            if preferred_ts:
                requested_slot_value = preferred_ts.start_time.strftime("%H:%M")

                # 1) Check if patient already has a booking in DB for this date+slot
                patient_already_booked = (
                    RoomBooking.objects.filter(patient_id=patient_id, date=dt, time_slot=preferred_ts, status='BOOKED').exists()
                    or TherapistBooking.objects.filter(patient_id=patient_id, date=dt, time_slot=preferred_ts, status='BOOKED').exists()
                )
                if patient_already_booked:
                    # record failed attempt and continue
                    if AllocationAttempt:
                        try:
                            AllocationAttempt.objects.create(
                                visit=visit,
                                therapy=therapy,
                                date=dt,
                                requested_time_slot=preferred_ts,
                                requested_time_slot_value=requested_slot_value,
                                status='FAILED',
                                reason='patient_already_has_booking',
                                extra={}
                            )
                        except Exception:
                            pass
                    tasks.append({
                        "date": dt.isoformat(),
                        "therapy_name": therapy.therapy_name,
                        "slot": requested_slot_value,
                        "status": "FAILED",
                        "reason": "patient_already_has_booking",
                        "room_no": None,
                        "therapists": []
                    })
                    continue

                # 2) Check in-memory used slots in this run (prevents double booking within same submission)
                if any(getattr(s, 'start_time', None) == preferred_ts.start_time for s in used_slots):
                    if AllocationAttempt:
                        try:
                            AllocationAttempt.objects.create(
                                visit=visit,
                                therapy=therapy,
                                date=dt,
                                requested_time_slot=preferred_ts,
                                requested_time_slot_value=requested_slot_value,
                                status='FAILED',
                                reason='slot_already_used_in_run',
                                extra={}
                            )
                        except Exception:
                            pass
                    tasks.append({
                        "date": dt.isoformat(),
                        "therapy_name": therapy.therapy_name,
                        "slot": requested_slot_value,
                        "status": "FAILED",
                        "reason": "slot_already_used_in_run",
                        "room_no": None,
                        "therapists": []
                    })
                    continue

                # 3) Candidate therapists (uses your allocate_therapists helper)
                candidate_therapists = allocate_therapists(dt, preferred_ts, therapy_req, last_allocation.get("last_therapist_codes"), needs_bath_flag)
                req_total = therapy_req.get("total", 0) or 0
                if len(candidate_therapists) < req_total:
                    if AllocationAttempt:
                        try:
                            AllocationAttempt.objects.create(
                                visit=visit,
                                therapy=therapy,
                                date=dt,
                                requested_time_slot=preferred_ts,
                                requested_time_slot_value=requested_slot_value,
                                status='FAILED',
                                reason='insufficient_therapists_available',
                                extra={"required": req_total, "found": len(candidate_therapists)}
                            )
                        except Exception:
                            pass
                    tasks.append({
                        "date": dt.isoformat(),
                        "therapy_name": therapy.therapy_name,
                        "slot": requested_slot_value,
                        "status": "FAILED",
                        "reason": "insufficient_therapists_available",
                        "room_no": None,
                        "therapists": [t.therapist_code for t in candidate_therapists]
                    })
                    continue

                # 4) Room candidate if therapy needs room
                room_candidate = None
                if needs_room_flag:
                    room_candidate = allocate_treatment_room(dt, preferred_ts, last_allocation.get("last_t_room"))
                    if not room_candidate:
                        if AllocationAttempt:
                            try:
                                AllocationAttempt.objects.create(
                                    visit=visit,
                                    therapy=therapy,
                                    date=dt,
                                    requested_time_slot=preferred_ts,
                                    requested_time_slot_value=requested_slot_value,
                                    status='FAILED',
                                    reason='no_room_available',
                                    extra={}
                                )
                            except Exception:
                                pass
                        tasks.append({
                            "date": dt.isoformat(),
                            "therapy_name": therapy.therapy_name,
                            "slot": requested_slot_value,
                            "status": "FAILED",
                            "reason": "no_room_available",
                            "room_no": None,
                            "therapists": [t.therapist_code for t in candidate_therapists]
                        })
                        continue

                # 5) Attempt bookings atomically (room + all therapists)
                try:
                    with transaction.atomic():
                        rb_obj = None
                        if needs_room_flag:
                            rb_obj, rb_created = create_room_booking_safe(room_candidate, dt, preferred_ts, therapy.therapy_name, patient_id, visit)
                            if not rb_created:
                                # conflict: someone else booked the room
                                raise RuntimeError("room_already_booked")

                            # attach therapy pointer if available
                            if rb_obj and getattr(rb_obj, 'therapy', None) is None:
                                matched_th = store_Therapy.objects.filter(
                                    visit=visit,
                                    therapy_name__iexact=therapy.therapy_name,
                                    from_date__lte=dt,
                                    to_date__gte=dt
                                ).first()
                                if matched_th:
                                    rb_obj.therapy = matched_th
                                    rb_obj.save(update_fields=['therapy'])

                        tb_objs = []
                        for t in candidate_therapists:
                            tb_obj, tb_created = create_therapist_booking_safe(t, dt, preferred_ts, therapy.therapy_name, patient_id, visit)
                            if not tb_created:
                                raise RuntimeError(f"therapist_already_booked:{t.therapist_code}")
                            if tb_obj and getattr(tb_obj, 'therapy', None) is None:
                                matched_th2 = store_Therapy.objects.filter(
                                    visit=visit,
                                    therapy_name__iexact=therapy.therapy_name,
                                    from_date__lte=dt,
                                    to_date__gte=dt
                                ).first()
                                if matched_th2:
                                    tb_obj.therapy = matched_th2
                                    tb_obj.save(update_fields=['therapy'])
                            tb_objs.append(tb_obj)

                        # success: create AllocationAttempt success record
                        if AllocationAttempt:
                            try:
                                AllocationAttempt.objects.create(
                                    visit=visit,
                                    therapy=therapy,
                                    date=dt,
                                    requested_time_slot=preferred_ts,
                                    requested_time_slot_value=requested_slot_value,
                                    status='SUCCESS',
                                    reason='preferred_slot_booked',
                                    extra={
                                        "room_no": getattr(rb_obj.room, 'room_no', None) if rb_obj else None,
                                        "therapists": [t.therapist_code for t in candidate_therapists]
                                    }
                                )
                            except Exception:
                                pass

                        # mark used slot in this run
                        used_slots.append(preferred_ts)
                        used_slots_per_date[dt] = used_slots

                        tasks.append({
                            "date": dt.isoformat(),
                            "therapy_name": therapy.therapy_name,
                            "slot": requested_slot_value,
                            "status": "BOOKED",
                            "room_no": getattr(rb_obj.room, 'room_no', None) if rb_obj else None,
                            "therapists": [t.therapist_code for t in candidate_therapists]
                        })

                        # update last allocation info
                        if room_candidate:
                            last_allocation["last_t_room"] = room_candidate.room_no
                        if candidate_therapists:
                            last_allocation["last_therapist_codes"] = [t.therapist_code for t in candidate_therapists]

                        # done for this date
                        continue

                except RuntimeError as rte:
                    reason_txt = str(rte)
                    if AllocationAttempt:
                        try:
                            AllocationAttempt.objects.create(
                                visit=visit,
                                therapy=therapy,
                                date=dt,
                                requested_time_slot=preferred_ts,
                                requested_time_slot_value=requested_slot_value,
                                status='FAILED',
                                reason=reason_txt,
                                extra={"therapists_tried": [t.therapist_code for t in candidate_therapists], "room_candidate": getattr(room_candidate, 'room_no', None) if room_candidate else None}
                            )
                        except Exception:
                            pass
                    tasks.append({
                        "date": dt.isoformat(),
                        "therapy_name": therapy.therapy_name,
                        "slot": requested_slot_value,
                        "status": "FAILED",
                        "reason": reason_txt,
                        "room_no": getattr(room_candidate, 'room_no', None) if room_candidate else None,
                        "therapists": [t.therapist_code for t in candidate_therapists]
                    })
                    continue
                except Exception as exc:
                    reason_txt = f"exception:{str(exc)}"
                    if AllocationAttempt:
                        try:
                            AllocationAttempt.objects.create(
                                visit=visit,
                                therapy=therapy,
                                date=dt,
                                requested_time_slot=preferred_ts,
                                requested_time_slot_value=requested_slot_value,
                                status='FAILED',
                                reason=reason_txt,
                                extra={}
                            )
                        except Exception:
                            pass
                    tasks.append({
                        "date": dt.isoformat(),
                        "therapy_name": therapy.therapy_name,
                        "slot": requested_slot_value,
                        "status": "FAILED",
                        "reason": reason_txt,
                        "room_no": getattr(room_candidate, 'room_no', None) if room_candidate else None,
                        "therapists": [t.therapist_code for t in (candidate_therapists or [])]
                    })
                    continue

            # END preferred-slot branch

            # If no preferred slot -> fallback to original automatic allocation (unchanged)
            assigned_slot_str = allocate_treatment_slot(visit.is_ip_or_op, therapy_req["therapy_category"], used_slots)
            if not assigned_slot_str:
                if AllocationAttempt:
                    try:
                        AllocationAttempt.objects.create(
                            visit=visit,
                            therapy=therapy,
                            date=dt,
                            requested_time_slot=None,
                            requested_time_slot_value='',
                            status='FAILED',
                            reason='no_slot_available_auto',
                            extra={}
                        )
                    except Exception:
                        pass
                tasks.append({
                    "date": dt.isoformat(),
                    "therapy_name": therapy.therapy_name,
                    "slot": None,
                    "status": "FAILED",
                    "reason": "no_slot_available_auto",
                    "room_no": None,
                    "therapists": []
                })
                continue

            assigned_time = datetime.strptime(assigned_slot_str, "%H:%M").time()
            time_slot, _ = TimeSlot.objects.get_or_create(start_time=assigned_time)

            # Check patient already booked at this date/time (DB) and used slots in this run
            if RoomBooking.objects.filter(patient_id=patient_id, date=dt, time_slot=time_slot, status='BOOKED').exists() \
               or TherapistBooking.objects.filter(patient_id=patient_id, date=dt, time_slot=time_slot, status='BOOKED').exists():
                if AllocationAttempt:
                    try:
                        AllocationAttempt.objects.create(
                            visit=visit,
                            therapy=therapy,
                            date=dt,
                            requested_time_slot=time_slot,
                            requested_time_slot_value=assigned_slot_str,
                            status='FAILED',
                            reason='patient_already_has_booking',
                            extra={}
                        )
                    except Exception:
                        pass
                tasks.append({
                    "date": dt.isoformat(),
                    "therapy_name": therapy.therapy_name,
                    "slot": assigned_slot_str,
                    "status": "FAILED",
                    "reason": "patient_already_has_booking",
                    "room_no": None,
                    "therapists": []
                })
                continue

            if any(getattr(s, 'start_time', None) == time_slot.start_time for s in used_slots):
                if AllocationAttempt:
                    try:
                        AllocationAttempt.objects.create(
                            visit=visit,
                            therapy=therapy,
                            date=dt,
                            requested_time_slot=time_slot,
                            requested_time_slot_value=assigned_slot_str,
                            status='FAILED',
                            reason='slot_already_used_in_run',
                            extra={}
                        )
                    except Exception:
                        pass
                tasks.append({
                    "date": dt.isoformat(),
                    "therapy_name": therapy.therapy_name,
                    "slot": assigned_slot_str,
                    "status": "FAILED",
                    "reason": "slot_already_used_in_run",
                    "room_no": None,
                    "therapists": []
                })
                continue

            # Room allocation (original logic)
            room_obj = None
            if therapy_needs_room(therapy):
                room_obj = allocate_treatment_room(dt, time_slot, last_allocation.get("last_t_room"))

            # Therapist allocation (original logic)
            therapists = allocate_therapists(dt, time_slot, therapy_req, last_allocation.get("last_therapist_codes"), therapy_needs_bath(therapy))

            # Save RoomBooking (safe creation) and attach visit + try to attach store_Therapy
            room_booking = None
            if room_obj and create_bookings:
                rb, created_rb = create_room_booking_safe(room_obj, dt, time_slot, therapy.therapy_name, patient_id, visit)
                room_booking = rb
                if rb and getattr(rb, 'therapy', None) is None:
                    matched_th = store_Therapy.objects.filter(
                                    visit=visit,
                                    therapy_name__iexact=therapy.therapy_name,
                                    from_date__lte=dt,
                                    to_date__gte=dt
                                ).first()
                    if matched_th:
                        rb.therapy = matched_th
                        rb.save(update_fields=['therapy'])

            # Save TherapistBooking(s)
            therapist_booking_objs = []
            if create_bookings:
                for t in therapists:
                    tb, created_tb = create_therapist_booking_safe(t, dt, time_slot, therapy.therapy_name, patient_id, visit)
                    therapist_booking_objs.append(tb)
                    if tb and getattr(tb, 'therapy', None) is None:
                        matched_th = store_Therapy.objects.filter(
                                        visit=visit,
                                        therapy_name__iexact=therapy.therapy_name,
                                        from_date__lte=dt,
                                        to_date__gte=dt
                                    ).first()
                        if matched_th:
                            tb.therapy = matched_th
                            tb.save(update_fields=['therapy'])

            # Mark this slot as used for the patient in this run
            used_slots.append(time_slot)
            used_slots_per_date[dt] = used_slots

            tasks.append({
                "date": dt.isoformat(),
                "therapy_name": therapy.therapy_name,
                "slot": assigned_slot_str,
                "room_no": room_obj.room_no if room_obj else None,
                "therapists": [t.therapist_code for t in therapists],
                "status": "BOOKED" if (room_obj or not therapy_needs_room(therapy)) else "PARTIAL"
            })

            # update last allocation info for patient
            if room_obj:
                last_allocation["last_t_room"] = room_obj.room_no
            if therapists:
                last_allocation["last_therapist_codes"] = [t.therapist_code for t in therapists]

    return tasks
# ---------------- DEMO ----------------
if __name__=="__main__":
    visit_id = int(input("Enter visit id: "))
    tasks = expand_therapies_for_visit(visit_id)
    if isinstance(tasks, dict) and "error" in tasks:
        print(tasks["error"])
    else:
        print(f"\nExpanded {len(tasks)} tasks:\n")
        for t in tasks:
            print(f"Date: {t['date']} | Therapy: {t['therapy_name']} | Slot: {t['slot']} | Room: {t['room_no']} | Therapists: {', '.join(t['therapists'])}")
