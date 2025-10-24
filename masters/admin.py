from django.contrib import admin
from .models import (
    Procured, OilClass, UsageType, PrescriptionTime, 
    PrescriptionScope, UnitNo, TherapyMaster, ItemMaster, SlotMaster,
    TherapistMaster, TherapistLeaveMaster
)

@admin.register(Procured)
class ProcuredAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    list_editable = ['is_active']
    ordering = ['name']

@admin.register(OilClass)
class OilClassAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    list_editable = ['is_active']
    ordering = ['name']

@admin.register(UsageType)
class UsageTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    list_editable = ['is_active']
    ordering = ['name']

@admin.register(PrescriptionTime)
class PrescriptionTimeAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    list_editable = ['is_active']
    ordering = ['name']

@admin.register(PrescriptionScope)
class PrescriptionScopeAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    list_editable = ['is_active']
    ordering = ['name']

@admin.register(UnitNo)
class UnitNoAdmin(admin.ModelAdmin):
    list_display = ['unit_name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['unit_name']
    list_editable = ['is_active']
    ordering = ['unit_name']

@admin.register(TherapyMaster)
class TherapyMasterAdmin(admin.ModelAdmin):
    list_display = ['therapy_code', 'therapy_name', 'therapy_group', 'total_no_of_therapist', 'is_active', 'created_at']
    list_filter = ['is_active', 'therapy_group', 'therapy_category', 'created_at']
    search_fields = ['therapy_code', 'therapy_name', 'therapy_group']
    list_editable = ['is_active']
    ordering = ['therapy_name']
    fieldsets = (
        ('Basic Information', {
            'fields': ('therapy_code', 'therapy_name', 'therapy_group', 'therapy_category')
        }),
        ('Therapy Details', {
            'fields': ('therapy_duration', 'bathing_required', 'treatment_room_required', 'cost_of_therapy')
        }),
        ('Therapist Requirements', {
            'fields': ('no_of_super_senior_therapist', 'no_of_senior_therapist', 'no_of_junior_therapist', 'no_of_trainee_therapist', 'total_no_of_therapist'),
            'description': 'Number of therapists required for this therapy'
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(ItemMaster)
class ItemMasterAdmin(admin.ModelAdmin):
    list_display = ['item_code', 'item_name', 'item_category', 'is_active', 'created_at']
    list_filter = ['is_active', 'item_category', 'created_at']
    search_fields = ['item_code', 'item_name', 'item_category']
    list_editable = ['is_active']
    ordering = ['item_name']
    fieldsets = (
        ('Basic Information', {
            'fields': ('item_code', 'item_name', 'item_category')
        }),
        ('Details', {
            'fields': ('unit_of_measure',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(SlotMaster)
class SlotMasterAdmin(admin.ModelAdmin):
    list_display = ['slot_number', 'slot_name', 'start_time', 'end_time', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['slot_name', 'slot_number']
    list_editable = ['is_active']
    ordering = ['slot_number']
    fieldsets = (
        ('Slot Information', {
            'fields': ('slot_number', 'slot_name', 'start_time', 'end_time')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(TherapistMaster)
class TherapistMasterAdmin(admin.ModelAdmin):
    list_display = ['therapist_code', 'therapist_name', 'therapist_grade', 'employee_code', 'is_bathing_therapist', 'is_active', 'created_at']
    list_filter = ['is_active', 'is_bathing_therapist', 'therapist_grade', 'created_at']
    search_fields = ['therapist_code', 'therapist_name', 'employee_code']
    list_editable = ['is_active', 'is_bathing_therapist']
    ordering = ['therapist_name']
    fieldsets = (
        ('Basic Information', {
            'fields': ('therapist_code', 'therapist_name', 'therapist_grade', 'employee_code')
        }),
        ('Therapist Details', {
            'fields': ('is_bathing_therapist',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(TherapistLeaveMaster)
class TherapistLeaveMasterAdmin(admin.ModelAdmin):
    list_display = ['therapist', 'leave_day_name', 'leave_day', 'is_active', 'created_at']
    list_filter = ['is_active', 'leave_day', 'therapist__therapist_grade', 'created_at']
    search_fields = ['therapist__therapist_name', 'therapist__therapist_code', 'leave_day_name']
    list_editable = ['is_active']
    ordering = ['therapist__therapist_name', 'leave_day']
    fieldsets = (
        ('Leave Information', {
            'fields': ('therapist', 'leave_day', 'leave_day_name')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
