# AVCRI — Client Knowledge Transfer Handbook (Complete)

**Single document for stakeholders and delivery teams**  
**Audience:** Product owners, clinical and operations leads, client sponsors, engineering, support  
**Contents:** (1) Resource-allocation rules and parameters, (2) Application URLs, pages, modules, and data models  
**Version:** 1.0 — March 2026  

---

## How to use this file with Google Docs

1. **Recommended:** Upload **`KT_AVCRI_Client_Handbook_Complete.html`** (in the same `docs/` folder) to **Google Drive**, then right-click → **Open with → Google Docs**. Google converts it to an editable Doc you can share (you may tidy headings or table widths once).
2. **Alternative:** If you have **Pandoc** installed locally, run  
   `pandoc KT_AVCRI_Client_Handbook_Complete.md -o KT_AVCRI_Client_Handbook_Complete.docx`  
   then upload the **`.docx`** to Drive and **Open with → Google Docs**.
3. **Alternative:** Copy from this **`.md`** into a blank Google Doc (tables may need touch-up).
4. **Regenerate HTML** after editing this markdown:  
   `pip install markdown` then `python docs/_md_to_html.py` (script lives in `docs/`).

---

## Table of contents

| Section | Topic |
|---------|--------|
| **1–15** | Resource allocation — conditions, parameters, lifecycle |
| **16** | URL map (where each part of the system lives) |
| **17–18** | Therapy and prescription flows (conceptual) |
| **19** | Patient module (`/` routes) |
| **20** | Scheduling module (`/sheduling/`) |
| **21** | Authentication module (`/authentication/`) |
| **22** | Masters module (`/Masters/`) |
| **23** | MySQL data tools (`/therapy/`) |
| **24** | Model index (quick reference) |
| **25–27** | Front-end assets, known gaps, references |

---

# Part I — Resource allocation: conditions and parameters

## 1. Executive summary

The application allocates **finite resources** (therapists by grade and gender, treatment rooms by slot, nurses for specific treatment types) to **patient therapies** and coordinates **medicine prescriptions** per patient and date. Behaviour is **parameter-driven** from **master data** (therapies, slots, grades, nurse-treatment definitions) and **hard-coded business rules** (IP/OP slot sets, Vasthi 08:30, Lepam slot exclusion, etc.).

**Two parallel domains:**

| Domain | Primary artefacts | Resource focus |
|--------|-------------------|----------------|
| **Therapy scheduling** | `TherapyAllocation`, `Booking`, `BookingAssignment`, `TherapistBooking`, `RoomBooking` | Therapists, rooms, time slots |
| **Prescription scheduling** | `PrescriptionAllocation`, `PrescriptionScheduling`, dispatches | Procurement / dispatch workflow per calendar day |

---

## 2. Stakeholder lens — what each group should know

| Stakeholder | Focus |
|-------------|--------|
| **Clinical / therapy leads** | Which therapies need rooms, bathing therapists, senior tagging, nurse-only flow; slot restrictions by therapy group and category. |
| **Operations / floor** | Draft vs scheduled vs failed bookings; patient “active” definition for lists; zero-therapist therapies may be hidden from some dashboards. |
| **Master data owners** | `TherapyMaster`, `TherapyGroup`, `SlotMaster`, `NurseTreatmentMaster`, therapist grades, room catalogue — incorrect masters directly change allocation outcomes. |
| **IT / integration** | External DBs (`therapy_db`, `iptherapy_db`, `hospital_db`) for registration, treatment, discharge; failures often **fail-open** (patient treated as active) to avoid blocking care. |
| **Engineering** | Core logic in `final_allocation.py`, `reshedule.py`, `allocation_logic.py`, `Sheduling/views.py`, `Patient/views.py`, `Sheduling/nurse_allocation.py`. |

---

## 3. Core parameters (master data)

### 3.1 Therapy master (`TherapyMaster` and related)

| Parameter | Effect on allocation |
|-----------|----------------------|
| **Therapy name / code** | Lookup key; normalized matching tolerates spacing/case variants. |
| **Therapy group** (e.g. name **“Vasthi”**, case-insensitive) | Triggers **08:30-only** scheduling rule (see section 4.2). |
| **Therapy code `THEB037`** (Mathra Vasthi) | **Exempt** from Vasthi 08:30-only rule. |
| **Category** (`easy` / `medium` / `hard` / `special`) | Drives **allowed slot sets** with IP/OP (see section 4.1). |
| **Counts:** `no_of_super_senior_therapist`, `no_of_senior_therapist`, `no_of_junior_therapist`, `no_of_trainee_therapist`, **`total_no_of_therapist`** | Required therapist mix per session; **zero total** therapies handled differently in UI lists vs unknown therapy fallbacks. |
| **`bathing_required` = Yes** | Pool restricted to **bathing-capable** therapists; special rules for Dhara/Pizhichil senior vs bathing (see section 5). |
| **`treatment_room_required` = Yes** | Room must be allocated; room free per date+slot; **unique constraint** on `(room, date, timeslot)` for bookings. |

### 3.2 Slot master (`SlotMaster`)

| Parameter | Effect |
|-----------|--------|
| **`slot_time`** (e.g. 08:30) | Canonical slot for bookings and `TherapistBooking` / `RoomBooking`. |
| **`is_active`** | Inactive slots are not used when resolving 08:30 or other fixed times. |

### 3.3 Nurse treatments (`NurseTreatmentMaster`)

| Parameter | Effect |
|-----------|--------|
| **`treatment_code` / name**, **`is_active`** | If matched, therapy is treated as **nurse treatment**: no therapist slot requirement in the same way; **nurse assignments** per booking/day (`BookingNurseAssignment`). |
| **Nurse count** (from master / allocation) | Drives how many nurses are attached; workload balancing across active nurses. |

### 3.4 Therapist master

| Parameter | Effect |
|-----------|--------|
| **Grade** (Super Senior / Senior / Junior / Trainee) | Must satisfy counts from therapy master; **trainee** requirements may be substituted with **junior** under rules in `reshedule.py`. |
| **`therapist_gender`** | Matched to **patient gender** (normalized: non-female → male preference path). |
| **`is_bathing_therapist` / bathing flag** | Required when therapy needs bathing. |
| **`employee_code`** | Used with **emergency leave** matching. |
| **Weekly leave** (`TherapistLeaveMaster` / `TherapistLeave` by weekday) | Therapist excluded for that weekday. |
| **Emergency leave** (`EmergencyLeave` date range) | Therapist excluded for overlapping dates. |

### 3.5 Rooms (`TreatmentRoom`)

| Parameter | Effect |
|-----------|--------|
| **Room number / floor / type** | Room selection and **patient staying-room** mapping (e.g. CT → TRC) in allocation logic. |
| **Booking uniqueness** | One booking per `(room, date, timeslot)` at DB level. |

---

## 4. Time-slot conditions

### 4.1 Patient type: IP vs OP

| Patient type | Default allowed slots (algorithm `get_allowed_slot_values`) |
|--------------|-------------------------------------------------------------|
| **OP** | `11:30`, `17:30` |
| **IP** | `06:30`, `08:30`, `10:00`, `14:30`, `16:00` |
| **Unspecified** | Full general list: `06:30`, `08:30`, `10:00`, `11:30`, `14:30`, `16:00`, `17:30` |

### 4.2 Therapy category interaction

| Category | Condition |
|----------|-----------|
| **`hard` or `special`** | **Removes** OP-only slots `11:30` and `17:30` from the **general** pool (stricter set). |
| **IP + `easy` or `medium`** | **Adds** `11:30` and `17:30` to IP allowed list (IP easy/medium may use OP-preferred slots). |

### 4.3 Named therapy restrictions

| Rule | Condition |
|------|-----------|
| **Lepam** | Name contains **“lepam”** (case-insensitive) → **`06:30` excluded** from allowed slots. |
| **Vasthi group** | Therapy linked to **`TherapyGroup.name`** normalised to **`vasthi`**, except code **`THEB037`** → **only `08:30`** allowed (allocation, reschedule, slot APIs, patient slot picker). |

### 4.4 Patient-facing slot availability (`compute_available_slots_for_date`)

Beyond allowed lists, each candidate slot is checked for:

- **Room:** if therapy needs room → at least one **free** `TreatmentRoom` for that date + `SlotMaster` (no `RoomBooking` with `status='BOOKED'` blocking all rooms).
- **Therapists:** exclude therapists on **weekday leave**; exclude **booked** at that slot (`TherapistBooking` `BOOKED`); if **bathing required** → filter to `is_bathing_therapist`; **grade counts** must be satisfiable from remaining pool.

**OP default candidate list** in this path: `11:30`, `17:30` (then category/Vasthi/Lepam filters apply).

---

## 5. Therapist allocation — key conditions

| Condition | Detail |
|-----------|--------|
| **Leave** | Weekly recurring leave + emergency leave (by therapist id or employee code). |
| **Already booked** | Same therapist cannot be double-booked at same date+slot (`TherapistBooking` / assignment uniqueness). |
| **Gender** | Therapist gender aligned with patient (normalization rules in `reshedule.allocate_therapists`). |
| **Senior tag therapies** | Fixed list of **Dhara / Thakradhara** variants (`is_treatment_requiring_senior_tag`) — **one** non-bathing senior tagged; bathing senior rules for multi-therapist Dhara/Pizhichil. |
| **Daily load / difficulty** | Category-aware balancing (easy/medium/hard counts per therapist day). |
| **Continuity** | `TherapistContinuityPlan` can pre-reserve therapists for date/slot/patient before final run. |
| **Unknown therapy in master** | Some code paths default to requiring **at least one** therapist to avoid “scheduled with zero therapists”; exact default can differ between `final_allocation` vs `reshedule` — treat master data as source of truth. |

---

## 6. Room allocation — key conditions

| Condition | Detail |
|-----------|--------|
| **Therapy needs room** | From master `treatment_room_required == Yes`. |
| **Free room** | No existing `RoomBooking` for same room+date+slot with `BOOKED` (and algorithm fallbacks). |
| **Patient context** | **Staying room** may map to preferred treatment room types (e.g. cottage CT → TRC). |
| **TRC exclusion** | Legacy paths may exclude `TRC*` prefixed rooms from certain fallbacks. |

---

## 7. Nurse allocation — key conditions

| Condition | Detail |
|-----------|--------|
| **Identification** | `is_nurse_treatment(therapy_code, therapy_name)` via `NurseTreatmentMaster`. |
| **Time slot** | Not slot-bound like therapists; **day-level** assignment. |
| **Nurse pool** | `NurseMaster.is_active=True`; round-robin / workload soft balancing. |
| **Uniqueness** | One row per `(nurse, booking)` for assigned status (see model constraints). |

---

## 8. Patient “active” and visibility

| Check | Source | Used for |
|-------|--------|----------|
| **IP active** | `Registration` (`therapy_db`): `pat_status == 'Y'` | `is_patient_active`, room search cross-checks, draft therapy list filtering. |
| **OP active** | `Treatment` (`iptherapy_db`): `Status == 'ON'` | Same helper; padded reg no variants tried. |
| **Room search (Treatment row)** | `Pat_DoD` null or ≥ today, `DOA` ≤ today | “In hospital” for room tab. |
| **Errors / DB down** | Helper often **fail-open → active** | Avoids blocking scheduling if SQL Server link fails. |

**Stakeholder note:** If external DB is unstable, logs may show ODBC errors; behaviour may **include** patients or **skip** checks unpredictably until connectivity is restored.

---

## 9. Booking and therapy allocation lifecycle (status vocabulary)

### 9.1 `TherapyAllocation.status`

`draft` → `allocated` → `cancelled` / `failed` (as implemented in workflows).

### 9.2 `Booking.status` (per day)

Examples used in code/comments: **`draft`**, **`scheduled`**, **`failed`**, **`cancelled`**, **`completed`**, partially cancelled variants.  
**`failure_reason`** stores machine-oriented reasons (e.g. insufficient therapists, slot issues).

### 9.3 `BookingItem.status`

`scheduled` / `cancelled` / `completed` — procurement and completion granularity.

### 9.4 Dashboard / API filters

- **Zero-therapist** non-nurse therapies may be **hidden** from **scheduled/failed** therapy lists (still may appear for **allocated/prescription** views).  
- **Draft** therapy list may **exclude inactive patients** using `is_patient_active`.

---

## 10. Prescription (medicine) scheduling — parameters

| Entity | Status / meaning |
|--------|------------------|
| **`PrescriptionAllocation`** | Header for a prescription period; `draft` / `active` / `cancelled` / `failed`; cancellation date ranges for partial OFF. |
| **`PrescriptionScheduling`** | Per **patient + calendar date**: `draft`, `scheduled`, `dispatched`, `cancelled`, `failed`, etc. |
| **Toggle OFF/ON** | Changes allocation + syncs scheduling rows by rules (not auto-cancelled from external discharge in current build — bulk discharge auto-cancel was **removed** from prescription refresh). |
| **Procurement** | `sent_to` / department routing from allocation metadata; final schedule run may flip days to `scheduled`. |

---

## 11. Hard constraints (integrity)

| Constraint | Business meaning |
|------------|-------------------|
| **Unique `(room, date, timeslot)` on `Booking`** | One concurrent booking per room per slot. |
| **Unique `(therapist, booking_date, booking_timeslot)` on `BookingAssignment`** | No double therapist assignment at same time. |
| **Nurse `(nurse, booking)` unique** | No duplicate nurse on same booking. |

---

## 12. External systems and databases

| Database (alias) | Typical content |
|------------------|-----------------|
| **`therapy_db`** | `Registration`, `Patient_Discharge`, etc. |
| **`iptherapy_db`** | `Treatment` (OP/IP therapy rows, room, DoD, status). |
| **`hospital_db`** | OP registration (`OPMaster`), etc. |
| **Django default DB** | Allocations, bookings, snapshots, masters, sessions. |

---

## 13. Operational parameters (for configuration discussions)

| Topic | Question for stakeholders |
|-------|---------------------------|
| **Slot grid** | Should general slots change (e.g. add 09:00)? Requires `SlotMaster` + code list sync in `get_allowed_slot_values` / patient UI. |
| **Vasthi rule** | Confirmed: **Therapy group name** `Vasthi` + **THEB037** exemption — any new Vasthi-like therapies must be grouped correctly in masters. |
| **Senior-tag list** | New Dhara variants require code update in `is_treatment_requiring_senior_tag`. |
| **Nurse treatments** | New nurse-only procedures must be added to `NurseTreatmentMaster`. |
| **SQLite vs production DB** | Dev `database is locked` / session errors: use proper DB for concurrent use. |

---

## 14. Traceability — main code anchors

| Topic | Primary modules |
|-------|-----------------|
| Slot rules | `reshedule.py` → `get_allowed_slot_values`, `is_group_vasthi_0830_only` |
| Patient slot API | `Patient/views.py` → `compute_available_slots_for_date` |
| Therapist assign | `reshedule.py` → `allocate_therapists`; `allocation_logic.py`; `final_allocation.py` |
| Room assign | `reshedule.py` → `allocate_treatment_room` |
| Nurse assign | `Sheduling/nurse_allocation.py` |
| Therapy create / API | `Sheduling/views.py` → `allocate_therapy`, `therapy_entry`, `get_therapy_data_api` |
| Patient active | `final_allocation.py` → `is_patient_active` |
| Room search API | `authentication/views.py` → `search_patients_by_room` |

---

## 15. Document maintenance (Part I)

- When **business rules change**, update **this handbook** and any separate engineering deep-dives in the repository if applicable.  
- For **algorithm step-by-step** (e.g. emergency leave reassignment), keep `RESCHEDULE_ALGORITHM_EXPLANATION.md` aligned in the codebase.

---

# Part II — Application structure: pages, flows, and models

## 16. URL map (how the project is mounted)

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

## 17. Therapy flow (conceptual)

1. **Patient identity** comes from **registration** data (often `MySql_Data_pull.Registration` on alias `therapy_db`) and/or **scheduling** `PatientSnapshot` after allocation.
2. **Prescribing therapies** happens either:
   - **Legacy path:** `Patient` views store rows in **session**, then `submit_all_data` writes **`Visit`**, **`store_Therapy`**, **`store_PrescriptionItem`** (and related) on the default DB / therapy DB per code paths in `Patient/views.py`, or  
   - **Scheduling path:** Staff use **`/sheduling/therapy-entry/`** (`therapy_entry` + `allocate_therapy`) which creates **`Sheduling.TherapyAllocation`**, per-day **`Booking`**, **`BookingItem`**, **`BookingAssignment`**, optional **`BookingNurseAssignment`**, notifications, audit rows.
3. **Final scheduling** (`final_schedule_api`, `final_allocation.py`) assigns **`Patient.TherapistBooking`** / **`Patient.RoomBooking`** (and links from scheduling bookings) according to masters and business rules in **Part I** of this handbook.
4. **Operational views** (`/sheduling/therapist/`, `/sheduling/patient/`, availability pages) read scheduling + patient booking models for the day.

---

## 18. Prescription flow (conceptual)

1. **Prescription lines** originate from **`store_Prescription`** / **`store_PrescriptionItem`** (MySql_Data_pull) synced or entered via UI; scheduling mirrors allocations in **`PrescriptionAllocation`**, **`PrescriptionItem`**, **`PrescriptionScheduling`**, **`PrescriptionDispatch`**.
2. **`/sheduling/prescriptions/`** — list/update prescription scheduling state; browser scripts call **`Sheduling/views.py`** prescription refresh/toggle endpoints (see `static/js/updated_dash_prescription_entry.js`).
3. **`/sheduling/prescription-scheduling/`** — board-style scheduling; APIs in **`prescription_views.py`** (`get_prescription_data_api`, `send_final_prescription_api`, change log, status updates).
4. **`/sheduling/procurement/`** — procurement marks dispatch; APIs in **`procurement_views.py`**.

---

## 19. Module: Patient (`/`)

Base namespace: `patient:` (see `AVCRI/urls.py`).

### 19.1 `GET /` — Home

- **View:** `home`  
- **Template:** `home.html`  
- **Role:** Entry / navigation hub for patient journey.  
- **Models:** None required for static home; downstream flows use session keys such as `patient_reg_no`.

### 19.2 `GET|POST /therapy/` — Legacy therapy entry

- **View:** `therapy_entry_view`  
- **Template:** `dashboards/prescriptions/therapy_entry.html` (same template family as scheduling therapy entry)  
- **Behaviour:**  
  - **GET:** Loads patient from `Registration` (`therapy_db`) using `session['patient_reg_no']`. If missing, redirects to `patient:patient_lookup` (URL is **commented out** in `Patient/urls.py` — operational sites should set session via another path or use Sheduling entry).  
  - **POST (JSON):** Accepts `therapy_data` rows; resolves optional slot strings against **`masters.SlotMaster`**; stores sanitized rows in **`session['therapy_rows_data']`**.  
- **Models:** `MySql_Data_pull.Registration`, `masters.ItemMaster` / `masters.SlotMaster` (read).

### 19.3 `GET /prescription/` — Legacy prescription entry

- **View:** `prescription_entry_view`  
- **Behaviour:** Currently **`redirect('prescription_entry')`** — same name as this route → **self-redirect risk**. Operational prescription UI is **`/sheduling/prescriptions/`** (`prescription_entry_page`).  
- **Models:** None (redirect only).

### 19.4 `POST /submit/` — Commit wizard data

- **View:** `submit_all_data`  
- **Behaviour:** Creates **`MySql_Data_pull.Visit`** and persists therapy/prescription structures from session into **`store_Therapy`**, **`store_TherapyItem`**, **`store_Prescription`**, **`store_PrescriptionItem`** (and related day rows) inside `transaction.atomic` — see `Patient/views.py` for full field mapping. Uses **`Patient.Repeated_Visitors`** for repeated-visitor flag.  
- **Models:** `Visit`, `store_*`, `Repeated_Visitors`, `Registration`.

### 19.5 Patient search and details APIs

| URL | View | Purpose | Models / DB |
|-----|------|---------|-------------|
| `GET /search-patients/` | `search_patients_api` | Autocomplete patients | `Registration` (therapy_db) |
| `GET /get-patient-details/` | `get_patient_details_api` | Detail payload | `Registration`, related |
| `GET /patient-history/` | `patient_history_api` | History for popups | `Patient.PatientHistory`, etc. |
| `GET /search-therapies/` | `search_therapies_api` | Therapy search by IP/OP | `masters.TherapyMaster`, fallback `Patient.TherapyDetails` |

### 19.6 `GET /patients/<visit_id>/sessions/` — Session management

- **View:** `PatientSessionsView` (TemplateView)  
- **Template:** `dashboards/prescriptions/patient_sessions.html`  
- **Role:** Lists/cancels/completes session-level bookings for a visit.  
- **Models:** `Visit`, `store_TherapyItem`, `TherapistBooking`, `RoomBooking` (per actions in views).

### 19.7 Session actions

- **`POST /session/cancel-multi/`** — `cancel_session_bookings`  
- **`POST /session/complete-multi/`** — `complete_session_bookings`  
- **Models:** Booking-related rows on default DB and therapy store.

### 19.8 Therapy / prescription item CRUD

| URL | View | Template | Models |
|-----|------|----------|--------|
| `…/therapy-item/<id>/update/` | `update_therapy_item` | `update_therapy_item.html` | `store_TherapyItem`, etc. |
| `…/therapy-item/<id>/cancel/` | `cancel_therapy_item` | — | Store + cancellations |
| `…/prescription-item/<id>/update/` | `update_prescription_item` | `update_prescription_item.html` | `store_PrescriptionItem` |
| `…/prescription-item/<id>/cancel/` | `cancel_prescription_item` | — | Store items |
| `…/prescription/<id>/add-item/` | `add_prescription_item` | `add_prescription_item.html` | `store_PrescriptionItem` |
| Add therapy item (path typo in urls: leading `/`) | `add_therapy_item` | `add_therapy_item.html` | `store_TherapyItem` |

### 19.9 Supporting JSON endpoints

- **`GET /available_slots/`**, **`/time_slots/`**, **`/unit_numbers/`** — slot/unit helpers; tie to **`SlotMaster`**, **`Patient.TimeSlot`**, **`masters.UnitNo`** depending on implementation in `Patient/views.py`.  
- **`GET /allocation-result/`** — `allocation_result_view` → `dashboards/doctorsAndHelpDesk/allocation_result.html` (post-allocation messaging).  
- **`GET /get-item-details/`** — item metadata for forms.

---

## 20. Module: Sheduling (`/sheduling/`)

### 20.1 Therapy entry

| URL | Name | View | Template | Functionality | Primary models |
|-----|------|------|----------|---------------|----------------|
| `GET/POST …/therapy-entry/` | `patient_therapy` | `therapy_entry` | `dashboards/prescriptions/therapy_entry.html` | Rich therapy capture for staff; builds payloads for allocation; uses masters context | `PatientSnapshot`, masters |
| `POST …/api/allocate_therapy/` | `allocate_therapy` | `allocate_therapy` | — (JSON) | Creates **`TherapyAllocation`**, **`Booking`**, items, assignments, audit; nurse vs normal paths | `TherapyAllocation`, `Booking`, `BookingItem`, `BookingAssignment`, `BookingNurseAssignment`, `PatientSnapshot`, `SlotMaster`, `TreatmentRoom`, `AuditLog`, `TherapyNotification` |

### 20.2 Prescription entry (scheduling app)

| URL | View | Template | Functionality | Models |
|-----|------|----------|---------------|--------|
| `GET …/prescriptions/` | `prescription_entry_page` | `dashboards/prescriptions/prescription_entry.html` | Lists prescriptions, ON/OFF scheduling toggle, refresh; uses `updated_dash_prescription_entry.js/css` | `PrescriptionAllocation`, store prescriptions, session/toggle state |

### 20.3 Therapy scheduling board

| URL | View | Template | APIs (same module) | Functionality | Models |
|-----|------|----------|-------------------|---------------|--------|
| `GET …/scheduling/` | `scheduling_dashboard` | `dashboards/scheduling/scheduling.html` | `schedule_therapies_api`, `final_schedule_api`, `get_therapy_data_api`, `final_schedule_status_api`, `reschedule_therapy_api`, `reschedule_all_failed_api`, `therapy_change_log_api` | Draft/final schedule, reschedule failed, change log, therapy grid data | `TherapyAllocation`, `Booking*`, `FinalScheduleRun`, `TherapistContinuityPlan`, `BookingRescheduleHistory`, etc. |

### 20.4 Continuity matrix

- **`GET …/scheduling/api/continuity-matrix/`** — `matrix_views.continuity_matrix_api` — data for therapist continuity planning.

### 20.5 Prescription scheduling

| URL | View | Template | Key APIs | Models |
|-----|------|----------|----------|--------|
| `GET …/prescription-scheduling/` | `prescription_scheduling_dashboard` | `dashboards/prescriptions/prescription_scheduling.html` | `get_prescription_data_api`, `get_prescription_details_api`, `send_final_prescription_api`, `get_change_log_api`, `update_prescription_status_api`, `get_previous_prescriptions_api`, `download_prescription_history_api` | `PrescriptionAllocation`, `PrescriptionScheduling`, `PrescriptionItem`, `PrescriptionChangeLog`, `PrescriptionFinalScheduleRun`, `PrescriptionDispatch` |

### 20.6 Procurement

| URL | View | Template | APIs | Models |
|-----|------|----------|------|--------|
| `GET …/procurement/` | `procurement_dashboard` | `dashboards/procurement/procurement_dashboard.html` | `get_procurement_prescriptions_api`, `mark_as_dispatched_api`, details/items/change-log | `PrescriptionDispatch`, allocations, items |

### 20.7 Patient dashboard (scheduling)

| URL | View | Template | APIs | Models |
|-----|------|----------|------|--------|
| `GET …/patient/` | `patient_dashboard` | `patient_dashboard.html` | `get_patient_data_api`, `get_patient_prescriptions_api` | Snapshots, bookings, prescription summaries |

### 20.8 Therapist dashboard and difficulty

| URL | View | Template | APIs | Models |
|-----|------|----------|------|--------|
| `GET …/therapist/` | `therapist_dashboard` | `dashboards/therapist/therapist_dashboard.html` | `get_therapist_data_api`, `get_therapist_sessions_by_date_api` | `TherapistMaster`, `BookingAssignment`, sessions |
| `GET …/therapist-difficulty/` | `therapist_difficulty_dashboard` | `dashboards/superadmin/therapist_difficulty_dashboard.html` | `get_therapist_difficulty_data` | Load / metrics models per view |

### 20.9 Availability

| URL | View | Template | APIs | Models |
|-----|------|----------|------|--------|
| `GET …/therapist-availability/` | `therapist_availability_dashboard` | `dashboards/therapist/therapist_availability.html` | `get_available_therapists_api`, `get_therapists_on_leave_api`, `get_time_slots_api` | `TherapistMaster`, `TherapistLeave` / masters leave, `SlotMaster` |
| `GET …/room-availability/` | `room_availability_dashboard` | `dashboards/room/room_availability.html` | `get_available_rooms_api`, `get_occupied_rooms_api`, time slots | `TreatmentRoom`, bookings, `Floor` |

### 20.10 User therapy entry

| URL | View | Template | Role |
|-----|------|----------|------|
| `GET …/user-therapy-entry/` | `user_therapy_entry_dashboard` | `dashboards/user_therapy_entry/user_therapy_entry.html` | Simplified therapy entry for designated users (same template reused in branching in `views.py`). |

### 20.11 Bulk Excel (testing / bulk load)

| URL | View | Template | Role |
|-----|------|----------|------|
| `GET|POST …/therapy-bulk-excel/` | `therapy_bulk_excel` | `dashboards/scheduling/therapy_bulk_excel.html` | Upload spreadsheet to create **`TherapyAllocation`** + **`Booking`** rows in bulk. |

---

## 21. Module: authentication (`/authentication/`)

### 21.1 Auth and profile

- **`GET|POST …/login/`** — `login_view` → `login.html`  
- **`GET …/logout/`** — `logout_view`  
- **`GET …/profile/`** — `user_profile` → `dashboards/account/user_profile.html`  

### 21.2 Role landing dashboards (each renders a hub template)

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

### 21.3 Admin and APIs

- **Role CRUD:** `role_management`, `create_role`, `edit_role`, `delete_role`, `toggle_role_status` — templates under `authentication/`.  
- **User–role assignment:** `user_role_assignment`  
- **Module and nav:** `module_management`, `nav_section_management`  
- **Therapist schedule:** `therapist_schedule` → `dashboards/therapist/therapist_schedule.html`  
- **Add therapy (autofill):** `add_therapy_with_autofill` (may render `therapy_entry` template with context)  
- **Patient search APIs:** `search_patients`, `search_patients_by_room`, `get_patient_details` — used by dashboards; respect **`is_patient_active`** filters on room search paths.  
- **Audit APIs:** `audit_log_api`, `therapy_audit_log_api`  
- **Role change:** `confirm_role_change`, `execute_role_change`  

**Models:** `authentication` app models for roles/modules/users; `authentication.AuditLog` (referenced from `masters` audit logging).

---

## 22. Module: masters (`/Masters/`)

**Dashboard:** `GET /Masters/dashboard/` → `master_management_dashboard` → `masters/master_management_dashboard.html` (super admin). Links to each list view below.

### 22.1 Master list pages (typical pattern)

Each **manage** URL is a list view with search/filters, pagination, enable/disable/delete/update routes, and often bulk-upload metadata. Templates live under `masters/*.html`.

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

### 22.2 Master JSON APIs

- **`GET /Masters/api/master-data/?type=…`** — Dropdown payloads (`therapy`, `item`, `slot`, `therapist`, etc.).  
- **`POST /Masters/api/master-item/`** (super admin) — `create_master_item`  
- **PATCH/PUT `/Masters/api/master-item/<id>/`** — `update_master_item`  
- **DELETE `/Masters/api/master-item/<id>/delete/`** — `delete_master_item`  
- **Therapist REST** under `/Masters/api/therapist/` and therapist-leave endpoints.

---

## 23. Module: MySql_Data_pull (`/therapy/`)

| URL | View | Template | Functionality | Models |
|-----|------|----------|---------------|--------|
| `GET /therapy/therapy/` | `table_view` | `sql_data_test.html` | Pick a legacy table name; show first 10 rows from **`therapy_db`** | Keys in `TABLE_MODELS` in `views.py` (some model names may be legacy) |
| `GET|POST /therapy/registration-search/` | `registration_search` | `dashboards/pat_reg.html` | Search registration by number; list recent registrations | `Registration` |

**Important operational models (app `MySql_Data_pull`):** `Registration`, `Visit`, `store_Therapy`, `store_TherapyItem`, `store_TherapyItemDay`, `store_Prescription`, `store_PrescriptionItem`, `Prescription`, `Treatment`, `Scheduling`, etc. (see `models.py` in the repository for the full list).

---

## 24. Cross-app model index (quick reference)

### Sheduling.models

`PatientSnapshot`, `TherapyAllocation`, `Booking`, `BookingItem`, `BookingAssignment`, `BookingNurseAssignment`, `TherapistContinuityPlan`, `CancellationRequest`, `NotificationQueue`, `TherapyNotification`, `AuditLog`, `AllocationChange`, `BookingRescheduleHistory`, `PrescriptionAllocation`, `PrescriptionNotification`, `PrescriptionChange`, `PrescriptionScheduling`, `PrescriptionChangeLog`, `PrescriptionItem`, `PrescriptionDispatch`, `FinalScheduleRun`, `PrescriptionFinalScheduleRun`.

### Patient.models

`Repeated_Visitors`, `Therapist`, `TherapyDetails`, `PatientHistory`, `DailyPatientCount`, `TherapistLeave`, `TimeSlot`, `RoomName`, `Floor`, `TreatmentRoom`, `RoomBooking`, `TherapistBooking`, `BookingCancellations`, `AllocationAttempt`.

### masters.models

`Procured`, `OilClass`, `UsageType`, `PrescriptionUsage`, `NurseTreatmentMaster`, `NurseMaster`, `PrescriptionTime`, `PrescriptionScope`, `UnitNo`, `TherapyGroup`, `TherapyMaster`, `ItemGroup`, `ItemMaster`, `SlotMaster`, `IngredientMaster`, `TherapistGrade`, `TherapistMaster`, `TherapistLeaveMaster`, `StayingRoom`, `EmergencyLeave`.

---

## 25. Front-end assets (high touch)

| Area | Files (under `static/` in the repository) |
|------|-------------------------------------------|
| Scheduling grid / draft PDF | `js/scheduling.js`, scheduling templates |
| Prescription entry toggle and list | `js/updated_dash_prescription_entry.js`, `css/updated_dash_prescription_entry.css` |
| Therapy entry forms | Shared `therapy_entry.html` + app-specific JS |

---

## 26. Known gaps / code health notes (for maintainers)

- **`Patient`:** `patient_lookup` URL is commented but **`therapy_entry_view`** still redirects to it if session lacks `patient_reg_no`.  
- **`prescription_entry_view`** redirects to itself (`prescription_entry`); use **`/sheduling/prescriptions/`** for the live screen.  
- **`Patient/urls.py`:** `path('/patients/<visit_id>/add-therapy-item/'` has a leading slash typo — verify routing in your environment.

---

## 27. Additional references in the repository

The following files in the AVCRI codebase may supplement this handbook for engineering depth: `COMPREHENSIVE_KT_DOCUMENTATION.md`, `RESCHEDULE_ALGORITHM_EXPLANATION.md`, `DHARA_PIZICHIL_RESCHEDULING_FIXES.md`.  

For day-to-day updates, prefer editing **`KT_AVCRI_Client_Handbook_Complete.md`** (this document) and regenerating the **`.docx`** if you use Word/Google Docs as the client-facing copy.

---

*End of AVCRI Client Knowledge Transfer Handbook (Complete)*
