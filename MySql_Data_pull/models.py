from django.db import models

# Create your models here.

#Therapist_Details Db
class TherapyDetails(models.Model):
    therapy_code = models.CharField(max_length=50,primary_key=True)
    senior_spl_thr_need = models.IntegerField()
    senior_thr_need = models.IntegerField()
    junior_thr_need = models.IntegerField()
    trainee_thr_need = models.CharField(max_length=50)
    therapy_duration = models.CharField(max_length=50, null=True, blank=True)
    helpers_needed = models.IntegerField()
    treat_rm_req = models.CharField(max_length=50)
    treatment_session = models.CharField(max_length=100)
    treatment_nature = models.CharField(max_length=100, null=True, blank=True)
    treat_bath = models.CharField(max_length=50, null=True, blank=True)
    treatment_room = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        managed = False  # Django won’t try to create/migrate this table
        db_table = '[dbo].[Therapy_Details]'  # SQL Server schema + table
        app_label = 'MySql_Data_pull'



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
class TimeSlot(models.Model):
    slot_no = models.IntegerField(primary_key=True)   # Slot_No
    starting_time = models.CharField(max_length=50, null=True, blank=True)
    time_session = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        managed = False   
        db_table = '[dbo].[Slot_Master]'
