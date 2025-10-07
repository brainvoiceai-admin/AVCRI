from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
    ("super_admin", "Super Admin (IT Department)"),
    ("admin", "Admin (Administrative GM / Management)"),
    ("doctor", "Doctor"),
    ("scheduling_staff", "Scheduling Staff"),
    ("therapist", "Therapist"),
    ("nurse", "Nurse"),
    ("patient", "Patient"),
    ("ip_pharmacy_staff", "IP Pharmacy Staff"),
    ("imu_staff", "IMU Staff (Instant Medical Unit)"),
    ("finance_staff", "Finance Staff"),
    ("hr", "HR"),
    ("housekeeping_staff", "Housekeeping Staff"),
]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="therapist")
    mobile = models.CharField(max_length=15, unique=True, null=True, blank=True)