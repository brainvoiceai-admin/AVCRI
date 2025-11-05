# Model Analysis Report

## Executive Summary
This document provides a comprehensive analysis of all Django models in the AVCRI project, identifying their purposes, duplicates, and recommendations for removal.

---

## 1. AUTHENTICATION APP (`authentication/models.py`)

### Active Models (Keep):
- **CustomUser** - Extends Django's AbstractUser, core user authentication
- **Module** - Defines available modules in the system
- **Role** - User roles with module permissions
- **PatientProfile** - Profile for patient users (linked to CustomUser)
- **TherapistProfile** - Profile for therapist users (linked to CustomUser)
- **DoctorProfile** - Profile for doctor users
- **AdminProfile** - Profile for admin users
- **NurseProfile** - Profile for nurse users
- **StaffProfile** - Profile for other staff users

### Duplicate/Conflicting:
- **AuditLog** (in `authentication/models.py`) - ⚠️ **DUPLICATE**
  - Purpose: Tracks system audit logs
  - Conflict: There's also `AuditLog` in `Sheduling/models.py`
  - Usage: Used in `authentication/views.py` and `authentication/admin.py`
  - Recommendation: **Keep the one in `authentication`**, rename `Sheduling.AuditLog` to `TherapyAuditLog` or merge them

---

## 2. SHEDULING APP (`Sheduling/models.py`)

### Active Models (Keep):
- **PatientSnapshot** - Local patient data snapshot (pat_reg_no, pat_name, pat_age, etc.)
- **TherapyAllocation** - Header for therapy prescriptions (date range, therapy details)
- **Booking** - Per-date booking for therapies (one per allocation per date)
- **BookingItem** - Per-date, per-item row for procurement and completion
- **BookingAssignment** - Assigns therapists to bookings
- **CancellationRequest** - Cancellation requests for therapies
- **NotificationQueue** - Persistent queue for notifications
- **TherapyNotification** - Notifications for therapy-related actions
- **PrescriptionAllocation** - Header for prescription allocations
- **PrescriptionNotification** - Notifications for prescription actions
- **PrescriptionChange** - Change log for prescriptions
- **PrescriptionScheduling** - Per-date prescription scheduling status
- **PrescriptionChangeLog** - Change log for prescriptions
- **PrescriptionItem** - Individual prescription items
- **PrescriptionDispatch** - Tracks prescription dispatch to departments
- **FinalScheduleRun** - Marker for per-date final schedule runs

### Duplicate/Conflicting:
- **AuditLog** (in `Sheduling/models.py`) - ⚠️ **DUPLICATE**
  - Purpose: Tracks therapy-related audit logs
  - Conflict: There's also `AuditLog` in `authentication/models.py`
  - Usage: Used in `Sheduling/views.py` (imported as `AuditLog`, separate from `AuthAuditLog`)
  - Recommendation: **Rename to `TherapyAuditLog`** or merge with `authentication.AuditLog`

- **AllocationChange** - ⚠️ **POTENTIALLY UNUSED**
  - Purpose: Tracks changes to therapy allocations
  - Usage: Check if actively used in views
  - Recommendation: **Verify usage**, if unused, consider removing

---

## 3. PATIENT APP (`Patient/models.py`)

### Active Models (Keep):
- **Repeated_Visitors** - Tracks repeated visitors
- **PatientHistory** - Historical patient treatment data
- **DailyPatientCount** - For forecasting patient demand
- **TherapistLeave** - Weekly leave management for therapists
- **TimeSlot** - ⚠️ **LEGACY - Being replaced by SlotMaster**
- **TreatmentRoom** - Treatment room master data
- **RoomBooking** - Room booking records (links to Booking, TherapyAllocation)
- **TherapistBooking** - Therapist booking records (uses TherapistMaster, not Patient.Therapist)
- **BookingCancellations** - Audit log for booking cancellations
- **AllocationAttempt** - Tracks allocation attempt history

### Duplicate/Unused Models:
- **Therapist** (in `Patient/models.py`) - ⚠️ **DUPLICATE - Should be removed**
  - Purpose: Therapist master data
  - Conflict: Replaced by `masters.models.TherapistMaster`
  - Current Usage: 
    - `Sheduling/models.py` line 4: Imported
    - `Sheduling/views.py` lines 2111, 2420, 2783: Used
    - `Sheduling/therapist_views.py` line 14: Used
    - `Sheduling/patient_views.py` line 16: Used
    - `final_allocation.py` line 531: Used
    - `Patient/admin.py` line 2: Registered in admin
  - Recommendation: **Migrate all references to `TherapistMaster`**, then remove
  - Action Required: Update `BookingAssignment.therapist` FK in `Sheduling/models.py` line 153

- **TherapyDetails** (in `Patient/models.py`) - ⚠️ **DUPLICATE - Should be removed**
  - Purpose: Therapy master data
  - Conflict: Replaced by `masters.models.TherapyMaster`
  - Fields: Identical to `TherapyMaster` (therapy_code, therapy_name, therapist counts, etc.)
  - Current Usage:
    - `algorithm.py` lines 13, 39, 42: Used (legacy)
    - `Patient/views.py` lines 310, 314, 1440, 1447, 1449: Used
    - `Patient/admin.py` line 2: Registered in admin
  - Recommendation: **Migrate all references to `TherapyMaster`**, then remove

- **TimeSlot** (in `Patient/models.py`) - ⚠️ **LEGACY - Being replaced**
  - Purpose: Time slot master data
  - Conflict: Being replaced by `masters.models.SlotMaster`
  - Current Usage: Still used in `Sheduling/models.py` and `Patient/models.py` (RoomBooking, TherapistBooking reference it via imports)
  - Recommendation: **Migrate to `SlotMaster`**, then remove

---

## 4. MASTERS APP (`masters/models.py`)

### Active Models (Keep - These are the PRIMARY master tables):
- **Procured** - Procurement sources master
- **OilClass** - Oil categories/classes master
- **UsageType** - Usage types master
- **PrescriptionTime** - Prescription time slots master
- **PrescriptionScope** - Prescription scope (Ext/Int) master
- **UnitNo** - Unit names master
- **TherapyMaster** - ⭐ **PRIMARY therapy master** (replaces Patient.TherapyDetails)
- **ItemMaster** - ⭐ **PRIMARY item master** (replaces external DB)
- **SlotMaster** - ⭐ **PRIMARY slot master** (replaces Patient.TimeSlot)
- **TherapistMaster** - ⭐ **PRIMARY therapist master** (replaces Patient.Therapist)
- **TherapistLeaveMaster** - Weekly leave management for therapists
- **EmergencyLeave** - Emergency leave records from HRMS

---

## 5. PREDICTOR APP (`predictor/models.py`)

### Active Models (Keep):
- **Prediction** - Stores forecast predictions (daily/weekly/monthly)
- **ForecastRun** - Tracks forecast execution runs

---

## 6. MYSQL_DATA_PULL APP (`MySql_Data_pull/models.py`)

### Purpose: External SQL Server database models (READ-ONLY, managed=False)

### External Models (Keep - These are read-only references):
- **TherapistDeployment** - External therapist deployment data
- **Prescription** - External prescription data
- **OPMaster** - External OP master data
- **Registration** - External patient registration data
- **RoomMaster** - External room master data
- **TherapistDetails** - External therapist details (different from Patient.TherapistDetails)
- **TherapistMaster** - External therapist master (different from masters.TherapistMaster)
- **TRMaster** - External TR master
- **ItemMaster** - External item master (different from masters.ItemMaster)
- **TimeSlot_sql** - External slot master (different from Patient.TimeSlot)
- **Scheduling** - External scheduling data
- **Visit** - Visit records (managed by us, not external)
- **store_Therapy** - Stored therapy data (managed by us)
- **store_TherapyItem** - Stored therapy item data (managed by us)
- **store_TherapyItemDay** - Per-day therapy item data (managed by us)
- **store_Prescription** - Stored prescription data (managed by us)
- **store_PrescriptionItem** - Stored prescription item data (managed by us)

### Note on External Models:
- Models with `managed = False` are read-only references to external SQL Server
- Models without `managed = False` (Visit, store_*) are managed by Django

---

## 7. DUPLICATE MODELS SUMMARY

### High Priority Removals:

1. **Patient.Therapist** → Replace with **masters.TherapistMaster**
   - Status: Still referenced in `Sheduling/models.py`
   - Action: Update imports, then remove

2. **Patient.TherapyDetails** → Replace with **masters.TherapyMaster**
   - Status: Likely unused, verify
   - Action: Verify no references, then remove

3. **Patient.TimeSlot** → Replace with **masters.SlotMaster**
   - Status: Still referenced in multiple files
   - Action: Migrate references, then remove

### Medium Priority:

4. **Sheduling.AuditLog** vs **authentication.AuditLog**
   - Status: Both are used
   - Action: Rename `Sheduling.AuditLog` to `TherapyAuditLog` or merge

---

## 8. MODEL USAGE BY PURPOSE

### Patient Data:
- **Primary**: `Sheduling.PatientSnapshot` (local snapshot)
- **External Reference**: `MySql_Data_pull.Registration` (external DB)
- **User Profile**: `authentication.PatientProfile` (linked to CustomUser)

### Therapy Master Data:
- **Primary**: `masters.TherapyMaster` ⭐
- **Legacy**: `Patient.TherapyDetails` (REMOVE)

### Therapist Master Data:
- **Primary**: `masters.TherapistMaster` ⭐
- **Legacy**: `Patient.Therapist` (REMOVE)
- **External Reference**: `MySql_Data_pull.TherapistDetails` (external DB)

### Time Slot Master Data:
- **Primary**: `masters.SlotMaster` ⭐
- **Legacy**: `Patient.TimeSlot` (REMOVE)
- **External Reference**: `MySql_Data_pull.TimeSlot_sql` (external DB)

### Item Master Data:
- **Primary**: `masters.ItemMaster` ⭐
- **External Reference**: `MySql_Data_pull.ItemMaster` (external DB)

### Therapy Scheduling:
- **Header**: `Sheduling.TherapyAllocation`
- **Per-Date**: `Sheduling.Booking`
- **Per-Item**: `Sheduling.BookingItem`
- **Assignments**: `Sheduling.BookingAssignment`
- **Room Booking**: `Patient.RoomBooking` (links to Booking)
- **Therapist Booking**: `Patient.TherapistBooking` (uses TherapistMaster)

### Prescription Scheduling:
- **Header**: `Sheduling.PrescriptionAllocation`
- **Per-Date**: `Sheduling.PrescriptionScheduling`
- **Per-Item**: `Sheduling.PrescriptionItem`
- **Dispatch**: `Sheduling.PrescriptionDispatch`

### External Storage (Legacy):
- **Therapy**: `MySql_Data_pull.store_Therapy`
- **Therapy Items**: `MySql_Data_pull.store_TherapyItem`
- **Prescription**: `MySql_Data_pull.store_Prescription`
- **Prescription Items**: `MySql_Data_pull.store_PrescriptionItem`

---

## 9. RECOMMENDATIONS

### Immediate Actions:

1. **Remove `Patient.Therapist`**
   - **Files to update:**
     - `Sheduling/models.py` line 4: Remove `Therapist` from import, update `BookingAssignment.therapist` FK (line 153) to `masters.TherapistMaster`
     - `Sheduling/views.py` lines 2111, 2420, 2783: Replace `Patient.models.Therapist` with `masters.models.TherapistMaster`
     - `Sheduling/therapist_views.py` line 14: Replace import
     - `Sheduling/patient_views.py` line 16: Replace import
     - `final_allocation.py` line 531: Replace usage
     - `Patient/admin.py` line 2: Remove from admin registration
   - **Create migration** to remove model after updating references

2. **Remove `Patient.TherapyDetails`**
   - **Files to update:**
     - `algorithm.py` lines 13, 39, 42: Replace with `TherapyMaster`
     - `Patient/views.py` lines 310, 314, 1440, 1447, 1449: Replace with `TherapyMaster`
     - `Patient/admin.py` line 2: Remove from admin registration
   - **Create migration** to remove model after updating references

3. **Migrate `Patient.TimeSlot` to `masters.SlotMaster`**
   - Update `Sheduling/models.py` line 92: Change Booking.timeslot to FK to `masters.SlotMaster`
   - Update `Patient.models.py` RoomBooking and TherapistBooking to use `SlotMaster`
   - Migrate data, then remove `Patient.TimeSlot`

4. **Resolve AuditLog Duplicate**
   - Rename `Sheduling.AuditLog` to `TherapyAuditLog`
   - Update all references in `Sheduling/views.py`

### Long-term Actions:

5. **Consolidate External vs Internal Models**
   - Clearly document which models are read-only external references
   - Consider removing external models if not actively used

6. **Review store_* Models**
   - Verify if `MySql_Data_pull.store_*` models are still needed
   - Consider migrating to `Sheduling` models if applicable

---

## 10. MODEL DEPENDENCY CHECKLIST

Before removing any model, verify:

- [ ] No foreign key references in other models
- [ ] No imports in views, utils, or other code
- [ ] No admin registrations
- [ ] No migrations that depend on it
- [ ] Data migration completed (if needed)
- [ ] All references updated to new model

---

## 11. SUMMARY

**Total Models Analyzed**: ~50+ models

**Models to Remove**:
1. `Patient.Therapist` (replace with `masters.TherapistMaster`)
2. `Patient.TherapyDetails` (replace with `masters.TherapyMaster`)
3. `Patient.TimeSlot` (replace with `masters.SlotMaster`)

**Models to Rename/Consolidate**:
1. `Sheduling.AuditLog` → `TherapyAuditLog` (or merge with `authentication.AuditLog`)

**Primary Master Models** (use these):
- `masters.TherapyMaster`
- `masters.TherapistMaster`
- `masters.SlotMaster`
- `masters.ItemMaster`
- `masters.Procured`
- `masters.OilClass`
- `masters.UsageType`
- `masters.PrescriptionTime`
- `masters.PrescriptionScope`
- `masters.UnitNo`

---

**Generated**: 2025-11-03
**Last Updated**: 2025-11-03

