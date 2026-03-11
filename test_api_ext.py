import os
import sys
import django
import json

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings") # Adjust if settings is elsewhere
django.setup()

from Sheduling.models import Booking
from Sheduling.views import get_therapy_data_api

booking = Booking.objects.filter(allocation__patient__id=692, date='2026-03-11').first()
if not booking:
    print("Booking not found")
    sys.exit(0)

print(f"Booking {booking.id} assignments: {booking.assignments.count()}")

# Simulate get_therapy_data_api extraction logic
therapist_codes = [a.therapist.therapist_code for a in booking.assignments.all()]
print(f"Codes from assignments: {therapist_codes}")

# What if therapist_codes is empty? (fallback)
if not therapist_codes:
    from Patient.models import TherapistBooking
    tb_fallback = TherapistBooking.objects.filter(
        visit=booking.allocation,
        date=booking.date,
        time_slot=booking.timeslot,
        status='BOOKED'
    ).select_related('therapist').order_by('therapist_id')
    therapist_codes = [tb.therapist.therapist_code for tb in tb_fallback if tb.therapist]
    print(f"Codes from fallback: {therapist_codes}")

