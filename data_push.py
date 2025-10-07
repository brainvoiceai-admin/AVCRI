import os
import django
from datetime import timedelta

# ---------------- SETUP DJANGO ----------------
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "AVCRI.settings")  # change to your project
django.setup()

# ---------------- IMPORT MODELS ----------------
from MySql_Data_pull.models import Visit, store_Therapy
from Patient.models import TherapyDetails  # update app name

# ---------------- HELPERS ----------------
def daterange(start_date, end_date):
    """Yield each date from start_date to end_date inclusive."""
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
            "therapy_category": None  # added
        }
    return {
        "super_senior": details.no_of_super_senior_therapist,
        "senior": details.no_of_senior_therapist,
        "junior": details.no_of_junior_therapist,
        "trainee": details.no_of_trainee_therapist,
        "total": details.total_no_of_therapist,
        "therapy_code": details.therapy_code,
        "therapy_category": details.therapy_category  # added
    }

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

    tasks = []
    therapies = list(visit.therapies.all())  # assuming related_name='therapies'
    if not therapies:
        return {"error": "No therapies found for visit."}

    for therapy in therapies:
        if not therapy.from_date or not therapy.to_date:
            continue  # skip invalid ranges

        for dt in daterange(therapy.from_date, therapy.to_date):
            req = therapist_requirements(therapy)
            tasks.append({
    "visit_id": visit.id,
    "patient_id": patient_id,
    **patient_common,
    "therapy_id": therapy.id,
    "therapy_name": therapy.therapy_name,
    "therapy_code": req["therapy_code"],
    "therapy_category": req["therapy_category"],  # added
    "date": dt.isoformat(),
    "needs_room": therapy_needs_room(therapy),
    "needs_bath": therapy_needs_bath(therapy),
    "therapist_requirements": {
        "super_senior": req["super_senior"],
        "senior": req["senior"],
        "junior": req["junior"],
        "trainee": req["trainee"],
        "total": req["total"],
    }
})

    return tasks

# ---------------- DEMO ----------------
if __name__ == "__main__":
    visit_id = int(input("Enter visit id: "))
    tasks = expand_therapies_for_visit(visit_id)
    if "error" in tasks:
        print(tasks["error"])
    else:
        print(f"Expanded {len(tasks)} tasks:")
        for t in tasks[:20]:  # show first 20
            print(t)
