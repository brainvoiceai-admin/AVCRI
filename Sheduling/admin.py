from django.contrib import admin
from .models import TherapyAllocation, Booking, BookingItem, BookingAssignment, PrescriptionAllocation

admin.site.register(TherapyAllocation)
admin.site.register(Booking)
admin.site.register(BookingItem)
admin.site.register(BookingAssignment)
admin.site.register(PrescriptionAllocation)
