from django.conf import settings
from django.db import models
from django.utils import timezone
from Patient.models import TimeSlot,TreatmentRoom,Therapist
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
    timeslot = models.ForeignKey(TimeSlot, null=True, blank=True, on_delete=models.SET_NULL)
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
    timeslot = models.ForeignKey(TimeSlot, null=True, blank=True, on_delete=models.SET_NULL)
    room = models.ForeignKey(TreatmentRoom, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=30, default='scheduled')  # scheduled / partially_cancelled / cancelled / completed
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
    booking_timeslot = models.ForeignKey(TimeSlot, null=True, blank=True, on_delete=models.SET_NULL, related_name='booking_assignments')

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

