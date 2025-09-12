from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):
    ROLE_CHOICES = [
        ("therapist", "Therapist"),
        ("therapist_admin", "Therapist Admin"),
        ("doctor_admin", "Doctor Admin"),
        ("gm_hr", "GM & HR Team"),
        ("super_admin", "Super Admin"),
        ("Patient", "Patient"),
        ("Tenants", "Tenants"),
        ("Doctor Helpdesk", "Doctor Helpdesk "),
       
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="therapist")
    mobile = models.CharField(max_length=15, unique=True, null=True, blank=True)