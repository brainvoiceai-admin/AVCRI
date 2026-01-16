from django.contrib import admin
from .models import (
    Procured, OilClass, UsageType, PrescriptionUsage, PrescriptionTime, 
    PrescriptionScope, UnitNo, TherapyMaster, TherapyGroup, ItemMaster, ItemGroup, SlotMaster,
    TherapistMaster, TherapistLeaveMaster, TherapistGrade, StayingRoom,
    NurseTreatmentMaster, NurseMaster
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

@admin.register(PrescriptionUsage)
class PrescriptionUsageAdmin(admin.ModelAdmin):
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

@admin.register(TherapyGroup)
class TherapyGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    list_editable = ['is_active']
    ordering = ['name']

@admin.register(TherapyMaster)
class TherapyMasterAdmin(admin.ModelAdmin):
    list_display = ['therapy_code', 'therapy_name', 'therapy_group', 'total_no_of_therapist', 'is_active', 'created_at']
    list_filter = ['is_active', 'therapy_group', 'therapy_category', 'created_at']
    search_fields = ['therapy_code', 'therapy_name', 'therapy_group__name']
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

@admin.register(ItemGroup)
class ItemGroupAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    list_editable = ['is_active']
    ordering = ['name']

@admin.register(ItemMaster)
class ItemMasterAdmin(admin.ModelAdmin):
    list_display = ['item_code', 'item_name', 'item_group', 'umo', 'procured_from', 'is_active', 'created_at']
    list_filter = ['is_active', 'item_group', 'umo', 'procured_from', 'created_at']
    search_fields = ['item_code', 'item_name', 'item_group__name', 'umo__unit_name', 'procured_from__name']
    list_editable = ['is_active']
    ordering = ['item_name']
    readonly_fields = ['item_code']
    fieldsets = (
        ('Basic Information', {
            'fields': ('item_code', 'item_name', 'item_group')
        }),
        ('Details', {
            'fields': ('umo', 'min_max', 'procured_from')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(SlotMaster)
class SlotMasterAdmin(admin.ModelAdmin):
    list_display = ['slot_number', 'slot_name', 'slot_time', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['slot_name', 'slot_number']
    list_editable = ['is_active']
    ordering = ['slot_number']
    fieldsets = (
        ('Slot Information', {
            'fields': ('slot_number', 'slot_name', 'slot_time')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(TherapistMaster)
class TherapistMasterAdmin(admin.ModelAdmin):
    list_display = ['therapist_code', 'therapist_name', 'therapist_grade', 'employee_code', 'get_gender', 'is_bathing_therapist', 'is_active', 'created_at']
    list_filter = ['is_active', 'is_bathing_therapist', 'therapist_grade', 'user__gender', 'created_at']
    search_fields = ['therapist_code', 'therapist_name', 'employee_code']
    list_editable = ['is_active', 'is_bathing_therapist']
    ordering = ['therapist_name']
    fieldsets = (
        ('Basic Information', {
            'fields': ('therapist_code', 'therapist_name', 'therapist_grade', 'employee_code')
        }),
        ('User Information', {
            'fields': ('user', 'therapist_profile'),
            'description': 'Link to user account for gender and other user details'
        }),
        ('Therapist Details', {
            'fields': ('is_bathing_therapist',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
    
    def get_gender(self, obj):
        """Display gender from associated user"""
        if obj.user:
            return obj.user.gender
        return 'No User'
    get_gender.short_description = 'Gender'
    get_gender.admin_order_field = 'user__gender'

@admin.register(TherapistGrade)
class TherapistGradeAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_order', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name']
    list_editable = ['display_order', 'is_active']
    ordering = ['display_order', 'name']
    fieldsets = (
        ('Grade Information', {
            'fields': ('name', 'display_order')
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

@admin.register(StayingRoom)
class StayingRoomAdmin(admin.ModelAdmin):
    list_display = ['number', 'room_no', 'room_desc', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['number', 'room_no', 'room_desc']
    list_editable = ['is_active']
    ordering = ['number']
    fieldsets = (
        ('Room Information', {
            'fields': ('number', 'room_no', 'room_desc')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(NurseTreatmentMaster)
class NurseTreatmentMasterAdmin(admin.ModelAdmin):
    list_display = ['treatment_code', 'name', 'number_of_nurse_required', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['treatment_code', 'name']
    list_editable = ['is_active']
    ordering = ['treatment_code']
    fieldsets = (
        ('Treatment Information', {
            'fields': ('treatment_code', 'name', 'number_of_nurse_required')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )

@admin.register(NurseMaster)
class NurseMasterAdmin(admin.ModelAdmin):
    list_display = ['nurse_code', 'nurse_name', 'designation', 'is_active', 'created_at', 'updated_at']
    list_filter = ['is_active', 'designation', 'created_at']
    search_fields = ['nurse_code', 'nurse_name', 'designation']
    list_editable = ['is_active']
    ordering = ['nurse_code']
    fieldsets = (
        ('Nurse Information', {
            'fields': ('nurse_code', 'nurse_name', 'designation')
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
    )
