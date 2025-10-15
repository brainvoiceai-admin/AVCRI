from django.db import models



#Depute_Details Db

class TherapistDeployment(models.Model):
    applied_date = models.DateTimeField()
    thpst_code = models.CharField(max_length=50, primary_key=True)  # assuming therapist code is unique
    thpst_name = models.CharField(max_length=100)
    thpst_grade_code = models.CharField(max_length=50)
    dep_fr_date = models.DateTimeField()
    dep_to_date = models.DateTimeField()
    deputed_place = models.CharField(max_length=100, null=True, blank=True)
    thr_sex = models.CharField(max_length=10)
    user_name = models.CharField(max_length=50)

    class Meta:
        managed = False  # Django won’t create/migrate this table
        db_table = '[dbo].[Deput_Details]'  # replace with actual table name in SQL Server
        app_label = 'MySql_Data_pull'



#for dbo.Prescription Db

class Prescription(models.Model):
    rdate = models.DateTimeField(db_column='Rdate', null=True, blank=True)
    rtime = models.DateTimeField(db_column='RTime', null=True, blank=True)
    pres_doc_code = models.IntegerField(db_column='Pres_Doc_Code', null=True, blank=True)
    pat_reg_no = models.IntegerField(db_column='Pat_Reg_No',primary_key=True)
    doa = models.DateTimeField(db_column='DOA', null=True, blank=True)
    pres_item_seq = models.IntegerField(db_column='Pres_Item_Seq')
    pres_item_seq1 = models.IntegerField(db_column='Pres_Item_Seq1')
    pres_item_code = models.IntegerField(db_column='Pres_Item_Code')
    pres_item_dosage = models.CharField(db_column='Pres_Item_Dosage', max_length=50, null=True, blank=True)
    pres_item_uom = models.CharField(db_column='Pres_Item_Uom', max_length=50, null=True, blank=True)
    pres_item_usage = models.CharField(db_column='Pres_Item_Usage', max_length=100, null=True, blank=True)
    pres_int_ext = models.CharField(db_column='Pres_Int_Ext', max_length=50, null=True, blank=True)
    pres_time_period = models.CharField(db_column='Pres_Time_Period', max_length=100, null=True, blank=True)
    pres_from = models.CharField(db_column='Pres_From', max_length=50, null=True, blank=True)
    pres_to = models.CharField(db_column='Pres_To', max_length=50, null=True, blank=True)
    taken_from = models.CharField(db_column='Taken_From', max_length=50, null=True, blank=True)
    med_status = models.CharField(db_column='Med_Status', max_length=50, null=True, blank=True)
    time_1 = models.CharField(db_column='Time_1', max_length=50, null=True, blank=True)
    time_2 = models.CharField(db_column='Time_2', max_length=50, null=True, blank=True)
    time_3 = models.CharField(db_column='Time_3', max_length=50, null=True, blank=True)
    time_4 = models.CharField(db_column='Time_4', max_length=50, null=True, blank=True)
    time_5 = models.IntegerField(db_column='Time_5', null=True, blank=True)
    exp_dod = models.DateTimeField(db_column='Exp_DOD', null=True, blank=True)
    pat_name = models.CharField(db_column='Pat_Name', max_length=200, null=True, blank=True)
    pat_room_no = models.CharField(db_column='Pat_Room_No', max_length=50, null=True, blank=True)
    pat_sex = models.CharField(db_column='Pat_Sex', max_length=10, null=True, blank=True)
    pat_age = models.IntegerField(db_column='Pat_Age', null=True, blank=True)
    ingred = models.CharField(db_column='Ingred', max_length=200, null=True, blank=True)
    upd_time = models.CharField(db_column='Upd_Time', max_length=200, null=True, blank=True)

    class Meta:
        managed = False  # prevent migrations
        db_table = '[dbo].[Prescription]'
        app_label = 'MySql_Data_pull'


class OPMaster(models.Model):
    # Replace field names / max_length if your actual SQL schema differs
    Reg_Date = models.DateTimeField(null=True, blank=True)                      # appears like "2018-06-25 00:00:00.000"
    NPat_Name = models.CharField(max_length=200, null=True, blank=True)
    NPat_Reg_No = models.BigIntegerField(primary_key=True)                      # patient registration number (treated as PK)
    NPat_Sex = models.CharField(max_length=10, null=True, blank=True)
    NPat_Add1 = models.CharField(max_length=200, null=True, blank=True)
    NPat_Add2 = models.CharField(max_length=200, null=True, blank=True)
    NPat_Add3 = models.CharField(max_length=200, null=True, blank=True)
    NPat_City = models.CharField(max_length=100, null=True, blank=True)         # CSV showed NaNs; using CharField to accept codes/names

    class Meta:
        managed = False   # Django won't manage (external SQL Server table)
        db_table = '[dbo].[NPat_Reg_Master]'  # <-- change to the exact external table name if different
        app_label = 'MySql_Data_pull'
        
#For dbo.Registration
class Registration(models.Model):
    pat_reg_no = models.BigIntegerField(primary_key=True)   # Pat_Reg_No
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
    aadharno1 = models.BigIntegerField(null=True, blank=True)
    aadharno2 = models.BigIntegerField(null=True, blank=True)
    aadharno3 = models.BigIntegerField(null=True, blank=True)
    pat_op_reg_no = models.BigIntegerField(null=True, blank=True)
    imgloc = models.CharField(max_length=255, null=True, blank=True)
    pat_bgroup = models.CharField(max_length=10, null=True, blank=True)
    e_contact_name = models.CharField(max_length=200, null=True, blank=True)
    pat_ref_id = models.BigIntegerField(null=True, blank=True)
    e_contact_no = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        managed = False   # don't let Django create/drop this table
        db_table = '[dbo].[Registration]'
        app_label = 'MySql_Data_pull'



#for dbo.Room_Master
class RoomMaster(models.Model):
    room_code = models.CharField(max_length=50, primary_key=True)   # Room_Code
    room_name = models.CharField(max_length=100, null=True, blank=True)
    room_type = models.CharField(max_length=50, null=True, blank=True)
    room_capacity = models.IntegerField(null=True, blank=True)
    room_location = models.CharField(max_length=100, null=True, blank=True)
    room_status = models.CharField(max_length=50, null=True, blank=True)
    room_user = models.CharField(max_length=50, null=True, blank=True)
    room_user_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False   # Django won’t manage this table
        db_table = '[dbo].[Room_Master]'
        app_label = 'MySql_Data_pull'



#for dbo.Therapist_Details
class TherapistDetails(models.Model):
    therapist_code = models.CharField(max_length=50, primary_key=True)   # Therapist_Code
    therapist_name = models.CharField(max_length=100, null=True, blank=True)
    therapist_grade_code = models.CharField(max_length=50, null=True, blank=True)
    instit = models.CharField(max_length=100, null=True, blank=True)
    thr_age = models.IntegerField(null=True, blank=True)
    thr_sex = models.CharField(max_length=10, null=True, blank=True)
    add1 = models.CharField(max_length=200, null=True, blank=True)
    add2 = models.CharField(max_length=200, null=True, blank=True)
    add3 = models.CharField(max_length=200, null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    pincode = models.CharField(max_length=20, null=True, blank=True)
    phone_no_resi = models.CharField(max_length=20, null=True, blank=True)
    phone_no_mob = models.CharField(max_length=20, null=True, blank=True)
    weekly_off = models.CharField(max_length=50, null=True, blank=True)
    service_grade = models.CharField(max_length=50, null=True, blank=True)
    thr_class = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        managed = False   # Django won’t manage this table
        db_table = '[dbo].[Therapist_Details]'
        app_label = 'MySql_Data_pull'



#for dbo.Therapist_Master
class TherapistMaster(models.Model):
    therapist_class_code = models.CharField(max_length=50, primary_key=True)   # Therapist_Class_Code
    therapist_class_name = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        managed = False   # Django won’t manage this table
        db_table = '[dbo].[Therapist_Master]'
        app_label = 'MySql_Data_pull'



#for dbo.TR_Master
class TRMaster(models.Model):
    TRCode = models.CharField(max_length=50, primary_key=True)   # TRCode
    tr_room = models.CharField(max_length=100, null=True, blank=True)
    tr_group = models.CharField(max_length=100, null=True, blank=True)
    stage = models.IntegerField(null=True, blank=True)

    class Meta:
        managed = False   # Django won’t manage this table
        db_table = '[dbo].[TR_Master]'
        app_label = 'MySql_Data_pull'


#for dbo.item_Master
class ItemMaster(models.Model):
    item_code = models.CharField(max_length=50, primary_key=True)   # Item_Code
    item_name = models.CharField(max_length=255, null=True, blank=True)  # Item_Name
    item_uom = models.CharField(max_length=50, null=True, blank=True)    # Item_Uom
    item_group_name = models.CharField(max_length=100, null=True, blank=True)  # Item_Group_Name
    item_category = models.CharField(max_length=50, null=True, blank=True)     # Item_Category
    item_cex = models.CharField(max_length=10, null=True, blank=True)   # Item_Cex
    item_seasonal = models.CharField(max_length=10, null=True, blank=True)  # Item_Seasonal
    item_max = models.IntegerField(null=True, blank=True)   # Item_Max
    item_min = models.IntegerField(null=True, blank=True)   # Item_Min
    item_rol = models.FloatField(null=True, blank=True)     # Item_Rol
    item_procurred_from = models.CharField(max_length=255, null=True, blank=True)  # Item_Procurred_From

    class Meta:
        managed = False   
        db_table = '[dbo].[item_Master]'



#dbo.Slot_Master
class TimeSlot_sql(models.Model):
    slot_no = models.IntegerField(primary_key=True)   # Slot_No
    starting_time = models.CharField(max_length=50, null=True, blank=True)
    time_session = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        managed = False   
        db_table = '[dbo].[Slot_Master]'


#dbo.Scheduling

class Scheduling(models.Model):
    pat_reg_no = models.CharField(max_length=50, primary_key=True, db_column="PReg_No")  # Patient Reg No

    tdate = models.DateTimeField(null=True, blank=True, db_column="TDate")  # Treatment Date
    treat_no = models.FloatField(null=True, blank=True, db_column="Treat_No")  # Treatment Number
    troom_no = models.CharField(max_length=50, null=True, blank=True, db_column="TRoom_No")  # Therapy Room
    therapy_name = models.CharField(max_length=255, null=True, blank=True, db_column="Therapy_Name")  # Therapy Name
    therapist_name = models.CharField(max_length=255, null=True, blank=True, db_column="Therapist_Name")  # Therapist Name
    start_time = models.CharField(max_length=50, null=True, blank=True, db_column="Start_Time")  # Start Time
    pat_room_no = models.CharField(max_length=50, null=True, blank=True, db_column="Pat_Room_No")  # Patient Room
    admit_date = models.DateTimeField(null=True, blank=True, db_column="Admit_Date")  # Admit Date
    pat_name = models.CharField(max_length=255, null=True, blank=True, db_column="Pat_Name")  # Patient Name
    therapist_code = models.CharField(max_length=50, null=True, blank=True, db_column="Therapist_Code")  # Therapist Code
    therapy_code = models.CharField(max_length=50, null=True, blank=True, db_column="Therapy_Code")  # Therapy Code
    therapist_sex = models.CharField(max_length=10, null=True, blank=True, db_column="Therapist_Sex")  # Therapist Sex
    therapist_grade = models.CharField(max_length=50, null=True, blank=True, db_column="Therapist_Grade")  # Therapist Grade
    treat_status = models.IntegerField(null=True, blank=True, db_column="Treat_Status")  # Treatment Status
    exc_status = models.IntegerField(null=True, blank=True, db_column="Exc_Status")  # Excuse Status
    reason_code = models.IntegerField(null=True, blank=True, db_column="Reason_Code")  # Reason Code
    active = models.CharField(max_length=10, null=True, blank=True, db_column="Active")  # Active

    class Meta:
        managed = False  # Since table exists in SQL Server
        db_table = '[dbo].[Scheduling]'




#data base after doctor consultation managed by us


class Visit(models.Model):
    patient_id = models.BigIntegerField()
    patient_name = models.CharField(max_length=255, null=True, blank=True)  # new field
    from_date = models.DateField(null=True, blank=True)
    to_date = models.DateField(null=True, blank=True)
    admission_days = models.IntegerField(null=True, blank=True)
    is_ip_or_op = models.CharField(max_length=5, null=True, blank=True)
    is_vip = models.BooleanField(default=False)
    repeated_status = models.CharField(max_length=3, choices=[('Yes','Yes'),('No','No')], default='No')
    date_of_visit = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Visit for Patient {self.patient_id} ({self.patient_name}) on {self.date_of_visit.date()}"


from Patient.models import TimeSlot
class store_Therapy(models.Model):
    # Use DO_NOTHING for foreign key to the live server model to prevent errors
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='therapies',
    null=True,  # allows empty values
    blank=True)
    patient_id = models.BigIntegerField()
    therapy_name = models.CharField(max_length=100)
    ext_int = models.CharField(max_length=50)
    procured = models.CharField(max_length=50)
    from_date = models.DateField()
    to_date = models.DateField()
    days = models.IntegerField()
    preferred_time_slot = models.ForeignKey(TimeSlot, null=True, blank=True, on_delete=models.SET_NULL, related_name='preferred_for_therapies')
    preferred_time_slot_value = models.CharField(max_length=8, null=True, blank=True)



from django.conf import settings
from django.utils import timezone
class store_TherapyItem(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
    ]

    therapy = models.ForeignKey('store_Therapy', on_delete=models.CASCADE, related_name='items')
    item_code = models.CharField(max_length=50)
    oil_class = models.CharField(max_length=100, blank=True, null=True)
    usage = models.CharField(max_length=255, blank=True, null=True)
    procured = models.CharField(max_length=100, blank=True, null=True)

    # Duplicate therapy date range on item for simple queries & reporting
    from_date = models.DateField(null=True)
    to_date = models.DateField(null=True)
    days = models.IntegerField(default=0)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    created_at = models.DateTimeField(auto_now_add=True,null=True)
    updated_at = models.DateTimeField(auto_now=True,null=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['item_code']),
            models.Index(fields=['status']),
            models.Index(fields=['from_date', 'to_date']),
        ]

    def __str__(self):
        return f"{self.item_code} ({self.therapy_id})"

    def cancel(self, by_user=None):
        """Mark this item as cancelled."""
        if self.status != 'cancelled':
            self.status = 'cancelled'
            self.cancelled_by = by_user
            self.cancelled_at = timezone.now()
            self.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'updated_at'])



from django.db import models, transaction
from datetime import timedelta
class store_TherapyItemDay(models.Model):
    STATUS_CHOICES = [('active', 'Active'), ('cancelled', 'Cancelled'), ('completed', 'Completed')]

    therapy_item = models.ForeignKey('store_TherapyItem', on_delete=models.CASCADE, related_name='day_rows')
    date = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        unique_together = ('therapy_item', 'date')
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.therapy_item.item_code} on {self.date} ({self.status})"

    @classmethod
    def expand_for_item(cls, item: 'store_TherapyItem'):
        """
        Create day rows for the given item for its from_date..to_date range.
        Called automatically on new store_TherapyItem.save().
        """
        if not item.from_date or not item.to_date:
            return 0
        start = item.from_date
        end = item.to_date
        days = []
        d = start
        while d <= end:
            days.append(cls(therapy_item=item, date=d, status='active'))
            d += timedelta(days=1)
        # bulk create ignoring existing duplicates
        try:
            with transaction.atomic():
                cls.objects.bulk_create(days, ignore_conflicts=True)
        except TypeError:
            # older Django: no ignore_conflicts -> fallback to per-row get_or_create
            created = 0
            for row in days:
                obj, was_created = cls.objects.get_or_create(therapy_item=item, date=row.date, defaults={'status': 'active'})
                if was_created:
                    created += 1
            return created
        return len(days)

    @classmethod
    def cancel_day(cls, therapy_item: 'store_TherapyItem', cancel_date, by_user=None):
        """
        Cancel a single date row for the given therapy_item; create row if missing, set status cancelled.
        Returns True if row created/updated.
        """
        obj, created = cls.objects.get_or_create(therapy_item=therapy_item, date=cancel_date,
                                                 defaults={'status': 'cancelled', 'cancelled_by': by_user, 'cancelled_at': timezone.now()})
        if not created:
            if obj.status != 'cancelled':
                obj.status = 'cancelled'
                obj.cancelled_by = by_user
                obj.cancelled_at = timezone.now()
                obj.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'updated_at'])
        return True




class store_Prescription(models.Model):
    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='prescriptions',
    null=True,  # allows empty values
    blank=True)
    patient_id = models.BigIntegerField()
    date_created = models.DateTimeField(auto_now_add=True)

class store_PrescriptionItem(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('cancelled', 'Cancelled'),
    ]

    prescription = models.ForeignKey('store_Prescription', on_delete=models.CASCADE, related_name='items')
    item_code = models.CharField(max_length=50)
    dosage = models.CharField(max_length=50)
    usage = models.CharField(max_length=100)
    internal_external = models.CharField(max_length=20)
    time = models.CharField(max_length=50)
    item_uom = models.CharField(max_length=50, blank=True, null=True)

    # New fields to match front-end
    from_date = models.DateField(null=True, blank=True)
    to_date = models.DateField(null=True, blank=True)
    days = models.IntegerField(default=0)

    procured_from = models.CharField(max_length=100, blank=True, null=True)

    # Optional cancellation / status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True,null=True)
    updated_at = models.DateTimeField(auto_now=True,null=True)

    class Meta:
        indexes = [
            models.Index(fields=['item_code']),
            models.Index(fields=['from_date', 'to_date']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.item_code} (Prescription {self.prescription_id})"

    def cancel(self, by_user=None):
        """Mark this prescription item cancelled (soft-delete)."""
        if self.status != 'cancelled':
            self.status = 'cancelled'
            self.cancelled_by = by_user
            self.cancelled_at = timezone.now()
            self.save(update_fields=['status', 'cancelled_by', 'cancelled_at', 'updated_at'])