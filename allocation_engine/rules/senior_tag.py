"""Special Dhara / Thakradhara senior-tag identification and daily usage count rules."""


def is_treatment_requiring_senior_tag(therapy_name):
    """
    Check if a treatment requires special senior tag handling.
    Returns True ONLY if the therapy name exactly matches one of the specified treatments.
    """
    if not therapy_name:
        return False

    special_treatments = [
        'dhara & abh(3)',
        'dhara& pizhichil (4)',
        'dhara & pizhichil (5)',
        'dhara & pizhichil (6)',
        'dhara & pizhichil (7)',
        'dhara & abyangam ( 3 t)',
        'dhara & sudhikalpana dhara (5t)',
        'dhara ( 2 t)',
        'thakradhara & abhyangam (4)',
        'thakradhara & pizichil(6)',
        'thakradhara ( 2 t)',
        'thakradhara&fbkadee kizhi (5 t)',
        'thakradhara& thakrapizhichil(7)',
    ]

    therapy_normalized = ' '.join(str(therapy_name).lower().strip().split())
    for special_treatment in special_treatments:
        special_normalized = ' '.join(special_treatment.lower().strip().split())
        if therapy_normalized == special_normalized:
            return True
    return False


def get_senior_tag_count_for_therapist(therapist, date):
    """
    Count how many special senior-tag treatments a therapist is already assigned to
    on a given date (based on TherapistBooking records with is_bathing=False, status='BOOKED').
    """
    from Patient.models import TherapistBooking

    try:
        qs = (
            TherapistBooking.objects
            .filter(therapist=therapist, date=date, status='BOOKED')
            .select_related('therapy', 'visit')
        )
    except Exception:
        return 0

    count = 0
    for tb in qs:
        if getattr(tb, 'is_bathing', False):
            continue
        name = getattr(tb.therapy, 'therapy_name', None) or getattr(tb, 'therapy_name', None)
        if not name and getattr(tb, 'visit', None) is not None:
            name = getattr(tb.visit, 'therapy_name', None)
        if is_treatment_requiring_senior_tag(name):
            count += 1
    return count
