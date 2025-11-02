from django.conf import settings
from django.db import models
from django.utils import timezone
from Patient.models import TimeSlot,TreatmentRoom,Therapist
from django.utils.translation import gettext_lazy as _
# -------------------------
# Local patient snapshot
# -------------------------
class PatientSnapshot(models.Model):
    pat_reg_no = models.CharField(max_length=50, unique=True)  # store as string (OP/IP)
    pat_name = models.CharField(max_length=255, blank=True, null=True)
    pat_age = models.CharField(max_length=20, blank=True, null=True)
    pat_sex = models.CharField(max_length=10, blank=True, null=True)
    pat_room_no = models.CharField(max_length=50, blank=True, null=True)
    pat_ref_id = models.CharField(max_length=100, blank=True, null=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_op(self):
        digits = ''.join(ch for ch in str(self.pat_reg_no or '') if ch.isdigit())
        return len(digits) == 5

    def __str__(self):
        return f"{self.pat_reg_no} - {self.pat_name or '—'}"


# -----------------------------------------------------------------------------
# Core scheduling models
# -----------------------------------------------------------------------------
class TherapyAllocation(models.Model):
    """
    Header: one logical therapy prescription / allocation for a patient.
    items_groups stores the original prescription (snapshot).
    required_therapist_roles example: [{"role":"senior","count":1},{"role":"junior","count":3}]
    """
    patient = models.ForeignKey(PatientSnapshot, on_delete=models.CASCADE, related_name='allocations')
    therapy_code = models.CharField(max_length=50)
    therapy_name = models.CharField(max_length=255)
    ext_int = models.CharField(max_length=50, blank=True)
    timeslot = models.ForeignKey('masters.SlotMaster', null=True, blank=True, on_delete=models.SET_NULL)
    room = models.ForeignKey(TreatmentRoom, null=True, blank=True, on_delete=models.SET_NULL)
    items_groups = models.JSONField(help_text="List of item groups (snapshot)", default=list)
    oil_class = models.CharField(max_length=100, blank=True)
    usage = models.CharField(max_length=100, blank=True)
    procured_from = models.CharField(max_length=200, blank=True)
    from_date = models.DateField()
    to_date = models.DateField()
    days = models.PositiveIntegerField()
    required_therapist_roles = models.JSONField(default=list, blank=True)
    allocated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='allocations_created')
    locked = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    
    # Status and cancellation fields
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('allocated', 'Allocated'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='allocations_cancelled')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, help_text="Mandatory when cancelling")
    cancelled_date_from = models.DateField(null=True, blank=True, help_text="Cancellation date range start")
    cancelled_date_to = models.DateField(null=True, blank=True, help_text="Cancellation date range end")
    resumed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='allocations_resumed')
    resumed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['patient','from_date','to_date']),
            models.Index(fields=['from_date', 'to_date']),
        ]

    def __str__(self):
        return f"Alloc #{self.pk} – {self.therapy_name} for {self.patient.pat_reg_no}"


class Booking(models.Model):
    """
    One booking per allocation per date.
    UniqueConstraint on (room, date, timeslot) prevents double-booking of room (capacity=1).
    If a room supports >1 concurrent bookings, remove the constraint and handle capacity in allocation logic.
    """
    allocation = models.ForeignKey(TherapyAllocation, on_delete=models.CASCADE, related_name='bookings')
    date = models.DateField(db_index=True)
    timeslot = models.ForeignKey('masters.SlotMaster', null=True, blank=True, on_delete=models.SET_NULL)
    room = models.ForeignKey(TreatmentRoom, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=30, default='draft')  # draft / scheduled / partially_cancelled / cancelled / completed
    therapist_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['room','date','timeslot'], name='ux_booking_room_date_timeslot')
        ]
        indexes = [
            models.Index(fields=['allocation','date']),
            models.Index(fields=['date','timeslot']),
        ]

    def __str__(self):
        room_str = self.room.room_no if self.room else '—'
        return f"Booking {self.pk} – {self.allocation.therapy_name} on {self.date} (room: {room_str})"


class BookingItem(models.Model):
    """
    BookingItem is the per-date, per-item row derived from items_groups.
    This is the unit for procurement and completion.
    """
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='items')
    item_code = models.CharField(max_length=50)
    item_name = models.CharField(max_length=255)
    dosage = models.CharField(max_length=100, blank=True)
    uno = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=30, default='scheduled')  # scheduled / cancelled / completed
    cancel_reason = models.TextField(blank=True)
    cancel_requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['booking','item_code']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.item_name} ({self.item_code}) on {self.booking.date}"


class BookingAssignment(models.Model):
    """
    Assign therapists to bookings or booking_items.
    We denormalize booking_date and booking_timeslot for a robust unique constraint that prevents
    assigning the same therapist to two bookings at the same date+timeslot.
    """
    ASSIGNED_FOR_CHOICES = [('booking','booking'), ('booking_item','booking_item')]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='assignments')
    booking_item = models.ForeignKey(BookingItem, null=True, blank=True, on_delete=models.CASCADE, related_name='assignments')
    therapist = models.ForeignKey(Therapist, on_delete=models.PROTECT)   # references therapist.therapist_code PK
    role = models.CharField(max_length=50, blank=True)
    assigned_for = models.CharField(max_length=20, choices=ASSIGNED_FOR_CHOICES, default='booking')
    status = models.CharField(max_length=20, default='assigned')  # assigned | released
    assigned_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    # denormalized snapshot of booking's date/timeslot for uniqueness checks
    booking_date = models.DateField(db_index=True, null=True, blank=True)
    booking_timeslot = models.ForeignKey('masters.SlotMaster', null=True, blank=True, on_delete=models.SET_NULL, related_name='booking_assignments')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['therapist','booking_date','booking_timeslot'], name='ux_assignment_therapist_date_timeslot')
        ]
        indexes = [
            models.Index(fields=['therapist','status']),
            models.Index(fields=['booking','therapist']),
        ]

    def save(self, *args, **kwargs):
        # keep denormalized booking_date/booking_timeslot in sync with booking
        if self.booking:
            self.booking_date = self.booking.date
            if not self.booking_timeslot:
                self.booking_timeslot = self.booking.timeslot
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.therapist} assigned to {self.booking} ({self.assigned_for})"


class CancellationRequest(models.Model):
    """
    CancellationRequest may target a date range and (optionally) a list of booking_item ids.
    If 'items' is empty, treat it as request for full-date cancellation (allocation-level for dates).
    """
    allocation = models.ForeignKey(TherapyAllocation, on_delete=models.CASCADE, related_name='cancel_requests')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    from_date = models.DateField()
    to_date = models.DateField()
    items = models.JSONField(default=list, blank=True, help_text='List of booking_item ids or {date,item_code} entries')
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, default='pending')  # pending / approved / rejected
    admin_action_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, related_name='cancel_requests_admin', on_delete=models.SET_NULL)
    admin_action_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['allocation','status']),
            models.Index(fields=['from_date','to_date']),
        ]

    def __str__(self):
        return f"CancelRequest #{self.pk} alloc {self.allocation_id} ({self.from_date}→{self.to_date})"


class NotificationQueue(models.Model):
    """
    Persistent queue for notifications. A background worker should process these rows.
    """
    target_type = models.CharField(max_length=50)   # e.g., 'pharmacy', 'kashayam_room', 'therapist', 'patient', 'admin'
    target_identifier = models.CharField(max_length=255, blank=True)
    channel = models.CharField(max_length=20, default='webhook')  # 'sms','webhook','email'
    payload = models.JSONField()
    status = models.CharField(max_length=20, default='queued')  # queued | sent | failed
    attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['status','target_type']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Notification {self.pk} -> {self.target_type} ({self.status})"

class TherapyNotification(models.Model):
    """Notifications for therapy-related actions"""
    NOTIFICATION_TYPES = [
        ('therapy_allocated', 'Therapy Allocated'),
        ('therapy_cancelled', 'Therapy Cancelled'),
        ('therapy_resumed', 'Therapy Resumed'),
        ('therapy_updated', 'Therapy Updated'),
        ('item_removed', 'Item Removed'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    therapy_allocation = models.ForeignKey(TherapyAllocation, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    
    # Recipients
    target_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='therapy_notifications', blank=True)
    target_roles = models.JSONField(default=list, help_text="List of roles to notify")
    
    # Status
    is_read = models.BooleanField(default=False)
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_therapy_notifications')
    created_at = models.DateTimeField(auto_now_add=True)
    additional_data = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['notification_type', 'is_read']),
            models.Index(fields=['priority', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_notification_type_display()} - {self.title}"
    
    def mark_as_read(self, user):
        """Mark notification as read for a specific user"""
        self.is_read = True
        self.save()
    
    def send_to_roles(self, roles):
        """Send notification to users with specific roles - COMMENTED OUT DUE TO WEBSOCKET ERRORS"""
        # COMMENTED OUT DUE TO WEBSOCKET ERRORS
        # from authentication.models import CustomUser
        # target_users = CustomUser.objects.filter(role__in=roles)
        # self.target_users.set(target_users)
        # self.target_roles = roles
        # self.save()
        pass


class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=200)  # e.g., 'allocate_therapy', 'update_allocation', 'request_cancel', 'approve_cancel'
    obj_type = models.CharField(max_length=100, null=True, blank=True)
    obj_id = models.CharField(max_length=200, null=True, blank=True)
    data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['action','created_at']),
        ]

    def __str__(self):
        return f"Audit {self.action} by {self.user} at {self.created_at}"


class AllocationChange(models.Model):
    allocation = models.ForeignKey(TherapyAllocation, on_delete=models.CASCADE, related_name='changes')
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    change_type = models.CharField(max_length=100)  # e.g., 'edit_items', 'change_slot', 'extend_dates'
    diff = models.JSONField(null=True, blank=True)  # {added:[], removed:[], updated:[]}
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['allocation','created_at']),
        ]

    def __str__(self):
        return f"Change #{self.pk} for alloc {self.allocation_id} by {self.changed_by}"


# -----------------------------------------------------------------------------
# Prescription models (similar to therapy)
# -----------------------------------------------------------------------------
class PrescriptionAllocation(models.Model):
    """
    Header: one logical prescription allocation for a patient.
    items_groups stores the original prescription (snapshot).
    """
    patient = models.ForeignKey(PatientSnapshot, on_delete=models.CASCADE, related_name='prescription_allocations')
    prescription_name = models.CharField(max_length=255)
    items_groups = models.JSONField(help_text="List of item groups (snapshot)", default=list)
    procured_from = models.CharField(max_length=200, blank=True)
    from_date = models.DateField()
    to_date = models.DateField()
    days = models.PositiveIntegerField()
    allocated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='prescription_allocations_created')
    locked = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    
    # Status and cancellation fields
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='prescription_allocations_cancelled')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True, help_text="Mandatory when cancelling")
    cancelled_date_from = models.DateField(null=True, blank=True, help_text="Cancellation date range start")
    cancelled_date_to = models.DateField(null=True, blank=True, help_text="Cancellation date range end")
    resumed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='prescription_allocations_resumed')
    resumed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['patient','from_date','to_date']),
            models.Index(fields=['from_date', 'to_date']),
        ]

    def __str__(self):
        return f"Prescription #{self.pk} – {self.prescription_name} for {self.patient.pat_reg_no}"


class PrescriptionNotification(models.Model):
    """Notifications for prescription-related actions"""
    NOTIFICATION_TYPES = [
        ('prescription_allocated', 'Prescription Allocated'),
        ('prescription_cancelled', 'Prescription Cancelled'),
        ('prescription_resumed', 'Prescription Resumed'),
        ('prescription_updated', 'Prescription Updated'),
        ('item_removed', 'Item Removed'),
    ]
    
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]
    
    prescription_allocation = models.ForeignKey(PrescriptionAllocation, on_delete=models.CASCADE, related_name='notifications')
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    title = models.CharField(max_length=200)
    message = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    
    # Recipients
    target_users = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name='prescription_notifications', blank=True)
    target_roles = models.JSONField(default=list, help_text="List of roles to notify")
    
    # Status
    is_read = models.BooleanField(default=False)
    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_prescription_notifications')
    created_at = models.DateTimeField(auto_now_add=True)
    additional_data = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['notification_type', 'is_read']),
            models.Index(fields=['priority', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.get_notification_type_display()} - {self.title}"
    
    def mark_as_read(self, user):
        """Mark notification as read for a specific user"""
        self.is_read = True
        self.save()
    
    def send_to_roles(self, roles):
        """Send notification to users with specific roles - COMMENTED OUT DUE TO WEBSOCKET ERRORS"""
        # COMMENTED OUT DUE TO WEBSOCKET ERRORS
        # from authentication.models import CustomUser
        # target_users = CustomUser.objects.filter(role__in=roles)
        # self.target_users.set(target_users)
        # self.target_roles = roles
        # self.save()
        pass


class PrescriptionChange(models.Model):
    prescription_allocation = models.ForeignKey(PrescriptionAllocation, on_delete=models.CASCADE, related_name='changes')
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    change_type = models.CharField(max_length=100)  # e.g., 'edit_items', 'change_dates', 'cancel', 'resume'
    diff = models.JSONField(null=True, blank=True)  # {added:[], removed:[], updated:[]}
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['prescription_allocation','created_at']),
        ]

    def __str__(self):
        return f"Change #{self.pk} for prescription {self.prescription_allocation_id} by {self.changed_by}"


# -----------------------------------------------------------------------------
# New Prescription Scheduling Models
# -----------------------------------------------------------------------------
class PrescriptionScheduling(models.Model):
    """Model to track prescription scheduling status"""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('dispatched', 'Dispatched'),
    ]
    
    patient = models.ForeignKey(PatientSnapshot, on_delete=models.CASCADE, related_name='prescription_scheduling')
    prescription_date = models.DateField()
    doctor = models.ForeignKey('authentication.CustomUser', on_delete=models.CASCADE, related_name='prescribed_prescriptions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    sent_to = models.CharField(max_length=100, blank=True, null=True)  # IP Pharmacy, Kashaya Room, etc.
    dispatched_from = models.CharField(max_length=100, blank=True, null=True)
    dispatched_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['patient', 'prescription_date']
        verbose_name = 'Prescription Scheduling'
        verbose_name_plural = 'Prescription Scheduling'

    def __str__(self):
        return f"{self.patient.pat_name} - {self.prescription_date} ({self.status})"

class PrescriptionChangeLog(models.Model):
    """Model to track all changes to prescriptions"""
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('status_change', 'Status Change'),
    ]
    
    patient = models.ForeignKey(PatientSnapshot, on_delete=models.CASCADE, related_name='prescription_changes')
    prescription_date = models.DateField()
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    changed_by = models.ForeignKey('authentication.CustomUser', on_delete=models.CASCADE, related_name='prescription_changes_made')
    before_values = models.JSONField(blank=True, null=True)
    after_values = models.JSONField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    description = models.TextField(blank=True, null=True)
    
    class Meta:
        verbose_name = 'Prescription Change Log'
        verbose_name_plural = 'Prescription Change Logs'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.patient.pat_name} - {self.action} - {self.timestamp}"

class PrescriptionItem(models.Model):
    """Model to store individual prescription items"""
    prescription_scheduling = models.ForeignKey(PrescriptionScheduling, on_delete=models.CASCADE, related_name='items')
    item_name = models.CharField(max_length=200)
    dose = models.CharField(max_length=100)
    quantity = models.IntegerField()
    time = models.CharField(max_length=50)  # M, ABF, BL, AL, E, AD, BT, PRN
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Prescription Item'
        verbose_name_plural = 'Prescription Items'

    def __str__(self):
        return f"{self.item_name} - {self.dose} x{self.quantity}"

class PrescriptionDispatch(models.Model):
    """Model to track prescription dispatch to procurement departments"""
    prescription_scheduling = models.ForeignKey(PrescriptionScheduling, on_delete=models.CASCADE, related_name='dispatches')
    department = models.CharField(max_length=100)  # IP Pharmacy, Kashaya Room, etc.
    dispatched_at = models.DateTimeField(auto_now_add=True)
    dispatched_by = models.ForeignKey('authentication.CustomUser', on_delete=models.CASCADE, related_name='dispatched_prescriptions')
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        verbose_name = 'Prescription Dispatch'
        verbose_name_plural = 'Prescription Dispatches'
    
    def __str__(self):
        return f"{self.prescription_scheduling.patient.pat_name} - {self.department} - {self.dispatched_at}"


# -----------------------------------------------------------------------------
# Final Schedule Run marker (per-date)
# -----------------------------------------------------------------------------
class FinalScheduleRun(models.Model):
    class Status(models.TextChoices):
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")

    run_date = models.DateField(unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCESS)
    ran_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    ran_at = models.DateTimeField(auto_now_add=True)
    message = models.TextField(blank=True)
    stats = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-run_date"]
        verbose_name = "Final Schedule Run"
        verbose_name_plural = "Final Schedule Runs"

    def __str__(self) -> str:
        return f"FinalScheduleRun {self.run_date} ({self.status})"