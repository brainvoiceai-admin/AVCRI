import os
import django
from datetime import timedelta

# ---------------- SETUP DJANGO ----------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AVCRI.settings")  # change to your project
django.setup()

# ---------------- IMPORT MODELS ----------------
from MySql_Data_pull.models import Visit
from Patient.models import TherapyDetails, PatientHistory, TreatmentRoom, RoomBooking

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
    return details and details.treatment_room_required and details.treatment_room_required.lower() == "yes"

def therapy_needs_bath(therapy_obj):
    details = get_therapy_details(therapy_obj.therapy_name)
    return details and details.bathing_required and details.bathing_required.lower() == "yes"

def therapist_requirements(therapy_obj):
    details = get_therapy_details(therapy_obj.therapy_name)
    if not details:
        return {
            "super_senior": 0,
            "senior": 0,
            "junior": 0,
            "trainee": 0,
            "total": 0,
            "therapy_code": None,
            "therapy_category": None
        }
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
    last_history = (
        PatientHistory.objects
        .filter(preg_no=preg_no)
        .order_by('-date')
    )
    
    if not last_history.exists():
        return {"last_therapist_codes": [], "last_t_room": None}

    last_record = last_history.first()
    therapist_codes = []
    therapist_names = []

    if last_record.therapist_code:
        therapist_codes = [code.strip() for code in last_record.therapist_code.split(",")]
    if last_record.therapist_name:
        therapist_names = [name.strip() for name in last_record.therapist_name.split(",")]

    return {
        "last_therapist_codes": therapist_codes,
        "last_therapist_names": therapist_names,
        "last_t_room": last_record.t_room
    }

# ---------------- ROOM ALLOCATION FUNCTION ----------------
def allocate_treatment_room(patient_id, therapy_name, date, last_room=None):
    print(f"\n[DEBUG] Allocating room for Patient {patient_id}, Therapy: {therapy_name}, Date: {date}")

    # 1. Try last assigned room
    if last_room:
        if not RoomBooking.objects.filter(room_id=last_room, date=date).exists():
            print(f"[INFO] Assigned last used room: {last_room}")
            return last_room
        else:
            print(f"[INFO] Last used room {last_room} is already booked.")

    # 2. Try rooms on same floor
    if last_room:
        try:
            last_room_obj = TreatmentRoom.objects.get(room_no=last_room)
            same_floor_rooms = TreatmentRoom.objects.filter(floor=last_room_obj.floor)
            for room in same_floor_rooms:
                if not RoomBooking.objects.filter(room=room, date=date).exists():
                    print(f"[INFO] Assigned same floor room: {room.room_no}")
                    return room.room_no
        except TreatmentRoom.DoesNotExist:
            print("[WARN] Last room not found in TreatmentRoom table.")

    # 3. Try any available room
    all_rooms = TreatmentRoom.objects.all()
    for room in all_rooms:
        if not RoomBooking.objects.filter(room=room, date=date).exists():
            print(f"[INFO] Assigned available room: {room.room_no}")
            return room.room_no

    print("[ERROR] No room available for this date.")
    return None

# ---------------- SLOT ALLOCATION FUNCTION ----------------
def allocate_treatment_slot(patient_type, therapy_category, last_slot=None):
    """
    Allocate slot based on IP/OP rules and therapy type.
    """
    general_slots = ["06:30", "08:30", "10:00", "11:30", "14:30", "16:00", "17:30"]

    if patient_type.upper() == "OP":
        allowed_slots = ["11:30", "17:30"]
    elif patient_type.upper() == "IP":
        allowed_slots = ["06:30", "08:30", "10:00", "14:30", "16:00"]
    else:
        allowed_slots = general_slots  # fallback

    # Hard/Special treatment rule
    if therapy_category and therapy_category.lower() in ["hard", "special"]:
        allowed_slots = [s for s in general_slots if s not in ["11:30", "17:30"]]

    # Reuse last slot if valid
    if last_slot and last_slot in allowed_slots:
        print(f"[INFO] Reusing last slot: {last_slot}")
        return last_slot

    # Otherwise assign first available
    if allowed_slots:
        print(f"[INFO] Assigned new slot: {allowed_slots[0]}")
        return allowed_slots[0]

    print("[ERROR] No valid slot available.")
    return None

# ---------------- CORE FUNCTION ----------------
def expand_therapies_for_visit(visit_id):
    try:
        visit = Visit.objects.get(pk=visit_id)
    except Visit.DoesNotExist:
        return {"error": f"Visit id {visit_id} not found."}

    patient_id = visit.patient_id
    patient_common = {
        "is_ip_or_op": visit.is_ip_or_op,
        "is_vip": visit.is_vip,
        "repeated_status": visit.repeated_status
    }

    last_allocation = {}
    if visit.repeated_status and visit.repeated_status.lower() == "yes":
        last_allocation = get_last_patient_allocation(visit.patient_id)

    tasks = []
    therapies = list(visit.therapies.all())
    if not therapies:
        return {"error": "No therapies found for visit."}

    for therapy in therapies:
        if not therapy.from_date or not therapy.to_date:
            continue  

        for dt in daterange(therapy.from_date, therapy.to_date):
            req = therapist_requirements(therapy)
            task = {
                "visit_id": visit.id,
                "patient_id": patient_id,
                **patient_common,
                "therapy_id": therapy.id,
                "therapy_name": therapy.therapy_name,
                "therapy_code": req["therapy_code"],
                "therapy_category": req["therapy_category"],
                "date": dt.isoformat(),
                "needs_room": therapy_needs_room(therapy),
                "needs_bath": therapy_needs_bath(therapy),
                "therapist_requirements": req,
            }

            # Allocate room if required
            if therapy_needs_room(therapy):
                assigned_room = allocate_treatment_room(
                    patient_id=patient_id,
                    therapy_name=therapy.therapy_name,
                    date=dt,
                    last_room=last_allocation.get("last_t_room") if last_allocation else None
                )
                task["assigned_room_no"] = assigned_room
            else:
                task["assigned_room_no"] = None

            # Allocate slot
            assigned_slot = allocate_treatment_slot(
                patient_type=visit.is_ip_or_op,
                therapy_category=req["therapy_category"],
                last_slot=None  # later can reuse from history
            )
            task["assigned_slot"] = assigned_slot

            if last_allocation:
                task["last_therapist_codes"] = last_allocation.get("last_therapist_codes", [])
                task["last_therapist_names"] = last_allocation.get("last_therapist_names", [])
                task["last_t_room"] = last_allocation.get("last_t_room")

            tasks.append(task)

    return tasks

# ---------------- DEMO ----------------
if __name__ == "__main__":
    visit_id = int(input("Enter visit id: "))
    tasks = expand_therapies_for_visit(visit_id)
    if "error" in tasks:
        print(tasks["error"])
    else:
        print(f"\nExpanded {len(tasks)} tasks:\n")
        for t in tasks[:20]:
            print(
                f"Date: {t['date']} | Therapy: {t['therapy_name']} | "
                f"Room: {t.get('assigned_room_no')} | Slot: {t.get('assigned_slot')}"
            )
