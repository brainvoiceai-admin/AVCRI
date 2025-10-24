from django.contrib import admin
from .models import Repeated_Visitors, Therapist, TherapyDetails, PatientHistory, DailyPatientCount, TherapistLeave, TimeSlot, TreatmentRoom, RoomBooking, TherapistBooking, BookingCancellations, AllocationAttempt
# Register your models here.
admin.site.register(Repeated_Visitors)
admin.site.register(Therapist)
admin.site.register(TherapyDetails)
admin.site.register(PatientHistory)
admin.site.register(DailyPatientCount)
admin.site.register(TherapistLeave)
admin.site.register(TimeSlot)
admin.site.register(TreatmentRoom)
admin.site.register(RoomBooking)
admin.site.register(TherapistBooking)
admin.site.register(BookingCancellations)
admin.site.register(AllocationAttempt)