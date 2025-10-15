# models.py
from django.db import models


class Repeated_Visitors(models.Model):
    register_number = models.IntegerField(primary_key=True)  # unique identifier
    patient_name = models.CharField(max_length=255)
    total_visits = models.IntegerField()
    is_vip = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.patient_name} ({self.register_number})"
    




class Therapist(models.Model):
    therapist_code = models.CharField(max_length=20, primary_key=True)
    therapist_name = models.CharField(max_length=255)
    therapist_grade = models.CharField(max_length=100)
    is_bathing_therapist = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.therapist_name} ({self.therapist_code})"





class TherapyDetails(models.Model):
    therapy_code = models.CharField(max_length=20, primary_key=True)
    therapy_name = models.CharField(max_length=255)
    therapy_group = models.CharField(max_length=100, null=True, blank=True)
    therapy_category = models.CharField(max_length=100, null=True, blank=True)
    therapy_duration = models.CharField(max_length=50, null=True, blank=True)
    bathing_required = models.CharField(max_length=10, null=True, blank=True)
    treatment_room_required = models.CharField(max_length=10, null=True, blank=True)
    cost_of_therapy = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    

    no_of_super_senior_therapist = models.IntegerField(default=0)
    no_of_senior_therapist = models.IntegerField(default=0)
    no_of_junior_therapist = models.IntegerField(default=0)
    no_of_trainee_therapist = models.IntegerField(default=0)
    total_no_of_therapist = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.therapy_code} - {self.therapy_name}"



class PatientHistory(models.Model):
    id = models.AutoField(primary_key=True)
    preg_no = models.CharField(max_length=50, db_index=True)  # Patient Reg No
    pat_name = models.CharField(max_length=200)
    date = models.DateField()
    therapist_name = models.CharField(max_length=200)
    therapist_code = models.CharField(max_length=100)
    room_no = models.CharField(max_length=50, null=True, blank=True)
    treatment = models.CharField(max_length=200)
    t_room = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f"{self.preg_no} - {self.pat_name} ({self.date})"



#Model for forcasting the demand
class DailyPatientCount(models.Model):
    date = models.DateField(unique=True)
    patient_count = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)


#models supporting allocation
class TherapistLeave(models.Model):
    WEEK_DAYS = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    therapist = models.ForeignKey(Therapist, on_delete=models.CASCADE)
    leave_day = models.IntegerField(choices=WEEK_DAYS)  # store integer for logic
    leave_day_name = models.CharField(max_length=10, blank=True)  # optional readable name

    def save(self, *args, **kwargs):
        # auto-fill day name based on leave_day
        self.leave_day_name = dict(self.WEEK_DAYS).get(self.leave_day, "")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.therapist.therapist_name} - {self.leave_day_name}"


class TimeSlot(models.Model):
    slot_number = models.IntegerField(primary_key=True)  # 1 to 7
    start_time = models.TimeField()
    end_time = models.TimeField()
    def __str__(self):
        return f"Slot {self.slot_number}: {self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')}"


 # optional if you want Room_Rent

class TreatmentRoom(models.Model):
    room_no = models.CharField(max_length=20, primary_key=True)
    floor = models.CharField(max_length=20, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    tr_code = models.CharField(max_length=20, null=True, blank=True)
    def __str__(self):
        return f"{self.room_no} ({self.tr_code})"

from django.db import models, IntegrityError, transaction
from django.utils import timezone
from MySql_Data_pull.models import Visit  # adjust path if needed

class BookingManager(models.Manager):
    def active(self):
        return self.filter(status='BOOKED')

    def booked_on(self, *, room=None, therapist=None, date=None, time_slot=None):
        qs = self.active()
        if room is not None:
            qs = qs.filter(room=room)
        if therapist is not None:
            qs = qs.filter(therapist=therapist)
        if date is not None:
            qs = qs.filter(date=date)
        if time_slot is not None:
            qs = qs.filter(time_slot=time_slot)
        return qs

class RoomBooking(models.Model):
    room = models.ForeignKey(TreatmentRoom, on_delete=models.CASCADE)
    date = models.DateField()
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE)
    therapy_name = models.CharField(max_length=255, null=True, blank=True)
    patient_id = models.BigIntegerField(null=True, blank=True)

    STATUS_CHOICES = [
        ("BOOKED", "Booked"),
        ("CANCELED", "Canceled"),
        ("COMPLETED", "Completed"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="BOOKED")
    visit = models.ForeignKey('MySql_Data_pull.Visit', null=True, blank=True, on_delete=models.SET_NULL, related_name='room_bookings')
    therapy = models.ForeignKey('MySql_Data_pull.store_Therapy', null=True, blank=True, on_delete=models.SET_NULL, related_name='room_bookings')

    # timestamps
    created_at = models.DateTimeField(auto_now_add=True,null=True,)
    updated_at = models.DateTimeField(auto_now=True,null=True,)

    objects = BookingManager()

    class Meta:
        # enforce one row per (room,date,time_slot,status) — prevents concurrent double-booking of BOOKED rows
        # this is preferable to a plain (room,date,time_slot) unique constraint because we want a freed
        # slot when a row is changed to CANCELED.
        constraints = [
            models.UniqueConstraint(fields=['room', 'date', 'time_slot', 'status'],
                                    name='unique_room_date_slot_status')
        ]
        indexes = [
            models.Index(fields=['room', 'date', 'time_slot', 'status']),
            models.Index(fields=['date', 'time_slot']),
            models.Index(fields=['patient_id']),
        ]

    def __str__(self):
        return f"Room {self.room.room_no} - {self.date} - {self.time_slot}"

    def cancel(self, by_user=None, reason=None, cascade=True):
        """
        Soft-cancel this booking. Creates a BookingCancellations audit row.
        """
        from Patient.models import BookingCancellations
        from MySql_Data_pull.models import store_Therapy, store_TherapyItem, store_PrescriptionItem

        if self.status == 'CANCELED':
            return

        now = timezone.now()
        with transaction.atomic():
            self.status = 'CANCELED'
            self.save(update_fields=['status', 'updated_at'])

            BookingCancellations.objects.create(
                canceled_at=now,
                reason=reason,
                canceled_by=by_user,
                patient_id=self.patient_id,
                date=self.date,
                time_slot_id=getattr(self.time_slot, 'id', None),
                therapy_name=self.therapy_name,
                therapist_name=None,
                room_no=getattr(self.room, 'room_no', None)
            )

            if cascade and self.visit:
                # cancel visit-level therapy items overlapping this date
                matched_therapies = []
                if self.therapy:
                    matched_therapies = [self.therapy]
                else:
                    matched_therapies = store_Therapy.objects.filter(
                        visit=self.visit,
                        therapy_name__iexact=self.therapy_name,
                        from_date__lte=self.date,
                        to_date__gte=self.date
                    )
                for th in matched_therapies:
                    if hasattr(th, 'status'):
                        th.status = 'cancelled'
                        th.save(update_fields=['status'])
                    store_TherapyItem.objects.filter(therapy=th, status='active').update(status='cancelled', cancelled_at=now)

                store_PrescriptionItem.objects.filter(
                    prescription__visit=self.visit,
                    from_date__lte=self.date,
                    to_date__gte=self.date,
                    status='active'
                ).update(status='cancelled', cancelled_at=now)


class TherapistBooking(models.Model):
    therapist = models.ForeignKey(Therapist, on_delete=models.CASCADE)
    date = models.DateField()
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE)
    therapy_name = models.CharField(max_length=255, null=True, blank=True)
    patient_id = models.BigIntegerField(null=True, blank=True)

    STATUS_CHOICES = [
        ("BOOKED", "Booked"),
        ("CANCELED", "Canceled"),
        ("COMPLETED", "Completed"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="BOOKED")
    visit = models.ForeignKey('MySql_Data_pull.Visit', null=True, blank=True, on_delete=models.SET_NULL, related_name='therapist_bookings')
    therapy = models.ForeignKey('MySql_Data_pull.store_Therapy', null=True, blank=True, on_delete=models.SET_NULL, related_name='therapist_bookings')

    created_at = models.DateTimeField(auto_now_add=True,null=True,)
    updated_at = models.DateTimeField(auto_now=True,null=True,)

    objects = BookingManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['therapist', 'date', 'time_slot', 'status'],
                                    name='unique_therapist_date_slot_status')
        ]
        indexes = [
            models.Index(fields=['therapist', 'date', 'time_slot', 'status']),
            models.Index(fields=['date', 'time_slot']),
            models.Index(fields=['patient_id']),
        ]

    def __str__(self):
        return f"{self.therapist.therapist_name} - {self.date} - {self.time_slot}"

    def cancel(self, by_user=None, reason=None, cascade=True):
        # mirror of RoomBooking.cancel but for therapist
        from Patient.models import BookingCancellations
        from MySql_Data_pull.models import store_Therapy, store_TherapyItem, store_PrescriptionItem
        if self.status == 'CANCELED':
            return

        now = timezone.now()
        with transaction.atomic():
            self.status = 'CANCELED'
            self.save(update_fields=['status', 'updated_at'])

            BookingCancellations.objects.create(
                canceled_at=now,
                reason=reason,
                canceled_by=by_user,
                patient_id=self.patient_id,
                date=self.date,
                time_slot_id=getattr(self.time_slot, 'id', None),
                therapy_name=self.therapy_name,
                therapist_name=getattr(self.therapist,'therapist_name',None),
                room_no=None
            )

            if cascade and self.visit:
                matched_therapies = []
                if self.therapy:
                    matched_therapies = [self.therapy]
                else:
                    matched_therapies = store_Therapy.objects.filter(
                        visit=self.visit,
                        therapy_name__iexact=self.therapy_name,
                        from_date__lte=self.date,
                        to_date__gte=self.date
                    )
                for th in matched_therapies:
                    if hasattr(th, 'status'):
                        th.status = 'cancelled'
                        th.save(update_fields=['status'])
                    store_TherapyItem.objects.filter(therapy=th, status='active').update(status='cancelled', cancelled_at=now)

                store_PrescriptionItem.objects.filter(
                    prescription__visit=self.visit,
                    from_date__lte=self.date,
                    to_date__gte=self.date,
                    status='active'
                ).update(status='cancelled', cancelled_at=now)


from django.db import models
from django.utils import timezone
from django.conf import settings

class BookingCancellations(models.Model):
    # --- AUDIT FIELDS ---
    id = models.AutoField(primary_key=True)
    canceled_at = models.DateTimeField(default=timezone.now)
    reason = models.TextField(null=True, blank=True)
    
    # Link to the user who canceled (Required Detail)
    canceled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancellations_audit"
    )

    # --- SESSION DETAIL FIELDS (Denormalized from RoomBooking/TherapistBooking) ---
    patient_id = models.BigIntegerField(db_index=True,null=True,)
    date = models.DateField(null=True,)
    time_slot_id = models.IntegerField(null=True) # Store the TimeSlot ID directly
    therapy_name = models.CharField(max_length=255,null=True,)
    
    # Store Room and Therapist details if they were part of the cancelled session
    therapist_name = models.CharField(max_length=200, null=True, blank=True)
    room_no = models.CharField(max_length=50, null=True, blank=True) 


    def __str__(self):
        return f"Canceled: Patient {self.patient_id} - {self.therapy_name} on {self.date}"
    



class AllocationAttempt(models.Model):
    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    visit = models.ForeignKey('MySql_Data_pull.Visit', null=True, blank=True, on_delete=models.SET_NULL)
    therapy = models.ForeignKey('MySql_Data_pull.store_Therapy', null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateField()
    requested_time_slot = models.ForeignKey(TimeSlot, null=True, blank=True, on_delete=models.SET_NULL)
    requested_time_slot_value = models.CharField(max_length=8, blank=True, null=True)  # backup text
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='FAILED')
    reason = models.TextField(blank=True, null=True)  # e.g. "room_unavailable" or "therapist_conflict: T1,T2"
    created_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(null=True, blank=True)  # optional: store attempted therapist codes, room_no, etc.

    class Meta:
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.therapy} @ {self.date} - {self.requested_time_slot_value or self.requested_time_slot} - {self.status}"