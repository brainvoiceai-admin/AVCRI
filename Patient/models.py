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
