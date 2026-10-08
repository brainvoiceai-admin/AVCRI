from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import (
    TherapyAllocation, Booking, BookingItem, BookingAssignment, BookingNurseAssignment,
    PrescriptionAllocation, PatientSnapshot, CancellationRequest,
    NotificationQueue, TherapyNotification, AuditLog, AllocationChange,
    PrescriptionNotification, PrescriptionChange,
    PrescriptionScheduling, PrescriptionChangeLog, PrescriptionItem, PrescriptionDispatch,
    HelpingTherapistAllocationLog
)

@admin.register(PatientSnapshot)
class PatientSnapshotAdmin(admin.ModelAdmin):
    list_display = ['pat_reg_no', 'pat_name', 'pat_age', 'pat_sex', 'is_op', 'created_at']
    list_filter = ['pat_sex', 'created_at']
    search_fields = ['pat_reg_no', 'pat_name']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']

@admin.register(TherapyAllocation)
class TherapyAllocationAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'patient_info', 'therapy_name', 'status_badge', 
        'date_range', 'room_info', 'timeslot_info', 'allocated_by', 'created_at'
    ]
    list_filter = ['status', 'therapy_name', 'from_date', 'allocated_by', 'created_at']
    search_fields = ['patient__pat_name', 'patient__pat_reg_no', 'therapy_name']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    raw_id_fields = ['patient', 'room', 'timeslot', 'allocated_by']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('patient', 'therapy_code', 'therapy_name', 'ext_int')
        }),
        ('Scheduling', {
            'fields': ('timeslot', 'room', 'from_date', 'to_date', 'days')
        }),
        ('Therapy Details', {
            'fields': ('items_groups', 'oil_class', 'usage', 'procured_from', 'required_therapist_roles')
        }),
        ('Status & Management', {
            'fields': ('status', 'allocated_by', 'locked', 'notes')
        }),
        ('Cancellation', {
            'fields': ('cancelled_by', 'cancelled_at', 'cancellation_reason', 'cancelled_date_from', 'cancelled_date_to'),
            'classes': ('collapse',)
        }),
        ('Resumption', {
            'fields': ('resumed_by', 'resumed_at'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def patient_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{}</small>',
            obj.patient.pat_name or '—',
            obj.patient.pat_reg_no
        )
    patient_info.short_description = 'Patient'
    
    def status_badge(self, obj):
        colors = {
            'draft': '#f59e0b',
            'allocated': '#10b981', 
            'cancelled': '#6b7280',
            'failed': '#ef4444'
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def date_range(self, obj):
        return format_html(
            '{} to {}<br><small>{} days</small>',
            obj.from_date, obj.to_date, obj.days
        )
    date_range.short_description = 'Date Range'
    
    def room_info(self, obj):
        return obj.room.room_no if obj.room else '—'
    room_info.short_description = 'Room'
    
    def timeslot_info(self, obj):
        return obj.timeslot.slot_time.strftime('%H:%M') if obj.timeslot else '—'
    timeslot_info.short_description = 'Time Slot'

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'allocation_info', 'date', 'timeslot_info', 'room_info', 'status', 'created_at']
    list_filter = ['status', 'date', 'timeslot', 'room', 'created_at']
    search_fields = ['allocation__patient__pat_name', 'allocation__patient__pat_reg_no', 'allocation__therapy_name']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-date', '-created_at']
    raw_id_fields = ['allocation', 'timeslot', 'room']
    
    def allocation_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{} - {}</small>',
            obj.allocation.therapy_name,
            obj.allocation.patient.pat_name,
            obj.allocation.patient.pat_reg_no
        )
    allocation_info.short_description = 'Therapy & Patient'
    
    def timeslot_info(self, obj):
        return obj.timeslot.slot_time.strftime('%H:%M') if obj.timeslot else '—'
    timeslot_info.short_description = 'Time Slot'
    
    def room_info(self, obj):
        return obj.room.room_no if obj.room else '—'
    room_info.short_description = 'Room'

@admin.register(BookingItem)
class BookingItemAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking_info', 'item_code', 'item_name', 'dosage', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['item_code', 'item_name', 'booking__allocation__patient__pat_name']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    raw_id_fields = ['booking']
    
    def booking_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{} - {}</small>',
            obj.booking.allocation.therapy_name,
            obj.booking.allocation.patient.pat_name,
            obj.booking.date
        )
    booking_info.short_description = 'Booking'

@admin.register(BookingAssignment)
class BookingAssignmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking_info', 'therapist_info', 'role', 'assigned_for', 'status', 'assigned_at']
    list_filter = ['status', 'assigned_for', 'role', 'assigned_at']
    search_fields = ['therapist__therapist_name', 'therapist__therapist_code', 'booking__allocation__patient__pat_name']
    readonly_fields = ['assigned_at', 'released_at']
    ordering = ['-assigned_at']
    raw_id_fields = ['booking', 'booking_item', 'therapist', 'booking_timeslot', 'released_by']
    
    def booking_info(self, obj):
        if obj.booking:
            return format_html(
                '<strong>{}</strong><br><small>{} - {}</small>',
                obj.booking.allocation.therapy_name if obj.booking.allocation else 'N/A',
                obj.booking.allocation.patient.pat_name if obj.booking.allocation else 'N/A',
                obj.booking.date
            )
        return 'N/A'
    booking_info.short_description = 'Booking'
    
    def therapist_info(self, obj):
        if obj.therapist:
            return format_html(
                '<strong>{}</strong><br><small>{}</small>',
                obj.therapist.therapist_name or 'N/A',
                obj.therapist.therapist_code or 'N/A'
            )
        return 'N/A'
    therapist_info.short_description = 'Therapist'

@admin.register(BookingNurseAssignment)
class BookingNurseAssignmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'booking_info', 'nurse_info', 'status', 'assigned_at']
    list_filter = ['status', 'assigned_at']
    search_fields = ['nurse__nurse_name', 'nurse__nurse_code', 'booking__allocation__patient__pat_name']
    readonly_fields = ['assigned_at', 'released_at']
    ordering = ['-assigned_at']
    
    def booking_info(self, obj):
        if obj.booking:
            return format_html(
                '<a href="{}">Booking #{}</a> - {}',
                reverse('admin:Sheduling_booking_change', args=[obj.booking.pk]),
                obj.booking.pk,
                obj.booking.allocation.therapy_name if obj.booking.allocation else 'N/A'
            )
        return 'N/A'
    booking_info.short_description = 'Booking'
    
    def nurse_info(self, obj):
        if obj.nurse:
            return f"{obj.nurse.nurse_name} ({obj.nurse.nurse_code})"
        return 'N/A'
    nurse_info.short_description = 'Nurse'
    raw_id_fields = ['booking', 'nurse', 'booking_timeslot', 'released_by']

@admin.register(PrescriptionAllocation)
class PrescriptionAllocationAdmin(admin.ModelAdmin):
    list_display = ['id', 'patient_info', 'prescription_name', 'status_badge', 'date_range', 'allocated_by', 'created_at']
    list_filter = ['status', 'from_date', 'allocated_by', 'created_at']
    search_fields = ['patient__pat_name', 'patient__pat_reg_no', 'prescription_name']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    raw_id_fields = ['patient', 'allocated_by']
    
    def patient_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{}</small>',
            obj.patient.pat_name or '—',
            obj.patient.pat_reg_no
        )
    patient_info.short_description = 'Patient'
    
    def status_badge(self, obj):
        colors = {
            'draft': '#f59e0b',
            'active': '#10b981',
            'cancelled': '#6b7280',
            'failed': '#ef4444'
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def date_range(self, obj):
        return format_html(
            '{} to {}<br><small>{} days</small>',
            obj.from_date, obj.to_date, obj.days
        )
    date_range.short_description = 'Date Range'

@admin.register(CancellationRequest)
class CancellationRequestAdmin(admin.ModelAdmin):
    list_display = ['id', 'allocation_info', 'date_range', 'status', 'requested_by', 'created_at']
    list_filter = ['status', 'from_date', 'to_date', 'created_at']
    search_fields = ['allocation__patient__pat_name', 'allocation__therapy_name']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    raw_id_fields = ['allocation', 'requested_by', 'admin_action_by']
    
    def allocation_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{} - {}</small>',
            obj.allocation.therapy_name,
            obj.allocation.patient.pat_name,
            obj.allocation.patient.pat_reg_no
        )
    allocation_info.short_description = 'Therapy & Patient'
    
    def date_range(self, obj):
        return f"{obj.from_date} to {obj.to_date}"
    date_range.short_description = 'Date Range'

@admin.register(NotificationQueue)
class NotificationQueueAdmin(admin.ModelAdmin):
    list_display = ['id', 'target_type', 'target_identifier', 'channel', 'status', 'attempts', 'created_at']
    list_filter = ['target_type', 'channel', 'status', 'created_at']
    search_fields = ['target_identifier']
    readonly_fields = ['created_at', 'last_attempt_at']
    ordering = ['-created_at']

@admin.register(TherapyNotification)
class TherapyNotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'allocation_info', 'notification_type', 'title', 'priority', 'is_read', 'is_sent', 'created_at']
    list_filter = ['notification_type', 'priority', 'is_read', 'is_sent', 'created_at']
    search_fields = ['title', 'message', 'allocation__patient__pat_name']
    readonly_fields = ['created_at', 'sent_at']
    ordering = ['-created_at']
    raw_id_fields = ['therapy_allocation', 'created_by']
    
    def allocation_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{} - {}</small>',
            obj.therapy_allocation.therapy_name,
            obj.therapy_allocation.patient.pat_name,
            obj.therapy_allocation.patient.pat_reg_no
        )
    allocation_info.short_description = 'Therapy & Patient'

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'action', 'obj_type', 'obj_id', 'created_at']
    list_filter = ['action', 'obj_type', 'created_at']
    search_fields = ['action', 'obj_type', 'obj_id', 'user__username']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    raw_id_fields = ['user']

@admin.register(AllocationChange)
class AllocationChangeAdmin(admin.ModelAdmin):
    list_display = ['id', 'allocation_info', 'change_type', 'changed_by', 'created_at']
    list_filter = ['change_type', 'created_at']
    search_fields = ['allocation__patient__pat_name', 'allocation__therapy_name']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    raw_id_fields = ['allocation', 'changed_by']
    
    def allocation_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{} - {}</small>',
            obj.allocation.therapy_name,
            obj.allocation.patient.pat_name,
            obj.allocation.patient.pat_reg_no
        )
    allocation_info.short_description = 'Therapy & Patient'

@admin.register(PrescriptionNotification)
class PrescriptionNotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'allocation_info', 'notification_type', 'title', 'priority', 'is_read', 'is_sent', 'created_at']
    list_filter = ['notification_type', 'priority', 'is_read', 'is_sent', 'created_at']
    search_fields = ['title', 'message', 'prescription_allocation__patient__pat_name']
    readonly_fields = ['created_at', 'sent_at']
    ordering = ['-created_at']
    raw_id_fields = ['prescription_allocation', 'created_by']
    
    def allocation_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{} - {}</small>',
            obj.prescription_allocation.prescription_name,
            obj.prescription_allocation.patient.pat_name,
            obj.prescription_allocation.patient.pat_reg_no
        )
    allocation_info.short_description = 'Prescription & Patient'

@admin.register(PrescriptionChange)
class PrescriptionChangeAdmin(admin.ModelAdmin):
    list_display = ['id', 'allocation_info', 'change_type', 'changed_by', 'created_at']
    list_filter = ['change_type', 'created_at']
    search_fields = ['prescription_allocation__patient__pat_name', 'prescription_allocation__prescription_name']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    raw_id_fields = ['prescription_allocation', 'changed_by']
    
    def allocation_info(self, obj):
        return format_html(
            '<strong>{}</strong><br><small>{} - {}</small>',
            obj.prescription_allocation.prescription_name,
            obj.prescription_allocation.patient.pat_name,
            obj.prescription_allocation.patient.pat_reg_no
        )
    allocation_info.short_description = 'Prescription & Patient'

@admin.register(PrescriptionScheduling)
class PrescriptionSchedulingAdmin(admin.ModelAdmin):
    list_display = ['patient', 'prescription_date', 'doctor', 'status', 'sent_to', 'dispatched_at', 'created_at']
    list_filter = ['status', 'prescription_date', 'sent_to', 'created_at']
    search_fields = ['patient__pat_name', 'patient__pat_reg_no', 'doctor__username']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-prescription_date', '-created_at']
    raw_id_fields = ['patient', 'doctor']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('patient', 'doctor')

@admin.register(PrescriptionChangeLog)
class PrescriptionChangeLogAdmin(admin.ModelAdmin):
    list_display = ['patient', 'prescription_date', 'action', 'changed_by', 'timestamp']
    list_filter = ['action', 'prescription_date', 'timestamp']
    search_fields = ['patient__pat_name', 'patient__pat_reg_no', 'changed_by__username']
    readonly_fields = ['timestamp']
    ordering = ['-timestamp']
    raw_id_fields = ['patient', 'changed_by']

@admin.register(PrescriptionItem)
class PrescriptionItemAdmin(admin.ModelAdmin):
    list_display = ['prescription_scheduling', 'item_name', 'dose', 'quantity', 'time', 'created_at']
    list_filter = ['time', 'created_at']
    search_fields = ['item_name', 'prescription_scheduling__patient__pat_name']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    raw_id_fields = ['prescription_scheduling']

@admin.register(PrescriptionDispatch)
class PrescriptionDispatchAdmin(admin.ModelAdmin):
    list_display = ['prescription_scheduling', 'department', 'dispatched_by', 'dispatched_at']
    list_filter = ['department', 'dispatched_at']
    search_fields = ['prescription_scheduling__patient__pat_name', 'department']
    readonly_fields = ['dispatched_at']
    ordering = ['-dispatched_at']
    raw_id_fields = ['prescription_scheduling', 'dispatched_by']

@admin.register(HelpingTherapistAllocationLog)
class HelpingTherapistAllocationLogAdmin(admin.ModelAdmin):
    list_display = ['patient_id', 'helping_therapist', 'date', 'time_slot', 'therapy_name', 'shortage_condition', 'allocated_at']
    list_filter = ['date', 'is_supporting_backup', 'allocated_at']
    search_fields = ['patient_id', 'helping_therapist__therapist_code', 'helping_therapist__therapist_name', 'therapy_name', 'reason_for_fallback']
    readonly_fields = ['allocated_at']
    ordering = ['-allocated_at']

# Customize admin site
admin.site.site_header = "AVCRI Therapy Management System"
admin.site.site_title = "AVCRI Admin"
admin.site.index_title = "Therapy Scheduling & Management"
    