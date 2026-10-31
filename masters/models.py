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
    order_no = models.IntegerField(default=0, verbose_name="Order Number")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Prescription Usage"
        verbose_name_plural = "Prescription Usages"
        ordering = ["order_no", "name"]


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
    order_no = models.IntegerField(default=0, verbose_name="Order Number")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Prescription Time Slot"
        verbose_name_plural = "Prescription Time Slots"
        ordering = ["order_no", "name"]


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
    therapy_category = models.CharField(max_length=100, verbose_name="Therapy Category")
    therapy_duration = models.CharField(max_length=50, verbose_name="Duration")
    bathing_required = models.CharField(max_length=10, verbose_name="Bathing Required")
    treatment_room_required = models.CharField(max_length=10, verbose_name="Room Required")
    cost_of_therapy = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="Cost")
    
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
    
    is_steam_therapy = models.BooleanField(
        default=False,
        verbose_name="Steam Therapy",
        help_text="If enabled, this therapy is dynamically allocated to designated Steam Therapy Rooms configured in Treatment Room Master without slot restrictions."
    )
    is_vamanam = models.BooleanField(
        default=False,
        verbose_name="Vamanam Therapy",
        help_text="If enabled, this therapy is strictly allocated to designated Vamanam slots (e.g. 05:00 AM, 05:30 AM) and Vamanam treatment rooms."
    )
    is_vasthi = models.BooleanField(
        default=False,
        verbose_name="Vasthi Therapy",
        help_text="If enabled, this therapy is scheduled in the 8:30 AM Vasthi slot and uses dedicated Vasthi Cottage Room allocation rules."
    )
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
    is_vamanam_slot = models.BooleanField(
        default=False,
        verbose_name="Vamanam Slot (Exclusive)",
        help_text="Designate this slot exclusively for Vamanam treatments. Regular treatments will not use this slot."
    )
    is_vasthi_slot = models.BooleanField(
        default=False,
        verbose_name="Vasthi Slot",
        help_text="Designate this slot for Vasthi treatments (default 08:30 AM)."
    )
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

# Shift Master
class ShiftMaster(models.Model):
    """
    Master list of therapist shifts.
    Example: shift-1, shift-2, etc.
    """
    shift_name = models.CharField(max_length=50, unique=True, verbose_name="Shift Name")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    def __str__(self):
        return self.shift_name

    class Meta:
        verbose_name = "Shift Master"
        verbose_name_plural = "Shift Masters"
        ordering = ["shift_name"]


class ShiftSlotMapping(models.Model):
    """
    Maps a shift to the SlotMaster records that belong to that shift.
    This supports overlap: the same SlotMaster slot can be present in multiple shifts.
    """
    shift = models.ForeignKey(ShiftMaster, on_delete=models.CASCADE, related_name="shift_slots", verbose_name="Shift")
    slot = models.ForeignKey(SlotMaster, on_delete=models.CASCADE, related_name="slot_shifts", verbose_name="Slot")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Shift Slot Mapping"
        verbose_name_plural = "Shift Slot Mappings"
        constraints = [
            models.UniqueConstraint(fields=["shift", "slot"], name="ux_shift_slot_unique"),
        ]
        indexes = [
            models.Index(fields=["shift", "is_active"], name="idx_shift_slot_shift_active"),
            models.Index(fields=["slot", "is_active"], name="idx_shift_slot_slot_active"),
        ]

    def __str__(self):
        return f"{self.shift.shift_name} -> {self.slot.slot_time.strftime('%H:%M')}"


class TherapistShiftMapping(models.Model):
    """
    Maps therapists to shifts (e.g., therapist is available for shift-1 / shift-2).
    Allocation checks both sides:
      - therapist must have a shift mapping
      - shift must contain the requested time-slot
    """
    therapist = models.ForeignKey("TherapistMaster", on_delete=models.CASCADE, related_name="shift_mappings", verbose_name="Therapist")
    shift = models.ForeignKey(ShiftMaster, on_delete=models.CASCADE, related_name="therapist_mappings", verbose_name="Shift")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "Therapist Shift Mapping"
        verbose_name_plural = "Therapist Shift Mappings"
        constraints = [
            models.UniqueConstraint(fields=["therapist", "shift"], name="ux_therapist_shift_unique"),
        ]
        indexes = [
            models.Index(fields=["shift", "is_active"], name="idx_tshift_sh_act"),
            models.Index(fields=["therapist", "is_active"], name="idx_tshift_th_act"),
        ]

    def __str__(self):
        return f"{self.therapist.therapist_code} -> {self.shift.shift_name}"

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
    is_helping_therapist = models.BooleanField(default=False, verbose_name="Mark as Helping Therapist", help_text="Designates whether this therapist is a backup/supporting Helping Therapist")
    is_deputed = models.BooleanField(default=False, verbose_name="Deputed Therapist", help_text="Designates whether this therapist is marked as deputed")
    is_active = models.BooleanField(default=True, verbose_name="Active")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    @property
    def current_deputation(self):
        """Returns the currently active approved deputation, if any."""
        import datetime
        today = datetime.date.today()
        return self.deputations.filter(
            status='approved',
            start_date__lte=today,
            end_date__gte=today
        ).first()

    @property
    def pending_deputation(self):
        """Returns pending deputation request, if any."""
        return self.deputations.filter(status='pending').order_by('-created_at').first()

    @property
    def latest_deputation(self):
        """Returns latest deputation record (any status)."""
        return self.deputations.order_by('-created_at').first()

    @property
    def approved_omitted_treatments(self):
        """Returns approved omitted treatment records."""
        return self.treatment_omissions.filter(status='approved', is_active=True).select_related('treatment', 'approved_by')

    @property
    def pending_omitted_treatments(self):
        """Returns pending omitted treatment records."""
        return self.treatment_omissions.filter(status='pending', is_active=True).select_related('treatment', 'requested_by')

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

    # Half day leave details from HRMS
    is_half_day = models.BooleanField(default=False, verbose_name="Is Half Day")
    half_day_date = models.DateField(null=True, blank=True, verbose_name="Half Day Date")
    half_day_session = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        choices=[
            ("Forenoon", "Forenoon"),
            ("Afternoon", "Afternoon"),
            ("Both", "Both"),
        ],
        verbose_name="Half Day Session",
    )
    custom_forenoon = models.BooleanField(default=False, verbose_name="Forenoon")
    custom_afternoon = models.BooleanField(default=False, verbose_name="Afternoon")

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
        hd_str = f" [Half Day: {self.half_day_session or 'Yes'}]" if self.is_half_day else ""
        return f"{self.employee_code} ({self.from_date} → {self.to_date}){hd_str}"

    @staticmethod
    def is_forenoon_slot(slot) -> bool:
        """
        Determine if the given slot is in the Forenoon (morning) session.
        AVCRI slots:
          Forenoon (slots 1-4): 06:30, 08:30, 10:00, 11:30 (< 13:00)
          Afternoon (slots 5-7): 14:30, 16:00, 17:30 (>= 13:00)
        """
        import datetime
        if slot is None:
            return False

        # If slot has slot_time attribute (SlotMaster instance)
        if hasattr(slot, "slot_time") and slot.slot_time:
            return slot.slot_time < datetime.time(13, 0)

        # If slot has slot_number attribute
        if hasattr(slot, "slot_number") and slot.slot_number:
            return int(slot.slot_number) <= 4

        # If slot is a datetime.time object
        if isinstance(slot, datetime.time):
            return slot < datetime.time(13, 0)

        # If slot is an integer
        if isinstance(slot, int):
            if 1 <= slot <= 4:
                return True
            if 5 <= slot <= 7:
                return False
            # If it's a SlotMaster PK (e.g. 6..9 vs 10..12), check from SlotMaster
            try:
                sm = SlotMaster.objects.filter(pk=slot).first()
                if sm and sm.slot_time:
                    return sm.slot_time < datetime.time(13, 0)
            except Exception:
                pass
            return slot <= 4

        # If slot is a string
        if isinstance(slot, str):
            s = slot.strip().lower()
            # Check slot number string like "1", "slot 1"
            import re
            m = re.search(r"slot\s*(\d+)", s)
            if m:
                return int(m.group(1)) <= 4
            if s.isdigit():
                return int(s) <= 4
            # Try parsing time e.g. "06:30", "14:30"
            for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
                try:
                    t = datetime.datetime.strptime(s, fmt).time()
                    return t < datetime.time(13, 0)
                except Exception:
                    continue

        return False

    def is_slot_on_leave(self, target_date, slot=None) -> bool:
        """
        Check if this leave record makes the therapist unavailable for a given target_date and slot.
        - target_date: date object or ISO string
        - slot: SlotMaster, int, time, str, or None
        Returns True if therapist is ON LEAVE (unavailable).
        Returns False if therapist is AVAILABLE.
        """
        import datetime
        if isinstance(target_date, str):
            try:
                target_date = datetime.datetime.strptime(target_date[:10], "%Y-%m-%d").date()
            except Exception:
                return True

        if not (self.from_date <= target_date <= self.to_date):
            return False

        # If not a half-day leave, entire day is on leave
        if not self.is_half_day:
            return True

        # If multi-day leave and half_day_date is specified, only that day is half-day
        if self.half_day_date and target_date != self.half_day_date:
            return True  # Other days are full leave

        # If no slot specified, caller is checking if therapist has any leave on target_date
        if slot is None:
            return True

        is_fn = EmergencyLeave.is_forenoon_slot(slot)

        # Forenoon leave: unavailable during morning/forenoon slots, available in afternoon
        if self.custom_forenoon or self.half_day_session == "Forenoon":
            return is_fn

        # Afternoon leave: available during morning/forenoon slots, unavailable in afternoon
        if self.custom_afternoon or self.half_day_session == "Afternoon":
            return not is_fn

        # Both sessions marked
        if self.half_day_session == "Both":
            return True

        # Fallback for unspecified half-day: default to afternoon leave (most common)
        return not is_fn


def is_therapist_on_emergency_leave(therapist, target_date, slot=None) -> bool:
    """
    Module helper to check if a therapist is on emergency leave on target_date for slot.
    Returns True if on leave (unavailable).
    Returns False if available.
    """
    if not therapist or not target_date:
        return False

    import datetime
    from django.db.models import Q

    if isinstance(target_date, str):
        try:
            target_date = datetime.datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        except Exception:
            return False

    emp_code = getattr(therapist, "employee_code", None)
    th_pk = getattr(therapist, "pk", None) or getattr(therapist, "id", None)

    q_filter = Q()
    if th_pk:
        q_filter |= Q(therapist_id=th_pk)
    if emp_code:
        q_filter |= Q(employee_code=str(emp_code).strip())

    if not q_filter:
        return False

    leaves = EmergencyLeave.objects.filter(
        from_date__lte=target_date,
        to_date__gte=target_date,
    ).filter(q_filter)

    if not leaves.exists():
        return False

    for el in leaves:
        if el.is_slot_on_leave(target_date, slot):
            return True

    return False


class TherapistDeputation(models.Model):
    """
    Model to track therapist deputations.
    When marked as deputed, requires destination, duration (no. of days), assigned doctor,
    and remarks. Deputations require approval from HR or Admin.
    Once approved, the therapist will not come under scheduling for the duration.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    therapist = models.ForeignKey(
        TherapistMaster,
        on_delete=models.CASCADE,
        related_name='deputations',
        verbose_name="Therapist"
    )
    destination = models.CharField(max_length=255, verbose_name="Destination")
    start_date = models.DateField(verbose_name="Start Date")
    duration_days = models.PositiveIntegerField(default=1, verbose_name="Duration (Number of Days)")
    end_date = models.DateField(verbose_name="End Date", blank=True, null=True)
    assigned_doctor = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='deputed_therapist_assignments',
        verbose_name="Assigned Doctor"
    )
    assigned_doctor_name = models.CharField(max_length=255, blank=True, null=True, verbose_name="Assigned Doctor Name")
    remarks = models.TextField(blank=True, null=True, verbose_name="Relevant Deputation Details (Remarks)")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True, verbose_name="Approval Status")
    requested_by = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_deputations',
        verbose_name="Requested By"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    approved_by = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_deputations',
        verbose_name="Approved/Rejected By"
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="Approved/Rejected At")
    approval_remarks = models.TextField(blank=True, null=True, verbose_name="Approval/Rejection Remarks")

    class Meta:
        verbose_name = "Therapist Deputation"
        verbose_name_plural = "Therapist Deputations"
        ordering = ['-created_at']

    def calculate_end_date(self):
        import datetime
        st = self.start_date
        if not st:
            st = datetime.date.today()
        elif isinstance(st, str):
            try:
                st = datetime.datetime.strptime(st[:10], "%Y-%m-%d").date()
            except Exception:
                st = datetime.date.today()
        days = max(1, int(self.duration_days or 1))
        return st + datetime.timedelta(days=days - 1)

    def save(self, *args, **kwargs):
        import datetime
        if not self.start_date:
            self.start_date = datetime.date.today()
        self.end_date = self.calculate_end_date()
        if self.assigned_doctor and not self.assigned_doctor_name:
            self.assigned_doctor_name = self.assigned_doctor.get_full_name() or self.assigned_doctor.username
        super().save(*args, **kwargs)

    def is_active_for_date(self, target_date):
        if self.status != 'approved':
            return False
        import datetime
        if isinstance(target_date, str):
            try:
                target_date = datetime.datetime.strptime(target_date[:10], "%Y-%m-%d").date()
            except Exception:
                return False
        return self.start_date <= target_date <= self.end_date

    def __str__(self):
        return f"{self.therapist.therapist_name} -> {self.destination} ({self.duration_days} days) [{self.status}]"


def is_therapist_deputed(therapist, target_date=None) -> bool:
    """
    Check if a therapist is on approved deputation covering target_date.
    Returns True if therapist is currently on approved deputation (unavailable for scheduling).
    Returns False if available.
    """
    if not therapist:
        return False
    import datetime
    if target_date is None:
        target_date = datetime.date.today()
    elif isinstance(target_date, str):
        try:
            target_date = datetime.datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        except Exception:
            return False
    elif hasattr(target_date, 'date') and callable(target_date.date):
        target_date = target_date.date()

    th_pk = getattr(therapist, "pk", None) or getattr(therapist, "id", None)
    if not th_pk and isinstance(therapist, (int, str)):
        try:
            th_pk = int(therapist)
        except (ValueError, TypeError):
            th_pk = None
    if not th_pk:
        return False

    return TherapistDeputation.objects.filter(
        therapist_id=th_pk,
        status='approved',
        start_date__lte=target_date,
        end_date__gte=target_date
    ).exists()


def get_deputed_therapist_ids_for_date(target_date=None):
    """
    Return set of therapist IDs that are on approved deputation on target_date.
    """
    import datetime
    if target_date is None:
        target_date = datetime.date.today()
    elif isinstance(target_date, str):
        try:
            target_date = datetime.datetime.strptime(target_date[:10], "%Y-%m-%d").date()
        except Exception:
            return set()
    elif hasattr(target_date, 'date') and callable(target_date.date):
        target_date = target_date.date()

    return set(TherapistDeputation.objects.filter(
        status='approved',
        start_date__lte=target_date,
        end_date__gte=target_date
    ).values_list('therapist_id', flat=True))


def can_request_deputation(user) -> bool:
    """
    Check if a user is authorized to request a therapist deputation.
    Rule: Only the scheduling team and therapist HOD (plus super_admin) can request.
    """
    if not user or not user.is_authenticated:
        return False

    role = (getattr(user, 'role', '') or '').lower()
    if role in ['scheduling_staff', 'therapist_hod', 'super_admin']:
        return True

    # Custom role checks
    custom_role = getattr(user, 'custom_role', None)
    if custom_role:
        c_name = (getattr(custom_role, 'name', '') or '').lower()
        c_disp = (getattr(custom_role, 'display_name', '') or '').lower()
        if any(term in c_name or term in c_disp for term in ['scheduling', 'sheduling', 'hod']):
            return True

    # Profile designation/department checks
    staff_profile = getattr(user, 'staff_profile', None)
    if staff_profile:
        s_dept = (getattr(staff_profile, 'department', '') or '').lower()
        s_desig = (getattr(staff_profile, 'designation', '') or '').lower()
        if any(term in s_dept or term in s_desig for term in ['scheduling', 'sheduling', 'hod', 'head']):
            return True

    therapist_profile = getattr(user, 'therapist_profile', None)
    if therapist_profile:
        t_dept = (getattr(therapist_profile, 'department', '') or '').lower()
        t_grade = (getattr(therapist_profile, 'therapist_grade', '') or '').lower()
        if any(term in t_dept or term in t_grade for term in ['hod', 'head']):
            return True

    return False


def can_approve_deputation(user) -> bool:
    """
    Check if a user is authorized to approve or reject a therapist deputation.
    Rule: Approval only given by Admin (Administrative GM / Management) and HR (not Super Admin).
    """
    if not user or not user.is_authenticated:
        return False

    role = (getattr(user, 'role', '') or '').lower()
    if role in ['admin', 'hr']:
        return True

    # Custom role checks for Admin / GM / HR
    custom_role = getattr(user, 'custom_role', None)
    if custom_role:
        c_name = (getattr(custom_role, 'name', '') or '').lower()
        c_disp = (getattr(custom_role, 'display_name', '') or '').lower()
        if any(term in c_name or term in c_disp for term in ['hr', 'human resource', 'admin', 'gm', 'general manager']):
            if 'super' not in c_name and 'super' not in c_disp:
                return True

    admin_profile = getattr(user, 'admin_profile', None)
    if admin_profile and role != 'super_admin':
        return True

    return False


class TherapistTreatmentOmission(models.Model):
    """
    Model to track therapists omitting particular treatments on special request.
    Therapists/staff select treatments to omit in Therapist Master edit.
    Requests are sent for approval to HR and Admin.
    Once approved, their name will not be scheduled with those treatments
    in the scheduling list (only for those treatments their name will not be there).
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    therapist = models.ForeignKey(
        TherapistMaster,
        on_delete=models.CASCADE,
        related_name='treatment_omissions',
        verbose_name="Therapist"
    )
    treatment = models.ForeignKey(
        TherapyMaster,
        on_delete=models.CASCADE,
        related_name='therapist_omissions',
        verbose_name="Treatment / Therapy"
    )
    reason = models.TextField(blank=True, null=True, verbose_name="Reason for Special Request / Omission")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name="Approval Status"
    )
    requested_by = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='requested_treatment_omissions',
        verbose_name="Requested By"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    approved_by = models.ForeignKey(
        'authentication.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_treatment_omissions',
        verbose_name="Approved/Rejected By"
    )
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name="Approved/Rejected At")
    approval_remarks = models.TextField(blank=True, null=True, verbose_name="Approval/Rejection Remarks")
    batch_id = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Request Batch ID",
        help_text="Groups all treatments submitted together in a single request"
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        verbose_name = "Therapist Treatment Omission"
        verbose_name_plural = "Therapist Treatment Omissions"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['treatment', 'status', 'is_active'], name='idx_tto_tr_st_act'),
            models.Index(fields=['therapist', 'status', 'is_active'], name='idx_tto_th_st_act'),
            models.Index(fields=['batch_id', 'status', 'is_active'], name='idx_tto_batch_st_act'),
        ]

    def __str__(self):
        return f"{self.therapist.therapist_name} - Omit {self.treatment.therapy_name} [{self.status}]"


def is_therapist_omitted_for_treatment(therapist, treatment) -> bool:
    """
    Check if a therapist has an approved omission for a specific treatment.
    Returns True if therapist is omitted (must NOT be scheduled for this treatment).
    Returns False otherwise.
    """
    if not therapist or not treatment:
        return False

    th_id = None
    th_code = None
    if isinstance(therapist, TherapistMaster):
        th_id = therapist.pk
        th_code = therapist.therapist_code
    elif hasattr(therapist, 'pk') and getattr(therapist, 'pk', None):
        th_id = therapist.pk
        th_code = getattr(therapist, 'therapist_code', None)
    elif isinstance(therapist, int):
        th_id = therapist
    elif isinstance(therapist, str):
        th_str = therapist.strip()
        if th_str.isdigit():
            th_id = int(th_str)
        else:
            th_code = th_str

    tr_id = None
    tr_code = None
    tr_name = None
    if isinstance(treatment, TherapyMaster):
        tr_id = treatment.pk
        tr_code = treatment.therapy_code
        tr_name = treatment.therapy_name
    elif hasattr(treatment, 'pk') and getattr(treatment, 'pk', None) and hasattr(treatment, 'therapy_name'):
        tr_id = treatment.pk
        tr_code = getattr(treatment, 'therapy_code', None)
        tr_name = getattr(treatment, 'therapy_name', None)
    elif isinstance(treatment, int):
        tr_id = treatment
    elif isinstance(treatment, str):
        tr_str = treatment.strip()
        if tr_str.isdigit():
            tr_id = int(tr_str)
        else:
            tr_code = tr_str
            tr_name = tr_str

    from django.db.models import Q
    th_q = Q()
    if th_id:
        th_q |= Q(therapist_id=th_id)
    if th_code:
        th_q |= Q(therapist__therapist_code__iexact=th_code)
    if not th_q:
        return False

    tr_q = Q()
    if tr_id:
        tr_q |= Q(treatment_id=tr_id)
    if tr_code:
        tr_q |= Q(treatment__therapy_code__iexact=tr_code)
    if tr_name:
        tr_q |= Q(treatment__therapy_name__iexact=tr_name)
    if not tr_q:
        return False

    return TherapistTreatmentOmission.objects.filter(
        th_q,
        tr_q,
        status='approved',
        is_active=True
    ).exists()


def get_omitted_therapist_ids_for_treatment(treatment) -> set:
    """
    Return a set of TherapistMaster IDs who have approved omissions for `treatment`.
    """
    if not treatment:
        return set()
    from django.db.models import Q
    tr_q = Q()
    if isinstance(treatment, TherapyMaster):
        tr_q = Q(treatment_id=treatment.pk)
    elif hasattr(treatment, 'pk') and getattr(treatment, 'pk', None) and hasattr(treatment, 'therapy_name'):
        tr_q = Q(treatment_id=treatment.pk)
    elif isinstance(treatment, int):
        tr_q = Q(treatment_id=treatment)
    elif isinstance(treatment, str):
        treatment_clean = treatment.strip()
        if treatment_clean.isdigit():
            tr_q = Q(treatment_id=int(treatment_clean))
        else:
            tr_q = Q(treatment__therapy_code__iexact=treatment_clean) | Q(treatment__therapy_name__iexact=treatment_clean)
    if not tr_q:
        return set()

    return set(TherapistTreatmentOmission.objects.filter(
        tr_q,
        status='approved',
        is_active=True
    ).values_list('therapist_id', flat=True))


def get_omitted_therapist_codes_for_treatment(treatment) -> set:
    """
    Return a set of therapist_code strings who have approved omissions for `treatment`.
    """
    if not treatment:
        return set()
    from django.db.models import Q
    tr_q = Q()
    if isinstance(treatment, TherapyMaster):
        tr_q = Q(treatment_id=treatment.pk)
    elif hasattr(treatment, 'pk') and getattr(treatment, 'pk', None) and hasattr(treatment, 'therapy_name'):
        tr_q = Q(treatment_id=treatment.pk)
    elif isinstance(treatment, int):
        tr_q = Q(treatment_id=treatment)
    elif isinstance(treatment, str):
        treatment_clean = treatment.strip()
        if treatment_clean.isdigit():
            tr_q = Q(treatment_id=int(treatment_clean))
        else:
            tr_q = Q(treatment__therapy_code__iexact=treatment_clean) | Q(treatment__therapy_name__iexact=treatment_clean)
    if not tr_q:
        return set()

    return set(TherapistTreatmentOmission.objects.filter(
        tr_q,
        status='approved',
        is_active=True
    ).values_list('therapist__therapist_code', flat=True))


def can_approve_treatment_omission(user) -> bool:
    """
    Check if a user is authorized to approve or reject a therapist treatment omission.
    Rule: Approval only given by Admin (Administrative GM / Management) and HR.
    """
    return can_approve_deputation(user)


class TherapistOmissionRequestGroup:
    """
    Encapsulates all treatments submitted together in a single request for a therapist.
    """
    def __init__(self, key, first_omission):
        self.key = key
        self.batch_id = first_omission.batch_id or f"TOR-{first_omission.id}"
        self.raw_batch_id = first_omission.batch_id
        self.therapist = first_omission.therapist
        self.reason = first_omission.reason
        self.status = first_omission.status
        self.requested_by = first_omission.requested_by
        self.created_at = first_omission.created_at
        self.approved_by = first_omission.approved_by
        self.approved_at = first_omission.approved_at
        self.approval_remarks = first_omission.approval_remarks
        self.omissions = []
        self.treatments = []
        self.first_id = first_omission.id

    def add_omission(self, omission):
        self.omissions.append(omission)
        self.treatments.append(omission.treatment)
        if omission.created_at and (not self.created_at or omission.created_at > self.created_at):
            self.created_at = omission.created_at
        if omission.approved_at and (not self.approved_at or omission.approved_at > self.approved_at):
            self.approved_at = omission.approved_at
        if omission.approved_by and not self.approved_by:
            self.approved_by = omission.approved_by
        if omission.approval_remarks and not self.approval_remarks:
            self.approval_remarks = omission.approval_remarks

    @property
    def total_count(self):
        return len(self.omissions)

    @property
    def hard_count(self):
        return sum(1 for t in self.treatments if (getattr(t, 'therapy_category', None) or '').strip().lower() == 'hard')

    @property
    def medium_count(self):
        return sum(1 for t in self.treatments if (getattr(t, 'therapy_category', None) or '').strip().lower() == 'medium')

    @property
    def easy_count(self):
        return sum(1 for t in self.treatments if (getattr(t, 'therapy_category', None) or '').strip().lower() == 'easy')

    @property
    def other_count(self):
        return self.total_count - (self.hard_count + self.medium_count + self.easy_count)

    @property
    def treatments_summary(self):
        names = [t.therapy_name for t in self.treatments]
        if len(names) <= 3:
            return ", ".join(names)
        return f"{', '.join(names[:3])} + {len(names) - 3} more"

    @property
    def action_identifier(self):
        return self.raw_batch_id or str(self.first_id)


def group_omissions_by_request(omissions_queryset):
    """
    Groups a queryset or iterable of TherapistTreatmentOmission instances
    into logical requests (by batch_id, or by therapist+date fallback).
    Preserves ordering (newest first).
    """
    if not omissions_queryset:
        return []

    groups = {}
    for om in omissions_queryset:
        if om.batch_id:
            key = f"BATCH_{om.batch_id}"
        else:
            time_key = om.created_at.strftime('%Y%m%d%H%M') if om.created_at else 'unknown'
            key = f"LEGACY_{om.therapist_id}_{time_key}_{(om.reason or '').strip()[:20]}"

        if key not in groups:
            groups[key] = TherapistOmissionRequestGroup(key, om)
        groups[key].add_omission(om)

    return list(groups.values())

