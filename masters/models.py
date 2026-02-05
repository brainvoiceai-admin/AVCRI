from django.db import models
#Procured master
class Procured(models.Model):
    """Master list of procurement sources (e.g., IP Pharmacy, Kashaya Room)."""
    
    name = models.CharField(max_length=100, unique=True, verbose_name="Source Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Procurement Source"
        verbose_name_plural = "Procurement Sources"
        ordering = ["name"]





#oil class master
class OilClass(models.Model):
    """Master list of oil categories/classes. Examples: Sesame Oil (Tila Taila), Coconut Oil (Narikela Taila)."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Oil Class Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Oil Class"
        verbose_name_plural = "Oil Classes"
        ordering = ["name"]

#usage master
class UsageType(models.Model):
    """Master list of usage types for inventory and resources. Examples: Internal (IP Use), Dispensed (OP Use), Wastage/Damage."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Usage Type Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Usage Type"
        verbose_name_plural = "Usage Types"
        ordering = ["name"]

#Prescription Usage Master
class PrescriptionUsage(models.Model):
    """Master list of usage types specifically for prescriptions."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Prescription Usage Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Prescription Usage"
        verbose_name_plural = "Prescription Usages"
        ordering = ["name"]


class NurseTreatmentMaster(models.Model):
    """Master list of nurse treatments with required nurse count."""
    treatment_code = models.CharField(max_length=50, unique=True, verbose_name="Treatment Code")
    name = models.CharField(max_length=200, verbose_name="Treatment Name")
    number_of_nurse_required = models.PositiveIntegerField(default=1, verbose_name="Number of Nurses Required")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return f"{self.treatment_code} - {self.name}"

    class Meta:
        verbose_name = "Nurse Treatment"
        verbose_name_plural = "Nurse Treatments"
        ordering = ["treatment_code"]


class NurseMaster(models.Model):
    """Master list of nurses with their codes, names, and designations."""
    nurse_code = models.CharField(max_length=50, unique=True, verbose_name="Nurse Code")
    nurse_name = models.CharField(max_length=200, verbose_name="Nurse Name")
    designation = models.CharField(max_length=100, verbose_name="Designation")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return f"{self.nurse_code} - {self.nurse_name}"

    class Meta:
        verbose_name = "Nurse"
        verbose_name_plural = "Nurses"
        ordering = ["nurse_code"]


#Prescription time master
class PrescriptionTime(models.Model):
    """Master list of standardized time slots for prescriptions or dosing schedules. Examples: 8 AM, 12 PM, 4 PM."""
    name = models.CharField(max_length=20, unique=True, verbose_name="Time Slot")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Prescription Time Slot"
        verbose_name_plural = "Prescription Time Slots"
        ordering = ["name"]


#Ext/Int Master
class PrescriptionScope(models.Model):
    """Master list for classifying prescription scope (e.g., External/Internal). Clarifies whether a prescription is for an existing IP patient or OP/external use."""
    name = models.CharField(max_length=50, unique=True, verbose_name="Scope Name (Ext/Int)")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Prescription Scope"
        verbose_name_plural = "Prescription Scopes"
        ordering = ["name"]

class UnitNo(models.Model):
    """
    Master model for storing unit names (e.g., ml, cm) and their status.
    """
    unit_name = models.CharField(max_length=50,unique=True,verbose_name="Unit Name",help_text="e.g., ml, cm, kg")
    is_active = models.BooleanField(default=True,verbose_name="Is Active",help_text="Designates whether the unit can be used.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Unit Number"
        verbose_name_plural = "Unit Numbers"
        ordering = ['unit_name']

    def __str__(self):
        return self.unit_name

# Therapy Group Master
class TherapyGroup(models.Model):
    """Master list of therapy groups/categories."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Group Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Therapy Group"
        verbose_name_plural = "Therapy Groups"
        ordering = ["name"]

# Therapy Master
class TherapyMaster(models.Model):
    """Master list of therapy names and details."""
    therapy_code = models.CharField(max_length=20, unique=True, verbose_name="Therapy Code")
    therapy_name = models.CharField(max_length=255, verbose_name="Therapy Name")
    therapy_group = models.ForeignKey('TherapyGroup', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Therapy Group")
    therapy_category = models.CharField(max_length=100, null=True, blank=True, verbose_name="Therapy Category")
    therapy_duration = models.CharField(max_length=50, null=True, blank=True, verbose_name="Duration")
    bathing_required = models.CharField(max_length=10, null=True, blank=True, verbose_name="Bathing Required")
    treatment_room_required = models.CharField(max_length=10, null=True, blank=True, verbose_name="Room Required")
    cost_of_therapy = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Cost")
    
    # Patient type field (IP or OP)
    patient_type = models.CharField(
        max_length=2,
        choices=[('IP', 'IP (Inpatient)'), ('OP', 'OP (Outpatient)')],
        default='IP',
        verbose_name="Patient Type",
        help_text="Select whether this therapy is for Inpatient (IP) or Outpatient (OP) patients"
    )
    
    # Therapist count fields (from original TherapyDetails model)
    no_of_super_senior_therapist = models.IntegerField(default=0, verbose_name="Super Senior Therapists")
    no_of_senior_therapist = models.IntegerField(default=0, verbose_name="Senior Therapists")
    no_of_junior_therapist = models.IntegerField(default=0, verbose_name="Junior Therapists")
    no_of_trainee_therapist = models.IntegerField(default=0, verbose_name="Trainee Therapists")
    total_no_of_therapist = models.IntegerField(default=0, verbose_name="Total Therapists")
    
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return f"{self.therapy_code} - {self.therapy_name}"

    class Meta:
        verbose_name = "Therapy Master"
        verbose_name_plural = "Therapy Masters"
        ordering = ["therapy_name"]

# Item Group Master
class ItemGroup(models.Model):
    """Master list of item groups/categories."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Group Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Item Group"
        verbose_name_plural = "Item Groups"
        ordering = ["name"]

# Item Master
class ItemMaster(models.Model):
    """Master list of items used in therapies and prescriptions."""
    item_code = models.CharField(max_length=4, unique=True, verbose_name="Item Code", editable=False)
    item_name = models.CharField(max_length=255, verbose_name="Item Name")
    item_group = models.ForeignKey('ItemGroup', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Group")
    umo = models.ForeignKey('UnitNo', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="UOM")
    min_quantity = models.IntegerField(null=True, blank=True, verbose_name="Min Quantity")
    max_quantity = models.IntegerField(null=True, blank=True, verbose_name="Max Quantity")
    procured_from = models.ForeignKey('Procured', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Procured From")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def save(self, *args, **kwargs):
        if not self.item_code:
            # Auto-generate 4-digit unique code
            self.item_code = self.generate_unique_code()
        super().save(*args, **kwargs)

    def generate_unique_code(self):
        """Generate a unique 4-digit code starting from 0001"""
        from django.db.models import Max
        # Get the maximum existing code
        max_code = ItemMaster.objects.aggregate(Max('item_code'))['item_code__max']
        
        if max_code:
            try:
                # Try to parse as integer and increment
                next_num = int(max_code) + 1
                if next_num > 9999:
                    # If we exceed 9999, find the next available number
                    for i in range(1, 10000):
                        code_str = f"{i:04d}"
                        if not ItemMaster.objects.filter(item_code=code_str).exists():
                            return code_str
            except ValueError:
                # If max_code is not numeric, start from 0001
                pass
        
        # Start from 0001 or find first available
        for i in range(1, 10000):
            code_str = f"{i:04d}"
            if not ItemMaster.objects.filter(item_code=code_str).exists():
                return code_str
        
        # Fallback (should never reach here)
        return "0001"

    def __str__(self):
        return f"{self.item_code} - {self.item_name}"

    class Meta:
        verbose_name = "Item Master"
        verbose_name_plural = "Item Masters"
        ordering = ["item_name"]

# Slot Master
class SlotMaster(models.Model):
    """Master list of time slots for therapy scheduling."""
    slot_number = models.IntegerField(unique=True, verbose_name="Slot Number")
    slot_time = models.TimeField(verbose_name="Slot Time")
    slot_name = models.CharField(max_length=100, null=True, blank=True, verbose_name="Slot Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        # Format time in 12-hour format
        time_str = self.slot_time.strftime('%I:%M %p')
        return f"Slot {self.slot_number}: {time_str}"

    class Meta:
        verbose_name = "Slot Master"
        verbose_name_plural = "Slot Masters"
        ordering = ["slot_number"]

# Ingredient Master
class IngredientMaster(models.Model):
    """Master list of ingredients used in prescriptions."""
    ingredient_code = models.CharField(max_length=20, unique=True, verbose_name="Ingredient Code")
    ingredient_name = models.CharField(max_length=255, verbose_name="Ingredient Name")
    description = models.TextField(null=True, blank=True, verbose_name="Description")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return f"{self.ingredient_code} - {self.ingredient_name}"

    class Meta:
        verbose_name = "Ingredient Master"
        verbose_name_plural = "Ingredient Masters"
        ordering = ["ingredient_name"]

# Therapist Grade Master
class TherapistGrade(models.Model):
    """Master list of therapist grades/levels."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Grade Name")
    display_order = models.IntegerField(default=0, verbose_name="Display Order", help_text="Order for display in dropdowns")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Therapist Grade"
        verbose_name_plural = "Therapist Grades"
        ordering = ["display_order", "name"]

# Therapist Master
class TherapistMaster(models.Model):
    """Master list of therapists with leave management."""
    # Foreign keys to user system
    user = models.ForeignKey('authentication.CustomUser', on_delete=models.CASCADE, related_name='therapist_master', verbose_name="User", null=True, blank=True)
    therapist_profile = models.ForeignKey('authentication.TherapistProfile', on_delete=models.CASCADE, related_name='therapist_master', verbose_name="Therapist Profile", null=True, blank=True)
    therapist_gender = models.CharField(max_length=200,verbose_name="Therapist Gender",null=True,blank=True,default="Male")
    # Therapist details (can be synced from user profile)
    therapist_code = models.CharField(max_length=20, unique=True, verbose_name="Therapist Code")
    therapist_name = models.CharField(max_length=255, verbose_name="Therapist Name")
    therapist_grade = models.ForeignKey(TherapistGrade, on_delete=models.PROTECT, related_name='therapists', verbose_name="Therapist Grade", null=True, blank=True)
    employee_code = models.CharField(max_length=50, unique=True, verbose_name="Employee Code", help_text="Used for emergency leave API mapping")
    is_bathing_therapist = models.BooleanField(default=True, verbose_name="Bathing Therapist")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return f"{self.therapist_name} ({self.therapist_code})"

    class Meta:
        verbose_name = "Therapist Master"
        verbose_name_plural = "Therapist Masters"
        ordering = ["therapist_name"]

# Therapist Leave Master
class TherapistLeaveMaster(models.Model):
    """Weekly leave management for therapists."""
    WEEK_DAYS = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    therapist = models.ForeignKey(TherapistMaster, on_delete=models.CASCADE, related_name='leaves', verbose_name="Therapist")
    leave_day = models.IntegerField(choices=WEEK_DAYS, verbose_name="Leave Day")
    leave_day_name = models.CharField(max_length=10, blank=True, verbose_name="Day Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def save(self, *args, **kwargs):
        # Auto-fill day name based on leave_day
        self.leave_day_name = dict(self.WEEK_DAYS).get(self.leave_day, "")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.therapist.therapist_name} - {self.leave_day_name}"

    class Meta:
        verbose_name = "Therapist Leave"
        verbose_name_plural = "Therapist Leaves"
        ordering = ["therapist__therapist_name", "leave_day"]
        unique_together = ['therapist', 'leave_day']



class StayingRoom(models.Model):
    """Master list for staying rooms."""
    number = models.CharField(max_length=20, unique=True, verbose_name="No")
    room_desc = models.CharField(max_length=255, verbose_name="Room Description")
    room_no = models.CharField(max_length=50, verbose_name="Room Number")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Staying Room"
        verbose_name_plural = "Staying Rooms"
        ordering = ["number"]

    def __str__(self):
        return f"{self.number} - {self.room_no}"


def get_staying_room_display_number(room_number):
    """
    Given a room identifier (No), return the corresponding StayingRoom.room_no.
    Falls back to the original value if no match is found.
    """
    if room_number in (None, ''):
        return room_number
    lookup = str(room_number).strip()
    if not lookup:
        return room_number
    try:
        staying_room = StayingRoom.objects.filter(number__iexact=lookup).first()
        if staying_room and staying_room.room_no:
            return staying_room.room_no
    except Exception:
        pass
    return room_number


class EmergencyLeave(models.Model):
    """
    Stores emergency leave records fetched from HRMS (or webhook events).
    Linked to TherapistMaster via employee_code -> therapist.
    """
    # HRMS identifiers
    leave_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    # keep employee_code so we can map/update even if FK missing
    employee_code = models.CharField(max_length=50, db_index=True)

    # resolved link to our TherapistMaster (nullable if mapping missing)
    therapist = models.ForeignKey(
        "TherapistMaster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="emergency_leaves"
    )

    # leave window
    from_date = models.DateField()
    to_date = models.DateField()

    # meta / status
    leave_type = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=50, default="new", help_text="eg: new, processed, resolved")
    raw_payload = models.JSONField(null=True, blank=True)  # store original HRMS payload
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-from_date"]
        indexes = [
            models.Index(fields=["employee_code", "from_date", "to_date"]),
        ]

    def __str__(self):
        return f"{self.employee_code} ({self.from_date} → {self.to_date})"