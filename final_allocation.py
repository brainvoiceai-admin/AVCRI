import os
import django
from datetime import timedelta, datetime
from django.db import transaction, IntegrityError

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
    Updated allocation:
      - reads Visit and its store_Therapy rows
      - chooses slots, rooms, therapists while ignoring CANCELED bookings
      - creates RoomBooking/TherapistBooking with visit pointer using safe functions
    Returns a list of created tasks (same structure as before).
    """
    try:
        visit = Visit.objects.get(pk=visit_id)
    except Visit.DoesNotExist:
        return {"error": f"Visit id {visit_id} not found."}

    patient_id = visit.patient_id
    last_allocation = {}
    if visit.repeated_status and visit.repeated_status.lower()=="yes":
        last_allocation = get_last_patient_allocation(visit.patient_id)

    used_slots_per_date = {}  # Track used slots per patient per date (TimeSlot instances)
    tasks=[]

    for therapy in visit.therapies.all():
        for dt in daterange(therapy.from_date, therapy.to_date):
            therapy_req = therapist_requirements(therapy)

            # Get already used slots for this patient/date
            used_slots = used_slots_per_date.get(dt, [])

            # Allocate a slot avoiding conflicts
            assigned_slot_str = allocate_treatment_slot(visit.is_ip_or_op, therapy_req["therapy_category"], used_slots)
            if not assigned_slot_str:
                print(f"No available slot for patient {patient_id} on {dt}")
                continue

            assigned_time = datetime.strptime(assigned_slot_str, "%H:%M").time()
            time_slot, _ = TimeSlot.objects.get_or_create(start_time=assigned_time)

            # Room allocation (ignores canceled bookings)
            room_obj = None
            if therapy_needs_room(therapy):
                room_obj = allocate_treatment_room(dt, time_slot, last_allocation.get("last_t_room"))

            # Therapist allocation (ignores canceled bookings)
            therapists = allocate_therapists(dt, time_slot, therapy_req, last_allocation.get("last_therapist_codes"), therapy_needs_bath(therapy))

            # Save RoomBooking (safe creation) and attach visit + try to attach store_Therapy
            room_booking = None
            if room_obj and create_bookings:
                rb, created_rb = create_room_booking_safe(room_obj, dt, time_slot, therapy.therapy_name, patient_id, visit)
                room_booking = rb
                # try to link store_Therapy if not already linked
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
                    # attach therapy pointer if available
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

            # Optional: Save PatientHistory (uncomment if you want)
            # PatientHistory.objects.create(
            #     preg_no=visit.patient_id,
            #     pat_name=getattr(visit,"patient_name",str(visit.patient_name)),
            #     date=dt,
            #     therapist_name=", ".join([t.therapist_name for t in therapists]),
            #     therapist_code=", ".join([t.therapist_code for t in therapists]),
            #     room_no=room_obj.room_no if room_obj else None,
            #     treatment=therapy.therapy_name,
            #     t_room=room_obj.room_no if room_obj else None
            # )

            # Mark this slot as used for the patient
            used_slots.append(time_slot)
            used_slots_per_date[dt] = used_slots

            tasks.append({
                "date": dt.isoformat(),
                "therapy_name": therapy.therapy_name,
                "slot": assigned_slot_str,
                "room_no": room_obj.room_no if room_obj else None,
                "therapists": [t.therapist_code for t in therapists]
            })

            # update last allocation info for patient (helps next therapy)
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
