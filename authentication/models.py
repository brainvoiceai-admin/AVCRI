from django.db import models

# Create your models here.
from django.contrib.auth.models import AbstractUser
from django.db import models

class Module(models.Model):
    """Model to define available modules in the system"""
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    url_name = models.CharField(max_length=100, help_text="URL name for the module")
    icon = models.CharField(max_length=50, default="📋", help_text="Icon for the module")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0, help_text="Display order")
    
    class Meta:
        ordering = ['order', 'name']
    
    def __str__(self):
        return self.display_name

class Role(models.Model):
    """Model to define user roles with module permissions"""
    name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    modules = models.ManyToManyField(Module, blank=True, help_text="Modules accessible to this role")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return self.display_name

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
    custom_role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, 
                                   help_text="Custom role with specific module permissions")
    mobile = models.CharField(max_length=15, null=True, blank=True)
    
    GENDER_CHOICES = [
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other'),
    ]
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='male', 
                             help_text="User's gender")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def get_accessible_modules(self):
        """Get modules accessible to this user"""
        if self.role == "super_admin":
            # Super admin has access to all modules
            return Module.objects.filter(is_active=True)
        elif self.custom_role:
            # User has a custom role with specific module permissions
            return self.custom_role.modules.filter(is_active=True)
        else:
            # Use default role-based module access
            return self.get_default_modules_for_role()
    
    def get_default_modules_for_role(self):
        """Get default modules for standard roles"""
        # This will be implemented based on the current navigation logic
        module_mapping = {
            "doctor": ["add_therapy", "add_prescription", "reports", "treatment_schedule"],
            "therapist": ["therapy_schedule"],
            "patient": ["patient_profiles", "patient_dashboard", "patient_feedback"],
            "nurse": ["nurse_dashboard"],
            "ip_pharmacy_staff": ["ip_pharmacy", "procurement_dashboard"],
            "hr": ["hr_dashboard"],
            "housekeeping_staff": ["housekeeping"],
            "admin": ["user_management", "demand_prediction", "audit_log", "master_tables"],
        }
        
        accessible_modules = module_mapping.get(self.role, [])
        return Module.objects.filter(name__in=accessible_modules, is_active=True)
    
    def clean(self):
        """Custom validation for the model"""
        super().clean()
        
        # Validate mobile number uniqueness when provided
        if self.mobile:
            # Check if another user has the same mobile number
            existing_user = CustomUser.objects.filter(mobile=self.mobile).exclude(pk=self.pk)
            if existing_user.exists():
                from django.core.exceptions import ValidationError
                raise ValidationError({'mobile': 'A user with this mobile number already exists.'})
    
    def has_module_access(self, module_name):
        """Check if user has access to a specific module"""
        accessible_modules = self.get_accessible_modules()
        return accessible_modules.filter(name=module_name).exists()

class AuditLog(models.Model):
    """Model to track system audit logs"""
    ACTION_CHOICES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('create', 'Create'),
        ('update', 'Update'),
        ('delete', 'Delete'),
        ('access', 'Access'),
        ('export', 'Export'),
        ('import', 'Import'),
        ('error', 'Error'),
        # Therapy-specific actions
        ('allocate_therapy', 'Allocate Therapy'),
        ('update_therapy', 'Update Therapy'),
        ('cancel_therapy', 'Cancel Therapy'),
        ('resume_therapy', 'Resume Therapy'),
        ('remove_item', 'Remove Item'),
        ('view_therapy', 'View Therapy'),
    ]
    
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('warning', 'Warning'),
    ]
    
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='auth_audit_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    description = models.TextField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='success')
    timestamp = models.DateTimeField(auto_now_add=True)
    object_type = models.CharField(max_length=100, blank=True, help_text="Type of object affected (e.g., User, Role, Module)")
    object_id = models.CharField(max_length=100, blank=True, help_text="ID of the affected object")
    additional_data = models.JSONField(null=True, blank=True, help_text="Additional data in JSON format")
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Audit Log'
        verbose_name_plural = 'Audit Logs'
    
    def __str__(self):
        return f"{self.user.username if self.user else 'System'} - {self.get_action_display()} - {self.timestamp}"


# Profile Models for Different User Roles
class PatientProfile(models.Model):
    """Profile model for Patient users"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='patient_profile')
    patient_reg_no = models.CharField(max_length=50, unique=True, verbose_name="Patient Registration Number")
    date_of_birth = models.DateField(null=True, blank=True, verbose_name="Date of Birth")
    gender = models.CharField(max_length=10, choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')], null=True, blank=True)
    address = models.TextField(null=True, blank=True, verbose_name="Address")
    emergency_contact = models.CharField(max_length=100, null=True, blank=True, verbose_name="Emergency Contact")
    emergency_phone = models.CharField(max_length=15, null=True, blank=True, verbose_name="Emergency Phone")
    medical_history = models.TextField(null=True, blank=True, verbose_name="Medical History")
    allergies = models.TextField(null=True, blank=True, verbose_name="Allergies")
    is_vip = models.BooleanField(default=False, verbose_name="VIP Patient")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Patient Profile"
        verbose_name_plural = "Patient Profiles"
        ordering = ['patient_reg_no']

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.patient_reg_no})"


class TherapistProfile(models.Model):
    """Profile model for Therapist users"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='therapist_profile')
    therapist_code = models.CharField(max_length=20, unique=True, verbose_name="Therapist Code")
    employee_code = models.CharField(max_length=50, unique=True, verbose_name="Employee Code")
    therapist_grade = models.CharField(max_length=100, verbose_name="Therapist Grade")
    department = models.CharField(max_length=100, null=True, blank=True, verbose_name="Department")
    specialization = models.CharField(max_length=200, null=True, blank=True, verbose_name="Specialization")
    is_bathing_therapist = models.BooleanField(default=True, verbose_name="Bathing Therapist")
    joining_date = models.DateField(null=True, blank=True, verbose_name="Joining Date")
    qualification = models.TextField(null=True, blank=True, verbose_name="Qualification")
    experience_years = models.IntegerField(null=True, blank=True, verbose_name="Experience (Years)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Therapist Profile"
        verbose_name_plural = "Therapist Profiles"
        ordering = ['therapist_code']

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.therapist_code})"


class DoctorProfile(models.Model):
    """Profile model for Doctor users"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='doctor_profile')
    doctor_id = models.CharField(max_length=20, unique=True, verbose_name="Doctor ID")
    specialization = models.CharField(max_length=200, verbose_name="Specialization")
    department = models.CharField(max_length=100, verbose_name="Department")
    qualification = models.TextField(verbose_name="Qualification")
    experience_years = models.IntegerField(verbose_name="Experience (Years)")
    license_number = models.CharField(max_length=50, null=True, blank=True, verbose_name="Medical License Number")
    consultation_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, verbose_name="Consultation Fee")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Doctor Profile"
        verbose_name_plural = "Doctor Profiles"
        ordering = ['doctor_id']

    def __str__(self):
        return f"Dr. {self.user.get_full_name()} ({self.doctor_id})"


class AdminProfile(models.Model):
    """Profile model for Admin users"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='admin_profile')
    admin_id = models.CharField(max_length=20, unique=True, verbose_name="Admin ID")
    department = models.CharField(max_length=100, verbose_name="Department")
    designation = models.CharField(max_length=100, verbose_name="Designation")
    reporting_manager = models.CharField(max_length=100, null=True, blank=True, verbose_name="Reporting Manager")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Admin Profile"
        verbose_name_plural = "Admin Profiles"
        ordering = ['admin_id']

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.admin_id})"


class NurseProfile(models.Model):
    """Profile model for Nurse users"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='nurse_profile')
    nurse_id = models.CharField(max_length=20, unique=True, verbose_name="Nurse ID")
    department = models.CharField(max_length=100, verbose_name="Department")
    qualification = models.CharField(max_length=200, verbose_name="Qualification")
    experience_years = models.IntegerField(null=True, blank=True, verbose_name="Experience (Years)")
    shift = models.CharField(max_length=50, null=True, blank=True, verbose_name="Shift")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Nurse Profile"
        verbose_name_plural = "Nurse Profiles"
        ordering = ['nurse_id']

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.nurse_id})"


class StaffProfile(models.Model):
    """Profile model for other staff users (Scheduling, Pharmacy, Finance, HR, Housekeeping)"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='staff_profile')
    staff_id = models.CharField(max_length=20, unique=True, verbose_name="Staff ID")
    department = models.CharField(max_length=100, verbose_name="Department")
    designation = models.CharField(max_length=100, verbose_name="Designation")
    reporting_manager = models.CharField(max_length=100, null=True, blank=True, verbose_name="Reporting Manager")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Staff Profile"
        verbose_name_plural = "Staff Profiles"
        ordering = ['staff_id']

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.staff_id})"