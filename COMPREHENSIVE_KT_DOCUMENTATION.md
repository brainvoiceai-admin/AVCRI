# Comprehensive Knowledge Transfer (KT) Documentation
## AVCRI System - Complete Implementation Guide


**Documentation Scope:** All modules, models, views, and recent implementations

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Role and Module Management System](#2-role-and-module-management-system)
3. [Authentication & User Management](#3-authentication--user-management)
4. [Patient Management](#4-patient-management)
5. [Therapy Management](#5-therapy-management)
6. [Prescription Management](#6-prescription-management)
7. [Therapist Management](#7-therapist-management)
8. [Master Tables Management](#8-master-tables-management)
9. [Scheduling System](#9-scheduling-system)
10. [Views and API Endpoints](#10-views-and-api-endpoints)
11. [Recent Fixes and Improvements](#11-recent-fixes-and-improvements)
12. [Best Practices and Guidelines](#12-best-practices-and-guidelines)

---

## 1. System Overview

### 1.1 Architecture
The AVCRI system is a Django-based healthcare management platform with the following key components:

- **Frontend:** Django Templates with Bootstrap 5
- **Backend:** Django 5.2.6 with SQLite (development) / SQL Server (production)
- **Authentication:** Custom user system with role-based access control
- **Modules:** Modular design with dynamic navigation based on user roles

### 1.2 Application Structure

```
AVCRI/
├── authentication/      # User management, roles, modules
├── Patient/            # Patient data and history
├── Sheduling/          # Therapy and prescription scheduling
├── masters/            # Master data management
├── MySql_Data_pull/    # External database integration
├── predictor/          # Demand forecasting
└── templates/          # HTML templates
```

---

## 2. Role and Module Management System

### 2.1 Overview
The system uses a **simplified role-based access control (RBAC)** where:
- Each user has **one role** (either default role or custom role)
- Roles can have **multiple modules** assigned
- Modules control what pages/features users can access
- Super Admin has access to all modules

### 2.2 Models

#### 2.2.1 Module Model (`authentication/models.py`)
```python
class Module(models.Model):
    name = models.CharField(max_length=100, unique=True)  # Internal name
    display_name = models.CharField(max_length=100)      # Display name
    description = models.TextField(blank=True)
    url_name = models.CharField(max_length=100)           # URL pattern name
    icon = models.CharField(max_length=50, default="📋")
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)        # Display order
```

**Key Fields:**
- `name`: Unique identifier (e.g., "add_therapy", "prescription_scheduling")
- `url_name`: Django URL name or path (e.g., "sheduling:patient_therapy", "/Masters/procured")
- `is_active`: Controls if module is available for assignment

#### 2.2.2 Role Model (`authentication/models.py`)
```python
class Role(models.Model):
    name = models.CharField(max_length=100, unique=True)  # e.g., "scheduling_staff"
    display_name = models.CharField(max_length=100)       # e.g., "Scheduling Staff"
    description = models.TextField(blank=True)
    modules = models.ManyToManyField(Module, blank=True)  # Assigned modules
    is_active = models.BooleanField(default=True)
```

**Key Relationships:**
- `modules`: Many-to-many relationship with Module
- One role can have multiple modules
- One module can be assigned to multiple roles

#### 2.2.3 CustomUser Model (`authentication/models.py`)
```python
class CustomUser(AbstractUser):
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="therapist")
    custom_role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True)
    mobile = models.CharField(max_length=15, null=True, blank=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='male')
    
    def get_accessible_modules(self):
        """Returns modules accessible to this user"""
        if self.role == "super_admin":
            return Module.objects.filter(is_active=True).order_by('order', 'name')
        elif self.custom_role:
            return self.custom_role.modules.filter(is_active=True).order_by('order', 'name')
        else:
            return self.get_default_modules_for_role()
```

**Key Methods:**
- `get_accessible_modules()`: Returns all modules user can access
- `has_module_access(module_name)`: Checks if user has access to specific module
- `is_super_admin()`: Checks if user is super admin

**Role Types:**
1. **Default Roles:** Predefined roles (doctor, therapist, nurse, etc.)
2. **Custom Roles:** Created by Super Admin with specific module assignments

### 2.3 Views

#### 2.3.1 Role Management (`authentication/views.py`)

**`role_management(request)`**
- Lists all roles
- URL: `/authentication/role-management/`
- Access: Super Admin only

**`create_role(request)`**
- Creates new role with module assignments
- POST: Creates role and assigns modules using `role.modules.set(modules)`
- URL: `/authentication/create-role/`

**`edit_role(request, role_id)`**
- Updates role details and module assignments
- POST: Updates modules using `role.modules.set(modules)`
- URL: `/authentication/edit-role/<role_id>/`

**`delete_role(request, role_id)`**
- Deletes role (with confirmation if users assigned)
- Shows confirmation page if users are assigned
- Force delete removes role assignments from users
- URL: `/authentication/delete-role/<role_id>/`

#### 2.3.2 Module Management (`authentication/views.py`)

**`module_management(request)`**
- Lists all modules
- Actions: Create, Update, Delete
- Delete: Automatically removes module from all roles before deletion
- URL: `/authentication/module-management/`

#### 2.3.3 User Role Assignment (`authentication/views.py`)

**`user_role_assignment(request)`**
- Assigns custom roles to users
- Filters: Search, Status, Default Role, Custom Role
- POST: Updates `user.custom_role`
- URL: `/authentication/user-role-assignment/`

### 2.4 Navigation System

The navigation (`templates/dashboards/nav.html`) dynamically displays modules based on:
1. User's accessible modules from `get_accessible_modules()`
2. Module categorization (Patient Management, Therapy & Prescription, Scheduling, etc.)
3. "All Modules" section shows all assigned modules

**Key Sections:**
- Masters (Super Admin only)
- Patient Management
- Therapy & Prescription
- Scheduling
- Dashboards
- Reports & Analytics
- Administration
- All Modules (shows all assigned modules)

---

## 3. Authentication & User Management

### 3.1 User Profiles

Each user role has a corresponding profile model:

#### 3.1.1 PatientProfile (`authentication/models.py`)
```python
class PatientProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    patient_reg_no = models.CharField(max_length=50, unique=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10)
    address = models.TextField(null=True, blank=True)
    emergency_contact = models.CharField(max_length=100, null=True, blank=True)
    medical_history = models.TextField(null=True, blank=True)
    allergies = models.TextField(null=True, blank=True)
    is_vip = models.BooleanField(default=False)
```

#### 3.1.2 TherapistProfile (`authentication/models.py`)
```python
class TherapistProfile(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    therapist_code = models.CharField(max_length=20, unique=True)
    employee_code = models.CharField(max_length=50, unique=True)
    therapist_grade = models.CharField(max_length=100)
    department = models.CharField(max_length=100, null=True, blank=True)
    specialization = models.CharField(max_length=200, null=True, blank=True)
    is_bathing_therapist = models.BooleanField(default=True)
    joining_date = models.DateField(null=True, blank=True)
    qualification = models.TextField(null=True, blank=True)
    experience_years = models.IntegerField(null=True, blank=True)
```

#### 3.1.3 Other Profiles
- `DoctorProfile`: Doctor-specific information
- `AdminProfile`: Admin-specific information
- `NurseProfile`: Nurse-specific information
- `StaffProfile`: Generic staff profile

### 3.2 User Management Views

#### 3.2.1 Manage User (`authentication/views.py`)

**`Manage_user(request)`**
- Main user management interface
- Actions: Create, Update, Delete, Activate/Deactivate
- Role-specific fields:
  - **Patient:** Patient Registration Number
  - **Therapist:** Therapist Code, Employee Code
  - **IP Pharmacy Staff:** Department
- URL: `/authentication/Manage_user/dashboard/`

**Key Features:**
- Supports both default roles and custom roles
- Automatically creates appropriate profile based on role
- Validates unique constraints (therapist_code, patient_reg_no, etc.)
- Updates therapist master when therapist role is assigned

**Therapist Code Field Logic:**
- Shows when `role == 'therapist'` OR `custom_role.name` contains 'therapist'
- Required field for therapist role
- Creates `TherapistProfile` and `TherapistMaster` records

---

## 4. Patient Management

### 4.1 Patient Models

#### 4.1.1 PatientSnapshot (`Sheduling/models.py`)
```python
class PatientSnapshot(models.Model):
    pat_reg_no = models.CharField(max_length=50, unique=True, primary_key=True)
    pat_op_reg_no = models.CharField(max_length=50, unique=True, null=True, blank=True)
    pat_name = models.CharField(max_length=255)
    pat_age = models.IntegerField(null=True, blank=True)
    pat_gender = models.CharField(max_length=10, null=True, blank=True)
    pat_type = models.CharField(max_length=20, null=True, blank=True)  # IP/OP
    room_no = models.CharField(max_length=50, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

**Purpose:** Local snapshot of patient data (synced from external database)

#### 4.1.2 PatientHistory (`Patient/models.py`)
```python
class PatientHistory(models.Model):
    patient_reg_no = models.CharField(max_length=50)
    visit_date = models.DateField()
    therapy_details = models.TextField(null=True, blank=True)
    prescription_details = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

**Purpose:** Historical patient treatment records

### 4.2 Patient Views

#### 4.2.1 Patient Lookup (`Patient/views.py`)
- Search patients by registration number
- Displays patient details
- URL: `/patient_lookup/`

#### 4.2.2 Patient List (`Patient/views.py`)
- Lists all patients
- Shows patient sessions and bookings
- URL: `/patients/`

---

## 5. Therapy Management

### 5.1 Therapy Models

#### 5.1.1 TherapyAllocation (`Sheduling/models.py`)
```python
class TherapyAllocation(models.Model):
    patient = models.ForeignKey(PatientSnapshot, on_delete=models.CASCADE)
    therapy_code = models.CharField(max_length=50)
    therapy_name = models.CharField(max_length=255)
    ext_int = models.CharField(max_length=50, blank=True)  # External/Internal
    timeslot = models.ForeignKey('masters.SlotMaster', null=True, blank=True)
    room = models.ForeignKey(TreatmentRoom, null=True, blank=True)
    items_groups = models.JSONField(default=list)  # Item groups snapshot
    oil_class = models.CharField(max_length=100, blank=True)
    usage = models.CharField(max_length=100, blank=True)
    procured_from = models.CharField(max_length=200, blank=True)
    from_date = models.DateField()
    to_date = models.DateField()
    days = models.PositiveIntegerField()
    required_therapist_roles = models.JSONField(default=list, blank=True)
    allocated_by = models.ForeignKey(CustomUser, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    cancelled_date_from = models.DateField(null=True, blank=True)
    cancelled_date_to = models.DateField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
```

**Status Choices:**
- `draft`: Created but not scheduled
- `allocated`: Scheduled and assigned
- `cancelled`: Cancelled (partially or fully)
- `failed`: Allocation failed

#### 5.1.2 Booking (`Sheduling/models.py`)
```python
class Booking(models.Model):
    allocation = models.ForeignKey(TherapyAllocation, on_delete=models.CASCADE)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    booking_date = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
```

**Purpose:** One booking per date per allocation

#### 5.1.3 BookingItem (`Sheduling/models.py`)
```python
class BookingItem(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE)
    item_code = models.CharField(max_length=50)
    item_name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50, blank=True)
    procured = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
```

**Purpose:** Individual items within a booking

#### 5.1.4 BookingAssignment (`Sheduling/models.py`)
```python
class BookingAssignment(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE)
    therapist = models.ForeignKey('masters.TherapistMaster', on_delete=models.CASCADE)
    role = models.CharField(max_length=50)  # senior, junior, etc.
    assigned_at = models.DateTimeField(auto_now_add=True)
```

**Purpose:** Assigns therapists to bookings

### 5.2 Therapy Views

#### 5.2.1 Therapy Entry (`Sheduling/views.py`)

**`therapy_entry(request)`**
- Main therapy allocation interface
- Template: `templates/updated_dash/therapy_entry.html`
- URL: `/sheduling/therapy-entry/`

**Features:**
- Patient selection and search
- Therapy selection from TherapyMaster
- Item group management
- Date range selection
- Slot and room assignment
- Create, Edit, Cancel, Resume operations

**API Endpoints:**
- `patient_therapies`: Returns patient's therapies with status_summary
- `allocate_therapy`: Creates new therapy allocation
- `update_therapy`: Updates existing allocation
- `cancel_therapy`: Cancels therapy for date range
- `resume_therapy`: Resumes cancelled therapy for date range

**Status Summary:**
```javascript
{
    "draft": 2,      // Number of draft bookings
    "allocated": 5,  // Number of allocated bookings
    "cancelled": 3,  // Number of cancelled bookings
    "failed": 0      // Number of failed bookings
}
```

**Key Fixes:**
1. **Resume Button Visibility:** Now checks `status_summary.cancelled > 0` instead of overall status
2. **Patient Change Detection:** Resets form when patient changes during edit mode
3. **Data Refresh:** Reloads therapies from server after cancel/resume operations

---

## 6. Prescription Management

### 6.1 Prescription Models

#### 6.1.1 PrescriptionAllocation (`Sheduling/models.py`)
```python
class PrescriptionAllocation(models.Model):
    patient = models.ForeignKey(PatientSnapshot, on_delete=models.CASCADE)
    from_date = models.DateField()
    to_date = models.DateField()
    days = models.PositiveIntegerField()
    procured_from = models.CharField(max_length=200, blank=True)
    scope = models.CharField(max_length=100, blank=True)  # Internal/External
    items_groups = models.JSONField(default=list)
    allocated_by = models.ForeignKey(CustomUser, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    cancelled_date_from = models.DateField(null=True, blank=True)
    cancelled_date_to = models.DateField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
```

#### 6.1.2 PrescriptionScheduling (`Sheduling/models.py`)
```python
class PrescriptionScheduling(models.Model):
    allocation = models.ForeignKey(PrescriptionAllocation, on_delete=models.CASCADE)
    date = models.DateField()
    time = models.ForeignKey('masters.PrescriptionTime', null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    scheduled_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
```

#### 6.1.3 PrescriptionItem (`Sheduling/models.py`)
```python
class PrescriptionItem(models.Model):
    allocation = models.ForeignKey(PrescriptionAllocation, on_delete=models.CASCADE)
    item_code = models.CharField(max_length=50)
    item_name = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    unit = models.CharField(max_length=50, blank=True)
    procured_from = models.CharField(max_length=200, blank=True)
```

### 6.2 Prescription Views

#### 6.2.1 Prescription Entry (`Sheduling/views.py`)

**`prescription_entry_page(request)`**
- Main prescription allocation interface
- Template: `templates/updated_dash/prescription_entry.html`
- URL: `/sheduling/prescriptions/`

**Features:**
- Similar to therapy entry
- Prescription time selection
- Scope selection (Internal/External)
- Create, Edit, Cancel, Resume operations

**API Endpoints:**
- `patient_prescriptions`: Returns patient's prescriptions with status_summary
- `allocate_prescription`: Creates new prescription allocation
- `update_prescription`: Updates existing allocation
- `cancel_prescription`: Cancels prescription for date range
- `resume_prescription`: Resumes cancelled prescription for date range

---

## 7. Therapist Management

### 7.1 Therapist Models

#### 7.1.1 TherapistMaster (`masters/models.py`)
```python
class TherapistMaster(models.Model):
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, null=True, blank=True)
    therapist_profile = models.ForeignKey(TherapistProfile, on_delete=models.CASCADE, null=True, blank=True)
    therapist_code = models.CharField(max_length=20, unique=True)
    therapist_name = models.CharField(max_length=255)
    therapist_grade = models.ForeignKey(TherapistGrade, on_delete=models.PROTECT, null=True, blank=True)
    employee_code = models.CharField(max_length=50, unique=True)
    is_bathing_therapist = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
```

**Purpose:** Primary therapist master data (replaces legacy Patient.Therapist)

#### 7.1.2 TherapistGrade (`masters/models.py`)
```python
class TherapistGrade(models.Model):
    name = models.CharField(max_length=50, unique=True)  # e.g., "Senior", "Junior"
    display_name = models.CharField(max_length=100)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
```

#### 7.1.3 TherapistLeaveMaster (`masters/models.py`)
```python
class TherapistLeaveMaster(models.Model):
    therapist = models.ForeignKey(TherapistMaster, on_delete=models.CASCADE)
    week_start_date = models.DateField()
    monday = models.BooleanField(default=True)
    tuesday = models.BooleanField(default=True)
    # ... other days
    is_active = models.BooleanField(default=True)
```

**Purpose:** Weekly leave management for therapists

#### 7.1.4 EmergencyLeave (`masters/models.py`)
```python
class EmergencyLeave(models.Model):
    employee_code = models.CharField(max_length=50)
    leave_date = models.DateField()
    leave_type = models.CharField(max_length=50)
    synced_at = models.DateTimeField(auto_now_add=True)
```

**Purpose:** Emergency leave records synced from HRMS API

### 7.2 Therapist Views

#### 7.2.1 Therapist Master Management (`masters/views.py`)

**`TherapistMasterManagementView`**
- Lists all therapists
- CRUD operations
- Excel export
- URL: `/Masters/therapists/`

#### 7.2.2 Therapist Dashboard (`Sheduling/therapist_views.py`)

**`therapist_dashboard(request)`**
- Shows therapist's assigned sessions
- Daily schedule view
- URL: `/sheduling/therapist/`

#### 7.2.3 Therapist Schedule (`authentication/views.py`)

**`therapist_schedule(request)`**
- Tomorrow's schedule for therapist
- URL: `/authentication/therapist_schedule/`

---

## 8. Master Tables Management

### 8.1 Master Models

#### 8.1.1 TherapyMaster (`masters/models.py`)
```python
class TherapyMaster(models.Model):
    therapy_code = models.CharField(max_length=20, unique=True)
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
    is_active = models.BooleanField(default=True)
```

**Purpose:** Master list of all available therapies

#### 8.1.2 ItemMaster (`masters/models.py`)
```python
class ItemMaster(models.Model):
    item_code = models.CharField(max_length=20, unique=True)
    item_name = models.CharField(max_length=255)
    item_category = models.CharField(max_length=100, null=True, blank=True)
    unit_of_measure = models.CharField(max_length=50, null=True, blank=True)
    is_active = models.BooleanField(default=True)
```

**Purpose:** Master list of items used in therapies and prescriptions

#### 8.1.3 SlotMaster (`masters/models.py`)
```python
class SlotMaster(models.Model):
    slot_code = models.CharField(max_length=20, unique=True)
    slot_name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
```

**Purpose:** Master list of time slots for scheduling

#### 8.1.4 Other Master Models

- **Procured:** Procurement sources (IP Pharmacy, Kashaya room, etc.)
- **OilClass:** Oil categories
- **UsageType:** Usage types for items
- **PrescriptionUsage:** Prescription usage types
- **PrescriptionTime:** Prescription time slots
- **PrescriptionScope:** Prescription scopes (Internal/External)
- **UnitNo:** Unit names
- **IngredientMaster:** Ingredient master data
- **TreatmentRoom:** Treatment room master
- **NurseMaster:** Nurse master data
- **NurseTreatmentMaster:** Nurse treatment master

### 8.2 Master Management Views

#### 8.2.1 Master Management Dashboard (`masters/views.py`)

**`master_management_dashboard(request)`**
- Central dashboard for all master tables
- Shows counts and active counts for each master
- Quick links to manage each master
- URL: `/Masters/dashboard/`

#### 8.2.2 Individual Master Management

Each master has:
- **ListView:** Lists all records with pagination
- **CreateView:** Creates new records
- **UpdateView:** Updates existing records
- **Delete/Enable/Disable:** Status management

**URL Patterns:**
- Therapy Master: `/Masters/therapy/`
- Item Master: `/Masters/items/`
- Slot Master: `/Masters/slots/`
- Therapist Master: `/Masters/therapists/`
- Procurement Sources: `/Masters/procured`
- Oil Classes: `/Masters/oils/`
- Usage Types: `/Masters/usages/`
- Prescription Usage: `/Masters/prescription-usages/`
- Prescription Times: `/Masters/times/`
- Prescription Scopes: `/Masters/prescopes/`
- Units: `/Masters/units/`
- Ingredients: `/Masters/ingredients/`
- Treatment Rooms: `/Masters/treatment-rooms/`
- Nurse Master: `/Masters/nurses/`
- Nurse Treatments: `/Masters/nurse-treatments/`

---

## 9. Scheduling System

### 9.1 Scheduling Models

#### 9.1.1 RoomBooking (`Patient/models.py`)
```python
class RoomBooking(models.Model):
    booking = models.ForeignKey('Sheduling.Booking', on_delete=models.CASCADE)
    room = models.ForeignKey(TreatmentRoom, on_delete=models.CASCADE)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    booked_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
```

#### 9.1.2 TherapistBooking (`Patient/models.py`)
```python
class TherapistBooking(models.Model):
    booking = models.ForeignKey('Sheduling.Booking', on_delete=models.CASCADE)
    therapist = models.ForeignKey('masters.TherapistMaster', on_delete=models.CASCADE)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    booked_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
```

### 9.2 Scheduling Views

#### 9.2.1 Scheduling Dashboard (`Sheduling/views.py`)

**`scheduling_dashboard(request)`**
- Main scheduling interface
- Shows all therapies ready for scheduling
- Allows bulk scheduling operations
- URL: `/sheduling/scheduling/`

#### 9.2.2 Prescription Scheduling (`Sheduling/prescription_views.py`)

**`prescription_scheduling_dashboard(request)`**
- Prescription scheduling interface
- Shows all prescriptions ready for scheduling
- URL: `/sheduling/prescription-scheduling/`

#### 9.2.3 Therapist Availability (`Sheduling/availability_views.py`)

**`therapist_availability_dashboard(request)`**
- Shows therapist availability
- Leave management
- URL: `/sheduling/therapist-availability/`

---

## 10. Views and API Endpoints

### 10.1 Authentication Views

| View Function | URL | Purpose | Access |
|--------------|-----|---------|--------|
| `login_view` | `/authentication/login/` | User login | Public |
| `logout_view` | `/authentication/logout/` | User logout | Authenticated |
| `Manage_user` | `/authentication/Manage_user/dashboard/` | User management | Super Admin |
| `role_management` | `/authentication/role-management/` | Role management | Super Admin |
| `create_role` | `/authentication/create-role/` | Create role | Super Admin |
| `edit_role` | `/authentication/edit-role/<id>/` | Edit role | Super Admin |
| `delete_role` | `/authentication/delete-role/<id>/` | Delete role | Super Admin |
| `module_management` | `/authentication/module-management/` | Module management | Super Admin |
| `user_role_assignment` | `/authentication/user-role-assignment/` | Assign roles to users | Super Admin |
| `user_profile` | `/authentication/profile/` | User profile | Authenticated |

### 10.2 Therapy Views

| View Function | URL | Purpose | Access |
|--------------|-----|---------|--------|
| `therapy_entry` | `/sheduling/therapy-entry/` | Therapy allocation | Doctor, Scheduling Staff |
| `scheduling_dashboard` | `/sheduling/scheduling/` | Therapy scheduling | Scheduling Staff |
| `therapist_dashboard` | `/sheduling/therapist/` | Therapist schedule | Therapist |
| `patient_dashboard` | `/sheduling/patient/` | Patient dashboard | Patient |

### 10.3 Prescription Views

| View Function | URL | Purpose | Access |
|--------------|-----|---------|--------|
| `prescription_entry_page` | `/sheduling/prescriptions/` | Prescription allocation | Doctor, Scheduling Staff |
| `prescription_scheduling_dashboard` | `/sheduling/prescription-scheduling/` | Prescription scheduling | Scheduling Staff |

### 10.4 Master Views

| View Function | URL | Purpose | Access |
|--------------|-----|---------|--------|
| `master_management_dashboard` | `/Masters/dashboard/` | Master dashboard | Super Admin |
| `TherapyMasterManagementView` | `/Masters/therapy/` | Therapy master | Super Admin |
| `ItemMasterManagementView` | `/Masters/items/` | Item master | Super Admin |
| `SlotMasterManagementView` | `/Masters/slots/` | Slot master | Super Admin |
| `TherapistMasterManagementView` | `/Masters/therapists/` | Therapist master | Super Admin |
| `ProcuredManagementView` | `/Masters/procured` | Procurement sources | Super Admin |

### 10.5 API Endpoints

#### Therapy APIs (`Sheduling/views.py`)
- `patient_therapies`: GET - Returns patient's therapies with status_summary
- `allocate_therapy`: POST - Creates new therapy allocation
- `update_therapy`: POST - Updates existing therapy
- `cancel_therapy`: POST - Cancels therapy for date range
- `resume_therapy`: POST - Resumes cancelled therapy

#### Prescription APIs (`Sheduling/views.py`)
- `patient_prescriptions`: GET - Returns patient's prescriptions with status_summary
- `allocate_prescription`: POST - Creates new prescription allocation
- `update_prescription`: POST - Updates existing prescription
- `cancel_prescription`: POST - Cancels prescription for date range
- `resume_prescription`: POST - Resumes cancelled prescription

#### Master APIs (`masters/views.py`)
- `get_master_data`: GET - Returns master data by type
- `create_master_item`: POST - Creates master item
- `update_master_item`: PUT - Updates master item
- `delete_master_item`: DELETE - Deletes master item

---

## 11. Recent Fixes and Improvements

### 11.1 Role and Module Management Fixes

#### 11.1.1 Module Display Issue
**Problem:** Only 3 modules showing when multiple modules assigned to role

**Root Cause:** Navigation template filtered modules by keywords, missing modules that didn't match

**Solution:**
- Updated `get_accessible_modules()` to return all modules with proper ordering
- Added "All Modules" section in navigation to display all assigned modules
- Fixed module URL handling for namespaced and non-namespaced URLs

#### 11.1.2 Module Deletion Issue
**Problem:** Cannot delete modules used by roles

**Solution:**
- Updated `module_management` view to automatically remove modules from all roles before deletion
- Shows warning message about modules removed from roles

#### 11.1.3 Role Deletion Issue
**Problem:** Cannot delete roles with assigned users

**Solution:**
- Added confirmation page (`confirm_role_delete.html`)
- Force delete option removes role assignments from users before deletion
- Shows list of affected users

### 11.2 Therapy/Prescription Entry Fixes

#### 11.2.1 Resume Button Visibility
**Problem:** Resume button disappears after partial resume even when cancelled days remain

**Root Cause:** Frontend checked overall `status` instead of `status_summary.cancelled` count

**Solution:**
- Changed button visibility logic to check `status_summary.cancelled > 0`
- Reloads data from server after cancel/resume operations
- Updates `status_summary` locally as fallback

**Files Changed:**
- `templates/updated_dash/therapy_entry.html`
- `templates/updated_dash/prescription_entry.html`

#### 11.2.2 Patient Change During Edit
**Problem:** Changing patient during edit mode doesn't reload new patient's data

**Solution:**
- Added `editModePatientRegNo` to track patient when entering edit mode
- Detects patient change in `populatePatientInfo()`
- Resets form and clears edit mode when patient changes
- Prevents update if patient changed during edit

**Files Changed:**
- `templates/updated_dash/therapy_entry.html`
- `templates/updated_dash/prescription_entry.html`

### 11.3 User Management Fixes

#### 11.3.1 Therapist Code Field Not Showing
**Problem:** Therapist code field not visible when custom role with "therapist" in name is assigned

**Solution:**
- Updated JavaScript to check both `role` and `custom_role.name` for therapist detection
- Updated view logic to check `custom_role.name` when creating therapist profiles
- Applied same fix for patient registration field

**Files Changed:**
- `templates/dashboards/superadmin/Manage_user.html`
- `authentication/views.py`

### 11.4 Navigation Template Fixes

#### 11.4.1 URL Reverse Errors
**Problem:** `NoReverseMatch` errors for `procured_manage`, `patient_therapy`, etc.

**Solution:**
- Added special handling for master management URLs (use `/Masters/` prefix)
- Added special handling for sheduling URLs (use `/sheduling/` prefix)
- Fixed URL namespace handling in "All Modules" section

**Files Changed:**
- `templates/dashboards/nav.html`

### 11.5 Template Fixes

#### 11.5.1 Confirm Role Delete Template
**Problem:** `TemplateDoesNotExist` for `dashboards/base.html`

**Solution:**
- Changed from extending base template to standalone HTML
- Includes navigation using `{% include 'dashboards/nav.html' %}`
- Matches structure of other authentication templates

**Files Changed:**
- `templates/authentication/confirm_role_delete.html`

---

## 12. Best Practices and Guidelines

### 12.1 Role and Module Management

1. **Creating Roles:**
   - Use descriptive names (e.g., "scheduling_staff", "doctor_admin")
   - Assign relevant modules only
   - Set `is_active=True` for active roles

2. **Creating Modules:**
   - Use unique `name` (lowercase, underscores)
   - Set correct `url_name` (with namespace if needed)
   - Set appropriate `order` for display
   - Keep `is_active=True` for available modules

3. **Assigning Roles to Users:**
   - Use `user_role_assignment` view
   - Can assign both default role and custom role
   - Custom role takes precedence for module access

### 12.2 Therapy/Prescription Management

1. **Creating Allocations:**
   - Always select patient first
   - Validate date ranges
   - Ensure items are from ItemMaster
   - Set appropriate therapist requirements

2. **Cancelling Allocations:**
   - Use date range for partial cancellation
   - Provide cancellation reason
   - System updates individual bookings

3. **Resuming Allocations:**
   - Only cancelled bookings can be resumed
   - Use date range for partial resume
   - System updates status to 'draft' or 'allocated'

### 12.3 Master Data Management

1. **Master Data Rules:**
   - Always use master tables (TherapyMaster, ItemMaster, etc.)
   - Keep `is_active=True` for active records
   - Don't delete, disable instead

2. **Therapist Master:**
   - Link to CustomUser and TherapistProfile
   - Set `employee_code` for HRMS integration
   - Set `is_bathing_therapist` flag correctly

3. **Therapy Master:**
   - Set therapist counts correctly
   - Set `bathing_required` and `treatment_room_required` flags
   - Keep therapy codes unique

### 12.4 Code Guidelines

1. **Model Naming:**
   - Use PascalCase for models
   - Use descriptive names
   - Add `__str__` methods

2. **View Naming:**
   - Use snake_case for functions
   - Use descriptive names
   - Add docstrings

3. **URL Naming:**
   - Use snake_case with hyphens in paths
   - Use descriptive names
   - Group related URLs

4. **Template Structure:**
   - Include navigation in all templates
   - Use Bootstrap 5 for styling
   - Follow existing template patterns

### 12.5 Security Guidelines

1. **Access Control:**
   - Use decorators: `@login_required`, `@super_admin_required`, `@module_access_required`
   - Check permissions in views
   - Validate user access to resources

2. **Data Validation:**
   - Validate all user inputs
   - Check unique constraints
   - Handle errors gracefully

3. **Audit Logging:**
   - Log important actions
   - Track user changes
   - Maintain audit trail

---

## 13. Common Issues and Troubleshooting

### 13.1 Module Not Showing in Navigation

**Symptoms:** Module assigned to role but not visible in navigation

**Solutions:**
1. Check `module.is_active = True`
2. Check `role.is_active = True`
3. Check `user.custom_role` is assigned correctly
4. Check "All Modules" section in navigation
5. Verify `module.url_name` is correct

### 13.2 User Cannot Access Module

**Symptoms:** User has module assigned but gets access denied

**Solutions:**
1. Check `get_accessible_modules()` returns the module
2. Verify decorator `@module_access_required` is used
3. Check user's role and custom_role assignment
4. Verify module is active

### 13.3 Resume Button Not Showing

**Symptoms:** Cancelled days exist but resume button not visible

**Solutions:**
1. Check `status_summary.cancelled > 0` in frontend
2. Verify API returns correct `status_summary`
3. Reload page to refresh data
4. Check browser console for errors

### 13.4 Therapist Code Field Not Showing

**Symptoms:** Therapist code field not visible when creating therapist user

**Solutions:**
1. Check role is "therapist" OR custom_role.name contains "therapist"
2. Verify JavaScript `toggleRoleSpecificFields()` is called
3. Check custom_role dropdown is selected correctly
4. Verify view logic checks custom_role.name

### 13.5 URL Reverse Errors

**Symptoms:** `NoReverseMatch` errors in templates

**Solutions:**
1. Check URL name exists in urls.py
2. Verify namespace is correct (e.g., "sheduling:patient_therapy")
3. Use direct paths for master URLs (e.g., "/Masters/procured")
4. Check "All Modules" section handles URL correctly

---

## 14. Database Schema Overview

### 14.1 Key Relationships

```
CustomUser
├── custom_role (ForeignKey → Role)
├── role (CharField - default role)
└── Profiles (OneToOne)
    ├── PatientProfile
    ├── TherapistProfile
    ├── DoctorProfile
    └── ...

Role
└── modules (ManyToMany → Module)

Module
└── (standalone, referenced by Role)

PatientSnapshot
└── allocations (ForeignKey → TherapyAllocation)

TherapyAllocation
├── patient (ForeignKey → PatientSnapshot)
├── timeslot (ForeignKey → SlotMaster)
├── room (ForeignKey → TreatmentRoom)
└── bookings (ForeignKey → Booking)

Booking
├── allocation (ForeignKey → TherapyAllocation)
├── booking_items (ForeignKey → BookingItem)
└── assignments (ForeignKey → BookingAssignment)

BookingAssignment
├── booking (ForeignKey → Booking)
└── therapist (ForeignKey → TherapistMaster)

TherapistMaster
├── user (ForeignKey → CustomUser)
├── therapist_profile (ForeignKey → TherapistProfile)
└── therapist_grade (ForeignKey → TherapistGrade)
```

### 14.2 Status Flow

**Therapy/Prescription Status Flow:**
```
draft → allocated → cancelled
                ↓
            (resume)
                ↓
            draft/allocated
```

**Booking Status Flow:**
```
draft → allocated → completed
        ↓
    cancelled
        ↓
    (resume)
        ↓
    draft/allocated
```

---

## 15. API Response Formats

### 15.1 Therapy API Responses

**GET /sheduling/api/patient-therapies/**
```json
{
    "status": "ok",
    "therapies": [
        {
            "allocation_id": 1,
            "therapy_code": "TH001",
            "therapy_name": "Abhyanga",
            "from_date": "2025-11-01",
            "to_date": "2025-11-05",
            "status": "allocated",
            "status_summary": {
                "draft": 0,
                "allocated": 3,
                "cancelled": 2,
                "failed": 0
            },
            "cancelled_date_from": "2025-11-03",
            "cancelled_date_to": "2025-11-04",
            "cancellation_reason": "Patient request"
        }
    ]
}
```

**POST /sheduling/api/allocate-therapy/**
```json
{
    "action": "allocate_therapy",
    "patient_reg_no": "PAT001",
    "therapy_code": "TH001",
    "from_date": "2025-11-01",
    "to_date": "2025-11-05",
    "items_groups": [...],
    ...
}
```

### 15.2 Prescription API Responses

Similar structure to therapy APIs with prescription-specific fields.

---

## 16. Migration Guide

### 16.1 Updating Existing System

1. **Backup Database:**
   ```bash
   python manage.py dumpdata > backup.json
   ```

2. **Run Migrations:**
   ```bash
   python manage.py migrate
   ```

3. **Create Modules:**
   - Use module management interface
   - Or use management commands

4. **Create Roles:**
   - Create roles with appropriate modules
   - Assign to users

5. **Test:**
   - Verify user access
   - Check navigation
   - Test all modules

### 16.2 Data Migration

If migrating from old role system:
1. Create Role objects for existing roles
2. Assign modules to roles
3. Update users to use custom_role
4. Remove old role fields (if applicable)

---

## 17. Testing Checklist

### 17.1 Role and Module Management
- [ ] Create new role
- [ ] Assign modules to role
- [ ] Assign role to user
- [ ] Verify modules appear in navigation
- [ ] Edit role and update modules
- [ ] Delete role (with and without users)
- [ ] Create new module
- [ ] Delete module (with and without roles)

### 17.2 Therapy Management
- [ ] Create therapy allocation
- [ ] Edit therapy allocation
- [ ] Cancel therapy (full and partial)
- [ ] Resume therapy (full and partial)
- [ ] Verify resume button visibility
- [ ] Change patient during edit
- [ ] Verify status_summary accuracy

### 17.3 Prescription Management
- [ ] Create prescription allocation
- [ ] Edit prescription allocation
- [ ] Cancel prescription (full and partial)
- [ ] Resume prescription (full and partial)
- [ ] Verify resume button visibility

### 17.4 User Management
- [ ] Create user with default role
- [ ] Create user with custom role
- [ ] Create therapist user (verify therapist code field)
- [ ] Create patient user (verify patient reg field)
- [ ] Edit user role
- [ ] Update therapist code
- [ ] Delete user

### 17.5 Master Management
- [ ] Create master records
- [ ] Update master records
- [ ] Delete master records
- [ ] Enable/disable master records
- [ ] Bulk upload master data

---

## 18. Support and Maintenance

### 18.1 Regular Maintenance Tasks

1. **Weekly:**
   - Review audit logs
   - Check for inactive users
   - Verify master data accuracy

2. **Monthly:**
   - Review role assignments
   - Check module usage
   - Update master data

3. **Quarterly:**
   - Review and clean up old data
   - Update documentation
   - Performance optimization

### 18.2 Monitoring

1. **Error Logs:**
   - Check Django error logs
   - Monitor API errors
   - Track user access issues

2. **Performance:**
   - Monitor database queries
   - Check page load times
   - Optimize slow queries

### 18.3 Backup Strategy

1. **Database Backups:**
   - Daily automated backups
   - Weekly full backups
   - Monthly archive backups

2. **Code Backups:**
   - Version control (Git)
   - Regular commits
   - Tag releases

---

## 19. Glossary

- **Allocation:** Header record for therapy or prescription (date range, items)
- **Booking:** Per-date record for therapy scheduling
- **Custom Role:** Role created by Super Admin with specific module assignments
- **Default Role:** Predefined system role (doctor, therapist, etc.)
- **Module:** Feature/page that can be assigned to roles
- **Master Data:** Reference data (therapies, items, therapists, etc.)
- **Status Summary:** Count of bookings by status (draft, allocated, cancelled, failed)
- **Therapy Allocation:** Therapy prescription for a patient over a date range
- **Prescription Allocation:** Prescription for a patient over a date range

---

## 20. Appendices

### 20.1 File Structure Reference

```
authentication/
├── models.py          # User, Role, Module, Profiles
├── views.py           # User management, Role/Module management
├── decorators.py      # Access control decorators
├── urls.py            # Authentication URLs
└── templates/
    └── authentication/
        ├── role_management.html
        ├── create_role.html
        ├── edit_role.html
        └── confirm_role_delete.html

Sheduling/
├── models.py          # TherapyAllocation, Booking, PrescriptionAllocation
├── views.py           # Therapy entry, scheduling
├── prescription_views.py  # Prescription entry, scheduling
├── therapist_views.py     # Therapist dashboard
└── templates/
    └── updated_dash/
        ├── therapy_entry.html
        └── prescription_entry.html

masters/
├── models.py          # All master tables
├── views.py           # Master management views
└── templates/
    └── masters/
        └── [master]_manage.html

Patient/
├── models.py          # PatientHistory, RoomBooking, TherapistBooking
└── views.py           # Patient views

templates/
└── dashboards/
    └── nav.html       # Main navigation template
```

### 20.2 URL Namespace Reference

- `authentication:` - Authentication app URLs
- `patient:` - Patient app URLs
- `sheduling:` - Scheduling app URLs (no namespace in main urls.py)
- Master URLs: Direct paths under `/Masters/`

### 20.3 Environment Variables

Key settings in `AVCRI/settings.py`:
- `DATABASES`: Database configuration
- `AUTH_USER_MODEL`: Custom user model
- `MEDIA_ROOT`: Media files location
- `STATIC_ROOT`: Static files location

---

**End of Documentation**

For questions or issues, contact the development team or refer to the codebase comments.

