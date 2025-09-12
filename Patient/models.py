# models.py
from django.db import models

class Therapy(models.Model):
    code = models.CharField(max_length=50, unique=True)   # Therapy code
    name = models.CharField(max_length=200)               # Therapy name
    group = models.CharField(max_length=100)              # Therapy group
    category = models.CharField(max_length=100)           # Therapy category
    duration = models.CharField(max_length=100)           # Therapy duration (e.g. 30 min, 1 hr)

    bathing_required = models.BooleanField(default=False)         # Bathing required?
    treatment_room_required = models.BooleanField(default=False)  # Treatment room required?
    cost = models.DecimalField(max_digits=10, decimal_places=2)   # Cost of the therapy

    super_senior_needed = models.PositiveIntegerField(default=0)  # No. of Super Senior therapists
    senior_needed = models.PositiveIntegerField(default=0)        # No. of Senior therapists
    junior_needed = models.PositiveIntegerField(default=0)        # No. of Junior therapists
    trainee_needed = models.PositiveIntegerField(default=0)       # No. of Trainee therapists
    total_therapist_needed = models.PositiveIntegerField(default=0)  # Total therapists needed

    created_at = models.DateTimeField(auto_now_add=True)   # Record created date
    updated_at = models.DateTimeField(auto_now=True)       # Record updated date

    def save(self, *args, **kwargs):
        # Auto-calculate total therapists needed
        self.total_therapist_needed = (
            self.super_senior_needed +
            self.senior_needed +
            self.junior_needed +
            self.trainee_needed
        )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} - {self.name}"






class PatientTherapyAssignment(models.Model):
    patient_id = models.CharField(max_length=50)
    therapy = models.ForeignKey(Therapy, on_delete=models.CASCADE)
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)



from django.db import models

class Patient(models.Model):
    reg_no = models.CharField(max_length=50, unique=True)   # Registration Number
    full_name = models.CharField(max_length=200)
    age = models.PositiveIntegerField()
    gender_choices = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    ]
    gender = models.CharField(max_length=10, choices=gender_choices)
    vip_status = models.BooleanField(default=False)
    ip_number = models.CharField(max_length=50, blank=True, null=True)   # In-patient Number
    room_number = models.CharField(max_length=20, blank=True, null=True)
    unique_id = models.CharField(max_length=100, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)   # When patient was created
    updated_at = models.DateTimeField(auto_now=True)       # When patient details last updated

    def __str__(self):
        return f"{self.reg_no} - {self.full_name}"
