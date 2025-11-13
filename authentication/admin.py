from django.contrib import admin

# Register your models here.
# app/admin.py
from django.contrib import admin
from .models import CustomUser, AuditLog, Role, Module
from django.contrib.auth.admin import UserAdmin
from .models import PatientProfile, TherapistProfile, DoctorProfile, AdminProfile, NurseProfile, StaffProfile

class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Role Info', {'fields': ('role',)}),
        ('Gender Info', {'fields': ('gender',)}),
    )

admin.site.register(CustomUser, CustomUserAdmin)
admin.site.register(AuditLog)
admin.site.register(Role)
admin.site.register(Module)
admin.site.register(PatientProfile)
admin.site.register(TherapistProfile)
admin.site.register(DoctorProfile)
admin.site.register(AdminProfile)
admin.site.register(NurseProfile)
admin.site.register(StaffProfile)