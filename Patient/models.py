# models.py
from django.db import models

# yourapp/models.py
from django.db import models

class LocalRegistration(models.Model):
    pat_reg_no = models.BigIntegerField(primary_key=True)
    pat_prefix = models.CharField(max_length=20, null=True, blank=True)
    pat_name = models.CharField(max_length=200, null=True, blank=True)
    doctcode = models.CharField(max_length=50, null=True, blank=True)
    pat_dob = models.DateTimeField(null=True, blank=True)
    pat_age = models.CharField(max_length=10, null=True, blank=True)
    pat_sex = models.CharField(max_length=10, null=True, blank=True)
    pat_marital_status = models.CharField(max_length=50, null=True, blank=True)
    pat_occup = models.CharField(max_length=100, null=True, blank=True)
    pat_add1 = models.CharField(max_length=255, null=True, blank=True)
    pat_add2 = models.CharField(max_length=255, null=True, blank=True)
    pat_add3 = models.CharField(max_length=255, null=True, blank=True)
    pat_add4 = models.CharField(max_length=255, null=True, blank=True)
    pat_add5 = models.CharField(max_length=255, null=True, blank=True)
    pat_add6 = models.CharField(max_length=255, null=True, blank=True)
    pat_ph_no = models.CharField(max_length=50, null=True, blank=True)
    pat_email = models.CharField(max_length=100, null=True, blank=True)
    pat_passport = models.CharField(max_length=50, null=True, blank=True)
    pat_reg_date = models.DateTimeField(null=True, blank=True)
    pat_visit_date = models.DateTimeField(null=True, blank=True)
    pat_room_no = models.IntegerField(null=True, blank=True)
    pat_room_date = models.DateTimeField(null=True, blank=True)
    pat_status = models.CharField(max_length=50, null=True, blank=True)
    pat_user = models.CharField(max_length=50, null=True, blank=True)
    pat_user_date = models.DateTimeField(null=True, blank=True)
    dct_team = models.CharField(max_length=100, null=True, blank=True)
    aadharno1 = models.CharField(null=True, blank=True)
    aadharno2 = models.CharField(null=True, blank=True)
    aadharno3 = models.CharField(null=True, blank=True)
    pat_op_reg_no = models.BigIntegerField(null=True, blank=True)
    imgloc = models.CharField(max_length=255, null=True, blank=True)
    pat_bgroup = models.CharField(max_length=10, null=True, blank=True)
    e_contact_name = models.CharField(max_length=200, null=True, blank=True)
    pat_ref_id = models.CharField(null=True, blank=True)
    e_contact_no = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        managed = True   # Django will manage this table
        db_table = 'local_registration'




class Repeated_Visitors(models.Model):
    register_number = models.CharField(max_length=50, primary_key=True)  # unique identifier
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
