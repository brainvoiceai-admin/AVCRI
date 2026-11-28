"""TherapyMaster lookup, caching, and requirement calculation helpers."""

therapy_cache = {}


def clear_therapy_cache():
    """Clear the in-memory TherapyMaster lookup cache."""
    therapy_cache.clear()


def get_therapy_details(therapy_name):
    """
    Robust therapy lookup that tolerates minor name formatting differences.
    Tries exact iexact on original name first, then whitespace-normalized match.
    """
    from masters.models import TherapyMaster

    raw = (therapy_name or "").strip()
    if not raw:
        return None

    norm_key = " ".join(raw.lower().split())

    details = (
        TherapyMaster.objects.filter(therapy_name__iexact=raw)
        .order_by("id")
        .first()
    )

    if details is None:
        try:
            candidates = TherapyMaster.objects.all()
            best = None
            for tm in candidates:
                tname = getattr(tm, "therapy_name", "") or ""
                t_norm = " ".join(tname.lower().split())
                if t_norm == norm_key:
                    best = tm
                    break
            details = best
        except Exception:
            details = None

    return details


def therapy_needs_room(allocation_or_booking):
    th_name = getattr(allocation_or_booking, 'therapy_name', None) or getattr(allocation_or_booking, 'therapy', None)
    details = get_therapy_details(th_name) if th_name else None
    if not details:
        return False
    val = getattr(details, 'treatment_room_required', '')
    return str(val).strip().lower() == 'yes'


def therapy_needs_bath(allocation_or_booking):
    if getattr(allocation_or_booking, 'bathing_therapists_count', 0) > 0:
        return True
    booking_alloc = getattr(allocation_or_booking, 'allocation', None)
    if booking_alloc and getattr(booking_alloc, 'bathing_therapists_count', 0) > 0:
        return True
    th_name = getattr(allocation_or_booking, 'therapy_name', None) or getattr(allocation_or_booking, 'therapy', None)
    details = get_therapy_details(th_name) if th_name else None
    if not details:
        return False
    val = getattr(details, 'bathing_required', '')
    return str(val).strip().lower() == 'yes'


def get_therapist_grade_name(therapist):
    """Helper function to get therapist grade name from TherapistGrade FK."""
    if not therapist:
        return ''
    if hasattr(therapist, 'therapist_grade') and therapist.therapist_grade:
        if hasattr(therapist.therapist_grade, 'name'):
            return therapist.therapist_grade.name
    return ''


def therapist_requirements(allocation_or_therapy_obj, *, default_total_if_missing=1):
    """
    Compute therapist grade & total requirements for an allocation or therapy object.

    Args:
        allocation_or_therapy_obj: TherapyAllocation, Booking, or TherapyMaster-like object.
        default_total_if_missing: Total therapists to require when TherapyMaster row is not found.
            - final_allocation uses 1 (prevents unknown therapies auto-scheduling with 0 therapists).
            - reshedule historically used 0.
    """
    name = getattr(allocation_or_therapy_obj, 'therapy_name', None)
    details = get_therapy_details(name) if name else None
    bathing_therapists_count = getattr(allocation_or_therapy_obj, 'bathing_therapists_count', 0) or 0
    if not bathing_therapists_count:
        booking_alloc = getattr(allocation_or_therapy_obj, 'allocation', None)
        if booking_alloc:
            bathing_therapists_count = getattr(booking_alloc, 'bathing_therapists_count', 0) or 0

    if not details:
        base_total = int(default_total_if_missing)
        req_total = max(base_total, bathing_therapists_count)
        return {
            "super_senior": 0,
            "senior": 0,
            "junior": 0,
            "trainee": 0,
            "total": req_total,
            "normal_total": base_total,
            "bathing_therapists_count": bathing_therapists_count,
            "therapy_code": getattr(allocation_or_therapy_obj, 'therapy_code', None),
            "therapy_category": None,
            "therapy_name": name,
        }

    base_total = int(getattr(details, 'total_no_of_therapist', 0) or 0)
    req_total = max(base_total, bathing_therapists_count)
    return {
        "super_senior": int(getattr(details, 'no_of_super_senior_therapist', 0) or 0),
        "senior": int(getattr(details, 'no_of_senior_therapist', 0) or 0),
        "junior": int(getattr(details, 'no_of_junior_therapist', 0) or 0),
        "trainee": int(getattr(details, 'no_of_trainee_therapist', 0) or 0),
        "total": req_total,
        "normal_total": base_total,
        "bathing_therapists_count": bathing_therapists_count,
        "therapy_code": getattr(details, 'therapy_code', getattr(allocation_or_therapy_obj, 'therapy_code', None)),
        "therapy_category": getattr(details, 'therapy_category', None),
        "therapy_name": getattr(details, 'therapy_name', name),
    }
