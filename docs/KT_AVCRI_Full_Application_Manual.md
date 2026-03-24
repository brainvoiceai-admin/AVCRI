# AVCRI — Full Application Knowledge Transfer (Pages, Flows, Models)

**Audience:** Engineering, product, operations, support  
**Scope:** End-to-end **therapy** and **prescription** flows, **Sheduling** dashboards/APIs, **Patient** registration path, **Masters**, **Authentication** role surfaces, and **MySql_Data_pull** tools  
**Version:** 1.0 (March 2026)  

**Client handoff:** This Part II content is merged (with resource-allocation Part I) in **[`KT_AVCRI_Client_Handbook_Complete.md`](./KT_AVCRI_Client_Handbook_Complete.md)** and **`KT_AVCRI_Client_Handbook_Complete.html`** for Google Docs.  

**Related:** [`KT_Resource_Allocation_Conditions_and_Parameters.md`](./KT_Resource_Allocation_Conditions_and_Parameters.md) (rules and parameters), project root KT markdown files where present  

---

## 1. URL map (how the project is mounted)

| Mount path | Django app | Purpose |
|------------|------------|---------|
| `/` | `Patient` | Patient-facing home, legacy therapy/prescription wizard, sessions, APIs |
| `/sheduling/` | `Sheduling` | Primary scheduling UIs: therapy entry, prescription entry, scheduling board, procurement, dashboards |
| `/authentication/` | `authentication` | Login, role dashboards, user/role/module admin, patient search APIs |
| `/Masters/` | `masters` | Super-admin master CRUD (therapies, items, slots, therapists, rooms, prescription metadata) |
| `/therapy/` | `MySql_Data_pull` | Dev/ops: raw external DB table peek, registration search |
| `/admin/` | Django admin | Built-in admin |
| `/patient-history/` | `Patient` (root) | Alias for patient history API used by popups |

---

## 2. Therapy flow (conceptual)

1. **Patient identity** comes from **registration** data (often `MySql_Data_pull.Registration` on alias `therapy_db`) and/or **scheduling** `PatientSnapshot` after allocation.
2. **Prescribing therapies** happens either:
   - **Legacy path:** `Patient` views store rows in **session**, then `submit_all_data` writes **`Visit`**, **`store_Therapy`**, **`store_PrescriptionItem`** (and related) on the default DB / therapy DB per code paths in `Patient/views.py`, or  
   - **Scheduling path:** Staff use **`/sheduling/therapy-entry/`** (`therapy_entry` + `allocate_therapy`) which creates **`Sheduling.TherapyAllocation`**, per-day **`Booking`**, **`BookingItem`**, **`BookingAssignment`**, optional **`BookingNurseAssignment`**, notifications, audit rows.
3. **Final scheduling** (`final_schedule_api`, `final_allocation.py`) assigns **`Patient.TherapistBooking`** / **`Patient.RoomBooking`** (and links from scheduling bookings) according to masters and business rules documented in the resource-allocation KT doc.
4. **Operational views** (`/sheduling/therapist/`, `/sheduling/patient/`, availability pages) read scheduling + patient booking models for the day.

---

## 3. Prescription flow (conceptual)

1. **Prescription lines** originate from **`store_Prescription`** / **`store_PrescriptionItem`** (MySql_Data_pull) synced or entered via UI; scheduling mirrors allocations in **`PrescriptionAllocation`**, **`PrescriptionItem`**, **`PrescriptionScheduling`**, **`PrescriptionDispatch`**.
2. **`/sheduling/prescriptions/`** — list/update prescription scheduling state; JS talks to **`Sheduling/views.py`** prescription refresh/toggle endpoints (see `static/js/updated_dash_prescription_entry.js`).
3. **`/sheduling/prescription-scheduling/`** — board-style scheduling; APIs in **`prescription_views.py`** (`get_prescription_data_api`, `send_final_prescription_api`, change log, status updates).
4. **`/sheduling/procurement/`** — procurement marks dispatch; APIs in **`procurement_views.py`**.

---

## 4. Module: `Patient` (`/`)

Base namespace: `patient:` (see `AVCRI/urls.py`).

### 4.1 `GET /` — Home

- **View:** `home`  
- **Template:** `home.html`  
- **Role:** Entry / navigation hub for patient journey.  
- **Models:** None required for static home; downstream flows use session keys such as `patient_reg_no`.

### 4.2 `GET|POST /therapy/` — Legacy therapy entry

- **View:** `therapy_entry_view`  
- **Template:** `dashboards/prescriptions/therapy_entry.html` (same template family as scheduling therapy entry)  
- **Behaviour:**  
  - **GET:** Loads patient from `Registration` (`therapy_db`) using `session['patient_reg_no']`. If missing, redirects to `patient:patient_lookup` (URL is **commented out** in `Patient/urls.py` — operational sites should set session via another path or use Sheduling entry).  
  - **POST (JSON):** Accepts `therapy_data` rows; resolves optional slot strings against **`masters.SlotMaster`**; stores sanitized rows in **`session['therapy_rows_data']`**.  
- **Models:** `MySql_Data_pull.Registration`, `masters.ItemMaster` / `masters.SlotMaster` (read).

### 4.3 `GET /prescription/` — Legacy prescription entry

- **View:** `prescription_entry_view`  
- **Behaviour:** Currently **`redirect('prescription_entry')`** — same name as this route → **self-redirect risk**. Operational prescription UI is **`/sheduling/prescriptions/`** (`prescription_entry_page`).  
- **Models:** None (redirect only).

### 4.4 `POST /submit/` — Commit wizard data

- **View:** `submit_all_data`  
- **Behaviour:** Creates **`MySql_Data_pull.Visit`** and persists therapy/prescription structures from session into **`store_Therapy`**, **`store_TherapyItem`**, **`store_Prescription`**, **`store_PrescriptionItem`** (and related day rows) inside `transaction.atomic` — see `Patient/views.py` for full field mapping. Uses **`Patient.Repeated_Visitors`** for repeated-visitor flag.  
- **Models:** `Visit`, `store_*`, `Repeated_Visitors`, `Registration`.

### 4.5 Patient search & details APIs

| URL | View | Purpose | Models / DB |
|-----|------|---------|-------------|
| `GET /search-patients/` | `search_patients_api` | Autocomplete patients | `Registration` (therapy_db) |
| `GET /get-patient-details/` | `get_patient_details_api` | Detail payload | `Registration`, related |
| `GET /patient-history/` | `patient_history_api` | History for popups | `Patient.PatientHistory`, etc. |
| `GET /search-therapies/` | `search_therapies_api` | Therapy search by IP/OP | `masters.TherapyMaster`, fallback `Patient.TherapyDetails` |

### 4.6 `GET /patients/<visit_id>/sessions/` — Session management

- **View:** `PatientSessionsView` (TemplateView)  
- **Template:** `dashboards/prescriptions/patient_sessions.html`  
- **Role:** Lists/cancels/completes session-level bookings for a visit.  
- **Models:** `Visit`, `store_TherapyItem`, `TherapistBooking`, `RoomBooking` (per actions in views).

### 4.7 Session actions

- **`POST /session/cancel-multi/`** — `cancel_session_bookings`  
- **`POST /session/complete-multi/`** — `complete_session_bookings`  
- **Models:** Booking-related rows on default DB and therapy store.

### 4.8 Therapy / prescription item CRUD

| URL | View | Template | Models |
|-----|------|----------|--------|
| `…/therapy-item/<id>/update/` | `update_therapy_item` | `update_therapy_item.html` | `store_TherapyItem`, etc. |
| `…/therapy-item/<id>/cancel/` | `cancel_therapy_item` | — | Store + cancellations |
| `…/prescription-item/<id>/update/` | `update_prescription_item` | `update_prescription_item.html` | `store_PrescriptionItem` |
| `…/prescription-item/<id>/cancel/` | `cancel_prescription_item` | — | Store items |
| `…/prescription/<id>/add-item/` | `add_prescription_item` | `add_prescription_item.html` | `store_PrescriptionItem` |
| Add therapy item (path typo in urls: leading `/`) | `add_therapy_item` | `add_therapy_item.html` | `store_TherapyItem` |

### 4.9 Supporting JSON endpoints

- **`GET /available_slots/`**, **`/time_slots/`**, **`/unit_numbers/`** — slot/unit helpers; tie to **`SlotMaster`**, **`Patient.TimeSlot`**, **`masters.UnitNo`** depending on implementation in `Patient/views.py`.  
- **`GET /allocation-result/`** — `allocation_result_view` → `dashboards/doctorsAndHelpDesk/allocation_result.html` (post-allocation messaging).  
- **`GET /get-item-details/`** — item metadata for forms.

---

## 5. Module: `Sheduling` (`/sheduling/`)

### 5.1 Therapy entry

| URL | Name | View | Template | Functionality | Primary models |
|-----|------|------|----------|---------------|----------------|
| `GET/POST …/therapy-entry/` | `patient_therapy` | `therapy_entry` | `dashboards/prescriptions/therapy_entry.html` | Rich therapy capture for staff; builds payloads for allocation; uses masters context | `PatientSnapshot`, masters |
| `POST …/api/allocate_therapy/` | `allocate_therapy` | `allocate_therapy` | — (JSON) | Creates **`TherapyAllocation`**, **`Booking`**, items, assignments, audit; nurse vs normal paths | `TherapyAllocation`, `Booking`, `BookingItem`, `BookingAssignment`, `BookingNurseAssignment`, `PatientSnapshot`, `SlotMaster`, `TreatmentRoom`, `AuditLog`, `TherapyNotification` |

### 5.2 Prescription entry (scheduling app)

| URL | View | Template | Functionality | Models |
|-----|------|----------|---------------|--------|
| `GET …/prescriptions/` | `prescription_entry_page` | `dashboards/prescriptions/prescription_entry.html` | Lists prescriptions, ON/OFF scheduling toggle, refresh; uses `updated_dash_prescription_entry.js/css` | `PrescriptionAllocation`, store prescriptions, session/toggle state |

### 5.3 Therapy scheduling board

| URL | View | Template | APIs (same module) | Functionality | Models |
|-----|------|----------|-------------------|---------------|--------|
| `GET …/scheduling/` | `scheduling_dashboard` | `dashboards/scheduling/scheduling.html` | `schedule_therapies_api`, `final_schedule_api`, `get_therapy_data_api`, `final_schedule_status_api`, `reschedule_therapy_api`, `reschedule_all_failed_api`, `therapy_change_log_api` | Draft/final schedule, reschedule failed, change log, therapy grid data | `TherapyAllocation`, `Booking*`, `FinalScheduleRun`, `TherapistContinuityPlan`, `BookingRescheduleHistory`, etc. |

### 5.4 Continuity matrix

- **`GET …/scheduling/api/continuity-matrix/`** — `matrix_views.continuity_matrix_api` — data for therapist continuity planning.

### 5.5 Prescription scheduling

| URL | View | Template | Key APIs | Models |
|-----|------|----------|----------|--------|
| `GET …/prescription-scheduling/` | `prescription_scheduling_dashboard` | `dashboards/prescriptions/prescription_scheduling.html` | `get_prescription_data_api`, `get_prescription_details_api`, `send_final_prescription_api`, `get_change_log_api`, `update_prescription_status_api`, `get_previous_prescriptions_api`, `download_prescription_history_api` | `PrescriptionAllocation`, `PrescriptionScheduling`, `PrescriptionItem`, `PrescriptionChangeLog`, `PrescriptionFinalScheduleRun`, `PrescriptionDispatch` |

### 5.6 Procurement

| URL | View | Template | APIs | Models |
|-----|------|----------|------|--------|
| `GET …/procurement/` | `procurement_dashboard` | `dashboards/procurement/procurement_dashboard.html` | `get_procurement_prescriptions_api`, `mark_as_dispatched_api`, details/items/change-log | `PrescriptionDispatch`, allocations, items |

### 5.7 Patient dashboard (scheduling)

| URL | View | Template | APIs | Models |
|-----|------|----------|------|--------|
| `GET …/patient/` | `patient_dashboard` | `patient_dashboard.html` | `get_patient_data_api`, `get_patient_prescriptions_api` | Snapshots, bookings, prescription summaries |

### 5.8 Therapist dashboard & difficulty

| URL | View | Template | APIs | Models |
|-----|------|----------|------|--------|
| `GET …/therapist/` | `therapist_dashboard` | `dashboards/therapist/therapist_dashboard.html` | `get_therapist_data_api`, `get_therapist_sessions_by_date_api` | `TherapistMaster`, `BookingAssignment`, sessions |
| `GET …/therapist-difficulty/` | `therapist_difficulty_dashboard` | `dashboards/superadmin/therapist_difficulty_dashboard.html` | `get_therapist_difficulty_data` | Load / metrics models per view |

### 5.9 Availability

| URL | View | Template | APIs | Models |
|-----|------|----------|------|--------|
| `GET …/therapist-availability/` | `therapist_availability_dashboard` | `dashboards/therapist/therapist_availability.html` | `get_available_therapists_api`, `get_therapists_on_leave_api`, `get_time_slots_api` | `TherapistMaster`, `TherapistLeave` / masters leave, `SlotMaster` |
| `GET …/room-availability/` | `room_availability_dashboard` | `dashboards/room/room_availability.html` | `get_available_rooms_api`, `get_occupied_rooms_api`, time slots | `TreatmentRoom`, bookings, `Floor` |

### 5.10 User therapy entry

| URL | View | Template | Role |
|-----|------|----------|------|
| `GET …/user-therapy-entry/` | `user_therapy_entry_dashboard` | `dashboards/user_therapy_entry/user_therapy_entry.html` | Simplified therapy entry for designated users (same template reused in branching in `views.py`). |

### 5.11 Bulk Excel (testing / bulk load)

| URL | View | Template | Role |
|-----|------|----------|------|
| `GET|POST …/therapy-bulk-excel/` | `therapy_bulk_excel` | `dashboards/scheduling/therapy_bulk_excel.html` | Upload spreadsheet to create **`TherapyAllocation`** + **`Booking`** rows in bulk. |

---

## 6. Module: `authentication` (`/authentication/`)

### 6.1 Auth & profile

- **`GET|POST …/login/`** — `login_view` → `login.html`  
- **`GET …/logout/`** — `logout_view`  
- **`GET …/profile/`** — `user_profile` → `dashboards/account/user_profile.html`  

### 6.2 Role landing dashboards (each renders a hub template)

| URL | View | Template |
|-----|------|----------|
| `…/therapist/dashboard/` | `therapist_dashboard` | `dashboards/therapist/therapist_dashboard.html` |
| `…/scheduling_dashboard/dashboard/` | `scheduling_dashboard` | `dashboards/scheduling/scheduling_dashboard.html` |
| `…/doctor/dashboard/` | `doctor_dashboard` | `dashboards/doctorsAndHelpDesk/doctor_dashboard.html` |
| `…/gmhr/dashboard/` | `gm_hr_dashboard` | `dashboards/gm_hr/gm_hr_dashboard.html` |
| `…/Patient_dashboard/dashboard/` | `Patient_dashboard` | `dashboards/patient/Patient_dashboard.html` |
| `…/Manage_user/dashboard/` | `Manage_user` | `dashboards/superadmin/Manage_user.html` |
| `…/Audit_Log/dashboard/` | `Audit_Log` | `dashboards/superadmin/Audit_Log.html` |
| `…/Therapy_Audit_Log/dashboard/` | `Therapy_Audit_Log` | `dashboards/superadmin/Therapy_Audit_Log.html` |
| `…/view_patient_details/dashboard/` | `view_patient_details` | `dashboards/therapist/view_patient_details.html` |
| `…/therapist_feedback_form/dashboard/` | `therapist_feedback_form` | `dashboards/therapist/therapist_feedback_form.html` |
| `…/Therapy_Report/dashboard/` | `Therapy_Report` | `dashboards/reports/therapy_report.html` |
| `…/housekeepingdash/dashboard/` | `housekeepingdash` | `dashboards/Housekeeping Staff/housekeepingdash.html` |
| `…/Patient_feedback_review/dashboard/` | `Patient_feedback_review` | `dashboards/gm_hr/Patient_feedback_review.html` |
| `…/nurse_dash/dashboard/` | `nurse_dash` | `dashboards/Nurse/nurse_dash.html` |
| `…/ip_pharmacy/dashboard/` | `ip_pharmacy` | `dashboards/ip_pharmacy/ip_pharmacy.html` |
| `…/prescription_dash/dashboard/` | `prescription_dash` | `dashboards/prescriptions/prescription_dash.html` |
| `…/patient_profile/dashboard/` | `patient_profile` | `dashboards/patient/patient_profile.html` |

### 6.3 Admin & APIs

- **Role CRUD:** `role_management`, `create_role`, `edit_role`, `delete_role`, `toggle_role_status` — templates under `authentication/`.  
- **User–role assignment:** `user_role_assignment`  
- **Module & nav:** `module_management`, `nav_section_management`  
- **Therapist schedule:** `therapist_schedule` → `dashboards/therapist/therapist_schedule.html`  
- **Add therapy (autofill):** `add_therapy_with_autofill` (may render `therapy_entry` template with context)  
- **Patient search APIs:** `search_patients`, `search_patients_by_room`, `get_patient_details` — used by dashboards; respect **`is_patient_active`** filters on room search paths.  
- **Audit APIs:** `audit_log_api`, `therapy_audit_log_api`  
- **Role change:** `confirm_role_change`, `execute_role_change`  

**Models:** `authentication` app models for roles/modules/users; `authentication.AuditLog` (referenced from `masters` `_log_master_audit`).

---

## 7. Module: `masters` (`/Masters/`)

**Dashboard:** `GET /Masters/dashboard/` → `master_management_dashboard` → `masters/master_management_dashboard.html` (super admin). Links to each list view below.

### 7.1 Master list pages (typical pattern)

Each **manage** URL is a `ListView` with search/filters, paginate_by≈20, enable/disable/delete/update routes, and often bulk-upload metadata. Templates live under `masters/*.html`.

| Path (relative to `/Masters/`) | Route name | Model |
|--------------------------------|------------|--------|
| `therapy/` | `therapy_master_manage` | `TherapyMaster` |
| `therapy-groups/` | `therapy_group_manage` | `TherapyGroup` |
| `items/` | `item_master_manage` | `ItemMaster` |
| `item-groups/` | `item_group_manage` | `ItemGroup` |
| `slots/` | `slot_master_manage` | `SlotMaster` |
| `ingredients/` | `ingredient_master_manage` | `IngredientMaster` |
| `treatment-rooms/` | `treatment_room_master_manage` | `Patient.TreatmentRoom` |
| `therapists/` | `therapist_master_manage` | `TherapistMaster` (+ Excel export) |
| `therapist-grades/` | `therapistgrade_manage` | `TherapistGrade` |
| `nurse-treatments/` | `nursetreatment_manage` | `NurseTreatmentMaster` |
| `nurses/` | `nursemaster_manage` | `NurseMaster` |
| `procured` | `procured_manage` | `Procured` |
| `oils/` | `oilclass_manage` | `OilClass` |
| `usages/` | `usagetype_manage` | `UsageType` |
| `prescription-usages/` | `prescriptionusage_manage` | `PrescriptionUsage` |
| `times/` | `prestime_manage` | `PrescriptionTime` |
| `prescopes/` | `prescope_manage` | `PrescriptionScope` |
| `units/` | `unit_list` | `UnitNo` |
| `room-names/` | `roomname_manage` | `Patient.RoomName` |
| `floors/` | `floor_manage` | `Patient.Floor` |
| `bulk-upload/` | `bulk_upload_master` | Multi-type spreadsheet import |
| `download-template/<master_type>/` | `download_master_template` | Template files |

### 7.2 Master JSON APIs

- **`GET /Masters/api/master-data/?type=…`** — Dropdown payloads (`therapy`, `item`, `slot`, `therapist`, etc.).  
- **`POST /Masters/api/master-item/`** (super admin) — `create_master_item`  
- **PATCH/PUT `/Masters/api/master-item/<id>/`** — `update_master_item`  
- **DELETE `/Masters/api/master-item/<id>/delete/`** — `delete_master_item`  
- **Therapist REST** under `/Masters/api/therapist/` and therapist-leave endpoints.

---

## 8. Module: `MySql_Data_pull` (`/therapy/`)

| URL | View | Template | Functionality | Models |
|-----|------|----------|---------------|--------|
| `GET /therapy/therapy/` | `table_view` | `sql_data_test.html` | Pick a legacy table name; show first 10 rows from **`therapy_db`** | Keys in `TABLE_MODELS` in `views.py` (some model names may be legacy) |
| `GET|POST /therapy/registration-search/` | `registration_search` | `dashboards/pat_reg.html` | Search registration by number; list recent registrations | `Registration` |

**Important operational models (app `MySql_Data_pull`):** `Registration`, `Visit`, `store_Therapy`, `store_TherapyItem`, `store_TherapyItemDay`, `store_Prescription`, `store_PrescriptionItem`, `Prescription`, `Treatment`, `Scheduling`, etc. (see `models.py` for full list).

---

## 9. Cross-app model index (quick reference)

### `Sheduling.models`

`PatientSnapshot`, `TherapyAllocation`, `Booking`, `BookingItem`, `BookingAssignment`, `BookingNurseAssignment`, `TherapistContinuityPlan`, `CancellationRequest`, `NotificationQueue`, `TherapyNotification`, `AuditLog`, `AllocationChange`, `BookingRescheduleHistory`, `PrescriptionAllocation`, `PrescriptionNotification`, `PrescriptionChange`, `PrescriptionScheduling`, `PrescriptionChangeLog`, `PrescriptionItem`, `PrescriptionDispatch`, `FinalScheduleRun`, `PrescriptionFinalScheduleRun`.

### `Patient.models`

`Repeated_Visitors`, `Therapist`, `TherapyDetails`, `PatientHistory`, `DailyPatientCount`, `TherapistLeave`, `TimeSlot`, `RoomName`, `Floor`, `TreatmentRoom`, `RoomBooking`, `TherapistBooking`, `BookingCancellations`, `AllocationAttempt`.

### `masters.models`

`Procured`, `OilClass`, `UsageType`, `PrescriptionUsage`, `NurseTreatmentMaster`, `NurseMaster`, `PrescriptionTime`, `PrescriptionScope`, `UnitNo`, `TherapyGroup`, `TherapyMaster`, `ItemGroup`, `ItemMaster`, `SlotMaster`, `IngredientMaster`, `TherapistGrade`, `TherapistMaster`, `TherapistLeaveMaster`, `StayingRoom`, `EmergencyLeave`.

---

## 10. Front-end assets (high touch)

| Area | Files (under `static/`) |
|------|-------------------------|
| Scheduling grid / draft PDF | `js/scheduling.js`, scheduling templates |
| Prescription entry toggle & list | `js/updated_dash_prescription_entry.js`, `css/updated_dash_prescription_entry.css` |
| Therapy entry forms | Shared `therapy_entry.html` + app-specific JS |

---

## 11. Known gaps / code health notes (for maintainers)

- **`Patient`:** `patient_lookup` URL is commented but **`therapy_entry_view`** still redirects to it if session lacks `patient_reg_no`.  
- **`prescription_entry_view`** redirects to itself (`prescription_entry`); use **`/sheduling/prescriptions/`** for the live screen.  
- **`Patient/urls.py`:** `path('/patients/<visit_id>/add-therapy-item/'` has a leading slash typo — verify routing in your environment.

---

## 12. Where to read rules vs pages

- **Business rules, slot logic, Vasthi, nurse allocation, parameters:** [`KT_Resource_Allocation_Conditions_and_Parameters.md`](./KT_Resource_Allocation_Conditions_and_Parameters.md)  
- **This document:** **what pages exist**, **what they call**, and **which models** they touch at a high level.

When extending either KT doc, prefer linking to the **view function** and **template path** in the repo so future readers can jump straight from narrative to code.
