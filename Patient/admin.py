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
@admin.register(TreatmentRoom)
class TreatmentRoomAdmin(admin.ModelAdmin):
    list_display = ['room_no', 'tr_code', 'room_name', 'floor_master', 'is_steam_room', 'is_vamanam_room', 'is_active', 'created_at']
    list_filter = ['is_active', 'is_steam_room', 'is_vamanam_room', 'floor_master']
    list_editable = ['is_steam_room', 'is_vamanam_room', 'is_active']
    search_fields = ['room_no', 'tr_code', 'description']
admin.site.register(RoomBooking)
admin.site.register(TherapistBooking)
admin.site.register(BookingCancellations)
admin.site.register(AllocationAttempt)